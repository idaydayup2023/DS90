#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""换绑具负控（站长 2026-11-28 03:1x ② 令：「『只验不写』必须实测零写」＋三缺陷回归）。

跑法： python3 tools/test_manifest_sidecar_rebind_20261128.py     （全绿 exit 0，任一红 exit 1）

覆盖（假 FTP 记账，写命令一律可查）：
 T1 干跑（apply=False）＝GREEN **且零写命令**（D2：验证路径在结构上取不到写函数）
 T2 幂等路径（盘面侧车已指新终稿）带 --apply ＝GREEN **且零写命令**、无 NameError（D1＋D2）
 T3 真换绑（apply=True、盘面指旧 output）＝GREEN＋写命令齐（STOR/RNTO）＋侧车被替换成引擎出件
 T4 等长替换（新旧侧车同字节数、size 不变）＝V-3b **不假红**（D3）
 T5 同案单 ledger 锁：前轮 apply 行出件 sha 不等 ⇒ FREEZE@L-1（双头刀规 e31a）
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest_sidecar_rebind_20261128 as M          # noqa: E402

D = "X-Movie/2010s/Sheep"          # 与真跑 cfg["dir"] 同形（相对形，CD 逐级进）
DIR_ABS = "/" + D                       # 假服务器内的键一律绝对形（CWD 后 pwd 之形）
AI, MAN, VID = "S.ai.srt", "S.ai.srt.ftpuser.json", "S.mp4"
OLD_OUT = "bf" + "2" * 62
NEW_OUT = "ae" + "0" * 62
SRC = "fe" + "3" * 62
CACHE, ACQ, IDENT = "fe" + "4" * 62, "78" + "c" * 62, "41" + "8b" * 31
BASE = b"baseline toml bytes"
TRACK = b"1\n00:00:01,000 --> 00:00:02,000\nhello\n"


def sha(b):
    return hashlib.sha256(b).hexdigest()


class FakeFtp:
    """假 FTP：与 ftplib.FTP 同名同签名（cwd/retrlines/retrbinary/storbinary/voidcmd/sendcmd/
    delete/rename/quit），全部命令记账，写命令一律可查——负控的『实测零写』靠这里。"""

    def __init__(self, srv):
        self.srv = srv
        self.pos = ""                                  # 当前目录（不用 cwd 之名，避免与方法撞名）

    def _p(self, n):
        return n if n.startswith("/") else self.pos.rstrip("/") + "/" + n

    def cwd(self, p):                                  # ftplib 姿势：CWD 进目录
        self.srv["cmds"].append("CWD " + p)
        self.pos = p if p.startswith("/") else self.pos.rstrip("/") + "/" + p

    def pwd(self):
        return self.pos

    def retrlines(self, cmd, cb):
        self.srv["cmds"].append(cmd)
        pre = self.pos.rstrip("/") + "/"
        for name in sorted(self.srv["files"]):
            if name.startswith(pre) and "/" not in name[len(pre):]:
                m, o = self.srv["meta"][name]
                cb("%s 1 %s %s %d Jan  1 00:00 %s" % (m, o[0], o[1], len(self.srv["files"][name]),
                                                      name[len(pre):]))

    def voidcmd(self, c):
        self.srv["cmds"].append(c)

    def sendcmd(self, c):
        self.srv["cmds"].append(c)
        return "250 ok"

    def retrbinary(self, cmd, w):
        self.srv["cmds"].append(cmd)
        w(self.srv["files"][self._p(cmd.split(" ", 1)[1])])

    def storbinary(self, cmd, fp):
        self.srv["cmds"].append(cmd)
        p = self._p(cmd.split(" ", 1)[1])
        self.srv["files"][p] = fp.read()
        self.srv["meta"].setdefault(p, ["-rw-rw-rw-", ("ftp", "users")])

    def delete(self, cmd):
        self.srv["cmds"].append(cmd)
        p = self._p(cmd.split(" ", 1)[1])
        self.srv["files"].pop(p, None)

    def rename(self, a, b):
        self.srv["cmds"] += [a, b]
        s, t = self._p(a.split(" ", 1)[1]), self._p(b.split(" ", 1)[1])
        self.srv["files"][t] = self.srv["files"].pop(s)
        if s in self.srv["meta"]:
            self.srv["meta"][t] = self.srv["meta"].pop(s)

    def quit(self):
        self.srv["cmds"].append("QUIT")


def sidecar(output_sha, created=1700000000):
    return json.dumps({"schema": 3, "status": "ready", "source_kind": "embedded_live",
                       "source_path": None, "source_sha256": sha(TRACK), "output_sha256": output_sha,
                       "cache_key": CACHE, "acquisition_key": ACQ, "video_identity_sha256": IDENT,
                       "video_path": D + "/" + VID, "created_unix_seconds": created},
                      ensure_ascii=False, indent=2).encode() + b"\n"


def probe_new(new_bytes):
    def probe(name, args):
        if name == "sha_key_probe":
            return {"cache_key": CACHE}
        if name == "identity_probe":
            return {"verdict": "READY status=ready identity=%s cache_key=%s acq=%s" % (IDENT, CACHE, ACQ)}
        return dict({"VALIDATE": "ok", "_manifest_bytes": new_bytes.decode()}, **json.loads(new_bytes))
    return probe


