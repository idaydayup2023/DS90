from __future__ import annotations

import logging
import time
from concurrent.futures import FIRST_COMPLETED, Future, wait
from pathlib import Path
from dataclasses import dataclass

from .config import AppConfig, normalize_extensions
from .domain import VideoFile, compute_video_id, subtitle_remote_paths
from .daemon_executor import DaemonExecutor
from .logging_util import setup_logging
from .mcp.ftp import FtpMcp
from .mcp.media import MediaMcp
from .mcp.ollama import OllamaMcp
from .mcp.asr import AsrMcp
from .store import StateStore, TaskRecord
from .subtitle_acquisition import SubtitleSource, choose_source_subtitle
from .translation import to_ai_srt_content, translate_srt_to_bilingual

# dir_migrate imports
try:
    from dir_migrate.agents.planner import plan_one
    from dir_migrate.agents.executor import apply_one
    from dir_migrate.domain import SourceFiles
    from dir_migrate.mcp.llm import LlmMcp
    from dir_migrate.mcp.storage import build_storage_mcp
except ImportError:
    plan_one = None
    apply_one = None
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


def _normalize_model_name(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _suggest_model(preferred: str, available: list[str]) -> str | None:
    pref_norm = _normalize_model_name(preferred)
    if not available:
        return None
    for m in available:
        if _normalize_model_name(m) == pref_norm:
            return m
    candidates = [
        preferred,
        preferred + ":latest" if ":" not in preferred else preferred,
        preferred.replace("tranlate", "translate"),
        preferred.replace("tranlategemma", "translategemma"),
        preferred.replace("translate-gemma", "translategemma"),
        preferred.replace("translategemma", "translategemma:latest"),
    ]
    candidates = [c for c in candidates if c and c != preferred]
    for c in candidates:
        c_norm = _normalize_model_name(c)
        for m in available:
            if _normalize_model_name(m) == c_norm:
                return m
    for m in available:
        if "translategemma" in _normalize_model_name(m):
            return m
    return None


def _resolve_ollama_model(ollama: OllamaMcp, preferred: str) -> str:
    try:
        available = ollama.tags()
    except Exception:
        return preferred
    return _suggest_model(preferred, available) or preferred


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
        model = _resolve_ollama_model(ollama, cfg.ollama.model)
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


def _asr_then_upload(cfg: AppConfig, video_id: str, video_remote_path: str, dry_run: bool) -> SubtitleSource:
    local_video = _download_video(cfg, video_id, video_remote_path)
    paths = subtitle_remote_paths(video_remote_path)
    asr_remote = paths["asr"]
    local_asr = _local_sub_path_for_video(cfg.paths.local_cache_dir, video_id, asr_remote)
    asr = AsrMcp(cfg.whisper.command, cfg.whisper.language)
    asr.transcribe_to_srt(local_video, local_asr)
    if not dry_run:
        with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
            ftp.atomic_write_from_file(asr_remote, local_asr)
    return SubtitleSource(kind="asr", remote_path=asr_remote, local_path=local_asr, quality=None, meta={"generated": True})


def _migrate_task(
    migrate_cfg,
    llm,
    source_storage,
    dest_storage,
    video_remote_path: str,
    root_path: str,
    dry_run: bool,
) -> tuple[bool, str | None]:
    # Convert absolute to relative
    rel_video = video_remote_path
    if rel_video.startswith(root_path):
        rel_video = rel_video[len(root_path):].lstrip("/")
    
    # Find subtitles (re-scan directory using source_storage to be sure)
    # dir_migrate scanner uses list_dir.
    # We can just check the standard paths we know about.
    paths = subtitle_remote_paths(video_remote_path)
    # paths is {'ai': ..., 'eng': ...} absolute
    
    subs = []
    for k, v in paths.items():
        rel_sub = v
        if rel_sub.startswith(root_path):
            rel_sub = rel_sub[len(root_path):].lstrip("/")
        if source_storage.exists(rel_sub):
            subs.append(rel_sub)
    
    # Also check if there are other subs (like .chs.srt) that srt_translate didn't touch but exist?
    # For now, let's rely on what srt_translate knows + what it generated.
    # Ideally we should list the dir, but that's slow.
    # Let's trust subtitle_remote_paths + existence check.
    
    item = SourceFiles(
        video_path=rel_video,
        subtitle_paths=tuple(sorted(subs)),
        video_size_bytes=None, # We can pass None if we don't have it handy or query it
    )
    
    plan = plan_one(migrate_cfg, llm, item)
    success, result, error = apply_one(migrate_cfg, source_storage, dest_storage, plan)
    if not success:
        return False, f"{result}: {error}"
    return True, None


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
    asr_pool = DaemonExecutor(max_workers=max(1, cfg.whisper.asr_workers), thread_name_prefix="asr")
    
    # Migration setup
    migrate_pool = None
    migrate_llm = None
    source_storage = None
    dest_storage = None
    if migrate_cfg and plan_one:
        migrate_pool = DaemonExecutor(max_workers=1, thread_name_prefix="migrate")
        ollama_migrate = OllamaMcp(migrate_cfg.ollama.base_url, timeout_seconds=migrate_cfg.ollama.timeout_seconds)
        migrate_llm = LlmMcp(ollama_migrate, migrate_cfg.ollama.model, migrate_cfg.ollama.temperature)
        source_storage = build_storage_mcp(migrate_cfg.source)
        dest_storage = build_storage_mcp(migrate_cfg.dest)

    pending: set[Future[object]] = set()
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
        meta[fut] = ("migrate", video_id, remote_path, None)

    def _schedule_translation(video_id: str, remote_path: str, source: SubtitleSource) -> None:
        log.info("translate queued video=%s source=%s", remote_path, source.kind)
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
        fut_asr: Future[object] = asr_pool.submit(_asr_then_upload, cfg, video_id, remote_path, dry_run)
        pending.add(fut_asr)
        meta[fut_asr] = ("asr", video_id, remote_path, None)

    with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
        media = MediaMcp()
        for v in videos:
            video_id = compute_video_id(v)
            paths = subtitle_remote_paths(v.remote_path)
            ai_remote = paths["ai"]
            if not force and ftp.exists(ai_remote):
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
                            failed_count += 1
                            store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="FAILED", payload={"error": str(e), "stage": kind}, updated_at=int(time.time())))
                            continue
                        if kind == "asr" and isinstance(res, SubtitleSource):
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
                                    # failed_count += 1 # Migration failure does not fail the whole run
                                    store.upsert_task(TaskRecord(video_id=vid, video_path=rpath, status="MIGRATION_FAILED", payload={"error": err}, updated_at=int(time.time())))
                            else:
                                log.error("unexpected migrate result type: %s", type(res))
                continue

            local_video = _download_video(cfg, video_id, v.remote_path)
            source = choose_source_subtitle(
                ftp=ftp,
                media=media,
                cache_dir=cfg.paths.local_cache_dir / "work" / video_id,
                video_remote_path=v.remote_path,
                local_video_path=local_video,
                dry_run=dry_run,
            )
            if source is not None:
                _schedule_translation(video_id, v.remote_path, source)
                continue

            if cfg.whisper.enabled:
                _schedule_asr(video_id, v.remote_path)
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
                    failed_count += 1
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
                if kind == "asr":
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
                                payload={"error": "invalid asr result"},
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
                    if migrate_pool:
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
    except KeyboardInterrupt:
        for fut in list(pending):
            fut.cancel()
        translation_pool.shutdown(wait=False, cancel_futures=True)
        asr_pool.shutdown(wait=False, cancel_futures=True)
        if migrate_pool:
            migrate_pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        translation_pool.shutdown(wait=False, cancel_futures=False)
        asr_pool.shutdown(wait=False, cancel_futures=False)
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
