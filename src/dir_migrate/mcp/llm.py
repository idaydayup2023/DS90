from __future__ import annotations

import json
import logging
import re
from typing import Any

from srt_translate.mcp.llm_mcp import LlmMcp as BaseLlmMcp

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
    stem = re.sub(r"(?i)\.(mkv|mp4|avi|mov|m4v|ts)$", "", name).strip()

    # Simple title extraction: everything before the first year, resolution, or common keyword
    title_part = stem
    keywords = r"\b(19\d{2}|20\d{2}|2160p|1080p|720p|4k|web[-_. ]?dl|webrip|bluray|brrip|hdtv|remux|x264|x265|hevc|S\d{1,2}E\d{1,2})\b"
    m = re.search(r"(?i)" + keywords, stem)
    if m:
        title_part = stem[:m.start()].strip(" ._-")

    if title_part:
        # Clean up dots and underscores
        t = title_part.replace(".", " ").replace("_", " ").strip()
        if t:
            out["title"] = t
            out["series"] = t

    m = re.search(r"(?i)\b(19\d{2}|20\d{2})\b", name)
    if m:
        out["year"] = int(m.group(1))
    m = re.search(r"(?i)\bS(\d{1,2})E(\d{1,2})\b", name)
    if m:
        out["kind"] = "tv"
        out["season"] = int(m.group(1))
        out["episode"] = int(m.group(2))
    if re.search(r"(?i)\b2160p\b|\b4k\b", name):
        out["resolution"] = "2160p"
    elif re.search(r"(?i)\b1080p\b", name):
        out["resolution"] = "1080p"
    elif re.search(r"(?i)\b720p\b", name):
        out["resolution"] = "720p"
    
    # If it's 2160p/4K and no SxxExx, it's almost certainly a movie.
    if out.get("resolution") == "2160p" and "kind" not in out:
        out["kind"] = "movie"

    if "kind" not in out:
        out["kind"] = "movie" if out.get("year") else "unknown"
    
    # Try to extract group and codec if common patterns match
    if re.search(r"(?i)\bx265\b|\bhevc\b", name):
        out["codec"] = "x265"
    elif re.search(r"(?i)\bx264\b|\bavc\b|\bh264\b", name):
        out["codec"] = "x264"
    
    # Try to extract source
    if re.search(r"(?i)\bWEB[-_. ]?DL\b", name):
        out["source"] = "WEB-DL"
    elif re.search(r"(?i)\bWebRip\b", name):
        out["source"] = "WebRip"
    elif re.search(r"(?i)\bBluRay\b", name):
        out["source"] = "BluRay"
    elif re.search(r"(?i)\bHDTV\b", name):
        out["source"] = "HDTV"
    
    # Try to extract group from brackets if present
    m_bracket = re.search(r"\[(.*?)\]", name)
    if m_bracket:
        out["group"] = m_bracket.group(1)
    
    # Simple group extraction: last part after hyphen or dot (if no bracketed group found)
    if not out.get("group"):
        m = re.search(r"(?i)[-_.]([a-zA-Z0-9]+)$", stem)
        if m:
            g = m.group(1)
            # Exclusion list for common tags that are not groups
            exclusions = {
                "mkv", "mp4", "avi", "mov", "srt", "x264", "x265", "hevc", 
                "1080p", "720p", "2160p", "aac", "ac3", "amzn", "nf", 
                "dsnp", "hmax", "max", "atvp", "webdl", "web", "rip"
            }
            if g.lower() not in exclusions:
                out["group"] = g

    # If source was mistakenly put into group or vice versa, or source was hallucinated from group
    # We trust fallback group more if LLM returns null group but has source that looks like group?
    # Actually, in fallback, we don't set source unless we see WEB-DL etc.
    # ELiTE is a group.
    
    # If fallback has group, and LLM has source=group, we should clear source.
    if out.get("group") and out.get("source") == out.get("group"):
        out["source"] = None

    return out


