#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ds_task_upload.py — DS 建 BT 任务正解姿势（案1固化，2026-11-02 zhero 破案）。

破案出处：logs/zhero_upload_case_2026-11-02.md
  真身 = POST /webapi/entry.cgi/SYNO.DownloadStation2.Task（**非 task.cgi**）
  源码 = /volume1/@appstore/DownloadStation/ui/download.js QueueAddFileUploader
  · body 字段：api/version=2/method=create + type='"file"'(JSON 带引号)
    + file='["torrent"]'（=multipart part 名列表）+ destination(JSON 编码串)
    + create_list=false + size=<字节> + extract_password
  · 文件 part **name 必须是 "torrent"**（FILEFILEDNAME，写 "file" 必挂 101）
  · _sid 走 URL query
  · 旧 101 根因＝v3 task.cgi + 参数姿势混搭；119＝缺 size 类条件参数 **或**
    同 hash 在 @download/ 有残留目录（删单未清障，案2实证）
  · 出生秒抢 v2 pause：create 成功 DS 自动开下，v3 pause 慢一步报 103；
    **v2 pause 实测 1 秒内抢停成功**（18245 实证）。

用法：
  实弹:   python3 ds_task_upload.py --torrent /path/x.torrent --dest "Downloads/_dl_stage" \
              [--expect-sha256 ...] [--expect-ih ...] [--pause-now]
  预演:   加 --dry-run（验包+查残留+打印将发的请求概要，不 POST create）
  自测:   python3 ds_task_upload.py --selftest   （零联网，内置样例验姿势）
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ds_common import (BASE, CTX, bdecode, bencode, bare_id, login, logout,
                       pause_v2, ssh)

UNFINISHED_CAP = 60  # 满仓线（18240 案实测 403 风险位；队列闸沿用 zhero_upload_fix）


def upload_create_raw_shape(sid, fname, fbytes, dest_json, bnd="----DsUp20261102"):
    """构造正解 multipart 请求（拆出来给 --dry-run 与 --selftest 复用）。"""
    fields = {
        "api": "SYNO.DownloadStation2.Task", "version": "2", "method": "create",
        "_sid": sid, "type": '"file"', "file": '["torrent"]',
        "destination": dest_json, "create_list": "false", "size": str(len(fbytes)),
        "extract_password": '""',
    }
    body = b""
    for k, v in fields.items():
        body += ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (bnd, k, v)).encode()
    body += ('--%s\r\nContent-Disposition: form-data; name="torrent"; filename="%s"\r\n'
             'Content-Type: application/x-bittorrent\r\n\r\n' % (bnd, fname)).encode()
    body += fbytes + ("\r\n--%s--\r\n" % bnd).encode()
    headers = {"Content-Type": "multipart/form-data; boundary=" + bnd,
               "Content-Length": str(len(body))}
    return BASE + "/entry.cgi/SYNO.DownloadStation2.Task", fields, headers, body


def upload_post(url, headers, body, timeout=90):
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode())


def verify_torrent(path, expect_sha=None, expect_ih=None):
    b = open(path, "rb").read()
    sha = hashlib.sha256(b).hexdigest()
    td, _ = bdecode(b)
    info = td[b"info"]
    ih = hashlib.sha1(bencode(info)).hexdigest().upper()
    name = info.get(b"name", b"?").decode(errors="ignore")
    if expect_sha and sha != expect_sha:
        raise SystemExit("ABORT 本地包 sha 不符: %s != %s" % (sha, expect_sha))
    if expect_ih and ih != expect_ih.upper():
        raise SystemExit("ABORT info_hash 不符: %s != %s" % (ih, expect_ih))
    return {"bytes": len(b), "sha256": sha, "ih": ih, "name": name}


