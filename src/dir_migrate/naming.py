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
    
    # User request: group should be preceded by '-', not '.'
    # The construction logic below uses parts list and ".".join(parts).
    # If we want "-group", we should attach it to the previous part or handle it specially.
    
    # Logic revision:
    # 1. Construct parts excluding group.
    # 2. Join parts with ".".
    # 3. Append "-group" if group exists.
    
    # But wait, audio_group logic handles this partially:
    # audio_group = audio + (f"-{group}" if group else "")
    # If audio is "unknown", audio_group becomes "group" or "unknown".
    # If audio_group is just "group", it gets added to parts, and joined with ".".
    # So we get "...codec.group".
    # User wants "...codec-group".
    
    # Let's adjust audio_group logic.
    if audio == "unknown":
        # If audio is unknown, we just have group.
        # But we want "-group" at the end of filename.
        # We can set audio_group to None/empty here and handle group separately?
        audio_group = ""
    else:
        # If audio is known, usually it's "Audio.Group" or "Audio-Group"?
        # Scene standard is usually "Audio-Group".
        audio_group = audio
    
    # We will handle group appending at the end of joining.
    
    if fields.kind == "tv":
        # ... (series name logic) ...
        series_name = fields.series or fields.franchise_root
        
        series = _dotify(series_name or "") or _dotify(original_stem) or "Unknown.Series"
        
        # Heuristic fix: If series name looks like S01E01 (hallucination) or is empty, try to extract from stem
        if re.match(r"^S\d+E\d+$", series, re.IGNORECASE):
            m = re.search(r"(.+?)[._\s-]*S\d+E\d+", original_stem, re.IGNORECASE)
            if m:
                extracted = m.group(1)
                series = _dotify(extracted)
        
        # Deduplication logic ...
        series_parts = series.split(".")
        clean_parts = []
        for p in series_parts:
            lp = p.lower()
            if lp == codec.lower() or lp == src.lower() or lp == resolution.lower() or lp == group.lower():
                continue
            if re.match(r"^S\d+E\d+$", p, re.IGNORECASE):
                continue
            clean_parts.append(p)
        
        if clean_parts:
            series = ".".join(clean_parts)

        se = _season_episode(fields.season, fields.episode)
        ep_title = _dotify(fields.episode_title or "")
        parts = [series, se]
        if ep_title:
            parts.append(ep_title)
        
        # Add metadata parts
        parts += [resolution, src, codec]
        if audio_group:
             parts.append(audio_group)
        
        # Filter empty/unknown
        parts = [p for p in parts if p and p != "unknown"]
        
        base = ".".join(parts)
        if group:
            return f"{base}-{group}"
        return base

    title = _dotify(fields.title or "") or _dotify(original_stem) or "Unknown.Title"
    year = str(fields.year) if fields.year else "UnknownYear"
    parts = [title, year, resolution, src, codec]
    if audio_group:
        parts.append(audio_group)
        
    parts = [p for p in parts if p and p != "unknown"]
    base = ".".join(parts)
    if group:
        return f"{base}-{group}"
    return base


def subtitle_suffix(video_stem: str, subtitle_stem: str) -> str:
    if subtitle_stem == video_stem:
        return ""
    if subtitle_stem.startswith(video_stem + "."):
        return subtitle_stem[len(video_stem) :]
    return "." + _dotify(subtitle_stem)
