#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清单落库前 LIST 可达性预检（站长 11-08 第 2 单批准；代码运维·闸门治理器具，仅代码运维可改）。

缘起（11-08 实测缺陷）：扫描侧拼错目录名（`/X-TV/Grey's.Anatomy/Greys.Anatomy/S22`，
真目录为 `/X-TV/Greys.Anatomy/S22`）被写进读判清单，直到取件才暴雷——幽灵路径在清单
里静默存活。与 PR#17 修的群晖 MLSD 方括号空表同族：**列目录姿势与路径真实性都必须
对库实测，不得信生成侧**。

口径（fail-closed）：
  · 目录：CWD 进目录实测可达＝绿；不可达＝红——从最深可达祖先向下定位**断点成分**，
    对该成分的父目录清单给近邻候选（difflib + 撇号/空白变体），供人眼一秒定错位。
  · 文件：父目录可达 + basename 在 MLSD/LIST 清单内＝绿；缺席＝红（附文件近邻候选）。
  · 纯文本行不猜形：先按目录探，CWD 不中再按文件探（影视目录名满点是 .，禁止
    splitext 启发——首版教训）；JSON 清单按声明键（dir*/file*）信任其形。
  · 空表只警不红（预检只验存在性；「无残留」类空表禁过关归后验器具）。
  · 任一红＝退出码 2，清单不得落库。连接失败＝3。
--dry-selftest 用注入 lister 跑故障注入例，不连库。
"""
import argparse
import difflib
import ftplib
import json
import os
import sys

HOST, PORT = "172.19.60.90", 10021
U = os.environ.get("DSH_SECRET_SUBTRANS_FTP_USERNAME", "")
P = os.environ.get("DSH_SECRET_SUBTRANS_FTP_PASSWORD", "")

DIR_KEYS = ("dir", "directory", "lib_dir", "folder", "目录")
FILE_KEYS = ("file", "path", "file_path", "lib_path", "文件")


def conn():
    f = ftplib.FTP()
    f.connect(HOST, PORT, timeout=120)
    f.login(U, P)
    f.set_pasv(True)
    f.voidcmd("TYPE I")
    return f


def listing(d, f=None):
    """CWD 进目录再列（方括号坑定式，PR#17 同款）；MLSD 空退 LIST。
    返回 (files:set, dirs:set, empty:bool)。CWD 拒抛 error_perm。"""
    own = f is None
    if own:
        f = conn()
    try:
        f.cwd(d)
        dirs, files = set(), set()
        for name, facts in f.mlsd(""):
            t = dict(facts).get("type")
            if t == "dir":
                dirs.add(name)
            elif t == "file":
                files.add(name)
        if not dirs and not files:
            rows = []
            f.dir("", rows.append)
            for r in rows:
                parts = r.split()
                if len(parts) >= 9:
                    (dirs if parts[0][0] == "d" else files).add(parts[-1])
        return files, dirs, not (dirs or files)
    finally:
        if own:
            f.quit()


def variants(s):
    """常见拼错变体：撇号增删（' 与 ’）、连续空白归一、首尾空白。"""
    return {v for v in (s, s.strip(), s.replace("'", ""), s.replace("\u2019", ""),
                        " ".join(s.split())) if v}


def suggest(name, siblings):
    hit = [v for v in variants(name) if v in siblings]
    hit += difflib.get_close_matches(name, sorted(siblings), n=3, cutoff=0.6)
    return [c for c in dict.fromkeys(hit) if c != name][:3]


class Prober:
    def __init__(self, lister):
        self.lister = lister
        self.cache = {}

    def ls(self, d):
        if d not in self.cache:
            try:
                self.cache[d] = ("ok", self.lister(d))
            except Exception as e:  # noqa: BLE001 收口，红由判定层出
                self.cache[d] = ("fail", str(e))
        return self.cache[d]

    def deepest_ok(self, path):
        """自 path 向上找最深可达祖先（不含自身）。返回 (ok_anc 或 None)。"""
        cur = os.path.dirname(path.rstrip("/")) or "/"
        seen = 0
        while seen < 40:
            if cur == "" or cur == "\x00":
                break
            if self.ls(cur)[0] == "ok":
                return cur
            if cur == "/":
                return None
            cur = os.path.dirname(cur) or "/"
            seen += 1
        return None

    def missing_hop(self, path):
        """→ (ok_anc, missing_component, sib_dirs, sib_files)：从最深可达祖先向下的第一个断点。"""
        anc = self.deepest_ok(path)
        if anc is None:
            return None, path, set(), set()
        rest = os.path.relpath(path.rstrip("/"), anc)
        comp = rest.split(os.sep)[0] if rest not in (".", "") else ""
        st, payload = self.ls(anc)
        files, dirs = (payload[0], payload[1]) if st == "ok" else (set(), set())
        return anc, comp, dirs, files


