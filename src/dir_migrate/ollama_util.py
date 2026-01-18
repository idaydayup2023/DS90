from __future__ import annotations

import re

from srt_translate.mcp.ollama import OllamaMcp


def _normalize_model_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _suggest_model(preferred: str, available: list[str]) -> str | None:
    pref_norm = _normalize_model_name(preferred)
    for m in available:
        if _normalize_model_name(m) == pref_norm:
            return m
    candidates = [
        preferred + ":latest" if ":" not in preferred else preferred,
        preferred.replace("tranlate", "translate"),
        preferred.replace("tranlategemma", "translategemma"),
        preferred.replace("translate-gemma", "translategemma"),
        preferred.replace("translategemma", "translategemma:latest"),
    ]
    for c in candidates:
        c_norm = _normalize_model_name(c)
        for m in available:
            if _normalize_model_name(m) == c_norm:
                return m
    for m in available:
        if "translategemma" in _normalize_model_name(m):
            return m
    return None


def resolve_ollama_model(ollama: OllamaMcp, preferred: str) -> str:
    try:
        available = ollama.tags()
    except Exception:
        return preferred
    return _suggest_model(preferred, available) or preferred

