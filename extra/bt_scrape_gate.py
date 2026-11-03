#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bt_scrape_gate.py — 公开 tracker BEP15 /scrape 作第三 S 源（案3固化，2026-11-02）。

背景（knaben/itorrents 站侧 S 全黑时的唯一过闸通道）：
  站页 S 读数黑掉 ≠ 全网无种。公开 tracker 的 HTTP/HTTPS BEP15 scrape
  （announce 换 /scrape?info_hash=<urlencoded raw20>）能独立测得 seeds。
  团队实测定律（2026-10-21/22 ds_scrape2 案）：
  · tracker 出口极抖，**单轮 scrape 会把有效回包丢掉** → 判 0 必须两轮，
    任一轮 >0 即活；
  · NAS/本机 UDP 均不通 → **只用 HTTP/HTTPS tracker，UDP/DHT 一律不指望**；
  · fake-ip 会伪造回包（198.18.x.x 解析出来的 tracker 直接剔除）。

闸口径（站长定）：**≥2 家活体 tracker 同向**才作 S 闸依据——
  · 活体 = 两轮内至少一轮 bencode 合法回包；
  · 同向 = ≥2 家 seeds>0 且 max/min ≤ 8x（悬殊即互疑，不作数）；
  · 与任务表自身 tracker 统计（v3 additional=detail 的 tracker 段 / BT.Tracker）互印，
    三路读数一并输出，供人工终裁。

预期行为（站长 2026-11-02 验收批，真实验证过的失败样例）：
  外网出口故障期间，tracker 域名被网关 fake-ip 解析 → 全部剔除 → 0 活体 →
  正确报 `S_GATE_FAIL`（而非假过闸）。这是**设计行为不是工具故障**：
  2026-11-02 实弹 8/8 全黑即此样例。工具解的是「站页 S 黑 ≠ 全网无种」，
  前提是 tracker 路通；出口未修时读数一律不可信，等修好再跑。

用法：
  python3 bt_scrape_gate.py --ih 5C0135EDAA...40位 [--trackers a.org:1337,b.org:6969] \
      [--task dbid_18245] [--min-seeds 1] [--out logs/]
  --dry-run   不联网：只解析参数、打印池与判定流程、输出样例形状
  --selftest  零联网：内置 bencode 样例回归（单轮丢包/单家独证/两家同向/悬殊分歧）
输出统一读数 JSON：{ih, rounds, per_tracker[], consensus{gate_pass,seeds_med,n_agree,
  reason}, task_table{...}, verdict}
