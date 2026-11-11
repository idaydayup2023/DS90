#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸门实质判据公共件 · 2026-11-11（代码运维 · 站长 08:0x 令 · 闸门治理=只准代码运维仓内 PR 改）

跑批器（workspace tools/retrans14_run_20261109.py）与判卷器（workspace
tools/retrans14_*_five_assert_*.py）一律 import 本件出数，**禁止在闸体外面另写一份**。

════ 判据一 substantive_status / hard_ok ════（站长 11-11 08:0x 令②）
替换 11-09 跑批器 `"error" in x.lower()` 启发式——empty-correction 降级链等诊断行
自带 `error=`，任何 stderr 诊断行都能把成功件误判 FAIL_stderr（件4/件8 实证：
rc=0、成品无损、`subtitles complete … failed=0` 在尾，仍被判 FAIL_stderr）。

实质通过 = rc==0
         + 引擎权威汇总行 `subtitles complete … failed=0`（src/subtitles/mod.rs:131）
         + 无硬失败行 `subtitles failed`（mod.rs:126）/ `subtitle job(s) failed`
         + 三条硬计数过：cues==源轨 cues；cn_lines>0 且 cn_ratio_raw>=0.5；loop_share<=0.15。

unresolved 不单独判红（team 口径 2026-10-21：unresolved=0 不是质量证据；审校降级链
keep_current_translation 中文在位即无损——logs/定性_mass-unresolved_225-232_2026-11-11.md §3
逐条实证，件8 全片无中文行 0 条、件4 仅 cue429 一条）。

════ 判据二 x6_missing_cjk / x6_from_blocks ════（站长 11-11 08:0x 令①）
放行拦点从 unresolved==0 改为「**全片无中文行数==0**」硬拦：
  · 中文槽判定按位（末行=英文轨，其余中文槽，11-09 修正版口径）；
  · 唯一豁免形＝整条中文槽全为纯数字行（站长 11-09 20:2x 批复三条硬边界：
    含字母不豁免／含 CJK 不豁免／无数字不豁免；件2 #892/#893 先例）；
  · 含字母无 CJK 的英文镜像行（件4 cue429 形）必红，不许默默放行；
  · 去标签后全空的中文槽归 S4 占位闸管，X6 不重复计。

用法：`python3 tools/ai_gate_criteria_20261111.py --selftest` 全绿才可挂闸。
"""
import re
import sys

TAG_RE = re.compile(r"<[^>]+>")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ALPHA_RE = re.compile(r"[A-Za-z]")
DIGIT_RE = re.compile(r"[0-9０-９]")


def is_num_only_line(line):
    """纯数字行判定（站长 11-09 20:2x 批复口径，自跑批器逐字迁入，此处为唯一真源）：
    去标签后**无字母、无 CJK，且至少含一位数字** ⇒ 豁免形。例：念数字 `83，83……`、
    电话号码 `667-213-4777。`。三条硬边界（防把豁免当后门）：
      ① 含任何 ASCII 字母 ⇒ 不豁免（中文行照抄英文必须照旧掉闸）；
      ② 含任何 CJK ⇒ 不豁免（正常中文行照旧计入分子）；
      ③ 不含数字（纯标点/省略号行）⇒ 不豁免，只有真数字串才免检。"""
    s = TAG_RE.sub("", line).strip()
    if not s or CJK_RE.search(s) or ALPHA_RE.search(s):
        return False
    return bool(DIGIT_RE.search(s))


# ───────────────────────────── 判据二：X6 无中文行硬拦 ─────────────────────────────

def zh_slot(texts):
    """ai 双语块按位取中文槽：末行=英文轨，其余中文槽（11-09 修正版口径；
    单行块整行即中文槽——漏中文不许借行序躲闸）。"""
    return texts[:-1] if len(texts) >= 2 else list(texts)


def x6_from_blocks(blocks):
    """blocks: [(no:int, timing:str, [text_lines:str])]。
    返回 (missing, exempt)：
      missing = [{"cue","timing","zh_lines"}] 无中文且非豁免 ⇒ 非空即 X6 红；
      exempt  = 同形状，纯数字豁免形（件2 #892/#893 先例），读数记卷不拦。"""
    missing, exempt = [], []
    for no, tm, texts in blocks:
        zh = zh_slot(texts)
        if any(CJK_RE.search(TAG_RE.sub("", z)) for z in zh):
            continue
        body = [z for z in zh if TAG_RE.sub("", z).strip()]
        if not body:
            continue  # 去标签全空＝S4 占位闸管，X6 不重复计
        if all(is_num_only_line(z) for z in body):
            exempt.append({"cue": no, "timing": tm, "zh_lines": zh})
            continue
        missing.append({"cue": no, "timing": tm, "zh_lines": zh})
    return missing, exempt


