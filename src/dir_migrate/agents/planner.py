from __future__ import annotations

import posixpath
import re
import threading
from pathlib import PurePosixPath

from ..config import AppConfig
from ..domain import MovePlan, SourceFiles
from ..mcp.franchise_judge import FranchiseJudgeMcp
from ..mcp.imdb import ImdbMcp
from ..mcp.llm import LlmMcp
from ..mcp.storage import StorageMcp
from ..naming import build_normalized_basename, subtitle_suffix
from ..planning import dest_dir_for


_franchise_cache_lock = threading.Lock()
_franchise_present_cache: dict[str, bool] = {}


def _dotify(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = t.replace(":", " ")
    t = re.sub(r"[\\[\\](){}]", " ", t)
    t = re.sub(r"[^A-Za-z0-9]+", ".", t)
    t = re.sub(r"\\.+", ".", t)
    return t.strip(".")


def _franchise_present_in_dest(dest_storage: StorageMcp, cfg: AppConfig, franchise_root: str) -> bool:
    key = _dotify(franchise_root).lower()
    if not key:
        return False
    with _franchise_cache_lock:
        cached = _franchise_present_cache.get(key)
    if cached is not None:
        return cached

    roots = [
        posixpath.join("/", cfg.rules.movie_1080_root),
        posixpath.join("/", cfg.rules.movie_4k_root),
    ]
    found = False
    for root in roots:
        try:
            entries = dest_storage.list_dir(root)
        except Exception:
            continue
        buckets = [p for p, t, _sz in entries if t == "dir"]
        for bucket in buckets:
            try:
                items = dest_storage.list_dir(bucket)
            except Exception:
                continue
            for p, t, _sz in items:
                if t != "dir":
                    continue
                name = posixpath.basename(p).lower()
                if name.startswith(key):
                    found = True
                    break
            if found:
                break
        if found:
            break

    with _franchise_cache_lock:
        _franchise_present_cache[key] = found
    return found


def plan_one(cfg: AppConfig, llm: LlmMcp, item: SourceFiles, dest_storage: StorageMcp | None = None) -> MovePlan:
    p = PurePosixPath(item.video_path)
    fields = llm.infer(p.name, cfg.rules)
    if cfg.imdb.enabled:
        imdb = ImdbMcp(cache_dir=cfg.paths.local_cache_dir, auto_install=cfg.imdb.auto_install, ttl_days=cfg.imdb.ttl_days)
        if fields.kind == "movie":
            imdb_title = imdb.lookup(kind="movie", title=fields.title, year=fields.year)
            force_keep = False
            if dest_storage is not None:
                candidates: list[str] = []
                if imdb_title is not None and imdb_title.franchise_root:
                    candidates.append(imdb_title.franchise_root)
                judge = FranchiseJudgeMcp(cache_dir=cfg.paths.local_cache_dir, ttl_days=cfg.imdb.ttl_days, ollama=llm.ollama, model=cfg.ollama.model)
                decision = judge.judge(p.name, fields, imdb_title)
                if decision is not None and decision.is_franchise and decision.franchise_root:
                    candidates.append(decision.franchise_root)
                for c in candidates:
                    if _franchise_present_in_dest(dest_storage, cfg, c):
                        force_keep = True
                        break
            if imdb_title is None or imdb_title.rating is None:
                if (not force_keep) and cfg.imdb.skip_unrated:
                    dest_dir = "/Downloads/low_imdb"
                    dest_video_path = posixpath.join(dest_dir, p.name)
                    subtitle_moves = tuple((s, posixpath.join(dest_dir, PurePosixPath(s).name)) for s in item.subtitle_paths)
                    return MovePlan(
                        source=item,
                        normalized_basename=p.stem,
                        dest_dir=dest_dir,
                        dest_video_path=dest_video_path,
                        subtitle_moves=subtitle_moves,
                        skip_reason=None,
                    )
            else:
                votes_ok = cfg.imdb.min_votes is None or (imdb_title.votes or 0) >= cfg.imdb.min_votes
                if (not force_keep) and votes_ok and cfg.imdb.min_rating is not None and imdb_title.rating < cfg.imdb.min_rating:
                    dest_dir = "/Downloads/low_imdb"
                    dest_video_path = posixpath.join(dest_dir, p.name)
                    subtitle_moves = tuple((s, posixpath.join(dest_dir, PurePosixPath(s).name)) for s in item.subtitle_paths)
                    return MovePlan(
                        source=item,
                        normalized_basename=p.stem,
                        dest_dir=dest_dir,
                        dest_video_path=dest_video_path,
                        subtitle_moves=subtitle_moves,
                        skip_reason=None,
                    )
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
        skip_reason=None,
    )
