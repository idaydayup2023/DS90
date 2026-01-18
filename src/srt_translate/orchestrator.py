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
    local_ai = _local_ai_path_for_video(cfg.paths.local_cache_dir, video_id, video_remote_path)
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


def run_once(cfg: AppConfig, store: StateStore, force: bool, dry_run: bool) -> RunSummary:
    setup_logging()
    started = time.time()
    exts = normalize_extensions(cfg.video.extensions)
    log.info("run_once start force=%s dry_run=%s", force, dry_run)
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
    pending: set[Future[object]] = set()
    meta: dict[Future[object], tuple[str, str, str, str | None]] = {}
    skipped = 0
    done_count = 0
    failed_count = 0

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
    except KeyboardInterrupt:
        for fut in list(pending):
            fut.cancel()
        translation_pool.shutdown(wait=False, cancel_futures=True)
        asr_pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        translation_pool.shutdown(wait=False, cancel_futures=False)
        asr_pool.shutdown(wait=False, cancel_futures=False)
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
