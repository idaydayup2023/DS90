#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DS90 备勤 manifest 工具的「源档模式」解析器（代码运维 2026-11-08）。

站长 11-08 新单：源档模式在既有 emb(.emb.srt→embedded_cached) / en(<base>.en.srt→
external_english) 之外，新增两种命名——

  * `<base>.asr.srt` → source_kind="asr_cached"
      ASR 源轨（音频听写），ai 翻译的真源。闸：**逐字对齐命中率** ≥ 阈值
      （Amos.and.Andrew 实测 1364/1368=0.9971、aligned_lex 1.0，
      见修复卷 logs/en张冠李戴核查_C组三件_2026-11-08.md）。
  * `<base>.srt` → source_kind="external"
      发布组官方英文（YTS 等）。cue 数与末条时间和 ai 同、逐字可低（断句/说话人
      前缀差异），闸走 **±3s 窗时间对齐词共现** ≥ 阈值（Ghostheads 0.9095、
      Brown.Jesus 0.9322；错片负控 0.04，分离度 ~20×——判据能分辨张冠李戴）。
      证据卷：logs/弱审计名册_Ghostheads_2026-11-08.md、
      logs/弱审计名册_Brown.Jesus_2026-11-08.md。

rank/kind 命名与 DS90 引擎 `src/subtitles/mod.rs: source_rank()` 对齐
（.asr.srt→(300,"asr_cached")、<base>.srt→(450,"external")）；本模块只做
**备勤侧（写 manifest 前）的选源与闸门**，取件/写库留给调用方注入的 fetch。

安全口径（沿用 11-06 站长裁定）：
  * 闸门不过 = defer，绝不回退假绑（null+占位 sha 已冻结）。
  * `.ai.*` 产物与 manifest json 永不可当源（引擎同口径）。
  * gt/zh 一族非源（核心=.ai，gt 不可真信——11-03 站长裁定）。

