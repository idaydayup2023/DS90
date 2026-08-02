from __future__ import annotations

import logging
import posixpath
import time
import threading
from concurrent.futures import Future, wait, FIRST_COMPLETED
from pathlib import Path, PurePosixPath
from dataclasses import dataclass

from typing import Any

from .config import AppConfig, normalize_extensions
from .bootstrap import resolve_whisper_command, resolve_whisper_device
from .domain import VideoFile, compute_video_id, subtitle_remote_paths, split_basename
from .daemon_executor import DaemonExecutor
from .logging_util import setup_logging
from .mcp.ftp import FtpMcp
from .mcp.media import MediaMcp
from .mcp.llm_mcp import build_llm_mcp, resolve_llm_model
from .mcp.asr import AsrMcp
from .mcp.pgs_ocr import PgsOcrMcp
from .store import StateStore, TaskRecord
from .subtitle_acquisition import SubtitleSource, choose_source_subtitle
from .subtitle_quality import score_srt_content
from .translation import to_ai_srt_content, translate_srt_to_bilingual
from .summary import generate_summary

# dir_migrate imports
from dir_migrate.agents.planner import plan_one
from dir_migrate.agents.executor import apply_one
from dir_migrate.agents.cleaner import cleanup_sweep
from dir_migrate.domain import CLASSIFICATION_VERSION, SourceFiles, MovePlan
from dir_migrate.mcp.llm import LlmMcp
from dir_migrate.mcp.storage import build_storage_mcp
from dir_migrate.config import AppConfig as MigrateAppConfig
import dataclasses


log = logging.getLogger("srt_translate.orchestrator")

# Global semaphore to ensure only one heavy FTP operation (video download/upload/move)
# happens at a time across all task pools.
_FTP_HEAVY_SEMAPHORE = threading.Semaphore(1)


@dataclass(frozen=True)
class DiscoveryResult:
    video_id: str
    video_path: str
    action: str  # "MIGRATE" | "TRANSLATE" | "ASR" | "PGS_OCR" | "SKIPPED" | "FAILED"
    source: SubtitleSource | None = None
    sup_remote: str | None = None
    plan: MovePlan | None = None
    error: str | None = None


@dataclass(frozen=True)
class RunSummary:
    videos: int
    skipped: int
    done: int
    failed: int
    elapsed_seconds: float


def subtitle_suffix(video_stem: str, sub_stem: str) -> str:
    """Extract suffix like '.en' or '.zh' from 'movie.en' given 'movie'."""
    if sub_stem.startswith(video_stem):
        return sub_stem[len(video_stem):]
    return ""


def _locked_translate_and_upload(*args, **kwargs):
    # Deprecated: locking inside function now
    return _translate_and_upload(*args, **kwargs)


def _locked_generate_summary(*args, **kwargs):
    return generate_summary(*args, **kwargs)


def _locked_migrate_task(*args, **kwargs):
    return _migrate_task(*args, **kwargs)


