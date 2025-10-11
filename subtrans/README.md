# SubTrans 2.10.0 项目文档

## 📋 项目概述

SubTrans  是一个功能强大的智能字幕处理和翻译系统，支持多种字幕格式的转换、翻译、质量评估和批量处理。项目采用模块化架构设计，集成了 Whisper 语音识别、Ollama 大语言模型翻译、人名一致性管理、GPU 加速等先进技术。新版本增加了性能优化、可执行文件编译支持，以及完善的错误处理机制。

## 🚀 核心功能

### 字幕处理
- **多格式支持**: SRT、ASS/SSA、VTT、JSON 格式的读取、转换和保存
- **智能转录**: 集成 Whisper 模型进行音频转文字
- **批量处理**: 支持本地目录和 FTP 远程目录的批量处理
- **质量评估**: 自动评估字幕质量并生成详细报告

### 翻译引擎
- **AI 翻译**: 基于 Ollama 大语言模型的高质量翻译
- **上下文分析**: 智能分析电影/剧集上下文，提升翻译准确性
- **术语管理**: 自动学习和应用专业术语，保持翻译一致性
- **人名一致性**: 智能识别和统一人名翻译

### 高级特性
- **并行处理**: 多线程并行处理，提升处理效率
- **GPU 加速**: 支持 CUDA、MPS (Apple Silicon) 和 CPU 自动选择
- **性能优化**: 智能设备选择、内存管理和处理速度优化
- **网络功能**: 支持 FTP 远程处理和 OpenSubtitles 字幕下载
- **IMDB 集成**: 自动获取影片信息，增强翻译上下文
- **调试模式**: 详细的日志输出和调试信息
- **可执行文件**: 支持编译为独立可执行文件，无需 Python 环境

## 🏗️ 项目架构

### 核心组件

#### 1. 字幕处理器 (SubtitleProcessor)
- **功能**: 统一的字幕处理入口
- **特性**: 支持单文件、批量处理、FTP 远程处理
- **流程**: 文件检测 → 转录/翻译 → 格式转换 → 质量评估 → 输出

#### 2. 翻译引擎 (TranslationEngine)
- **功能**: 基于 Ollama 的智能翻译
- **特性**: 上下文感知、术语一致性、人名处理
- **优化**: 批量翻译、错误重试、结果缓存

#### 3. 格式转换器 (FormatConverter)
- **功能**: 多种字幕格式的转换
- **支持**: SRT ↔ ASS ↔ VTT ↔ JSON
- **特性**: 时间轴调整、字幕合并、语言分离

#### 4. 术语管理器 (TerminologyManager)
- **功能**: 智能术语学习和应用
- **特性**: 自动提取、分类管理、一致性应用
- **存储**: JSON 格式持久化存储

## 🛠️ 技术栈

- **语言**: Python 3.13+
- **AI 模型**: 
  - Whisper (语音识别) - 支持 GPU 加速
  - Ollama (大语言模型翻译)
- **主要依赖**:
  - `openai-whisper` - 语音识别引擎
  - `torch` - PyTorch 深度学习框架
  - `requests` - HTTP 请求
  - `pysubs2` - 字幕处理
  - `langdetect` - 语言检测
  - `pytest` - 测试框架
  - `pyinstaller` - 可执行文件编译
- **GPU 支持**:
  - NVIDIA CUDA (Windows/Linux)
  - Apple Metal Performance Shaders (macOS)
  - 自动设备检测和优化

## 📖 使用说明

### 基本用法

#### 使用 Python 脚本
```bash
# 处理单个文件
python main.py input.mkv

# 批量处理目录
python main.py /path/to/videos --batch

# 启用调试模式
python main.py input.mkv --debug

# FTP 远程处理
python main.py ftp://user:pass@server/path --ftp
```

#### 使用编译后的可执行文件
```bash
# 处理单个文件
./subtrans input.mkv

# 批量处理目录
./subtrans /path/to/videos --batch

# 查看版本信息
./subtrans --version

# 查看配置信息
./subtrans --config-info
```

### 配置选项

```bash
# 查看当前配置
python main.py --config-info

# 设置 Ollama 模型
python main.py input.mkv --model llama3

# 设置输出目录
python main.py input.mkv --output-dir /path/to/output

# GPU 和性能配置
python main.py input.mkv --device cuda    # 强制使用 CUDA
python main.py input.mkv --device mps     # 强制使用 Apple MPS
python main.py input.mkv --device cpu     # 强制使用 CPU
python main.py input.mkv --device auto    # 自动选择最佳设备

# Whisper 模型配置
python main.py input.mkv --whisper-model tiny     # 最快速度
python main.py input.mkv --whisper-model base     # 平衡质量和速度（推荐）
python main.py input.mkv --whisper-model medium   # 更高质量
python main.py input.mkv --whisper-model large    # 最高质量
```

