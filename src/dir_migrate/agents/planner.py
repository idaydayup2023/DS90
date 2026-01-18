from __future__ import annotations

import posixpath
from pathlib import PurePosixPath

from ..config import AppConfig
from ..domain import MovePlan, SourceFiles
from ..mcp.llm import LlmMcp
from ..naming import build_normalized_basename, subtitle_suffix
from ..planning import dest_dir_for


def plan_one(cfg: AppConfig, llm: LlmMcp, item: SourceFiles) -> MovePlan:
    p = PurePosixPath(item.video_path)
    fields = llm.infer(p.name, cfg.rules)
    normalized = build_normalized_basename(fields, p.stem)
    dest_dir = dest_dir_for(cfg.rules, fields, normalized)
    dest_video_path = posixpath.join(dest_dir, normalized + p.suffix)
    moves: list[tuple[str, str]] = []
    for s in item.subtitle_paths:
        sp = PurePosixPath(s)
        suffix = subtitle_suffix(p.stem, sp.stem)
        dest_sub = posixpath.join(dest_dir, normalized + suffix + sp.suffix)
        moves.append((s, dest_sub))
    return MovePlan(
        source=item,
        normalized_basename=normalized,
        dest_dir=dest_dir,
        dest_video_path=dest_video_path,
        subtitle_moves=tuple(moves),
    )

