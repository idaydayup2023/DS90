# subtrans V3

`subtrans` 是面向 Apple Silicon 一体化运行、兼容无容器 NAS 存储的单一 Rust 命令行程序，只保留两项能力：

1. 获取、翻译并校验字幕；
2. 生成可审计的媒体目录迁移计划，并在显式批准后安全执行。

V3 不沿用 V2 的 Python 运行时、运行时自动安装、剧情生成、IMDB 补全或让 LLM 决定媒体类型。V2 仍保留在 `version2` 分支。

## 构建

构建工具链固定为 Rust 1.89.0，依赖版本由 `Cargo.lock` 固定；SQLite 随程序静态打包，不需要 Python。

```sh
cargo build --locked --release
./target/release/subtrans --help
```

复制 `target/release/subtrans` 这一个主程序文件即可交付同 CPU/操作系统目标。`ffmpeg`、Ollama 和可选 ASR/OCR worker 是受控外部组件，不会被主程序静默下载。macOS arm64 构建不能直接在群晖 DSM 上运行；DSM 必须按实际 CPU 架构和 glibc 版本单独构建并验证。

## 配置

```sh
cp config.example.toml subtrans.toml
export SUBTRANS_FTP_PASSWORD='...'
```

配置采用严格 TOML：未知字段、字符串形式的布尔值和错误版本都会被拒绝。密码和 API 密钥只从环境变量读取，不写进配置文件。

先检查配置与外部程序：

```sh
subtrans doctor --config subtrans.toml
```

`ffmpeg`/`ffprobe` 是字幕流提取的外部依赖。纯 Rust 主程序不内嵌 Whisper/Torch 或 PGS OCR；确有需要时，通过配置中的受限 worker 命令调用外部 ASR/OCR，输入、输出和语言都使用显式占位符。详见 `PYTHON_COMPATIBILITY.md`。

生产建议是让 `subtrans`、ffmpeg、Ollama/ASR 都运行在 Apple Silicon，将群晖通过 SMB/NFS 挂载为本地目录；状态库放 Apple 本机磁盘。这样翻译完成状态、分类计划和迁移执行都在同一个事务域内。部署步骤见 `docs/APPLE_SILICON_DEPLOYMENT.md`。

## 字幕翻译

```sh
subtrans subtitles --config subtrans.toml --dry-run
subtrans subtitles --config subtrans.toml
subtrans subtitles --config subtrans.toml --force
```

程序优先选择同目录英文 SRT，其次尝试 ffmpeg 内嵌字幕，再按配置调用 PGS OCR/ASR worker。翻译响应必须是索引完整且无重复的 JSON；发布前会复核字幕数量、时间轴、非空文本和序列化结果。输出为 `<视频名>.ai.srt`，同时写入带源文件哈希和模型参数的 manifest；只有 `--force` 会显式绕过有效缓存。

## 目录迁移

第一步只生成计划，不移动文件：

```sh
subtrans migrate plan --config subtrans.toml --output migration.plan.json
```

检查 JSON 中每个文件的分类证据、目标位置和 `pending` 项：

```sh
subtrans migrate review --config subtrans.toml --plan migration.plan.json
```

待确认项必须在 `[migration.overrides."源相对路径"]` 中明确填写电影或剧集属性，然后重新生成计划；禁止手改计划文件。翻译就绪 manifest 默认是迁移前置条件，也只能由逐文件覆盖中的 `allow_untranslated = true` 显式豁免。只有新计划不含待确认项时，才可用计划哈希批准执行：

```sh
subtrans migrate apply \
  --config subtrans.toml \
  --plan migration.plan.json \
  --approve '<plan_hash>'
```

分类遵循确定性规则。`4K`、`UHD`、`2160p`、`HEVC`、`HDR` 和 `DV` 仅表示画质，绝不决定电影/剧集；缺少完整季集证据的文件进入待确认，不会自动移动。计划绑定配置、存储端点和每个文件的内容 SHA-256；执行还要求精确计划哈希。目标冲突会停止，同一文件系统或同一 FTP 账户优先原子改名，跨存储复制通过 SHA-256 校验后才删除源文件。租约、逐文件进度和事件保存在 SQLite 中，崩溃重跑会从已验证位置继续。

## 当前边界

- 已验证本地文件系统；明文 FTP 只保留可信内网兼容模式且必须显式开启，目标群晖仍需真实服务验收。优先使用 SMB/NFS 挂载。
- ASS/SSA/VTT 可作为迁移伴随文件，但当前翻译输入必须是严格 UTF-8 SRT。
- ASR 与 PGS OCR 的质量取决于所配置的外部 worker；未配置时会安全地标记为无字幕来源。
- V3 使用系统调度器启动一次性命令，不内置第二套守护进程或 Web 界面。

完整设计和安全边界见 `ARCHITECTURE.md`；V2 能力为何保留、重做或删除，见 `docs/V2_SCOPE_DECISIONS.md`。
