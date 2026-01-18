from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ..config import AppConfig
from ..domain import SourceFiles
from ..mcp.storage import StorageMcp


@dataclass(frozen=True)
class ScanResult:
    videos: list[SourceFiles]


def scan_once(cfg: AppConfig, source_storage: StorageMcp) -> ScanResult:
    exts = set(cfg.video.extensions)
    sub_exts = set(cfg.subtitle.extensions)
    all_files = source_storage.walk_files("/")
    out: list[SourceFiles] = []
    by_dir: dict[str, list[tuple[str, str, int | None]]] = {}

    for rel_path, size in all_files:
        p = PurePosixPath(rel_path)
        if p.suffix.lower() not in exts:
            continue
        if size is not None and size < cfg.video.min_bytes:
            continue
        dir_path = str(p.parent)
        if dir_path == ".":
            dir_path = "/"
        if dir_path not in by_dir:
            by_dir[dir_path] = source_storage.list_dir(dir_path)
        entries = by_dir[dir_path]
        stem = p.stem
        subs: list[str] = []
        for ep, _et, _sz in entries:
            q = PurePosixPath(ep)
            if q.suffix.lower() not in sub_exts:
                continue
            if q.parent != p.parent:
                continue
            if q.stem == stem or q.name.startswith(stem + "."):
                subs.append(ep)
        out.append(SourceFiles(video_path=rel_path, subtitle_paths=tuple(sorted(subs)), video_size_bytes=size))
        if cfg.execution.limit is not None and len(out) >= cfg.execution.limit:
            break
    return ScanResult(videos=out)

