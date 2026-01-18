# dir_migrate 项目对话记录（回顾用）

说明：本文件整理自本次会话中与 “目录迁移工具（dir_migrate）” 相关的“你的提问 + 我的结论性回答/交付结果”。省略了中间的工具输出与重复确认，仅保留关键决策、规则、产物与可运行入口。

---

## 1) 你：写另一个 PRD（目录迁移工具）

你提出的关键需求摘要：

- 工具用途：将指定目录（通常是 FTP 的 `/Downloads`）下的视频与字幕文件，按规则规范化命名并迁移到另一个目录
- 文件名格式化（核心）：用 LLM 识别并输出“规范化文件名字段”，字段用 `.` 分割
  - 默认：目录名与文件名一致（即落在同名目录下）
- 电视剧集规则：
  - 目录名中必须包含季信息 `Sxx`
  - 对衍生剧做归并（例：`NCIS`、`NCIS: Miami`），最好统一归类到主系列目录：`NCIS`
- 目录归档规则：
  - 1080p 电影 → `/X-Movie/<YearBucket>/...`
    - `2024` 及以后：按年份分目录（`2024/`、`2025/`）
    - `2024` 之前：按年代每 10 年一个目录（`1990s/`、`2000s/`）
  - 4K/2160p 电影 → `/MOVIE/<DecadeBucket>/...`（始终按年代）
  - 1080p 剧集 → `/X-TV/<Series>/...`（片名空格用 `.`）
  - 4K 剧集 → `/TV/<Series>/...`（规则同 1080p）

我交付的结论/产物：

- 已编写 PRD 文档：[dir_migrate.PRD](file:///Users/daibo/DS90v2/dir_migrate.PRD)
  - 包含：LLM 输出 JSON 约束、规范化命名模板、归档目录规则、冲突/幂等/回滚策略、配置与 CLI 建议、验收标准、风险与增强项

---

## 2) 你：开始编程

我交付的结论/产物（MVP 可运行）：

- 已实现目录迁移工具（支持 FTP/本地两种存储，dry-run 输出迁移计划，apply 执行迁移，支持冲突策略）
  - 入口脚本：[dir_migrate.py](file:///Users/daibo/DS90v2/dir_migrate.py)
  - 示例配置（统一配置文件，含 `dir_migrate` 节）：[config.example.json](file:///Users/daibo/DS90v2/config.example.json)
  - 包实现：[src/dir_migrate](file:///Users/daibo/DS90v2/src/dir_migrate)
  - 单元测试：`python3 -m unittest discover -v`
- 运行方式：
  - dry-run：`python3 dir_migrate.py --config config.json --once --dry-run`
  - apply：`python3 dir_migrate.py --config config.json --once --apply`

当时的限制（MVP）：

- 仅支持同存储类型迁移：local→local 或 ftp→ftp
- ftp→ftp 需要同一 host/port/username（跨主机/跨账号复制迁移不在本期）

---

## 3) 你：整个框架要参考 srt_translate 的 agent / mcp 架构来做

我交付的结论/产物（架构重构完成）：

- 已将 dir_migrate 重构为与 srt_translate 一致的分层：
  - Orchestrator：统一编排扫描/规划/执行与并发调度  
    - [src/dir_migrate/orchestrator.py](file:///Users/daibo/DS90v2/src/dir_migrate/orchestrator.py)
  - Agents：拆为 Scanner / Planner / Executor  
    - [src/dir_migrate/agents/scanner.py](file:///Users/daibo/DS90v2/src/dir_migrate/agents/scanner.py)  
    - [src/dir_migrate/agents/planner.py](file:///Users/daibo/DS90v2/src/dir_migrate/agents/planner.py)  
    - [src/dir_migrate/agents/executor.py](file:///Users/daibo/DS90v2/src/dir_migrate/agents/executor.py)
  - MCP：外部能力抽象（存储/LLM），Orchestrator/Agents 只依赖 MCP  
    - 存储 MCP：[src/dir_migrate/mcp/storage.py](file:///Users/daibo/DS90v2/src/dir_migrate/mcp/storage.py)  
    - LLM MCP：[src/dir_migrate/mcp/llm.py](file:///Users/daibo/DS90v2/src/dir_migrate/mcp/llm.py)
- 并保持可观测与可控：
  - dry-run 输出计划（JSON line）
  - apply 支持冲突策略：skip / suffix / overwrite
  - CLI 增强：非 Ctrl-C 的异常返回码 2，Ctrl-C 返回码 130
- 测试已通过：`python3 -m unittest discover -v`

---

## 4) 约定与注意事项（实践结论）

- 示例配置 `config.example.json` 里的 FTP 地址是占位符（`127.0.0.1`），使用前需替换为真实 FTP 信息
- 在统一 `config.json` 中，dir_migrate 默认复用顶层 `ftp/ollama/video/paths`，只需在 `dir_migrate` 节配置源/目标 root_path 与规则即可
- 文件名规范化是高风险动作，建议默认 `dry_run=true`，先抽样校验迁移计划再 `--apply`
