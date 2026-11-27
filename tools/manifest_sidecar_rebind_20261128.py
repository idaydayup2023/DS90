#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""manifest 侧车换绑具（正典面·2026-11-28）——站长 03:1x ② 令：闸具三缺陷全部修正＋负控。

三缺陷与本版对策（站长定性原文，逐条对应）：
  D1 幂等路径 NameError
     → 本版所有分支局部变量在分支**之前**统一初始化（见 `_State`），两分支同尾（`st.finish()`），
       任何路径走到 V 段都不得引用只在另一分支赋值的名字。
  D2 四步写缩进落在 if/else 之外 ⇒「只验不写」（干跑／幂等）也会 STOR
     → 写面收进唯一函数 `four_step_write()`，**只有** `run()` 里 `if st.apply and not st.already:`
       这一处调用；验证路径（干跑、已换绑幂等复核）在代码结构上取不到写函数。
     → 负控在 `test_manifest_sidecar_rebind_20261128.py`：假 FTP 记录全部命令，
       干跑与幂等两轮**必须零写命令**（STOR/RNTO/RNFR/DELE/MKD/SITE CHMOD 一律不得出现）。
  D3 V-3 同字节替换假红（等长替换 size 不变被判异动）
     → V-3 拆两条：V-3a 件名集合零变；V-3b 除侧车外逐枚 size 零变；侧车一枚内容变＝预期，
       **等长替换（size 不变）同样判绿**，内容级判据交给 V-2 逐字段对榫。

另补两条常守（站长 03:1x ④ 令，双头刀规 e31a）：
  · ledger 每行带 actor 戳（user/pid/ppid/cwd）；
  · 同案单 ledger：本案 ledger 已有 `apply=true` 且出件 sha 与本轮引擎出件不等 ⇒ 立即 FREEZE
    （第二把同案刀落地即停手报站长）。

用法（真跑）：
    python3 tools/manifest_sidecar_rebind_20261128.py --config cfg.json          # 干跑，实测零写
    python3 tools/manifest_sidecar_rebind_20261128.py --config cfg.json --apply  # 落刀
