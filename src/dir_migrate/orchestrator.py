from __future__ import annotations

import json
import logging
import posixpath
from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import asdict

from srt_translate.daemon_executor import DaemonExecutor
from srt_translate.mcp.llm_mcp import build_llm_mcp, resolve_llm_model

from .agents.executor import apply_one
from .agents.cleaner import cleanup_sweep
from .agents.planner import plan_one
from .agents.scanner import scan_once
from .config import AppConfig
from .domain import MovePlan, RunSummary, SourceFiles
from .mcp.llm import LlmMcp
from .mcp.storage import StorageMcp, build_storage_mcp


log = logging.getLogger("dir_migrate.orchestrator")


def _validate_storage(cfg: AppConfig) -> None:
    if cfg.source.kind != cfg.dest.kind:
        raise ValueError("cross-kind migrate is not supported")
    if cfg.source.kind == "ftp":
        if cfg.source.ftp is None or cfg.dest.ftp is None:
            raise ValueError("missing ftp config")
        if (cfg.source.ftp.host, cfg.source.ftp.port, cfg.source.ftp.username) != (cfg.dest.ftp.host, cfg.dest.ftp.port, cfg.dest.ftp.username):
            raise ValueError("cross-host or cross-user FTP migrate is not supported")


def run_once(cfg: AppConfig) -> RunSummary:
    if cfg.execution.apply and cfg.execution.dry_run:
        raise ValueError("invalid execution: both apply and dry_run are true")
    _validate_storage(cfg)

    source_storage: StorageMcp = build_storage_mcp(cfg.source)
    dest_storage: StorageMcp = build_storage_mcp(cfg.dest)

    scan = scan_once(cfg, source_storage)
    videos = scan.videos
    log.info("scan videos=%d", len(videos))

    llm_mcp = build_llm_mcp(cfg.llm.provider, cfg.llm.base_url, timeout_seconds=cfg.llm.timeout_seconds)
    model = resolve_llm_model(llm_mcp, cfg.llm.model)
    llm = LlmMcp(llm=llm_mcp, model=model, temperature=cfg.llm.temperature, max_retries=2)

    pool = DaemonExecutor(max_workers=max(1, cfg.execution.workers), thread_name_prefix="plan")
    pending: set[Future[MovePlan]] = set()
    meta: dict[Future[MovePlan], SourceFiles] = {}
    for v in videos:
        fut: Future[MovePlan] = pool.submit(plan_one, cfg, llm, v, dest_storage, source_storage)
        pending.add(fut)
        meta[fut] = v

    plans: list[MovePlan] = []
    failed = 0
    try:
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    plan = fut.result()
                except Exception as e:
                    failed += 1
                    v = meta.get(fut)
                    log.error("plan failed video=%s error=%s", getattr(v, "video_path", None), e)
                    continue
                plans.append(plan)
    except KeyboardInterrupt:
        for fut in list(pending):
            fut.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=False, cancel_futures=False)

    planned = len(plans)
    moved = 0
    skipped = 0
    conflicts = 0
    apply_failed = 0
    failed_source_dirs: set[str] = set()

    for plan in plans:
        if getattr(plan, "skip_reason", None):
            skipped += 1
            if cfg.execution.dry_run or not cfg.execution.apply:
                print(json.dumps(asdict(plan), ensure_ascii=False))
            continue
        if cfg.execution.dry_run or not cfg.execution.apply:
            print(json.dumps(asdict(plan), ensure_ascii=False))
            continue
        ok, status, err = apply_one(cfg, source_storage, dest_storage, plan)
        if ok:
            moved += 1
            continue
        
        # Record failed source directory to prevent aggressive cleanup
        # We normalize by stripping leading/trailing slashes
        sdir = posixpath.dirname(plan.source.video_path.rstrip("/"))
        sdir = sdir.strip("/")
        if sdir:
            failed_source_dirs.add(sdir)

        if status == "CONFLICT":
            conflicts += 1
            continue
        apply_failed += 1
        log.error("apply failed video=%s error=%s", plan.source.video_path, err)

    if cfg.cleanup.enabled and cfg.execution.apply and (not cfg.execution.dry_run):
        log.info("cleanup sweep start root=/Downloads max_dirs=%d", 200)
        try:
            removed = cleanup_sweep(cfg, source_storage, root="", max_dirs=200, exclude_dirs=failed_source_dirs)
            log.info("cleanup sweep done removed=%d", removed)
        except Exception as e:
            log.warning("cleanup sweep failed error=%s", e)
    else:
        log.info(
            "cleanup sweep skipped enabled=%s apply=%s dry_run=%s",
            cfg.cleanup.enabled,
            cfg.execution.apply,
            cfg.execution.dry_run,
        )

    return RunSummary(
        videos=len(videos),
        planned=planned,
        moved=moved,
        skipped=skipped,
        conflicts=conflicts,
        failed=failed + apply_failed,
    )
