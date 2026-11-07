#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""STOR 前置五样独立断言（站长 11-07 16:3x 裁定③：#6 终稿 STOR 前由代码运维跑，
作者的 selfcheck 只作对照，两份读数都进交卷卷）。

五样（全绿才建议站长发 STOR 令）：
  1 重复 i     review.jsonl 同 i 出现 >1 行 → FAIL（报错，不许后写覆盖）
  2 纯标点占位  zh 无汉字且不含数字（`...`/`———`/空白等）→ FAIL
  3 思考流混入  含汉字但命中推理标记/英比过高/超长/复读 的 SUSPECT → 非空即 FAIL，
               逐条列出人工判（判完在交卷卷里逐条销号）
  4 tag 词表    tag ∉ {ok, corrected, miss} → FAIL
  5 i 连续 1..N cues.json 的 i 必须恰为 1..N 连续无缺无重 → FAIL
参考行（不拦五样，但 STOR 时 miss 应为 0，读数给站长）：miss 残留数、journal 对账。

只读器具，不改任何被检件。用法:
  python3 tools/fbwl_stor_gate_20261107.py [workdir=tmp_fbwl_work/fbwl_run]

双读数存证（站长 11-07 21:0x 令）：输出头部逐件印 SOURCE 行（mtime+size+sha256），
无存证行的读数不算交卷——今日两次「快照时点错开导致假红/假绿」（41 条 miss 旧快照案）。
"""
import datetime
import hashlib
import json
import os
import re
import sys

W = sys.argv[1] if len(sys.argv) > 1 else "tmp_fbwl_work/fbwl_run"
WAIVE = set()
if len(sys.argv) > 2:                      # 人工判豁免账（代码运维签核），仅第3样生效
    WAIVE = set(json.load(open(sys.argv[2], encoding="utf-8"))["waive"])


def stamp(path):
    """数据源存证行：取数时刻的 mtime+size+sha256，与读数同批落卷。"""
    try:
        st = os.stat(path)
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        t = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return "SOURCE %s mtime=%s size=%d sha256=%s" % (path, t, st.st_size, h)
    except FileNotFoundError:
        return "SOURCE %s MISSING" % path


# —— 译评型思考流结构判据（站长 11-07 22:0x 令；与 fbwl_review_selfcheck.py 逐字同口径，
#    fixture 绑 tools/_gate_e_samples_20261107.json：阳性 971 必咬、阴性 29 零误判）——
META_E = ["如下：", "补充说明", "建议改", "待复核", "更准确", "多译", "漏译", "超译",
          "译为", "译作", "该译是", "这样译", "该译成", "这个译"]
TQUOTE_E = re.compile(r"[\"'“”‘’「『]\s*译|译\s*[\"'“”‘’「『]")
ALPHA_E = re.compile(r"[A-Za-z]")


def yi_ping_type(zh):
    """译评型泄漏结构判据：A 引号贴译评 / B 半角引号失衡+译评语境 / C 句级元话语。未命中回 None。"""
    if TQUOTE_E.search(zh):
        return "A译评贴引号"
    if (zh.count('"') % 2 == 1 and ALPHA_E.search(zh)
            and (re.search(r"译|评|注", zh) or any(m in zh for m in META_E))):
        return "B引号失衡+译评语"
    for m in META_E:
        if m in zh:
            return "C元话语:" + m
    return None


def _e_selftest():
    """fixture 正反例：阳性漏检或阴性误判都算不合格（rc=1）。"""
    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_gate_e_samples_20261107.json")
    fix = json.load(open(fp, encoding="utf-8"))
    fails = []
    for p in fix["positives"]:
        if not yi_ping_type(p["zh"]):
            fails.append("阳性漏检 i=%s %r" % (p["i"], p["zh"][:40]))
    for n in fix["negatives"]:
        v = yi_ping_type(n["zh"])
        if v:
            fails.append("阴性误判 i=%s %r 咬=%s" % (n["i"], n["zh"][:40], v))
    if fails:
        print("GATE E-SELFTEST FAIL %d 项" % len(fails))
        for f_ in fails:
            print(" ", f_)
        return 1
    print("GATE E-SELFTEST PASS 阳性%d/阴性%d（译评型判据绑 fixture，FBWL 971 案）" % (
        len(fix["positives"]), len(fix["negatives"])))
    return 0


if "--selftest" in sys.argv:
    sys.exit(_e_selftest())

print(stamp(W + "/review.jsonl"))
print(stamp(W + "/cues.json"))
if len(sys.argv) > 2:
    print(stamp(sys.argv[2]))

HAN = re.compile(r"[\u4e00-\u9fff]")
HASDIGIT = re.compile(r"[0-9]")
ALLOWED = {"ok", "corrected", "miss"}
MARK = ["用户要求", "让我", "我应该", "我应", "首先", "接下来", "翻译成", "以下是",
        "抱歉", "作为AI", "作为 AI", "思考", "推理", "直译", "意译", "这句话", "意思是"]
ENMARK = re.compile(r"\b(the user|i need|let me|translate|meaning|should be|first[, ]|note[:：])\b", re.I)

rows = [json.loads(ln) for ln in open(W + "/review.jsonl", encoding="utf-8") if ln.strip()]

# 1 重复 i
cnt = {}
for r in rows:
    cnt[r["i"]] = cnt.get(r["i"], 0) + 1
dup = sorted(i for i, n in cnt.items() if n > 1)

# 2 纯标点/无数字占位
punct = [r["i"] for r in rows
         if not HAN.search(r.get("zh", "")) and not HASDIGIT.search(r.get("zh", "").strip())]

# 3 思考流 SUSPECT（启发式，列出人工判）
sus = []
for r in rows:
    if r["i"] in WAIVE:
        continue
    zh = r.get("zh", "")
    if not HAN.search(zh):
        continue  # 无汉字归 2 管
    han_n = len(HAN.findall(zh))
    en_ratio = (len(zh) - han_n) / max(len(zh), 1)
    vt = yi_ping_type(zh)
    if (any(m in zh for m in MARK) or ENMARK.search(zh)
            or len(zh) > 120
            or vt  # 11-07 22:0x 站长令：译评型变体补进第3样
            or (re.search(r"[A-Za-z]", zh) and en_ratio > 0.6)):  # 11-07 收紧：仅含字母行谈英比
        sus.append({"i": r["i"], "tag": r.get("tag"),
                    "zh": zh[:80] + ("…[译评型:%s]" % vt if vt else "")})
    else:  # 复读环：同 8 字串出现 ≥3 次
        grams = [zh[k:k + 8] for k in range(0, max(len(zh) - 7, 0), 2)]
        gc = {}
        for g in grams:
            gc[g] = gc.get(g, 0) + 1
        if any(v >= 3 for v in gc.values()):
            sus.append({"i": r["i"], "tag": r.get("tag"), "zh": zh[:80] + "…[复读]"})

# 4 tag 词表
badtag = [{"i": r["i"], "tag": repr(r.get("tag"))} for r in rows if r.get("tag") not in ALLOWED]

# 5 i 连续 1..N（准绳：cues.json 的 i 集须恰为 1..N）
cues = json.load(open(W + "/cues.json", encoding="utf-8"))
cids = [c["i"] for c in cues]
n = len(cids)
gaps = sorted(set(range(1, n + 1)) - set(cids))
extra_cue = sorted(set(cids) - set(range(1, n + 1)))
cue_dup = n - len(set(cids))
# 对账：review 的 i 集 == cues 集
missing = sorted(set(cids) - set(cnt))
extra_rv = sorted(set(cnt) - set(cids))

miss_n = sum(1 for r in rows if r.get("tag") == "miss")
ok = not (dup or punct or sus or badtag or gaps or extra_cue or cue_dup or missing or extra_rv)
print("STOR_GATE %s entries=%d cues=%d" % ("PASS" if ok else "FAIL", len(rows), n))
for name, val in [("1重复i", dup), ("2标点占位", punct), ("4tag漂移", badtag),
                  ("5断号", gaps), ("5越界cue", extra_cue), ("5cue重复数", cue_dup),
                  ("5覆盖缺", missing), ("5覆盖多", extra_rv),
                  ("参考miss残留", miss_n)]:
    print("  %s: %s" % (name, (val[:12] if isinstance(val, list) else val)))
print("  3思考流SUSPECT: %d 条" % len(sus))
for s in sus[:20]:
    print("    i=%s tag=%s %r" % (s["i"], s["tag"], s["zh"]))
sys.exit(0 if ok else 1)
