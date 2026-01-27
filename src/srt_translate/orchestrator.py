from __future__ import annotations

import logging
import posixpath
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from pathlib import Path
from dataclasses import dataclass

from .config import AppConfig, normalize_extensions
from .bootstrap import resolve_whisper_command, resolve_whisper_device
from .domain import VideoFile, compute_video_id, subtitle_remote_paths, split_basename
from .daemon_executor import DaemonExecutor
from .logging_util import setup_logging
from .mcp.ftp import FtpMcp
from .mcp.media import MediaMcp
from .mcp.ollama import OllamaMcp, resolve_ollama_model
from .mcp.asr import AsrMcp
from .mcp.pgs_ocr import PgsOcrMcp
from .store import StateStore, TaskRecord
from .subtitle_acquisition import SubtitleSource, choose_source_subtitle
from .subtitle_quality import score_srt_content
from .translation import to_ai_srt_content, translate_srt_to_bilingual
from .summary import generate_summary

# dir_migrate imports
try:
    from dir_migrate.agents.planner import plan_one
    from dir_migrate.agents.executor import apply_one
    from dir_migrate.agents.cleaner import cleanup_sweep
    from dir_migrate.domain import SourceFiles
    from dir_migrate.mcp.llm import LlmMcp
    from dir_migrate.mcp.storage import build_storage_mcp
except ImportError:
    plan_one = None
    apply_one = None
    cleanup_sweep = None
    SourceFiles = None
    LlmMcp = None
    build_storage_mcp = None


log = logging.getLogger("srt_translate.orchestrator")