def collect(text):
    """→ (dirs:list, files:list, autos:list)。JSON 按键信任其形；文本行走 auto 探形。"""
    dirs, files, autos = [], [], []
    if text.strip().startswith(("{", "[")):
        data = json.loads(text)
        items = data.get("items", []) if isinstance(data, dict) else data
        for it in items:
            if isinstance(it, str):
                autos.append(it.strip().rstrip("/"))
                continue
            dval = next((it[k].strip() for k in DIR_KEYS
                         if isinstance(it.get(k), str) and it[k].strip()), None)
            fval = next((it[k].strip() for k in FILE_KEYS
                         if isinstance(it.get(k), str) and it[k].strip()), None)
            if dval:
                dirs.append(dval.rstrip("/"))
            if fval:
                # file 可为相对 dir 的文件名（landing list 定式）或全路径
                if fval.startswith("/") or not dval:
                    files.append(fval.rstrip("/"))
                else:
                    files.append(dval.rstrip("/") + "/" + fval.lstrip("/"))
    else:
        for ln in text.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                autos.append(ln.rstrip("/"))
    return dirs, files, autos


def check_dir(pb, d):
    if pb.ls(d)[0] == "ok":
        st, payload = pb.ls(d)
        return {"r": "ok", "path": d, "empty": payload[2]}
    anc, comp, sib_d, _ = pb.missing_hop(d)
    return {"r": "red", "kind": "dir", "path": d,
            "break_at": (anc + "/" + comp) if anc else d,
            "suggest": suggest(comp, sib_d) if comp else []}


def check_file(pb, pth):
    parent, base = os.path.dirname(pth) or "/", os.path.basename(pth)
    st, payload = pb.ls(parent)
    if st == "ok":
        if base in payload[0]:
            return {"r": "ok", "path": pth}
        return {"r": "red", "kind": "file", "path": pth, "break_at": pth,
                "suggest": suggest(base, payload[0])}
    anc, comp, sib_d, sib_f = pb.missing_hop(pth)
    # 断点若在末一级，补按文件近邻给候选
    sib = sib_f if comp == base else sib_d
    return {"r": "red", "kind": "file_parent", "path": pth,
            "break_at": (anc + "/" + comp) if anc else pth,
            "suggest": suggest(comp, sib) if comp else []}


def check_auto(pb, p):
    """文本行：先目录后文件。"""
    if pb.ls(p)[0] == "ok":
        return check_dir(pb, p)
    return check_file(pb, p)


