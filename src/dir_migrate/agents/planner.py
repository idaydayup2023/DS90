from __future__ import annotations

import dataclasses
import json
import logging
import os
import posixpath
import re
import threading
from pathlib import Path, PurePosixPath

from ..config import AppConfig
from ..domain import MovePlan, SourceFiles
from ..mcp.franchise_judge import FranchiseJudgeMcp
from ..mcp.imdb import ImdbMcp, ImdbLookupDebug
from ..mcp.llm import LlmMcp
from ..mcp.storage import StorageMcp
from ..mcp.media import MediaMcp
from ..naming import build_normalized_basename, subtitle_suffix
from ..planning import dest_dir_for


log = logging.getLogger("dir_migrate.agents.planner")

_franchise_cache_lock = threading.Lock()
_franchise_present_cache: dict[str, bool] = {}


def _extract_imdb_from_json(source_storage: StorageMcp, video_path: str) -> tuple[str | None, float | None, int | None]:
    """Extract imdb_id, rating, votes from a sidecar .json file if present."""
    try:
        d = posixpath.dirname(video_path.rstrip("/")) or ""
        basename = posixpath.splitext(posixpath.basename(video_path))[0]
        json_path = posixpath.join(d, f"{basename}.json")
        
        # Check if file exists in source storage listing
        # Since we don't have a direct 'exists' method on StorageMcp, we list dir
        # or just try to read it. Listing is safer to avoid exceptions if not exists.
        # But for performance, if we already listed dir in caller, we could reuse it.
        # Here we just try to read it, assuming StorageMcp.read_text raises if not found.
        # However, to be safe and consistent with _extract_tt_from_sidecars:
        try:
            entries = source_storage.list_dir(d)
        except Exception:
            return None, None, None
            
        has_json = False
        for p, t, _sz in entries:
            if t == "file" and p == json_path:
                has_json = True
                break
        
        if not has_json:
            return None, None, None

        text = source_storage.read_text(json_path, max_bytes=1048576) # 1MB limit
        data = json.loads(text)
        
        # Try to find imdb info in common structures
        # Structure 1: {"imdb": {"id": "tt...", "rating": 6.4, "rating_count": ...}}
        # Structure 2: {"imdb_id": "tt...", "imdb_rating": 6.4, ...}
        
        imdb_id = None
        rating = None
        votes = None

        if "imdb" in data and isinstance(data["imdb"], dict):
            imdb_obj = data["imdb"]
            imdb_id = imdb_obj.get("id")
            rating = imdb_obj.get("rating")
            votes = imdb_obj.get("rating_count")
        
        # Fallback/Override if top level keys exist
        if not imdb_id:
            imdb_id = data.get("imdb_id") or data.get("imdb") # sometimes "imdb": "tt..."
            if isinstance(imdb_id, dict): imdb_id = None # safety
        if rating is None:
            rating = data.get("imdb_rating")
        if votes is None:
            votes = data.get("imdb_votes") or data.get("imdb_rating_count")

        # Normalize
        if isinstance(imdb_id, str) and not imdb_id.startswith("tt"):
            # Check if it looks like an ID
            if re.match(r"^\d{7,8}$", imdb_id):
                imdb_id = f"tt{imdb_id}"
            else:
                imdb_id = None
        
        if rating is not None:
            try:
                rating = float(rating)
            except (ValueError, TypeError):
                rating = None
        
        if votes is not None:
            try:
                votes = int(votes)
            except (ValueError, TypeError):
                votes = None
                
        return imdb_id, rating, votes
    except Exception:
        return None, None, None


