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

E 样在原有五类（中文推理标记词 / 英文推理标记 / 超长>120 / 英比>0.6 仅字母行 /
复读环）之外，11-07 22:0x 站长令补**译评型结构判据**三类：A 引号贴「译」译评结构
（`X" 译"Y"` 含全/半角引号变体）、B 半角引号失衡（奇数个）+ASCII 字母+译评语境、
C 句级模型自评元话语（`如下：`/`建议改`/`多译`/`译为` 等短语级，避开日常台词高频词）。
判据按结构特征收、非单条黑名单；正反例绑仓内 fixture
`tools/_gate_e_samples_20261107.json`（阳性=FBWL 971 落库件泄漏变体，阴性=洗清 9 条
+正常台词 20 条），`--selftest` 阳性漏检或阴性误判即红。

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

## 双读数存证：一律带 mtime（站长 11-07 21:0x 令，11-07 一天两次假红/假绿换的规矩）

11-07 两次事故同源：读数没带取数时点，快照错开半轮就误判——19:44 那对读数咬住
41 条 B 闸红，实为复烧轮完成前的旧快照（假红）；同日 R2 的 miss=0 是假绿（revert
收口后作废）。**凡交卷的双读数（五断言 + 独立 selfcheck），输出头部必须逐件带
`SOURCE <path> mtime=… size=… sha256=…` 存证行，无存证行的读数不算交卷。**
`fbwl_stor_gate_20261107.py`（已入仓）与 `fbwl_review_selfcheck.py` 已内置自印；
比对两份读数先比 SOURCE 行时点是否同批，再比结论。对账终稿另带 ai.srt 的
sha 前缀与 mtime（与流水线所报互钉）。

## 写库后验：非作者闸门侧新连接后验（站长 11-07 21:3x 定式，FBWL #6 首例闭环）

**今后所有写库交付（STOR）一律由代码运维在执行方落库后做闸门侧后验，作者自检
只作对照。** 姿势三条：
1. **另开新连接**（新 FTP 会话）实拉库内交付件，不复用在途连接——防旧会话缓存
   造出假绿；
2. **sha256 全值 + 字节 size + cue 数三项全对**终稿登记值才算完卷，任一不符即
   MISMATCH **列单报站长、不重试**（重试会掩盖落库姿势问题）；
3. 守望与卷面：STOR 前架轮询守望（armed 时间戳落卷自证，防被重启静默带走），
   PASS/MISMATCH 读数行带取数时刻落 `logs/` 留痕，凭据绑进对应台账条目
   （如 rounds_ledger 的 `stor_postcheck` 字段）。先例卷面：
   `logs/fbwl_land_postcheck_2026-11-07.md`（#6 FBWL @21:25:26 PASS）。

## 台账一页纸：用 ds90_ledger.py，别拿纯 append 当真值（11-07 裁定⑤ 仓级规矩）

两条合法姿势各一个原语：快照台账 `atomic_write_json()`（tmp+os.replace 全量
重写，断电不留半截）；流水台账 `append_record()`（必带键）+ 读侧
`recompute_done()` 按键取最后一条定性，`status="undone"` 撤单。
**禁止 `set(所有行)` 当 done 集。** 高危名单存量件（acgs_s05 两支 journal、
gap_scan 五支 STATE、newseed AUDIT/POOL）新改一律迁本库。
自检：`python3 tools/ds90_ledger.py`。

## emb 元话语修复写库后验：ass 版五断言（站长 11-08 四点全批，首批 emb_landing 起用）

`.ai.ass` 双行块（Dialogue 全局序号，偶=中文行/奇=EN 伴侣），无 srt 的 `i` 序号，
故五断言走 **ass 版**（区别于 FBWL 的 .srt 版）。器具两件套，只准代码运维改：

