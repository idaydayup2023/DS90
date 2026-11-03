# v3 等价验收

这是步骤 F 的检查记录，不是签收。iDay 还没有在本文件签收。未签收之前，`version4` 不能替换 `version3`，也不能打 `v4.*` 标签。

- 基线：`origin/version3` @ `1f190158a0021d29070dd221685845e232c876a4`
- 被检查的树：`origin/version4` @ `a81747756769a0ca6eff6a3bbb2db0630759d6c4`
- 检查日期：2026-11-03
- iDay 签收：未签收

未签收之前保持这些边界：

- `version3` 仍是生产分支。launchd 与 `v3.*` 发布不变。
- `.github/workflows/release.yml` 仍只匹配 `v3.*`。本次没有改这个文件。
- 不把本分支合并进 `version3`。
- 不开始步骤 G。

`evals/` 没有单独的运行器。每一行 JSONL 的 `source` 指向现有测试，执行它们的是 `cargo test`。`evals/` 自步骤 A 抄出之后没有改过 `expect`。

## 检查结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| T1 | 通过 | `scripts/agent-check.sh --workspace` 打印 `{"ok":true,"tier":"t1","failed":0}`。3 个忽略的实盘测试没有运行。 |
| `classify` | 通过 | `evals/classify/kinds.jsonl` 14 条。来源测试在 `tests/rust_migration_plan.rs`，该文件与 `origin/version3` 相同，T1 里 12 个计划测试通过，含 `supergirl_is_a_movie_and_never_receives_s01e01`。 |
| `srt-protocol` | 通过 | `responses.jsonl` 29 条、`prompts.jsonl` 3 条。协议断言已搬到 `crates/subtrans-core/src/protocol.rs`，提示词测试仍在 `src/subtitles/translation.rs`。同名测试还在，T1 通过。`tests/rust_subtitles.rs` 与 v3 相同。 |
| `quality` | 通过 | `evals/quality/gates.jsonl` 12 条。质量门测试与 v3 的 `src/subtitles/quality.rs` 同名函数一致，现位于 `crates/subtrans-core/src/quality.rs`。`tests/rust_subtitles.rs` 的质量断言与 v3 相同，T1 通过。 |
| `plan` | 通过 | `evals/plan/assertions.jsonl` 14 条。`tests/rust_migration_plan.rs` 与 `tests/rust_migration_safety.rs` 相对 `origin/version3` 无差异，T1 通过。 |
| `path` | 通过 | `safety.jsonl` 13 条，来源 `tests/rust_storage.rs` 与 v3 相同。`listing.jsonl` 6 条，无网络判断在 `crates/subtrans-core/src/listing.rs`，断言与 v3 `src/storage/ftp.rs` 的两个单元测试相同，T1 通过。 |
| `scan` | 通过 | `evals/scan/exclude-and-empty.jsonl` 16 条。排除断言在 `src/config.rs`，与 v3 的测试断言行一致。空壳计数在 `crates/subtrans-io/src/storage/mod.rs`，T1 通过。 |
| `subtrans --help` 子命令 | 通过 | 对照 v3 与 v4 两个已构建二进制。顶层都是 `metadata`、`subtitles`、`migrate`、`doctor`、`help`。`migrate` 下都是 `plan`、`apply`、`review`、`help`。v4 多了全局 `--json`，它是选项，不是新子命令。 |
| `config.example.toml` 仍能加载 | 通过 | 该文件相对 `origin/version3` 无差异。T1 中 `distributed_example_is_valid_and_reproducible` 通过，它用 `Config` 解析这份示例。 |

## 第 12 节锚点

这些是验收时对照的现成事实，不是新行为。本次都由上表里的测试盖住。

| 锚点 | 结果 | 对照 |
| --- | --- | --- |
| 规则版本 `migration-rules-v3.3`，计划 schema 6，字幕 artifact schema 3，资料 schema 1 | 通过 | 与 `origin/version3` 的常量相同 |
| `Supergirl.2026.2160p` 判为电影，季集为空；4K/HDR/HEVC 不改变类型 | 通过 | `supergirl_is_a_movie_and_never_receives_s01e01` 与分类 JSONL |
| 证据不足进入 pending，`migrate review` 打印原因和 `[migration.overrides."<源相对路径>"]` | 通过 | `pending_review_prints_reason_evidence_and_exact_override_key` |
| 计划、配置、存储端点或源内容变化后，旧 `plan_hash` 不能 `apply` | 通过 | `plan_is_bound_to_configuration_and_recovers_when_sources_are_already_promoted` |
| 翻译失败不发布 `ready`；一个文件失败不挡住后面的文件 | 通过 | `one_translation_failure_is_repaired_by_review_and_later_videos_publish` 等字幕流水线测试 |
| 目标冲突、中断、重复执行不覆盖未知内容，也不在目标校验完成前删除源 | 通过 | `destination_collisions_are_detected_before_apply` 与 `plan_is_bound_to_configuration_and_recovers_when_sources_are_already_promoted` |
| 含 `[]` 的路径在目录内列举，并由无网络测试覆盖 | 通过 | `listing::tests` |
| 扫描排除命中的路径保持原样；空壳目录与列目录失败分开 | 通过 | `exclude_paths_match_files_and_directory_prefixes` 与空壳计数测试 |
| 计划、manifest、日志夹具不出现密钥的值 | 通过 | `distributed_example_contains_no_deployment_identifiers_or_inline_password` 与 `missing_tmdb_token_guidance_is_actionable_and_secret_free` |

## 签收

iDay 签收：未签收。

签收之前，不要把 `version4` 当成生产发布线，不要启用 `v4.*` 标签，不要开始步骤 G。
