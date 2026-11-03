# 给编码 agent

这是 `version4` 的唯一入口。先读本文件，再读 `docs/map.md`、`docs/invariants.md` 和 `docs/v4-decisions.md`。有任务卡时再读那一张卡。

这里的 agent 只改仓库、跑下面的检查、写任务卡。产品运行时仍由确定性规则做分类和迁移。v2 的 MCP、剧情生成和 LLM 规划器不回到这条分支。

## 当前阶段

步骤 A–D 已落地。步骤 B 抽出 `subtrans-core`。步骤 C 抽出 `subtrans-io` 和 `subtrans-remote`。步骤 D 增加 `--json` 事件通道、`Reporter`、`changes/` 片段和任务卡 `result`。默认人读句子与 `origin/version3` @ `1f19015` 相同。步骤 E–G 没有开始。

在 iDay 点名下一步之前：

- 不再拆 crate。不建 `subtrans-app`、`subtrans-cli`、`subtrans-evals`。`subtrans-core` 不加 reqwest、suppaftp、rusqlite，也不调用 `std::process`。
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

一个 `.rs` 文件超过 400 行时，拆文件属于以后的 `move-only` 任务。步骤 C 只搬了存储、状态、外部进程、密钥读取和 HTTP 客户端。步骤 D 只加了输出通道。

## 验证

默认只跑 T0：

```sh
scripts/agent-check.sh
```

CI 在 `version4` 的 push 和以 `version4` 为基线的 pull request 上跑 T1：

```sh
scripts/agent-check.sh --workspace
```

workspace 成员是根 crate `subtrans`、`subtrans-core`、`subtrans-io`、`subtrans-remote`。T0 和 T1 都是 `cargo fmt --all --check`、`cargo clippy --locked --workspace --all-targets -- -D warnings`、`cargo test --locked --workspace --all-targets`。成功时脚本打印一行 JSON：`{"ok":true,"tier":"t0","failed":0}`。

不要加 `--ignored`。方括号 FTP 的无网络判断在 `subtrans-core`。实盘测试在 `crates/subtrans-io/tests/ftp_bracket_realrun.rs`，默认忽略。`scripts/agent-check.sh --live` 在 `SUBTRANS_LIVE`、主机、端口、账号或样本路径缺失时直接失败，不使用内置地址。不要跑 `subtrans doctor` 做代码验证，它会在存储根上创建并删除探针。不要执行 `tools/` 里的脚本。

## 记录

任务完成时在卡末尾写 `result`。`check` 写 `passed` 或 `failed`，对应 T0/T1 JSON 的 `ok`。`behavior` 只用 `move-only`、`tighter`、`bugfix`、`invariant-change`。已发布的 `CHANGELOG.md` 章节不改。未发布的说明写在 `changes/NNNN-短名.md`，一条变更一个片段，用 Added、Changed 或 Fixed。

## `--json`

默认 stdout 仍是原来的人读句子，包括 `plan_hash=`、`PENDING ` 和可粘贴的覆盖键。`--json` 是全局开关，诊断改为 stdout 上每行一个 JSON 对象。计划文件照常写入。批准迁移仍然要提交 `plan_hash`，JSON 不能代替计划文件。

事件至少包含 `event`。下面四个是合同字段，按名字读取，不依赖键的顺序：

```json
{"event":"scan.empty_dir","path":"incoming/show"}
{"event":"subtitle.blocked","video":"...","reason":"review_failed","index":12}
{"event":"migrate.pending","source":"...","reason":"...","override_key":"[migration.overrides....]"}
{"event":"plan.ready","plan_hash":"...","items":10,"pending":2}
```

`path` 在整树为空时是 `(root)`。`override_key` 含方括号，就是原来人读行里的 TOML 表头。`index`、`items`、`pending` 是数字。`reason` 是已记录的审校原因；有多条时用逗号连接，没有记录时用 `review_failed`。`subtitle.blocked` 只在拒绝发布时出现，人读输出不因此多一行。其余诊断使用同一个信封，字段对应原来句子里的信息。JSON 模式下这些诊断都在 stdout，包括原来写到 stderr 的句子。命令失败时，`main` 返回的错误说明仍在 stderr。
