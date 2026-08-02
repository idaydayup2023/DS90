from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .domain import LlmFields


_SEPARATORS = r"[ ._-]*"
_PAIR_PATTERNS = (
    re.compile(rf"(?i)(?<![A-Z0-9])S(\d{{1,2}}){_SEPARATORS}E(\d{{1,3}})(?!\d)"),
    re.compile(r"(?i)(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)"),
    re.compile(
        rf"(?i)(?:Season|Series){_SEPARATORS}(\d{{1,2}}).{{0,80}}?"
        rf"(?:Episode|Ep|E){_SEPARATORS}(\d{{1,3}})(?!\d)"
    ),
    re.compile(r"第\s*(\d{1,2})\s*季.{0,80}?第?\s*(\d{1,3})\s*集"),
)
_SEASON_COMPONENT = re.compile(r"(?i)^(?:Season|Series|S)[ ._-]*(\d{1,2})$")
_SEASON_IN_TEXT = re.compile(r"(?i)(?<![A-Z0-9])(?:Season|Series)[ ._-]*(\d{1,2})(?!\d)")
_CHINESE_SEASON = re.compile(r"第\s*(\d{1,2})\s*季")
_EPISODE_IN_TEXT = re.compile(
    r"(?i)(?<![A-Z0-9])(?:Episode|Ep|E)[ ._-]*(\d{1,3})(?!\d)"
)
_CHINESE_EPISODE = re.compile(r"第?\s*(\d{1,3})\s*集")
_RELEASE_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_MOVIE_RELEASE_SOURCE = re.compile(
    r"(?i)(?<![A-Z0-9])(?:WEB[ ._-]*DL|WEBRIP|BLU[ ._-]*RAY|BDRIP|BRRIP|REMUX)(?![A-Z0-9])"
)


@dataclass(frozen=True)
class ClassificationDecision:
    kind: str
    season: int | None
    episode: int | None
    evidence: tuple[str, ...]
    pending_reason: str | None = None

    @property
    def explanation(self) -> str:
        evidence = ", ".join(self.evidence) if self.evidence else "no reliable evidence"
        if self.pending_reason:
            return f"{self.pending_reason}; evidence: {evidence}"
        return f"classified as {self.kind}; evidence: {evidence}"


def _positive(value: int | None) -> int | None:
    return value if value is not None and value > 0 else None


def _season_value(value: int | None) -> int | None:
    return value if value is not None and value >= 0 else None


def path_markers(path: str) -> tuple[int | None, int | None, list[str]]:
    normalized = path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    evidence: list[str] = []

    for pattern in _PAIR_PATTERNS:
        match = pattern.search(normalized)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            if episode <= 0:
                evidence.append(f"season marker S{season:02d} with invalid episode 0")
                return season, None, evidence
            evidence.append(f"path season/episode marker S{season:02d}E{episode:02d}")
            return season, episode, evidence

    season: int | None = None
    for component in parts[:-1]:
        match = _SEASON_COMPONENT.fullmatch(component.strip())
        if match:
            season = int(match.group(1))
            evidence.append(f"season directory {component}")
            break
        match = _CHINESE_SEASON.search(component)
        if match:
            season = int(match.group(1))
            evidence.append(f"season directory {component}")
            break

    if season is None:
        match = _SEASON_IN_TEXT.search(normalized) or _CHINESE_SEASON.search(normalized)
        if match:
            season = int(match.group(1))
            evidence.append(f"season marker {match.group(0)}")

    filename_stem = PurePosixPath(normalized).stem
    episode: int | None = None
    match = _EPISODE_IN_TEXT.search(filename_stem) or _CHINESE_EPISODE.search(filename_stem)
    if match:
        episode = int(match.group(1))
        evidence.append(f"episode marker {match.group(0)}")
    elif season is not None:
        # A bare numeric filename inside an explicit season directory is common
        # and sufficiently constrained; do not treat arbitrary sequel numbers as episodes.
        bare = re.fullmatch(r"\s*0*(\d{1,3})\s*", filename_stem)
        if bare:
            episode = int(bare.group(1))
            evidence.append(f"numeric episode filename {filename_stem}")

    return season, episode, evidence


def canonical_metadata_kind(value: str | None) -> str | None:
    text = (value or "").strip().lower().replace("_", " ").replace("-", " ")
    if not text:
        return None
    if any(token in text for token in ("tv series", "tv mini series", "tv episode", "television", "episode")):
        return "tv"
    if text in {"tv", "series", "show"}:
        return "tv"
    if text in {"movie", "film", "feature"}:
        return "movie"
    return None


