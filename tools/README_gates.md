# fbwl 字幕闸门三件套（11-07 站长裁定版）

**被闸的人不许改闸**：本目录 `fbwl_review_selfcheck.py` / `fbwl_rerun_gate.py` /
`l2_align_audit_v2.py` 属闸门与审计器具，只准代码运维在本仓提 PR 修改；
作者（字幕流水线）只提需求不许动刀。改前钉 sha256 报站长，改后必跑
`--selftest` 全绿再交。

## 1. tools/fbwl_review_selfcheck.py —— 作者侧收口自检（对照读数）

收口后跑：`python3 tools/fbwl_review_selfcheck.py [review.jsonl] [journal ...]`
（默认 `tmp_fbwl_work/fbwl_run/review.jsonl` + `main_journal.jsonl` `rerun_miss.jsonl`；
在团队 workspace 根目录下跑，`--work` 可换目录）。

断言 R重复 / T词表 / A覆盖+连续 / B在场 / C状态 / D形态 / E思考流 七组，全绿输出
`SELFCHECK PASS entries=… tags=… agg_sha256=…`（聚合 sha 口径=三键投影按 i 排序
sort_keys，与旧版逐字一致，两份读数须同值）。

注意：B 只证 review≈journal（同一作者自洽），属对照证据；**STOR 放行以代码运维
独立跑 `fbwl_stor_gate_20261107.py` 五断言全绿为准**。E 样豁免账
`logs/fbwl_stor_adjudicate_2026-11-07.json` 由代码运维签核，作者不得自改；
`--waive none` 可停用看原始 SUSPECT 全量。

## 2. tools/fbwl_rerun_gate.py —— rerun 熔断闸

**每轮 rerun 收口后登记一次，必须带收口事件标识**：

```
python3 tools/fbwl_rerun_gate.py --batch R2-strict-1830
```

- 轮次键 =（batch, review.jsonl sha256）。**同 batch 重跑幂等重放**不重复计轮；
  不同 batch 烧出相同 miss 集照常计轮——真·连烧两轮不降必触发 STOP_BREAKER。
- 不带 `--batch` 只读预演（DRY-RUN）：不落账不写 state，防半道误起闸假熔断。
  **禁止**为了「看一眼」随手起闸再删 state（11-07 曾发生删 rounds.json 清史）。
- 旧格式轮（无 verdict）重放 → `STATE_ERROR`（rc=2）报站长，绝不按默认 GO 放行。
- state 写回前自动整体备份 `.prev`，tmp+`os.replace`+fsync 全量重写。
- 退出码：0=GREEN/GO，1=STOP_BREAKER（禁起第 3 轮，报站长），2=STATE_ERROR。

## 3. tools/l2_align_audit_v2.py —— 对齐审计器（两队共用）

`python3 tools/l2_align_audit_v2.py <in.srt> <out_prefix> --judge qwen [--conc 2]`

- 缓存键 = 裁判指纹（judge_id+model+生效 token 档+判据版本）+（idx,en,zh）。
  换裁判/换 `--max-tokens` 续跑会**显式弃用**旧判定并计数点名（`弃用(异裁判配置/旧键)=N`），
  不再静默复用——「一个裁判配置一个 out_prefix」的规矩已由代码约束兜底，但换配置的
  重判要花模型时间，排期时按全量重判估。
- 判据与 `wb_align_audit.py` byte 级一致（11-07 复核坐实）；并发守团队硬限 ≤2。
- 阳性对照（`--control`）凡「NO=0」结论必跑。

## 4. tools/fbwl_sc_review_regress.py —— sc_review 保留改动哨兵

`python3 tools/fbwl_sc_review_regress.py [--src tmp_fbwl_work/sc_review.py]`

U1 无 i 批级记录被跳过 / U2 全量重写不丢段（对照实现行为用例）+ 源码钉
（跳过守卫与全量重写姿势、review.jsonl 禁 append）。作者不得再自改 sc_review；
姿势被改动即红。**交卷卷须点名带 --src 实跑的读数**，CI 里缺件只算 SKIP。

## 台账一页纸：用 ds90_ledger.py，别拿纯 append 当真值（11-07 裁定⑤ 仓级规矩）

两条合法姿势各一个原语：快照台账 `atomic_write_json()`（tmp+os.replace 全量
重写，断电不留半截）；流水台账 `append_record()`（必带键）+ 读侧
`recompute_done()` 按键取最后一条定性，`status="undone"` 撤单。
**禁止 `set(所有行)` 当 done 集。** 高危名单存量件（acgs_s05 两支 journal、
gap_scan 五支 STATE、newseed AUDIT/POOL）新改一律迁本库。
自检：`python3 tools/ds90_ledger.py`。
