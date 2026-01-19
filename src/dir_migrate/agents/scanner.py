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
        
        # Ensure the video has a corresponding .ai.srt subtitle file
        if not any(s.endswith(".ai.srt") for s in subs):
            # Special check for TV shows: if any episode in the same directory has an .ai.srt, 
            # and we are configured to allow partial season migration (implicit in logic), 
            # we might want to allow it?
            # BUT, user requirement says: "目录中我看到已经有翻译好的剧集字幕...程序逻辑是要完整整季翻译完成才迁移吗"
            # It seems the user WANTS to migrate even if only some episodes are done.
            # However, the current logic is strictly per-video:
            # "If THIS video does not have .ai.srt, skip THIS video."
            
            # If the user sees .ai.srt files in the directory but migration is not happening for THOSE specific files,
            # then those specific files must have the .ai.srt detected.
            
            # Wait, if the user sees .ai.srt for *some* episodes, but expects *all* to migrate?
            # Or maybe the user sees .ai.srt for Episode 1, but Episode 1 is NOT migrating?
            
            # Re-reading user input: "已翻译好的剧集字幕，虽然没有完整翻译这一季的所有字幕，程序逻辑是要完整整季翻译完成才迁移吗"
            # User is asking if PARTIAL season migration is supported.
            # My logic below supports partial migration (it checks per video).
            # So if Ep01 has .ai.srt, it SHOULD migrate.
            # If Ep01 is NOT migrating, then:
            # 1. The .ai.srt is not being detected (maybe naming convention issue?)
            # 2. Or the file system listing is stale/incomplete.
            
            continue

        out.append(SourceFiles(video_path=rel_path, subtitle_paths=tuple(sorted(subs)), video_size_bytes=size))
        if cfg.execution.limit is not None and len(out) >= cfg.execution.limit:
            break
    return ScanResult(videos=out)