def _extract_tt_from_text(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"tt\d{7,8}", text, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(0).lower()


def _extract_tt_from_sidecars(source_storage: StorageMcp, video_path: str) -> str | None:
    d = posixpath.dirname(video_path.rstrip("/")) or ""
    try:
        entries = source_storage.list_dir(d)
    except Exception:
        return None
    for p, t, _sz in entries:
        if t != "file":
            continue
        name = posixpath.basename(p).lower()
        if not (name.endswith(".nfo") or name.endswith(".txt") or name.endswith(".url")):
            continue
        try:
            text = source_storage.read_text(p, max_bytes=262144)
        except Exception:
            continue
        tt = _extract_tt_from_text(text)
        if tt:
            return tt
    return None


def _normalize_imdb_query_title(title: str | None, year: int | None) -> str | None:
    if not title:
        return None
    t = str(title).strip()
    if not t:
        return None
    if year and isinstance(year, int):
        t = re.sub(rf"(?<!\d){year}(?!\d)", " ", t)
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)
    t = re.sub(
        r"\b(remastered|unrated|extended|director'?s\s+cut|dc|final\s+cut|ultimate\s+edition|special\s+edition|repack|proper|limited|internal)\b",
        " ",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


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


def plan_one(cfg: AppConfig, llm: LlmMcp, item: SourceFiles, dest_storage: StorageMcp | None = None, source_storage: StorageMcp | None = None) -> MovePlan:
    p = PurePosixPath(item.video_path)
    fields = llm.infer(p.name, cfg.rules)

    local_probe_path: str | None = None
    if cfg.source.kind == "local" and cfg.source.local_root:
        local_probe_path = os.path.join(cfg.source.local_root, item.video_path.lstrip("/"))
    
    if local_probe_path:
        try:
            # We need to import MediaMcp
            media = MediaMcp() # assumes ffprobe in path
            # We need Path object
            info = media.probe_media_info(Path(local_probe_path))
            
            # Update fields if missing
            if info.video:
                if not fields.resolution and info.video.resolution_label:
                    log.info("enriched resolution=%s for %s", info.video.resolution_label, item.video_path)
                    fields = dataclasses.replace(fields, resolution=info.video.resolution_label)
                if not fields.codec and info.video.codec:
                    c = info.video.codec.lower()
                    if c in ("h264", "avc1"):
                        c = "x264"
                    elif c in ("hevc", "h265", "hev1"):
                        c = "x265"
                    elif c == "vp9":
                        c = "vp9"
                    elif c == "av1":
                        c = "av1"
                    log.info("enriched codec=%s for %s", c, item.video_path)
                    fields = dataclasses.replace(fields, codec=c)
            
            if info.audio and not fields.audio:
                best_audio = next((a for a in info.audio if a.is_default), info.audio[0] if info.audio else None)
                if best_audio and best_audio.codec:
                    ac = best_audio.codec.upper()
                    if best_audio.channels:
                        ch_map = {1: "1.0", 2: "2.0", 6: "5.1", 8: "7.1"}
                        ch_str = ch_map.get(best_audio.channels, f"{best_audio.channels}ch")
                        ac = f"{ac}.{ch_str}"
                    log.info("enriched audio=%s for %s", ac, item.video_path)
                    fields = dataclasses.replace(fields, audio=ac)

        except Exception as e:
            log.warning("failed to probe media info for %s: %s", item.video_path, e)

    if cfg.imdb.enabled:
        imdb = ImdbMcp(cache_dir=cfg.paths.local_cache_dir, auto_install=cfg.imdb.auto_install, ttl_days=cfg.imdb.ttl_days)
        if fields.kind == "movie":
            imdb_id = None
            imdb_rating = None
            imdb_votes = None
            imdb_franchise = None
            imdb_title = None
            imdb_dbg = None

            # 0. Try local json sidecar first (Highest Priority)
            if source_storage:
                jid, jrate, jvotes = _extract_imdb_from_json(source_storage, item.video_path)
                if jid or jrate is not None:
                    log.info("using sidecar json imdb info id=%s rating=%s votes=%s video=%s", jid, jrate, jvotes, item.video_path)
                    imdb_id = jid
                    imdb_rating = jrate
                    imdb_votes = jvotes
                    imdb_dbg = ImdbLookupDebug(status="ok_json", error=None, candidates=())

            # 1. Try LLM first (Preferred if no json)
            if imdb_rating is None:
                know = llm.query_imdb(fields.title or p.name, fields.year)
                if know.imdb_rating is not None:
                    log.info("using llm provided rating=%s for %s", know.imdb_rating, fields.title)
                    imdb_rating = know.imdb_rating
                    imdb_votes = know.imdb_votes
                    imdb_id = know.imdb_id
                    # Fake a debug info for logging
                    imdb_dbg = ImdbLookupDebug(status="ok_llm", error=None, candidates=())
                    try:
                        log.info("llm knowledge result: %s", json.dumps(dataclasses.asdict(know), default=str))
                    except Exception:
                        pass

            # 2. Fallback to standard IMDb lookup if LLM failed and no json
            if imdb_rating is None:
                tt = None
                if source_storage is not None:
                    tt = _extract_tt_from_sidecars(source_storage, item.video_path)
                if tt:
                    imdb_title, imdb_dbg = imdb.lookup_by_id_debug(tt)
                    log.info("imdb tt_source=sidecar tt=%s video=%s", tt, item.video_path)
                else:
                    qtitle = _normalize_imdb_query_title(fields.title, fields.year)
                    if qtitle and fields.title and qtitle.strip() != str(fields.title).strip():
                        log.info("imdb title normalized from=%s to=%s video=%s", fields.title, qtitle, item.video_path)
                    imdb_title, imdb_dbg = imdb.lookup_debug(kind="movie", title=qtitle or fields.title, year=fields.year)
                
                imdb_id = getattr(imdb_title, "imdb_id", None) if imdb_title is not None else None
                imdb_rating = getattr(imdb_title, "rating", None) if imdb_title is not None else None
                imdb_votes = getattr(imdb_title, "votes", None) if imdb_title is not None else None
                imdb_franchise = getattr(imdb_title, "franchise_root", None) if imdb_title is not None else None
            
            # Ensure imdb_dbg is not None before accessing its attributes
            if imdb_dbg is None:
                # Should normally not happen if logic above is correct, but for safety
                imdb_dbg = ImdbLookupDebug(status="unknown", error=None, candidates=())

            force_keep = False
            llm_franchise: str | None = None
            if dest_storage is not None:
                candidates: list[str] = []
                if imdb_title is not None and imdb_title.franchise_root:
                    candidates.append(imdb_title.franchise_root)
                judge = FranchiseJudgeMcp(cache_dir=cfg.paths.local_cache_dir, ttl_days=cfg.imdb.ttl_days, ollama=llm.ollama, model=cfg.ollama.model)
                decision = judge.judge(p.name, fields, imdb_title)
                if decision is not None and decision.is_franchise and decision.franchise_root:
                    llm_franchise = decision.franchise_root
                    candidates.append(decision.franchise_root)
                for c in candidates:
                    if _franchise_present_in_dest(dest_storage, cfg, c):
                        force_keep = True
                        break
            if imdb_rating is not None:
                votes_ok = cfg.imdb.min_votes is None or (imdb_votes or 0) >= cfg.imdb.min_votes
                if (not force_keep) and votes_ok and cfg.imdb.min_rating is not None and imdb_rating < cfg.imdb.min_rating:
                    log.info(
                        "imdb status=%s decision=low_imdb reason=rating_below_threshold video=%s title=%s year=%s imdb_id=%s rating=%s votes=%s imdb_franchise=%s llm_franchise=%s force_keep=%s",
                        imdb_dbg.status,
                        item.video_path,
                        fields.title,
                        fields.year,
                        imdb_id,
                        imdb_rating,
                        imdb_votes,
                        imdb_franchise,
                        llm_franchise,
                        force_keep,
                    )
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
                log.info(
                    "imdb status=%s decision=keep video=%s title=%s year=%s imdb_id=%s rating=%s votes=%s imdb_franchise=%s llm_franchise=%s force_keep=%s",
                    imdb_dbg.status,
                    item.video_path,
                    fields.title,
                    fields.year,
                    imdb_id,
                    imdb_rating,
                    imdb_votes,
                    imdb_franchise,
                    llm_franchise,
                    force_keep,
                )
            elif imdb_dbg.status not in ("ok", "cached"):
                log.info(
                    "imdb status=%s decision=keep reason=%s video=%s title=%s year=%s error=%s candidates=%s",
                    imdb_dbg.status,
                    "imdb_error" if imdb_dbg.status == "error" else "imdb_not_found",
                    item.video_path,
                    fields.title,
                    fields.year,
                    imdb_dbg.error,
                    ";".join(f"{c.get('title')}({c.get('year')})[{c.get('kind')}]" for c in imdb_dbg.candidates[:5]),
                )
            elif imdb_rating is None:
                if (not force_keep) and cfg.imdb.skip_unrated:
                    log.info(
                        "imdb status=%s decision=low_imdb reason=unrated video=%s title=%s year=%s imdb_id=%s rating=%s votes=%s imdb_franchise=%s llm_franchise=%s force_keep=%s",
                        imdb_dbg.status,
                        item.video_path,
                        fields.title,
                        fields.year,
                        imdb_id,
                        imdb_rating,
                        imdb_votes,
                        imdb_franchise,
                        llm_franchise,
                        force_keep,
                    )
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
    
    # Also migrate related json and md files if present
    # We can detect it from item.subtitle_paths? No, that's just subs.
    # But we can check source_storage for .json/.md file with same stem
    if source_storage:
        try:
            d = posixpath.dirname(item.video_path.rstrip("/")) or ""
            json_name = f"{p.stem}.json"
            json_path = posixpath.join(d, json_name)
            md_name = f"{p.stem}.md"
            md_path = posixpath.join(d, md_name)
            
            entries = source_storage.list_dir(d)
            for path, t, _sz in entries:
                if t != "file":
                    continue
                if path == json_path:
                    dest_json = posixpath.join(dest_dir, normalized + ".json")
                    moves.append((json_path, dest_json))
                elif path == md_path:
                    dest_md = posixpath.join(dest_dir, normalized + ".md")
                    moves.append((md_path, dest_md))
        except Exception:
            pass

    return MovePlan(
        source=item,
        normalized_basename=normalized,
        dest_dir=dest_dir,
        dest_video_path=dest_video_path,
        subtitle_moves=tuple(moves),
        skip_reason=None,
    )
