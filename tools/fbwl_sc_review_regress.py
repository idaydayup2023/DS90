#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_review 两处「已保留的未报备改动」回归测试（站长 11-07 裁定③：保留+补报备入卷，
并纳入代码运维 PR 的回归测试；作者不得再自改 sc_review）。

两条用例：
  U1 无 i 批级记录被跳过：journal 读入遇批级记录（无 "i" 键，如 batch_first_index）
     必须 continue 跳过、不崩、不把无 i 记录并进 by_i；有 i 且属于 cues 的才并入，
     已有条目不被覆盖（首写为准）。
  U2 全量重写不丢段：review.jsonl 由「journal 合并 + 跑批新增」统一按 i 排序全量重写
     （零零发丢段同型 bug 的修法），条目一条不丢、不重复、按 i 有序；重写幂等。

除行为用例（对照实现逐语义复刻，可离线跑 CI）外，另做**源码钉**：给定 sc_review.py
路径时核两条姿势仍在源码里（`if "i" not in o:` 跳过守卫、review.jsonl 全量重写
`open(rp, "w"` 且无 append 写法）——姿势被改动即红，作「作者不得再自改」的哨兵。

用法: python3 tools/fbwl_sc_review_regress.py [--src tmp_fbwl_work/sc_review.py]
退出码 0=绿（源码钉缺件时打 SKIP 也算绿，但交卷卷必须点名实跑读数）；1=红。
"""
import argparse
import json
import os
import re
import sys
import tempfile


# ---- 对照实现（与 sc_review.py 已批复行为逐语义一致的参考件） ----
def merge_journal(by_i, journal_rows, cues):
    for o in journal_rows:
        if not isinstance(o, dict):
            continue
        if "i" not in o:
            continue                                    # U1 守卫：批级记录跳过
        if o["i"] not in by_i and o["i"] in cues:
            by_i[o["i"]] = {"i": o["i"], "en": cues[o["i"]]["en"],
                            "zh": o["zh"], "tag": o["tag"]}
    return by_i


def rewrite_review(by_i, path):
    rows = sorted(by_i.values(), key=lambda r: r["i"])  # U2 守卫：全量重写
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def case_u1():
    fails = []
    cues = {i: {"en": "en%d" % i} for i in range(1, 6)}
    journal = [
        {"batch_first_index": 1, "stat": "batch-start"},          # 无 i 批级记录
        "非 dict 行（读入方已滤，双保险）",
        {"i": 1, "zh": "台词1 正常中文", "tag": "ok"},
        {"i": 99, "zh": "越界", "tag": "ok"},                     # 不在 cues
        {"i": 2, "zh": "先写", "tag": "ok"},
    ]
    by_i = {2: {"i": 2, "en": "en2", "zh": "先写", "tag": "ok"}}
    try:
        merge_journal(by_i, [r for r in journal if isinstance(r, dict)], cues)
    except Exception as e:  # noqa: BLE001
        fails.append("U1 崩在批级记录上: %r" % e)
        return fails
    if set(by_i) != {1, 2}:
        fails.append("U1 并入结果错: %s（无 i 记录应跳过、越界 i 不应并入）" % sorted(by_i))
    if by_i[2]["zh"] != "先写":
        fails.append("U1 已有条目被后写覆盖")
    return fails


def case_u2():
    fails = []
    d = tempfile.mkdtemp(prefix="sc_regress_")
    p = os.path.join(d, "review.jsonl")
    by_i = {}
    for i in range(1, 11):                                       # 5 条跑批 + 5 条 journal 合并
        by_i[i] = {"i": i, "en": "en%d" % i, "zh": "台词%d 正常中文" % i, "tag": "ok"}
    rewrite_review(by_i, p)
    got = [json.loads(ln) for ln in open(p, encoding="utf-8") if ln.strip()]
    if [g["i"] for g in got] != list(range(1, 11)):
        fails.append("U2 全量重写丢段/乱序: %s" % [g["i"] for g in got])
    b1 = open(p, "rb").read()
    rewrite_review(by_i, p)
    if open(p, "rb").read() != b1:
        fails.append("U2 重写不幂等")
    # journal-only 条目（曾丢段的本体）必须在盘上
    d2 = tempfile.mkdtemp(prefix="sc_regress2_")
    p2 = os.path.join(d2, "review.jsonl")
    cues = {i: {"en": "en%d" % i} for i in range(1, 4)}
    by = {}
    merge_journal(by, [{"i": 2, "zh": "journal 独有", "tag": "corrected"}], cues)
    by[1] = {"i": 1, "en": "en1", "zh": "跑批", "tag": "ok"}
    rewrite_review(by, p2)
    got2 = {json.loads(ln)["i"] for ln in open(p2, encoding="utf-8") if ln.strip()}
    if 2 not in got2:
        fails.append("U2 journal 合并条目未落盘（丢段同型 bug 复发）")
    return fails


def case_source_pins(src):
    fails = []
    if not os.path.exists(src):
        print("SKIP: 源码钉缺件（sc_review.py 不在 %s）——交卷卷须点名实跑读数" % src)
        return fails
    code = open(src, encoding="utf-8").read()
    if not re.search(r'if\s+"i"\s+not in o\s*:\s*\n\s*continue', code):
        fails.append("P1 源码钉红：journal 读入的无 i 批级记录跳过守卫不见了")
    if not re.search(r'open\(rp,\s*"w"', code):
        fails.append("P2 源码钉红：review.jsonl 全量重写（open(rp,\"w\")）不见了")
    if re.search(r'open\(rp,\s*"a"', code):
        fails.append("P2 源码钉红：review.jsonl 出现 append 写法（台账规矩禁止）")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="tmp_fbwl_work/sc_review.py")
    a = ap.parse_args()
    fails = case_u1() + case_u2() + case_source_pins(a.src)
    if fails:
        for f in fails:
            print("FAIL:", f)
        print("SC_REVIEW REGRESS FAIL %d 项" % len(fails))
        sys.exit(1)
    print("SC_REVIEW REGRESS PASS（U1 无i批级记录跳过 / U2 全量重写不丢段"
          + (" / 源码钉绿" if os.path.exists(a.src) else " / 源码钉 SKIP") + "）")


if __name__ == "__main__":
    main()
