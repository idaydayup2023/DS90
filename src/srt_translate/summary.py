from __future__ import annotations

import logging
import posixpath
from pathlib import Path

from .config import AppConfig
from .mcp.ftp import FtpMcp
from .mcp.llm_mcp import build_llm_mcp, resolve_llm_model
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
    if not cfg.summary.enabled:
        return

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
        # Use config if available, default to 100k
        max_chars = cfg.summary.max_chars
        if len(srt_content) > max_chars:
            log.warning("Subtitle content too long (%d chars), truncating to %d", len(srt_content), max_chars)
            # Take beginning and end to preserve context
            half = max_chars // 2
            srt_content = srt_content[:half] + "\n...[Content Truncated]...\n" + srt_content[-half:]

        system_prompt = (
            "Role:\n"
            "你是一位拥有 10 年经验的“影视剧深度解说”博主和资深编剧。你擅长从细碎的字幕对话中洞察剧情结构、角色动机和视觉张力。\n\n"
            "Task:\n"
            "我将为你提供一份影视剧的【字幕文本】，请你通过阅读对话内容，将其重构并整理为一份适合在 Markchart 显示、且便于后续制作视频脚本的 Markdown 档案。\n\n"
            "Extraction Logic (提取逻辑):\n"
            "过滤杂讯 ：忽略无意义的语气词、重复的打招呼。\n"
            "提炼冲突 ：从对话中推断出当前场景发生的动作（Action）和矛盾。\n"
            "挖掘深意 ：识别出潜台词、重要的线索点（伏笔）。\n\n"
            "Output Format (严格遵守以下 Markdown 结构):\n"
            "📊 档案元数据 (JSON)\n"
            "```json\n"
            "{\n"
            '  "title": "[剧名]" ,\n'
            '  "episode_index": "[集数/篇章]" ,\n'
            '  "key_conflict": "[本段最主要的矛盾]" ,\n'
            '  "pacing_score": "1-10 (节奏紧凑度)"\n'
            "}\n"
            "```\n\n"
            "🕸️ 人物动态图谱 (Mermaid)\n"
            "```mermaid\n"
            "graph LR\n"
            "    %% 请根据对话内容更新角色关系\n"
            '    A[主角] -- "当前互动关系" --> B[配角]\n'
            "```\n\n"
            "⏳ 本集叙事时间轴 (Mermaid Timeline)\n"
            "```mermaid\n"
            "timeline\n"
            "    title 情节推进\n"
            "    开场 : 场景/动作1 : 冲突1\n"
            "    发展 : 场景/动作2 : 关键台词1\n"
            "    转折/高潮 : 核心爆发点 : 情感转折\n"
            "    结尾 : 悬念留白\n"
            "```\n\n"
            "📝 视频脚本核心素材 (核心部分)\n"
            "| 时间区间/段落 | 核心动作 (画面感描述) | 黄金金句 (原话提取) | 情绪/BGM建议 |\n"
            "|---|---|---|---|\n"
            "| [起止时间] | 描述角色做了什么，而不是说了什么 | 提取最具爆发力或哲理的一句 | 紧张/哀伤/燃 |\n\n"
            "🗝️ 细节与伏笔捕捉\n"
            "- 关键信息 : 对话中提到的重要道具、人名或往事。\n"
            "- 逻辑关联 : 本段剧情如何影响后续（或解释了前文）。\n\n"
            "IMPORTANT: The output MUST be in Simplified Chinese (简体中文). Do not output English."
        )

        prompt = (
            "Input Data (字幕文本):\n"
            f"{srt_content}\n\n"
            "REMINDER: The output MUST be in Simplified Chinese."
        )
        
        llm = build_llm_mcp(cfg.llm.provider, cfg.llm.base_url, timeout_seconds=cfg.llm.timeout_seconds * 2)
        model = resolve_llm_model(llm, cfg.llm.model)
        
        try:
            resp = llm.generate(model, prompt, temperature=0.5, system=system_prompt)
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