### 高级功能

```bash
# 强制音频提取
python main.py input.mkv --force-audio

# 禁用 OpenSubtitles
python main.py input.mkv --disable-opensubtitles

# 保留临时文件
python main.py input.mkv --prevent-cleanup

# 性能测试和基准测试
python performance_benchmark.py          # 完整性能基准测试
python quick_performance_test.py         # 快速性能测试
python test_gpu_acceleration.py          # GPU 加速测试
python whisper_performance_test.py       # Whisper 性能测试
```

## 🔧 配置文件

### 主要配置项

```python
class SubTransConfig:
    # Ollama 配置
    OLLAMA_URL = "http://localhost:11434"
    OLLAMA_MODEL = "gemma3"
    OLLAMA_TIMEOUT = 120
    
    # 翻译配置
    TARGET_LANGUAGE = "Chinese"
    BATCH_SIZE = 20
    TRANSLATION_TIMEOUT = 30
    TRANSLATION_RETRIES = 2
    
    # Whisper 配置
    WHISPER_MODEL = "base"
    WHISPER_LANGUAGE = "auto"
    WHISPER_DEVICE = "auto"  # auto, cuda, mps, cpu
    WHISPER_USE_GPU = True
    WHISPER_FP16 = True
    
    # ASR 参数配置
    ASR_MAX_CHARS_PER_CUE = 40
    ASR_MAX_DURATION = 3.0
    ASR_MIN_DURATION = 0.8
    ASR_MERGE_MAX_GAP = 0.35
    ASR_WORD_PAUSE_SPLIT = 0.45
    
    # 功能开关
    DISABLE_OPENSUBTITLES = False
    FORCE_AUDIO_EXTRACTION = False
    PREVENT_CLEANUP = False
    PRESERVE_ORIGINAL_ENGLISH = True
    DEBUG_MODE = False
```

## 🔄 处理流程

### 本地目录和FTP目录处理流程

1. **视频文件检测**: 扫描目录下的视频文件
2. **已处理检查**: 检查是否存在 `.ai.srt` 翻译文件，如有则跳过
3. **英文字幕查找**: 查找 `.en.srt` 或 `.srt` 英文字幕文件
4. **视频下载**: 如无英文字幕，下载视频文件准备提取
5. **内嵌字幕评估**: 分析视频内嵌字幕，选择最佳英文字幕
6. **音轨转录**: 如无内嵌字幕，提取音轨进行 Whisper 转录
7. **递归处理**: 递归处理所有子目录

### 视频字幕提取流程

1. **内嵌字幕分析**: 检测视频中的多个英文字幕轨道
2. **最佳字幕提取**: 评估并提取最佳英文字幕，保存为 `.emb.srt`
3. **音轨转录**: 无内嵌字幕时，转录音轨保存为 `.asr.srt`
4. **翻译处理**: 将提取的字幕文件进行翻译
5. **输出保存**: 翻译结果保存为 `.ai.srt` 文件

## 🧪 测试

### 运行测试

```bash
# 运行所有测试
python tests/run_tests.py

# 运行特定测试
pytest tests/unit/test_config.py -v
pytest tests/integration/ -v
pytest tests/performance/ -v
```

### 测试覆盖

- **单元测试**: 核心组件功能测试
- **集成测试**: 组件间协作测试
- **功能测试**: 端到端功能验证
- **性能测试**: 大数据量处理性能

## 🔨 编译和部署

### 编译可执行文件

```bash
# 安装编译依赖
pip install pyinstaller

# 编译可执行文件
pyinstaller subtrans.spec

# 编译后的文件位于 dist/ 目录
ls -la dist/subtrans
```

### 打包分发

```bash
# 使用打包脚本创建分发包
./package_executable.sh

# 或使用 Makefile
make build
```

### 系统要求

- **macOS**: macOS 10.15+ (支持 Apple Silicon 和 Intel)
- **Windows**: Windows 10+ (64-bit)
- **Linux**: Ubuntu 18.04+ 或其他现代 Linux 发行版
- **内存**: 建议 8GB+ RAM
- **存储**: 至少 2GB 可用空间
- **GPU**: 可选，支持 NVIDIA CUDA 或 Apple MPS

