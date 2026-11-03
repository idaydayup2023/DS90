---
id: T-0003
status: done
title: 抽出 subtrans-io 与 subtrans-remote
crates: [subtrans, subtrans-core, subtrans-io, subtrans-remote]
allow_paths:
  - Cargo.toml
  - Cargo.lock
  - crates/subtrans-core/**
  - crates/subtrans-io/**
  - crates/subtrans-remote/**
  - src/**
  - tests/**
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

# 抽出 subtrans-io 与 subtrans-remote

iDay 已点名：只做迁移步骤 C。存储、SQLite、外部进程和密钥读取进 `subtrans-io`。TMDB 与模型 HTTP 进 `subtrans-remote`。工作流通过 core 里的 `LlmClient` 和 `MetadataSource`。测试用脚本化假客户端和本地存储，不再起 `TcpListener`。方括号列举的纯判断留在 core 的无网络测试。T2 缺少环境变量时直接失败。

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

`evals/` 的 `expect` 没有改。`check` 跑 fmt、clippy 和整个 workspace 的 `cargo test`，不运行忽略的实盘测试。
