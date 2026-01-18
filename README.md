# srt_translate

面向“FTP 视频库”的自动字幕翻译工具：扫描 FTP 指定目录的视频文件，获取英文源字幕（优先 `.emb.srt` / 外置字幕 / 内置提取，兜底 Whisper ASR），调用本地 Ollama 模型翻译，生成与视频同目录的 `*.ai.srt`（中文在上、英文在下）。

## 特性

- FTP 递归扫描：默认从 `/Downloads`（可配置）遍历视频文件
- 源字幕获取策略：
  - 命中同目录 `basename.emb.srt` 直接使用
  - 外置字幕：`basename.srt` / `basename.en.srt` / `basename.*.srt` 多候选择优
  - 内置字幕：ffprobe/ffmpeg 探测并提取英文文本轨，写回 `basename.emb.srt`
  - 兜底 ASR：Whisper 生成 `basename.asr.srt`，并进入翻译队列
- 翻译输出：
  - 生成 `basename.ai.srt`
  - 每条字幕两行：中文在上、英文在下（中英文之间换行）
  - 批量翻译 + 严格 1:1 对齐校验；失败自动回退逐条翻译
- 并行与不中断：
  - ASR 与翻译走不同 worker 池，ASR 再慢也不会阻塞翻译吞吐
  - Ctrl-C 可快速退出（返回码 130）

## 目录与文档

- 需求与规范： [srt_translate.PRD](file:///Users/daibo/DS90v2/srt_translate.PRD)
- 目录迁移工具 PRD： [dir_migrate.PRD](file:///Users/daibo/DS90v2/dir_migrate.PRD)
- 对话记录（过程回顾）：[srt_translate.conversation.md](file:///Users/daibo/DS90v2/srt_translate.conversation.md)
- Trae Skills（架构/提示词/MCP 契约）：
  - [.trae/skills/srt-translate-architecture/SKILL.md](file:///Users/daibo/DS90v2/.trae/skills/srt-translate-architecture/SKILL.md)
  - [.trae/skills/srt-translate-prompts/SKILL.md](file:///Users/daibo/DS90v2/.trae/skills/srt-translate-prompts/SKILL.md)
  - [.trae/skills/srt-translate-mcp-contracts/SKILL.md](file:///Users/daibo/DS90v2/.trae/skills/srt-translate-mcp-contracts/SKILL.md)

## 运行环境

- macOS / Linux
- Python 3.11+（示例使用 `python3`）
- FTP 服务器：支持 `MLSD` 更佳（无 `MLSD` 时会降级为目录/文件猜测）
- Ollama：本地服务可访问（默认 `http://localhost:11434`）
- ffprobe/ffmpeg：用于内置字幕探测与提取
- whisper CLI：用于 ASR 兜底（可配置关闭）

## 快速开始

### 1) 准备配置

复制示例配置并修改：

```bash
cp config.example.json config.json
```

关键字段：

- `ftp.host / ftp.port / ftp.username / ftp.password`
- `ftp.root_path`：要扫描的根目录（例如 `/downloads_1`）
- `ollama.base_url`：例如 `http://localhost:11434`
- `ollama.model`：建议填你本机存在的模型名（如 `translategemma:latest`）

### 2) 先跑 dry-run（不写回）

```bash
python3 srt_translate.py --config config.json --once --dry-run
```

你会在日志看到类似：

- `translate start ... cues=...`
- `translate progress x/y`
- `run_once summary ... done=... failed=...`

### 3) 正式写回生成字幕

```bash
python3 srt_translate.py --config config.json --once
```

如果你希望强制重译（即使远端已存在 `.ai.srt`）：

```bash
python3 srt_translate.py --config config.json --once --force
```

## 输出文件约定

对视频 `.../basename.mkv`，同目录可能出现：

- `basename.emb.srt`：内置字幕提取产物（英文源字幕）
- `basename.asr.srt`：Whisper ASR 产物（英文源字幕兜底）
- `basename.ai.srt`：最终输出（中文在上、英文在下）

## 开发与测试

单元测试：

```bash
python3 -m unittest discover -v
```

本地翻译冒烟（不走 FTP，只翻译本地 srt）：

```bash
python3 demo_translate_local_srt.py --config config.json --in input.srt --out output.ai.srt
```

## 目录迁移工具（dir_migrate）

用于将源目录（常为 FTP `/Downloads`）下的视频与字幕按 LLM 识别结果规范化命名，并按分辨率/电影或剧集/年份分桶规则迁移到目标目录。

- 统一配置：复用同一个 `config.json`（在 `dir_migrate` 节配置源/目标目录与规则），示例见 [config.example.json](file:///Users/daibo/DS90v2/config.example.json)
- dry-run（输出迁移计划 JSON 行，不移动文件）：

```bash
python3 dir_migrate.py --config config.json --once --dry-run
```

- apply（执行移动/重命名）：

```bash
python3 dir_migrate.py --config config.json --once --apply
```

## 常见问题

### 1) FTP 报 530 Login incorrect

说明账号/密码错误或权限不足；确认 `config.json` 的 FTP 账户信息与目录权限。

### 2) Ollama 报 model not found

确认模型确实已安装：`curl http://localhost:11434/api/tags`。把 `ollama.model` 改为返回列表中的某个 `name`（例如 `translategemma:latest`）。

### 3) 翻译很慢

电影字幕条目通常上千条，且翻译会按 batch 分段请求模型。可调整：

- `translation.batch_size`
- `translation.workers`（提高并发，但会增加 Ollama 压力）

## 安全提示

- 不要把包含真实 FTP 密码的 `config.json` 提交到版本库
- 避免在日志中输出敏感字段（本项目目前不打印密码）
