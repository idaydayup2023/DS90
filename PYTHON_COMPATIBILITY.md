# Python compatibility boundary

V3 核心不依赖 Python，也不包含 Python 兼容层。

Whisper/Torch ASR 与部分 PGS OCR 工具目前更适合作为可选外部 worker：它们的模型、硬件加速和大型依赖不应被塞进 `subtrans` 单文件。worker 契约输入为本地媒体路径、目标 SRT 路径、语言及可选字幕流编号；成功退出时必须生成能通过严格解析和质量门的 UTF-8 SRT。启用 worker 必须固定可执行路径、版本探测参数和期望版本，`doctor` 会实际执行并核对；失败、超时、缺失输出或非法字幕都不会进入翻译或迁移。

Apple Silicon 默认推荐带 Metal 的 `whisper.cpp` 类独立程序；Python worker 只是最后兼容选项，必须作为独立、可替换进程部署，不能修改主程序环境。这不是对 Python 的隐式保留：worker 可以由 C++、Rust、现有 Python 工具或远程服务实现。删除兼容边界的条件是 Rust 原生实现能在 Apple Silicon 与目标 DSM 上达到相同识别质量、硬件利用率、模型兼容性和可复现离线部署要求。

当内外英文字幕都不存在时，ASR 不再是可跳过的建议，而是该视频的必需来源。应在部署阶段手工安装 worker 和模型，并在配置中固定绝对命令、参数与版本；`subtrans doctor --config <CONFIG>` 会在处理媒体前核对可执行文件和版本。若命令不存在、Python 报 `ModuleNotFoundError`、模型缺失或输出不是有效 SRT，命令行会保留原始 stderr，并提示 Homebrew、虚拟环境/`python3 -m pip install <PACKAGE>`、模型和配置检查步骤；主程序不会自行联网安装。
