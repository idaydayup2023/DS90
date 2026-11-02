#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TPB 跟踪扫描（用户 2026-10-29 令，站长 14:05 催办）。
user:.BONE.(电影 cat=200) / user:jajaja(剧集 cat=208)，当天窗口（无新则前推一天）。
筛选全部脚本化：去重(任务表btih+库内目录名撞库) / 枪版排除 / 画质打分（[[种源检索]]优先级）。
输出 logs/tpb_scan_YYYY-MM-DD.json + 控制台 TOP≤6。knaben 实测成色若遇 SSL EOF 记录卡点不阻塞。
"""
import json, os, re, ssl, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
DAY = 86400
QUERIES = [("movie", "user%3A.BONE.", None), ("tv", "user%3Ajajaja", None)]
# 2026-11-02 根因修正：cat=200 过滤致 BONE 全空（其片实测落 cat=207/201，jajaja 落 208/205，
# 且 added 字段完好——「timestamp 全 0」是 09:49 那次 apibay 抖动占位行的误诊）。
# 站长 10:3x 批准：不信 timestamp、按 q.php 默认返回序（≈最新序）取 top，每条附时间读数与可信标记。
BAD = re.compile(r"\b(TS|TC|CAM|HDCAM|Screener|SCR|WEBRip-CAM|Workprint|PDVD|VHSRip|telesync|telesync)\b", re.I)

def get(url, tries=4, t=25):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=t, context=CTX)
            return r.read()
        except Exception as e:
            err = str(e)[:80]
            time.sleep(2 + 2 * i)
    return None

def fetch(kind, q, cat):
    """半抖动外网下 apibay 会返回空数组([])而非报错——空结果同样重试。
    cat=None 不带类别过滤（2026-11-02 实证：BONE 片落 207/201、jajaja 落 208/205，写死 200/208 会全空）。"""
    url = "https://apibay.org/q.php?q=%s&limit=100" % q + ("" if cat is None else "&cat=%s" % cat)
    last_err = None
    for attempt in range(6):
        b = get(url, tries=2, t=25)
        if b is None:
            last_err = "apibay 不可达"
        else:
            try:
                rows = json.loads(b)
                # apibay 空结果返回 [{"id":"0","name":"No hits..."}] 占位行，不是 []
                rows = [r for r in rows if str(r.get("id")) != "0"]
                if rows:
                    return rows, None
                last_err = "空结果(疑抖动)"
            except Exception as e:
                last_err = "解析失败 %s" % str(e)[:60]
        time.sleep(3 + 2 * attempt)
    return None, last_err

def norm(s):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (s or "").lower())

def score(n):
    ln = n.lower(); sc = 0.0
    if re.search(r"\bdolby.?vision\b|\bdv\b|\bhevc.?dv\b", ln): sc += 100
    if re.search(r"\bhdr10\+?\b|\bhdr\b", ln): sc += 80
    m265 = bool(re.search(r"x265|hevc", ln)); m1080 = "1080p" in ln
    if m265 and m1080: sc += 60
    if re.search(r"2160p|4k", ln): sc += 50
    if re.search(r"x264|avc", ln) and m1080: sc += 40
    if "720p" in ln: sc += 15
    if re.search(r"\b(dts-?hd|truehd|atmos|ddp?5\.1|dd5\.1|eac3)\b", ln): sc += 6
    if re.search(r"\b(flac|dts)\b", ln): sc += 3
    # 发布组内嵌英字概率加权（[[种源检索]]）
    for g, w in [("BTM",1.0),("NeoNoir",.82),("BONE",.45),("BYNDR",.42),("ELiTE",.18),("KONTRAST",.04),("FLUX",.02)]:
        if re.search(r"[-\[\s(]%s[-\]\s(.]" % g, n, re.I): sc += w*10
    return sc

def in_task_table(ih, tasks):
    return ih.upper() in tasks

RELEASE_JUNK = set("""1080p 2160p 720p 480p 360p x265 x264 hevc h264 h265 xvid av1 bluray blu ray brrip
webrip webrip webdl web dl amzn hulu nf hmax dtv itv itvx hdtv p2p ddp dts truehd atmos eac3 dd5
dual audio complete season proper repack internal limited multi subs sub eng english cht chs chinese
kor jpn 10bit 8bit remastered unrated extended theatrical canton mandarin tagalog soaplove megusta
afg msd jff rawr darkflix ngp norbit cakes bone x265 5 1 7 2 0 the and for with from""".split())

def in_library(name, idx_norms):
    # 2026-11-02 修正：通用发布 token 子串命中致吉卜力/英综全被误判撞库。
    # 剔发布元数据词后要求 ≥75% 词命中才算撞名；有效词不足 2 个一律放行（宁漏不误杀，TOP 人工看）。
    toks = [t for t in re.split(r"[^a-z0-9\u4e00-\u9fff]+", name.lower())
            if len(t) >= 4 and t not in RELEASE_JUNK and not t.isdigit()]
    if len(toks) < 2:
        return False
    hits = sum(1 for t in toks if any(t in x for x in idx_norms))
    return hits >= max(2, -(-3 * len(toks) // 4))

def main():
    now = time.time()
    # 任务表 btih（查重，v3 list）
    HOST = os.environ.get("DS90_HOST", "172.19.60.90"); BASE = "https://%s:5001/webapi" % HOST
    tasks = {}
    try:
        def post(path, data):
            req = urllib.request.Request(BASE+path, data=urllib.parse.urlencode(data).encode())
            return json.loads(urllib.request.urlopen(req, timeout=60, context=CTX).read().decode())
        sid = post("/auth.cgi", {"api":"SYNO.API.Auth","version":"3","method":"login",
              "account":os.environ["DSH_SECRET_SUBTRANS_FTP_USERNAME"],
              "passwd":os.environ["DSH_SECRET_SUBTRANS_FTP_PASSWORD"],
              "session":"DownloadStation","format":"sid"})["data"]["sid"]
        r = post("/DownloadStation/task.cgi", {"api":"SYNO.DownloadStation.Task","version":"3",
             "method":"list","_sid":sid,"offset":0,"limit":500,"additional":"detail"})
        for t in ((r.get("data") or {}).get("tasks") or []):
            u = ((t.get("additional") or {}).get("detail") or {}).get("uri") or ""
            m = re.search(r"btih:([0-9A-Fa-f]{40})", u)
            if m: tasks[m.group(1).upper()] = t["id"]
        post("/auth.cgi", {"api":"SYNO.API.Auth","version":"3","method":"logout","_sid":sid,"session":"DownloadStation"})
    except Exception as e:
        print("WARN 任务表查重跳过:", str(e)[:80])
    idx_path = "logs/xmovie_dir_index_2026-10-27.json"
    idx_norms = [norm(e["name"]) for e in json.load(open(idx_path))] if os.path.exists(idx_path) else []
    if not idx_norms: print("WARN 无库内索引，撞库未做")

    out = {}
    for kind, q, cat in QUERIES:
        rows, err = fetch(kind, q, cat)
        # 站长 10:3x 批准修法：apibay user 查询回包 added 全 0，时间窗过滤会杀光候选。
        # 改按 q.php 默认返回序（≈站内最新序）取 top，**不信 timestamp**；
        # 每条附「发布时间字段读数 + 是否可信」，added=0 一律标时间未证实——不许把老片当新片放行。
        rec = {"err": err, "mode": "q.php默认时间序(不信timestamp)"}
        if rows is None:
            out[kind] = rec; continue
        cands, skipped = [], []
        for r in rows[:80]:
            n = r["name"]; ih = r["info_hash"].upper()
            araw = str(r.get("added") or "0")
            time_ok = araw.isdigit() and float(araw) > 1e8  # 可信=合法 epoch
            reason = None
            if BAD.search(n): reason = "枪版"
            elif int(r.get("seeders") or 0) < 1: reason = "0做种"
            elif int(r.get("size") or 0) < 80*1024*1024: reason = "体积过小"
            elif ih in tasks: reason = "任务表已有 %s" % tasks[ih]
            elif in_library(n, idx_norms): reason = "库内撞名"
            (skipped if reason else cands).append(
                {"name": n, "ih": ih, "size": int(r.get("size") or 0), "cat": str(r.get("category")),
                 "user": str(r.get("username")),
                 "seeders": int(r.get("seeders") or 0), "leechers": int(r.get("leechers") or 0),
                 "added_raw": araw,
                 "added": datetime.fromtimestamp(float(araw)).strftime("%m-%d %H:%M") if time_ok else "未证实",
                 "time_ok": time_ok,
                 "score": round(score(n), 1), "reason": reason})
        cands.sort(key=lambda x: (-x["score"], -x["size"]))
        rec["top"] = cands[:6]; rec["n_rows"] = len(rows); rec["skipped"] = skipped[:40]
        out[kind] = rec

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    path = "logs/tpb_scan_%s.json" % datetime.now().strftime("%Y-%m-%d")
    old = {}
    if os.path.exists(path):
        try: old = json.load(open(path))
        except Exception: pass
    old[stamp] = out
    json.dump(old, open(path, "w"), ensure_ascii=False, indent=1)
    print("== TPB 扫描 %s ==" % stamp)
    for kind, rec in out.items():
        print("[%s] rows=%s err=%s mode=%s" % (kind, rec.get("n_rows"), rec.get("err"), rec.get("mode")))
        for c in rec.get("top", []):
            print("   %+6.1f %s | %.2fG S%s L%s %s %s | 时间读数=%s 可信=%s" % (c["score"], c["ih"][:8], c["size"]/2**30,
                  c["seeders"], c["leechers"], c["added"], c["name"][:64], c["added_raw"], c["time_ok"]))
    print("-> %s" % path)

# ---------------- 固化自测 / 预演（2026-11-02 工具固化单，代码运维） ----------------
# 两个死单回归（logs/tpb_fix_report_2026-11-02.md）：
#   死单一：cat 写死 200/208 → BONE 实落 207/201、jajaja 落 208/205 → 建档至今 TOP 恒空；
#   死单二：撞库用通用发布 token（1080p/web/hevc…）子串命中 → 吉卜力全套误杀。
# 另回归 apibay 占位行（id=0）过滤——10-24「timestamp 全 0」误诊源头。

SAMPLE_ROWS = [  # 混合样例：真行×3（含 BONE 吉卜力）+ 占位行 + 0 做种 + 枪版
    {"id": "1", "name": "Spirited Away 2001 1080p WEB-DL H265 DDP5.1 BONE", "info_hash": "02B8FD3F" + "A" * 32,
     "seeders": "365", "leechers": "10", "size": "2469606121", "added": "1730490300", "category": "207", "username": "BONE"},
    {"id": "2", "name": "Princess Mononoke 1997 1080p WEB-DL x265 BONE", "info_hash": "113F3444" + "B" * 32,
     "seeders": "14", "leechers": "2", "size": "2651707852", "added": "1730490180", "category": "201", "username": "BONE"},
    {"id": "3", "name": "Gilded Age S04E01 1080p WEB-DL x265 DDP5.1 MeGusta", "info_hash": "CC" + "C" * 38,
     "seeders": "111", "leechers": "5", "size": "1808794357", "added": "1730516100", "category": "205", "username": "jajaja"},
    {"id": "0", "name": "No hits found. Try different keywords", "info_hash": "0" * 40,
     "seeders": "0", "leechers": "0", "size": "0", "added": "0", "category": "0", "username": ""},
    {"id": "4", "name": "Dead Seed 2020 1080p x265", "info_hash": "DD" + "D" * 38,
     "seeders": "0", "leechers": "0", "size": "900000000", "added": "1730400000", "category": "200", "username": "x"},
    {"id": "5", "name": "CAM Flop 2021 TS", "info_hash": "EE" + "E" * 38,
     "seeders": "50", "leechers": "1", "size": "700000000", "added": "1730400000", "category": "200", "username": "x"},
]
# 库内目录索引样例（吉卜力中文目录——旧通用 token 版就是在这里被误杀的）
SAMPLE_LIB = ["千与千寻 2001 (吉卜力)", "幽灵公主 1997", "镀金时代 S03 全集", "某不相干片 2019 1080p"]


def _pipeline(rows, tasks=None, idx_norms=None):
    """复刻 main() 的候选筛选（离线，可用注入数据）。"""
    tasks = tasks or set()
    idx_norms = idx_norms if idx_norms is not None else [norm(e) for e in SAMPLE_LIB]
    rows = [r for r in rows if str(r.get("id")) != "0"]  # 占位行过滤（同 fetch()）
    kept, killed = [], {}
    for r in rows:
        n = r["name"]
        ih = r["info_hash"].upper()
        araw = str(r.get("added") or "0")
        time_ok = araw.isdigit() and float(araw) > 1e8
        reason = None
        if BAD.search(n): reason = "枪版"
        elif int(r.get("seeders") or 0) < 1: reason = "0做种"
        elif int(r.get("size") or 0) < 80 * 1024 * 1024: reason = "体积过小"
        elif ih in tasks: reason = "任务表已有"
        elif in_library(n, idx_norms): reason = "库内撞名"
        if reason:
            killed[reason] = killed.get(reason, 0) + 1
        else:
            kept.append({"name": n, "score": round(score(n), 1), "time_ok": time_ok})
    return kept, killed


def selftest():
    # 1) 占位行过滤（10-24 误诊源头）
    kept, killed = _pipeline(SAMPLE_ROWS)
    assert not any("No hits" in k["name"] for k in kept), "占位行漏进候选"
    print("selftest[占位行过滤] OK")
    # 2) 死单一：cat 不再写死——QUERIES 必须无 cat 参数（fetch 不带 &cat=）
    for _, _, cat in QUERIES:
        assert cat is None, "cat 又写死了，死单一会复发"
    urls = []
    real_get = get
    globals()["get"] = lambda url, *a, **k: (urls.append(url), json.dumps(SAMPLE_ROWS))[1]
    try:
        fetch("movie", "user%3A.BONE.", QUERIES[0][2])
    finally:
        globals()["get"] = real_get
    assert urls and all("&cat=" not in u for u in urls), urls
    print("selftest[cat 死单修复·查询无 cat] OK")
    # 3) 死单二：吉卜力候选不被通用 token 误杀（旧版会 1080p/web/hevc/bone 子串命中库目录）
    assert in_library("Spirited Away 2001 1080p WEB-DL H265 DDP5.1 BONE", [norm(x) for x in SAMPLE_LIB]) is False
    # 真撞名必须仍能命中（同英文名在库）
    assert in_library("Spirited Away 2001 1080p BluRay", [norm("Spirited Away 2001 1080p BluRay x264")]) is True
    # 有效词不足 2 个 → 放行
    assert in_library("BONE 1080p 2021", [norm("随便什么")]) is False
    kept, killed = _pipeline(SAMPLE_ROWS)
    assert len(kept) == 3 and killed.get("枪版") == 1 and killed.get("0做种") == 1, (kept, killed)
    print("selftest[撞库 token·宁漏不误杀+真撞名仍中] OK")
    # 4) 时间读数可信标记
    assert all(k["time_ok"] for k in kept), "样例真行时间应全可信（11:25 补跑全可信实证）"
    print("selftest[时间读数标记] OK")
    print("SELFTEST PASS")
    return 0


def dryrun():
    print("[DRY-RUN] 零联网预演：内置样例行过筛选管线")
    kept, killed = _pipeline(SAMPLE_ROWS, tasks={("FF" + "F" * 38)})
    print("  候选 %d ｜ 淘汰统计 %s" % (len(kept), killed))
    for k in sorted(kept, key=lambda x: -x["score"]):
        print("   TOP  %+6.1f %s (时间可信=%s)" % (k["score"], k["name"], k["time_ok"]))
    print("[DRY-RUN] 未访问 apibay / 未登录 DS。实跑去掉 --dry-run。")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="零联网：内置样例行走筛选管线，验形状与两死单修复")
    ap.add_argument("--selftest", action="store_true", help="回归自测：占位行/cat死单/撞库误杀三案")
    _a = ap.parse_args()
    if _a.selftest or _a.dry_run:
        sys.exit(selftest() if _a.selftest else dryrun())
    main()
