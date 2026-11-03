# 评测抄本

这些 JSONL 从 `version3` 已有测试的断言抄出，一行一个 JSON 对象。步骤 A 没有评测运行器，`scripts/agent-check.sh` 不读取本目录。对应行为由 `source` 字段里的测试执行。

不要改 `expect` 来配合一次代码改动。放宽断言属于 `risk: invariant`。

| 文件 | 来源测试 |
| --- | --- |
| `classify/kinds.jsonl` | `tests/rust_migration_plan.rs` 的 `classify_path` 断言 |
| `srt-protocol/responses.jsonl` | `tests/rust_subtitles.rs`、`src/subtitles/translation.rs` |
| `srt-protocol/prompts.jsonl` | `src/subtitles/translation.rs` 的提示词断言 |
| `quality/gates.jsonl` | `tests/rust_subtitles.rs`、`src/subtitles/quality.rs` |
| `plan/assertions.jsonl` | `tests/rust_migration_plan.rs`、`tests/rust_migration_safety.rs` |
| `path/safety.jsonl` | `tests/rust_storage.rs` |
| `path/listing.jsonl` | `src/storage/ftp.rs` 的无网络单元测试 |
| `scan/exclude-and-empty.jsonl` | `src/config.rs`、`src/storage/mod.rs` |
| `srt-protocol/stages.jsonl` | `tests/rust_subtitle_stages.rs`。这是 version4 的阶段断言，不是从 v3 抄来的 |

`tests/ftp_bracket_realrun.rs` 的生产路径没有抄进来。