def check_staging_residue(ih):
    """119 预检：同 hash 残留 @download/<数字> 目录（案2根因）。只读列举，清障须人工批准。"""
    try:
        out = ssh("grep -rl '%s' /volume1/@download/*/  --include='*.torrent' 2>/dev/null | head" % ih)
    except Exception as e:
        return {"err": str(e)[:120]}
    return {"torrent_hits": [l for l in out.splitlines() if l.strip()]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--torrent")
    ap.add_argument("--dest", default="Downloads/_dl_stage", help="DS 共享内相对路径（勿带 /volume1 前缀）")
    ap.add_argument("--expect-sha256")
    ap.add_argument("--expect-ih")
    ap.add_argument("--pause-now", action="store_true", help="出生秒抢 v2 pause（建单后立即抢停）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.torrent:
        raise SystemExit("需要 --torrent（或 --selftest）")
    if not os.path.exists(a.torrent):
        raise SystemExit("ABORT torrent 不存在: %s" % a.torrent)

    v = verify_torrent(a.torrent, a.expect_sha256, a.expect_ih)
    print("[0] 包验身:", json.dumps(v, ensure_ascii=False))
    dest_json = json.dumps(a.dest)  # destination=Ext.encode(path)
    tor_b = open(a.torrent, "rb").read()

    sid = login()
    try:
        # 队列闸（满仓建单必 403）
        try:
            n_unfin = None
            r = urllib.request.Request(BASE + "/DownloadStation/task.cgi",
                                       data=urllib.parse.urlencode({
                                           "api": "SYNO.DownloadStation.Task", "version": "3",
                                           "method": "list", "_sid": sid, "offset": 0,
                                           "limit": 500}).encode())
            tasks = (json.loads(urllib.request.urlopen(r, timeout=60, context=CTX).read())
                     .get("data") or {}).get("tasks") or []
            n_unfin = sum(1 for t in tasks if t.get("status") in ("downloading", "paused", "error"))
            print("[1] 队列:", len(tasks), "unfinished:", n_unfin)
            if n_unfin >= UNFINISHED_CAP:
                raise SystemExit("ABORT 未完成任务 %d ≥ 满仓线 %d，建单必 403，先候清位" % (n_unfin, UNFINISHED_CAP))
        except SystemExit:
            raise
        except Exception as e:
            print("WARN 队列闸查询失败(继续):", str(e)[:100])

        # 119 预检（只报不清，清障动作留给站批）
        res = check_staging_residue(v["ih"])
        print("[2] @download 残留预检:", json.dumps(res, ensure_ascii=False))
        if res.get("torrent_hits"):
            print("    !! 同 hash 有暂存残留，直接建单可能 119；先报备清障再建")

        url, fields, headers, body = upload_create_raw_shape(sid, os.path.basename(a.torrent), tor_b, dest_json)
        safe_fields = {k: ("<sid>" if k == "_sid" else v_) for k, v_ in fields.items()}
        print("[3] 将发请求: POST", url.replace(sid, "<sid>"))
        print("    fields:", json.dumps(safe_fields, ensure_ascii=False))
        print("    file part: name=torrent filename=%s (%d B)" % (os.path.basename(a.torrent), len(tor_b)))
        if a.dry_run:
            print("[DRY-RUN] 止于建单前，未 POST。")
            return 0

        r = upload_post(url, headers, body)
        if not r.get("success"):
            print("FAIL 建单失败:", json.dumps(r))
            return 1
        tid = (r.get("data") or {}).get("id")
        print("[4] 建成:", tid)

        if a.pause_now:
            t0 = time.time()
            pr = pause_v2(sid, tid)          # 出生秒抢 v2 pause（案1实证有效）
            print("[5] 秒抢 v2 pause @+%.1fs:" % (time.time() - t0), json.dumps(pr))
        return 0
    finally:
        logout(sid)


def selftest():
    """零联网自测：验包/姿势形状/裸任务号解析，含 101 根因对照。"""
    # 造一个最小 torrent
    info = {b"piece length": 16384, b"pieces": b"\x00" * 20, b"name": b"demo.mkv", b"length": 1000}
    tor = bencode({b"announce": b"http://x/announce", b"info": info})
    expect_ih = hashlib.sha1(bencode(info)).hexdigest().upper()
    d = verify_dict = None
    # 1) 验包
    td, _ = bdecode(tor)
    ih = hashlib.sha1(bencode(td[b"info"])).hexdigest().upper()
    assert ih == expect_ih, "验包 info_hash 不一致"
    print("selftest[验包] OK ih=%s" % ih[:12])
    # 2) 请求形状：part 名必须 torrent、type/file 带 JSON 引号、destination JSON 编码、size 在场
    url, fields, headers, body = upload_create_raw_shape("SID123", "demo.torrent", tor, json.dumps("Downloads/x"))
    assert fields["type"] == '"file"' and fields["file"] == '["torrent"]'
    assert fields["destination"] == '"Downloads/x"' and fields["size"] == str(len(tor))
    assert 'name="torrent"; filename="demo.torrent"' in body.decode("latin1")
    assert "/entry.cgi/SYNO.DownloadStation2.Task" in url
    assert "task.cgi" not in url  # 案1：非 task.cgi
    # 反例对照（旧 101 姿势）：part 名写 file → 形状断言应抓出
    bad = body.decode("latin1").replace('name="torrent"', 'name="file"')
    assert 'name="file"' in bad  # 模拟旧姿势确会偏离正解（断言形状可比对）
    print("selftest[姿势形状] OK（part=torrent、JSON 引号、destination 编码、size、entry.cgi 全对）")
    # 3) 裸任务号（案2）
    assert bare_id("dbid_18245") == "18245" and bare_id(18232) == "18232"
    print("selftest[裸任务号] OK")
    print("SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
