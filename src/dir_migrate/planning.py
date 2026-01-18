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
    return (fields.franchise_root or fields.series or "Unknown.Series").replace(" ", ".").replace(":", ".")


def dest_dir_for(rules: RulesConfig, fields: LlmFields, normalized_basename: str) -> str:
    if fields.kind == "tv":
        root = rules.tv_4k_root if _is_4k(fields.resolution) else rules.tv_1080_root
        sb = series_bucket(fields)
        season = fields.season if fields.season is not None else 0
        sxx = f"S{season:02d}"
        return posixpath.join("/", root, sb, sxx, normalized_basename)
    root = rules.movie_4k_root if _is_4k(fields.resolution) else rules.movie_1080_root
    if _is_4k(fields.resolution):
        bucket = _decade_bucket(fields.year)
    else:
        bucket = _year_bucket_movie_1080(fields.year, rules.year_split)
    return posixpath.join("/", root, bucket, normalized_basename)

