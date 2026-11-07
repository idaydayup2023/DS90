#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ds90_ftp_walk 自检（代码运维 2026-11-07）。两层：

A 层：pyftpdlib 起真 FTP 服务，端到端验证「不漏不假空」——
      方括号目录(80件)、中文、空格、超长名、深嵌套、真空中、#recycle 排除。
B 层：注入 mock 连接，模拟 NAS 病态行为——
      ① 带参 MLSD/NLST 静默 0（断言库永不带参发）② LIST 假空+旁证打架→SUSPECT_EMPTY
      ③ 两旁证不可用的 0 也不当空 ④ 瞬态 550 新连接退避重试 ⑤ 持续 550→missing
      ⑥ RNFR 瞬态 550 重试 ⑦ NLST 绝对路径归一 ⑧ unknown 条目试探定性
      ⑨ jsonl 死活契约（逐行可解析、尾行 DONE、计数对上）。

跑法：tmp/_ftpwalk_venv/bin/python tools/ds90_ftp_walk_selftest.py
退出码 0=全过。输出建议 tee 到 logs/ 留证。
"""
import ftplib
import json
import os
import shutil
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ds90_ftp_walk import FtpWalker, norm_entry_name, ScanError  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


# ================================================================ A 层
def layer_a():
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer

    case = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ftpwalk_case")
    if os.path.isdir(case):
        shutil.rmtree(case)

    def mk(path, content="x"):
        full = os.path.join(case, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)

    expected = set()

    def expect(path):
        expected.add("/" + path.lstrip("/"))

    # ① 方括号组目录 80 件（站长点名案例）
    for i in range(1, 81):
        p = f"TV/[A.B.C] Show/Show.S01E{i:02d}.1080p.mkv"
        mk(p); expect(p)
    # ② 中文（目录名+文件名）
    for p in ["影视/甄嬛传 S01/甄嬛传.S01E01.中文.1080p.mkv",
              "影视/甄嬛传 S01/nfo 子目录/甄嬛传.nfo",
              "影视/长津湖.2021.国语音轨.flac"]:
        mk(p); expect(p)
    # ③ 空格
    p = "TV/With Space Dir/file name with space.mkv"
    mk(p); expect(p)
    # ④ 超长名（单段 ~200 字节）
    longseg = "Very.Long.Title." + "Segment." * 18 + "FIN"
    p = f"TV/{longseg}/{longseg}.mkv"
    mk(p); expect(p)
    # ⑤ 深嵌套 7 层
    deep = "/".join(f"L{i}_层目录" for i in range(1, 8))
    p = f"DEEP/{deep}/leaf.mkv"
    mk(p); expect(p)
    # ⑥ 真空中（应判 empty 而非 suspect）
    os.makedirs(os.path.join(case, "TV", "empty_dir"), exist_ok=True)
    # ⑦ #recycle 应被默认排除（放在遍历根 /TV 下面才测得出排除逻辑）
    p = "TV/#recycle/deleted_junk.mkv"
    mk(p)  # 不 expect —— 若被算进来说明排除失效

    authorizer = DummyAuthorizer()
    authorizer.add_user("t", "t1234", case, perm="elradfmwMT")
    handler = FTPHandler
    handler.authorizer = authorizer
    handler.encoding = "utf8"
    srv = FTPServer(("127.0.0.1", 0), handler)
    port = srv.address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        def factory():
            ftp = ftplib.FTP(timeout=30)
            ftp.encoding = "utf-8"
            ftp.connect("127.0.0.1", port)
            ftp.login("t", "t1234")
            ftp.set_pasv(True)
            return ftp

        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ftpwalk_a.jsonl")
        w = FtpWalker(factory=factory)
        done = w.walk(["/TV", "/影视", "/DEEP"], out, progress_every=0)

        found, last, bad_lines, n_dir = set(), None, 0, 0
        with open(out, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    bad_lines += 1
                    continue
                last = rec
                if rec.get("event") == "dir":
                    n_dir += 1
                    for fe in rec["entries"]["files"]:
                        found.add(rec["path"].rstrip("/") + "/" + fe["name"])
                elif rec.get("event") == "file":
                    found.add(rec["path"])

        check("A1 不漏：全部预期文件都被扫到", expected <= found,
              f"missing={sorted(expected - found)[:5]}")
        check("A2 不误报：扫出的文件都在预期内(排除#recycle生效)", found <= expected,
              f"extra={sorted(found - expected)[:5]}")
        check("A3 尾行 DONE 且计数对上", last and last.get("event") == "DONE"
              and last.get("dirs_seen") == n_dir, f"last={str(last)[:120]}")
        check("A4 jsonl 逐行可解析（fsync 契约）", bad_lines == 0, f"bad={bad_lines}")
        empty_rec_status = None
        with open(out, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("path") == "/TV/empty_dir":
                    empty_rec_status = rec.get("status")
        check("A5 真空中判 empty 不判 suspect", empty_rec_status == "empty"
              and not done["suspect_empty"],
              f"status={empty_rec_status} suspect={done['suspect_empty']}")
        check("A6 无 missing（中文/方括号/空格/超长/深嵌套全可达）", not done["missing"],
              f"missing={done['missing'][:5]}")
    finally:
        srv.close()


# ================================================================ B 层
class FakeFtp:
    """mock 连接：树 = {dir: {'dirs': set, 'files': {name: size}}}。"""

    def __init__(self, tree, server):
        self.tree, self.srv = tree, server
        self.cur = "/"
        self.calls = server.calls

    def _dir(self, p=None):
        p = self.cur if p is None else ("/" + p.lstrip("/") if p.startswith("/")
                                        else "/" + (self.cur.strip("/") + "/" + p).strip("/"))
        return p.rstrip("/") or "/"

    def cwd(self, p):
        key = self._dir(p)
        self.calls.append(("cwd", key, id(self)))
        if key not in self.tree:
            raise ftplib.error_perm("550 Operation not permitted")
        flaky = self.srv.flaky_cwd.get(key)
        if flaky is not None:
            self.srv.hits_cwd[key] = self.srv.hits_cwd.get(key, 0) + 1
            if self.srv.hits_cwd[key] <= flaky:
                raise ftplib.error_perm("550 transient")
        self.cur = key

    def retrlines(self, cmd, cb):
        assert cmd.strip() == "LIST", cmd  # 库只发无参 LIST
        d = self._dir()
        self.calls.append(("LIST", d, id(self)))
        if d in self.srv.blind_list:
            return
        ent = self.tree.get(d)
        if ent is None:
            raise ftplib.error_perm("550 nope")
        for n in sorted(ent["dirs"]):
            cb(f"drwxr-xr-x 1 u g 0 Nov  7 00:00 {n}")
        for n, s in sorted(ent["files"].items()):
            cb(f"-rw-r--r-- 1 u g {s} Nov  7 00:00 {n}")

    def mlsd(self, path=None, facts=()):
        d = self._dir(path)
        self.calls.append(("mlsd", d, path is not None, id(self)))
        if self.srv.mlsd_raises and d in self.srv.mlsd_raises:
            raise ftplib.error_perm("500 MLSD not implemented")
        if path is not None and "[" in path:  # NAS 坑：带参→静默 0
            return iter(())
        ent = self.tree.get(d, {"dirs": set(), "files": {}})
        out = [(n, {"type": "dir"}) for n in sorted(ent["dirs"])]
        out += [(n, {"type": "file", "size": str(s)}) for n, s in sorted(ent["files"].items())]
        return iter(out)

    def nlst(self, path=None):
        d = self._dir(path)
        self.calls.append(("nlst", d, path is not None, id(self)))
        if self.srv.nlst_raises and d in self.srv.nlst_raises:
            raise ftplib.error_perm("500 NLST broken")
        if path is not None and "[" in path:
            return []
        ent = self.tree.get(d, {"dirs": set(), "files": {}})
        names = sorted(ent["dirs"]) + sorted(ent["files"])
        if self.srv.nlst_absolute:  # 根级 NLST 实测回绝对路径
            return [("/" + d.strip("/") + "/" + n).replace("//", "/") if d != "/" else "/" + n
                    for n in names]
        return names

    def sendcmd(self, cmd):
        self.calls.append(("cmd", cmd, id(self)))
        verb, _, arg = cmd.partition(" ")
        if verb == "RNFR":
            self.srv.hits_rnfr += 1
            if self.srv.hits_rnfr <= self.srv.rnfr_fail_first:
                raise ftplib.error_perm("550 transient on RNFR")
            return "250 ok"
        if verb == "RNTO":
            self.srv.rnto_log.append(arg)
            return "250 ok"
        return "250 ok"

    def delete(self, p):
        self.calls.append(("dele", p, id(self)))

    def mkd(self, p):
        self.calls.append(("mkd", p, id(self)))
        return "257"

    def quit(self):
        pass

    def close(self):
        pass


class FakeServer:
    def __init__(self, tree):
        self.tree = tree
        self.calls = []
        self.blind_list = set()
        self.mlsd_raises = set()
        self.nlst_raises = set()
        self.flaky_cwd = {}
        self.hits_cwd = {}
        self.rnfr_fail_first = 0
        self.hits_rnfr = 0
        self.rnto_log = []
        self.nlst_absolute = False


def walker_for(srv, **kw):
    kw.setdefault("sleep", lambda s: None)  # mock 掉 sleep，退避不真等
    return FtpWalker(factory=lambda: FakeFtp(srv.tree, srv), **kw)


def layer_b():
    # B1 方括号目录 + corroborate=all：旁证被叫到但**永不带路径参数**
    tree = {"/": {"dirs": {"TV"}, "files": {}},
            "/TV": {"dirs": {"[A.B.C] Show"}, "files": {}},
            "/TV/[A.B.C] Show": {"dirs": set(), "files": {f"S{i}.mkv": i for i in range(3)}}}
    srv = FakeServer(tree)
    w = walker_for(srv)
    r = w.list_dir("/TV/[A.B.C] Show", corroborate="all")
    args_used = [c for c in srv.calls if c[0] in ("mlsd", "nlst") and len(c) > 2 and c[2]]
    check("B1 旁证永不带路径参数（带参静默0坑免疫）", not args_used and r["status"].startswith("ok"),
          f"calls={ [c[:3] for c in srv.calls if c[0] in ('mlsd','nlst')][:6] }")

    # B2 LIST 假空 + 无参 MLSD 有件 → suspect_empty 且条目来自旁证
    tree2 = {"/": {"dirs": {"blind"}, "files": {}},
             "/blind": {"dirs": set(), "files": {"a.mkv": 1, "b.nfo": 2}}}
    srv2 = FakeServer(tree2)
    srv2.blind_list.add("/blind")
    r = walker_for(srv2).list_dir("/blind")
    check("B2 LIST假空+旁证有件 → SUSPECT_EMPTY 且条目恢复",
          r["status"] == "suspect_empty" and sorted(f["name"] for f in r["entries"]["files"]) == ["a.mkv", "b.nfo"],
          f"status={r['status']}")

    # B3 LIST=0 且两旁证都不可用 → 也不当空（suspect_empty）
    srv3 = FakeServer(tree2)
    srv3.blind_list.add("/blind")
    srv3.mlsd_raises.add("/blind")
    srv3.nlst_raises.add("/blind")
    r = walker_for(srv3).list_dir("/blind")
    check("B3 两旁证不可用的0 → suspect_empty 不当空", r["status"] == "suspect_empty",
          f"status={r['status']}")

    # B4 真空中：LIST 0 + MLSD 0 → empty
    tree4 = {"/": {"dirs": {"empty_dir"}, "files": {}}, "/empty_dir": {"dirs": set(), "files": {}}}
    r = walker_for(FakeServer(tree4)).list_dir("/empty_dir")
    check("B4 真空中判 empty", r["status"] == "empty", f"status={r['status']}")

    # B5 瞬态 550：前 2 次 CWD 炸，第 3 次成——新连接+指数退避
    srv5 = FakeServer(tree2)
    srv5.flaky_cwd["/blind"] = 2
    slept = []
    w = walker_for(srv5, sleep=slept.append, retries=3)
    r = w.list_dir("/blind")
    conn_ids = {c[2] for c in srv5.calls if c[0] == "cwd"}
    check("B5 瞬态550退避后成功（新连接×3、退避1s,2s）",
          r["status"] == "ok" and len(conn_ids) == 3 and slept == [1.0, 2.0]
          and w.stats["retried_550"] == 2,
          f"status={r['status']} ids={len(conn_ids)} slept={slept}")

    # B6 持续 550 → missing（重试耗尽）
    srv6 = FakeServer(tree2)
    srv6.flaky_cwd["/blind"] = 99
    r = walker_for(srv6, retries=3).list_dir("/blind")
    check("B6 持续550 → missing 不无限重试", r["status"] == "missing", f"status={r['status']}")

    # B7 RNFR 瞬态 550 → 新连接重试成，RNFR/RNTO 成对
    srv7 = FakeServer(tree2)
    srv7.rnfr_fail_first = 1
    w7 = walker_for(srv7)
    w7.rename_with_retry("/blind/a.mkv", "/blind/a2.mkv")
    check("B7 RNFR瞬态550重试成（RNTO 落了）", srv7.rnto_log == ["/blind/a2.mkv"]
          and w7.stats["retried_550"] == 1, f"rnto={srv7.rnto_log}")

    # B8 NLST 绝对路径归一
    check("B8 NLST绝对路径归一回裸名",
          norm_entry_name("/TV/[A.B.C] Show", "/TV/[A.B.C] Show/x.mkv") == "x.mkv"
          and norm_entry_name("/", "/file.mkv") == "file.mkv", "")

    # B9 unknown 条目试探定性：NLST 全 unknown——目录续爬、文件不炸 missing
    tree9 = {"/": {"dirs": {"nlstonly"}, "files": {}},
             "/nlstonly": {"dirs": {"sub"}, "files": {"a.mkv": 1}},
             "/nlstonly/sub": {"dirs": set(), "files": {"deep.mkv": 2}}}
    srv9 = FakeServer(tree9)
    srv9.blind_list.add("/nlstonly")
    srv9.mlsd_raises.add("/nlstonly")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ftpwalk_b.jsonl")
    done = walker_for(srv9).walk(["/nlstonly"], out, progress_every=0)
    events = [json.loads(l) for l in open(out, encoding="utf-8")]
    paths = {e.get("path") for e in events if e.get("path")}
    sub_rec = next((e for e in events if e.get("path") == "/nlstonly/sub"
                    and e.get("event") == "dir"), None)
    sub_files = [f["name"] for f in (sub_rec or {}).get("entries", {}).get("files", [])]
    check("B9 unknown试探：目录续爬、文件不污染missing",
          done["missing"] == [] and sub_files == ["deep.mkv"]
          and any(e.get("event") == "file" and e.get("path") == "/nlstonly/a.mkv" for e in events),
          f"missing={done['missing']} sub_files={sub_files} paths={sorted(paths)}")

    # B10 jsonl 死活契约（B9 产物）：尾行 DONE、逐行 JSON、dirs_seen 对上
    dirs_n = sum(1 for e in events if e.get("event") == "dir")
    check("B10 jsonl契约：尾行DONE、逐行可解析、计数对上",
          events[-1]["event"] == "DONE" and events[-1]["dirs_seen"] == dirs_n,
          f"tail={events[-1].get('event')}")


if __name__ == "__main__":
    t0 = time.time()
    layer_a()
    layer_b()
    npass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n==== {npass}/{len(RESULTS)} PASS in {time.time()-t0:.1f}s ====")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAIL: {name} -- {detail}")
    sys.exit(0 if npass == len(RESULTS) else 1)
