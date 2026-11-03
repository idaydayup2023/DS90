---
id: T-0004
status: done
title: 增加 --json、Reporter、changes 片段和任务卡 result
crates: [subtrans, subtrans-core, subtrans-io]
allow_paths:
  - src/**
  - crates/subtrans-core/**
  - crates/subtrans-io/**
  - tests/**
  - changes/**
  - CHANGELOG.md
  - AGENTS.md
  - docs/invariants.md
  - docs/map.md
  - docs/v4-decisions.md
  - tasks/**
  - scripts/agent-check.sh
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

# 增加 --json、Reporter 和发布片段

iDay 已点名：只做迁移步骤 D。诊断走 `Reporter`。默认仍是原来的人读句子。`--json` 把同一条诊断打成事件。`plan_hash=`、`PENDING` 和覆盖键由现有 CLI 测试钉住。未发布的变更说明改放 `changes/`。`CHANGELOG.md` 已发布章节不改。

人读输出没有新增句子。`subtitle.blocked` 只在 JSON 通道出现。计划文件照常写入，批准仍然要提交 `plan_hash`。

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

`behavior` 记为 `move-only`：`evals/` 的 `expect` 和默认人读句子不变，唯一新增是 `--json` 通道。`check` 表示 T1 JSON 的 `ok` 为 true。