def _discovery_task(
    cfg: AppConfig, 
    v: VideoFile, 
    force: bool, 
    dry_run: bool,
    migrate_cfg: MigrateAppConfig | None = None,
    migrate_llm: LlmMcp | None = None,
    source_storage: Any | None = None,
    dest_storage: Any | None = None,
) -> DiscoveryResult:
    video_id = compute_video_id(v)
    paths = subtitle_remote_paths(v.remote_path)
    ai_remote = paths["ai"]
    
    plan: MovePlan | None = None
    
    try:
        with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
            # Pre-plan if migration is enabled to ensure deterministic naming throughout the flow
            if migrate_cfg and migrate_llm and plan_one:
                try:
                    # We need a SourceFiles object. Subtitles are not yet collected, but we can plan with just video
                    item = SourceFiles(video_path=v.remote_path, subtitle_paths=(), video_size_bytes=v.size_bytes)
                    plan = plan_one(migrate_cfg, migrate_llm, item, dest_storage, source_storage=source_storage)
                    log.info("discovery: planned video=%s to=%s", v.remote_path, plan.dest_video_path)
                except Exception as pe:
                    log.warning("discovery: pre-planning failed for %s: %s", v.remote_path, pe)

            ai_exists = False
            if not force:
                try:
                    ai_exists = ftp.exists(ai_remote)
                    log.debug("discovery: ai_remote=%s exists=%s", ai_remote, ai_exists)
                except Exception as e:
                    log.warning("discovery: failed to check ai_exists: %s", e)
                    ai_exists = False
            if not force and ai_exists:
                log.info("discovery: ai exists, action=MIGRATE video=%s", v.remote_path)
                return DiscoveryResult(video_id, v.remote_path, "MIGRATE", plan=plan)

            # Try to choose subtitle without video download first (external or cached)
            source = choose_source_subtitle(
                ftp=ftp,
                media=None,
                pgs_ocr=None,
                cache_dir=cfg.paths.local_cache_dir / "work" / video_id,
                video_remote_path=v.remote_path,
                local_video_path=None,
                dry_run=dry_run,
            )
            if source is not None:
                return DiscoveryResult(video_id, v.remote_path, "TRANSLATE", source=source, plan=plan)

            # Need to download video for internal subtitle extraction or PGS OCR
            local_video = _local_video_path(cfg.paths.local_cache_dir, video_id, v.remote_path)
            if not (local_video.exists() and local_video.stat().st_size > 0):
                log.info("downloading video for subtitle discovery: %s", v.remote_path)
                with _FTP_HEAVY_SEMAPHORE:
                    ftp.download(v.remote_path, local_video)
            
            media = MediaMcp()
            # Try again with local video
            source = choose_source_subtitle(
                ftp=ftp,
                media=media,
                pgs_ocr=None,
                cache_dir=cfg.paths.local_cache_dir / "work" / video_id,
                video_remote_path=v.remote_path,
                local_video_path=local_video,
                dry_run=dry_run,
            )
            if source is not None:
                return DiscoveryResult(video_id, v.remote_path, "TRANSLATE", source=source, plan=plan)

            # Check for PGS tracks if enabled
            if cfg.pgs_ocr.enabled:
                try:
                    tracks = media.probe_subtitles(local_video)
                except Exception:
                    tracks = []
                pgs_tracks = [t for t in tracks if getattr(t, "is_text", False) is False and (t.lang or "").lower() in ("eng", "en") and media.is_pgs(t)]
                if pgs_tracks:
                    def _rank(t) -> tuple[int, int, int, int]:
                        sdh = 1 if "sdh" in (t.title or "").lower() or "hi" in (t.title or "").lower() else 0
                        return (0 if t.is_default else 1, 0 if not t.is_forced else 1, sdh, int(t.stream_index))

                    pgs_tracks.sort(key=_rank)
                    t = pgs_tracks[0]
                    d, stem, _ = split_basename(v.remote_path)
                    lang = (t.lang or "en").strip().lower()
                    if lang == "eng": lang = "en"
                    sup_remote = posixpath.join(d, f"{stem}.{lang}.sup")
                    
                    if force or (not ftp.exists(sup_remote)):
                        local_sup = cfg.paths.local_cache_dir / "work" / video_id / "subs" / posixpath.basename(sup_remote)
                        pgs_ocr = PgsOcrMcp(
                            cache_dir=cfg.paths.local_cache_dir,
                            auto_install=cfg.pgs_ocr.auto_install,
                            languages=cfg.pgs_ocr.languages,
                            keep_temp_files=cfg.pgs_ocr.keep_temp_files,
                        )
                        pgs_ocr.extract_track_to_sup(local_video, t.stream_index, local_sup)
                        if not dry_run:
                            ftp.atomic_write_from_file(sup_remote, local_sup)
                        log.info("pgs sup saved video=%s track=%s sup=%s", v.remote_path, t.stream_index, sup_remote)
                    
                    return DiscoveryResult(video_id, v.remote_path, "PGS_OCR", sup_remote=sup_remote, plan=plan)

            # Fallback to ASR
            if cfg.whisper.enabled:
                return DiscoveryResult(video_id, v.remote_path, "ASR", plan=plan)
            
            return DiscoveryResult(video_id, v.remote_path, "FAILED", error="no subtitles found and ASR disabled", plan=plan)

    except Exception as e:
        log.exception("discovery failed video=%s", v.remote_path)
        return DiscoveryResult(video_id, v.remote_path, "FAILED", error=str(e))


def _local_video_path(cache_dir: Path, video_id: str, remote_path: str) -> Path:
    suffix = Path(remote_path).suffix.lower() or ".video"
    return cache_dir / "videos" / f"{video_id}{suffix}"

def _local_sub_path_for_video(cache_dir: Path, video_id: str, remote_sub_path: str) -> Path:
    name = Path(remote_sub_path).name
    return cache_dir / "work" / video_id / "subs" / name

def _local_ai_path_for_video(cache_dir: Path, video_id: str, video_remote_path: str) -> Path:
    ai_remote = subtitle_remote_paths(video_remote_path)["ai"]
    return cache_dir / "work" / video_id / "out" / Path(ai_remote).name


