from __future__ import annotations

import logging
import posixpath
from pathlib import Path

from .config import AppConfig
from .mcp.ftp import FtpMcp
from .mcp.ollama import OllamaMcp, resolve_ollama_model
from .domain import split_basename
from .subtitle_acquisition import SubtitleSource

log = logging.getLogger("srt_translate.summary")


def _local_summary_path_for_video(cache_dir: Path, video_id: str, video_remote_path: str) -> Path:
    # Use .md extension for summary
    name = posixpath.splitext(posixpath.basename(video_remote_path))[0] + ".md"
    return cache_dir / "work" / video_id / "out" / name


def generate_summary(
    cfg: AppConfig,
    video_id: str,
    video_remote_path: str,
    source: SubtitleSource,
    force: bool,
    dry_run: bool,
) -> None:
    directory, stem, _ = split_basename(video_remote_path)
    summary_remote = posixpath.join(directory, f"{stem}.md")

    with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
        if not force and ftp.exists(summary_remote):
            return

    local_summary = _local_summary_path_for_video(cfg.paths.local_cache_dir, video_id, video_remote_path)
    
    if local_summary.exists() and local_summary.stat().st_size > 0:
         log.info("using cached summary result: %s", local_summary)
         summary_content = local_summary.read_text(encoding="utf-8")
    else:
        if not source.local_path.exists():
             raise FileNotFoundError(f"Subtitle source file not found: {source.local_path}")
        
        srt_content = source.local_path.read_text(encoding="utf-8", errors="replace")
        
        # Truncate content if excessively long to avoid blowing up context window
        # User has configured 256k context.
        # We limit to 200k chars to leave room for prompt and output.
        MAX_CHARS = 200000
        if len(srt_content) > MAX_CHARS:
            log.warning("Subtitle content too long (%d chars), truncating to %d", len(srt_content), MAX_CHARS)
            srt_content = srt_content[:MAX_CHARS] + "\n...[Content Truncated]..."

        system_prompt = (
            "You are a professional movie critic and editor. "
            "Your task is to read the provided subtitle content and generate a detailed movie plot summary in Markdown format. "
            "IMPORTANT: The output MUST be in Simplified Chinese (简体中文). Do not output English."
        )

        prompt = (
            "Based on the following subtitle content, generate a detailed movie plot summary in Markdown format.\n"
            "Requirements:\n"
            "1. Language: Chinese (Simplified).\n"
            "2. Structure: Introduction, Plot Outline (with chapters), Key Characters, Conclusion.\n"
            "3. Output ONLY the markdown content.\n\n"
            "Subtitle Content:\n"
            f"{srt_content}\n\n"
            "REMINDER: The output MUST be in Simplified Chinese."
        )
        
        ollama = OllamaMcp(cfg.ollama.base_url, timeout_seconds=cfg.ollama.timeout_seconds * 2)
        model = resolve_ollama_model(ollama, cfg.ollama.model)
        
        try:
            resp = ollama.generate(model, prompt, temperature=0.5, system=system_prompt)
            log.info("Summary generated, model=%s len=%d", resp.model, len(resp.text))
            summary_content = resp.text
        except Exception as e:
            log.error("Failed to generate summary: %s", e)
            raise

        local_summary.parent.mkdir(parents=True, exist_ok=True)
        local_summary.write_text(summary_content, encoding="utf-8")

    if not dry_run:
        with FtpMcp(cfg.ftp.host, cfg.ftp.port, cfg.ftp.username, cfg.ftp.password) as ftp:
             ftp.atomic_write_from_file(summary_remote, local_summary)