def x6_missing_cjk(ai_srt_text):
    """从 SRT 全文直接出 X6 读数（判卷器已自 parse 时用 x6_from_blocks 同函数）。"""
    return x6_from_blocks(parse_blocks_light(ai_srt_text, "ai"))


def parse_blocks_light(txt, label="srt"):
    out = []
    for b in txt.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        if not b.strip():
            continue
        lines = b.split("\n")
        if len(lines) < 2:
            raise ValueError("%s: short block #%d" % (label, len(out) + 1))
        if not lines[0].strip().isdigit() or "-->" not in lines[1]:
            raise ValueError("%s: malformed block #%d" % (label, len(out) + 1))
        out.append((int(lines[0].strip()), lines[1], lines[2:]))
    return out


# ─────────────────────── 判据一：跑批件级实质 PASS/FAIL ───────────────────────

def hard_ok(tail):
    """引擎权威汇总行判定（src/subtitles/mod.rs:126/:131）：
    存在 `subtitles complete … failed=0` 且无硬失败行。"""
    done = [x for x in tail if x.startswith("subtitles complete")]
    if not done or not re.search(r"\bfailed=0\b", done[-1]):
        return False
    if any("subtitles failed" in x or "subtitle job(s) failed" in x for x in tail):
        return False
    return True


def substantive_status(rc, out, src_cues, tail):
    """件级实质判据（None 的硬计数交给 out；out=None 即无产出）。
    返回状态串：PASS_staged / FAIL_rcN / FAIL_no_output / FAIL_cues_A_vs_B /
    FAIL_no_chinese / FAIL_low_cn_ratio_x(a/b) / FAIL_loop_x /
    FAIL_engine_failed / FAIL_no_completion。"""
    if rc != 0:
        return "FAIL_rc%s" % rc
    if not out:
        return "FAIL_no_output"
    if src_cues and out.get("cues") != src_cues:
        return "FAIL_cues_%s_vs_%s" % (out.get("cues"), src_cues)
    if out.get("cn_lines", 0) <= 0:
        return "FAIL_no_chinese"
    if out.get("cn_ratio_raw", 0.0) < 0.5:
        return "FAIL_low_cn_ratio_%s(%s/%s)" % (
            out.get("cn_ratio"), out.get("cues_cn"), out.get("cues_need_cn"))
    if out.get("loop_share", 1.0) > 0.15:
        return "FAIL_loop_%s" % out.get("loop_share")
    # 硬失败行优先于完成行（自相矛盾的输出从严）
    if any("subtitles failed" in x or "subtitle job(s) failed" in x for x in tail):
        return "FAIL_engine_failed"
    if not hard_ok(tail):
        return "FAIL_no_completion"
    return "PASS_staged"


# ───────────────────────────────── selftest ─────────────────────────────────

_SRT_OK = """1
00:00:01,000 --> 00:00:02,000
正常中文。
Hello there.

2
00:00:05,000 --> 00:00:06,000
667-213-4777。
667-213-4777.
"""

_SRT_MIRROR = """1
00:00:01,000 --> 00:00:02,000
the 335th Regiment of the 38th's 3rd Company.
the 335th Regiment of the 38th's 3rd Company.
"""

_SRT_PLACEHOLDER = """1
00:00:01,000 --> 00:00:02,000
。。。。。
Hmm.
"""

_TAIL_PASS = [
    "translation review_check corrected=23 flagged=23 unresolved=8",
    "translation alignment cue indices {225, 226} empty_correction_retry_unparseable=true indices=[225, 226] error=audit response is not valid JSON after safe wrapper normalization: EOF",
    "subtitles translated video=A.mkv output=A.ai.srt",
    "subtitles complete scanned=1 translated=1 cached=0 pending=0 failed=0",
]

