#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5 专名废形扫描器（**唯一实现**，闸刀与阳性对照自测刀共用同一把，防「自测绿而闸不咬」）。

令据：站长 2026-11-27 13:27 派单（闸面盲区）＋ 21:1x 裁二；闸门治理 9bed——被闸的人不许改闸，
本件与其词表 `a5_deprecated_forms_2026-11-27.json` 只由 系统运维 经仓内 PR 改动。

三条硬规矩（写死在本件，消费端不可绕过）：
  R1 空词表＝红：`load_wordlist(..., fail_closed=True)` 遇词表缺失／族数 0／条目 0 → 抛 `GateBlindError`。
  R2 门控语义：条目 `gate_en` 非空 ⇒ 同枚 en 腿须含其中任一 token 才计（防真台词同形误伤，
     《误杀》案：cue 491「他没有上课的话」／cue 1203「为后来的蒙太奇做了素材」）。
  R3 计数对榫：词表 `expect_counts` 系生成时现读 sha 钉定底件算得；`count_check` 重算比对，
     漂移即红——防词表与盘面各说各话（11-27 数字串行案教训）。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")
TS = re.compile(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}")
HERE = Path(__file__).resolve().parent
DEFAULT_WORDLIST = HERE / "a5_deprecated_forms_2026-11-27.json"


class GateBlindError(RuntimeError):
    """闸盲：词表缺失／为空／对榫不过——一律 fail-closed，不得当「零违规」放过。"""


