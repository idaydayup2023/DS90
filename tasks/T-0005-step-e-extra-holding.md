---
id: T-0005
status: done
title: 把运维脚本暂存到 extra
crates: []
allow_paths:
  - extra/**
  - tools/**
  - AGENTS.md
  - docs/invariants.md
  - docs/map.md
  - docs/v4-decisions.md
  - tasks/**
  - scripts/agent-check.sh
  - .github/workflows/ci.yml
deny_paths:
  - src/**
  - crates/**
  - deploy/**
  - .github/workflows/release.yml
  - config.example.toml
  - CHANGELOG.md
risk: normal
verify: scripts/agent-check.sh --workspace
record:
  - 本任务卡的 result 段
---

# 把运维脚本暂存到 extra

iDay 改了决定 4：暂不另建仓库。只做迁移步骤 E。DownloadStation、SSH 和外网站点脚本从 `tools/` 移到 `extra/`。`extra/` 是暂存区，不是默认可写面。以后迁出本仓库仍是开放项。产品验证不调用实弹入口。

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

`evals/` 的 `expect` 没有改。`check` 跑 fmt、clippy 和整个 workspace 的 `cargo test`，不运行 `extra/` 的实弹入口，也不运行忽略的实盘测试。
