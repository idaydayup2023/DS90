#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审校件完整性自检（journal 合并丢段 bug 的收口断言，11-07 站长令落地）。

修复版（代码运维 11-07，站长 16:3x 裁定②：C/D 补漏 + tag 词表 + 重复 i 报错 + A 连续性；
被闸的人不许改闸，本文件只准代码运维在本仓 PR 内修改）：
  R 重复：review.jsonl 同 i 出现 >1 行 → FAIL（报错，不许后写覆盖——旧版后写读法
          让「先 miss 后 ok」两条同 i 藏住 miss，C 闸形同虚设）。
  T 词表：tag ∉ {ok, corrected, miss} → FAIL（tag 漂移如 OK/mis 旧版全算非 miss）。
  A 覆盖：review.jsonl 的 i 集合 == cues.json 全量（无缺无多）
          + cues 的 i 必须恰为 1..N 连续无缺无重（防 cues.json 与 review 同缺假绿）。
  B 在场：每条 (i, zh, tag) 在 journal（按给定顺序后写覆盖）里逐字有源。
          （B 只证 review≈journal 自洽，属作者侧证据，不替代五样独立断言。）
  C 状态：任一行 tag=='miss' → FAIL（rerun 收口后跑必绿；行级扫描，配合 R 无藏行）。
  D 形态：每行含汉字，或「含数字且全落白名单」——纯标点/纯空白（`...`/`———`）
          无数字即 FAIL（旧版白名单含 .,—，纯标点占位符被放行）。
  E 思考流：含汉字的行命中推理标记/英文标记/超长(>120)/英比>0.6/8字复读环≥3
          → SUSPECT 非空即 FAIL，逐条人工判（豁免账由代码运维签核，作者不得自改）。
输出聚合 sha（统一 i,zh,tag 三键、按 i 排序、sort_keys）——交卷卷「零丢失」证据。
与 tools/fbwl_stor_gate_20261107.py 五样同口径；本脚本是作者侧对照读数。

用法: python3 tools/fbwl_review_selfcheck.py [review.jsonl] [journal ...]
                                        [--waive PATH|none] [--selftest]
默认: tmp_fbwl_work/fbwl_run/review.jsonl + main_journal.jsonl rerun_miss.jsonl
豁免账默认: logs/fbwl_stor_adjudicate_2026-11-07.json（代码运维签核件；--waive none 停用）
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from collections import Counter

HAN = re.compile(r"[\u4e00-\u9fff]")
NUM = re.compile(r"^[\d\s\.,:;~%\-–—/]+$")
HASDIGIT = re.compile(r"[0-9]")
ALLOWED = {"ok", "corrected", "miss"}
MARK = ["用户要求", "让我", "我应该", "我应", "首先", "接下来", "翻译成", "以下是",
        "抱歉", "作为AI", "作为 AI", "思考", "推理", "直译", "意译", "这句话", "意思是"]
ENMARK = re.compile(r"\b(the user|i need|let me|translate|meaning|should be|first[, ]|note[:：])\b", re.I)
DEFAULT_WAIVE = "logs/fbwl_stor_adjudicate_2026-11-07.json"


def read_jsonl(path):
    out = []
    try:
        fh = open(path, encoding="utf-8")
    except FileNotFoundError:
        return out
    with fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                out.append({"__bad__": ln[:60]})
    return out


# —— 译评型思考流结构判据（站长 11-07 22:0x 令；与 fbwl_stor_gate_20261107.py 逐字同口径，
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


def suspect(zh):
    """E 样探测器——与 fbwl_stor_gate_20261107.py 逐字同口径。命中回原因，否则 None。"""
    han_n = len(HAN.findall(zh))
    en_ratio = (len(zh) - han_n) / max(len(zh), 1)
    if any(m in zh for m in MARK):
        return "标记"
    if ENMARK.search(zh):
        return "EN标记"
    if len(zh) > 120:
        return "超长%d" % len(zh)
    if re.search(r"[A-Za-z]", zh) and en_ratio > 0.6:
        return "英比%.2f" % en_ratio   # 仅含 ASCII 字母的行才谈英比（数数行/符号行不误咬）
    vp = yi_ping_type(zh)
    if vp:
        return vp
    grams = [zh[k:k + 8] for k in range(0, max(len(zh) - 7, 0), 2)]
    gc = Counter(grams)
    if any(v >= 3 for v in gc.values()):
        return "复读"
    return None