def parse_cues(raw: bytes, label: str = "srt") -> dict[int, dict]:
    """严格解析 srt → {cue: {"zh": 拼接中文腿, "en": 拼接英文腿, "ts": 时间戳}}。硬错即抛。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{label}: 存在 UTF-8 BOM")
    if b"\r" in raw:
        raise ValueError(f"{label}: 含 CR 行尾")
    if b"\x00" in raw:
        raise ValueError(f"{label}: 含 NUL")
    text = raw.decode("utf-8")
    blocks = [b for b in re.split(r"\n[ \t]*\n", text) if b.strip("\n") != ""]
    cues: dict[int, dict] = {}
    for b in blocks:
        lines = b.split("\n")
        if not lines[0].strip().isdigit():
            raise ValueError(f"{label}: 序号行非数字 {lines[0]!r}")
        i = int(lines[0].strip())
        if i in cues:
            raise ValueError(f"{label}: 序号重复 i={i}")
        if len(lines) < 2 or not TS.fullmatch(lines[1].strip()):
            raise ValueError(f"{label}: 时间戳形制异常 i={i}")
        cues[i] = {
            "zh": "".join(l for l in lines[2:] if CJK.search(l)),
            "en": " ".join(l for l in lines[2:] if l.strip() and not CJK.search(l)),
            "ts": lines[1].strip(),
        }
    return cues


def load_wordlist(path: Path | str = DEFAULT_WORDLIST, fail_closed: bool = True) -> dict:
    p = Path(path)
    if not p.exists():
        if fail_closed:
            raise GateBlindError(f"词表缺失：{p}——A5 不得报「废形 0」")
        return {}
    doc = json.loads(p.read_text(encoding="utf-8"))
    fams = doc.get("families") or []
    n = sum(len(f.get("deprecated") or []) for f in fams)
    if fail_closed and (not fams or n == 0):
        raise GateBlindError(f"词表为空：{p}（族数 {len(fams)}／条数 {n}）——A5 不得报「废形 0」")
    doc["_n_entries"] = n
    doc["_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return doc


def entries(doc: dict):
    for f in doc.get("families") or []:
        for e in f.get("deprecated") or []:
            yield f, e


def scan(cues: dict[int, dict], doc: dict) -> list[dict]:
    """返回命中列表。只看中文腿；`gate_en` 非空的条目须同枚 en 腿含门控 token 才计。"""
    hits = []
    for i, c in sorted(cues.items()):
        z, en = c.get("zh", ""), c.get("en", "")
        if not z:
            continue
        for f, e in entries(doc):
            form = e["form"]
            if form not in z:
                continue
            gate = e.get("gate_en") or []
            if gate and not any(t in en for t in gate):
                continue                      # R2 门控未开＝真台词同形，不计
            hits.append({"cue": i, "family": f["final"], "form": form, "zh": z, "en": en,
                         "gate_en": gate, "source": e.get("source", "roster")})
    return hits


def count_check(doc: dict, cues: dict[int, dict]) -> dict:
    """R3：expect_counts 与现读重算比对（终形与误形都算）。"""
    zh_all = "".join(c.get("zh", "") for c in cues.values())
    now = {w: zh_all.count(w) for w in (doc.get("expect_counts") or {})}
    exp = doc.get("expect_counts") or {}
    drift = {w: {"expect": exp[w], "now": now[w]} for w in exp if exp[w] != now[w]}
    return {"ok": not drift, "n_checked": len(exp), "drift": drift,
            "base_sha256_declared": (doc.get("film") or {}).get("base_sha256")}


def selftest(doc: dict) -> dict:
    """阳性对照：逐条造一枚含该形＋门控 token 的假 cue，**必须咬**；
    负例（词表 `negative_fixtures`，真台词同形）**必须不咬**。任一反例＝闸失效／误伤，判红。"""
    pos_fail, pos_ok, neg_fail, neg_ok = [], 0, [], 0
    for f, e in entries(doc):
        form, gate = e["form"], (e.get("gate_en") or [])
        fake = {999999: {"zh": f"前文{form}后文", "en": "prefix " + (gate[0] if gate else "X") + " suffix"}}
        got = [h for h in scan(fake, doc) if h["cue"] == 999999 and h["form"] == form]
        if got:
            pos_ok += 1
        else:
            pos_fail.append({"family": f["final"], "form": form, "gate_en": gate,
                             "why": "阳性不命中＝该形对闸不可见（闸失效）"})
        # 门控条目再补一发「门控关闭则不咬」探针（证明 R2 真在生效，而非门控写了没接线）
        if gate:
            closed = {999998: {"zh": f"前文{form}后文", "en": "unrelated english line"}}
            if [h for h in scan(closed, doc) if h["cue"] == 999998 and h["form"] == form]:
                pos_fail.append({"family": f["final"], "form": form, "gate_en": gate,
                                 "why": "门控关闭仍命中＝R2 未接线（真台词必被误伤）"})
    for fx in doc.get("negative_fixtures") or []:
        fake = {999997: {"zh": fx["zh"], "en": fx["en"]}}
        got = [h for h in scan(fake, doc) if h["cue"] == 999997 and h["form"] == fx["form"]]
        if got:
            neg_fail.append({"cue": fx["cue"], "form": fx["form"], "zh": fx["zh"],
                             "why": "真台词同形被咬＝误伤，须补门控"})
        else:
            neg_ok += 1
    n_pos = pos_ok + len(pos_fail)
    return {"ok": not pos_fail and not neg_fail and n_pos > 0,
            "n_positive": n_pos, "n_positive_bitten": pos_ok, "positive_fail": pos_fail,
            "n_negative": len(doc.get("negative_fixtures") or []), "n_negative_silent": neg_ok,
            "negative_fail": neg_fail, "wordlist_sha256": doc.get("_sha256")}


def gate(doc: dict, cues: dict[int, dict], allow_deferred: bool = True) -> dict:
    """A5 判定：阳性对照必须全绿（R0，不绿即整项红）；命中拆「阻闸」与「预存挂账（列名）」。"""
    st = selftest(doc)
    hits = scan(cues, doc)
    deferred = {(d["cue"], d["form"]) for d in (doc.get("deferred_known_hits") or [])}
    def _is_deferred(h):
        return any(h["cue"] == c and h["form"] in f for (c, f) in deferred)
    blocking = [h for h in hits if not (allow_deferred and _is_deferred(h))]
    parked = [h for h in hits if allow_deferred and _is_deferred(h)]
    return {"ok": bool(st["ok"] and not blocking),
            "positive_control": st, "hits": hits, "n_hits": len(hits),
            "blocking": blocking, "n_blocking": len(blocking),
            "parked_known": parked, "n_parked_known": len(parked),
            "wordlist_sha256": doc.get("_sha256"),
            "wordlist_entries": doc.get("_n_entries")}