"""
import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ds_common import bdecode

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 实测回过包池（tools/http_trackers.py 2026-10-21 定；UDP 一律不收）
POOL = [
    "http://tracker.opentrackr.org:1337/announce",
    "http://tracker.dler.org:6969/announce",
    "http://tracker.leechers-paradise.org:6969/announce",
    "http://tracker.internetwarriors.net:1337/announce",
    "http://tracker.torrent.eu.org:451/announce",
    "http://open.stealth.si:80/announce",
    "https://tracker.gbitt.info/announce",
    "http://tracker.gbitt.info/announce",
]


def scrape_url(announce, ih_hex):
    base = announce.rsplit("/announce", 1)[0] + "/scrape"
    raw = bytes.fromhex(ih_hex)
    q = "".join("%%%02X" % b for b in raw)  # BEP15: urlencoded raw 20B
    return base + "?info_hash=" + q


def fake_ip(url):
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        ip = socket.gethostbyname(host)
        return ip.startswith("198.18.")
    except Exception:
        return False


def fetch_one(announce, ih_hex, tries=3, timeout=12):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(scrape_url(announce, ih_hex),
                                         headers={"User-Agent": "Mozilla/5.0"})
            b = urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
            d, _ = bdecode(b)
            files = d.get(b"files") or {}
            rec = files.get(bytes.fromhex(ih_hex)) or {}
            return {"state": "bencode", "seeds": int(rec.get(b"seeders", 0) or 0),
                    "leechers": int(rec.get(b"leechers", 0) or 0)}
        except Exception as e:
            last = type(e).__name__
            time.sleep(1)
    return {"state": "dead", "seeds": 0, "leechers": 0, "err": last}


def scrape_round(pool, ih_hex):
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(fetch_one, t, ih_hex): t for t in pool}
        return {futs[f]: f.result() for f in futs}


def two_round_gate(pool, ih_hex, min_seeds=1):
    """两轮判定（0.0x 案定：单轮丢包必误杀）。返回 (per_tracker, consensus)。"""
    r1 = scrape_round(pool, ih_hex)
    r2 = scrape_round(pool, ih_hex)
    per = []
    for t in pool:
        a, b2 = r1.get(t, {}), r2.get(t, {})
        seeds = max(a.get("seeds", 0), b2.get("seeds", 0))
        alive = a.get("state") == "bencode" or b2.get("state") == "bencode"
        per.append({"tracker": t, "seeds_r1": a.get("seeds"), "seeds_r2": b2.get("seeds"),
                    "seeds": seeds, "alive": alive,
                    "err": (a.get("err") or b2.get("err"))})
    pos = sorted(p["seeds"] for p in per if p["alive"] and p["seeds"] >= min_seeds)
    agree = len(pos) >= 2
    same_dir = True
    reason = "ok"
    if agree:
        if pos[-1] > pos[0] * 8:
            same_dir = False
            reason = "seeders 悬殊(%d~%d)互疑，不作数" % (pos[0], pos[-1])
    else:
        reason = "活体且 S≥%d 的 tracker 仅 %d 家，<2 家同向" % (min_seeds, len(pos))
    med = pos[len(pos) // 2] if pos else 0
    return per, {"gate_pass": bool(agree and same_dir), "n_agree": len(pos),
                 "seeds_med": med, "reason": reason}


def task_table_cross(sid, task_id):
    """与任务表自身 tracker 统计互印（尽力而为，失败只记 note）。"""
    own = sid is None
    s = sid
    try:
        from ds_common import login, logout, task_list
        if own:
            s = login()
        for t in task_list(s, additional="detail,tracker", limit=500):
            if t.get("id") == task_id:
                trk = (t.get("additional") or {}).get("tracker") or []
                return {"status": t.get("status"),
                        "trackers": [{"url": x.get("url"), "seeds": x.get("seeds"),
                                      "leechers": x.get("leechers"), "status": x.get("status")}
                                     for x in trk][:12]}
        return {"note": "task 不在表"}
    except Exception as e:
        return {"note": str(e)[:120]}
    finally:
        if own and s:
            try:
                from ds_common import logout
                logout(s)
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ih", help="40 位 hex infohash")
    ap.add_argument("--trackers", help="逗号分隔 announce url/裸host:port，覆盖默认池")
    ap.add_argument("--task", help="可选：DS 任务 id，用于任务表互印")
    ap.add_argument("--sid", help="可选：复用已登录 sid")
    ap.add_argument("--min-seeds", type=int, default=1)
    ap.add_argument("--out", default="logs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.ih or len(a.ih) != 40:
        raise SystemExit("需要 --ih 40 位 hex（或 --selftest）")
    def norm_pool():
        pool = []
        for t in (a.trackers.split(",") if a.trackers else POOL):
            t = t.strip()
            if not t.startswith("http"):
                t = "http://" + t + "/announce"
            if "/announce" not in t:
                t += "/announce"
            pool.append(t)
        return pool

    if a.dry_run:
        pool = norm_pool()  # 预演不剔 fake-ip（那要现场 DNS），只验形状与流程
        print("[DRY-RUN] 池(%d):" % len(pool), pool)
        print("[DRY-RUN] scrape 样例 URL:", scrape_url(pool[0], a.ih)[:110], "...")
        print("[DRY-RUN] 判定流程: 两轮并发 scrape → 活体取 max → ≥2 家 S≥%d 且 max/min≤8x → gate_pass"
              % a.min_seeds)
        print("[DRY-RUN] 未联网。")
        return 0

    pool = []
    for t in norm_pool():
        if fake_ip(t):
            print("剔除 fake-ip tracker:", t)
            continue
        pool.append(t)

    per, cons = two_round_gate(pool, a.ih.upper(), a.min_seeds)
    out = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "ih": a.ih.upper(),
           "rounds": 2, "per_tracker": per, "consensus": cons}
    if a.task:
        out["task_table"] = task_table_cross(a.sid, a.task)
    alive = sum(1 for p in per if p["alive"])
    out["verdict"] = ("S_GATE_PASS" if cons["gate_pass"] else "S_GATE_FAIL:" + cons["reason"])
    print("活体 %d/%d ｜ 同向 %d 家 ｜ med=%d ｜ %s"
          % (alive, len(per), cons["n_agree"], cons["seeds_med"], out["verdict"]))
    os.makedirs(a.out, exist_ok=True)
    p = "%s/scrape_gate_%s_%s.json" % (a.out, a.ih.upper()[:8], time.strftime("%H%M%S"))
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
    print("->", p)
    return 0 if cons["gate_pass"] else 2


def selftest():
    """零联网：用假 fetch_one 注入四种形态，回归闸口径（含 10-21 单轮丢包案）。"""
    import bt_scrape_gate as M
    IH = "5C0135EDAA7592174DB297A5479FB5EAA21D44CB"
    pool = ["http://a/announce", "http://b/announce", "http://c/announce", "http://d/announce"]

    # 场景1（10-21 案复现）：a 单轮丢包（r1 dead r2 seeds=4）→ 不得误杀
    seq = [{"http://a/announce": {"state": "dead", "seeds": 0, "err": "SSLEOFError"},
            "http://b/announce": {"state": "bencode", "seeds": 5, "leechers": 1},
            "http://c/announce": {"state": "bencode", "seeds": 0, "leechers": 0},
            "http://d/announce": {"state": "dead", "seeds": 0, "err": "timeout"}},
           {"http://a/announce": {"state": "bencode", "seeds": 4, "leechers": 0},
            "http://b/announce": {"state": "bencode", "seeds": 5, "leechers": 1},
            "http://c/announce": {"state": "bencode", "seeds": 0, "leechers": 0},
            "http://d/announce": {"state": "dead", "seeds": 0, "err": "timeout"}}]
    it = iter(seq)
    M.scrape_round = lambda p, ih: next(it)
    per, c = M.two_round_gate(pool, IH)
    assert c["gate_pass"] and c["n_agree"] == 2 and c["seeds_med"] in (4, 5), c
    print("selftest[单轮丢包不误杀] OK")

    # 场景2：单家独证（只 b 有种）→ 不过闸
    one = {"http://a/announce": {"state": "bencode", "seeds": 0, "leechers": 0},
           "http://b/announce": {"state": "bencode", "seeds": 7, "leechers": 0},
           "http://c/announce": {"state": "bencode", "seeds": 0, "leechers": 0},
           "http://d/announce": {"state": "dead", "seeds": 0}}
    it = iter([one, one])
    per, c = M.two_round_gate(pool, IH)
    assert not c["gate_pass"] and "仅 1 家" in c["reason"], c
    print("selftest[单家独证不过闸] OK")

    # 场景3：两家但悬殊 2 vs 300 → 同向不成立
    far = {"http://a/announce": {"state": "bencode", "seeds": 2, "leechers": 0},
           "http://b/announce": {"state": "bencode", "seeds": 300, "leechers": 0},
           "http://c/announce": {"state": "bencode", "seeds": 0, "leechers": 0},
           "http://d/announce": {"state": "dead", "seeds": 0}}
    it = iter([far, far])
    per, c = M.two_round_gate(pool, IH)
    assert not c["gate_pass"] and "悬殊" in c["reason"], c
    print("selftest[悬殊分歧不作数] OK")

    # scrape URL 形状（BEP15 urlencoded raw20）
    u = M.scrape_url("http://x:6969/announce", IH)
    assert u.startswith("http://x:6969/scrape?info_hash=%5C%01%35%ED") and "%44%CB" in u, u
    print("selftest[BEP15 URL 形状] OK")
    print("SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
