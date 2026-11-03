---
id: T-0000
status: template
title: 短标题
crates: [subtrans]
allow_paths: []
deny_paths:
  - tools/**
  - deploy/**
  - .github/workflows/release.yml
risk: normal
verify: scripts/agent-check.sh
record:
  - 本任务卡的 result 段
---

# 短标题

这是模板，不是开放任务。复制到 `tasks/T-NNNN-短名.md` 后再填。`crates` 可以写 `subtrans`、`subtrans-core`、`subtrans-io` 或 `subtrans-remote`。不要在一张卡里开始步骤 D–G。

## 做什么

写清要保持或收紧的行为。先指出对应的 `evals/` 或现有测试。

## 不做什么

步骤 B–G 的事项不要写进一张 normal 卡。不要执行 `tools/`，不要改 `deploy/`，不要改 `v3.*` 发布工作流。

## result

完成后把 `status` 改成 `done`，并填写：

```yaml
result:
  behavior: move-only
  eval: []
  check: passed
  invariants_touched: []
```

`behavior` 用 `move-only`、`tighter`、`bugfix` 或 `invariant-change`。最后一种还要求本卡的 `risk` 已经是 `invariant`。
