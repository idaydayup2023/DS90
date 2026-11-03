# 代码地图

workspace 成员是根 crate `subtrans`（`Cargo.toml`，库 `src/lib.rs`，二进制 `src/main.rs`）、`subtrans-core`、`subtrans-io`、`subtrans-remote`。步骤 C 让工作流走 trait。步骤 D 把诊断收进 `Reporter`。`subtrans-app`、`subtrans-cli`、`subtrans-evals` 还没有建。

验证命令：`scripts/agent-check.sh`。CI 使用 `scripts/agent-check.sh --workspace`。`evals/` 还没有运行器；下表的 JSONL 是从测试抄出的断言，执行它们的是对应的 `cargo test`。

| 模块 | 路径 | 职责 | 断言抄本 | 现有测试 |
| --- | --- | --- | --- | --- |
| CLI | `src/main.rs` | 四个子命令。默认人读句子；`--json` 打事件 | `tests/rust_cli.rs` 钉住 `plan_hash=`、`PENDING`、覆盖键 | `tests/rust_cli.rs` |
| Reporter | `crates/subtrans-core/src/report.rs` | 人读句子或一行一个 JSON 事件。不写计划文件 | 见 `AGENTS.md` 的事件形状 | `crates/subtrans-core/src/report.rs`、`tests/rust_cli.rs` |
| 配置 | `src/config.rs` | 严格 TOML、`version = 3`、扫描排除 | `evals/scan/exclude-and-empty.jsonl` | `src/config.rs` 内测试 |
| 路径规则 | `crates/subtrans-core/src/path.rs` | 相对路径规范化。根 crate 再导出 `storage::validate_relative_path` | `evals/path/safety.jsonl` | `tests/rust_storage.rs` |
| 方括号列举判断 | `crates/subtrans-core/src/listing.rs` | 含 `[]` 则目录内列举。无网络 | `evals/path/listing.jsonl` | `crates/subtrans-core/src/listing.rs` |
| 存储 | `crates/subtrans-io/src/storage/` | 本地/FTP 与 `Storage`。根 crate 再导出并按配置打开 | `evals/path/`、`evals/scan/exclude-and-empty.jsonl` | `tests/rust_storage.rs`、`crates/subtrans-io` |
| 状态 | `crates/subtrans-io/src/state.rs` | SQLite 租约、进度、事件 | 见不变量；无独立 JSONL | `crates/subtrans-io/src/state.rs` |
| 外部进程 | `crates/subtrans-io/src/process.rs` | ffmpeg、ffprobe、worker 进程 | 见不变量 | `crates/subtrans-io/src/process.rs` |
| 密钥读取 | `crates/subtrans-io/src/secrets.rs` | 环境变量、launchd、钥匙串。值不进计划或日志 | 见不变量 | `src/config.rs` 内测试 |
| 分类 | `crates/subtrans-core/src/classify.rs` | 规则分类。根 crate 再导出 `migration::classify_path` | `evals/classify/kinds.jsonl` | `tests/rust_migration_plan.rs` |
| 计划数据 | `crates/subtrans-core/src/plan.rs` | 计划结构、哈希、schema 6。列举存储和写盘仍在 `src/migration/planner.rs` | `evals/plan/assertions.jsonl` | `tests/rust_migration_plan.rs`、`tests/rust_migration_safety.rs` |
| 迁移执行 | `src/migration/` | 建计划、批准、执行 | `evals/plan/assertions.jsonl` | `tests/rust_migration_plan.rs`、`tests/rust_migration_safety.rs` |
| SRT | `crates/subtrans-core/src/srt.rs` | 解析与格式化。根 crate 再导出 `subtitles::parse_srt` | `evals/srt-protocol/` | `tests/rust_subtitles.rs` |
| 质量门 | `crates/subtrans-core/src/quality.rs` | 源字幕评分和译文质量门 | `evals/quality/gates.jsonl` | `crates/subtrans-core/src/quality.rs`、`tests/rust_subtitles.rs` |
| 协议解析 | `crates/subtrans-core/src/protocol.rs` | 翻译/审校 JSON、围栏剥离、已知键名。根 crate 再导出 `parse_aligned` | `evals/srt-protocol/responses.jsonl` | `crates/subtrans-core/src/protocol.rs`、`tests/rust_subtitles.rs` |
| 字幕流程 | `src/subtitles/` | 抽取、缓存、发布。模型调用走 `LlmClient` | `evals/srt-protocol/prompts.jsonl`、`evals/quality/` | `tests/rust_subtitle_pipeline.rs`、`tests/support/mod.rs` |
| 模型 HTTP | `crates/subtrans-remote/src/llm.rs` | Ollama 与 OpenAI-compatible HTTP。实现 `LlmClient` | `evals/srt-protocol/responses.jsonl` | 字幕集成测试注入 `ScriptedLlm` |
| 资料 | `src/metadata.rs` | 匹配、NFO、清单。TMDB 调用走 `MetadataSource` | 行为仍由集成测试覆盖 | `tests/rust_metadata.rs` |
| TMDB HTTP | `crates/subtrans-remote/src/tmdb.rs` | TMDB JSON 与图片。实现 `MetadataSource` | 见资料测试 | `tests/support/mod.rs` 的 `FixtureMetadata` |
| 产物 | `src/artifact.rs` | 字幕 `ready` manifest，schema 3 | 见不变量 | 随字幕与迁移测试 |

`tools/` 不是这条地图的一部分。那里是下载站、SSH 和外网站点脚本，步骤 E 迁出仓库。`scripts/agent-check.sh` 不调用它们。

`crates/subtrans-io/tests/ftp_bracket_realrun.rs` 是忽略的实盘测试。它不带默认主机或样本库路径。无网络的方括号规则在 `crates/subtrans-core/src/listing.rs`，并抄到 `evals/path/listing.jsonl`。

外部边界保持 v3：`ffmpeg` / `ffprobe`、可选 ASR 与 PGS OCR worker、Ollama 或兼容 HTTP、TMDB。模型只翻译 cue。
