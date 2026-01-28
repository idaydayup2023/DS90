from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from srt_translate.mcp.llm_mcp import LlmMcp

from ..domain import LlmFields
from .imdb import ImdbTitle


@dataclass(frozen=True)
class FranchiseDecision:
    is_franchise: bool
    franchise_root: str | None
    confidence: float | None


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


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y")


def _prompt(filename: str, parsed: LlmFields, imdb: ImdbTitle | None) -> str:
    imdb_json = json.dumps(asdict(imdb), ensure_ascii=False) if imdb is not None else "null"
    return (
        "You are a media metadata analyst.\n"
        "Given a movie filename, parsed metadata, and optional IMDb data, decide whether the movie belongs to a franchise/series.\n"
        "If it does, output the franchise root name used to group all entries in the franchise.\n"
        "Rules:\n"
        "1) Output JSON only.\n"
        "2) Be conservative: if unsure, set is_franchise=false and franchise_root=null.\n"
        "3) franchise_root should be a clean short name, not including part numbers, years, resolutions, or release groups.\n"
        "4) Examples of franchise_root: \"Rocky\", \"Harry Potter\", \"Fast and Furious\", \"Mission: Impossible\".\n\n"
        f"FILENAME: {filename}\n"
        f"PARSED: {json.dumps(asdict(parsed), ensure_ascii=False)}\n"
        f"IMDB: {imdb_json}\n"
        "OUTPUT JSON SCHEMA:\n"
        "{\n"
        "  \"is_franchise\": true|false,\n"
        "  \"franchise_root\": string|null,\n"
        "  \"confidence\": number|null\n"
        "}\n"
    )


def _cache_key(title: str | None, year: int | None) -> str:
    h = hashlib.sha1()
    h.update((title or "").encode("utf-8"))
    h.update(b"\0")
    h.update(str(year or "").encode("utf-8"))
    return h.hexdigest()


class FranchiseJudgeMcp:
    def __init__(self, cache_dir: Path, ttl_days: int, llm: LlmMcp, model: str):
        self._cache_dir = cache_dir / "franchise_judge_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._ttl_seconds = max(0, int(ttl_days)) * 86400
        self._llm = llm
        self._model = model

    def judge(self, filename: str, parsed: LlmFields, imdb: ImdbTitle | None) -> FranchiseDecision | None:
        # ... (cache logic)
        title = (parsed.title or "") if parsed.kind == "movie" else ""
        year = parsed.year
        key = _cache_key(title or None, year)
        p = self._cache_dir / f"{key}.json"
        now = int(time.time())
        if p.exists() and self._ttl_seconds > 0:
            try:
                if now - int(p.stat().st_mtime) <= self._ttl_seconds:
                    obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                    if isinstance(obj, dict):
                        return FranchiseDecision(
                            is_franchise=_as_bool(obj.get("is_franchise")),
                            franchise_root=_as_str(obj.get("franchise_root")),
                            confidence=_as_float(obj.get("confidence")),
                        )
            except Exception:
                pass

        try:
            text = self._llm.generate(model=self._model, prompt=_prompt(filename, parsed, imdb), temperature=0.0).text
            obj = _extract_json(text)
            decision = FranchiseDecision(
                is_franchise=_as_bool(obj.get("is_franchise")),
                franchise_root=_as_str(obj.get("franchise_root")),
                confidence=_as_float(obj.get("confidence")),
            )
            try:
                p.write_text(json.dumps(asdict(decision), ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return decision
        except Exception:
            return None

