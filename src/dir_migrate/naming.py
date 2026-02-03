from __future__ import annotations

import re

from .domain import LlmFields


def _dotify(text: str) -> str:
    t = text.strip()
    if not t:
        return ""
    # User request: strictly keep names, only replace spaces with dots.
    # Replace path-unsafe characters and spaces with dots.
    # We keep '-', '_', and '.'
    
    # 1. Remove [...] content (forwarding groups)
    def remove_brackets(m):
        return ""
    t = re.sub(r"\[(.*?)\]", remove_brackets, t)
    
    # 2. Replace spaces with dots
    t = t.replace(" ", ".")
    
    # 3. Replace path-unsafe characters with dots
    # Unsafe: / \ : * ? " < > |
    t = re.sub(r"[\\/\\:*?\"<>|]+", ".", t)
    
    # 4. Clean up multiple dots and leading/trailing dots
    t = re.sub(r"\.+", ".", t)
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
    tags = _dotify(fields.video_tags or "")
    audio = _dotify(fields.audio or "") or "unknown"
    group = _dotify(fields.group or "") or ""
    
    if fields.kind == "tv":
        # User request: preserve original name strictly.
        # Prefer series (spin-off name) if available.
        series_name = fields.series or fields.franchise_root
        
        series = _dotify(series_name or "") or _dotify(original_stem) or "Unknown.Series"
        
        # REMOVED: The aggressive cleaning loop that dropped parts of the series name.
        
        se = _season_episode(fields.season, fields.episode)
        ep_title = _dotify(fields.episode_title or "")
        parts = [series, se]
        if ep_title:
            parts.append(ep_title)
        
        # Deduplicate metadata parts against themselves
        if group and codec and group.lower() == codec.lower():
             group = ""
        if group and src and group.lower() == src.lower():
             group = ""
        
        parts += [resolution, src, codec, tags, audio]
        
        # Filter empty/unknown
        final_parts = []
        for p in parts:
            if not p or p == "unknown":
                continue
            if final_parts and final_parts[-1].lower() == p.lower():
                continue
            final_parts.append(p)
            
        base = ".".join(final_parts)
        if group:
            # Prevent duplication like x265-x265-ELiTE
            if base.lower().endswith("." + group.lower()) or base.lower() == group.lower():
                pass
            elif final_parts and group.lower().startswith(final_parts[-1].lower() + "-"):
                prefix_len = len(final_parts[-1]) + 1
                remainder = group[prefix_len:]
                if remainder:
                    return f"{base}-{remainder}"
                else:
                    return base
            else:
                 return f"{base}-{group}"
        return base

    title = _dotify(fields.title or "") or _dotify(original_stem) or "Unknown.Title"
    year = str(fields.year) if fields.year else "UnknownYear"
    
    if group and codec and group.lower() == codec.lower():
         group = ""
    if group and src and group.lower() == src.lower():
         group = ""
         
    parts = [title, year, resolution, src, codec, tags, audio]
    
    final_parts = []
    for p in parts:
        if not p or p == "unknown":
            continue
        if final_parts and final_parts[-1].lower() == p.lower():
            continue
        final_parts.append(p)

    base = ".".join(final_parts)
    if group:
        if base.lower().endswith("." + group.lower()) or base.lower() == group.lower():
            pass
        elif final_parts and group.lower().startswith(final_parts[-1].lower() + "-"):
            prefix_len = len(final_parts[-1]) + 1
            remainder = group[prefix_len:]
            if remainder:
                return f"{base}-{remainder}"
            else:
                return base
        else:
            return f"{base}-{group}"
    return base


def subtitle_suffix(video_stem: str, subtitle_stem: str) -> str:
    # We should return the suffix that distinguishes the subtitle from the video.
    # Usually video is "Movie.2024"
    # Subtitle is "Movie.2024.en" -> ".en"
    # Subtitle is "Movie.2024.eng" -> ".eng"
    # Subtitle is "Movie.2024.zh-CN" -> ".zh-CN"
    # Subtitle is "Movie.2024" -> "" (rare, usually means default language)
    
    # Simple logic: strip the common prefix.
    # BUT, we need to be careful not to strip too much if stems are different.
    # The caller passes video_stem and subtitle_stem.
    
    # If stems are identical, return empty string (extension handles it)
    if subtitle_stem == video_stem:
        return ""
        
    # If subtitle starts with video stem + dot
    if subtitle_stem.startswith(video_stem + "."):
        return subtitle_stem[len(video_stem) :]
    
    # Fallback: if they are completely different, return the whole subtitle stem as suffix?
    # Or just dot + stem?
    # This might double the name if not careful.
    # e.g. video="Movie", sub="Other" -> ".Other" -> dest="Movie.Other.srt"
    return "." + _dotify(subtitle_stem)
