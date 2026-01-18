from __future__ import annotations

import re

from .domain import LlmFields


def _dotify(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    t = t.replace(":", " ")
    t = re.sub(r"[\\[\\](){}]", " ", t)
    t = re.sub(r"[^A-Za-z0-9]+", ".", t)
    t = re.sub(r"\\.+", ".", t)
    return t.strip(".")


def _season_episode(season: int | None, episode: int | None) -> str:
    s = season if season is not None else 0
    e = episode if episode is not None else 0
    return f"S{s:02d}E{e:02d}"


def build_normalized_basename(fields: LlmFields, original_stem: str) -> str:
    resolution = (fields.resolution or "").lower()
    if resolution in ("4k", "2160", "2160p"):
        resolution = "2160p"
    if resolution in ("1080", "1080p"):
        resolution = "1080p"
    if resolution in ("720", "720p"):
        resolution = "720p"
    if not resolution:
        resolution = "unknown"

    src = _dotify(fields.source or "") or "unknown"
    codec = _dotify(fields.codec or "") or "unknown"
    audio = _dotify(fields.audio or "") or "unknown"
    group = _dotify(fields.group or "") or ""
    audio_group = audio + (f"-{group}" if group else "")

    if fields.kind == "tv":
        series = _dotify(fields.series or "") or _dotify(original_stem) or "Unknown.Series"
        se = _season_episode(fields.season, fields.episode)
        ep_title = _dotify(fields.episode_title or "")
        parts = [series, se]
        if ep_title:
            parts.append(ep_title)
        parts += [resolution, src, codec, audio_group]
        parts = [p for p in parts if p and p != "unknown"]
        return ".".join(parts)

    title = _dotify(fields.title or "") or _dotify(original_stem) or "Unknown.Title"
    year = str(fields.year) if fields.year else "UnknownYear"
    parts = [title, year, resolution, src, codec, audio_group]
    parts = [p for p in parts if p]
    return ".".join(parts)


def subtitle_suffix(video_stem: str, subtitle_stem: str) -> str:
    if subtitle_stem == video_stem:
        return ""
    if subtitle_stem.startswith(video_stem + "."):
        return subtitle_stem[len(video_stem) :]
    return "." + _dotify(subtitle_stem)