def _sanitize_fields(filename: str, fields: LlmFields, fallback: dict[str, Any]) -> LlmFields:
    allowed_res = {"1080p", "2160p", "720p", "unknown"}

    def _norm_res(v: str | None) -> str | None:
        if not v:
            return None
        s = str(v).strip()
        if not s:
            return None
        if s.lower() in ("4k", "2160", "2160p"):
            return "2160p"
        if s.lower() in ("1080", "1080p"):
            return "1080p"
        if s.lower() in ("720", "720p"):
            return "720p"
        if s.lower() == "unknown":
            return "unknown"
        return None

    def _looks_like_se(s: str | None) -> bool:
        if not s:
            return False
        return bool(re.match(r"(?i)^S\d{1,2}E\d{1,2}$", s.strip()))

    def _looks_like_resolution(s: str | None) -> bool:
        if not s:
            return False
        return bool(re.match(r"(?i)^(2160p|1080p|720p|4k)$", s.strip()))

    def _looks_like_codec(s: str | None) -> bool:
        if not s:
            return False
        return bool(re.match(r"(?i)^(x265|x264|h265|h264|hevc|av1|vp9)$", s.strip()))

    def _looks_like_source(s: str | None) -> bool:
        if not s:
            return False
        # Extended list of common sources and streaming providers
        return bool(re.match(r"(?i)^(web[-_. ]?dl|webrip|bluray|brrip|hdtv|remux|amzn|nf|dsnp|hmax|max|atvp|apple[-_. ]?tv|hulu|pcok|paramount|dpv)$", s.strip()))

    def _looks_like_ad_tag(s: str | None) -> bool:
        if not s:
            return False
        t = re.sub(r"[^a-z0-9]", "", s.lower())
        return t in {"eztvxto", "eztv", "eztvx"}

    resolution = _norm_res(fields.resolution) or _norm_res(_as_str(fallback.get("resolution")))
    codec = _as_str(fields.codec)
    if codec and _looks_like_resolution(codec):
        codec = None
    if not codec:
        codec = _as_str(fallback.get("codec"))
    if codec:
        c = codec.strip().lower()
        if c in ("h265", "hevc"):
            codec = "x265"
        elif c in ("h264", "avc1"):
            codec = "x264"
        else:
            codec = codec.strip()

    source = _as_str(fields.source)
    group = _as_str(fields.group)
    audio = _as_str(fields.audio)
    video_tags = _as_str(fields.video_tags)
    episode_title = _as_str(fields.episode_title)

    if episode_title and (_looks_like_resolution(episode_title) or _looks_like_codec(episode_title) or _looks_like_source(episode_title) or _looks_like_se(episode_title)):
        episode_title = None

    if source and (_looks_like_resolution(source) or _looks_like_codec(source) or _looks_like_se(source)):
        source = None
    if not source:
        source = _as_str(fallback.get("source"))
    if _looks_like_ad_tag(source):
        source = None

    if not group:
        group = _as_str(fallback.get("group"))

    # If group is same as source, keep source and clear group if source is stronger?
    # Or keep group and clear source?
    # ELiTE is definitely a group.
    # If source is ELiTE, it's wrong.
    # But _looks_like_source checks for WEB-DL etc. ELiTE won't match.
    
    if group and (_looks_like_resolution(group) or _looks_like_codec(group) or _looks_like_source(group) or _looks_like_se(group)):
        group = None
    if _looks_like_ad_tag(group):
        group = None
    
    # New check: if source matches group, clear source?
    # No, source might be real source.
    # If source == group, it's duplication.
    if source and group and source.lower() == group.lower():
         # Usually group is more specific or it's a mistake.
         # If source is "WEB-DL", group won't be "WEB-DL".
         # If source is "ELiTE", it's wrong.
         if _looks_like_source(source):
             group = None
         else:
             source = None

    if audio and (_looks_like_resolution(audio) or _looks_like_codec(audio) or _looks_like_source(audio) or _looks_like_se(audio)):
        audio = None
    if not audio:
        audio = _as_str(fallback.get("audio"))

    if resolution is None:
        resolution = "unknown"
    if resolution not in allowed_res:
        resolution = "unknown"

    video_tags = _as_str(fields.video_tags)
    if video_tags:
        # Clean video_tags: split by comma/space, remove duplicates and known fields
        # Regex to split by comma or space but keep multi-word tags? 
        # Usually tags are single words like "HDR", "DV". 
        # But "HDR10+" is one tag.
        # Let's split by comma first, then by space if needed?
        # User prompt says "include HDR info...".
        # Let's try to normalize.
        raw_tags = re.split(r"[, ]+", video_tags)
        cleaned_tags = []
        seen_tags = set()
        
        # Collect values to exclude
        exclude_values = set()
        if resolution: exclude_values.add(resolution.lower())
        if codec: exclude_values.add(codec.lower())
        if source: exclude_values.add(source.lower())
        if audio: exclude_values.add(audio.lower())
        if group: exclude_values.add(group.lower())
        exclude_values.add("unknown")
        
        for t in raw_tags:
            t_clean = t.strip()
            if not t_clean:
                continue
            t_lower = t_clean.lower()
            
            # Skip if it's one of the other fields
            if t_lower in exclude_values:
                continue
                
            # Skip if it looks like resolution/codec/source/SE
            if _looks_like_resolution(t_clean) or _looks_like_codec(t_clean) or _looks_like_se(t_clean):
                continue
            
            if t_lower not in seen_tags:
                seen_tags.add(t_lower)
                cleaned_tags.append(t_clean)
        
        video_tags = ".".join(cleaned_tags) if cleaned_tags else None

    series = _as_str(fields.series)
    if series and _looks_like_se(series):
        series = None
    if not series:
        series = _as_str(fallback.get("series"))
    if series:
        trimmed = re.sub(r"(?i)[ ._-]*S\d{1,2}E\d{1,2}.*$", "", series).strip(" ._-")
        if trimmed:
            series = trimmed
    if (not series) and _as_str(fallback.get("series")):
        series = _as_str(fallback.get("series"))

    season = fields.season if (fields.season is not None and fields.season > 0) else None
    episode = fields.episode if (fields.episode is not None and fields.episode > 0) else None

    kind = fields.kind
    if kind == "tv" and (season is None or episode is None):
        if resolution == "2160p" or fields.year is not None or fallback.get("kind") == "movie":
            log.info("overriding kind from tv to movie for %s (no valid SxxExx found)", filename)
            kind = "movie"

    if kind == "movie" and season is not None and episode is not None:
        log.info("overriding kind from movie to tv for %s (found S%sE%s)", filename, season, episode)
        kind = "tv"

    return LlmFields(
        kind=kind,
        title=fields.title,
        series=series,
        franchise_root=fields.franchise_root,
        year=fields.year,
        season=season,
        episode=episode,
        episode_title=episode_title,
        resolution=resolution,
        source=source,
        codec=codec,
        audio=audio,
        group=group,
        video_tags=video_tags,
        confidence=fields.confidence,
    )


