# Python compatibility boundary

V3 核心不依赖 Python，也不包含 Python 兼容层。

Whisper/Torch ASR 与部分 PGS OCR 工具目前更适合作为可选外部 worker：它们的模型、硬件加速和大型依赖不应被塞进 `subtrans` 单文件。worker 契约输入为本地媒体路径、目标 SRT 路径、语言及可选字幕流编号；成功退出时必须生成能通过严格解析和质量门的 UTF-8 SRT。启用 worker 必须固定可执行路径、版本探测参数和期望版本，`doctor` 会实际执行并核对；失败、超时、缺失输出或非法字幕都不会进入翻译或迁移。

Apple Silicon 默认推荐带 Metal 的 `whisper.cpp` 类独立程序；Python worker 只是最后兼容选项，必须作为独立、可替换进程部署，不能修改主程序环境。这不是对 Python 的隐式保留：worker 可以由 C++、Rust、现有 Python 工具或远程服务实现。删除兼容边界的条件是 Rust 原生实现能在 Apple Silicon 与目标 DSM 上达到相同识别质量、硬件利用率、模型兼容性和可复现离线部署要求。