def _download_video(cfg: AppConfig, video_id: str, video_remote_path: str) -> Path:
    local = _local_video_path(cfg.paths.local_cache_dir, video_id, video_remote_path)
    if local.exists() and local.stat().st_size > 0:
        return local
    with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
        with _FTP_HEAVY_SEMAPHORE:
            ftp.download(video_remote_path, local)
    return local


def _translate_and_upload(
    cfg: AppConfig,
    video_id: str,
    video_remote_path: str,
    source: SubtitleSource,
    force: bool,
    dry_run: bool,
) -> None:
    paths = subtitle_remote_paths(video_remote_path)
    ai_remote = paths["ai"]
    with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
        if not force and ftp.exists(ai_remote):
            return
    
    # Check if local .ai.srt already exists (from previous partial run)
    local_ai = _local_ai_path_for_video(cfg.paths.local_cache_dir, video_id, video_remote_path)
    if local_ai.exists() and local_ai.stat().st_size > 0:
        log.info("using cached translation result: %s", local_ai)
        ai_content = local_ai.read_text(encoding="utf-8")
    else:
        srt_content = source.local_path.read_text(encoding="utf-8", errors="replace")
        llm = build_llm_mcp(cfg.llm.provider, cfg.llm.base_url, timeout_seconds=cfg.llm.timeout_seconds)
        model = resolve_llm_model(llm, cfg.llm.model)
        
        # Lock removed as per user request
        result = translate_srt_to_bilingual(
            llm=llm,
            model=model,
            srt_content=srt_content,
            batch_size=cfg.translation.batch_size,
            max_retries=cfg.translation.max_retries,
            temperature=cfg.llm.temperature,
        )
            
        ai_content = to_ai_srt_content(result)
        local_ai.parent.mkdir(parents=True, exist_ok=True)
        local_ai.write_text(ai_content, encoding="utf-8")
    
    if not dry_run:
        with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
            log.info("uploading translation result to ftp: %s", ai_remote)
            ftp.atomic_write_from_file(ai_remote, local_ai)
            log.info("upload translation done: %s", ai_remote)


def _asr_then_upload(
    cfg: AppConfig,
    video_id: str,
    video_remote_path: str,
    asr_command: tuple[str, ...],
    asr_device: str,
    dry_run: bool,
) -> SubtitleSource:
    local_video = _download_video(cfg, video_id, video_remote_path)
    paths = subtitle_remote_paths(video_remote_path)
    asr_remote = paths["asr"]
    local_asr = _local_sub_path_for_video(cfg.paths.local_cache_dir, video_id, asr_remote)
    asr = AsrMcp(
        asr_command,
        cfg.whisper.language,
        asr_device,
        cfg.whisper.model,
        cfg.whisper.task,
        cfg.whisper.temperature,
        cfg.whisper.no_speech_threshold,
        cfg.whisper.fallback_models,
    )
    asr.transcribe_to_srt(local_video, local_asr)
    if not dry_run:
        with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
            log.info("uploading asr result to ftp: %s", asr_remote)
            ftp.atomic_write_from_file(asr_remote, local_asr)
            log.info("upload asr done: %s", asr_remote)
    return SubtitleSource(kind="asr", remote_path=asr_remote, local_path=local_asr, quality=None, meta={"generated": True})


def _pgs_ocr_sup_then_upload(
    cfg: AppConfig,
    video_id: str,
    video_remote_path: str,
    sup_remote_path: str,
    dry_run: bool,
) -> SubtitleSource:
    cache_dir = cfg.paths.local_cache_dir / "work" / video_id
    paths = subtitle_remote_paths(video_remote_path)
    emb_remote = paths["emb"]
    local_sup = cache_dir / "subs" / posixpath.basename(sup_remote_path)
    local_emb = cache_dir / "subs" / Path(emb_remote).name
    with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
        ftp.download(sup_remote_path, local_sup)
    ocr = PgsOcrMcp(
        cache_dir=cfg.paths.local_cache_dir,
        auto_install=cfg.pgs_ocr.auto_install,
        languages=cfg.pgs_ocr.languages,
        keep_temp_files=cfg.pgs_ocr.keep_temp_files,
    )
    ocr.sup_to_srt(local_sup, local_emb)
    if not dry_run:
        with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
            log.info("uploading pgs ocr result to ftp: %s", emb_remote)
            ftp.atomic_write_from_file(emb_remote, local_emb)
            log.info("upload pgs ocr done: %s", emb_remote)
    q = score_srt_content(local_emb.read_text(encoding="utf-8", errors="replace"))
    return SubtitleSource(
        kind="emb",
        remote_path=emb_remote,
        local_path=local_emb,
        quality=q,
        meta={"ocr": True, "sup_remote": sup_remote_path},
    )


