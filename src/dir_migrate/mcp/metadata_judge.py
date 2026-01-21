from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from srt_translate.mcp.ollama import OllamaMcp

from ..domain import LlmFields
from .imdb import ImdbTitle


def _extract_json(text: str) -> dict[str, Any]:
    t = text.strip()
    if not t:
        raise ValueError("empty model output")
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    a = t.find("{")
    b = t.rfind("}")
    if a >= 0 and b > a:
        obj = json.loads(t[a : b + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("model output is not a JSON object")


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _as_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _prompt(filename: str, parsed: LlmFields, imdb: ImdbTitle) -> str:
    return (
        "You are a metadata judge.\n"
        "Given a video filename, parsed metadata, and IMDb metadata, produce the most trustworthy metadata.\n"
        "Rules:\n"
        "1) Output JSON only. No explanations.\n"
        "2) kind must be \"movie\" or \"tv\".\n"
        "3) title for movie; series for tv.\n"
        "4) Prefer IMDb title/year if it clearly matches the filename.\n"
        "5) franchise_root: for tv spin-off, use the original franchise name if known; otherwise null.\n"
        "6) Keep season/episode from parsed metadata.\n\n"
        f"FILENAME: {filename}\n"
        f"PARSED: {json.dumps(asdict(parsed), ensure_ascii=False)}\n"
        f"IMDB: {json.dumps(asdict(imdb), ensure_ascii=False)}\n"
        "OUTPUT JSON SCHEMA:\n"
        "{\n"
        "  \"kind\": \"movie|tv\",\n"
        "  \"title\": string|null,\n"
        "  \"series\": string|null,\n"
        "  \"franchise_root\": string|null,\n"
        "  \"year\": number|null,\n"
        "  \"season\": number|null,\n"
        "  \"episode\": number|null,\n"
        "  \"episode_title\": string|null,\n"
        "  \"confidence\": number|null\n"
        "}\n"
    )


class MetadataJudgeMcp:
    def __init__(self, ollama: OllamaMcp, model: str, temperature: float, max_retries: int = 1):
        self._ollama = ollama
        self._model = model
        self._temperature = temperature
        self._max_retries = max(0, int(max_retries))

    def judge(self, filename: str, parsed: LlmFields, imdb: ImdbTitle) -> LlmFields:
        last_err: Exception | None = None
        for _attempt in range(self._max_retries + 1):
            try:
                resp = self._ollama.generate(model=self._model, prompt=_prompt(filename, parsed, imdb), temperature=self._temperature).text
                obj = _extract_json(resp)
                kind = _as_str(obj.get("kind")) or parsed.kind
                out = LlmFields(
                    kind=str(kind).lower(),
                    title=_as_str(obj.get("title")) or parsed.title,
                    series=_as_str(obj.get("series")) or parsed.series,
                    franchise_root=_as_str(obj.get("franchise_root")) or parsed.franchise_root,
                    year=_as_int(obj.get("year")) or parsed.year,
                    season=_as_int(obj.get("season")) or parsed.season,
                    episode=_as_int(obj.get("episode")) or parsed.episode,
                    episode_title=_as_str(obj.get("episode_title")) or parsed.episode_title,
                    resolution=parsed.resolution,
                    source=parsed.source,
                    codec=parsed.codec,
                    audio=parsed.audio,
                    group=parsed.group,
                    confidence=_as_float(obj.get("confidence")) or parsed.confidence,
                )
                return out
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(str(last_err) if last_err else "metadata judge failed")

