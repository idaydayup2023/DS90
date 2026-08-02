# Changelog

本项目遵循“Keep a Changelog”格式记录变更（语义版本以实际发布为准）。

## [Unreleased] - 2026-08-02

### Security

- 可选 ASR/OCR/IMDb 依赖改为带哈希的锁定文件安装，避免运行时获取未固定版本；新增统一的手动安装入口与离线 wheelhouse 说明。
- 默认关闭 Whisper、PGS OCR 和 IMDb 组件的运行时自动安装；运行过程不再修改系统 Python，也不再调用系统包管理器安装 Tesseract。
- 升级 `torch`、`requests`、`urllib3`、`Pillow` 和 `Cinemagoer` 至已验证的新稳定版本，并升级 FFmpeg/Tesseract 外部组件。

### Changed

- 可选工具使用各自的项目缓存虚拟环境，并通过锁文件摘要标记验证环境是否与当前依赖配置一致。
- README 与示例配置明确记录依赖版本、联网/离线安装流程以及需要单独部署的外部组件。

### Fixed

- 修复 `dir_migrate` 加盟系列目录缓存跨目标存储污染，以及年份/年代桶与带前缀系列目录无法正确识别的问题。
- 更新已过期的 LLM/IMDb 测试配置，使测试覆盖与当前配置模型一致。
- 修复目录迁移把 4K/UHD/2160p/HEVC 画质标签当成电影证据的问题；分类现在读取完整目录路径中的季集标记及 `.nfo/.json` 元数据，证据不足时保留原文件并标记 `CLASSIFICATION_PENDING`。
- 拒绝模型在无路径或元数据佐证时虚构的季集号；对于同时具备发布年份和 `WEB-DL/BluRay/Remux` 等电影发布结构的文件，丢弃虚构季集号并按电影处理，避免 `DDP5.1` 等技术数字导致错误追加 `S01E01`。

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

- 稳定性优化：修复 `orchestrator` 调度逻辑中的 JSON 序列化错误和资源竞争死锁；移除全局锁，通过细粒度调度（翻译后串行生成总结）解决并发卡死问题；增加任务等待超时监控与日志。
- 性能优化：降低 `srt_translate` 默认并发数（workers=1）并增加 Ollama 超时时间（300s），避免高负载下请求超时
- `srt_translate` 剧情总结提示词增强：采用“影视剧深度解说”角色，输出 JSON 元数据、Mermaid 关系图/时间轴及视频脚本素材，提升剧情介绍的专业度与结构化
- 合并配置：支持用同一个 `config.json` 同时配置 `srt_translate` 与 `dir_migrate`，并复用顶层 `ftp/ollama/video/paths`
- README 更新：新增 `dir_migrate` 使用说明，并改为统一配置文件
- 目录迁移字幕收集：迁移同目录字幕时包含 `.en.srt/.zh.srt` 等 sidecar 文件
- 迁移冲突策略增强：当目标已存在 `.ai.srt` 且非 overwrite 时，源 `.ai.srt` 会被清理以避免残留
- IMDb 低分归集判定更保守：仅在 IMDb 查询成功时才按“无评分/低分”归集到 `low_imdb`，查询失败/未命中默认 keep
- `srt_translate` 跳过已生成字幕：当远端已存在 `.ai.srt` 时不再重复翻译（FTP exists 对大小写不敏感）
- PGS OCR 策略优化：7 天内失败过（`PGS_OCR_FAILED`）则不再重试 OCR，直接回落 ASR

### Fixed

- `dir_migrate` 分类与命名逻辑修复：
  - 修复 `The.Rip.2026` 等 4K 影片在 LLM 识别为 `tv` 但无 `season/episode` 时被误判定为电视剧的问题。
  - 增强 `_sanitize_fields` 的安全性：若 `kind` 为 `tv` 但未找到剧集信息且文件看起来像电影（如 4K 或有年份），则强制修正为 `movie`。
  - 改进 LLM Prompt，强调高分辨率（2160p/4K）且无剧集标识的文件通常为电影。
  - 统一电影分类逻辑：4K 影片现在也遵循 `year_split` 规则，近几年（>= 2024）的影片将保存在年份目录（如 `2026`），而非年代桶（如 `2020s`）。
  - 严格保持影片/剧集原始名称（如 `St. Denis Medical`, `9-1-1 Nashville`），禁止 LLM 或程序逻辑进行删减或“总结”。
  - 修正衍生剧归集逻辑：支持 `主剧集/衍生剧/季/视频` 的嵌套目录结构（如 `9-1-1/9-1-1.Nashville/S01/...`）。
  - 优化字符处理：仅对空格和系统不安全字符进行 `.` 替换，保留 `-` 和 `_` 等合法字符。
  - 新增 `[...]` 内容自动识别并去除逻辑（针对转发 group）。
  - 修复文件名中 Codec/Source 重复出现的问题（如 `x265.x265`），并将压制组（Group）连接符优化为 `-`。
