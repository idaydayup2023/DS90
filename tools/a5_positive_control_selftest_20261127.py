#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5 阳性对照自测刀（站长 2026-11-27 13:27 单第 2 件：「五断言/名册跑之前先用已知废形自测一发，
阳性不命中＝闸失效，当场报站长；今后『废形 0』一律附阳性对照读数才算数」）。

用法
    python3 tools/a5_positive_control_selftest_20261127.py                 # 只跑自测
    python3 tools/a5_positive_control_selftest_20261127.py --srt <file>    # 顺带跑计数对榫＋A5 判定
    python3 tools/a5_positive_control_selftest_20261127.py --report <path> # 读数落盘（交卷须附）

退出码：0 全绿；1 阳性不命中／负例被咬／计数漂移／词表空＝**当场报站长**；2 解析硬错。
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from a5_scan_20261127 import (DEFAULT_WORDLIST, GateBlindError, count_check, gate,  # noqa: E402
                              load_wordlist, parse_cues)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wordlist", default=str(DEFAULT_WORDLIST))
    ap.add_argument("--srt", default=None, help="可选：对待审终稿顺带跑计数对榫＋A5 判定")
    ap.add_argument("--base", default=None, help="可选：sha 钉定底件，用于计数对榫的第二个读数")
    ap.add_argument("--report", default=None, help="读数落盘路径")
    ap.add_argument("--no-deferred", action="store_true", help="预存挂账也计为阻闸（严口径）")
    a = ap.parse_args()

    out = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "tool": "a5_positive_control_selftest/1", "wordlist": str(a.wordlist), "result": "RED",
           "red_items": []}
    try:
        doc = load_wordlist(a.wordlist, fail_closed=True)      # R1 空词表＝红
    except GateBlindError as e:
        out["fatal"] = str(e)
        out["red_items"].append("R1_词表缺失或为空")
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 1
    out["wordlist_sha256"] = doc["_sha256"]
    out["wordlist_entries"] = doc["_n_entries"]

    st = __import__("a5_scan_20261127").selftest(doc)
    out["positive_control"] = st
    if not st["ok"]:
        out["red_items"].append("R0_阳性对照（已知废形必须咬／真台词必须放过）")

    if a.srt:
        try:
            cues = parse_cues(Path(a.srt).read_bytes(), "srt")
        except ValueError as e:
            out["fatal"] = str(e)
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 2
        g = gate(doc, cues, allow_deferred=not a.no_deferred)
        out["a5"] = g
        if not g["ok"]:
            out["red_items"].append("A5_阻闸废形命中" if st["ok"] else "A5_阳性未全绿且仍有命中")
        if a.base:
            bc = count_check(doc, parse_cues(Path(a.base).read_bytes(), "base"))
            out["count_check"] = bc
            if not bc["ok"]:
                out["red_items"].append("R3_计数与词表漂移")
        else:
            out["count_check"] = {"ok": None, "note": "未给 --base，计数对榫未跑（交付件读数须补）"}

    out["result"] = "GREEN" if not out["red_items"] else "RED"
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(txt + "\n", encoding="utf-8")
    print(txt)
    return 0 if out["result"] == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
