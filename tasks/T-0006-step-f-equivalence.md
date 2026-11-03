---
id: T-0006
status: done
title: 记录 v3 等价检查
crates: []
allow_paths:
  - docs/v3-equivalence.md
  - docs/invariants.md
  - docs/map.md
  - docs/v4-decisions.md
  - AGENTS.md
  - tasks/**
deny_paths:
  - src/**
  - crates/**
  - extra/**
  - tools/**
  - deploy/**
  - .github/workflows/release.yml
  - config.example.toml
  - CHANGELOG.md
  - evals/**
risk: normal
verify: scripts/agent-check.sh --workspace
record:
  - 本任务卡的 result 段
  - docs/v3-equivalence.md
---

# 记录 v3 等价检查

iDay 已点名：只做迁移步骤 F。对照 `origin/version3` @ `1f19015` 跑 T1、六个评测套件、`subtrans --help` 子命令和 `config.example.toml` 加载，把通过或失败写进 `docs/v3-equivalence.md`。不代替 iDay 签收。不切换生产，不启用 `v4.*` 标签，不开始步骤 G，不合并进 `version3`。

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
  check: passed
  invariants_touched: []
```

检查对象是 `a817477`。结果都是通过，详见 `docs/v3-equivalence.md`。该文件的签收栏仍是未签收。
