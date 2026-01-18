from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SrtCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


_TIME_RE = re.compile(
    r"^(?P<sh>\d{2}):(?P<sm>\d{2}):(?P<ss>\d{2}),(?P<sms>\d{3})\s+-->\s+(?P<eh>\d{2}):(?P<em>\d{2}):(?P<es>\d{2}),(?P<ems>\d{3})\s*$"
)


def _to_ms(h: int, m: int, s: int, ms: int) -> int:
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def parse_srt(content: str) -> list[SrtCue]:
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [b for b in re.split(r"\n{2,}", content) if b.strip()]
    cues: list[SrtCue] = []
    for block in blocks:
        lines = [ln.rstrip("\n") for ln in block.split("\n") if ln.strip() != ""]
        if len(lines) < 2:
            continue
        idx_line = lines[0].strip()
        time_line = lines[1].strip()
        text_lines = lines[2:] if len(lines) > 2 else []

        index = None
        try:
            index = int(idx_line)
        except Exception:
            time_line = idx_line
            text_lines = lines[1:]

        m = _TIME_RE.match(time_line)
        if not m:
            raise ValueError(f"invalid srt time line: {time_line}")
        start_ms = _to_ms(
            int(m.group("sh")),
            int(m.group("sm")),
            int(m.group("ss")),
            int(m.group("sms")),
        )
        end_ms = _to_ms(
            int(m.group("eh")),
            int(m.group("em")),
            int(m.group("es")),
            int(m.group("ems")),
        )
        if index is None:
            index = len(cues) + 1
        text = "\n".join(text_lines).strip()
        cues.append(SrtCue(index=index, start_ms=start_ms, end_ms=end_ms, text=text))
    cues.sort(key=lambda c: (c.start_ms, c.end_ms, c.index))
    return cues


def format_time(ms: int) -> str:
    if ms < 0:
        ms = 0
    s, milli = divmod(ms, 1000)
    s, sec = divmod(s, 60)
    h, minute = divmod(s, 60)
    return f"{h:02d}:{minute:02d}:{sec:02d},{milli:03d}"


def format_srt(cues: list[SrtCue]) -> str:
    lines: list[str] = []
    for i, c in enumerate(cues, start=1):
        lines.append(str(i))
        lines.append(f"{format_time(c.start_ms)} --> {format_time(c.end_ms)}")
        text = c.text.strip()
        if text:
            lines.extend(text.split("\n"))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def clamp_text_single_line(s: str) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

