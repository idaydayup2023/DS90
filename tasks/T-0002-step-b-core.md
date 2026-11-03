---
id: T-0002
status: done
title: 抽出 subtrans-core
crates: [subtrans, subtrans-core]
allow_paths:
  - Cargo.toml
  - Cargo.lock
  - crates/subtrans-core/**
  - src/migration/**
  - src/storage/mod.rs
  - src/subtitles/**
  - AGENTS.md
  - docs/invariants.md
  - docs/map.md
  - docs/v4-decisions.md
  - tasks/**
  - scripts/agent-check.sh
  - .github/workflows/ci.yml
deny_paths:
  - tools/**
  - deploy/**
  - .github/workflows/release.yml
  - config.example.toml
risk: normal
verify: scripts/agent-check.sh --workspace
record:
  - 本任务卡的 result 段
---

# 抽出 subtrans-core

iDay 已点名：只做迁移步骤 B。把路径规范化、分类、SRT、质量门、协议解析和计划数据结构搬进 `subtrans-core`。断言不改。core 不依赖 reqwest 或 suppaftp。

## result

```yaml
result:
  behavior: move-only
  eval:
    - evals/classify/kinds.jsonl
    - evals/srt-protocol/responses.jsonl
    - evals/srt-protocol/prompts.jsonl
    - evals/quality/gates.jsonl
    - evals/plan/assertions.jsonl
    - evals/path/safety.jsonl
    - evals/path/listing.jsonl
    - evals/scan/exclude-and-empty.jsonl
  check: scripts/agent-check.sh --workspace
  invariants_touched: []
```

`evals/` 仍是断言抄本，本步不改 `expect`。`check` 跑的是 fmt、clippy 和整个 workspace 的 `cargo test`。