def _movie_release_signature(path: str) -> tuple[bool, str | None]:
    filename = PurePosixPath(path.replace("\\", "/")).stem
    year = _RELEASE_YEAR.search(filename)
    source = _MOVIE_RELEASE_SOURCE.search(filename)
    if year and source:
        return True, f"movie release signature year {year.group(1)} + source {source.group(0)}"
    return False, None


def sidecar_media_kind(
    filename: str,
    text: str,
) -> tuple[str | None, str | None, int | None, int | None]:
    if not isinstance(text, str):
        return None, None, None, None
    lower_name = filename.lower()
    lower = text.lower()
    if lower_name.endswith(".nfo"):
        if any(tag in lower for tag in ("<episodedetails", "<tvshow", "<tvshowtitle", "<season>", "<episode>")):
            season_match = re.search(r"<season>\s*(\d{1,2})\s*</season>", lower)
            episode_match = re.search(r"<episode>\s*(\d{1,3})\s*</episode>", lower)
            return (
                "tv",
                f"TV metadata in {filename}",
                int(season_match.group(1)) if season_match else None,
                int(episode_match.group(1)) if episode_match else None,
            )
        if "<movie" in lower:
            return "movie", f"movie metadata in {filename}", None, None

    if lower_name.endswith(".json"):
        if re.search(r'"(?:season|season_number|episode|episode_number|tvshowtitle)"\s*:', lower):
            season_match = re.search(r'"(?:season|season_number)"\s*:\s*"?(\d{1,2})', lower)
            episode_match = re.search(r'"(?:episode|episode_number)"\s*:\s*"?(\d{1,3})', lower)
            return (
                "tv",
                f"TV metadata in {filename}",
                int(season_match.group(1)) if season_match else None,
                int(episode_match.group(1)) if episode_match else None,
            )
        match = re.search(r'"(?:kind|type|media_type)"\s*:\s*"([^"]+)"', lower)
        if match:
            kind = canonical_metadata_kind(match.group(1))
            if kind:
                return kind, f"{kind} metadata in {filename}", None, None
    return None, None, None, None


def classify_media(
    path: str,
    fields: LlmFields,
    *,
    metadata_kind: str | None = None,
    metadata_evidence: str | None = None,
) -> ClassificationDecision:
    path_season, path_episode, evidence = path_markers(path)
    parsed_season = _season_value(fields.season)
    parsed_episode = _positive(fields.episode)
    season = path_season if path_season is not None else parsed_season
    episode = path_episode if path_episode is not None else parsed_episode

    if path_season is not None and path_episode is not None:
        return ClassificationDecision("tv", season, episode, tuple(evidence))
    if path_season is not None or path_episode is not None:
        missing = "episode" if episode is None else "season"
        return ClassificationDecision(
            "unknown",
            season,
            episode,
            tuple(evidence),
            f"classification pending: probable TV item but {missing} is missing",
        )

    canonical_kind = canonical_metadata_kind(metadata_kind)
    if canonical_kind:
        evidence.append(metadata_evidence or f"metadata kind {canonical_kind}")
        if canonical_kind == "movie":
            return ClassificationDecision("movie", None, None, tuple(evidence))
        if season is not None and episode is not None:
            return ClassificationDecision("tv", season, episode, tuple(evidence))
        return ClassificationDecision(
            "unknown",
            season,
            episode,
            tuple(evidence),
            "classification pending: metadata identifies TV but season/episode is incomplete",
        )

    movie_signature, movie_evidence = _movie_release_signature(path)
    if movie_signature:
        evidence.append(movie_evidence or "movie release signature")
        if parsed_season is not None or parsed_episode is not None:
            evidence.append("uncorroborated model season/episode was discarded")
        return ClassificationDecision("movie", None, None, tuple(evidence))

    # Model-produced season/episode values are not corroboration by themselves:
    # the model can hallucinate S01E01 from technical numbers such as DDP5.1.
    if fields.kind == "tv":
        evidence.append("parser suggested TV without path or metadata corroboration")
        return ClassificationDecision(
            "unknown",
            None,
            None,
            tuple(evidence),
            "classification pending: TV suggestion is not corroborated by path or metadata",
        )

    if parsed_season is not None or parsed_episode is not None:
        evidence.append("parser season/episode was rejected because the path has no matching marker")
        return ClassificationDecision(
            "unknown",
            None,
            None,
            tuple(evidence),
            "classification pending: model season/episode is not corroborated by path or metadata",
        )

    if fields.kind == "movie" and (fields.confidence or 0.0) >= 0.75:
        evidence.append(f"parser movie confidence {fields.confidence:.2f}")
        return ClassificationDecision("movie", None, None, tuple(evidence))

    evidence.append(f"parser kind {fields.kind or 'unknown'} with insufficient confidence")
    return ClassificationDecision(
        "unknown",
        None,
        None,
        tuple(evidence),
        "classification pending: no reliable movie or TV evidence",
    )
