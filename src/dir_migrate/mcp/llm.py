from __future__ import annotations

import json
import logging
import re
from typing import Any

from srt_translate.mcp.ollama import OllamaMcp

from ..config import RulesConfig
from ..domain import ImdbKnowledge, ImdbRelatedMovie, LlmFields


log = logging.getLogger("dir_migrate.mcp.llm")


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


def _fallback_from_filename(name: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = re.search(r"(?i)\\b(19\\d{2}|20\\d{2})\\b", name)
    if m:
        out["year"] = int(m.group(1))
    m = re.search(r"(?i)\\bS(\\d{1,2})E(\\d{1,2})\\b", name)
    if m:
        out["kind"] = "tv"
        out["season"] = int(m.group(1))
        out["episode"] = int(m.group(2))
    if re.search(r"(?i)\\b2160p\\b|\\b4k\\b", name):
        out["resolution"] = "2160p"
    elif re.search(r"(?i)\\b1080p\\b", name):
        out["resolution"] = "1080p"
    elif re.search(r"(?i)\\b720p\\b", name):
        out["resolution"] = "720p"
    if "kind" not in out:
        out["kind"] = "movie" if out.get("year") else "unknown"
    return out


def _prompt(filename: str) -> str:
    return (
        "You are a media filename parser.\n"
        "Given an original video filename, extract structured fields as a single JSON object.\n"
        "Rules:\n"
        "1) Output JSON only. No explanations.\n"
        "2) If unsure, use null for the field.\n"
        "3) kind must be \"movie\" or \"tv\".\n"
        "4) For tv: season and episode should be integers if possible.\n"
        "5) resolution should be one of: 1080p, 2160p, 720p, unknown.\n\n"
        f"FILENAME: {filename}\n"
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
        "  \"resolution\": \"1080p|2160p|720p|unknown\"|null,\n"
        "  \"source\": string|null,\n"
        "  \"codec\": string|null,\n"
        "  \"audio\": string|null,\n"
        "  \"group\": string|null,\n"
        "  \"confidence\": number|null\n"
        "}\n"
    )


def _prompt_imdb_knowledge(title: str, year: int | None) -> str:
    year_str = f" {year}" if year else ""
    return (
        f'Provide IMDb information for the movie/TV show: "{title}{year_str}".\n'
        "If it is part of a franchise/collection, list related movies/shows.\n"
        "Output a SINGLE JSON object.\n"
        "Rules:\n"
        "1) Output JSON only. No explanations.\n"
        "2) Use null if unknown.\n"
        "3) imdb_rating should be a float (e.g. 6.8).\n"
        "4) imdb_votes should be an integer (approximate number of votes).\n"
        "5) imdb_id should be the tt-id (e.g. tt0120737).\n\n"
        "OUTPUT JSON SCHEMA:\n"
        "{\n"
        '  "title": string,\n'
        '  "year": number,\n'
        '  "imdb_id": string|null,\n'
        '  "imdb_rating": number|null,\n'
        '  "imdb_votes": number|null,\n'
        '  "related_movies": [\n'
        '    {\n'
        '      "title": string,\n'
        '      "year": number,\n'
        '      "imdb_rating": number|null\n'
        '    }\n'
        '  ]\n'
        "}\n"
    )


def _apply_franchise_rules(rules: RulesConfig, fields: LlmFields) -> LlmFields:
    series = fields.series or ""
    franchise_root = fields.franchise_root
    if not franchise_root and rules.franchise_map and series in rules.franchise_map:
        franchise_root = rules.franchise_map[series]
    if not franchise_root and series.upper().startswith("NCIS"):
        franchise_root = "NCIS"
    return LlmFields(
        kind=fields.kind,
        title=fields.title,
        series=fields.series,
        franchise_root=franchise_root,
        year=fields.year,
        season=fields.season,
        episode=fields.episode,
        episode_title=fields.episode_title,
        resolution=fields.resolution,
        source=fields.source,
        codec=fields.codec,
        audio=fields.audio,
        group=fields.group,
        confidence=fields.confidence,
    )


class LlmMcp:
    def __init__(self, ollama: OllamaMcp, model: str, temperature: float, max_retries: int = 2):
        self._ollama = ollama
        self._model = model
        self._temperature = temperature
        self._max_retries = max(0, int(max_retries))

    @property
    def ollama(self) -> OllamaMcp:
        return self._ollama

    @property
    def model(self) -> str:
        return self._model

    @property
    def temperature(self) -> float:
        return self._temperature

    def infer(self, filename: str, rules: RulesConfig) -> LlmFields:
        fallback = _fallback_from_filename(filename)
        last_err: Exception | None = None
        for _attempt in range(self._max_retries + 1):
            try:
                resp = self._ollama.generate(model=self._model, prompt=_prompt(filename), temperature=self._temperature).text
                obj = _extract_json(resp)
                kind = _as_str(obj.get("kind")) or _as_str(fallback.get("kind")) or "movie"
                fields = LlmFields(
                    kind=str(kind).lower(),
                    title=_as_str(obj.get("title")) or _as_str(fallback.get("title")),
                    series=_as_str(obj.get("series")) or _as_str(fallback.get("series")),
                    franchise_root=_as_str(obj.get("franchise_root")) or _as_str(fallback.get("franchise_root")),
                    year=_as_int(obj.get("year")) or _as_int(fallback.get("year")),
                    season=_as_int(obj.get("season")) or _as_int(fallback.get("season")),
                    episode=_as_int(obj.get("episode")) or _as_int(fallback.get("episode")),
                    episode_title=_as_str(obj.get("episode_title")) or _as_str(fallback.get("episode_title")),
                    resolution=_as_str(obj.get("resolution")) or _as_str(fallback.get("resolution")),
                    source=_as_str(obj.get("source")) or _as_str(fallback.get("source")),
                    codec=_as_str(obj.get("codec")) or _as_str(fallback.get("codec")),
                    audio=_as_str(obj.get("audio")) or _as_str(fallback.get("audio")),
                    group=_as_str(obj.get("group")) or _as_str(fallback.get("group")),
                    confidence=_as_float(obj.get("confidence")) or _as_float(fallback.get("confidence")),
                )
                return _apply_franchise_rules(rules, fields)
            except Exception as e:
                last_err = e
                continue
        log.warning("llm failed, fallback used filename=%s error=%s", filename, last_err)
        return _apply_franchise_rules(
            rules,
            LlmFields(
                kind=str(fallback.get("kind") or "movie").lower(),
                title=_as_str(fallback.get("title")),
                series=_as_str(fallback.get("series")),
                franchise_root=_as_str(fallback.get("franchise_root")),
                year=_as_int(fallback.get("year")),
                season=_as_int(fallback.get("season")),
                episode=_as_int(fallback.get("episode")),
                episode_title=_as_str(fallback.get("episode_title")),
                resolution=_as_str(fallback.get("resolution")),
                source=_as_str(fallback.get("source")),
                codec=_as_str(fallback.get("codec")),
                audio=_as_str(fallback.get("audio")),
                group=_as_str(fallback.get("group")),
                confidence=None,
            ),
        )

    def query_imdb(self, title: str, year: int | None) -> ImdbKnowledge:
        for _attempt in range(self._max_retries + 1):
            try:
                prompt = _prompt_imdb_knowledge(title, year)
                resp = self._ollama.generate(model=self._model, prompt=prompt, temperature=self._temperature).text
                obj = _extract_json(resp)
                related_raw = obj.get("related_movies")
                related: list[ImdbRelatedMovie] = []
                if isinstance(related_raw, list):
                    for r in related_raw:
                        if isinstance(r, dict):
                            related.append(
                                ImdbRelatedMovie(
                                    title=str(r.get("title") or "").strip(),
                                    year=_as_int(r.get("year")),
                                    imdb_rating=_as_float(r.get("imdb_rating")),
                                )
                            )
                return ImdbKnowledge(
                    title=_as_str(obj.get("title")),
                    year=_as_int(obj.get("year")),
                    imdb_id=_as_str(obj.get("imdb_id")),
                    imdb_rating=_as_float(obj.get("imdb_rating")),
                    imdb_votes=_as_int(obj.get("imdb_votes")),
                    related_movies=tuple(related),
                )
            except Exception:
                continue
        return ImdbKnowledge(title=None, year=None, imdb_id=None, imdb_rating=None, imdb_votes=None, related_movies=())
