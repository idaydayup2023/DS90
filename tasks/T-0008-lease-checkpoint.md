---
id: T-0008
status: done
title: 并发字幕任务不能互相改检查点或覆盖发布
crates: [subtrans, subtrans-io]
allow_paths:
  - src/subtitles/**
  - crates/subtrans-io/src/state.rs
  - tests/rust_subtitle_stages.rs
  - evals/srt-protocol/stages.jsonl
  - evals/README.md
  - docs/map.md
  - changes/0010-lease-checkpoint.md
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
  - changes/0010-lease-checkpoint.md
---

# 并发字幕任务不能互相改检查点或覆盖发布

iDay 已点名：多个机器人同时跑翻译和审校时，不能改坏同一条视频的检查点，也不能互相盖掉已发布字幕。

领取 job 的排他租约本来就在。缺口是 `subtitle_checkpoints` 的整行覆盖和删除不看租约，发布前也没有在写文件的当下再确认租约。先写会失败的测试 `tests/rust_subtitle_stages.rs` 的 `stale_reviewer_cannot_clobber_checkpoint_or_ready_artifact`，再改实现。不放宽 `docs/invariants.md`。不改默认分支，不合并 `version3`，不启用 `v4.*`。

## result

```yaml
result:
  behavior: bugfix
  eval:
    - evals/srt-protocol/stages.jsonl
  check: passed
  invariants_touched: []
```

T1 在本卡完成时必须打印 `{"ok":true,"tier":"t1","failed":0}`。