纯函数：无网络无 IO，fetch(name)->bytes 由调用方注入（FTP 侧包装即可）。
"""
import hashlib
import re

__all__ = ["resolve_source", "parse_srt", "extract_ai_english",
           "verbatim_aligned_ratio", "cooccur_ratio", "is_english"]

TAG_RE = re.compile(r"<[^>]+>")
CUE_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
                    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")
WORD_RE = re.compile(r"[A-Za-z']{4,}")

# 引擎 source_rank 的两种新命名 + 既有两模式；备勤侧优先序 emb > en > asr > base
MODES = {
    "emb":  {"suffix": ".emb.srt", "kind": "embedded_cached"},
    "en":   {"suffix": ".en.srt",  "kind": "external_english", "needs_english": True},
    "asr":  {"suffix": ".asr.srt", "kind": "asr_cached",       "needs_english": True},
    "base": {"suffix": ".srt",     "kind": "external",         "needs_english": True},
}
# 永不可当源的命名（引擎排除面 ∪ 本站非源轨）
NEVER_SOURCE = re.compile(r"\.ai\.(srt|ass)$|\.ai\.srt\..+\.json$|"
                          r"\.(gt|zh|zho|chs|cht|chi)\.srt$|\.pgs\.srt$", re.I)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- SRT 基础件

def parse_srt(text):
    """返回 [{'start':ms,'end':ms,'text':str}, ...]（时间轴升序）。"""
    cues, cur = [], None
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        m = CUE_RE.search(block)
        if not m:
            continue
        h1, m1, s1, f1, h2, m2, s2, f2 = (int(x) for x in m.groups())
        body = block[m.end():].strip()
        cur = {"start": ((h1 * 60 + m1) * 60 + s1) * 1000 + f1,
               "end": ((h2 * 60 + m2) * 60 + s2) * 1000 + f2,
               "text": body}
        cues.append(cur)
    return cues


def norm_line(s):
    s = TAG_RE.sub("", s).lower()
    s = re.sub(r"[\s]+", " ", s).strip()
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff' ]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_ai_english(ai_cues):
    """ai 双语 cue → 每 cue 的内嵌英文行（去标签、剔 CJK 行）。"""
    out = []
    for c in ai_cues:
        lines = [TAG_RE.sub("", ln).strip() for ln in c["text"].split("\n")]
        en = " ".join(ln for ln in lines if ln and not CJK_RE.search(ln))
        out.append(norm_line(en))
    return out


def _to_ms(sec):
    return int(round(sec * 1000))


def timeline_ok(ai_cues, src_cues):
    """cue 数一致（允许 ≤5% 偏差）且末条 end 逐秒同（±1s）。"""
    n1, n2 = len(ai_cues), len(src_cues)
    if not n1 or not n2:
        return False, {"n_ai": n1, "n_src": n2}
    cnt_dev = abs(n1 - n2) / max(n1, n2)
    end_dev = abs(ai_cues[-1]["end"] - src_cues[-1]["end"]) / 1000.0
    return (cnt_dev <= 0.05 and end_dev <= 1.0), {"n_ai": n1, "n_src": n2,
                                                  "cnt_dev": round(cnt_dev, 4),
                                                  "end_dev_s": round(end_dev, 3)}


def verbatim_aligned_ratio(src_cues, ai_en):
    """逐字：cue 数同才计（逐条位置对齐）；数不同返回 None。"""
    return _verbatim(src_cues, ai_en)


def _verbatim(src_cues, ai_en):
    if len(src_cues) != len(ai_en) or not src_cues:
        return None
    hit = sum(1 for s, a in zip(src_cues, ai_en)
              if norm_line(s["text"]) and norm_line(s["text"]) == a)
    return hit / len(src_cues)


def cooccur_ratio(src_cues, ai_cues, window_ms=3000):
    """±3s 窗时间对齐词共现：源 cue 的长词(>3)出现在窗内 ai 英文行即得分。"""
    ai_en = extract_ai_english(ai_cues)
    scored = hits = 0
    for s, en_txt in zip(src_cues, ai_en):
        words = set(w.lower() for w in WORD_RE.findall(TAG_RE.sub("", s["text"])))
        if not words:
            continue
        scored += 1
        # 收集 ±window 内的 ai 英文文本
        blob = []
        for k, a in enumerate(ai_cues):
            if a["start"] > s["end"] + window_ms:
                break
            if a["end"] < s["start"] - window_ms:
                continue
            blob.append(ai_en[k])
        joined = " " + " ".join(blob) + " "
        if any((" " + w + " ") in joined for w in words):
            hits += 1
    return (hits / scored) if scored else 0.0, {"scored": scored, "hits": hits}


def is_english(text):
    """粗判英文：CJK 占比 >2% 即非英文（源档模式全要求英文源）。"""
    body = TAG_RE.sub("", text)
    letters = [c for c in body if c.isalpha()]
    if not letters:
        return False
    cjk = sum(1 for c in letters if CJK_RE.match(c))
    return cjk / len(letters) <= 0.02


# ---------------------------------------------------------------- 选源解析

def candidate_name(video_stem, mode):
    return video_stem + MODES[mode]["suffix"]


def resolve_source(video_stem, files, fetch, ai_bytes, dir_prefix="",
                   modes=("emb", "en", "asr", "base"),
                   min_verbatim=0.95, min_cooccur=0.90):
    """备勤侧选源。返回：
      命中 {"status":"ready","source_kind","source_path","source_sha256","gates","cross"}
      未中 {"status":"defer_*","tried":[...]}
    闸门不过即 defer，不跨模式静默降级（fail-closed，同 11-06 假绑冻结口径）。
    """
    files = [f for f in files if not NEVER_SOURCE.search(f)]
    ai_cues = parse_srt(ai_bytes.decode("utf-8", "replace"))
    ai_en = extract_ai_english(ai_cues)
    tried = []
    for mode in modes:
        name = candidate_name(video_stem, mode)
        if name not in files:
            continue
        data = fetch(name)
        src_cues = parse_srt(data.decode("utf-8", "replace"))
        tl, tl_info = timeline_ok(ai_cues, src_cues)
        ver = _verbatim(src_cues, ai_en)
        co, co_info = cooccur_ratio(src_cues, ai_cues)
        eng = is_english(data.decode("utf-8", "replace")) if MODES[mode].get("needs_english") else True
        g = {"timeline": tl, "timeline_info": tl_info,
             "verbatim": None if ver is None else round(ver, 4),
             "cooccur": round(co, 4), "cooccur_info": co_info, "english": eng}
        rec = {"mode": mode, "name": name, "gates": g,
               "sha256": sha256(data), "bytes": len(data)}
        tried.append(rec)
        if not tl:
            continue  # 轴不同＝非本片源，换下一模式（各模式独立判）
        if mode == "asr":
            ok = ver is not None and ver >= min_verbatim
        elif mode == "base":
            ok = eng and co >= min_cooccur
        else:  # emb / en：轴过 + 共现达标（en 另有英文闸，沿用既有口径的最低面）
            ok = eng and co >= min_cooccur
        if not ok:
            return {"status": "defer_%s_low" % mode, "tried": tried}
        return {"status": "ready", "source_kind": MODES[mode]["kind"],
                "source_path": (dir_prefix.rstrip("/") + "/" + name).lstrip("/"),
                "source_sha256": sha256(data), "gates": g, "cross": rec}
    return {"status": "defer_no_source_candidate", "tried": tried}