def _migrate_task(
    migrate_cfg,
    llm,
    source_storage,
    dest_storage,
    video_remote_path: str,
    root_path: str,
    dry_run: bool,
    store: StateStore | None = None,
    video_id: str | None = None,
) -> tuple[bool, str | None]:
    try:
        if plan_one is None or apply_one is None or SourceFiles is None:
            raise RuntimeError("dir_migrate not available")
        rel_video = video_remote_path
        if rel_video.startswith(root_path):
            rel_video = rel_video[len(root_path):].lstrip("/")
        
        log.info("migrate task start video=%s rel=%s", video_remote_path, rel_video)
        subs = _collect_related_subtitles_for_migration(source_storage, rel_video, migrate_cfg.subtitle.extensions)
        log.info("migrate found subs video=%s subs=%s", video_remote_path, subs)

        plan: MovePlan | None = None
        # Try to retrieve pre-planned info from store to ensure determinism
        if store and video_id:
            task = store.get_task(video_id)
            if task and task.payload.get("plan"):
                try:
                    plan_data = task.payload["plan"]
                    if plan_data.get("classification_version") != CLASSIFICATION_VERSION:
                        raise ValueError("stored migration plan uses stale classification rules")
                    pending_reason = plan_data.get("skip_reason")
                    if pending_reason:
                        log.warning(
                            "migrate classification pending video=%s reason=%s",
                            video_remote_path,
                            pending_reason,
                        )
                        return False, f"CLASSIFICATION_PENDING: {pending_reason}"
                    source_data = plan_data["source"]
                    
                    # Reconstruct SourceFiles with current subtitles (might have more now)
                    source_files = SourceFiles(
                        video_path=rel_video,
                        subtitle_paths=tuple(sorted(subs)),
                        video_size_bytes=source_data.get("video_size_bytes")
                    )
                    
                    # Reconstruct MovePlan using the locked normalized_basename and dest_dir
                    # We re-calculate dest_video_path and subtitle_moves based on these locked values
                    locked_basename = plan_data["normalized_basename"]
                    locked_dest_dir = plan_data["dest_dir"]
                    
                    p_orig = PurePosixPath(rel_video)
                    dv = posixpath.join(locked_dest_dir, locked_basename + p_orig.suffix)
                    
                    moves = []
                    subtitle_exts = {str(e).lower() for e in migrate_cfg.subtitle.extensions}
                    existing_src = set()
                    for s in subs:
                        sp = PurePosixPath(s)
                        suffix = subtitle_suffix(p_orig.stem, sp.stem)
                        dest_sub = posixpath.join(locked_dest_dir, locked_basename + suffix + sp.suffix)
                        moves.append((s, dest_sub))
                        existing_src.add(s)

                    locked_moves = plan_data.get("subtitle_moves") or []
                    for pair in locked_moves:
                        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                            continue
                        src_locked = str(pair[0])
                        dst_locked = str(pair[1])
                        ext = PurePosixPath(src_locked).suffix.lower()
                        if ext in subtitle_exts:
                            if src_locked in existing_src:
                                continue
                            sp = PurePosixPath(src_locked)
                            suffix = subtitle_suffix(p_orig.stem, sp.stem)
                            dst_locked = posixpath.join(locked_dest_dir, locked_basename + suffix + sp.suffix)
                            existing_src.add(src_locked)
                        moves.append((src_locked, dst_locked))
                    
                    plan = MovePlan(
                        source=source_files,
                        normalized_basename=locked_basename,
                        dest_dir=locked_dest_dir,
                        dest_video_path=dv,
                        subtitle_moves=tuple(moves),
                        skip_reason=None
                    )
                    log.info("migrate: using locked pre-plan for %s -> %s", video_remote_path, plan.dest_video_path)
                except Exception as ee:
                    log.warning("migrate: failed to reconstruct locked pre-plan: %s", ee)

        if plan is None:
            item = SourceFiles(
                video_path=rel_video,
                subtitle_paths=tuple(sorted(subs)),
                video_size_bytes=None,
            )
            # plan_one is deterministic now with temperature 0.0, but we prefer the locked one above
            plan = plan_one(migrate_cfg, llm, item, dest_storage, source_storage=source_storage)
            log.info("migrate planned video=%s dest=%s", video_remote_path, plan.dest_video_path)

        if plan.skip_reason:
            log.warning(
                "migrate classification pending video=%s reason=%s",
                video_remote_path,
                plan.skip_reason,
            )
            return False, f"CLASSIFICATION_PENDING: {plan.skip_reason}"

        with _FTP_HEAVY_SEMAPHORE:
            success, result, error = apply_one(migrate_cfg, source_storage, dest_storage, plan)
            
        if not success:
            log.error("migrate apply failed video=%s error=%s", video_remote_path, error)
            return False, f"{result}: {error}"
        
        log.info("migrate success video=%s", video_remote_path)
        return True, None
    except Exception as e:
        log.exception("migrate task exception video=%s", video_remote_path)
        return False, str(e)