- `srt_translate` 迁移逻辑修复：
  - **修复字幕遗漏**：移除了 `_collect_related_subtitles_for_migration` 中的全局目录缓存。该缓存会导致在翻译过程中新生成的 `.ai.srt` 或其他后加入的字幕文件无法被迁移任务识别，从而导致视频迁移后字幕留在原处的问题。
  - **增强路径一致性**：确保迁移阶段搜寻字幕时使用的路径逻辑与 `dir_migrate` 核心逻辑完全对齐。
- `dir_migrate` 命名确定性与全流程一致性：
  - **强制确定性解析**：将 LLM 解析的 `temperature` 默认值降至 `0.0`，消除同文件名多次解析结果不一致的随机性。
  - **全流程命名锚定**：在 `srt_translate` 的 `Discovery` 阶段即进行初步规划（Pre-plan），并将规划信息（目标路径、规范化文件名等）持久化至任务数据库。
  - **统一字符处理**：统一了 `planner` 和 `naming` 模块中的 `_dotify` 逻辑，确保加盟店（Franchise）识别与最终文件命名使用完全一致的字符过滤规则。
  - **任务状态溯源**：在迁移阶段复用发现阶段的规划结果，确保翻译、总结到迁移的整个生命周期中，文件身份标识唯一且确定。
- `dir_migrate` 清理逻辑安全性增强：
  - **现场保护**：在 `orchestrator` 中记录所有迁移失败的任务路径，并在随后的 `cleanup_sweep` 扫描中强制跳过这些目录，防止因迁移中断导致的误删。
  - **清理策略收敛**：更新清理智能体提示词，要求在发现大量字幕文件或元数据文件时采取保守策略（keep/unknown），避免清理尚未完成迁移的目录。
  - **路径规范化**：统一清理排除列表的路径规范化逻辑，确保排除匹配的准确性。
  - **回滚日志增强**：在 `executor` 中增加详细的回滚失败日志记录，便于追踪文件丢失的极端情况。
- `srt_translate` 任务链与调度修复：
  - 修复 `orchestrator` 中配置继承问题，确保翻译或总结完成后能正确触发迁移任务。
  - 增加目录列表缓存，减少重复的 FTP `LIST` 请求。
  - 解决因全局锁范围过大导致的 FTP IO 阻塞问题；修复 TaskRecord 序列化异常；增加任务状态的超时监控。
- 其他通用修复：
  - **并发稳定性**：修复了 `StateStore` (SQLite) 在多线程环境下因连接共享导致的错误，并统一了 `dir_migrate` 中硬编码的 30 秒超时限制为 7200 秒。
  - **启动自清理机制**：新增启动时自动清理 `videos` 缓存目录的逻辑，防止因异常中断导致的临时大文件长期占用磁盘空间。
  - **确定性迁移保障**：修复了 `orchestrator` 在迁移阶段未严格遵循数据库中预规划路径的 Bug。现在系统会强制复用 `Discovery` 阶段锁定的 `normalized_basename` 和 `dest_dir`，确保全流程路径一致性。
  - **大文件迁移进度监控**：为 FTP 下载和上传增加了实时进度日志（每 10 秒输出一次百分比），解决超大文件（20GB+）在搬运时看起来像“卡住”的问题。
  - **大文件迁移优化**：
    - 移除了 `dir_migrate` 配置加载中硬编码的 30s 默认超时，确保其能继承 7200s 的长效超时设置。
    - 优化了翻译任务的批处理大小（从 20 降至 10），显著减轻 LLM (Ollama) 的单次请求负载，预防因翻译耗时过长导致的系统性连锁超时。
  - **网络健壮性**：将 FTP 默认超时时间进一步增加到 7200 秒（2 小时），以支持 20GB 以上超大文件在跨分区迁移时的长耗时操作。
  - **冲突处理优化**：优化了迁移任务的冲突处理逻辑。如果目标文件已存在（CONFLICT），系统现在会将其视为已完成（MIGRATED）而非失败。
  - 修复 PGS OCR 兼容性：规避语言码规范化导致的文件找不到问题，并增强容错解码以避免 `UnicodeDecodeError`。
  - 修复：PGS OCR 失败时自动回落到 ASR，避免单片卡住主流程。
  - 修复目录路径拼接不一致导致的 `/Downloads/Downloads` 嵌套与清理误判。
  - 修复 IMDb 查询标题污染：查询前归一化标题（去除年份与 `REMASTERED/UNRATED` 等标签）。

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
