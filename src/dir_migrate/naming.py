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
        
        # Deduplicate metadata parts against themselves to avoid x265.x265
        # Metadata parts: resolution, src, codec, audio_group
        
        # Helper to check if a token is already in parts or redundant
        # But here we are constructing the suffix parts.
        
        # Check if codec is same as group (case insensitive)
        if group and codec and group.lower() == codec.lower():
             # "x265-x265" -> "x265" (keep codec, clear group) or keep group?
             # Usually group is the one to drop if it's just repeating codec.
             group = ""
        
        # Check if src is same as group
        if group and src and group.lower() == src.lower():
             group = ""
             
        # Check if codec is same as src
        if src and codec and src.lower() == codec.lower():
             # Unlikely but possible if misparsed
             src = "unknown" # drop src?

        # Add metadata parts
        # If codec is x265, and group is ELiTE, we get ...x265-ELiTE. Correct.
        # If codec is x265, and group is x265, we get ...x265. Corrected above.
        
        # What if codec is x265, and src is x265? (Misparsed source)
        
        parts += [resolution, src, codec]
        
        # Extra robust check:
        # If audio_group starts with any of the previous parts + "-", it might be duplicated.
        # e.g. codec="x265", audio_group="x265-ELiTE"
        # We want to avoid ...x265.x265-ELiTE
        # In this case, we should probably strip the prefix from audio_group or drop codec?
        # Dropping codec is safer if audio_group contains it.
        
        if audio_group:
            ag_lower = audio_group.lower()
            # Check if audio_group starts with codec-
            if codec and codec != "unknown" and ag_lower.startswith(f"{codec.lower()}-"):
                # Drop codec from parts list (it's in parts[-1] currently)
                parts.pop() 
                # codec is now gone from parts, audio_group will provide it.
            
            # Check if audio_group starts with src-
            elif src and src != "unknown" and ag_lower.startswith(f"{src.lower()}-"):
                 # src is at parts[-2] or parts[-1] depending on codec
                 # This is getting complicated indices.
                 # Safer: iterate and check overlap.
                 pass
                 
            parts.append(audio_group)
        
        # Filter empty/unknown
        # Also dedup adjacent identical parts? 
        # e.g. if resolution=1080p, src=1080p (wrongly parsed)
        
        final_parts = []
        for p in parts:
            if not p or p == "unknown":
                continue
            # Simple dedup: if p is same as last part, skip
            if final_parts and final_parts[-1].lower() == p.lower():
                continue
            final_parts.append(p)
            
        base = ".".join(final_parts)
        if group:
            # Check if group is already at end of base?
            # base="...x265", group="x265" -> "...x265-x265"
            # base="...ELiTE", group="ELiTE" -> "...ELiTE-ELiTE"
            
            # More complex check: 
            # if group is "x265-ELiTE", and base ends with "x265", we get "x265-x265-ELiTE"
            # if group is "ELiTE", and base ends with "ELiTE", we get "ELiTE-ELiTE"
            
            # Check if base ends with the WHOLE group string (preceded by dot)
            if base.lower().endswith("." + group.lower()) or base.lower() == group.lower():
                pass
            # Check if group STARTS with the last part of base + separator?
            # e.g. base="...x265", group="x265-ELiTE"
            # last_part = "x265"
            # group starts with "x265-"
            elif final_parts and group.lower().startswith(final_parts[-1].lower() + "-"):
                # We have duplication.
                # Remove prefix from group? or remove last part from base?
                # Usually group is more authoritative?
                # Or if group is "x265-ELiTE", it's redundant. "ELiTE" is better group.
                # But we can't change group easily here.
                # We can strip the prefix from group to append.
                # prefix len = len(last_part) + 1
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
    
    # Same dedup logic for movies
    if group and codec and group.lower() == codec.lower():
         group = ""
    if group and src and group.lower() == src.lower():
         group = ""
         
    parts = [title, year, resolution, src, codec]
    if audio_group:
        parts.append(audio_group)
        
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
