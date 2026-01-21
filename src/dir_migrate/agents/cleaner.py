from __future__ import annotations

import json
import logging
import posixpath
from dataclasses import dataclass
from typing import Any

from srt_translate.mcp.ollama import OllamaMcp

from ..config import AppConfig
from ..domain import MovePlan
from ..mcp.storage import StorageMcp


log = logging.getLogger("dir_migrate.agents.cleaner")


@dataclass(frozen=True)
class CleanupDecision:
    decision: str
    confidence: float | None
    reason: str | None


def _extract_json(text: str) -> dict[str, Any]:
    t = text.strip()
    if not t:
        raise ValueError("empty model output")
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    a = t.find("{")
    b = t.rfind("}")
    if a >= 0 and b > a:
        obj = json.loads(t[a : b + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("model output is not a JSON object")


def _prompt(dir_path: str, moved_files: list[str], residual_dirs: list[str], residual_files: list[tuple[str, int | None]]) -> str:
    moved = "\n".join(f"- {x}" for x in moved_files[:20])
    if len(moved_files) > 20:
        moved += f"\n- ... ({len(moved_files) - 20} more)"
    dirs = "\n".join(f"- {x}" for x in residual_dirs[:40])
    if len(residual_dirs) > 40:
        dirs += f"\n- ... ({len(residual_dirs) - 40} more)"
    files = "\n".join(f"- {p} ({sz if sz is not None else 'unknown'} bytes)" for p, sz in residual_files[:40])
    if len(residual_files) > 40:
        files += f"\n- ... ({len(residual_files) - 40} more)"
    return (
        "You are a cautious cleanup agent for a media migration tool.\n"
        "We migrated a movie/TV file out of a source directory. The directory may have residual files and residual subfolders.\n"
        "Decide whether it is SAFE to delete ALL residual files and ALL residual subfolders in this directory, and then delete the directory itself.\n"
        "Rules:\n"
        "1) Only output JSON. No explanations outside JSON.\n"
        "2) If you are not very sure, choose \"unknown\".\n"
        "3) Choose \"delete\" ONLY when the directory is clearly a per-title download folder or a season folder, and residual items are typical extras.\n"
        "4) Choose \"keep\" for generic folders (Downloads, Movies, TV, torrents, incomplete, temp) or anything that may hold other downloads.\n"
        "5) Never delete directories named torrent.files or low_imdb.\n"
        "6) When in doubt: unknown.\n\n"
        f"DIRECTORY: {dir_path}\n"
        "MOVED FILES (examples):\n"
        f"{moved or '- (none)'}\n\n"
        "RESIDUAL DIRS:\n"
        f"{dirs or '- (none)'}\n\n"
        "RESIDUAL FILES:\n"
        f"{files or '- (none)'}\n\n"
        "OUTPUT JSON SCHEMA:\n"
        "{\n"
        "  \"decision\": \"delete|keep|unknown\",\n"
        "  \"confidence\": number|null,\n"
        "  \"reason\": string|null\n"
        "}\n"
    )


def _llm_decide_cleanup(cfg: AppConfig, moved_files: list[str], dir_path: str, residual_dirs: list[str], residual_files: list[tuple[str, int | None]]) -> CleanupDecision:
    ollama = OllamaMcp(cfg.ollama.base_url, timeout_seconds=cfg.ollama.timeout_seconds)
    text = ollama.generate(model=cfg.ollama.model, prompt=_prompt(dir_path, moved_files, residual_dirs, residual_files), temperature=0.0).text
    obj = _extract_json(text)
    decision = str(obj.get("decision") or "unknown").strip().lower()
    confidence = obj.get("confidence")
    try:
        confidence_f = float(confidence) if confidence is not None else None
    except Exception:
        confidence_f = None
    reason = obj.get("reason")
    reason_s = str(reason).strip() if reason is not None else None
    if decision not in ("delete", "keep", "unknown"):
        decision = "unknown"
    return CleanupDecision(decision=decision, confidence=confidence_f, reason=reason_s)


def cleanup_source_residual_dirs(cfg: AppConfig, source_storage: StorageMcp, plan: MovePlan) -> None:
    if not cfg.cleanup.enabled:
        return
    if cfg.execution.dry_run or not cfg.execution.apply:
        return
    start_dir = posixpath.dirname(plan.source.video_path.rstrip("/")) or "/"
    if start_dir == "/":
        return

    protected = {p.lower() for p in cfg.cleanup.protected_dirnames}
    cur = start_dir
    while cur and cur != "/":
        base = posixpath.basename(cur.rstrip("/")).lower()
        if base in protected:
            return
        entries = source_storage.list_dir(cur)
        dirs = [p for p, t, _sz in entries if t == "dir"]
        files = [(p, sz) for p, t, sz in entries if t == "file"]

        if cfg.cleanup.delete_residual_files:
            video_exts = {e.lower() for e in cfg.video.extensions}
            moved_names = {posixpath.basename(plan.source.video_path).lower(), *(posixpath.basename(s).lower() for s in plan.source.subtitle_paths)}
            for p, _sz in files:
                name = posixpath.basename(p).lower()
                _stem, ext = posixpath.splitext(name)
                if ext in video_exts and name not in moved_names and "sample" not in name:
                    return

            moved_files = [plan.source.video_path, *plan.source.subtitle_paths]
            decision = _llm_decide_cleanup(cfg, moved_files, cur, [posixpath.basename(d) for d in dirs], [(posixpath.basename(p), sz) for p, sz in files])
            if decision.decision != "delete":
                log.info("cleanup keep dir=%s decision=%s confidence=%s reason=%s", cur, decision.decision, decision.confidence, decision.reason)
                return
            if decision.confidence is not None and decision.confidence < cfg.cleanup.min_confidence:
                log.info("cleanup confidence too low dir=%s confidence=%s reason=%s", cur, decision.confidence, decision.reason)
                return

            for p, _sz in files:
                source_storage.delete_file(p)
            for d in dirs:
                d_base = posixpath.basename(d.rstrip("/")).lower()
                if d_base in protected:
                    continue
                source_storage.delete_dir_tree(d)

        removed = source_storage.rmdir_if_empty(cur)
        if not removed:
            return
        log.info("cleanup removed dir=%s", cur)
        parent = posixpath.dirname(cur.rstrip("/")) or "/"
        if parent == cur:
            return
        cur = parent


def cleanup_sweep(cfg: AppConfig, source_storage: StorageMcp, root: str = "", max_dirs: int = 200) -> int:
    if not cfg.cleanup.enabled:
        return 0
    if cfg.execution.dry_run or not cfg.execution.apply:
        return 0
    protected = {p.lower() for p in cfg.cleanup.protected_dirnames}
    try:
        entries = source_storage.list_dir(root)
    except Exception:
        return 0
    dirs = [p for p, t, _sz in entries if t == "dir"]
    removed = 0
    for d in dirs[: max(0, int(max_dirs))]:
        base = posixpath.basename(d.rstrip("/")).lower()
        if base in protected:
            continue
        try:
            children = source_storage.list_dir(d)
        except Exception:
            continue
        residual_dirs = [posixpath.basename(p) for p, t, _sz in children if t == "dir"]
        residual_files = [(posixpath.basename(p), sz) for p, t, sz in children if t == "file"]

        video_exts = {e.lower() for e in cfg.video.extensions}
        has_real_video = False
        for name, _sz in residual_files:
            lower = name.lower()
            _stem, ext = posixpath.splitext(lower)
            if ext in video_exts and "sample" not in lower:
                has_real_video = True
                break
        if has_real_video:
            continue

        decision = _llm_decide_cleanup(cfg, [], d, residual_dirs, residual_files)
        if decision.decision != "delete":
            continue
        if decision.confidence is not None and decision.confidence < cfg.cleanup.min_confidence:
            continue
        source_storage.delete_dir_tree(d)
        removed += 1
    return removed