- `tools/emb_gate_leaklex_20261108.py` —— **独立泄漏词表（唯一真源·落仓固化）**。
  站长 11-08 第 1 条③：词表闸门侧自建、落仓、**全站后验以此为准，跑批中途不得换表**；
  换表＝向 version3 再提 PR 升 `LEX_VERSION`，旧读数作废重跑。版本号随每轮 round 卷面记录。
- `tools/emb_gate_postcheck_v1_20261108.py` —— 闸门侧连库后验（FTP 新连接 RETR + 本地实算
  sha，不走作者代码路径）。`GO` 前必先 `selftest` 全绿（零连库，验断言器本身：泄漏/占位/
  畸形标签/越白名单/纯标点五类注入故障必红、正常行不误伤）。

**ass 版五断言**（站长四条全批）：①Dialogue 全局序号连续 + 奇偶自证（偶=中文行）
②新中文行非空/非纯标点/占位符残留=0（限本批新写行；全卷占位数旧↔新只断不增——
非本批半件本就占位）③新中文行无元话语/思考流（走上面的落仓词表，不复用作者 leakscan）
④tag 白名单 `<i>/<b>/<u>/<font color>/</font>` + BROKEN 畸形开标签两段式解析（10-22 教训，
不与改写方共用正则）⑤去标签后全文件文字逐字相同、豁免面恰为清单本批中文行；
EN 行/时间轴/Style 头零改动。

**完卷三件套**＝sha 全值 + size + Dialogue 序号数（srt 的 cue 数断言不适用 .ass）。

**TOCTOU 三断言**（站长第 3 条 + 硬规矩）：`_Trash` 留底逐条==清单 `cur_zh`；
`journal` 改前 sha==闸门侧 `_Trash` 实拉、改后 sha==库内实拉；改动面 ⊆ 清单中文行
（以「留底按清单正向映射重建 ≡ 库内新件」字节级还原强化＝FBWL④ 定式）。
**留底对拍一旦红（区间内件被动过）＝该件即停报站长，由执行方重编该件清单——
闸门侧不改写清单内容，只判红绿。** 续批口径：10 重点疑点 + PREFIX 9 条一律必查，
每件全量旧↔新逐 cue 对拍，抽样只用于新文正确性人工复核面。

`GO` 用法：`emb_gate_postcheck_v1_20261108.py GO --batch-name <en.dotted> --journal <path>
--trash /homes/_Trash/<batch> [--only f1 f2 ...]`；`_Trash` 批次名英文点号化，
df 先核落 volume1（11-04 规矩，禁 md0）。两遍独立新连接读数须逐位一致，任何红 exit 2 停手报站长。

## inline_bilingual 特例形制（站长 11-08 特例批裁定，Spit 案）

合并双语行件（单条 Dialogue 内 `{\r中文}中文段\N{\rEnglish_N}英文段`、Style 全列单一）
天然违反「cue 偶=中文行」——**豁免生效唯一通道＝清单逐件显式声明**
`file_formats{"<file>": "inline_bilingual"}` 或 `item.format` 同值（两源自洽断言）。
**双向 fail-closed**：声明而实测不符＝红；实测符合而未声明＝红停报，绝不自动豁免。

四条形制断言（对声明件替代 ①奇偶自证，序号连续照跑）：
inline-a Style 段全文件零改动；inline-b 每条英文段逐字同（闸门侧独立两段式解析器自切，
不信任改写方切分）；inline-c 每行结构不变量（`\N`/`{\r`/override 标签集合旧↔新一致）；
inline-d 改动面 ⊆ 清单 cue 集。`new_zh_semantics="full_line"`（整行语义，cur_zh 用
`Dialogue:` 整行）随清单顶层与条目自洽断言。selftest 含 inline 六例（好例+五种破坏注入）。

## 目录列举定式（11-08 PR#17 教训固化）

