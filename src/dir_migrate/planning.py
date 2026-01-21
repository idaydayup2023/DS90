from __future__ import annotations

import posixpath
import re

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


def _norm_folder_name(name: str | None, default: str) -> str:
    s = (name or "").strip()
    if not s:
        return default
    s = s.replace("/", ".").replace("\\", ".").replace(":", ".").replace(" ", ".")
    s = re.sub(r"\\.+", ".", s).strip(".")
    return s or default


def series_bucket(fields: LlmFields) -> str:
    root = _norm_folder_name(fields.franchise_root or fields.series, default="Unknown.Series")
    if fields.franchise_root and fields.series:
        f = _norm_folder_name(fields.franchise_root, default="Unknown.Series")
        s = _norm_folder_name(fields.series, default="Unknown.Series")
        if f.lower() != s.lower():
            return posixpath.join(f, s)
    return root


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
