from __future__ import annotations

import posixpath
from pathlib import PurePosixPath

from ..config import AppConfig
from ..domain import MovePlan
from ..mcp.storage import StorageMcp
from ..naming import subtitle_suffix


def _pick_non_conflicting(cfg: AppConfig, dest_storage: StorageMcp, plan: MovePlan) -> MovePlan | None:
    if cfg.execution.on_conflict not in ("skip", "suffix", "overwrite"):
        raise ValueError(f"unsupported on_conflict: {cfg.execution.on_conflict}")
    if not dest_storage.exists(plan.dest_video_path):
        return plan
    if cfg.execution.on_conflict == "overwrite":
        return plan
    if cfg.execution.on_conflict == "skip":
        return None
    base = plan.normalized_basename
    p = PurePosixPath(plan.source.video_path)
    for i in range(1, 1000):
        nb = f"{base}-{i}"
        d = posixpath.join(posixpath.dirname(plan.dest_dir), nb)
        dv = posixpath.join(d, nb + p.suffix)
        if dest_storage.exists(dv):
            continue
        moves = []
        for src_sub, _dst_sub in plan.subtitle_moves:
            sp = PurePosixPath(src_sub)
            suffix = subtitle_suffix(p.stem, sp.stem)
            moves.append((src_sub, posixpath.join(d, nb + suffix + sp.suffix)))
        return MovePlan(
            source=plan.source,
            normalized_basename=nb,
            dest_dir=d,
            dest_video_path=dv,
            subtitle_moves=tuple(moves),
        )
    return None


def apply_one(cfg: AppConfig, source_storage: StorageMcp, dest_storage: StorageMcp, plan: MovePlan) -> tuple[bool, str | None, str | None]:
    chosen = _pick_non_conflicting(cfg, dest_storage, plan)
    if chosen is None:
        return False, "CONFLICT", None
    overwrite = cfg.execution.on_conflict == "overwrite"
    dest_storage.ensure_dir(chosen.dest_dir)
    moved: list[tuple[str, str]] = []
    try:
        source_storage.rename(chosen.source.video_path, chosen.dest_video_path, overwrite=overwrite)
        moved.append((chosen.dest_video_path, chosen.source.video_path))
        for src_sub, dst_sub in chosen.subtitle_moves:
            source_storage.rename(src_sub, dst_sub, overwrite=overwrite)
            moved.append((dst_sub, src_sub))
    except Exception as e:
        for dst_rel, src_rel in reversed(moved):
            try:
                dest_storage.rename(dst_rel, src_rel, overwrite=False)
            except Exception:
                pass
        return False, "FAILED", str(e)
    return True, None, None

