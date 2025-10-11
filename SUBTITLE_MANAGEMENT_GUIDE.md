# 字幕管理功能使用指南

## 概述

本媒体库管理系统现已集成完整的字幕检测、管理和AI字幕检查功能。系统可以自动检测视频文件对应的字幕文件，识别AI生成的字幕，并提供详细的统计报告。

## 功能特性

### 🔍 字幕检测功能
- **自动检测**: 扫描视频文件时自动检测对应的字幕文件
- **多格式支持**: 支持 SRT、ASS、SSA、VTT、SUB、IDX、SUP 等格式
- **智能匹配**: 基于文件名、目录结构等规则智能匹配字幕
- **语言识别**: 自动识别字幕语言（中文、英文、日文、韩文等）
- **编码检测**: 自动检测字幕文件编码格式

### 🤖 AI字幕识别
- **AI标识检测**: 自动识别AI生成的字幕文件（如 .ai.srt）
- **质量评估**: 对字幕质量进行评分
- **缺失检查**: 检查哪些视频文件缺少AI字幕

### 📊 统计分析
- **全面统计**: 提供字幕文件的详细统计信息
- **分类统计**: 按语言、格式、类型分类统计
- **覆盖率分析**: AI字幕覆盖率分析
- **详细报告**: 生成完整的字幕管理报告

## 数据库结构

### 字幕相关表

#### `subtitle_files` - 字幕文件表
存储字幕文件的详细信息：
- 文件路径、名称、大小、哈希值
- 语言、格式、编码信息
- AI生成标识和置信度
- 字幕数量和质量评分

#### `subtitle_analysis` - 字幕分析表
存储字幕内容的分析结果：
- 内容分析数据
- 置信度评分

#### `subtitle_matching_rules` - 字幕匹配规则表
定义字幕文件与视频文件的匹配规则：
- 文件名匹配规则
- 目录匹配规则
- 优先级设置

#### `subtitle_scan_history` - 字幕扫描历史表
记录字幕扫描的历史信息：
- 扫描路径和结果
- 发现的字幕数量
- 扫描耗时

## 使用方法

### 1. 应用字幕Schema

首次使用前需要应用字幕数据库Schema：

```bash
python3 apply_subtitle_schema.py
```

### 2. 字幕管理工具

使用 `subtitle_management_tool.py` 进行字幕管理：

#### 扫描媒体文件和字幕
```bash
# 扫描所有配置的路径
python3 subtitle_management_tool.py scan

# 扫描指定路径
python3 subtitle_management_tool.py scan --paths /path/to/movies /path/to/tv

# 详细输出
python3 subtitle_management_tool.py scan --verbose
```

#### 检查缺失的AI字幕
```bash
python3 subtitle_management_tool.py check
```

#### 获取字幕统计信息
```bash
python3 subtitle_management_tool.py stats
```

#### 生成详细报告
```bash
# 输出到控制台
python3 subtitle_management_tool.py report

# 保存到文件
python3 subtitle_management_tool.py report --output subtitle_report.txt
```

#### 清理孤立的字幕记录
```bash
python3 subtitle_management_tool.py cleanup
```

#### 重新扫描字幕
```bash
# 重新扫描所有媒体文件的字幕
python3 subtitle_management_tool.py rescan

# 重新扫描指定媒体文件的字幕
python3 subtitle_management_tool.py rescan --media-ids 1 2 3
```

### 3. 编程接口

#### 使用 SubtitleDetector 类

```python
from media_manager.utils.subtitle_detector import SubtitleDetector

# 创建检测器实例
detector = SubtitleDetector()

# 检测单个视频文件的字幕
video_path = "/path/to/movie.mp4"
subtitles = detector.detect_subtitles_for_video(video_path)

# 批量检测目录中的字幕
directory_path = "/path/to/movies"
all_subtitles = detector.scan_directory_for_subtitles(directory_path)

# 检查缺失的AI字幕
missing_ai_subtitles = detector.check_missing_ai_subtitles()
```

#### 使用 MediaFileScanner 类

```python
from media_manager.scanner.file_scanner import MediaFileScanner

# 创建扫描器实例（已集成字幕检测）
scanner = MediaFileScanner()

# 扫描目录（自动检测字幕）
results = scanner.scan_directory("/path/to/media")

# 获取缺失AI字幕报告
report = scanner.get_missing_ai_subtitles_report()
```

