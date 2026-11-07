#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rerun 熔断闸（站长 11-07 令：同一批 miss 连烧两轮不降即停手报站长）。

修复版（代码运维 11-07，站长 16:3x 裁定② + 字幕流水线需求单一；被闸的人不许改闸，
本文件只准代码运维在本仓 PR 内修改）：
  · 轮次绑收口事件：登记轮必须带 --batch <收口事件标识>，轮键 = (batch, review.jsonl
    sha256)。同 batch 重跑 = 幂等重放已登记轮，不重复计轮；不同 batch 烧出相同 miss
    集 = 新轮入账 —— 修复旧版「与上轮读数相同即去重」把真·连烧三轮吞成一轮、永远 GO。
  · 去重分支禁默认 GO：旧格式轮（无 verdict）重放 → STATE_ERROR 报站长，绝不沿用 GO。
  · 不带 --batch 只读预演（DRY-RUN）：不登记轮、不写 state —— 防半道误起闸假熔断。
  · 坏/空 state 视同 []（写回前原字节先备份 .prev 留证），禁起跑即崩。
  · state 写回：先整体备份 .prev，再 tmp+os.replace+fsync 全量重写（台账规矩）。

退出码：0=GREEN/GO  1=STOP_BREAKER  2=STATE_ERROR（含 state 异常需站长人工判）
用法:
  python3 tools/fbwl_rerun_gate.py --batch R3-strict [--work tmp_fbwl_work/fbwl_run]
                                   [--state logs/fbwl_rerun_rounds.json]
  python3 tools/fbwl_rerun_gate.py            # 只读预演，不落账
  python3 tools/fbwl_rerun_gate.py --selftest
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time


def read_review_miss(review_path):
    """当前 miss 集 = tag=='miss' 的行取 i；缺 i/tag 的行跳过（宽松读，判定从严）。"""
    cur = set()
    with open(review_path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            o = json.loads(ln)
            if o.get("tag") == "miss" and "i" in o:
                cur.add(o["i"])
    return cur


def read_state(path):
    """state 缺失/坏/空一律视同 []，并回 warning 供点名；不在只读路径上动文件。"""
    if not os.path.exists(path):
        return [], None
    try:
        d = json.load(open(path, encoding="utf-8"))
        if not isinstance(d, list):
            raise ValueError("state 不是 list: %r" % type(d).__name__)
        return d, None
    except Exception as e:  # noqa: BLE001
        return [], ("state 损坏(%r)：视同空账。写回前原文件将先备份 .prev 留证，"
                    "请站长核对是否被人删改。" % (e,))


def rounds_of(rows):
    # 账本允许 {"note":...} 说明行穿插（站长 11-07 硬控制），读轮时过滤
    return [r for r in rows if isinstance(r, dict) and "miss" in r]


def judge(rounds, cur):
    """rounds = 历轮（当前轮已作为最后一项在列）。"""
    if not cur:
        return "GREEN"
    if len(rounds) >= 2:
        if set(rounds[-2]["miss"]) & cur:
            return "STOP_BREAKER"          # 同 cue 连烧两轮仍 miss，禁第 3 轮
        if len(cur) >= len(rounds[-2]["miss"]):
            return "STOP_BREAKER"          # 整批两轮不降
    return "GO"


def file_sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def run(work, state_path, batch=None):
    """返回 (rc, lines)。batch=None → 只读预演。"""
    review = os.path.join(work, "review.jsonl")
    cur = read_review_miss(review)
    rows, warn = read_state(state_path)
    rounds = rounds_of(rows)
    out = []
    if warn:
        out.append("WARN: " + warn)

    if batch is None:
        preview = rounds + [{"miss": sorted(cur)}]
        verdict = judge(preview, cur)
        out.append("verdict=%s（DRY-RUN 只读预演，未落账：收口登记轮须带 --batch <标识>）"
                   % verdict)
        out.append("cur_miss=%d rounds=%s" % (len(cur), [len(r["miss"]) for r in rounds]))
        return (0 if verdict in ("GREEN", "GO") else 1), out

    event = file_sha(review)
    match = [r for r in rounds if r.get("batch") == batch]
    write = False
    if match:
        r = match[-1]
        if "verdict" not in r:
            rc, verdict = 2, "STATE_ERROR"
            out.append("batch=%s 已登记但无 verdict（旧格式轮）：拒绝按默认 GO 放行，报站长。" % batch)
        elif list(r["miss"]) != sorted(cur) or (r.get("event") not in (None, event)):
            rc, verdict = 2, "STATE_ERROR"
            out.append("batch=%s 已登记，但当前 miss 集/文件指纹与登记时不符——收口件被改过，"
                       "禁止同名蒙混；请另起新 --batch 标识重登并报站长。" % batch)
        else:
            verdict = r["verdict"]
            rc = 0 if verdict in ("GREEN", "GO") else (1 if verdict == "STOP_BREAKER" else 2)
            out.append("batch=%s 已登记，幂等重放 verdict，未重复计轮。" % batch)
    else:
        newr = {"t": time.strftime("%F %T"), "batch": batch, "event": event,
                "miss": sorted(cur)}
        rows.append(newr)
        rounds.append(newr)
        verdict = judge(rounds, cur)
        newr["verdict"] = verdict          # 判定随轮入账（幂等重放用）
        rc = 0 if verdict in ("GREEN", "GO") else (1 if verdict == "STOP_BREAKER" else 2)
        write = True

    if write:
        d = os.path.dirname(state_path)
        if d:
            os.makedirs(d, exist_ok=True)
        if os.path.exists(state_path):
            shutil.copy2(state_path, state_path + ".prev")   # 写回前整体备份（账本规矩）
        tmp = state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, state_path)

    out.insert(0, "verdict=%s cur_miss=%d rounds=%s batch=%s event=%s"
               % (verdict, len(cur), [len(r["miss"]) for r in rounds], batch, event))
    if verdict == "STOP_BREAKER" and len(rounds) >= 2:
        stubborn = sorted(set(rounds[-2]["miss"]) & cur)
        out.append("熔断 cue（连烧两轮仍 miss）: %s" % stubborn)
        for f in sorted(os.listdir(work)):
            if f.startswith("raw_reject_rerun_miss"):
                out.append("  两轮原始输出备查: %s/%s" % (work, f))
    out.append("state: %s%s" % (state_path, "（本次未写入）" if not write else ""))
    return rc, out


