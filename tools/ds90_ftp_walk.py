#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ds90_ftp_walk — 全队共用 FTP 列举/遍历库（代码运维 2026-11-07，站长派单）。

治的三个坑（都是 NAS 实测定性，各路别再自己踩）：
  ① 含方括号目录（/TV/[A.B.C] 这类）：`MLSD <绝对路径>` / `NLST <绝对路径>` 会被
     该 NAS **静默返回 0 条且不报错**，看着像空目录实际组内有件。
     → 本库一律 **CWD 进目录再发无参 LIST** 为准绳；绝不发带路径参数的
       MLSD/NLST（发了也只作旁证计数，见 ②）。
  ② 单姿势可能说谎：LIST 返 0 时自动换第二姿势（无参 MLSD，服务器不支持则
     无参 NLST）复验一次；两法不一致 → 标 **SUSPECT_EMPTY**，绝不当成空目录。
  ③ 中文/空格/方括号路径走 UTF-8（OPTS UTF8 ON best-effort）；CWD/RNFR/RNTO
     偶发瞬态 **550** → **新连接**指数退避重试（retries 次），持续 550 才报
     missing/error——防止把瞬态误判成目录不存在。

死活契约：扫描逐条结果 **fsync 落 jsonl**，成功收尾写尾行
  {"event": "DONE", ...}
判扫描死活**只认 DONE 行**（半截 jsonl = 死了/没跑完，别信计数）。

用法：
  # 遍历（只读），逐目录 fsync 落 jsonl + DONE 尾行
  python3 tools/ds90_ftp_walk.py --root "/TV/[A.B.C] Show" --out logs/walk.jsonl
  # 加严：每个目录 LIST/MLSD/NLST 三姿势全跑对照
  python3 tools/ds90_ftp_walk.py --root /TV --out logs/w.jsonl --corroborate all --depth 2
  # 代码内使用
  from ds90_ftp_walk import FtpWalker
  w = FtpWalker()                       # host/port/凭证默认取 DSH_FTP_* / DSH_SECRET_* env
  r = w.list_dir("/TV/[A.B.C] Show")    # {'status':'ok','entries':{...},'methods':{...}}
  w.walk(["/TV"], "out.jsonl")

 凭证：DSH_SECRET_SUBTRANS_FTP_USERNAME / _PASSWORD；入口 DSH_FTP_HOST(172.19.60.90)
       DSH_FTP_PORT(10021，明文 FTP PASV；60021 是 SFTP 假入口别用)。

 相关坑位备忘（11-05~11-07 全队实证，详见 tools/README_ftp_walk.md）：
   · 方括号路径带参 LIST/NLST/MLSD 静默返 0（本库三条治之，11-07 /TV/[A.B.C] 实证）。
   · 群晖 DSM 回收站 `<共享>/#recycle`：walk 默认排除，别把它当库内容数。
   · 中文路径列举有 DS 老 bug（10-30 铁律的由来）：新建任务/目录命名一律禁中文、
     用英文点号化；本库读存量中文路径走 UTF-8 无碍。
   · 中文路径 RNFR 偶发瞬态 550：新连接退避重试即成（rename_with_retry 内置）。
   · MOVIE-EXT **不是** FTP 共享：本库读不到它，去那边要用 SSH `/volume2/MOVIE-EXT`
     （见仓库 tools/ds90_ssh.sh 姿势）。