cfg.json 见 `example_config.json` 同目录注释；本具**只写侧车一枚**，`.ai`／底件／其余件零碰。
"""
from __future__ import annotations

import argparse
import datetime
import ftplib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

WS = Path(__file__).resolve().parent.parent          # 仓根（DS90/）
WRITE_CMDS = ("STOR", "RNTO", "RNFR", "DELE", "MKD", "SITE CHMOD", "APPE")


def conn(timeout=300):
    """真跑用的连接工厂（形制沿仓内 tools/ds90_ftp_walk.py 的 factory，凭证只走环境变量）。

    NAS 规矩：明文 FTP 172.19.60.90:10021（PASV）；60021 是 SFTP 假入口，勿用。
    """
    host = os.environ.get("DSH_FTP_HOST", "172.19.60.90")
    port = int(os.environ.get("DSH_FTP_PORT", "10021"))
    user = os.environ["DSH_SECRET_SUBTRANS_FTP_USERNAME"]
    password = os.environ["DSH_SECRET_SUBTRANS_FTP_PASSWORD"]
    f = ftplib.FTP()
    f.encoding = "utf-8"
    f.connect(host, port, timeout=60)
    f.login(user, password)
    try:
        f.voidcmd("OPTS UTF8 ON")
    except Exception:
        pass                                          # 不支持 UTF8 opt 时按原编码走，不静默改名
    f.set_pasv(True)
    f.sock.settimeout(timeout)
    return f


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def hms_now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class GateFail(Exception):
    pass


class State:
    """D1 对策：所有分支变量先置默认值，两分支同尾，杜绝 NameError。"""

    def __init__(self, cfg, apply):
        self.cfg, self.apply = cfg, apply
        self.gates, self.writes, self.ledger_row = [], [], {"ts": hms_now(), "apply": bool(apply),
                                                            "order": cfg.get("order", ""),
                                                            "actor": {"user": os.environ.get("USER", "?"),
                                                                      "pid": os.getpid(),
                                                                      "ppid": os.getppid(),
                                                                      "cwd": os.getcwd()}}
        self.dir_before, self.dir_after = {}, {}
        self.sidecar_disk = b""
        self.expected = {}
        self.expected_sha = None
        self.already = False
        self.verdict_pre = self.verdict_post = None
        self.write = {"before": None, "sha_after_newconn": None, "bytes_after_newconn": None,
                      "chmod_err": None}

    def gate(self, name, ok, detail=None):
        self.gates.append({"gate": name, "ok": bool(ok), "detail": detail})
        print("%s %s %s" % (hms_now(), "PASS" if ok else "FREEZE", name), flush=True)
        if not ok:
            self.ledger_row.update(gates=self.gates, result="FREEZE")
            raise GateFail(name)

    def finish(self):
        self.ledger_row.update(gates=self.gates,
                               result="GREEN" if all(g["ok"] for g in self.gates) else "FREEZE",
                               writes_seen=self.writes,
                               sidecar_before_sha=sha(self.sidecar_disk) if self.sidecar_disk else None,
                               manifest_expected_sha=self.expected_sha,
                               write=self.write)
        return self.ledger_row


def cd(conn, path):
    """先回根再逐级 CWD 进入（NAS 对含方括号路径的 LIST 直接传路径会返回空，必须逐级进）。

    先 CWD `/` 是为幂等：同一连接上第二次进同一目录不会把路径套成两层（负控 T1/T2 抓到过）。
    """
    conn.cwd("/")
    for seg in [x for x in path.strip("/").split("/") if x]:
        conn.cwd(seg)


def face(conn, dirpath):
    cd(conn, dirpath)
    lines = []
    conn.retrlines("LIST", lines.append)
    out = {}
    for ln in lines:
        p = ln.split(None, 8)
        if len(p) > 8:
            out[p[8].strip()] = {"mode": p[0], "size": int(p[4]), "owner": p[2], "group": p[3]}
    return out


def fetch(conn, dirpath, name):
    cd(conn, dirpath)
    try:
        conn.voidcmd("TYPE I")                    # DSM 坑（11-05）：LIST 后 RETR 会插 CR
    except Exception:
        pass
    buf = io.BytesIO()
    conn.retrbinary("RETR " + name, buf.write)
    return buf.getvalue()


def four_step_write(conn_w, conn_r, dirpath, name, data, before_sha):
    """唯一写面（D2 对策）：STOR 临时名 → 同连回读 → RNTO → 新会话逐位。调用点唯一。"""
    want = sha(data)
    tmp = name + ".tmp-%d" % int(time.time())
    cd(conn_w, dirpath)                                # STOR 前必须先 CWD 进目标目录（负控 T3 抓到的缺陷）
    conn_w.storbinary("STOR " + tmp, io.BytesIO(data))
    if sha(fetch(conn_w, dirpath, tmp)) != want:
        conn_w.delete("DELE " + tmp)
        raise GateFail("W-2a 临时名回读 sha 不符（已删临时件）")
    conn_w.rename("RNFR " + tmp, "RNTO " + name)
    fin = fetch(conn_r, dirpath, name)
    if fin != data or sha(fin) != want:
        raise GateFail("W-2b 新会话回读逐位不等")
    try:
        cd(conn_r, dirpath)
        conn_r.sendcmd("SITE CHMOD 0644 " + name)
    except Exception as e:                                # mode 压不住落清单交站长 SSH 扫尾，不判红
        return {"before": before_sha, "sha_after_newconn": sha(fin), "bytes_after_newconn": len(fin),
                "chmod_err": repr(e)[:160]}
    return {"before": before_sha, "sha_after_newconn": sha(fin), "bytes_after_newconn": len(fin),
            "chmod_err": None}


def run(cfg, conns, probe, apply=False, ledger_path=None):
    """conns: 取连接的工厂（真跑＝本具 conn()，测试＝假 FTP）；probe: (name,args)->dict。"""
    st = State(cfg, apply)
    DIR, AI, MAN = cfg["dir"], cfg["ai"], cfg["manifest"]
    OLD_OUT, NEW_OUT = cfg["sidecar_output_sha_expected_old"], cfg["output_sha_new"]
    CMP = ("schema", "status", "source_kind", "source_path", "source_sha256", "output_sha256",
           "cache_key", "acquisition_key", "video_identity_sha256", "video_path")

    # ---- R 前置：基准 toml 与键面（禁抄旧值，一律现算对榫） ----
    st.gate("R-1 基准 toml sha ≡ 在案锚", sha(cfg["baseline_bytes"]) == cfg["baseline_sha"],
            {"sha256": sha(cfg["baseline_bytes"])})
    st.gate("R-2 甲源轨件 ≡ 在案锚", sha(cfg["source_track_bytes"]) == cfg["source_sha"],
            {"sha256": sha(cfg["source_track_bytes"]), "bytes": len(cfg["source_track_bytes"])})
    pb = probe("manifest_bind_probe", [cfg["video_rel"], cfg["source_sha"], cfg["source_kind"]])
    if "_manifest_bytes" not in pb:
        st.gate("R-3 引擎出件可得", False, pb)
    exp = json.loads(pb["_manifest_bytes"])
    st.expected, st.expected_sha = exp, sha(pb["_manifest_bytes"].encode())
    st.gate("R-3 引擎出件 VALIDATE ok 且三值 ≡ 现算对榫",
            pb.get("VALIDATE") == "ok"
            and exp.get("cache_key") == cfg["cache_key"] == probe("sha_key_probe", [cfg["source_sha"]]).get("cache_key")
            and exp.get("acquisition_key") == cfg["acq"]
            and exp.get("video_identity_sha256") == cfg["identity"],
            {"cache_key": exp.get("cache_key"), "acq": exp.get("acquisition_key"),
             "identity": exp.get("video_identity_sha256")})
    st.gate("R-4 output_sha256 ≡ 新终稿且 status=ready/schema=3",
            exp.get("output_sha256") == NEW_OUT and exp.get("schema") == 3 and exp.get("status") == "ready",
            {"output_sha256": exp.get("output_sha256")})

    # ---- S 盘面现读（新会话） ----
    c = conns()
    try:
        st.dir_before = face(c, DIR)
        st.gate("S-1 残留扫描空", not any((".tmp-" in n) or n.endswith((".orig", ".new")) for n in st.dir_before),
                [n for n in st.dir_before if ".tmp-" in n or n.endswith((".orig", ".new"))])
        st.gate("S-2 `.ai` ≡ 新终稿且件名在位",
                MAN in st.dir_before and AI in st.dir_before
                and sha(fetch(c, DIR, AI)) == cfg["ai_sha"],
                {"ai_sha_face": st.dir_before.get(AI)})
        st.sidecar_disk = fetch(c, DIR, MAN)
        cur = json.loads(st.sidecar_disk.decode("utf-8"))
        st.gate("S-3 侧车写窗内未被改动（与账面旧值对榫）",
                sha(st.sidecar_disk) == cfg.get("sidecar_disk_sha") or cur.get("output_sha256") in (OLD_OUT, NEW_OUT),
                {"disk_sha": sha(st.sidecar_disk)[:16], "output_sha256": cur.get("output_sha256")})
    finally:
        c.quit()
    st.already = json.loads(st.sidecar_disk.decode("utf-8")).get("output_sha256") == NEW_OUT
    st.write["before"] = "already_rebound" if st.already else "to_replace"

    # ---- L 同案单 ledger 锁（双头刀规 e31a） ----
    if ledger_path and os.path.exists(ledger_path):
        prior = [json.loads(l) for l in open(ledger_path, encoding="utf-8") if l.strip()]
        clash = [r for r in prior if r.get("apply") and r.get("manifest_expected_sha")
                 and r["manifest_expected_sha"] != st.expected_sha]
        st.gate("L-1 同案单 ledger：无第二把刀落地冲突", not clash,
                {"prior_apply_rows": sum(1 for r in prior if r.get("apply")),
                 "clash_sha": [r["manifest_expected_sha"][:16] for r in clash][:3]})

    # ---- V 判词 pre ----
    st.verdict_pre = probe("identity_probe", [cfg["video_rel"]])

    # ---- W 写面：唯一调用点（D2 对策） ----
    if st.apply and not st.already:
        keep = cfg["keep_dir"] + "/" + MAN + ".old"
        os.makedirs(cfg["keep_dir"], exist_ok=True)
        if os.path.exists(keep) and sha(open(keep, "rb").read()) != sha(st.sidecar_disk):
            st.gate("W-1 留底件已在位但 sha 不等（禁覆盖留底）", False, {"keep": keep})
        if not os.path.exists(keep):
            open(keep, "wb").write(st.sidecar_disk)
        st.gate("W-1 旧侧车留底且回读 sha ≡ 盘面值",
                sha(open(keep, "rb").read()) == sha(st.sidecar_disk), {"keep": keep})
        cw, cr = conns(), conns()
        try:
            st.write = four_step_write(cw, cr, DIR, MAN, pb["_manifest_bytes"].encode(),
                                       "pre_written_old_replaced")
        finally:
            for _c in (cw, cr):
                try:
                    _c.quit()
                except Exception:
                    pass
    elif st.already:
        st.write["before"] = "already_rebound_verified"
    else:
        st.write["before"] = "dry_run_no_write"

    # ---- V 判词 post ＋ 逐字段 ＋ 目录 diff（D3 对策） ----
    st.verdict_post = probe("identity_probe", [cfg["video_rel"]])
    st.gate("V-1 判词 post = READY 且三值逐位",
            "READY" in (st.verdict_post.get("verdict") or "")
            and cfg["identity"] in (st.verdict_post.get("verdict") or "")
            and cfg["cache_key"] in (st.verdict_post.get("verdict") or "")
            and cfg["acq"] in (st.verdict_post.get("verdict") or ""),
            {"verdict": st.verdict_post.get("verdict"), "reason": st.verdict_post.get("reason")})
    c2 = conns()
    try:
        st.dir_after = face(c2, DIR)
        disk = json.loads(fetch(c2, DIR, MAN).decode("utf-8"))
    finally:
        c2.quit()
    if st.apply and not st.already:                    # 真换绑：逐字段须与引擎出件全等
        bad = [k for k in CMP if disk.get(k) != exp.get(k)]
        st.gate("V-2 盘面侧车逐字段 ≡ 引擎出件（created_unix_seconds 系当次现戳不比）", not bad, {"不等": bad})
    elif st.already:                                   # 幂等复核：同上
        bad = [k for k in CMP if disk.get(k) != exp.get(k)]
        st.gate("V-2 盘面侧车逐字段 ≡ 引擎出件（幂等复核）", not bad, {"不等": bad})
    else:                                              # 干跑：除 output_sha256 外全等，且该值仍指旧终稿（＝未被人动）
        bad = [k for k in CMP if k != "output_sha256" and disk.get(k) != exp.get(k)]
        st.gate("V-2 干跑口径：盘面侧车逐字段 ≡ 引擎出件（output_sha256 仍 ≡ 旧终稿）",
                not bad and disk.get("output_sha256") == OLD_OUT,
                {"不等": bad, "output_sha256": disk.get("output_sha256")})
    st.gate("V-3a 目录件名集合零变（替换形制＝无新增无删除）",
            set(st.dir_before) == set(st.dir_after),
            {"only_before": sorted(set(st.dir_before) - set(st.dir_after)),
             "only_after": sorted(set(st.dir_after) - set(st.dir_before))})
    drift = {n: (st.dir_before[n]["size"], st.dir_after[n]["size"])
             for n in st.dir_before if n in st.dir_after
             and n != MAN and st.dir_before[n]["size"] != st.dir_after[n]["size"]}
    st.gate("V-3b 除侧车外逐枚 size 零变；侧车等长替换亦判绿（内容级看 V-2）",
            not drift, {"drift": drift,
                        "sidecar_size": [st.dir_before.get(MAN, {}).get("size"), st.dir_after.get(MAN, {}).get("size")]})
    st.gate("V-4 写后残留扫描空", not any((".tmp-" in n) or n.endswith((".orig", ".new")) for n in st.dir_after),
            [n for n in st.dir_after if ".tmp-" in n or n.endswith((".orig", ".new"))])
    return st.finish()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--ledger", default=None)
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    for k in ("baseline_bytes_path", "source_track_bytes_path"):
        cfg[k.replace("_path", "_bytes")] = open(cfg[k], "rb").read()

    def probe(name, args):
        bins = {"manifest_bind_probe": "manifest_bind_probe", "identity_probe": "identity_probe",
                "sha_key_probe": "sha_key_probe"}
        pb = WS / "target" / "release" / "examples" / bins[name]
        argv = [str(pb)] + ([] if name == "sha_key_probe" else [cfg["baseline_toml_rel"]]) + list(args)
        if name == "sha_key_probe":
            sf = "/tmp/rebind_src.txt"
            open(sf, "w").write(args[0] + "\n")
            argv = [str(pb), sf, cfg["tomls_list"]]
        p = subprocess.run(argv, capture_output=True, text=True, cwd=WS)
        raw = p.stdout + "\n" + p.stderr
        out = {"_rc": p.returncode}
        for line in raw.splitlines():
            m = re.match(r"^\s+([A-Za-z0-9_]+)\s*=\s*(.*)$", line)
            if m:
                out[m.group(1)] = re.sub(r"\s+\([^)]*\)\s*$", "", m.group(2).strip())
            if "DS90_VERDICT" in line:
                out["verdict"] = line.split("DS90_VERDICT", 1)[1].strip("= ").strip()
            if "reason=" in line and "reason" not in out:
                out["reason"] = line.split("reason=")[1].split()[0]
            if name == "sha_key_probe" and line.startswith("KEY"):
                out["cache_key"] = line.split("\t")[3] if len(line.split("\t")) > 3 else None
        m = re.search(r"---BEGIN-MANIFEST---\n(.*?)\n---END-MANIFEST---", p.stdout, re.S)
        if m:
            out["_manifest_bytes"] = m.group(1) + "\n"
        return out

    try:
        row = run(cfg, conn, probe, apply=a.apply, ledger_path=a.ledger)
        res = "GREEN"
    except GateFail as e:
        row = {"result": "FREEZE", "at": str(e)}
        res = "FREEZE"
    if a.ledger:
        os.makedirs(os.path.dirname(a.ledger), exist_ok=True)
        with open(a.ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"result": res, "row": row}, ensure_ascii=False, indent=1))
    return 0 if res == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