def _collect_related_subtitles_for_migration(source_storage, rel_video_path: str, subtitle_exts: tuple[str, ...]) -> list[str]:
    directory = posixpath.dirname(rel_video_path)
    video_stem = posixpath.splitext(posixpath.basename(rel_video_path))[0]
    stem_lower = video_stem.lower()
    ext_set = {e.lower() for e in subtitle_exts}

    # No caching here to ensure we see the most up-to-date file list (especially newly created .ai.srt)
    entries = source_storage.list_dir(directory)

    subs: list[str] = []
    for p, t, _size in entries:
        if t != "file":
            continue
        name = posixpath.basename(p)
        lower = name.lower()
        _root, ext = posixpath.splitext(lower)
        if ext not in ext_set:
            continue
        if lower == f"{stem_lower}{ext}" or lower.startswith(stem_lower + "."):
            subs.append(p.lstrip("/"))
    return sorted(set(subs))


def _handle_future_result(
    fut: Future[object],
    meta: dict[Future[object], tuple[str, str, str, Any]],
    store: StateStore,
    cfg: AppConfig,
    pending_ops: dict[str, set[str]],
    translation_success: set[str],
    migrate_pool: DaemonExecutor | None,
    _schedule_asr: Any,
    _schedule_translation: Any,
    _schedule_summary: Any,
    _schedule_migration: Any,
    _schedule_pgs_ocr: Any,
) -> tuple[int, int, int]:
    """Returns (done_delta, failed_delta, migrated_delta)"""
    done_delta = 0
    failed_delta = 0
    migrated_delta = 0

    kind, vid, rpath, extra = meta.pop(fut, ("unknown", "", "", None))
    log.info("task finished kind=%s video=%s", kind, rpath)
    try:
        res = fut.result()
    except Exception as e:
        if kind == "pgs_ocr":
            log.warning("pgs ocr failed video=%s error=%s", rpath, e)
            store.upsert_task(
                TaskRecord(
                    video_id=vid,
                    video_path=rpath,
                    status="PGS_OCR_FAILED",
                    payload={"error": str(e), "stage": kind},
                    updated_at=int(time.time()),
                )
            )
            if cfg.whisper.enabled:
                _schedule_asr(vid, rpath)
            return 0, 0, 0
        
        log.error("task failed video=%s error=%s stage=%s", rpath, e, kind)
        failed_delta = 1
        if vid in pending_ops:
            pending_ops[vid].discard(kind)
        
        # Even if summary fails, we might still want to migrate if translation succeeded
        if kind == "summary" and migrate_pool and (vid in translation_success) and (vid not in pending_ops or not pending_ops[vid]):
            _schedule_migration(vid, rpath)
            
        store.upsert_task(
            TaskRecord(
                video_id=vid,
                video_path=rpath,
                status="FAILED",
                payload={"error": str(e), "stage": kind},
                updated_at=int(time.time()),
            )
        )
        return 0, 1, 0

    if kind == "discover":
        if isinstance(res, DiscoveryResult):
            log.info("discovery result: video=%s action=%s", rpath, res.action)
            payload = {}
            if res.plan:
                payload["plan"] = dataclasses.asdict(res.plan)

            if res.action == "MIGRATE":
                _schedule_migration(vid, rpath)
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="TRANSLATED", payload=payload, updated_at=int(time.time())))
                done_delta = 1
            elif res.action == "TRANSLATE" and res.source:
                _schedule_translation(vid, rpath, res.source)
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="DISCOVERED", payload=payload, updated_at=int(time.time())))
            elif res.action == "ASR":
                _schedule_asr(vid, rpath)
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="DISCOVERED", payload=payload, updated_at=int(time.time())))
            elif res.action == "PGS_OCR" and res.sup_remote:
                _schedule_pgs_ocr(vid, rpath, res.sup_remote)
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="DISCOVERED", payload=payload, updated_at=int(time.time())))
            elif res.action == "FAILED":
                log.error("discovery failed video=%s error=%s", rpath, res.error)
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="FAILED", payload={"error": res.error}, updated_at=int(time.time())))
                failed_delta = 1
            elif res.action == "SKIPPED":
                done_delta = 1
        else:
            log.error("unexpected discovery result type: %s", type(res))
            failed_delta = 1

    elif kind in ("asr", "pgs_ocr"):
        if isinstance(res, SubtitleSource):
            _schedule_translation(vid, rpath, res)
        else:
            log.error("invalid %s result type: %s", kind, type(res))
            store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="FAILED", payload={"error": f"invalid {kind} result"}, updated_at=int(time.time())))
            return 0, 1, 0
    elif kind == "translate":
        done_delta = 1
        source_obj = extra
        actual_kind_str = source_obj.kind if hasattr(source_obj, "kind") else str(source_obj)
        
        store.upsert_task(
            TaskRecord(
                video_id=vid,
                video_path=rpath,
                status="DONE",
                payload={"source_kind": actual_kind_str},
                updated_at=int(time.time()),
            )
        )
        if vid in pending_ops:
            pending_ops[vid].discard("translate")
        translation_success.add(vid)

        # Schedule summary serially after translation
        if isinstance(source_obj, SubtitleSource):
            _schedule_summary(vid, rpath, source_obj)

        if migrate_pool and (vid not in pending_ops or not pending_ops[vid]):
            _schedule_migration(vid, rpath)
    elif kind == "summary":
        store.upsert_task(
            TaskRecord(
                video_id=vid,
                video_path=rpath,
                status="SUMMARY_DONE",
                payload={},
                updated_at=int(time.time()),
            )
        )
        if vid in pending_ops:
            pending_ops[vid].discard("summary")
        if migrate_pool and (vid in translation_success) and (vid not in pending_ops or not pending_ops[vid]):
            _schedule_migration(vid, rpath)
    elif kind == "migrate":
        if isinstance(res, tuple) and len(res) >= 2:
            success, err = res[0], res[1]
            if success:
                migrated_delta = 1
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATED", payload={}, updated_at=int(time.time())))
            elif err and "CONFLICT" in str(err):
                # If it's a conflict, it means the file is already at destination
                log.info("migration conflict video=%s: considering as migrated", rpath)
                migrated_delta = 1
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATED", payload={"info": "conflict: already exists"}, updated_at=int(time.time())))
            elif err and "CLASSIFICATION_PENDING" in str(err):
                log.warning("migration pending confirmation video=%s reason=%s", rpath, err)
                store.upsert_task(
                    TaskRecord(
                        video_id=vid,
                        video_path=rpath,
                        status="CLASSIFICATION_PENDING",
                        payload={"reason": err},
                        updated_at=int(time.time()),
                    )
                )
            else:
                store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATION_FAILED", payload={"error": err}, updated_at=int(time.time())))
        else:
            log.error("unexpected migrate result type: %s", type(res))
            
    return done_delta, failed_delta, migrated_delta


