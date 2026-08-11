# V3 architecture

## Scope

V3 从干净模块边界重建，只包含字幕翻译和目录迁移。主程序及核心逻辑均为 Rust，不直接复制 V2 Python 模块。

```text
subtrans CLI
├── config       strict TOML + environment/OS-keystore secrets
├── storage      local / FTP, normalized relative paths, atomic publication
├── subtitles    acquire → parse → translate → QC → publish
├── migration    classify → immutable plan → approve → verify → commit
├── artifact     字幕就绪提交标记与完整缓存身份
└── state        SQLite 租约、逐文件进度与 append-only 事件
```

## Safety invariants

- 所有存储路径必须是规范化相对路径；拒绝绝对路径、`..`、反斜杠、NUL 和本地符号链接逃逸。
- 媒体分类只使用可解释规则。完整季集标记可判剧集；年份与正式发行源标签可判电影；证据不足进入 `pending`。
- 画质/编码标签与媒体类型正交，永不合成季集编号。
- 迁移计划包含规则版本、配置/存储绑定、分类证据、建议目标和伴随文件，并由规范 JSON 的 SHA-256 固定。可执行项必须包含源内容 SHA-256；本来就禁止执行的待确认项只记录大小、修改时间和身份摘要，解决阻断后必须生成新的完整哈希计划，避免无效读取几十 GB 媒体。
- 执行必须提交精确的计划哈希；源身份变化、计划/配置不匹配、待确认项或目标内容冲突都会停止。
- 跨后端移动先流式复制并计算 SHA-256，再原子发布并复核目标；FTP 源通过独立下载/上传会话直接流向目标临时文件，不落本机完整副本。复制模式在全部目标验证后才按“伴随文件在前、主视频在后”删除源文件。同一 FTP 账户优先服务器端改名；群晖跨共享目录拒绝改名时安全回退到流式复制，逐文件状态支持中断后前向恢复。
- 字幕迁移默认要求有效的 `ready` manifest；manifest 绑定视频身份、字幕源哈希、完整翻译参数和最终输出哈希。
- 字幕翻译严格保持 cue 索引和时间轴；模型返回缺项、重复项、额外项、空文本、源文回显、低目标文字比例或非 JSON 均失败，不发布部分结果。
- 密钥不序列化到配置、计划、manifest 或状态库。

## External boundaries

Rust 原生实现目录扫描、本地/FTP I/O、分类、计划/执行、SRT、HTTP LLM 客户端、缓存、校验和状态机。以下能力保留为外部可选边界：

- `ffmpeg`/`ffprobe`：媒体容器与字幕流处理；
- 外置英文 SRT 必须以内置英文字幕为信任锚进行时间轴与文本交叉验证；无内置锚时不得自动采用，选择证据随翻译清单持久化；
- ASR worker：例如 Apple Silicon 上独立安装的 Whisper 实现；
- PGS OCR worker：图像字幕识别；
- Ollama 或 OpenAI-compatible 服务：只翻译字幕，不参与迁移分类。翻译采用带只读邻句的顺序批处理，失败批次按配置递归缩小；完成后对全片做一次严格 JSON 一致性校对。任何批次或校对失败都不发布 `ready` 产物。

worker 只能通过显式命令和 `{input}`、`{output}`、`{language}`、`{stream}` 参数模板调用，不经过 shell；启用时必须声明版本。进程有超时和输出大小边界，生成 SRT 仍须通过同一严格校验。V3 不自动安装 Python 包，也不创建隐式虚拟环境。

## Failure and restart model

SQLite 使用 WAL 与 `synchronous=FULL`，每次状态变更在同一事务内更新 job 快照并追加 event。任务带进程所有者和过期租约，避免两个执行端同时处理。相同计划/源文件产生稳定 job id，每个文件动作另有持久化状态；已 `COMMITTED` 的任务重跑会复核目标后跳过。进程在发布后、记账前崩溃时，重跑可依据源/目标哈希前向恢复；内容不一致立即停止。

## Deployment targets

Apple Silicon 是当前一体化生产基线：群晖媒体通过受限 FTP 账户访问，字幕、状态、规则分类、计划批准和迁移均由同一 Apple 主机执行，ASR/LLM 也可使用本机硬件。状态库必须放本机磁盘而非 FTP/NAS。

暂不拆成 NAS 与 Apple 两个执行端，因为迁移依赖字幕 `ready` 状态，拆分会新增跨端队列、锁、凭据、一致性和恢复面。只有 NAS 架构/glibc 已实机验收、共享锁和断网恢复测试通过、且测得显著吞吐或可用性收益时，才允许启用 NAS 原生执行；macOS 二进制不能复制到 DSM 使用。
