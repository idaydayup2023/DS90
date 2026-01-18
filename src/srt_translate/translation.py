from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from .mcp.ollama import OllamaMcp
from .srt import SrtCue, clamp_text_single_line, format_srt, parse_srt


log = logging.getLogger("srt_translate.translation")


@dataclass(frozen=True)
class TranslationResult:
    cues: list[SrtCue]
    failed_indices: list[int]


def _translategemma_prompt(source_lang: str, source_code: str, target_lang: str, target_code: str, text: str) -> str:
    return (
        f"You are a professional {source_lang} ({source_code}) to {target_lang} ({target_code}) translator. "
        f"Your goal is to accurately convey the meaning and nuances of the original {source_lang} text while adhering to "
        f"{target_lang} grammar, vocabulary, and cultural sensitivities.\n"
        f"Produce only the {target_lang} translation, without any additional explanations or commentary. "
        f"Please translate the following {source_lang} text into {target_lang}:\n\n\n"
        f"{text}"
    )


_MARK_RE = re.compile(r"^<<<SRT_LINE:(\d+)>>>$", re.MULTILINE)


def _batch_prompt(lines: list[tuple[int, str]]) -> str:
    body = []
    for idx, text in lines:
        body.append(f"<<<SRT_LINE:{idx}>>>")
        body.append(text)
        body.append("")
    joined = "\n".join(body).rstrip()
    return (
        "Translate the English lines into Simplified Chinese.\n"
        "Rules:\n"
        "1) Keep marker lines exactly as-is: <<<SRT_LINE:N>>>.\n"
        "2) After each marker, output exactly one line of Chinese translation for the following English text.\n"
        "3) Do not output any other text.\n\n"
        + joined
    )


def _parse_batch_output(text: str) -> dict[int, str] | None:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip() != ""]
    out: dict[int, str] = {}
    i = 0
    while i < len(lines):
        m = re.fullmatch(r"<<<SRT_LINE:(\d+)>>>", lines[i])
        if not m:
            return None
        idx = int(m.group(1))
        if i + 1 >= len(lines):
            return None
        out[idx] = lines[i + 1]
        i += 2
    return out


def translate_srt_to_bilingual(
    ollama: OllamaMcp,
    model: str,
    srt_content: str,
    batch_size: int,
    max_retries: int,
    temperature: float,
) -> TranslationResult:
    cues = parse_srt(srt_content)
    lines: list[tuple[int, str]] = []
    for c in cues:
        en = clamp_text_single_line(c.text)
        lines.append((c.index, en))

    translated: dict[int, str] = {}
    failed: list[int] = []

    total = len(lines)
    batches = (total + batch_size - 1) // max(1, batch_size)
    log.info("translate start model=%s cues=%d batch_size=%d batches=%d", model, total, batch_size, batches)

    for start in range(0, len(lines), batch_size):
        batch = lines[start : start + batch_size]
        got = None
        prompt = _batch_prompt(batch)
        for _ in range(max_retries + 1):
            resp = ollama.generate(model=model, prompt=prompt, temperature=temperature).text
            got = _parse_batch_output(resp)
            if got and len(got) == len(batch):
                break
            got = None
        if got is None:
            for idx, en in batch:
                sp = _translategemma_prompt("English", "en", "Chinese", "zh-Hans", en)
                try:
                    zh = ollama.generate(model=model, prompt=sp, temperature=temperature).text.strip()
                    zh = clamp_text_single_line(zh)
                    translated[idx] = zh
                except Exception:
                    failed.append(idx)
            log.info("translate progress %d/%d (fallback per-line)", min(start + len(batch), total), total)
            continue

        for idx, _en in batch:
            translated[idx] = clamp_text_single_line(got.get(idx, ""))
        log.info("translate progress %d/%d", min(start + len(batch), total), total)

    out_cues: list[SrtCue] = []
    for c in cues:
        zh = translated.get(c.index, "")
        en = clamp_text_single_line(c.text)
        text = zh + "\n" + en
        out_cues.append(SrtCue(index=c.index, start_ms=c.start_ms, end_ms=c.end_ms, text=text))
    log.info("translate done failed=%d", len(failed))
    return TranslationResult(cues=out_cues, failed_indices=failed)


def to_ai_srt_content(result: TranslationResult) -> str:
    cues = []
    for c in result.cues:
        lines = [ln for ln in c.text.split("\n") if ln.strip() != ""]
        if len(lines) >= 2:
            zh = clamp_text_single_line(lines[0])
            en = clamp_text_single_line(lines[1])
            text = zh + "\n" + en
        else:
            text = clamp_text_single_line(c.text)
        cues.append(SrtCue(index=c.index, start_ms=c.start_ms, end_ms=c.end_ms, text=text))
    return format_srt(cues)