## 📊 性能指标

- **代码规模**: 8,000+ 行 (核心代码 7,500+ 行)
- **模块数量**: 30+ 个文件
- **测试覆盖**: 15+ 个测试和性能测试文件
- **并发处理**: 支持多线程并行和 GPU 加速
- **处理速度**: 
  - CPU: 1000 条字幕 < 10 秒
  - GPU (CUDA/MPS): 1000 条字幕 < 5 秒
  - 音频转录: 1 小时音频 < 5 分钟 (GPU)
- **可执行文件**: 单文件 ~130MB，无需 Python 环境

## 🔍 调试和日志

### 日志级别
- **INFO**: 基本处理信息
- **DEBUG**: 详细调试信息
- **ERROR**: 错误信息
- **WARNING**: 警告信息

### 调试模式
```bash
# 启用调试模式
python main.py input.mkv --debug

# 或修改配置文件
DEBUG_MODE = True
```

## 🚀 未来规划

### 计划功能
- [ ] 支持更多字幕格式 (SUB, IDX)
- [ ] 集成更多翻译引擎 (OpenAI, Claude)
- [ ] Web 界面支持
- [ ] 实时字幕处理
- [ ] 云端部署支持
- [ ] 多语言界面支持

### 性能优化
- [x] GPU 加速支持 (已完成)
- [ ] 分布式处理
- [x] 缓存机制优化 (已完成)
- [x] 内存使用优化 (已完成)
- [ ] 模型量化支持
- [ ] 流式处理优化

## 📝 更新日志

### v2.10.0 (2025-09-29)
- ✅ 新增 LM Studio 框架支持和集成
- ✅ 实现多框架性能和质量对比测试
- ✅ 优化模型选择器支持 Gemma 模型系列
- ✅ 添加自动化测试用例集 (55个测试场景)
- ✅ 实现综合对比报告生成系统
- ✅ 增强多服务配置和错误处理机制

### v2.9.0 (2025-09-26)
- ✅ 添加 GPU 加速支持 (CUDA, MPS, CPU 自动选择)
- ✅ 实现可执行文件编译 (PyInstaller)
- ✅ 完善错误处理和类型安全
- ✅ 添加性能测试和基准测试工具
- ✅ 优化 Whisper 模型配置和参数
- ✅ 增强配置管理和设备检测
- ✅ 添加依赖包版本检查和报告
- ✅ 完善文档和使用指南

### v2.0 (2025-08-15)
- ✅ 完整重构项目架构
- ✅ 集成 Ollama 翻译引擎
- ✅ 添加人名一致性管理
- ✅ 实现并行处理支持
- ✅ 完善测试覆盖
- ✅ 优化性能和稳定性

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 运行测试
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

---

**SubTrans 2.10.0** - 让字幕处理更智能、更高效、更快速！

🚀 **新特性**: LM Studio 支持 | 多框架对比 | 质量评估 | 自动化测试
** 开发提示词记录

校验本地目录和FTP目录的处理，要求的处理方法是：
    1）找到目录下的视频文件，
    2）查找是否已存在本程序生成的字幕.ai.srt, 如有则跳过这个视频，继续下一个视频 
    3）如果没有已翻译的字幕，查找是否存在英文字幕，扩展名可能是.en.srt或.srt，如有则下载英文字幕后进行翻译，
    4）如果没有英文字幕，则下载视频文件，准备视频提取，
    5）如果下载的视频中包含了英文字幕，则评估视频中可能的多个英文字幕，提取最佳的英文字幕进行翻译，
    6）如果视频没有内嵌字幕，则提取音轨，通过音轨识别字幕并进行翻译。
    7）递归目标目录下所有子目录，重复以上步骤。

视频字幕提取的相应处理过程，
    1）视频下载后，分析内嵌字幕是否包括多个英文字幕，如有多个英文字幕，评估最佳字幕。
    2）提取视频内最佳英文字幕版本，保存在视频同目录下，文件名为视频文件名.emb.srt。
    3）如果没有内置字幕，则进入音轨转录，转录英文字幕文件名为视频文件名.asr.srt，保存在视频同目录下。
    4）然后继续现有字幕翻译流程，
    5）将视频文件名.emb.srt或视频文件名.asr.srt作为输入，翻译后的字幕文件名为视频文件名.ai.srt，保存在视频同目录下。
