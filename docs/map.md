# 代码地图

workspace 成员是根 crate `subtrans`（`Cargo.toml`，库 `src/lib.rs`，二进制 `src/main.rs`）和 `subtrans-core`（`crates/subtrans-core`）。步骤 B 只抽出纯规则。`subtrans-io`、`subtrans-remote`、`subtrans-app`、`subtrans-cli`、`subtrans-evals` 还没有建。

验证命令：`scripts/agent-check.sh`。CI 使用 `scripts/agent-check.sh --workspace`。`evals/` 还没有运行器；下表的 JSONL 是从测试抄出的断言，执行它们的是对应的 `cargo test`。

| 模块 | 路径 | 职责 | 断言抄本 | 现有测试 |
| --- | --- | --- | --- | --- |
| CLI | `src/main.rs` | 四个子命令；人读 stdout | 步骤 D 才加 `--json` | `tests/rust_cli.rs` |
| 配置 | `src/config.rs` | 严格 TOML、`version = 3`、扫描排除 | `evals/scan/exclude-and-empty.jsonl` | `src/config.rs` 内测试 |
| 路径规则 | `crates/subtrans-core/src/path.rs` | 相对路径规范化。根 crate 再导出 `storage::validate_relative_path` | `evals/path/safety.jsonl` | `tests/rust_storage.rs`、`src/storage/mod.rs` |
| 存储 | `src/storage/` | 本地/FTP、空壳目录、方括号列举。FTP 客户端留在这里 | `evals/path/`、`evals/scan/exclude-and-empty.jsonl` | `tests/rust_storage.rs`、`src/storage/mod.rs`、`src/storage/ftp.rs` |
| 分类 | `crates/subtrans-core/src/classify.rs` | 规则分类。根 crate 再导出 `migration::classify_path` | `evals/classify/kinds.jsonl` | `tests/rust_migration_plan.rs` |
| 计划数据 | `crates/subtrans-core/src/plan.rs` | 计划结构、哈希、schema 6。列举存储和写盘仍在 `src/migration/planner.rs` | `evals/plan/assertions.jsonl` | `tests/rust_migration_plan.rs`、`tests/rust_migration_safety.rs` |
| 迁移执行 | `src/migration/` | 建计划、批准、执行 | `evals/plan/assertions.jsonl` | `tests/rust_migration_plan.rs`、`tests/rust_migration_safety.rs` |
| SRT | `crates/subtrans-core/src/srt.rs` | 解析与格式化。根 crate 再导出 `subtitles::parse_srt` | `evals/srt-protocol/` | `tests/rust_subtitles.rs` |
| 质量门 | `crates/subtrans-core/src/quality.rs` | 源字幕评分和译文质量门 | `evals/quality/gates.jsonl` | `crates/subtrans-core/src/quality.rs`、`tests/rust_subtitles.rs` |
| 协议解析 | `crates/subtrans-core/src/protocol.rs` | 翻译/审校 JSON、围栏剥离、已知键名。根 crate 再导出 `parse_aligned` | `evals/srt-protocol/responses.jsonl` | `crates/subtrans-core/src/protocol.rs`、`tests/rust_subtitles.rs` |
| 字幕流程 | `src/subtitles/` | 抽取、HTTP 翻译、缓存、发布。reqwest 留在这里 | `evals/srt-protocol/prompts.jsonl`、`evals/quality/` | `src/subtitles/translation.rs`、`tests/rust_subtitle_pipeline.rs` |
| 资料 | `src/metadata.rs` | TMDB 海报/NFO 与资料清单 | 行为仍由集成测试覆盖，步骤 A 不另造期望 | `tests/rust_metadata.rs` |
| 产物 | `src/artifact.rs` | 字幕 `ready` manifest，schema 3 | 见不变量 | 随字幕与迁移测试 |
| 状态 | `src/state.rs` | SQLite 租约、进度、事件 | 见不变量；无独立 JSONL | `src/state.rs` 内测试 |

`tools/` 不是这条地图的一部分。那里是下载站、SSH 和外网站点脚本，步骤 E 迁出仓库。`scripts/agent-check.sh` 不调用它们。

`tests/ftp_bracket_realrun.rs` 是忽略的实盘测试。无网络的方括号规则在 `src/storage/ftp.rs` 的单元测试里，并抄到 `evals/path/listing.jsonl`。

外部边界保持 v3：`ffmpeg` / `ffprobe`、可选 ASR 与 PGS OCR worker、Ollama 或兼容 HTTP、TMDB。模型只翻译 cue。