群晖 FTPd 对**目录名含 `[ ]`** 的路径，绝对路径 MLSD/LIST 一律返 0 条（e1 作用域 50 目录
21 个中招）；CWD 进目录再列完全正常。器具定式：一律 `CWD` 进目录再 `MLSD ""`，空退
`LIST ""`，两路皆空即抛（fail-closed）——严禁拿空表过「目录无残留」（空表假绿教训）。
执行侧 `zz_auto_land.listdir` 早有同款定式，闸门侧自此同步。

## 清单落库前 LIST 可达性预检（站长 11-08 第 2 单，`ds90_list_preflight_20261108.py`）

扫描/读判清单曾把拼错目录（`Grey's.Anatomy`，真目录 `Greys.Anatomy`）静默写进清单，
取件才暴雷。与上节 MLSD 空表同族：**路径真实性必须对库实测，不得信生成侧**。

- 用法：`python3 ds90_list_preflight_20261108.py <清单.json|清单.txt|-> [--out 报告.json]`；
  故障注入自检 `--dry-selftest`（11 例，不连库）。
- 口径：目录 CWD 实测可达＝绿，不可达＝红并**从最深可达祖先定位断点成分**，对断点父目录
  清单给近邻候选（difflib + 撇号/空白变体，`Grey's.Anatomy→Greys.Anatomy` 直读命中）；
  文件＝父目录可达 + basename 在列；纯文本行不猜形（先目录后文件，影视目录名满点禁用
  splitext 启发）；JSON 清单信任 `dir*`/`file*` 键、`file` 可为相对 dir 文件名（landing list 定式）。
- fail-closed：任一红＝exit 2 **清单不得落库**；空表只警不红（存在性预检，空表禁过关仍归后验）；
  连接失败＝exit 3。
- 已实测：v4 写库清单 272 目录/274 文件（含 `[TGx]` 方括号件）PASS，报告
  `logs/landing_2026-11-08/preflight_v4_2026-11-08.json`。

## 样2 非中文行白名单（双闸 + 背书，站长 11-08 18:2x 批「品牌不译」形制）

`fbwl_stor_gate_20261107.py` 第 2 样拦「无汉字且无数字」的中文行（占位符/纯标点）。
但存在正当例外：品牌名、专有唤醒词等**不译**条——如 `P77.2025` 的 `Siri`（同轴英文行逐字即
`Siri`，中文行镜像英文行就是正译）。这类只能**逐条点名放行**，故加白名单，用法：

```
python3 tools/fbwl_stor_gate_20261107.py <workdir> [waive.json] --allow <nonhan_allow.json>
```

- **双闸**（`allow_hit`，两道缺一即 FAIL）：
  ① 同轴配对英文行**逐字** == `new_zh_fingerprint`（review.jsonl 的 `en`，不裁剪、不剥标签、不去空格）；
  ② 中文行**逐字** == 同一指纹，且 `(file_prefix, cue)` 精确命中——不许按件/按目录泛化。
- **背书闸**（两道都核，纵深防御）：顶层与条目 `approved_by` 必须 == `DS90站长` 且 `quote` 非空。
  交付方不得自行加条；新增只认站长原话。
- **fail-closed**：白名单里打不到任何样2命中的条目（陈旧/夹带）判 FAIL（`2白名单空转条目`）；
  缺背书的条目在装载期即丢弃并计入 `2白名单丢弃条目` 并 FAIL，不许静默忽略。
- **正反例绑 fixture**：`tools/_gate_nonhan_allow_fixtures_20261108.json`（阳性 1 / 阴性 9：
  句点差、件名差、cue 冒名、自签、空 quote、顶层非站长、空指纹、无白名单同形件）。
  `python3 tools/fbwl_stor_gate_20261107.py --selftest` 必须双 PASS 才算器具合格。
- 与 `waive.json` 分工：waive 只管第 3 样（思考流启发式人工判），白名单只管第 2 样；互不越界。
- 本件属闸门，**被闸的人不许改闸**，仅 代码运维 可改。