"""
from __future__ import annotations

import argparse
import ftplib
import json
import os
import posixpath
import sys
import time

# ---------------------------------------------------------------- helpers


def norm_entry_name(parent: str, entry: str) -> str:
    """把子目录列举可能返回的**绝对路径**归一回裸名（该 NAS 根级 NLST 实测给绝对路径）。"""
    if not entry.startswith("/"):
        return entry
    base = "/" + parent.strip("/")
    if base != "/" and entry.startswith(base.rstrip("/") + "/"):
        return entry[len(base) + 1:]
    # 服务器给了与 parent 不同根的怪值：能算相对就相对，否则退 basename 保底。
    try:
        rel = posixpath.relpath(entry, base)
    except ValueError:
        rel = posixpath.basename(entry)
    return rel if not rel.startswith("..") else posixpath.basename(entry)


def parse_list_line(line: str):
    """LIST 行 → (name, type, size|None)；认 Unix ls 与 MS-DOS 两种版式，兜底当裸名。"""
    if not line.strip():
        return None
    # Unix ls: perms links owner group size mon day time name...
    parts = line.split(None, 8)
    if len(parts) >= 9 and (parts[0][0] in "dl-pscptb" and len(parts[0]) >= 10):
        mode, size, name = parts[0], parts[4], parts[8]
        kind = "dir" if mode[0] == "d" else ("link" if mode[0] == "l" else "file")
        try:
            size_v = int(size)
        except ValueError:
            size_v = None
        return name, kind, size_v
    # MS-DOS: MM-DD-YY  HH:MMAM  <DIR>|size  name
    parts = line.split(None, 3)
    if len(parts) == 4 and "-" in parts[0] and (parts[2] == "<DIR>" or parts[2].isdigit()):
        name = parts[3]
        kind = "dir" if parts[2] == "<DIR>" else "file"
        size_v = None if parts[2] == "<DIR>" else int(parts[2])
        return name, kind, size_v
    # 兜底：有些服务器退化成裸名单行。
    return line.strip(), "unknown", None


def parse_mlsd_line(line: str):
    """MLSD 行 `type=file;size=1;modify=...; 名` → (name, type, size|None)。"""
    if ";" not in line:
        return None
    facts, name = line.rsplit(";", 1)
    name = name.strip()
    if not name:
        return None
    ftype, size_v = "unknown", None
    for fact in facts.split(";"):
        k, _, v = fact.partition("=")
        k = k.strip().lower()
        if k == "type":
            ftype = v.strip().lower() or "unknown"
        elif k == "size":
            try:
                size_v = int(v)
            except ValueError:
                pass
    return name, ftype, size_v


class ScanError(Exception):
    """操作最终失败（重试耗尽或非瞬态错误）。"""


# ---------------------------------------------------------------- walker


class FtpWalker:
    """单连接姿势的 FTP 列举/遍历。factory 注入假服务器可离线自测。"""

    def __init__(self, factory=None, host=None, port=None, user=None, password=None,
                 timeout=60, retries=3, backoff=1.0, sleep=time.sleep):
        if factory is None:
            host = host or os.environ.get("DSH_FTP_HOST", "172.19.60.90")
            port = port or int(os.environ.get("DSH_FTP_PORT", "10021"))
            user = user or os.environ["DSH_SECRET_SUBTRANS_FTP_USERNAME"]
            password = password or os.environ["DSH_SECRET_SUBTRANS_FTP_PASSWORD"]

            def factory():
                ftp = ftplib.FTP(timeout=timeout)
                ftp.encoding = "utf-8"
                ftp.connect(host, port)
                ftp.login(user, password)
                try:
                    ftp.voidcmd("OPTS UTF8 ON")
                except Exception:
                    pass  # 不支持 UTF8 opt 的服务器继续按 latin-1 走，中文路径会显式报错而非静默错名
                ftp.set_pasv(True)
                return ftp
        self._factory = factory
        self.retries = max(1, int(retries))
        self.backoff = float(backoff)
        self._sleep = sleep
        self.stats = {"connections": 0, "retried_550": 0}

    # -- 连接与瞬态 550 退避 -------------------------------------------------

    def _op(self, fn, retries=None):
        """每个动作都用**新连接**执行；550 视为瞬态 → 指数退避换新连接重试。"""
        attempts = retries if retries is not None else self.retries
        last = None
        for i in range(attempts):
            if i:
                self._sleep(self.backoff * (2 ** (i - 1)))
                self.stats["retried_550"] += 1
            conn = self._factory()
            self.stats["connections"] += 1
            try:
                return fn(conn)
            except ftplib.error_perm as e:
                if str(e).startswith("550"):
                    last = e
                    continue
                raise ScanError(str(e)) from e
            except (ftplib.error_temp, EOFError, TimeoutError, OSError) as e:
                # 传输层瞬断（421/425、控制/数据通道断流）同样按瞬态换新连接重试，
                # 重试预算耗尽才认输——NAS raw socket 瞬断史证。
                last = e
                continue
            finally:
                try:
                    conn.quit()
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
        raise ScanError(f"transient 550 persists after {attempts} fresh connections: {last}")

    # -- 单目录列举（核心姿势） ----------------------------------------------

    def _list_on_conn(self, conn, rel: str, corroborate: str) -> dict:
        try:
            conn.cwd(rel)
        except ftplib.error_perm as e:
            if str(e).startswith("550"):
                raise  # 交给 _op 的新连接退避重试；耗尽记 missing
            raise
        methods = {"list": None, "mlsd": None, "nlst": None}

        lines = []
        conn.retrlines("LIST", lines.append)
        parsed = [p for p in (parse_list_line(l) for l in lines) if p]
        methods["list"] = len(parsed)

        need_second = len(parsed) == 0 or corroborate == "all"

        def run_mlsd():
            out = []
            for name, attrs in conn.mlsd():  # 无参 MLSD：先 CWD 再发，绝不带路径参数
                if name in (".", ".."):
                    continue
                out.append((name, (attrs.get("type") or "unknown").lower(),
                            int(attrs["size"]) if attrs.get("size", "").isdigit() else None))
            return out

        def run_nlst():
            raw = conn.nlst()  # 无参 NLST
            return [(norm_entry_name(rel, n), "unknown", None) for n in raw if n not in (".", "..")]

        mlsd_out, nlst_out = [], []
        if need_second:
            try:
                mlsd_out = run_mlsd()
                methods["mlsd"] = len(mlsd_out)
            except Exception:
                try:
                    nlst_out = run_nlst()
                    methods["nlst"] = len(nlst_out)
                except Exception:
                    pass  # 两旁证全不可用：保持 None，由主法裁决
        elif corroborate == "facts":
            try:
                mlsd_out = run_mlsd()
                methods["mlsd"] = len(mlsd_out)
            except Exception:
                pass

        # 准绳 = LIST；LIST 为 0 时看旁证：打架 → suspect_empty；
        # 两旁证都**不可用**（None）时也不得当空——没复验过的 0 不可信，同样 suspect_empty。
        entries_src = parsed
        status = "ok"
        if len(parsed) == 0:
            second_n = max([n for n in (methods["mlsd"], methods["nlst"]) if n is not None] or [0])
            status = "empty" if second_n == 0 and any(
                m is not None for m in (methods["mlsd"], methods["nlst"])) else "suspect_empty"
            if mlsd_out:
                entries_src = mlsd_out
            elif nlst_out:
                entries_src = nlst_out
        elif corroborate in ("all", "facts") and methods["mlsd"] is not None and methods["mlsd"] != len(parsed):
            # 主法有件但旁证打架：仍 ok（LIST 为准），但计数留档供人看差异。
            status = "ok_methods_differ"

        # 类型只认 dir/pdir；unknown（裸名 LIST / NLST 旁证）单列，由 walk 用试探 CWD 定性，
        # 绝不盲目当目录递归（防 NLST 全 unknown 时把文件当目录炸出一堆 missing）。
        dirs = sorted(n for n, t, _ in entries_src if t in ("dir", "pdir"))
        files = sorted(({"name": n, "size": s} for n, t, s in entries_src if t not in ("dir", "pdir", "unknown")),
                       key=lambda e: e["name"])
        unknown = sorted(n for n, t, _ in entries_src if t == "unknown")
        return {"path": rel, "status": status, "methods": methods,
                "entries": {"dirs": dirs, "files": files, "unknown": unknown}}

    def list_dir(self, rel: str, corroborate: str = "lean", retries: int | None = None) -> dict:
        """列一个目录。corroborate: lean(默认，LIST=0 才复验) / all(三姿势全跑) / facts(LIST 有件也补 MLSD 尺寸)。"""
        def op(conn):
            return self._list_on_conn(conn, rel, corroborate)
        try:
            return self._op(op, retries=retries)
        except ScanError as e:
            return {"path": rel, "status": "missing", "error": str(e),
                    "methods": {"list": None, "mlsd": None, "nlst": None},
                    "entries": {"dirs": [], "files": [], "unknown": []}}

    # -- 整树遍历（fsync jsonl + DONE 尾行） ----------------------------------

    def walk(self, roots, out_path: str, exclude=("#recycle",), corroborate: str = "lean",
             depth: int | None = None, progress_every: int = 100) -> dict:
        """BFS 遍历；每目录一条 jsonl（fsync 落盘），成功收尾写 DONE 行。"""
        t0 = time.time()
        n_ok = n_empty = n_files = 0
        suspect, missing = [], []
        seen = 0
        with open(out_path, "w", encoding="utf-8") as out:

            def emit(rec: dict):
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                os.fsync(out.fileno())

            # (path, depth, maybe_file) —— maybe_file=True 的条目来自 NLST/裸名 LIST 的
            # unknown 类型：试探性 CWD 一次（retries=1），550 即归文件，不算 missing。
            stack = [(r.rstrip("/") or "/", 0, False) for r in roots]
            while stack:
                rel, d, maybe_file = stack.pop()
                if any(x in rel for x in exclude):
                    emit({"event": "skipped", "path": rel, "reason": "exclude"})
                    continue
                rec = self.list_dir(rel, corroborate=corroborate,
                                    retries=1 if maybe_file else None)
                if maybe_file and rec["status"] == "missing":
                    # 试探失败：它是文件不是目录。归文件计数，不污染 missing。
                    n_files += 1
                    emit({"event": "file", "path": rel, "size": None, "via": "unknown-probe"})
                    continue
                rec["event"] = "dir"
                emit(rec)
                seen += 1
                st = rec["status"]
                if st in ("ok", "ok_methods_differ"):
                    n_ok += 1
                    n_files += len(rec["entries"]["files"])
                elif st == "empty":
                    n_empty += 1
                elif st == "suspect_empty":
                    suspect.append(rel)
                else:
                    missing.append(rel)
                if progress_every and seen % progress_every == 0:
                    emit({"event": "progress", "seen": seen, "ok": n_ok,
                          "empty": n_empty, "suspect": len(suspect), "missing": len(missing)})
                if depth is not None and d >= depth:
                    continue
                for sub in rec["entries"]["dirs"]:
                    stack.append((posixpath.join(rel.rstrip("/"), sub) if rel != "/" else "/" + sub,
                                  d + 1, False))
                for sub in rec["entries"].get("unknown", []):
                    stack.append((posixpath.join(rel.rstrip("/"), sub) if rel != "/" else "/" + sub,
                                  d + 1, True))

            done = {"event": "DONE", "roots": list(roots), "dirs_seen": seen,
                    "dirs_ok": n_ok, "dirs_empty": n_empty, "files_total": n_files,
                    "suspect_empty": suspect, "missing": missing,
                    "connections": self.stats["connections"], "retried_550": self.stats["retried_550"],
                    "elapsed_s": round(time.time() - t0, 1)}
            emit(done)
        return done

    # -- 供各路复用的写姿势（瞬态 550 新连接退避） ----------------------------

    def rename_with_retry(self, src: str, dst: str) -> None:
        """RNFR/RNTO 成对动作，瞬态 550 → 新连接退避重试（库务实证 11-07）。"""
        def op(conn):
            conn.sendcmd("RNFR " + src)
            conn.sendcmd("RNTO " + dst)
            return True
        self._op(op)

    def delete_with_retry(self, path: str) -> None:
        def op(conn):
            conn.delete(path)
            return True
        self._op(op)

    def makedirs(self, rel: str) -> None:
        def op(conn):
            cur = ""
            for part in [p for p in rel.split("/") if p]:
                cur += "/" + part
                try:
                    conn.mkd(cur)
                except ftplib.error_perm as e:
                    if not str(e).startswith("550"):
                        raise
            return True
        self._op(op)


# ---------------------------------------------------------------- CLI


def main(argv=None):
    ap = argparse.ArgumentParser(description="FTP 列举/遍历共用库（CWD+无参 LIST 为准绳）")
    ap.add_argument("--root", action="append", required=True, help="遍历根，可多次")
    ap.add_argument("--out", required=True, help="jsonl 输出（逐条 fsync，尾行 DONE）")
    ap.add_argument("--host"), ap.add_argument("--port", type=int)
    ap.add_argument("--corroborate", choices=["lean", "all", "facts"], default="lean")
    ap.add_argument("--exclude", action="append", default=None, help="子串排除，可多次（默认含 #recycle）")
    ap.add_argument("--depth", type=int, default=None)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=60)
    a = ap.parse_args(argv)
    w = FtpWalker(host=a.host, port=a.port, retries=a.retries, timeout=a.timeout)
    done = w.walk(a.root, a.out,
                  exclude=tuple(a.exclude) if a.exclude else ("#recycle",),
                  corroborate=a.corroborate, depth=a.depth)
    print(json.dumps(done, ensure_ascii=False))
    return 0 if not done["missing"] else 2


if __name__ == "__main__":
    sys.exit(main())
