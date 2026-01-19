from __future__ import annotations

import posixpath

from .config import RulesConfig
from .domain import LlmFields


def _is_4k(resolution: str | None) -> bool:
    r = (resolution or "").lower()
    return "2160" in r or "4k" in r


def _year_bucket_movie_1080(year: int | None, year_split: int) -> str:
    if year is None:
        return "UnknownYear"
    if year >= year_split:
        return str(year)
    decade = (year // 10) * 10
    return f"{decade}s"


def _decade_bucket(year: int | None) -> str:
    if year is None:
        return "UnknownDecade"
    decade = (year // 10) * 10
    return f"{decade}s"


def series_bucket(fields: LlmFields) -> str:
    # If franchise_root is present, use it as the main folder, 
    # but put the specific series as a subfolder IF it's different from franchise_root.
    # User requirement: "对于衍生剧应该迁移到剧名/衍生剧名.Sxx下"
    # Example: franchise="Cosmos", series="Cosmos: A Spacetime Odyssey"
    # Target: Cosmos/Cosmos.A.Spacetime.Odyssey/S01
    
    root_name = (fields.franchise_root or fields.series or "Unknown.Series").replace(" ", ".").replace(":", ".")
    
    # If we have a franchise root AND a specific series name that is different
    if fields.franchise_root and fields.series:
        f_norm = fields.franchise_root.replace(" ", ".").replace(":", ".").lower()
        s_norm = fields.series.replace(" ", ".").replace(":", ".").lower()
        
        # If the series name effectively contains the franchise name (like "Cosmos" vs "Cosmos: A Spacetime Odyssey")
        # we still want the subfolder structure.
        if f_norm != s_norm:
             series_name = fields.series.replace(" ", ".").replace(":", ".")
             return posixpath.join(root_name, series_name)
             
    return root_name


def dest_dir_for(rules: RulesConfig, fields: LlmFields, normalized_basename: str) -> str:
    if fields.kind == "tv":
        root = rules.tv_4k_root if _is_4k(fields.resolution) else rules.tv_1080_root
        sb = series_bucket(fields)
        season = fields.season if fields.season is not None else 0
        sxx = f"S{season:02d}"
        # Ensure root starts with / but don't double it if already there
        # And ensure we don't accidentally put it in /Downloads if root is relative?
        # The rules.*_root usually are like "X-TV" or "TV". 
        # We force absolute path by prepending "/"
        return posixpath.join("/", root, sb, sxx)
    
    root = rules.movie_4k_root if _is_4k(fields.resolution) else rules.movie_1080_root
    if _is_4k(fields.resolution):
        bucket = _decade_bucket(fields.year)
    else:
        bucket = _year_bucket_movie_1080(fields.year, rules.year_split)
    return posixpath.join("/", root, bucket, normalized_basename)

