---
name: "srt-translate-mcp-contracts"
description: "定义 srt_translate 的 MCP 工具接口与返回结构约束。实现或联调 MCP server、做错误码/重试策略时调用。"
---

# srt_translate MCP Contracts

## 统一返回结构（建议）

所有 MCP tool 返回统一 envelope，便于 Orchestrator 处理重试与降级：

- `ok: boolean`
- `data: object | null`
- `error: { code: string, message: string, retryable: boolean, detail?: object } | null`

## FTP MCP（示例）

- `list(path) -> { entries: [{ path, type, size, mtime }] }`
- `stat(path) -> { type, size, mtime, etag? }`
- `download(remote_path, local_path) -> { bytes }`
- `atomic_write(remote_path, bytes|local_path) -> { mtime }`

错误码建议：

- `FTP_AUTH_FAILED`（不可重试）
- `FTP_NOT_FOUND`（不可重试）
- `FTP_TEMPORARY`（可重试）

## Media MCP（示例）

- `probe_subtitles(video_path) -> { tracks: [{ id, lang, title, codec, is_text, is_default, is_forced }] }`
- `extract_subtitle_track(video_path, track_id, out_srt_path) -> { out_path }`

## ASR MCP（示例）

- `transcribe_to_srt(video_path, out_srt_path, opts) -> { job_id? , out_path? , progress? }`

要求：

- 支持 job 模式（返回 `job_id`），便于 ASR Agent 轮询/回调
- 错误码区分资源不足（可重试、需 backoff）与输入损坏（不可重试）

## Ollama MCP（示例）

- `generate(model, prompt, opts) -> { text, usage? }`

要求：

- 明确超时（例如翻译批次超时）、返回可重试标记
- 并发限制在 MCP 内部也要生效（防止 Agent 误配并发把模型打挂）

