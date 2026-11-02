#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DS90 DownloadStation 工具共享库（代码运维 2026-11-02，工具固化单）。

约定：
- 凭据只从环境变量读：DSH_SECRET_SUBTRANS_FTP_USERNAME / DSH_SECRET_SUBTRANS_FTP_PASSWORD，
  主机 DS90_HOST（默认 172.19.60.90），永不硬编码、永不打印。
- WebAPI 走 https://<host>:5001/webapi，自签证书不校验（团队既定）。
- SSH 诊断/暂存操作走 ds90_ssh.sh 包装（密码经 stdin/askpass，不落命令行）。

破案出处（2026-11-02 工具固化单，站长按语）：
  案1 = logs/zhero_upload_case_2026-11-02.md（upload 正解姿势）
  案2 = logs/zhero_planB_report_2026-11-02.md（裸任务号暂存区规矩）
"""
import json
import os
import ssl
import subprocess
import urllib.parse
import urllib.request

HOST = os.environ.get("DS90_HOST", "172.19.60.90")
BASE = "https://%s:5001/webapi" % HOST
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _post(path, data, timeout=90):
    """form POST（参数走 body，DS 传统姿势）。"""
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode())


def login():
    r = _post("/auth.cgi", {"api": "SYNO.API.Auth", "version": "6", "method": "login",
                            "account": os.environ["DSH_SECRET_SUBTRANS_FTP_USERNAME"],
                            "passwd": os.environ["DSH_SECRET_SUBTRANS_FTP_PASSWORD"],
                            "session": "DownloadStation", "format": "sid"})
    if not r.get("success"):
        raise RuntimeError("DS login failed: %s" % r)
    return r["data"]["sid"]


def logout(sid):
    try:
        _post("/auth.cgi", {"api": "SYNO.API.Auth", "version": "6", "method": "logout",
                            "_sid": sid, "session": "DownloadStation"})
    except Exception:
        pass


def task_list(sid, additional="detail,transfer", limit=500):
    """v3 task list（分页拉全）。"""
    out, off = [], 0
    while True:
        r = _post("/DownloadStation/task.cgi", {"api": "SYNO.DownloadStation.Task", "version": "3",
                                                "method": "list", "_sid": sid, "offset": off,
                                                "limit": min(100, limit), "additional": additional})
        d = r.get("data") or {}
        ts = d.get("tasks") or []
        out += ts
        off += len(ts)
        if len(ts) < 100 or off >= int(d.get("total") or 0) or off >= limit:
            return out


def pause_v2(sid, task_id):
    """v2 pause（案1实证：v3 pause 慢一步报 103，v2 才抢得住）。"""
    return _post("/entry.cgi", {"api": "SYNO.DownloadStation2.Task", "version": "2",
                                "method": "pause", "_sid": sid, "id": json.dumps([task_id])})


def resume_v2(sid, task_id):
    return _post("/entry.cgi", {"api": "SYNO.DownloadStation2.Task", "version": "2",
                                "method": "resume", "_sid": sid, "id": json.dumps([task_id])})


def bare_id(task_id):
    """案2铁律：transmission 暂存区只认裸任务号 /volume1/@download/<数字>/，
    dbid_ 前缀目录 DS 根本不读（18232 实证 / 18240 塞 dbid_ 目录白塞）。"""
    return str(task_id).replace("dbid_", "")


def ssh(cmd, timeout=300):
    """NAS 侧只读/暂存命令通道。工具目录内自带 ds90_ssh.sh 包装。"""
    wrapper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ds90_ssh.sh")
    if not os.path.exists(wrapper):
        raise RuntimeError("缺少 tools/ds90_ssh.sh 包装")
    r = subprocess.run([wrapper, cmd], capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "").strip()
    if r.returncode != 0:
        raise RuntimeError("ssh rc=%s out=%s err=%s" % (r.returncode, out[:300], (r.stderr or "")[:300]))
    return out


# ---------- bencode（案1建单验包 / 案3 scrape 解析共用） ----------
def bdecode(b, i=0):
    c = b[i]
    if c == 0x69:
        j = b.index(b"e", i)
        return int(b[i + 1:j]), j + 1
    if c == 0x64:
        i += 1
        d = {}
        while b[i] != 0x65:
            k, i = bdecode(b, i)
            v, i = bdecode(b, i)
            d[k] = v
        return d, i + 1
    if c == 0x6c:
        i += 1
        l = []
        while b[i] != 0x65:
            v, i = bdecode(b, i)
            l.append(v)
        return l, i + 1
    j = b.index(b":", i)
    n = int(b[i:j])
    return b[j + 1:j + 1 + n], j + 1 + n


def bencode(v):
    if isinstance(v, int):
        return b"i%de" % v
    if isinstance(v, (bytes, str)):
        b_ = v.encode() if isinstance(v, str) else v
        return b"%d:%s" % (len(b_), b_)
    if isinstance(v, list):
        return b"l" + b"".join(bencode(x) for x in v) + b"e"
    if isinstance(v, dict):
        out = b"d"
        for k in sorted(v):
            out += bencode(k) + bencode(v[k])
        return out + b"e"
    raise TypeError(v)
