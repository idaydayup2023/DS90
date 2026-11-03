---
id: T-0007
status: done
title: 分开字幕翻译和审校，并按检查点续跑
crates: [subtrans, subtrans-io]
allow_paths:
  - src/main.rs
  - src/subtitles/**
  - crates/subtrans-io/src/state.rs
  - tests/rust_subtitle_stages.rs
  - evals/srt-protocol/stages.jsonl
  - evals/README.md
  - changes/0009-separate-subtitle-stages.md
  - README.md
  - CHANGELOG.md
  - tasks/**
deny_paths:
  - extra/**
  - tools/**
  - deploy/**
  - .github/workflows/release.yml
  - docs/invariants.md
  - config.example.toml
risk: normal
verify: scripts/agent-check.sh --workspace
record:
  - 本任务卡的 result 段
  - changes/0009-separate-subtitle-stages.md
---

# 分开字幕翻译和审校，并按检查点续跑

iDay 已点名：翻译流程和审校流程必须能分开调用。两条流程在中断后都从检查点继续，不能把已经完成的批次从头再跑。

默认 `subtitles` 仍是两条都做，避免已有调用突然只跑一半。显式阶段是：

- `subtrans subtitles --stage translate`
- `subtrans subtitles --stage review`

检查点写在状态库 `subtitle_checkpoints`，不写进媒体目录，也不写入密钥。审校没有匹配的翻译检查点时直接失败，不改去调用翻译模型。`--force` 丢弃检查点。已发布字幕仍走现有 ready manifest 缓存。

先写会失败的测试 `tests/rust_subtitle_stages.rs`，再改实现。不放宽 `docs/invariants.md`。不改默认分支，不合并 `version3`，不启用 `v4.*`。

## result

```yaml
result:
  behavior: tighter
  eval:
    - evals/srt-protocol/stages.jsonl
  check: passed
  invariants_touched: []
```

T1 打印 `{"ok":true,"tier":"t1","failed":0}`。`tests/rust_subtitle_stages.rs` 在实现前不能编译。实现后六条都通过。

分开调用：

- `subtrans subtitles --stage translate`
- `subtrans subtitles --stage review`
- 省略 `--stage` 仍是 `both`

检查点在配置 `state.database` 指向的 SQLite 文件的表 `subtitle_checkpoints`。状态库 schema 是 1。旧库打开后原有 job 还在。