def run_once(cfg: AppConfig, store: StateStore, force: bool, dry_run: bool, migrate_cfg=None) -> RunSummary:
    setup_logging()
    started = time.time()
    exts = normalize_extensions(cfg.video.extensions)
    log.info("run_once start force=%s dry_run=%s migrate=%s", force, dry_run, migrate_cfg is not None)
    log.info("scan ftp_root=%s extensions=%s", cfg.ftp.root_path, ",".join(exts))

    videos: list[VideoFile] = []
    with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
        for e in ftp.walk_files(cfg.ftp.root_path):
            p = e.path
            low_dir = posixpath.join(cfg.ftp.root_path.rstrip("/"), "low_imdb")
            if ("/low_imdb/" in p) or p.rstrip("/").endswith("/low_imdb"):
                continue
            lower = p.lower()
            if not any(lower.endswith(x) for x in exts):
                continue
            if e.size is not None and e.size < cfg.video.min_bytes:
                continue
            videos.append(
                VideoFile(
                    remote_path=p,
                    size_bytes=e.size,
                    mtime=e.mtime,
                )
            )

    now = int(time.time())
    discovery_pool = DaemonExecutor(max_workers=max(1, cfg.ftp.concurrency), thread_name_prefix="discover")
    translation_pool = DaemonExecutor(max_workers=max(1, cfg.translation.workers), thread_name_prefix="translate")
    summary_pool = DaemonExecutor(max_workers=max(1, cfg.summary.workers), thread_name_prefix="summary")
    asr_pool = DaemonExecutor(max_workers=max(1, cfg.whisper.asr_workers), thread_name_prefix="asr")
    pgs_ocr_pool = DaemonExecutor(max_workers=max(1, cfg.pgs_ocr.max_workers), thread_name_prefix="pgs_ocr") if cfg.pgs_ocr.enabled else None
    
    # Migration setup
    migrate_pool = None
    migrate_llm = None
    source_storage = None
    dest_storage = None
    if migrate_cfg and plan_one and apply_one and SourceFiles and LlmMcp and build_storage_mcp:
        log.info("migration enabled: initializing migrate_pool")
        migrate_pool = DaemonExecutor(max_workers=max(1, migrate_cfg.execution.workers), thread_name_prefix="migrate")
        llm_mcp_migrate = build_llm_mcp(migrate_cfg.llm.provider, migrate_cfg.llm.base_url, timeout_seconds=migrate_cfg.llm.timeout_seconds)
        model_migrate = resolve_llm_model(llm_mcp_migrate, migrate_cfg.llm.model)
        migrate_llm = LlmMcp(llm_mcp_migrate, model_migrate, migrate_cfg.llm.temperature)
        source_storage = build_storage_mcp(migrate_cfg.source)
        dest_storage = build_storage_mcp(migrate_cfg.dest)
    else:
        log.warning(
            "migration disabled: cfg=%s planner=%s executor=%s storage=%s",
            migrate_cfg is not None,
            plan_one is not None,
            apply_one is not None,
            build_storage_mcp is not None,
        )

    pending: set[Future[object]] = set()
    pending_ops: dict[str, set[str]] = {}
    translation_success: set[str] = set()
    meta: dict[Future[object], tuple[str, str, str, Any]] = {}
    skipped = 0
    done_count = 0
    failed_count = 0
    migrated_count = 0

    def _schedule_discovery(v: VideoFile) -> None:
        video_id = compute_video_id(v)
        log.info("discovery queued video=%s", v.remote_path)
        store.upsert_task(
            TaskRecord(
                video_id=video_id,
                video_path=v.remote_path,
                status="DISCOVERING",
                payload={"remote_path": v.remote_path, "size_bytes": v.size_bytes, "mtime": v.mtime},
                updated_at=int(time.time()),
            )
        )
        fut: Future[object] = discovery_pool.submit(_discovery_task, cfg, v, force, dry_run, migrate_cfg, migrate_llm, source_storage, dest_storage)
        pending.add(fut)
        meta[fut] = ("discover", video_id, v.remote_path, None)

    def _schedule_migration(video_id: str, remote_path: str) -> None:
        if not migrate_pool:
            return
        
        # Check if already migrated
        if store:
            task = store.get_task(video_id)
            if task and task.status == "MIGRATED":
                log.info("migrate skip (already MIGRATED in store): %s", remote_path)
                return

        log.info("migrate queued video=%s", remote_path)
        store.upsert_task(
            TaskRecord(
                video_id=video_id,
                video_path=remote_path,
                status="MIGRATING",
                payload={},
                updated_at=int(time.time()),
            )
        )
        fut = migrate_pool.submit(
            _locked_migrate_task, 
            migrate_cfg, 
            migrate_llm, 
            source_storage, 
            dest_storage, 
            remote_path, 
            cfg.ftp.root_path, 
            dry_run,
            store,
            video_id
        )
        pending.add(fut)
        meta[fut] = ("migrate", video_id, remote_path, None)

    def _schedule_summary(video_id: str, remote_path: str, source: SubtitleSource) -> None:
        if not cfg.summary.enabled:
            return
        log.info("summary queued video=%s", remote_path)
        if video_id not in pending_ops:
            pending_ops[video_id] = set()
        pending_ops[video_id].add("summary")
        
        store.upsert_task(
            TaskRecord(
                video_id=video_id,
                video_path=remote_path,
                status="SUMMARY_QUEUED",
                payload={"source_kind": source.kind},
                updated_at=int(time.time()),
            )
        )
        fut: Future[object] = summary_pool.submit(_locked_generate_summary, cfg, video_id, remote_path, source, force, dry_run)
        pending.add(fut)
        meta[fut] = ("summary", video_id, remote_path, None)

    def _schedule_translation(video_id: str, remote_path: str, source: SubtitleSource) -> None:
        log.info("translate queued video=%s source=%s", remote_path, source.kind)
        if video_id not in pending_ops:
            pending_ops[video_id] = set()
        pending_ops[video_id].add("translate")

        store.upsert_task(
            TaskRecord(
                video_id=video_id,
                video_path=remote_path,
                status="TRANSLATING",
                payload={"source_kind": source.kind, "source_remote": source.remote_path},
                updated_at=int(time.time()),
            )
        )
        fut: Future[object] = translation_pool.submit(_locked_translate_and_upload, cfg, video_id, remote_path, source, force, dry_run)
        pending.add(fut)
        meta[fut] = ("translate", video_id, remote_path, source)

    def _schedule_asr(video_id: str, remote_path: str) -> None:
        nonlocal failed_count
        log.info("asr queued video=%s", remote_path)
        store.upsert_task(
            TaskRecord(
                video_id=video_id,
                video_path=remote_path,
                status="ASR_QUEUED",
                payload={},
                updated_at=int(time.time()),
            )
        )
        try:
            asr_cmd = resolve_whisper_command(cfg.whisper, cache_dir=cfg.paths.local_cache_dir)
            asr_device = resolve_whisper_device(cfg.whisper, cache_dir=cfg.paths.local_cache_dir)
        except Exception as e:
            failed_count += 1
            store.upsert_task(
                TaskRecord(
                    video_id=video_id,
                    video_path=remote_path,
                    status="FAILED",
                    payload={"error": str(e), "stage": "asr_bootstrap"},
                    updated_at=int(time.time()),
                )
            )
            log.error("asr bootstrap failed video=%s error=%s", remote_path, e)
            return
        fut_asr: Future[object] = asr_pool.submit(_asr_then_upload, cfg, video_id, remote_path, asr_cmd, asr_device, dry_run)
        pending.add(fut_asr)
        meta[fut_asr] = ("asr", video_id, remote_path, None)

    def _schedule_pgs_ocr(video_id: str, remote_path: str, sup_remote_path: str) -> None:
        if not pgs_ocr_pool:
            return
        if dry_run:
            return
        log.info("pgs ocr queued video=%s sup=%s", remote_path, sup_remote_path)
        store.upsert_task(
            TaskRecord(
                video_id=video_id,
                video_path=remote_path,
                status="PGS_OCR_QUEUED",
                payload={"sup_remote": sup_remote_path},
                updated_at=int(time.time()),
            )
        )
        fut: Future[object] = pgs_ocr_pool.submit(_pgs_ocr_sup_then_upload, cfg, video_id, remote_path, sup_remote_path, dry_run)
        pending.add(fut)
        meta[fut] = ("pgs_ocr", video_id, remote_path, None)

    # Phase 1: Fast scheduling
    for v in videos:
        _schedule_discovery(v)

    # Phase 2: Handle all tasks in the pool
    try:
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED, timeout=10)
            if not done:
                # Add a periodic status report to see what's actually running
                active_kinds = {}
                for f in pending:
                    k = meta.get(f, ("unknown",))[0]
                    active_kinds[k] = active_kinds.get(k, 0) + 1
                
                # Check for stalled downloads/uploads by looking at logs
                log.info("Status Report: Waiting for %d tasks: %s", len(pending), active_kinds)
                continue
                
            for fut in done:
                dd, fd, md = _handle_future_result(
                    fut, meta, store, cfg, pending_ops, translation_success, migrate_pool,
                    _schedule_asr, _schedule_translation, _schedule_summary, _schedule_migration, _schedule_pgs_ocr
                )
                done_count += dd
                failed_count += fd
                migrated_count += md

        # Cleanup sweep (only if migration was active)
        if migrate_cfg and source_storage and cleanup_sweep:
            if migrate_cfg.cleanup.enabled and migrate_cfg.execution.apply and (not dry_run):
                log.info("migrate cleanup sweep start root=/Downloads max_dirs=%d", 200)
                try:
                    removed = cleanup_sweep(migrate_cfg, source_storage, root="", max_dirs=200)
                    log.info("migrate cleanup sweep done removed=%d", removed)
                except Exception as e:
                    log.warning("migrate cleanup sweep failed error=%s", e)
    except KeyboardInterrupt:
        for fut in list(pending):
            fut.cancel()
        discovery_pool.shutdown(wait=False, cancel_futures=True)
        translation_pool.shutdown(wait=False, cancel_futures=True)
        asr_pool.shutdown(wait=False, cancel_futures=True)
        if pgs_ocr_pool:
            pgs_ocr_pool.shutdown(wait=False, cancel_futures=True)
        if migrate_pool:
            migrate_pool.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        discovery_pool.shutdown(wait=True)
        translation_pool.shutdown(wait=True)
        summary_pool.shutdown(wait=True)
        asr_pool.shutdown(wait=True)
        if pgs_ocr_pool:
            pgs_ocr_pool.shutdown(wait=True)
        if migrate_pool:
            migrate_pool.shutdown(wait=True)
    elapsed = time.time() - started
    log.info(
        "run_once summary videos=%d skipped=%d done=%d failed=%d elapsed=%.2fs",
        len(videos),
        skipped,
        done_count,
        failed_count,
        elapsed,
    )
    return RunSummary(videos=len(videos), skipped=skipped, done=done_count, failed=failed_count, elapsed_seconds=elapsed)
