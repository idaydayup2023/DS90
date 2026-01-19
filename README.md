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

## 运行环境与依赖

### 1. 基础环境
*   **操作系统**: macOS / Linux (推荐), Windows (理论支持但未验证)
*   **Python**: >= 3.11 (本项目完全使用标准库开发，无第三方 pip 依赖)

### 2. 外部程序依赖
本项目依赖以下外部工具，请确保它们在系统 `PATH` 中可用：

*   **ffmpeg / ffprobe**: 用于提取视频内置字幕和探测视频信息。
    *   *安装示例 (macOS)*: `brew install ffmpeg`
    *   *安装示例 (Ubuntu)*: `sudo apt install ffmpeg`
*   **ollama**: 用于运行 LLM 进行字幕翻译和文件名解析。
    *   *官网*: https://ollama.com/
    *   *服务*: 需启动服务 (`ollama serve`) 并确保 API 端口 (默认 11434) 可访问。
*   **whisper** (可选): OpenAI 的语音转文字工具，用于无字幕视频的兜底 ASR。
    *   *安装*: `pip install -U openai-whisper`
    *   *注意*: 如果未安装，ASR 兜底功能将不可用，但不影响其他功能。

### 3. 模型准备
请在 Ollama 中拉取适合的模型：
*   **翻译模型**: 推荐 `gemma:2b` 或专门微调过的 `translategemma`。
    ```bash
    ollama pull gemma:2b
    ```

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

## 命令详解

### 1. 字幕翻译工具 (`srt_translate.py`)

核心工具，负责扫描 FTP、提取字幕、调用 LLM 翻译并回传。

**基本用法**

```bash
python3 srt_translate.py --config <CONFIG_PATH> [OPTIONS]
```

**参数说明**

| 参数 | 必选 | 说明 |
| :--- | :--- | :--- |
| `--config CONFIG` | **是** | 指定配置文件路径（如 `config.json`）。 |
| `--once` | 否 | **单次运行模式**。扫描一遍目录队列后即退出。如果不加此参数（且未实现守护进程模式前），行为可能未定义或默认为单次，但建议显式加上。 |
| `--dry-run` | 否 | **空跑模式**。执行完整的扫描、提取、翻译流程，但**不上传/写入**生成的 `.ai.srt` 文件。用于验证配置和翻译质量，而不污染线上文件。 |
| `--force` | 否 | **强制覆盖**。默认情况下，如果目标目录已存在 `.ai.srt` 文件，会跳过翻译。加上此参数将强制重新翻译并覆盖原有字幕。 |

**使用示例**

*   **测试配置与翻译效果（安全模式）**：
    ```bash
    python3 srt_translate.py --config config.json --once --dry-run
    ```
*   **生产环境运行（自动跳过已翻译文件）**：
    ```bash
    python3 srt_translate.py --config config.json --once
    ```
*   **修复/重译特定批次（强制覆盖）**：
    ```bash
    python3 srt_translate.py --config config.json --once --force
    ```

### 2. 目录迁移工具 (`dir_migrate.py`)

辅助工具，用于整理下载目录，识别影视信息并按规则迁移到标准库。

**基本用法**

```bash
python3 dir_migrate.py --config <CONFIG_PATH> [OPTIONS]
```

**参数说明**

| 参数 | 必选 | 说明 |
| :--- | :--- | :--- |
| `--config CONFIG` | **是** | 指定配置文件路径。复用 `srt_translate` 的配置文件，读取其中的 `dir_migrate` 字段。 |
| `--once` | 否 | **单次运行模式**。执行一次扫描和迁移计划后退出。 |
| `--dry-run` | 否 | **计划预览模式**。扫描并计算迁移计划，以 JSON Lines 格式打印到控制台，但**绝不移动**任何文件。强烈建议在正式执行前使用。 |
| `--apply` | 否 | **执行模式**。只有显式指定此参数，工具才会真正执行文件移动/重命名操作。 |
| `--limit LIMIT` | 否 | **数量限制**。限制单次处理的视频数量（整数）。用于小规模验证规则是否正确。 |

**使用示例**

*   **预览迁移计划（不执行移动）**：
    ```bash
    python3 dir_migrate.py --config config.json --once --dry-run
    ```
    *输出示例：* `{"src": "/dl/movie.mkv", "dst": "/movies/Movie (2024)/Movie.mkv", "reason": "match"}`

*   **小规模验证（只处理前 5 个视频）**：
    ```bash
    python3 dir_migrate.py --config config.json --once --apply --limit 5
    ```

*   **正式执行全量迁移**：
    ```bash
    python3 dir_migrate.py --config config.json --once --apply
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