_TAIL_REALFAIL = [
    "translation review_check split_indices=[418, 419] reason=missing_required_corrections indices=[419]",
    "subtitles failed video=B.mkv error=review failed for mandatory cue 419; refusing to publish questionable text",
    "subtitles complete scanned=1 translated=0 cached=0 pending=0 failed=1",
    "Error: 1 subtitle job(s) failed: B.mkv: review failed for mandatory cue 419",
]

_OUT_OK = {"cues": 2, "cn_lines": 1, "cn_ratio": 1.0, "cn_ratio_raw": 1.0,
           "cues_cn": 2, "cues_need_cn": 2, "loop_share": 0.0}


def _selftest():
    fails = []

    def chk(name, cond):
        print("  %-46s %s" % (name, "OK" if cond else "**FAIL**"))
        if not cond:
            fails.append(name)

    # X6：正常+纯数字豁免
    miss, ex = x6_missing_cjk(_SRT_OK)
    chk("X6 正常件绿", miss == [])
    chk("X6 纯数字行入豁免（件2 #892/#893 形）", [e["cue"] for e in ex] == [2])
    # X6：cue429 镜像行必红（含字母无 CJK，带数字也不豁免）
    miss, _ = x6_missing_cjk(_SRT_MIRROR)
    chk("X6 英文镜像行红（件4 cue429 形）", [x["cue"] for x in miss] == [1])
    # X6：全占位不豁免（归 S4 管的情形：有正文行「Hmm.」在英文槽，中文槽全占位）
    miss, _ = x6_missing_cjk(_SRT_PLACEHOLDER)
    chk("X6 无数字无字母中文槽不豁免", [x["cue"] for x in miss] == [1])
    # is_num_only_line 三硬边界
    chk("num_only 含字母不豁免", not is_num_only_line("Zoom 66."))
    chk("num_only 含 CJK 不豁免", not is_num_only_line("83，83……三"))
    chk("num_only 纯标点不豁免", not is_num_only_line("……"))
    chk("num_only 真数字串豁免", is_num_only_line("667-213-4777。"))
    # 判据一：件4/件8 回归形（rc=0 + complete failed=0 + 诊断行含 error= 也须 PASS）
    chk("成功件带 error= 诊断行 ⇒ PASS_staged（回归 FAIL_stderr 误判）",
        substantive_status(0, _OUT_OK, 2, _TAIL_PASS) == "PASS_staged")
    # 真失败对照：件5 形（rc=1）
    chk("真失败 rc=1 ⇒ FAIL_rc1",
        substantive_status(1, None, 1032, _TAIL_REALFAIL) == "FAIL_rc1")
    # 真失败对照：rc=0 但引擎报 subtitles failed ⇒ 从严 FAIL_engine_failed
    chk("rc=0 带 subtitles failed ⇒ FAIL_engine_failed",
        substantive_status(0, _OUT_OK, 2, _TAIL_REALFAIL) == "FAIL_engine_failed")
    # 无完成行 ⇒ FAIL_no_completion（旧启发式靠 Error 行碰运气，新判据缺行即红）
    chk("缺 complete 行 ⇒ FAIL_no_completion",
        substantive_status(0, _OUT_OK, 2, ["translating 1/2"]) == "FAIL_no_completion")
    # complete failed=1 ⇒ 红
    chk("complete failed=1 ⇒ FAIL_no_completion",
        substantive_status(0, _OUT_OK, 2,
                           ["subtitles complete scanned=1 translated=0 cached=0 pending=0 failed=1"])
        == "FAIL_no_completion")
    # 硬计数不许被 complete 行赦免
    chk("cues 不符仍红", substantive_status(0, dict(_OUT_OK, cues=1), 2, _TAIL_PASS)
        .startswith("FAIL_cues"))
    chk("loop 超标仍红", substantive_status(0, dict(_OUT_OK, loop_share=0.3), 2, _TAIL_PASS)
        .startswith("FAIL_loop"))
    chk("无中文仍红", substantive_status(0, dict(_OUT_OK, cn_lines=0, cn_ratio_raw=0.0),
                                         2, _TAIL_PASS) == "FAIL_no_chinese")
    print("selftest: %d checks, %d failed" % (17, len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    print(__doc__)