@dataclass(frozen=True)
class RunSummary:
    videos: int
    skipped: int
    done: int
    failed: int
    elapsed_seconds: float


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
        ollama = OllamaMcp(cfg.ollama.base_url, timeout_seconds=cfg.ollama.timeout_seconds)
        model = resolve_ollama_model(ollama, cfg.ollama.model)
        result = translate_srt_to_bilingual(
            ollama=ollama,
            model=model,
            srt_content=srt_content,
            batch_size=cfg.translation.batch_size,
            max_retries=cfg.translation.max_retries,
            temperature=cfg.ollama.temperature,
        )
        ai_content = to_ai_srt_content(result)
        local_ai.parent.mkdir(parents=True, exist_ok=True)
        local_ai.write_text(ai_content, encoding="utf-8")
    
    if not dry_run:
        with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
            ftp.atomic_write_from_file(ai_remote, local_ai)


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
            ftp.atomic_write_from_file(asr_remote, local_asr)
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
            ftp.atomic_write_from_file(emb_remote, local_emb)
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

        item = SourceFiles(
            video_path=rel_video,
            subtitle_paths=tuple(sorted(subs)),
            video_size_bytes=None, # We can pass None if we don't have it handy or query it
        )
        
        plan = plan_one(migrate_cfg, llm, item, dest_storage, source_storage=source_storage)
        log.info("migrate planned video=%s dest=%s", video_remote_path, plan.dest_video_path)

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

    subs: list[str] = []
    for p, t, _size in source_storage.list_dir(directory):
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
    translation_pool = DaemonExecutor(max_workers=max(1, cfg.translation.workers), thread_name_prefix="translate")
    summary_pool = DaemonExecutor(max_workers=max(1, cfg.translation.workers), thread_name_prefix="summary")
    asr_pool = DaemonExecutor(max_workers=max(1, cfg.whisper.asr_workers), thread_name_prefix="asr")
    pgs_ocr_pool = DaemonExecutor(max_workers=max(1, cfg.pgs_ocr.max_workers), thread_name_prefix="pgs_ocr") if cfg.pgs_ocr.enabled else None
    
    # Migration setup
    migrate_pool = None
    migrate_llm = None
    source_storage = None
    dest_storage = None
    if migrate_cfg and plan_one and apply_one and SourceFiles and LlmMcp and build_storage_mcp:
        migrate_pool = DaemonExecutor(max_workers=2, thread_name_prefix="migrate")
        ollama_migrate = OllamaMcp(migrate_cfg.ollama.base_url, timeout_seconds=migrate_cfg.ollama.timeout_seconds)
        migrate_llm = LlmMcp(ollama_migrate, migrate_cfg.ollama.model, migrate_cfg.ollama.temperature)
        source_storage = build_storage_mcp(migrate_cfg.source)
        dest_storage = build_storage_mcp(migrate_cfg.dest)

    pending: set[Future[object]] = set()
    pending_ops: dict[str, set[str]] = {}
    translation_success: set[str] = set()
    meta: dict[Future[object], tuple[str, str, str, str | None]] = {}
    skipped = 0
    done_count = 0
    failed_count = 0
    migrated_count = 0

    def _schedule_migration(video_id: str, remote_path: str) -> None:
        if not migrate_pool:
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
            _migrate_task, 
            migrate_cfg, 
            migrate_llm, 
            source_storage, 
            dest_storage, 
            remote_path, 
            cfg.ftp.root_path, 
            dry_run
        )
        pending.add(fut)
        # Ensure we wait if pending tasks grow too large, 
        # BUT for migration we usually want it to just run in background.
        # However, the main loop `while pending:` only waits when loop iterates.
        # If we just add tasks here and return, they will run.
        
        meta[fut] = ("migrate", video_id, remote_path, None)

    def _schedule_summary(video_id: str, remote_path: str, source: SubtitleSource) -> None:
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
        fut: Future[object] = summary_pool.submit(generate_summary, cfg, video_id, remote_path, source, force, dry_run)
        pending.add(fut)
        meta[fut] = ("summary", video_id, remote_path, None)

    def _schedule_translation(video_id: str, remote_path: str, source: SubtitleSource) -> None:
        log.info("translate queued video=%s source=%s", remote_path, source.kind)
        if video_id not in pending_ops:
            pending_ops[video_id] = set()
        pending_ops[video_id].add("translate")

        # Also schedule summary in parallel
        _schedule_summary(video_id, remote_path, source)

        store.upsert_task(
            TaskRecord(
                video_id=video_id,
                video_path=remote_path,
                status="TRANSLATING",
                payload={"source_kind": source.kind, "source_remote": source.remote_path},
                updated_at=int(time.time()),
            )
        )
        fut: Future[object] = translation_pool.submit(_translate_and_upload, cfg, video_id, remote_path, source, force, dry_run)
        pending.add(fut)
        meta[fut] = ("translate", video_id, remote_path, source.kind)

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
            asr_device = resolve_whisper_device(cfg.whisper)
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

    with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
        media = MediaMcp()
        pgs_ocr = None
        if cfg.pgs_ocr.enabled:
            pgs_ocr = PgsOcrMcp(
                cache_dir=cfg.paths.local_cache_dir,
                auto_install=cfg.pgs_ocr.auto_install,
                languages=cfg.pgs_ocr.languages,
                keep_temp_files=cfg.pgs_ocr.keep_temp_files,
            )
        for v in videos:
            video_id = compute_video_id(v)
            paths = subtitle_remote_paths(v.remote_path)
            ai_remote = paths["ai"]
            ai_exists = False
            if not force:
                try:
                    ai_exists = ftp.exists(ai_remote)
                except Exception:
                    ai_exists = False
            if not force and ai_exists:
                skipped += 1
                store.upsert_task(
                    TaskRecord(
                        video_id=video_id,
                        video_path=v.remote_path,
                        status="SKIPPED",
                        payload={"reason": "ai_exists", "ai_remote": ai_remote},
                        updated_at=now,
                    )
                )
                if migrate_pool:
                    _schedule_migration(video_id, v.remote_path)
                continue
            if (not force) and (not ai_exists):
                log.info("ai missing video=%s ai=%s", v.remote_path, ai_remote)

            store.upsert_task(
                TaskRecord(
                    video_id=video_id,
                    video_path=v.remote_path,
                    status="DISCOVERED",
                    payload={"remote_path": v.remote_path, "size_bytes": v.size_bytes, "mtime": v.mtime},
                    updated_at=now,
                )
            )

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
                _schedule_translation(video_id, v.remote_path, source)
                # If we scheduled a translation, and concurrency is high, wait a bit
                # to avoid overwhelming the system if we have too many pending tasks
                while len(pending) >= cfg.translation.workers * 2:
                     done, pending = wait(pending, return_when=FIRST_COMPLETED)
                     # Process finished tasks (same logic as main loop)
                     for fut in done:
                        kind, vid, rpath, skind = meta.pop(fut, ("unknown", "", "", None))
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
                                continue
                            log.error("task failed video=%s error=%s stage=%s", rpath, e, kind)
                            failed_count += 1
                            if vid in pending_ops:
                                pending_ops[vid].discard(kind)
                            if kind == "summary" and migrate_pool and (vid in translation_success) and (vid not in pending_ops or not pending_ops[vid]):
                                _schedule_migration(vid, rpath)
                            store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="FAILED", payload={"error": str(e), "stage": kind}, updated_at=int(time.time())))
                            continue
                        if kind in ("asr", "pgs_ocr") and isinstance(res, SubtitleSource):
                            _schedule_translation(vid, rpath, res)
                        elif kind == "translate":
                            done_count += 1
                            store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="DONE", payload={"source_kind": skind}, updated_at=int(time.time())))
                            if vid in pending_ops:
                                pending_ops[vid].discard("translate")
                            translation_success.add(vid)
                            if migrate_pool and (vid not in pending_ops or not pending_ops[vid]):
                                _schedule_migration(vid, rpath)
                        elif kind == "summary":
                            store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="SUMMARY_DONE", payload={}, updated_at=int(time.time())))
                            if vid in pending_ops:
                                pending_ops[vid].discard("summary")
                            if migrate_pool and (vid in translation_success) and (vid not in pending_ops or not pending_ops[vid]):
                                _schedule_migration(vid, rpath)
                        elif kind == "migrate":
                            # res is (success, err)
                            if isinstance(res, tuple) and len(res) >= 2:
                                success = res[0]
                                err = res[1]
                                if success:
                                    migrated_count += 1
                                    store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATED", payload={}, updated_at=int(time.time())))
                                else:
                                    # failed_count += 1 # Migration failure does not fail the whole run
                                    store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATION_FAILED", payload={"error": err}, updated_at=int(time.time())))
                            else:
                                log.error("unexpected migrate result type: %s", type(res))
                continue

            local_video = _download_video(cfg, video_id, v.remote_path)
            source = choose_source_subtitle(
                ftp=ftp,
                media=media,
                pgs_ocr=pgs_ocr,
                cache_dir=cfg.paths.local_cache_dir / "work" / video_id,
                video_remote_path=v.remote_path,
                local_video_path=local_video,
                dry_run=dry_run,
            )
            if source is not None:
                _schedule_translation(video_id, v.remote_path, source)
                continue

            if pgs_ocr_pool and pgs_ocr:
                prev = store.get_task(video_id)
                if (
                    prev is not None
                    and prev.status == "PGS_OCR_FAILED"
                    and (not force)
                    and (cfg.whisper.enabled)
                    and (int(time.time()) - int(prev.updated_at) <= 7 * 86400)
                ):
                    log.info("pgs ocr skipped due to previous failure video=%s", v.remote_path)
                    _schedule_asr(video_id, v.remote_path)
                    continue
                try:
                    tracks = media.probe_subtitles(local_video)
                except Exception:
                    tracks = []
                pgs_tracks = [t for t in tracks if getattr(t, "is_text", False) is False and (t.lang or "").lower() in ("eng", "en") and media.is_pgs(t)]
                if pgs_tracks:
                    def _rank(t) -> tuple[int, int, int, int]:
                        sdh = 1 if "sdh" in (t.title or "").lower() or "hi" in (t.title or "").lower() else 0
                        return (
                            0 if t.is_default else 1,
                            0 if not t.is_forced else 1,
                            sdh,
                            int(t.stream_index),
                        )

                    pgs_tracks.sort(key=_rank)
                    t = pgs_tracks[0]
                    d, stem, _ = split_basename(v.remote_path)
                    lang = (t.lang or "en").strip().lower()
                    if lang == "eng":
                        lang = "en"
                    sup_remote = posixpath.join(d, f"{stem}.{lang}.sup")
                    if force or (not ftp.exists(sup_remote)):
                        local_sup = cfg.paths.local_cache_dir / "work" / video_id / "subs" / posixpath.basename(sup_remote)
                        try:
                            pgs_ocr.extract_track_to_sup(local_video, t.stream_index, local_sup)
                            if not dry_run:
                                ftp.atomic_write_from_file(sup_remote, local_sup)
                            log.info("pgs sup saved video=%s track=%s sup=%s", v.remote_path, t.stream_index, sup_remote)
                        except Exception as e:
                            log.warning("pgs sup extract failed video=%s track=%s error=%s", v.remote_path, t.stream_index, e)
                    _schedule_pgs_ocr(video_id, v.remote_path, sup_remote)
                    continue

            if cfg.whisper.enabled:
                _schedule_asr(video_id, v.remote_path)
                # Also wait if too many pending tasks
                while len(pending) >= cfg.whisper.asr_workers + 2: # Keep queue small for ASR
                     done, pending = wait(pending, return_when=FIRST_COMPLETED)
                     for fut in done:
                        kind, vid, rpath, skind = meta.pop(fut, ("unknown", "", "", None))
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
                                continue
                            log.error("task failed video=%s error=%s stage=%s", rpath, e, kind)
                            failed_count += 1
                            store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="FAILED", payload={"error": str(e), "stage": kind}, updated_at=int(time.time())))
                            continue
                        if kind in ("asr", "pgs_ocr") and isinstance(res, SubtitleSource):
                            _schedule_translation(vid, rpath, res)
                        elif kind == "translate":
                            done_count += 1
                            store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="DONE", payload={"source_kind": skind}, updated_at=int(time.time())))
                            if migrate_pool:
                                _schedule_migration(vid, rpath)
                        elif kind == "migrate":
                            # res is (success, err)
                            if isinstance(res, tuple) and len(res) >= 2:
                                success = res[0]
                                err = res[1]
                                if success:
                                    migrated_count += 1
                                    store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATED", payload={}, updated_at=int(time.time())))
                                else:
                                    # failed_count += 1
                                    store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATION_FAILED", payload={"error": err}, updated_at=int(time.time())))
                            else:
                                log.error("unexpected migrate result type: %s", type(res))
            else:
                failed_count += 1
                store.upsert_task(
                    TaskRecord(
                        video_id=video_id,
                        video_path=v.remote_path,
                        status="FAILED",
                        payload={"error": "no subtitles and whisper disabled"},
                        updated_at=int(time.time()),
                    )
                )

    try:
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                kind, video_id, remote_path, source_kind = meta.pop(fut, ("unknown", "", "", None))
                try:
                    res = fut.result()
                except Exception as e:
                    if kind == "pgs_ocr":
                        log.warning("pgs ocr failed video=%s error=%s", remote_path, e)
                        store.upsert_task(
                            TaskRecord(
                                video_id=video_id,
                                video_path=remote_path,
                                status="PGS_OCR_FAILED",
                                payload={"error": str(e), "stage": kind},
                                updated_at=int(time.time()),
                            )
                        )
                        if cfg.whisper.enabled:
                            _schedule_asr(video_id, remote_path)
                        continue
                    log.error("task failed video=%s error=%s stage=%s", remote_path, e, kind)
                    failed_count += 1
                    if video_id in pending_ops:
                        pending_ops[video_id].discard(kind)
                    if kind == "summary" and migrate_pool and (video_id in translation_success) and (video_id not in pending_ops or not pending_ops[video_id]):
                        _schedule_migration(video_id, remote_path)
                    store.upsert_task(
                        TaskRecord(
                            video_id=video_id,
                            video_path=remote_path,
                            status="FAILED",
                            payload={"error": str(e), "stage": kind},
                            updated_at=int(time.time()),
                        )
                    )
                    continue
                if kind in ("asr", "pgs_ocr"):
                    source = res
                    if isinstance(source, SubtitleSource):
                        _schedule_translation(video_id, remote_path, source)
                    else:
                        failed_count += 1
                        store.upsert_task(
                            TaskRecord(
                                video_id=video_id,
                                video_path=remote_path,
                                status="FAILED",
                                payload={"error": f"invalid {kind} result"},
                                updated_at=int(time.time()),
                            )
                        )
                elif kind == "translate":
                    done_count += 1
                    store.upsert_task(
                        TaskRecord(
                            video_id=video_id,
                            video_path=remote_path,
                            status="DONE",
                            payload={"source_kind": source_kind},
                            updated_at=int(time.time()),
                        )
                    )
                    if video_id in pending_ops:
                        pending_ops[video_id].discard("translate")
                    translation_success.add(video_id)
                    if migrate_pool and (video_id not in pending_ops or not pending_ops[video_id]):
                        _schedule_migration(video_id, remote_path)
                elif kind == "summary":
                    store.upsert_task(
                        TaskRecord(
                            video_id=video_id,
                            video_path=remote_path,
                            status="SUMMARY_DONE",
                            payload={},
                            updated_at=int(time.time()),
                        )
                    )
                    if video_id in pending_ops:
                        pending_ops[video_id].discard("summary")
                    if migrate_pool and (video_id in translation_success) and (video_id not in pending_ops or not pending_ops[video_id]):
                        _schedule_migration(video_id, remote_path)
                elif kind == "migrate":
                    # res is (success, err)
                    if isinstance(res, tuple) and len(res) >= 2:
                        success = res[0]
                        err = res[1]
                        if success:
                            migrated_count += 1
                            store.upsert_task(TaskRecord(video_id=video_id, video_path=remote_path, status="MIGRATED", payload={}, updated_at=int(time.time())))
                        else:
                            # failed_count += 1
                            store.upsert_task(TaskRecord(video_id=video_id, video_path=remote_path, status="MIGRATION_FAILED", payload={"error": err}, updated_at=int(time.time())))
                    else:
                        log.error("unexpected migrate result type: %s", type(res))
        if migrate_cfg and source_storage and cleanup_sweep:
            if migrate_cfg.cleanup.enabled and migrate_cfg.execution.apply and (not dry_run):
                log.info("migrate cleanup sweep start root=/Downloads max_dirs=%d", 200)
                try:
                    removed = cleanup_sweep(migrate_cfg, source_storage, root="", max_dirs=200)
                    log.info("migrate cleanup sweep done removed=%d", removed)
                except Exception as e:
                    log.warning("migrate cleanup sweep failed error=%s", e)
            else:
                log.info(
                    "migrate cleanup sweep skipped enabled=%s apply=%s dry_run=%s",
                    migrate_cfg.cleanup.enabled,
                    migrate_cfg.execution.apply,
                    dry_run,
                )
    except KeyboardInterrupt:
        for fut in list(pending):
            fut.cancel()
        translation_pool.shutdown(wait=False, cancel_futures=True)
        asr_pool.shutdown(wait=False, cancel_futures=True)
        if pgs_ocr_pool:
            pgs_ocr_pool.shutdown(wait=False, cancel_futures=True)
        if migrate_pool:
            migrate_pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        translation_pool.shutdown(wait=False, cancel_futures=False)
        asr_pool.shutdown(wait=False, cancel_futures=False)
        if pgs_ocr_pool:
            pgs_ocr_pool.shutdown(wait=False, cancel_futures=False)
        if migrate_pool:
            migrate_pool.shutdown(wait=False, cancel_futures=False)
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
