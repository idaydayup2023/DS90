# 给编码 agent

这是 `version4` 的唯一入口。先读本文件，再读 `docs/map.md`、`docs/invariants.md` 和 `docs/v4-decisions.md`。有任务卡时再读那一张卡。

这里的 agent 只改仓库、跑下面的检查、写任务卡。产品运行时仍由确定性规则做分类和迁移。v2 的 MCP、剧情生成和 LLM 规划器不回到这条分支。

## 当前阶段

步骤 A 已落地：合同层，单 crate `subtrans`，产品行为与 `origin/version3` @ `1f19015` 相同。步骤 B–G 没有开始。

在 iDay 点名下一步之前：

- 不拆 crate，不改 `src/` 的行为，不改 `Cargo.toml` 依赖。
- 不删除、不移动 `tools/`。步骤 E 才把 DownloadStation、SSH 和外网站点脚本迁出本仓库，不放进 `ops/`。
- 不改 `deploy/`，不改 `.github/workflows/release.yml`。`v3.*` 发布和生产 launchd 仍走 `version3`。
- 不把本分支合并进 `version3`。

## 发现工作

没有 iDay 点名的任务卡，就不改产品代码。卡放在 `tasks/T-NNNN-短名.md`，格式见 `tasks/T-0000-template.md`。`tasks/backlog/` 里的候选不是实施许可。

`risk` 只有 iDay 能写成 `live` 或 `invariant`。agent 不能自己升风险。

## 修改边界

`normal` 任务的禁止路径：

- `tools/**`
- `deploy/**`
- `.github/workflows/release.yml`
- 任何 `subtrans.toml`、`.env`、`*.plan.json`、`*.sqlite3`
- `docs/invariants.md`，以及会放宽不变量断言的测试和 `evals/`

`evals/` 是从现有测试抄出的断言，步骤 A 没有评测运行器。真正执行这些断言的是 `cargo test`。不要改 `evals/` 的 `expect` 来迁就一次失败。

一个 `.rs` 文件超过 400 行时，拆文件属于以后的 `move-only` 任务，不是步骤 A 的工作。

## 验证

默认只跑 T0：

```sh
scripts/agent-check.sh
```

CI 在 `version4` 的 push 和以 `version4` 为基线的 pull request 上跑 T1：

```sh
scripts/agent-check.sh --workspace
```

现在仍是单 crate，两条命令都是 `cargo fmt --all --check`、`cargo clippy --locked --all-targets -- -D warnings`、`cargo test --locked --all-targets`。成功时脚本打印一行 JSON：`{"ok":true,"tier":"t0","failed":0}`。

不要加 `--ignored`。`tests/ftp_bracket_realrun.rs` 会连生产存储，不属于 T0/T1。`scripts/agent-check.sh --live` 在步骤 A 直接失败，不发起连接。不要跑 `subtrans doctor` 做代码验证，它会在存储根上创建并删除探针。不要执行 `tools/` 里的脚本。

## 记录

任务完成时在卡末尾写 `result`：`behavior`、碰到的 `evals/` 或测试、检查是否通过、`invariants_touched`。步骤 A 不改已发布的 `CHANGELOG.md`。发布片段是步骤 D 的事。

`--json` 命令输出已经批准，实现留在步骤 D。步骤 A 不改 CLI。
