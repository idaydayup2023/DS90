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
- 新增 PGS OCR 两阶段流水线：先将 PGS 轨抽取为同目录 `*.en.sup`，再异步 OCR 生成 `*.emb.srt` 并进入翻译队列
- 新增迁移后清理智能体：大模型判定残留目录/残留文件是否可安全删除（不确定不清理，`torrent.files` 永不清理）
- 新增 `killcron.sh`：根据锁文件 PID 递归中断 cron 任务进程树
- 新增 IMDb 查询兜底链路：支持从 `.nfo/.txt/.url` 提取 `tt` 号并直查；当 imdbpy 无结果时回退到 IMDb suggestion + 页面 `ld+json` 抽取评分
- 新增 LLM IMDb 知识增强：优先询问 LLM 获取影片评分/ID/票数，LLM 不知晓时才回退到 IMDb 接口查询（解决老片/冷门片查不到评分被误判问题）
- 新增 PGS OCR 失败现场保护：发生异常（如 utf8 解码错误）时保留 `.sup` 与错误日志，便于排查

### Changed

- 合并配置：支持用同一个 `config.json` 同时配置 `srt_translate` 与 `dir_migrate`，并复用顶层 `ftp/ollama/video/paths`
- README 更新：新增 `dir_migrate` 使用说明，并改为统一配置文件
- 目录迁移字幕收集：迁移同目录字幕时包含 `.en.srt/.zh.srt` 等 sidecar 文件
- 迁移冲突策略增强：当目标已存在 `.ai.srt` 且非 overwrite 时，源 `.ai.srt` 会被清理以避免残留
- IMDb 低分归集判定更保守：仅在 IMDb 查询成功时才按“无评分/低分”归集到 `low_imdb`，查询失败/未命中默认 keep
- `srt_translate` 跳过已生成字幕：当远端已存在 `.ai.srt` 时不再重复翻译（FTP exists 对大小写不敏感）
- PGS OCR 策略优化：7 天内失败过（`PGS_OCR_FAILED`）则不再重试 OCR，直接回落 ASR

### Fixed

- `dir_migrate` CLI 异常处理：非 Ctrl-C 错误返回码 2，避免输出长堆栈影响使用
- 修复：存在内置字幕时仍触发 ASR（改为优先下载视频并提取内置字幕/PGS OCR）
- 修复 PGS OCR：规避 pgsrip 对 `eng/en` 语言码规范化导致的文件找不到问题（OCR 前统一临时命名为 `subtitle.<lang>.sup`）
- 修复 PGS OCR：对外部工具输出进行容错解码（避免 `UnicodeDecodeError` 影响 OCR 任务）
- 修复：PGS OCR 失败时自动回落到 ASR，避免单片卡住主流程
- 修复目录路径拼接不一致导致的 `/Downloads/Downloads` 嵌套与清理误判
- 修复 IMDb 查询标题污染：查询前归一化标题（去除年份与 `REMASTERED/UNRATED` 等标签），避免因标题太长导致查询未命中

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