def _prompt(filename: str) -> str:
    return (
        "You are a professional media filename parser.\n"
        "Extract structured fields from the given filename as a SINGLE JSON object.\n\n"
        "STRICT RULES:\n"
        "1) TITLE/SERIES PRESERVATION: Extract the 'title' (for movies) or 'series' (for TV) EXACTLY as spelled in the filename. "
        "Do NOT truncate, do NOT summarize, and do NOT omit any words (e.g., 'St. Denis Medical' must stay 'St. Denis Medical', 'Law and Order SVU' must stay 'Law and Order SVU').\n"
        "2) FRANCHISE vs SERIES: 'franchise_root' is the main brand (e.g., '9-1-1', 'Law and Order'). 'series' is the specific show name (e.g., '9-1-1: Nashville', 'Law and Order: SVU'). "
        "If it's a spin-off, ensure 'franchise_root' is the main series and 'series' is the full spin-off name.\n"
        "3) KIND IDENTIFICATION: 'kind' must be 'tv' if there is season/episode information (like S01E01), even if resolution is high. "
        "Only set 'kind' to 'movie' if there is absolutely NO season/episode pattern.\n"
        "4) YEAR/SEASON/EPISODE: Extract accurately. 'season' and 'episode' must be integers.\n"
        "5) NO ALTERATION: Only extract fields. Do NOT change characters or capitalization from the original filename for names.\n"
        "6) NEVER NULL TITLE: You must provide a 'title' (for movies) or 'series' (for TV). If unsure, use the most likely name from the filename. Never return null for both 'title' and 'series'.\n"
        "7) RELEASE GROUP: 'group' is the release group. If there is a name in brackets at the end (e.g., [Ben The Men]), that is the 'group'. Streaming providers like 'AMZN', 'NF', 'DSNP' are part of the 'source', NOT the 'group'.\n"
        "8) VIDEO TAGS: 'video_tags' should include HDR info (DV, HDR10+, HDR, etc.) and other technical tags if present.\n"
        "9) OUTPUT ONLY JSON. No explanations.\n\n"
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
        "  \"video_tags\": string|null,\n"
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
        video_tags=fields.video_tags,
        confidence=fields.confidence,
    )


class LlmMcp:
    def __init__(self, llm: BaseLlmMcp, model: str, temperature: float, max_retries: int = 2):
        self._llm = llm
        self._model = model
        self._temperature = temperature
        self._max_retries = max(0, int(max_retries))

    @property
    def llm(self) -> BaseLlmMcp:
        return self._llm

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
                resp = self._llm.generate(model=self._model, prompt=_prompt(filename), temperature=self._temperature).text
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
                    video_tags=_as_str(obj.get("video_tags")) or _as_str(fallback.get("video_tags")),
                    confidence=_as_float(obj.get("confidence")) or _as_float(fallback.get("confidence")),
                )
                fields = _sanitize_fields(filename, fields, fallback)
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
                video_tags=_as_str(fallback.get("video_tags")),
                confidence=None,
            ),
        )

    def query_imdb(self, title: str, year: int | None) -> ImdbKnowledge:
        for _attempt in range(self._max_retries + 1):
            try:
                prompt = _prompt_imdb_knowledge(title, year)
                resp = self._llm.generate(model=self._model, prompt=prompt, temperature=self._temperature).text
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
