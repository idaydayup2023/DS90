# subtrans V3

版本变更记录见 [`CHANGELOG.md`](CHANGELOG.md)。每次正式 Release 都必须先把
`[Unreleased]` 内容整理到与 Cargo 版本和 Git 标签一致的带日期章节；发布流程会
校验该章节，并直接使用它生成 GitHub Release 说明。

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
# FTP 账号必须来自环境变量；密码可隐藏输入，生产部署建议存入钥匙串。
export SUBTRANS_FTP_USERNAME='<FTP账号>'
read -s "SUBTRANS_FTP_PASSWORD?FTP password: "; export SUBTRANS_FTP_PASSWORD; echo
```

配置采用严格 TOML：未知字段、字符串形式的布尔值和错误版本都会被拒绝。FTP 账号由 `SUBTRANS_FTP_USERNAME` 提供，不写入配置或计划；计划只保存账号 SHA-256 以绑定执行身份。上面的隐藏输入不会回显密码，也不会把密码写进 shell 历史。macOS 生产运行可把 FTP 密码存为与服务器、端口、运行时账号匹配的系统“互联网密码”；密码环境变量优先于钥匙串。

```sh
# -w 必须放在最后；security 会安全提示输入，不把密码放进命令行。
security add-internet-password -U -a '<FTP账号>' -s '<FTP服务器>' -P 10021 -r 'ftp ' -w
```

先检查配置与外部程序：

```sh
subtrans doctor --config subtrans.toml
```

生产配置使用 FTP：`source.root = "/Downloads"`，`destination.root = "/"`，四类目标根仍由迁移布局配置为 `MOVIE`、`TV`、`X-Movie`、`X-TV`。服务器和端口写在本机 `subtrans.toml`，真实账号由配置指定的环境变量在执行时读取。密码只从 `SUBTRANS_FTP_PASSWORD` 或 macOS 钥匙串读取。真实账号、密码都不会进入仓库示例，密码也绝不进入 TOML、计划、日志或 Git。

`subtrans doctor` 会检查 FTP 登录、两个根目录以及四个目标库，并在每个目录短暂创建后删除一个唯一的空探针，以确认实际具备写入和删除权限。明文 FTP 只允许在隔离且可信的内网中显式开启。

`ffmpeg`/`ffprobe` 是字幕流提取的外部依赖。纯 Rust 主程序不内嵌 Whisper/Torch 或 PGS OCR；确有需要时，通过配置中的受限 worker 命令调用外部 ASR/OCR，输入、输出和语言都使用显式占位符。详见 `PYTHON_COMPATIBILITY.md`。

外置英文 SRT 会先通过 UTF-8、严格 SRT 和英语内容质量门。有内置英文字幕时，程序用双向时间轴覆盖和文本相似度交叉验证；两者不一致或质量接近时选内置字幕，只有达到匹配阈值且外置质量明显更高时才选外置字幕。没有内置英文字幕时直接采用合格的外置英文 SRT；内外都没有时必须调用已配置的 ASR worker，未配置或执行失败会给出安装、配置和诊断指引。选择结果和比对指标写入 `.ai.srt.subtrans.json`。

生产建议是让 `subtrans`、ffmpeg、Ollama/ASR 都运行在 Apple Silicon，群晖只通过 FTP 提供媒体；状态库放 Apple 本机磁盘。这样翻译完成状态、分类计划和迁移执行仍在同一个事务域内，同时不再依赖 macOS 网络卷挂载。部署步骤见 `docs/APPLE_SILICON_DEPLOYMENT.md`。

## 字幕翻译

```sh
subtrans subtitles --config subtrans.toml --dry-run
subtrans subtitles --config subtrans.toml
subtrans subtitles --config subtrans.toml --force
# 临时翻译本机目录；不读取 FTP 源，也不会生成或执行迁移计划
subtrans subtitles --config subtrans.toml --local-dir "/本机/待翻译目录"
```

程序先收集同目录英文 SRT 和内置字幕：两者都有时交叉验证，仅有合格外置 SRT 时直接采用；都没有时调用 ASR。默认使用 `translategemma:12b` 顺序翻译：每批最多 32 条、8000 字符，并只携带前 6 条只读上下文，而不是并发争抢同一个 Ollama 模型。每个字幕编号都是不可拆分的英文—中文绑定；上下文只能帮助理解，不能把相邻句内容移入当前编号。网络或服务错误按配置重试；确定性的 JSON 结构错误会立即拆小异常批次，极端情况下带前导上下文逐条补译。若模型只漏掉重复短句等少量合法索引，程序保留本批已验证译文，仅补译缺失项；模型误回的已知只读邻句会被丢弃，提示范围外索引仍会拒绝。全部初译完成后由 `consistency_model` 做整片术语一致性校对，再由 `alignment_model` 分批核对同编号原文和译文。审校属于建议层：语境不足、服务失败或单条返回无法解析会记录明确警告并保留当前译文，不阻断上传；同一编号连续三次仍被校对模型否决时，该编号输出为单行英文原文，不再翻译，其余字幕照常发布。

翻译和校对响应都必须是索引合法、无重复且无多余字段的 JSON；仅对已实测的无语义包装差异（校对裸数组、空对象、单层 JSON 围栏）和 TranslateGemma 的精确键名笔误 `"text:"` 做安全规范化，数组内项目仍只允许 `index` 与 `text`，其他未知字段和范围外编号一律拒绝。初译的结构或质量错误仍会阻止该视频发布；审校错误只会降级为可观察警告或逐条英文回退。发布前会复核字幕数量、时间轴、非空文本、目标文字比例和序列化结果。输出为 `<视频名>.ai.srt`，同时写入带源文件哈希、提示协议和全部翻译参数的 manifest；批次、上下文、模型或校对配置改变都会使旧缓存失效，只有 `--force` 会显式绕过仍然有效的缓存。

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

分类遵循确定性规则。`4K`、`UHD`、`2160p`、`HEVC`、`HDR` 和 `DV` 仅表示画质，绝不决定电影/剧集；缺少完整季集证据的文件进入待确认，不会自动移动。计划绑定配置、存储端点和每个文件的内容 SHA-256；执行还要求精确计划哈希。目标冲突会停止，同一 FTP 账户先尝试服务器端原子改名；跨共享目录不能改名时，通过两个 FTP 会话流式复制到目标临时名，复核目标 SHA-256 后才删除源文件。租约、逐文件进度和事件保存在 SQLite 中，崩溃重跑会从已验证位置继续。

四类目标布局完全由 `[migration.layouts.movie_4k]`、`movie_other`、`tv_4k`、`tv_other` 配置，不需要修改代码。目录/文件模板可使用 `title`、`title_dot`、`source_file`、`source_file_dot`、`source_stem`、`source_stem_dot`、`release_dir`；其中 `*_dot` 会把连续空白统一为单个 `.`。当前四类文件名都配置为 `{source_file_dot}`，迁移的伴随字幕/清单文件也执行相同规范化。电影还可使用 `year`、`decade`、`year_bucket`，电视剧还可使用 `season`、`season_padded`、`episode`、`episode_padded`、`alpha_group`。`recent_year_from` 控制电影使用精确年份还是年代目录，`alphabet_groups` 控制 4K 剧集字母分组，`title_routes` 可为特殊剧名改目标显示名或分组但不能改变媒体类型。`incomplete_marker_extensions` 是字幕与迁移共用的安全规则：存在精确匹配视频名的 `.aria2/.part` 等未完成标记时，两条流程都会跳过该视频。模板是受限的：未知字段、绝对路径、反斜杠、`..` 和不完整的 A-Z 映射会在启动时被拒绝。完整示例见 `config.example.toml`。

## 当前边界

- FTP 模式下，为提取内置字幕、PGS OCR 或 ASR，ffmpeg 需要一个本地文件，因此单个视频会下载到系统临时目录并在处理结束后自动删除；本机可用临时空间必须大于当前视频大小加 128 MiB。仅翻译已存在且通过验证的外置 SRT 时不需要长期保存媒体副本。
- ASS/SSA/VTT 可作为迁移伴随文件，但当前翻译输入必须是严格 UTF-8 SRT。
- ASR 与 PGS OCR 的质量取决于所配置的外部 worker；内外英文字幕都不存在而 ASR 未配置时，该视频会失败并显示 `[subtitles.asr]`、worker、模型及 `doctor` 的补全步骤。
- V3 使用系统调度器启动一次性命令，不内置第二套守护进程或 Web 界面。

完整设计和安全边界见 `ARCHITECTURE.md`；V2 能力为何保留、重做或删除，见 `docs/V2_SCOPE_DECISIONS.md`。
