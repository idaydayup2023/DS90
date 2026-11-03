---
id: T-0001
status: done
title: 落地 version4 步骤 A 合同层
crates: [subtrans]
allow_paths:
  - AGENTS.md
  - docs/invariants.md
  - docs/map.md
  - docs/v4-decisions.md
  - tasks/**
  - evals/**
  - scripts/agent-check.sh
  - .github/workflows/ci.yml
deny_paths:
  - src/**
  - tools/**
  - deploy/**
  - .github/workflows/release.yml
  - Cargo.toml
  - Cargo.lock
  - config.example.toml
risk: normal
verify: scripts/agent-check.sh --workspace
record:
  - 本任务卡的 result 段
---

# 落地 version4 步骤 A 合同层

iDay 已点名：从 `origin/version3` 建立 `version4`，只加合同层。产品行为不变，仍是单 crate。

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

`evals/` 是断言抄本，步骤 A 不执行 JSONL。`check` 跑的是 fmt、clippy 和现有 `cargo test`。
