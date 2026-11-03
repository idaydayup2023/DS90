# v4 已批准的决定

iDay 于 2026-11-03 批准 `docs/v4-architecture.md` 第 11 节的全部十项决定。本文件是分支上的记录。步骤 A 落实合同层。步骤 B 抽出 `subtrans-core`。步骤 C 抽出 `subtrans-io` 与 `subtrans-remote`。下面其余标成“以后”的事项这次没有做。

1. **agent 的定义。** 已批准。v4 的 agent 只改仓库、跑 T0/T1、写任务卡。产品运行时继续由确定性规则做分类和迁移。v2 的 MCP、剧情生成和 LLM 规划器不回来。
2. **生产线。** 已批准。在步骤 F 签收之前，`version3` 仍是唯一生产分支。launchd 与 `v3.*` 发布保持不变。开发分支名是 `version4`。本次不合并进 `version3`，也不改 `deploy/` 与 `.github/workflows/release.yml`。
3. **配置兼容。** 已批准。v4 继续加载 `version = 3` 的 `subtrans.toml`，字段含义不变。步骤 A 不改配置解析。
4. **运维脚本的归属。** 已批准建议项：DownloadStation、SSH 和外网站点脚本在步骤 E 迁出本仓库，不放进 `ops/`。步骤 A 不删除、不移动 `tools/`。迁出之前，agent 不执行这些脚本，默认检查也不调用它们。
5. **不变量的批准方式。** 已批准。放宽不变量或修改 `docs/invariants.md` 必须有 iDay 在任务卡上写明的 `risk: invariant`。agent 不能自行升级风险等级。
6. **第一段自迭代授权。** 已批准。步骤 F 签收之后，agent 才可以自行领取 `risk: normal` 且 `behavior` 为 `move-only` 或 `tighter` 的 backlog 卡。在此之前，agent 只执行 iDay 点名的任务。步骤 A–C 是点名任务；D–G 还没有点名。
7. **`--json`。** 已批准，属于 v4 必做，实现排在步骤 D。人读文本保留。步骤 A 不改 CLI。
8. **文档语言。** 已批准。`AGENTS.md`、任务卡、`docs/invariants.md` 用中文。代码标识符、命令和 JSON 字段用英文。
9. **crate 划分。** 已批准六个 crate 的目标（`subtrans-core`、`subtrans-io`、`subtrans-remote`、`subtrans-app`、`subtrans-cli`、`subtrans-evals`）。步骤 C 之后，workspace 成员是根 crate `subtrans`、`subtrans-core`、`subtrans-io`、`subtrans-remote`。依赖向下：io 和 remote 只依赖 core。其余两个 crate 还没有建。
10. **实盘测试的默认地址。** 已批准，步骤 C 已做。实盘测试不写生产主机和样本库路径。`SUBTRANS_LIVE`、`SUBTRANS_FTP_HOST`、`SUBTRANS_FTP_PORT`、`SUBTRANS_FTP_USERNAME`、`SUBTRANS_FTP_PASSWORD`、`SUBTRANS_FTP_SAMPLES` 缺任何一个，T2 直接失败。T0/T1 不运行忽略测试。

架构原文在批准时位于项目文档，不在本仓库。实施以本文件和 `AGENTS.md` 为准。
