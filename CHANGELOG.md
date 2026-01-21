# Changelog

本项目遵循“Keep a Changelog”格式记录变更（语义版本以实际发布为准）。

## [Unreleased]

### Added

- 新增 `dir_migrate` 目录迁移工具：LLM 识别结构化字段，规范化文件名（`.` 分割），按电影/剧集与 1080p/2160p 规则规划目标目录并迁移（dry-run/apply、冲突策略）
- 新增 `dir_migrate` 的 Agent/Orchestrator/MCP 分层实现（Scanner/Planner/Executor + MCP: storage/llm），架构风格与 `srt_translate` 对齐
- 新增 `dir_migrate` 对话记录文档（独立沉淀）
- 新增 Whisper 自动安装与命令解析：遇到 PEP 668 时自动创建 venv 安装（避免系统环境受限）
- 新增 ASR 质量校验与重试：对明显重复/水印式输出判定失败并重试（避免把坏字幕送去翻译）
- 新增 PGS OCR（方案 A）：检测内置 PGS 位图字幕，抽取 `.sup` 并通过 OCR 生成 `*.emb.srt`（自动安装 `pgsrip`/`tesseract`）
- 新增迁移后清理智能体：大模型判定残留目录/残留文件是否可安全删除（不确定不清理，`torrent.files` 永不清理）
- 新增 `killcron.sh`：根据锁文件 PID 递归中断 cron 任务进程树

### Changed

- 合并配置：支持用同一个 `config.json` 同时配置 `srt_translate` 与 `dir_migrate`，并复用顶层 `ftp/ollama/video/paths`
- README 更新：新增 `dir_migrate` 使用说明，并改为统一配置文件
- 目录迁移字幕收集：迁移同目录字幕时包含 `.en.srt/.zh.srt` 等 sidecar 文件
- 迁移冲突策略增强：当目标已存在 `.ai.srt` 且非 overwrite 时，源 `.ai.srt` 会被清理以避免残留

### Fixed

- `dir_migrate` CLI 异常处理：非 Ctrl-C 错误返回码 2，避免输出长堆栈影响使用
- 修复：存在内置字幕时仍触发 ASR（改为优先下载视频并提取内置字幕/PGS OCR）

## [0.1.0] - 2026-01-18

### Added

- FTP 扫描与视频过滤（根目录递归、扩展名白名单、最小体积阈值）
- 源字幕获取链路：同名 `*.emb.srt` / 外置字幕候选择优 / 内置字幕提取 / Whisper ASR 兜底
- 字幕质量评分（用于多候选择优）
- Ollama 翻译生成 `*.ai.srt`：中文在上、英文在下；批量翻译对齐校验，失败回退逐条翻译
- 运行状态落库（SQLite）
- Trae Skills（架构/提示词/MCP 契约）与 PRD 文档沉淀
- 单元测试与本地翻译冒烟脚本

### Changed

- Ollama 模型名支持从 `/api/tags` 自动解析与纠正（避免 “model not found”）
- 翻译阶段增加进度日志（便于观测长任务）

### Fixed

- Ctrl-C 中断时线程退出体验：捕获 `KeyboardInterrupt` 并返回码 130，避免线程 shutdown 堆栈影响使用