def check(review_rows, journal_rows, cue_ids, waive=frozenset()):
    """返回 (fails, infos, agg_sha)。fails 空 = 全绿。"""
    fails, infos = [], []

    badline = [r["__bad__"] for r in review_rows if "__bad__" in r]
    if badline:
        fails.append("JSON FAIL review 坏行: %s" % badline[:5])
    rows = [r for r in review_rows if "__bad__" not in r]

    # R 重复 i：报错，不许后写覆盖
    cnt = Counter(r.get("i") for r in rows)
    dup = sorted(i for i, n in cnt.items() if n > 1)
    if dup:
        fails.append("R重复 FAIL 同 i 多行（禁后写覆盖，报作者查写入方）: %s" % dup[:10])

    # T 词表
    badtag = [i for r, i in ((r, r.get("i")) for r in rows) if r.get("tag") not in ALLOWED]
    if badtag:
        fails.append("T词表 FAIL tag∉{ok,corrected,miss}: %s" % badtag[:10])

    # A 覆盖 + 连续性
    ids = set(cnt)
    cues = set(cue_ids)
    if len(cue_ids) != len(cues):
        fails.append("A覆盖 FAIL cues.json 自身 i 有重复")
    n = len(cues)
    gaps = sorted(cues - set(range(1, n + 1)))
    if gaps:
        fails.append("A连续 FAIL cues i 非 1..N（越界/缺）: %s" % gaps[:10])
    missing, extra = sorted(cues - ids), sorted(ids - cues)
    if missing or extra:
        fails.append("A覆盖 FAIL 缺=%s 多=%s" % (missing[:10], extra[:10]))

    # B 在场（journal 后写覆盖读法）
    jr = {}
    for o in journal_rows:
        if "i" in o and "tag" in o and "zh" in o:
            jr[o["i"]] = {"i": o["i"], "zh": o["zh"], "tag": o["tag"]}
    rv = {r["i"]: {"i": r["i"], "zh": r["zh"], "tag": r["tag"]}
          for r in rows if all(k in r for k in ("i", "zh", "tag"))}
    unsourced = [i for i, r in rv.items() if jr.get(i) != r]
    if unsourced:
        fails.append("B在场 FAIL 无源/不符（rerun 判定必须落 journal）: %s" % unsourced[:10])
    never = [i for i in sorted(cues) if i not in jr]
    if never:
        fails.append("B在场 FAIL 有 cue 从未进审校 journal: %s" % never[:10])

    # C 状态：行级扫 miss（R 已禁重复，行级=终态）
    resid = sorted(i for r, i in ((r, r.get("i")) for r in rows) if r.get("tag") == "miss")
    if resid:
        fails.append("C状态 FAIL miss 残留: %s" % resid[:10])

    # D 形态 / E 思考流（只判有正文的行）
    bad, sus = [], []
    for r in rows:
        zh = str(r.get("zh", ""))
        if not HAN.search(zh):
            if not (HASDIGIT.search(zh.strip()) and NUM.match(zh.strip())):
                bad.append(r.get("i"))     # 纯标点/空白占位
            continue
        if HASDIGIT.search(zh.strip()) and NUM.match(zh.strip()):
            continue                        # 数字白名单行（数数行）E 样不碰
        if r.get("tag") != "miss" and r.get("i") not in waive:
            hit = suspect(zh)
            if hit:
                sus.append({"i": r.get("i"), "tag": r.get("tag"), "why": hit,
                            "zh": zh[:60]})
    if bad:
        fails.append("D形态 FAIL 无汉字且无数字（纯标点占位）: %s" % bad[:10])
    if sus:
        fails.append("E思考流 FAIL SUSPECT=%d 条（豁免后；逐条人工判，豁免账须代码运维签核）:"
                     % len(sus))
        fails.extend("    i=%s tag=%s [%s] %r" % (s["i"], s["tag"], s["why"], s["zh"])
                     for s in sus[:20])

    # 聚合 sha：口径与旧版逐字一致（三键投影、按 i 排序、sort_keys）
    h = hashlib.sha256()
    for i in sorted(rv):
        h.update(json.dumps(rv[i], ensure_ascii=False, sort_keys=True).encode() + b"\n")
    infos.append("entries=%d tags=%s" % (len(rows), dict(Counter(r.get("tag") for r in rows))))
    return fails, infos, h.hexdigest()


