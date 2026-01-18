---
name: "srt-translate-architecture"
description: "定义 srt_translate 的 Agent/队列/MCP 分层架构与并发策略。需要做架构设计、拆分模块或实现编排器时调用。"
---

# srt_translate Architecture

## 目标

把系统拆为“可并行、可重试、可观测”的流水线，避免 Whisper ASR 阻塞主线翻译，并让外部依赖（FTP/ffmpeg/whisper/ollama/存储）通过 MCP 抽象，业务只做决策与编排。

## 推荐分层

- Orchestrator（编排/状态机/调度）
- Agents（Scanner / Subtitle Acquisition / ASR / Translation / Writer / Observer）
- Skills（提示词与规则资产：可版本化、可回滚、可 A/B）
- MCP 工具层（所有外部副作用与依赖：FTP/媒体/ASR/Ollama/存储）

## 并发与队列

- 将队列拆为至少两条：
  - `translation_queue`：字幕提取成功后即可进入，优先保证吞吐
  - `asr_queue`：仅在无字幕时进入，后台 worker pool 并行跑
- 关键并发旋钮（必须可配置）：
  - `translation_workers`（Ollama 并发）
  - `asr_workers`（Whisper 并发）
  - `ftp_concurrency`（FTP list/stat/download/upload 并发）
- 不同队列之间要隔离资源：ASR 不得把 CPU/GPU/IO 抢到导致翻译变慢

## 状态机（建议）

- `DISCOVERED` → `SUBTITLE_SELECTING` → `TRANSLATING` → `WRITING` → `DONE`
- ASR 分支：
  - `SUBTITLE_SELECTING` → `ASR_QUEUED` → `ASR_RUNNING` → `ASR_DONE` → `TRANSLATING`
- 失败分级：
  - `RETRYABLE_FAILED`（可重试，带 backoff）
  - `FATAL_FAILED`（不可恢复，需人工介入）

## MCP 工具职责（仅示例）

- FTP MCP：`list`, `stat`, `download`, `upload`, `atomic_write`
- Media MCP：`probe_subtitles`, `extract_subtitle_track`, `extract_audio`
- ASR MCP：`transcribe_to_srt`（支持 job/进度）
- Ollama MCP：`generate`（超时/重试/并发限制/模型切换）
- Store MCP：`get_task`, `put_task`, `list_pending`, `mark_done`

## 落地检查清单

- Orchestrator 不直接调用 ffmpeg/whisper/ollama，只调用 MCP 工具
- Translation Agent 只引用 Skill 里的提示词模板，不硬编码长 prompt
- 所有产物写回使用 Writer Agent（可实现原子写策略：临时文件 → rename）

