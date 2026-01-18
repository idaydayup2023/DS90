from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFiles:
    video_path: str
    subtitle_paths: tuple[str, ...]
    video_size_bytes: int | None


@dataclass(frozen=True)
class LlmFields:
    kind: str
    title: str | None
    series: str | None
    franchise_root: str | None
    year: int | None
    season: int | None
    episode: int | None
    episode_title: str | None
    resolution: str | None
    source: str | None
    codec: str | None
    audio: str | None
    group: str | None
    confidence: float | None


@dataclass(frozen=True)
class MovePlan:
    source: SourceFiles
    normalized_basename: str
    dest_dir: str
    dest_video_path: str
    subtitle_moves: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RunSummary:
    videos: int
    planned: int
    moved: int
    skipped: int
    conflicts: int
    failed: int

