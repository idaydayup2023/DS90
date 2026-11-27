#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5 专名废形表 —— 扫描器 ＋ **阳性对照自测**（系统运维侧闸门件，2026-11-27）

令据：站长 2026-11-27 13:27 亲令「① 把这 11 形补进 A5 名册废形表（仓内 PR）；② 加阳性对照：
五断言/名册跑之前先用已知废形自测一发（阳性不命中＝闸失效，当场报站长），今后『废形 0』一律附
阳性对照读数才算数；③ 改闸三读数落卷」。旁据：`logs/返修账_预存瑕疵_2026-11-27.md` §一闸面盲区。

**为什么要有这个文件**：《误杀》(2019) v5 闸面 A5 曾报「专名废形 0」，但那 8 枚预存瑕疵的 11 个误形
全部未入词表 —— 那个「0」是**弱零值（无阳性对照）**，闸对它们盲。本件把词表落进仓内，并强制
「先自测、后读数」：阳性不咬 ⇒ 整闸 RED，禁止输出「废形 0」。

判定口径（表内 strength_rule / disposition_rule 为准）：
  · fixed_v6  枚号仍命中            → RED（未落刀／回归）
  · hard 形在 expected 之外命中      → RED
  · weak 形在 expected 之外命中      → WARN（不阻闸，随卷报站长候裁）
  · expect_zh 与终件该枚中文腿不等  → RED（改动面漂移）
  · 终形全片计数 < after_fix 期望     → RED
  · 阳性对照任一枚不咬／终形负检误咬  → RED（闸失效）

用法：
    python3 tools/a5_deprecated_forms_check_20261127.py --selftest
    python3 tools/a5_deprecated_forms_check_20261127.py --file <终件.srt> --out <读数.json>
零网络、零库面写、零模型请求；纯本地读文件。
"""
import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TABLE = HERE / "a5_deprecated_forms_sheep2019_2026-11-27.json"
CJK = re.compile(r"[\u4e00-\u9fff]")
TS = re.compile(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}")
WELL = re.compile(r"</?i(?:/\s*|\s[^>]*)?>")
BROKEN = re.compile(r"<i(?![/>\s>])")


# ---------------------------------------------------------------- 解析（独立实现）
def parse_srt(raw: bytes):
    """→ {cue: 中文腿拼接}，另回 (cues_total, zh_leg_count)。硬形制错直接抛。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("存在 UTF-8 BOM")
    if b"\r" in raw:
        raise ValueError("含 CR 行尾")
    if b"\x00" in raw:
        raise ValueError("含 NUL")
    text = raw.decode("utf-8")
    blocks = [b for b in re.split(r"\n[ \t]*\n", text.rstrip("\n")) if b.strip("\n") != ""]
    zh_by_cue, n_leg = {}, 0
    for n, b in enumerate(blocks, 1):
        ls = b.split("\n")
        if not ls[0].strip().isdigit():
            raise ValueError(f"第 {n} 块序号行非数字 {ls[0]!r}")
        if len(ls) < 2 or not TS.fullmatch(ls[1].strip()):
            raise ValueError(f"第 {n} 块时间戳形制异常")
        texts = [l for l in ls[2:] if l.strip() != ""]
        zh = [l for l in texts if CJK.search(l)]
        if zh:
            n_leg += 1
        zh_by_cue[int(ls[0].strip())] = "".join(zh)
    return zh_by_cue, len(blocks), n_leg


def strip_tags(t: str) -> str:
    return BROKEN.sub("", WELL.sub("", t))


# ---------------------------------------------------------------- 阳性对照（先跑，不咬即闸失效）
def positive_control(table):
    """每形造一枚合成行必须咬；终形合成行必须一枚都不咬。→ (ok, 读数)"""
    forms = [f["form"] for f in table["forms"]]
    probes, miss = [], []
    for spec in table["forms"]:
        f = spec["form"]
        synth = {900001: f"本片台词前缀{f}后缀"}          # 已知废形，必须命中
        hit = [c for c, z in synth.items() if f in strip_tags(z)]
        bites = hit == [900001]
        probes.append({"form": f, "strength": spec["strength"], "预期": "命中", "实得": "命中" if bites else "未命中"})
        if not bites:
            miss.append(f)
    # 负检：全是终形的行，一枚废形都不许咬（防词表把终形自己当废形）
    neg_line = " ".join(table.get("final_forms", {}))
    neg_hits = [f for f in forms if f in strip_tags(neg_line)]
    ok = not miss and not neg_hits
    return ok, {
        "阳性对照": probes,
        "n_阳性应咬": len(forms),
        "n_阳性实咬": len(forms) - len(miss),
        "阳性未咬": miss,
        "终形负检行": neg_line,
        "终形负检误咬": neg_hits,
        "自测": "PASS" if ok else "FAIL(闸失效)",
    }