def selftest():
    import os, tempfile
    base = tempfile.mkdtemp(prefix="selfcheck_selftest_")
    fails = []

    def write_fixtures(review_lines, cue_n=5, journal_lines=None):
        cues = [{"i": i, "en": "en%d" % i, "zh": ""} for i in range(1, cue_n + 1)]
        jp = os.path.join(base, "cues.json")
        json.dump(cues, open(jp, "w", encoding="utf-8"))
        good = [{"i": i, "zh": "台词%d 正常中文" % i, "tag": "ok"} for i in range(1, cue_n + 1)]
        rows = review_lines if review_lines is not None else good
        rows = rows + good if review_lines == "extend" else rows
        jrows = journal_lines if journal_lines is not None else rows
        return rows, jrows, [c["i"] for c in cues]

    def want_fail(name, rows, jrows=None, cues=None, waive=frozenset(), token=None):
        r, j, c = write_fixtures(rows)
        f, _, _ = check(r, jrows if jrows is not None else j, cues if cues else c, waive)
        blob = "\n".join(f)
        if not f or (token and token not in blob):
            fails.append("%s: 想 FAIL(%s)，实得 %s" % (name, token, blob[:80] or "PASS"))

    def want_pass(name, rows=None, **kw):
        r, j, c = write_fixtures(rows)
        f, _, _ = check(r, kw.get("jrows", j), kw.get("cues", c), kw.get("waive", frozenset()))
        if f:
            fails.append("%s: 想 PASS，实得 %s" % (name, "\n".join(f)[:120]))

    good = [{"i": i, "zh": "台词%d 正常中文" % i, "tag": "ok"} for i in range(1, 6)]
    want_pass("健康夹具")
    # 聚合 sha 稳定性：同数据两次同值；改一行即换值
    _, _, c5 = write_fixtures(good)
    _, _, s1 = check(good, good, c5)
    _, _, s2 = check(good, good, c5)
    if s1 != s2:
        fails.append("agg sha 不稳定")
    mod = [dict(good[0], zh="换字") ] + good[1:]
    _, _, s3 = check(mod, mod, c5)
    if s3 == s1:
        fails.append("agg sha 对改动不敏感")
    want_fail("R 重复 i（后写 ok 藏 miss）", good + [{"i": 3, "zh": "台词3 正常中文", "tag": "ok"}], token="R重复")
    want_fail("T tag 词表漂移", [dict(good[0], tag="OK")] + good[1:], token="T词表")
    want_fail("A cues 与 review 同缺(断号)", good[:4], cues=[1, 2, 3, 4, 6], token="A")
    want_fail("B journal 无源（rerun 未落 journal）", good, jrows=good[:4], token="B在场")
    want_fail("C miss 残留", [dict(good[0], tag="miss")] + good[1:], token="C状态")
    want_fail("D 纯标点占位", [dict(good[0], zh="...")] + good[1:], token="D形态")
    want_fail("D 纯破折号占位", [dict(good[0], zh="———")] + good[1:], token="D形态")
    want_pass("D 数字白名单行仍放行", [dict(good[0], zh="108 号")] + good[1:])
    f, _, _ = check([{"i": 1, "zh": "", "tag": "ok"}] + good[1:], good, c5)
    if not any("D形态" in x for x in f):
        fails.append("空串 zh 未被 D 拦")
    want_fail("E 思考流（含汉字推理腔）", [dict(good[0], zh="让我想想这句话的意思，用户要求直译。")] + good[1:], token="E思考流")
    want_fail("E 思考流（英文推理+超长，含汉字）",
              [dict(good[0], zh="I think the user wants a translation, 这句要重翻。" * 5)] + good[1:],
              token="E思考流")
    want_pass("E 豁免账生效", [dict(good[0], zh="让我帮你拿吧，正常台词。")] + good[1:], waive=frozenset({1}))
    want_fail("E 豁免不覆盖别条", [dict(good[0], zh="让我帮你拿吧，正常台词。"),
                                  dict(good[1], zh="让我帮你拿吧，这句没豁免。")] + good[2:],
              waive=frozenset({1}), token="E思考流")
    # 译评型判据绑 fixture（站长 11-07 22:0x 令）：阳性必咬、阴性零误判
    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_gate_e_samples_20261107.json")
    fix = json.load(open(fp, encoding="utf-8"))
    for p in fix["positives"]:
        if not suspect(p["zh"]):
            fails.append("E 译评型阳性漏检 i=%s %r" % (p["i"], p["zh"][:40]))
    for n in fix["negatives"]:
        v = suspect(n["zh"])
        if v:
            fails.append("E 译评型阴性误判 i=%s %r 咬=%s" % (n["i"], n["zh"][:40], v))

    if fails:
        for f in fails:
            print("FAIL:", f)
        print("SELFCHECK SELFTEST FAIL %d 项" % len(fails))
        return 1
    print("SELFCHECK SELFTEST PASS 全部用例通过（含 agg sha 稳定性）")
    return 0


