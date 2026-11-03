# 任务卡

一件工作一张卡：`tasks/T-NNNN-短名.md`。空白格式是 `tasks/T-0000-template.md`。`T-0000` 不是开放任务。

步骤 A 的完成记录是 `tasks/T-0001-step-a-contract.md`。步骤 B 的完成记录是 `tasks/T-0002-step-b-core.md`。步骤 C 的完成记录是 `tasks/T-0003-step-c-io-remote.md`。

`tasks/backlog/` 只放还没批准的候选。候选不能自行改成 `status: open`。步骤 F 之前，只有 iDay 点名的卡可以实施。

`risk` 的三个值：

- `normal`：默认。可以加更严的案例，不能放宽 `docs/invariants.md`。
- `live`：允许实盘或 `tools/`。步骤 A 的检查脚本拒绝 `--live`。只有 iDay 能写这个值。
- `invariant`：允许放宽不变量。只有 iDay 能写这个值。

完成时在卡末尾写 `result`。
