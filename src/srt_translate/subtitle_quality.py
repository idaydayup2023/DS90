from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .srt import SrtCue, parse_srt


@dataclass(frozen=True)
class SubtitleQuality:
    score: float
    breakdown: dict[str, Any]


_LETTER_RE = re.compile(r"[A-Za-z]")
_BAD_RE = re.compile(r"[\uFFFD]")
_MUSIC_RE = re.compile(r"(\[music\]|\[.*?sound.*?\]|♪)", re.IGNORECASE)


def score_srt_content(content: str) -> SubtitleQuality:
    cues = parse_srt(content)
    if not cues:
        return SubtitleQuality(0.0, {"reason": "empty"})
    return score_cues(cues)


def score_cues(cues: list[SrtCue]) -> SubtitleQuality:
    total_chars = 0
    letter_chars = 0
    bad_chars = 0
    music_lines = 0
    empty_lines = 0

    overlaps = 0
    backwards = 0
    total_duration_ms = 0

    last_end = -1
    for c in cues:
        if c.end_ms < c.start_ms:
            backwards += 1
        if last_end >= 0 and c.start_ms < last_end:
            overlaps += 1
        last_end = max(last_end, c.end_ms)
        total_duration_ms += max(0, c.end_ms - c.start_ms)

        text = c.text or ""
        if not text.strip():
            empty_lines += 1
        total_chars += len(text)
        letter_chars += len(_LETTER_RE.findall(text))
        bad_chars += len(_BAD_RE.findall(text))
        if _MUSIC_RE.search(text):
            music_lines += 1

    cues_count = len(cues)
    effective_secs = max(1.0, total_duration_ms / 1000.0)
    cps = total_chars / effective_secs
    letter_ratio = letter_chars / max(1, total_chars)
    bad_ratio = bad_chars / max(1, total_chars)
    overlap_ratio = overlaps / max(1, cues_count)
    backward_ratio = backwards / max(1, cues_count)
    empty_ratio = empty_lines / max(1, cues_count)
    music_ratio = music_lines / max(1, cues_count)

    axis = 1.0
    axis *= math.exp(-4.0 * overlap_ratio)
    axis *= math.exp(-6.0 * backward_ratio)

    text_health = 1.0
    text_health *= max(0.0, min(1.0, (letter_ratio - 0.3) / 0.6))
    text_health *= math.exp(-8.0 * bad_ratio)
    text_health *= math.exp(-2.0 * music_ratio)
    text_health *= math.exp(-2.0 * empty_ratio)

    cps_health = 1.0
    if cps < 5:
        cps_health *= cps / 5
    elif cps > 25:
        cps_health *= math.exp(-(cps - 25) / 10)

    coverage = 1.0
    est_span_ms = max(1, cues[-1].end_ms - cues[0].start_ms)
    density = cues_count / max(1.0, est_span_ms / 1000.0)
    if density < 0.1:
        coverage *= density / 0.1
    elif density > 3.0:
        coverage *= math.exp(-(density - 3.0) / 2.0)

    score = 100.0 * (0.35 * axis + 0.35 * text_health + 0.15 * cps_health + 0.15 * coverage)
    breakdown = {
        "cues": cues_count,
        "overlaps": overlaps,
        "backwards": backwards,
        "letter_ratio": round(letter_ratio, 4),
        "bad_ratio": round(bad_ratio, 4),
        "music_ratio": round(music_ratio, 4),
        "empty_ratio": round(empty_ratio, 4),
        "cps": round(cps, 2),
        "density": round(density, 4),
        "axis": round(axis, 4),
        "text_health": round(text_health, 4),
        "cps_health": round(cps_health, 4),
        "coverage": round(coverage, 4),
    }
    return SubtitleQuality(score=float(round(score, 2)), breakdown=breakdown)