def stamp(path):
    """数据源存证（站长 11-07 21:0x 令）：双读数一律带取数时刻的 mtime+size+sha256。
    今日两次「快照时点错开导致假红/假绿」（41 条 miss 旧快照案），凡无存证行的读数不算交卷。"""
    try:
        st = os.stat(path)
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        t = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return "SOURCE %s mtime=%s size=%d sha256=%s" % (path, t, st.st_size, h)
    except FileNotFoundError:
        return "SOURCE %s MISSING" % path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rest", nargs="*", help="[review.jsonl] [journal ...]")
    ap.add_argument("--waive", default="default",
                    help="豁免账 JSON 路径（{\"waive\":[i,...]}）；default=代码运维签核件；none=停用")
    ap.add_argument("--work", default="tmp_fbwl_work/fbwl_run")
    ap.add_argument("--cues", default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())

    rp = a.rest[0] if a.rest else a.work + "/review.jsonl"
    jps = a.rest[1:] if len(a.rest) >= 2 else [a.work + "/main_journal.jsonl",
                                               a.work + "/rerun_miss.jsonl"]
    cp = a.cues or a.work + "/cues.json"
    waive = frozenset()
    wp = DEFAULT_WAIVE if a.waive == "default" else (None if a.waive == "none" else a.waive)
    if wp and os.path.exists(wp):
        waive = frozenset(json.load(open(wp, encoding="utf-8"))["waive"])

    # 取数前钉存证（mtime 取在读文件之前的时刻，读数与存证同批）
    for p in [rp, cp] + list(jps) + ([wp] if wp else []):
        print(stamp(p))
    review_rows = read_jsonl(rp)
    journal_rows = [o for jp in jps for o in read_jsonl(jp)]
    cue_ids = [c["i"] for c in json.load(open(cp, encoding="utf-8"))]
    fails, infos, sha = check(review_rows, journal_rows, cue_ids, waive)
    if fails:
        for f in fails:
            print(f)
        print("SELFCHECK FAIL")
        sys.exit(1)
    print("SELFCHECK PASS %s agg_sha256=%s" % (infos[0], sha))


if __name__ == "__main__":
    main()