#### 使用 SubtitleManagementTool 类

```python
from subtitle_management_tool import SubtitleManagementTool

# 创建管理工具实例
tool = SubtitleManagementTool()

# 扫描媒体和字幕
results = tool.scan_media_with_subtitles(["/path/to/media"])

# 获取统计信息
stats = tool.get_subtitle_statistics()

# 生成报告
report = tool.generate_ai_subtitle_report()
```

## 字幕匹配规则

系统使用以下规则匹配字幕文件：

### 默认匹配规则（按优先级排序）

1. **AI字幕匹配** (优先级: 100)
   - 模式: `*.ai.srt`
   - 描述: AI生成的字幕文件

2. **同名字幕匹配** (优先级: 90)
   - 模式: `*`
   - 描述: 与视频文件同名的字幕

3. **中文字幕匹配** (优先级: 80)
   - 模式: `*.zh*.srt`
   - 描述: 中文字幕文件

4. **英文字幕匹配** (优先级: 70)
   - 模式: `*.en*.srt`
   - 描述: 英文字幕文件

5. **字幕目录匹配** (优先级: 60)
   - 模式: `Subs/*`
   - 描述: 字幕子目录中的文件

### 自定义匹配规则

可以通过数据库添加自定义匹配规则：

```sql
INSERT INTO subtitle_matching_rules 
(rule_name, rule_type, pattern, priority, is_enabled, description)
VALUES ('自定义规则', 'filename', '*.custom.srt', 85, 1, '自定义字幕规则');
```

## 配置选项

### 字幕相关设置

在 `settings` 表中可以配置以下选项：

- `subtitle_extensions`: 支持的字幕文件扩展名
- `subtitle_languages`: 支持的字幕语言
- `ai_subtitle_required`: 是否要求AI字幕
- `ai_subtitle_format`: AI字幕的默认格式
- `subtitle_quality_threshold`: 字幕质量评分阈值
- `subtitle_encoding_detection`: 是否启用字幕编码检测

## 示例输出

### 字幕统计示例
```
📈 字幕统计:
  总字幕文件数: 1250
  AI字幕文件数: 890
  其他字幕文件数: 360
  AI字幕覆盖率: 71.2%

🌍 按语言分布:
  中文(简体): 850 个
  English: 320 个
  日本語: 80 个

📄 按格式分布:
  SRT: 1100 个
  ASS: 120 个
  VTT: 30 个
```

### 缺失AI字幕报告示例
```
❌ 缺失AI字幕统计:
  总计缺失: 45 个文件
  电影缺失: 28 个
  电视剧缺失: 17 个

📋 缺失AI字幕的文件:
  - 复仇者联盟4：终局之战 (2019)
    文件: Avengers.Endgame.2019.2160p.BluRay.x265.mkv
  - 权力的游戏 第八季
    文件: Game.of.Thrones.S08E01.2160p.WEB.mkv
```

## 故障排除

### 常见问题

1. **字幕检测不到**
   - 检查文件名是否符合匹配规则
   - 确认字幕文件格式是否支持
   - 检查文件编码是否正确

2. **AI字幕识别错误**
   - 确认文件名包含 `.ai.` 标识
   - 检查匹配规则配置
   - 验证文件内容是否为AI生成

3. **数据库错误**
   - 确认已应用字幕Schema
   - 检查数据库连接
   - 验证表结构是否正确

### 日志调试

启用详细日志输出：

```bash
python3 subtitle_management_tool.py scan --verbose
```

## 性能优化

### 大型媒体库优化建议

1. **分批扫描**: 对于大型媒体库，建议分批扫描
2. **定期清理**: 定期清理孤立的字幕记录
3. **索引优化**: 确保数据库索引正常工作
4. **并发控制**: 避免同时运行多个扫描任务

## 更新日志

### v1.0.0 (2025-10-11)
- ✅ 实现字幕文件检测器
- ✅ 集成字幕检测到媒体扫描器
- ✅ 添加AI字幕识别功能
- ✅ 实现字幕统计和报告功能
- ✅ 创建字幕管理工具
- ✅ 添加字幕数据库Schema

## 技术支持

如有问题或建议，请查看：
- 日志文件中的错误信息
- 数据库表结构和数据
- 配置文件设置

---

**注意**: 本功能需要 Python 3.7+ 和相关依赖包。首次使用前请确保已正确安装所有依赖。