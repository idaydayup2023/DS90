#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ds90_source_modes 自检（代码运维 2026-11-08）。四例＝两种新命名 × 命中/不命中，
另加守卫：负控（错片/中文/错 stem/产物名）必须咬住，闸门不过 fail-closed 不降级。

fixture 依据（仓外证据卷，站长 11-08 批复新单时点名）：
  * Amos .asr.srt：cue 1368=ai 1368、逐字 0.9971、aligned_lex 1.0
  * Ghostheads/Brown.Jesus <base>.srt：cue/末条与 ai 同，逐字 0.557/0.652，
    共现 0.9095/0.9322，错片负控 0.04
跑法：python3 tools/ds90_source_modes_selftest_20261108.py ；退出码 0=全过。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ds90_source_modes_20261108 import resolve_source  # noqa: E402

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


def mk_srt(n, en_gen, zh=True, gap=2000, start_end=None):
    """生成 n 条 SRT；en_gen(i) 出该 cue 文本。"""
    out = []
    for i in range(1, n + 1):
        s_ms, e_ms = (i - 1) * gap, i * gap
        if start_end and i == n:
            e_ms = start_end
        t = lambda ms: "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60,
                                                ms // 1000 % 60, ms % 1000)
        body = en_gen(i)
        out.append("%d\n%s --> %s\n%s\n" % (i, t(s_ms), t(e_ms), body))
    return "\n".join(out).encode("utf-8")


STEM = "Amos.and.Andrew.2024.1080p.WEB-DL.x265.BONE"
GHOST = "Ghostheads.2016.1080p.WEBRip.x264.AAC5.1-YTS.MX"
BROWN = "Abhay.Nadkarni.Brown.Jesus.2025.1080p.WEBRip.x264.AAC-YTS.MX"


def ai_bilingual(n, en_gen, last_end=None):
    """ai = 中文行 + 内嵌英文行（双语核心轨）。"""
    return mk_srt(n, lambda i: "中文台词第%d句\n<i>%s</i>" % (i, en_gen(i)),
                  start_end=last_end)


def run(files, ai_bytes, stem, **kw):
    def fetch(name):
        return files[name]
    return resolve_source(stem, list(files), fetch, ai_bytes, **kw)


# ------------------------------------------------- T1 asr 命中（Amos 型）
en = lambda i: "sequence word alpha %d brave knight" % i
ai = ai_bilingual(200, en)
asr_ok = mk_srt(200, lambda i: "Sequence word alpha %d, brave knight!" % i)  # 标点差归一后同文
r = run({STEM + ".asr.srt": asr_ok, STEM + ".ai.srt": ai,
         STEM + ".mkv": b"x", STEM + ".ai.srt.team.json": b"{}"}, ai, STEM)
check("T1 asr 命中→asr_cached",
      r["status"] == "ready" and r["source_kind"] == "asr_cached"
      and r["gates"]["verbatim"] == 1.0, r)
check("T1 产物名不可当源（守卫）", r["status"] == "ready"  # 选中的是 asr 而非 ai/json
      and r["source_path"].endswith(STEM + ".asr.srt"), r.get("source_path"))

# ------------------------------------------------- T2 asr 不命中（逐字低/错 stem）
asr_bad = mk_srt(200, lambda i: "sequence word alpha %d, different text here" % i)
r2 = run({STEM + ".asr.srt": asr_bad, STEM + ".ai.srt": ai}, ai, STEM)
check("T2a asr 逐字低→defer_asr_low（不降级不假绑）",
      r2["status"] == "defer_asr_low" and r2["tried"][0]["gates"]["verbatim"] <= 0.10, r2)
r2b = run({STEM + ".asr.srt.bak": asr_ok, "Other.Movie.2020.asr.srt": asr_ok,
           STEM + ".ai.srt": ai}, ai, STEM)
check("T2b asr 错stem/后缀伪装→无候选",
      r2b["status"] == "defer_no_source_candidate", r2b)

# ------------------------------------------------- T3 base 命中（YTS 型，逐字低但共现高）
def en_ai(i):
    return "adventure begins near the ancient harbor tonight"
def en_yts(i):
    return "JOHN: The adventure begins near the ancient harbor tonight"
ai_g = ai_bilingual(150, en_ai, last_end=150 * 2000 + 300)  # 末条与 base 同秒级
base_ok = mk_srt(150, en_yts, start_end=150 * 2000 + 300)
r3 = run({GHOST + ".srt": base_ok, GHOST + ".ai.srt": ai_g}, ai_g, GHOST)
check("T3 base 命中→external（逐字低被共现闸救起）",
      r3["status"] == "ready" and r3["source_kind"] == "external"
      and r3["gates"]["cooccur"] >= 0.90, r3)

# ------------------------------------------------- T4 base 不命中（错片共现≈0 / 中文非英文）
base_wrongfilm = mk_srt(150, lambda i: "completely unrelated galaxy rocket launch %d" % i,
                        start_end=150 * 2000 + 300)
r4 = run({GHOST + ".srt": base_wrongfilm, GHOST + ".ai.srt": ai_g}, ai_g, GHOST)
check("T4a base 错片→defer_base_low（负控咬住）",
      r4["status"] == "defer_base_low" and r4["tried"][0]["gates"]["cooccur"] <= 0.05, r4)
base_cn = mk_srt(150, lambda i: "这里是中文旁白第%d段" % i, start_end=150 * 2000 + 300)
r4b = run({GHOST + ".srt": base_cn, GHOST + ".ai.srt": ai_g}, ai_g, GHOST)
check("T4b base 中文轨→defer（英文闸咬住，不拿 gt 族当源）",
      r4b["status"].startswith("defer"), r4b)
# gt 族即便名字撞模式也永不选（NEVER_SOURCE）
r4c = run({GHOST + ".srt": base_ok, GHOST + ".gt.srt": base_ok,
           GHOST + ".ai.srt": ai_g}, ai_g, GHOST, modes=("base",))
check("T4c gt 排除面不影响正例（守卫）",
      r4c["status"] == "ready", r4c)

# ------------------------------------------------- 模式序：emb 在 asr 之前（既有优先序不动）
emb = mk_srt(200, en)
r5 = run({STEM + ".emb.srt": emb, STEM + ".asr.srt": asr_ok, STEM + ".ai.srt": ai}, ai, STEM)
check("T5 emb 优先序保持", r5["status"] == "ready" and r5["source_kind"] == "embedded_cached", r5)

fails = [x for x in RESULTS if not x[1]]
print("\n%d/%d PASS" % (len(RESULTS) - len(fails), len(RESULTS)))
sys.exit(1 if fails else 0)