def scene(old_sidecar, keep):
    files = {DIR_ABS + "/" + AI: b"AI-BYTES", DIR_ABS + "/" + MAN: old_sidecar,
             DIR_ABS + "/" + VID: b"X" * 1234}
    meta = {DIR_ABS + "/" + AI: ["-rw-r--r--", ("sysadmin", "users")],
            DIR_ABS + "/" + MAN: ["-rw-r--r--", ("sysadmin", "users")],
            DIR_ABS + "/" + VID: ["-rw-r--r--", ("sysadmin", "users")]}
    srv = {"files": files, "meta": meta, "cmds": []}
    cfg = {"dir": D, "ai": AI, "manifest": MAN, "video_rel": D + "/" + VID,
           "sidecar_output_sha_expected_old": OLD_OUT, "output_sha_new": NEW_OUT,
           "baseline_bytes": BASE, "baseline_sha": sha(BASE),
           "source_track_bytes": TRACK, "source_sha": sha(TRACK), "source_kind": "embedded_live",
           "ai_sha": sha(b"AI-BYTES"), "sidecar_disk_sha": sha(old_sidecar),
           "cache_key": CACHE, "acq": ACQ, "identity": IDENT, "keep_dir": keep, "order": "负控"}
    return cfg, srv


def run_case(name, sidecar_old, apply, ledger=None, new_created=1800000000):
    keep = tempfile.mkdtemp()
    cfg, srv = scene(sidecar_old, keep)
    lp = os.path.join(keep, "ledger.jsonl") if ledger is not None or True else None
    if ledger:
        open(lp, "w", encoding="utf-8").write(ledger + "\n")
    new = sidecar(NEW_OUT, created=new_created)
    try:
        row = M.run(cfg, lambda: FakeFtp(srv), probe_new(new), apply=apply, ledger_path=lp)
        res, err, gates = row.get("result"), None, row.get("gates", [])
    except M.GateFail as e:
        res, err, gates = "FREEZE", str(e), []
    except Exception as e:
        res, err, gates = "CRASH", "%s: %s" % (type(e).__name__, e), []
    w = [c for c in srv["cmds"] if c.split(" ", 1)[0] in M.WRITE_CMDS]
    print("[%-20s] result=%-6s writes=%s%s" % (name, res, w or "∅", ("  err=" + err) if err else ""))
    return {"res": res, "err": err, "writes": w, "srv": srv, "cfg": cfg, "new": new, "gates": gates}


def main():
    fails = []
    old = sidecar(OLD_OUT)

    r = run_case("T1_dry_run", old, False)
    if not (r["res"] == "GREEN" and not r["writes"]):
        fails.append("T1 干跑须 GREEN 且零写命令：res=%s writes=%s" % (r["res"], r["writes"]))

    r = run_case("T2_idempotent_apply", sidecar(NEW_OUT, 1790000000), True)
    if not (r["res"] in ("GREEN", "FREEZE") and r["res"] == "GREEN" and not r["writes"]):
        fails.append("T2 幂等带 --apply 须 GREEN 且零写：res=%s writes=%s err=%s" % (r["res"], r["writes"], r["err"]))

    r = run_case("T3_apply", old, True)
    if not (r["res"] == "GREEN" and any(c.startswith("STOR ") for c in r["writes"])
            and any(c.startswith("RNTO ") for c in r["writes"])
            and r["srv"]["files"][DIR_ABS + "/" + MAN] == r["new"]):
        fails.append("T3 真换绑须 GREEN＋STOR/RNTO＋侧车替换：res=%s writes=%s" % (r["res"], r["writes"]))

    r = run_case("T4_same_length", old, True, new_created=1700000000)      # 与旧件等字节
    same = len(r["new"]) == len(old)
    v3b = [g for g in r["gates"] if g["gate"].startswith("V-3b")]
    if not (same and r["res"] == "GREEN" and v3b and v3b[0]["ok"]):
        fails.append("T4 等长替换不得假红：len_eq=%s res=%s V-3b=%s" % (same, r["res"], v3b))

    r = run_case("T5_double_knife_lock", old, True,
                 ledger=json.dumps({"apply": True, "manifest_expected_sha": "0" * 64}))
    if not (r["res"] == "FREEZE" and "L-1" in (r["err"] or "") and not r["writes"]):
        fails.append("T5 同案第二把刀须 FREEZE@L-1 且零写：res=%s err=%s writes=%s" % (r["res"], r["err"], r["writes"]))

    # T6 D2 结构锁（AST 判据，不受注释/文档字符串干扰）：
    #   ① 写方法（storbinary/delete/rename/sendcmd-CHMOD）只许出现在 four_step_write 体内；
    #   ② four_step_write 的调用点全仓唯一（验证路径在结构上取不到写面）。
    import ast
    src = Path(M.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    WRITE_METHODS = {"storbinary", "delete", "rename"}
    leaks, call_sites = [], []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Attribute) and (f.attr in WRITE_METHODS
                                                     or (f.attr == "sendcmd" and "CHMOD" in ast.dump(n))):
                    if fn.name != "four_step_write":
                        leaks.append("%s():%d %s" % (fn.name, n.lineno, f.attr))
                if isinstance(f, ast.Name) and f.id == "four_step_write":
                    call_sites.append((fn.name, n.lineno))
    if not (len(call_sites) == 1 and call_sites[0][0] == "run" and not leaks):
        fails.append("T6 D2 结构锁：写面调用点须唯一且在 run() 内、写方法不得外泄：calls=%s leaks=%s"
                     % (call_sites, leaks))
    else:
        print("[%-20s] 结构锁 OK：写方法仅在 four_step_write 体内，调用点唯一于 run()" % "T6_d2_structure")


    print("\n=== 负控结论 ===")
    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("ALL GREEN：T1–T5 全绿（含『只验不写』实测零写两条＝D1/D2/D3 回归到位）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
