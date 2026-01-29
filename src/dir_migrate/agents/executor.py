from __future__ import annotations

import logging
import posixpath
from pathlib import PurePosixPath

from ..config import AppConfig
from ..domain import MovePlan
from ..mcp.storage import StorageMcp
from ..naming import subtitle_suffix
from .cleaner import cleanup_source_residual_dirs


log = logging.getLogger("dir_migrate.agents.executor")


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
        # Suffix logic for conflict resolution
        # We append -1, -2 etc. to the normalized basename
        nb = f"{base}-{i}"
        
        # We need to re-construct paths with new basename
        # dest_dir might depend on basename if it's a folder-per-video structure?
        # dest_dir in plan is usually ".../Movie (Year)" or ".../Series/Season"
        # If it's movie folder, renaming movie file doesn't change folder name usually,
        # UNLESS the folder name itself is derived from basename?
        # dest_dir_for uses fields, not basename. So folder is stable.
        
        # But wait, logic in executor.py line 30:
        # d = posixpath.join(posixpath.dirname(plan.dest_dir), nb)
        # This implies it changes the PARENT FOLDER name too?
        # If dest_dir is ".../Movie (2024)", dirname is ".../".
        # So it creates ".../Movie (2024)-1/Movie (2024)-1.mkv"?
        # This seems to assume folder structure matches filename.
        
        # If we just want to rename the file inside the SAME directory:
        # d = plan.dest_dir
        # But if folder already exists and has content, maybe we want separate folder?
        
        # Current logic:
        # nb = f"{base}-{i}"
        # d = posixpath.join(posixpath.dirname(plan.dest_dir), nb)
        # dv = posixpath.join(d, nb + p.suffix)
        
        # This creates a new directory for the conflict.
        
        d = posixpath.join(posixpath.dirname(plan.dest_dir), nb)
        dv = posixpath.join(d, nb + p.suffix)
        if dest_storage.exists(dv):
            continue
        moves = []
        for src_sub, _dst_sub in plan.subtitle_moves:
            # Re-calculate subtitle destination
            sp = PurePosixPath(src_sub)
            video_stem = PurePosixPath(plan.source.video_path).stem
            suffix = subtitle_suffix(video_stem, sp.stem)
            
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
    if cfg.execution.dry_run:
        log.info("dry-run: would move %s to %s", plan.source.video_path, plan.dest_video_path)
        for src_sub, dst_sub in plan.subtitle_moves:
            log.info("dry-run: would move subtitle %s to %s", src_sub, dst_sub)
        return True, "DRY_RUN", None

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
            if (not overwrite) and dest_storage.exists(dst_sub) and dst_sub.lower().endswith(".ai.srt"):
                source_storage.delete_file(src_sub)
                continue
            source_storage.rename(src_sub, dst_sub, overwrite=overwrite)
            moved.append((dst_sub, src_sub))
    except Exception as e:
        for dst_rel, src_rel in reversed(moved):
            try:
                dest_storage.rename(dst_rel, src_rel, overwrite=False)
            except Exception:
                pass
        return False, "FAILED", str(e)
    try:
        cleanup_source_residual_dirs(cfg, source_storage, chosen)
    except Exception as e:
        log.warning("cleanup failed video=%s error=%s", chosen.source.video_path, e)
    return True, None, None