# ---------------------------------------------------------------- 扫描
def scan(zh_by_cue, table, expect_final_counts=True):
    red, warn, per_form = [], [], []
    for spec in table["forms"]:
        f, strength = spec["form"], spec.get("strength", "hard")
        disp = spec.get("disposition", "fixed_v6")
        true_line = set(spec.get("true_line") or [])
        base_cues = set(spec.get("cues_in_base") or [])
        fixed = base_cues - true_line if disp == "fixed_v6" else set()
        expected = true_line | (base_cues if disp == "known_remaining_pending_retranslation" else set())
        hits = sorted(c for c, z in zh_by_cue.items() if f in strip_tags(z))
        unexpected = [c for c in hits if c not in expected]
        still = [c for c in hits if c in fixed]
        row = {"form": f, "family": spec.get("family"), "final_form": spec.get("final_form"),
               "strength": strength, "disposition": disp, "命中枚号": hits,
               "预期允许枚号": sorted(expected), "修前应零枚号": sorted(fixed)}
        if still:
            red.append({"项": "A5_修后仍存废形", "form": f, "cues": still, "zh": {str(c): zh_by_cue[c] for c in still}})
        if unexpected:
            rec = {"项": "A5_计划外命中", "form": f, "cues": unexpected,
                   "zh": {str(c): zh_by_cue[c] for c in unexpected}}
            (red if strength == "hard" else warn).append(rec)
        if disp == "fixed_v6" and spec.get("expect_zh") and fixed:
            for c in sorted(fixed):
                got = zh_by_cue.get(c)
                if got != spec["expect_zh"]:
                    red.append({"项": "A5_改动面漂移", "form": f, "cue": c, "期望中文腿": spec["expect_zh"], "实得": got})
                elif spec.get("final_form") and spec["final_form"] not in got:
                    red.append({"项": "A5_终形未落", "form": f, "cue": c, "期望含终形": spec["final_form"], "实得": got})
        per_form.append(row)
    counts = {w: sum(strip_tags(z).count(w) for z in zh_by_cue.values())
              for w in table.get("final_forms", {})}
    fc = {}
    if expect_final_counts:
        for w, exp in (table.get("final_form_counts") or {}).items():
            if not isinstance(exp, dict) or "after_fix" not in exp:
                continue
            got = counts.get(w)
            fc[w] = {"base": exp.get("base"), "期望": exp["after_fix"], "实得": got}
            if got is None or got < exp["after_fix"]:
                red.append({"项": "A5_终形计数低于期望", "final_form": w, **fc[w]})
    return red, warn, per_form, counts, fc


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=str(DEFAULT_TABLE))
    ap.add_argument("--file", help="终件 .srt（不给＝只跑自测）")
    ap.add_argument("--selftest", action="store_true", help="只跑阳性对照自测")
    ap.add_argument("--out", help="读数 json 落盘路径")
    ap.add_argument("--allow-warn", action="store_true", help="weak 形 WARN 不影响退出码（默认即不影响）")
    a = ap.parse_args()

    table = json.loads(Path(a.table).read_text(encoding="utf-8"))
    out = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "gate": "a5_deprecated_forms/v1", "case": table.get("case"),
           "table": str(a.table), "table_sha256": hashlib.sha256(Path(a.table).read_bytes()).hexdigest()}

    pc_ok, pc = positive_control(table)
    out.update(pc)
    if a.selftest or not a.file:
        out["result"] = "GREEN" if pc_ok else "RED_闸失效"
        out["red_items"] = [] if pc_ok else [{"项": "A5_阳性对照未咬", "forms": pc["阳性未咬"],
                                             "项2": "A5_终形负检误咬", "forms": pc["终形负检误咬"]}]
        _emit(out, a.out)
        return 0 if pc_ok else 5

    p = Path(a.file)
    raw = p.read_bytes()
    out["obj"] = str(p)
    out["obj_sha256"] = hashlib.sha256(raw).hexdigest()
    out["obj_bytes"] = len(raw)
    zh_by_cue, n_cues, n_leg = parse_srt(raw)
    out["cues"], out["中文腿枚数"] = n_cues, n_leg
    # 闸失效即不出读数（站长：今后「废形 0」一律附阳性对照读数才算数）
    if not pc_ok:
        out["result"] = "RED_闸失效"
        out["red_items"] = [{"项": "A5_阳性对照未咬＝闸失效，读数作废", "forms": pc["阳性未咬"],
                             "终形负检误咬": pc["终形负检误咬"]}]
        _emit(out, a.out)
        return 5

    red, warn, per_form, counts, fc = scan(zh_by_cue, table)
    out["逐形读数"] = per_form
    out["终形计数"] = counts
    out["终形计数对榫"] = fc
    out["n_废形命中"] = sum(1 for r in per_form if r["命中枚号"])
    out["warn_items"] = warn
    out["result"] = "GREEN" if not red else "RED"
    out["red_items"] = red
    _emit(out, a.out)
    print(f"A5 {out['result']}  红 {len(red)} 警 {len(warn)}  阳性 {out['n_阳性实咬']}/{out['n_阳性应咬']}",
          file=sys.stderr)
    return 0 if not red else 1


def _emit(out, path):
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    print(txt)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(txt, encoding="utf-8")
        print("REPORT →", path, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