def preflight(text, lister=None, reporter=None):
    lister = lister or (lambda d: listing(d))
    pb = Prober(lister)
    dirs, files, autos = collect(text)
    results = ([check_dir(pb, d) for d in sorted(set(dirs))]
               + [check_file(pb, f) for f in sorted(set(files))]
               + [check_auto(pb, a) for a in sorted(set(autos))])
    rep = {"dirs_ok": sum(1 for r in results if r["r"] == "ok" and "empty" in r),
           "files_ok": sum(1 for r in results if r["r"] == "ok" and "empty" not in r),
           "warn": [{"kind": "dir", "path": r["path"], "note": "空表（存在但零条目）"}
                    for r in results if r["r"] == "ok" and r.get("empty")],
           "red": [r for r in results if r["r"] == "red"]}
    rep["verdict"] = "RED" if rep["red"] else "PASS"
    if reporter:
        reporter(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


# ---------------- selftest（故障注入，不连库） ----------------
def _selftest():
    FS = {
        "/X-TV/Greys.Anatomy": ({"a.nfo"}, {"S22"}, False),
        "/X-TV/Greys.Anatomy/S22": ({"e01.ai.srt", "e02.ai.srt"}, set(), False),
        "/X-TV": ({"nfo.txt"}, {"Greys.Anatomy", "Westworld"}, False),
        "/X-TV/Westworld": ({"s01.ai.srt"}, set(), False),
        "/EMPTYLIB": (set(), set(), True),
    }

    def lister(d):
        if d not in FS:
            raise ftplib.error_perm("550 %s: No such file or directory" % d)
        return FS[d]

    ok = True

    def run(name, text, expect):
        nonlocal ok
        rep = preflight(text, lister=lister)
        good = rep["verdict"] == expect
        ok &= good
        extra = (" red=%s" % [(r["kind"], r["break_at"], r["suggest"]) for r in rep["red"]]) if good and expect == "RED" else ""
        print("selftest %s: %s expect=%s%s %s" % (name, rep["verdict"], expect, extra, "OK" if good else "FAIL"))

    run("good", "/X-TV/Greys.Anatomy/S22\n/X-TV/Greys.Anatomy/S22/e01.ai.srt\n", "PASS")
    run("dir_dot_in_name", "/X-TV/Greys.Anatomy", "PASS")  # 名含点目录禁被 splitext 误判
    run("dir_apostrophe_typo", "/X-TV/Grey's.Anatomy/Greys.Anatomy/S22", "RED")
    r = preflight("/X-TV/Grey's.Anatomy/Greys.Anatomy/S22", lister=lister)
    hit = r["red"][0]["break_at"] == "/X-TV/Grey's.Anatomy" and "Greys.Anatomy" in r["red"][0]["suggest"]
    ok &= hit
    print("selftest suggest_apostrophe_break_at: %s" % ("OK" if hit else "FAIL"))
    run("file_missing", "/X-TV/Greys.Anatomy/S22/e03.ai.srt", "RED")
    r = preflight("/X-TV/Greys.Anatomy/S22/e01.ai.srr", lister=lister)
    hit = r["verdict"] == "RED" and "e01.ai.srt" in r["red"][0]["suggest"]
    ok &= hit
    print("selftest file_typo_suggest: %s" % ("OK" if hit else "FAIL"))
    r = preflight("/EMPTYLIB", lister=lister)
    hit = r["verdict"] == "PASS" and len(r["warn"]) == 1
    ok &= hit
    print("selftest empty_warn: %s" % ("OK" if hit else "FAIL"))
    run("json_items", json.dumps({"items": [
        {"dir": "/X-TV/Greys.Anatomy/S22", "file": "/X-TV/Greys.Anatomy/S22/e02.ai.srt"},
        {"directory": "/X-TV/Westworld"}]}), "PASS")
    run("json_bad_file", json.dumps({"items": [{"file": "/X-TV/Westworld/s01.aisrt"}]}), "RED")
    run("relative_file_join", json.dumps({"items": [
        {"dir": "/X-TV/Greys.Anatomy/S22", "file": "e01.ai.srt"}]}), "PASS")
    run("relative_file_bad", json.dumps({"items": [
        {"dir": "/X-TV/Greys.Anatomy/S22", "file": "e09.ai.srt"}]}), "RED")
    print("selftest ALL %s —— 预检器验讫（存在性 fail-closed + 断点成分定位 + 近邻/撇号变体建议）。"
          % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", nargs="?", help="清单文件路径（JSON/文本）；- 读 stdin")
    ap.add_argument("--out", help="报告 JSON 落盘路径")
    ap.add_argument("--dry-selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_selftest:
        return _selftest()
    if not a.target:
        ap.error("需要清单路径或 --dry-selftest")
    text = sys.stdin.read() if a.target == "-" else open(a.target, encoding="utf-8").read()
    try:
        rep = preflight(text)
    except ftplib.all_errors as e:
        print("CONNECT_FAIL:", e, file=sys.stderr)
        return 3
    out = json.dumps(rep, ensure_ascii=False, indent=1)
    print(out)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as h:
            h.write(out + "\n")
    return 2 if rep["verdict"] == "RED" else 0


if __name__ == "__main__":
    sys.exit(main())
