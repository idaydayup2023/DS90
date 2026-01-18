# Changelog

本项目遵循“Keep a Changelog”格式记录变更（语义版本以实际发布为准）。

## [Unreleased]

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