def selftest():
    import tempfile
    base = tempfile.mkdtemp(prefix="rerun_gate_selftest_")
    work = os.path.join(base, "run")
    os.makedirs(work)
    state = os.path.join(base, "rounds.json")
    fails = []

    def set_review(miss_ids, all_ids=(1, 2, 3)):
        with open(os.path.join(work, "review.jsonl"), "w", encoding="utf-8") as f:
            for i in all_ids:
                f.write(json.dumps({"i": i, "zh": "行%d" % i,
                                    "tag": "miss" if i in miss_ids else "ok"}) + "\n")

    def check(name, want_rc, want_in, batch=None):
        rc, lines = run(work, state, batch)
        blob = "\n".join(lines)
        if rc != want_rc or want_in not in blob:
            fails.append("%s: rc=%s(想%s) %s" % (name, rc, want_rc, want_in))
        return blob

    set_review({1, 2})
    check("R1 首轮 GO", 0, "verdict=GO", "R1")
    check("R2 同集连烧→熔断（正命题）", 1, "verdict=STOP_BREAKER", "R2")
    blob = check("R2 幂等重放", 1, "幂等重放", "R2")
    if "未重复计轮" not in blob:
        fails.append("R2 重放计了轮")
    n_rounds = json.load(open(state)).count
    set_review(set())
    check("R3 清零 GREEN", 0, "verdict=GREEN", "R3")
    if len(rounds_of(json.load(open(state)))) != 3:
        fails.append("轮数应为 3（R1/R2/R3），实际 %d —— 去重吞轮未修好" % n_rounds)
    # DRY-RUN 不落账（预览红绿皆可，重点：不写 state）
    set_review({1, 2})
    before = open(state, "rb").read()
    check("无 --batch 只读预演", 1, "DRY-RUN")
    if open(state, "rb").read() != before:
        fails.append("DRY-RUN 动了 state")
    # 坏 state 不崩、.prev 留证
    open(state, "w", encoding="utf-8").write("{坏 JSON")
    check("坏 state 视同 []", 0, "verdict=GO", "R4")
    if "坏 JSON" not in open(state + ".prev", encoding="utf-8").read():
        fails.append("坏 state 未备份 .prev")
    # 旧格式轮（有 batch 无 verdict）重放 → STATE_ERROR，禁默认 GO
    json.dump([{"t": "x", "miss": [1, 2], "batch": "R5"}], open(state, "w", encoding="utf-8"))
    check("旧格式轮重放 STATE_ERROR", 2, "STATE_ERROR", "R5")
    # 无 batch 的旧轮不参与幂等：新 batch 照常计轮，同集连烧触发熔断
    json.dump([{"t": "x", "miss": [1, 2]}], open(state, "w", encoding="utf-8"))
    check("旧轮后新 batch 照常计轮", 1, "verdict=STOP_BREAKER", "R5b")
    # note 行穿插允许
    json.dump([{"note": "站长说明"}, {"t": "x", "miss": [1, 2], "verdict": "GO",
                "batch": "R6", "event": file_sha(os.path.join(work, "review.jsonl"))}],
              open(state, "w", encoding="utf-8"))
    check("note 行 + 幂等", 0, "幂等重放", "R6")

    if fails:
        for f in fails:
            print("FAIL:", f)
        print("GATE SELFTEST FAIL %d 项" % len(fails))
        return 1
    print("GATE SELFTEST PASS 全部用例通过")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="tmp_fbwl_work/fbwl_run")
    ap.add_argument("--state", default="logs/fbwl_rerun_rounds.json")
    ap.add_argument("--batch", default=None,
                    help="收口事件标识（如 R3-strict）；带它才登记轮，同 batch 幂等")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    rc, lines = run(a.work, a.state, a.batch)
    print("\n".join(lines))
    sys.exit(rc)


if __name__ == "__main__":
    main()
