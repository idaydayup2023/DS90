# 不变量

本文件把 `ARCHITECTURE.md` 和现有测试已经钉住的安全行为列成检查清单。步骤 A–D 不放宽这些行为。步骤 C 把存储、状态、进程和 HTTP 客户端拆到 io 与 remote。步骤 D 只增加 `--json` 通道，默认人读句子不变。放宽任何一条，任务卡必须由 iDay 写成 `risk: invariant`。agent 不能自己改这个风险，也不能删掉对应断言。

来源：`ARCHITECTURE.md`、`docs/V2_SCOPE_DECISIONS.md`、`src/` 里的 schema 常量，以及 `evals/` 所引用的测试。

## 身份与版本

- 规则版本保持 `migration-rules-v3.3`（`src/migration/classifier.rs`）。
- 计划 schema 保持 `6`（`src/migration/planner.rs`）。
- 字幕 artifact schema 保持 `3`（`src/artifact.rs`）。
- 资料 schema 保持 `1`（`src/metadata.rs`）。
- 配置 `version = 3`。v4 继续加载现有 `subtrans.toml`，字段含义不变。

## 路径

- 存储路径是规范化相对路径。拒绝绝对路径、`..`、空路径段、`.` 段、反斜杠。空字符串和单独的 `.` 规范化成空相对路径。见 `evals/path/safety.jsonl`。
- 本地符号链接不得逃出存储根。
- 含 `[` 或 `]` 的远程目录必须进入目录后再列举，不能把该路径当作 `MLSD` 参数。无方括号路径保持原列举方式。见 `evals/path/listing.jsonl`。
- 这条规则的实盘样本测试是 `#[ignore]`，T0/T1 不跑。主机和样本路径只来自环境变量，缺失时 T2 直接失败。不要在新文件里写下生产主机。

## 分类

- 媒体类型只来自可解释规则。完整季集标记判剧集；年份加发行签名判电影；证据不足是 `unknown` / pending。
- `4K`、`UHD`、`2160p`、`HEVC`、`HDR`、`DV` 只表示画质，不生成季集，也不单独把文件判成电影。
- `Supergirl.2026.2160p...` 是电影，季和集都为空，证据含 `movie_release_signature`。
- 多集范围、日期型节目、动漫方括号集数进入 pending，不自动迁移。
- TMDB 和翻译模型不能改变媒体类型或目标路径。

案例在 `evals/classify/kinds.jsonl`。

## 字幕

- cue 索引和时间轴保持绑定。缺项、重复项、越界索引、空译文、非 JSON 不发布。
- 已测过的无语义包装可以规范化：代码围栏、裸数组、数字字符串索引、译文字段别名、附加元数据、TranslateGemma 的 `"text:"` 键名笔误。语义仍然拒绝。
- 同索引被模型拆开时，合并保留全部译文，空碎片仍拒绝。
- 英文回显和过低的目标文字比例不能当成功译文。短标识符（如 `FDE`、`OpenAI`）可以原样保留。
- 翻译失败不发布 `ready`。一个文件失败不挡住后面的文件。
- 模型、目标语言、批次大小或源哈希变化都会改变缓存身份。`should_translate(false, true, true)` 为假；`force`、输出不存在或 manifest 不匹配则为真。

案例在 `evals/srt-protocol/` 和 `evals/quality/`。

## 计划与执行

- 计划是规范 JSON。执行必须提交精确 `plan_hash`。改目标路径后校验失败。
- 同一输入再次生成计划，哈希不变。
- 配置或存储端点与计划不一致时，`apply` 失败。
- pending 项没有可执行目标、没有伴随文件动作、没有内容 SHA-256。
- 没有字幕 `ready` manifest 时，迁移默认 pending。逐文件 `allow_untranslated = true` 才能豁免。
- 与视频名精确匹配的 `.aria2` / `.part` 未完成标记使该视频 pending，不计算内容哈希。
- 目标冲突在 `apply` 之前停住。
- 默认 `apply` 在计划仍有 pending 时失败。`--allow-pending` 只搬走已就绪项，pending 源文件保持原样。
- 复制模式在目标校验完成之前不删除源。已提升到目标的文件，重跑向前恢复，不覆盖未知内容。

案例在 `evals/plan/assertions.jsonl`。

## 扫描

- `scan.exclude_paths` 命中文件或目录前缀时，该路径保持原样，不计入待处理。
- `scan.exclude_globs` 里 `*` / `?` 只匹配一个路径节，`**` 可跨节。
- 没有 `[scan]` 时，不排除任何路径。
- 目录存在但没有子条目，是空壳，与“列目录失败”和“有文件但缺件”分开。整树为空时报 `(root)`。

案例在 `evals/scan/exclude-and-empty.jsonl`。

## 密钥与状态

- 密码和 TMDB token 不进入配置、计划、manifest、状态库或日志。计划只保存账号 SHA-256。
- 状态库使用 SQLite WAL 与 `synchronous=FULL`。步骤 A 不改表结构。以后若改表，必须先有 schema 版本和打开旧库的测试。

## 执行面

- 一个二进制 `subtrans`，子命令是 `metadata`、`subtitles`、`migrate`、`doctor`。`--json` 只改变诊断的形状，不增加子命令，也不代替计划文件。
- `migrate apply` 不进无条件定时任务。`deploy/` 里的 launchd 示例只调度字幕命令。批准执行仍然要提交精确 `plan_hash`。
- worker 用显式命令和占位符，不经 shell，运行时不安装。
