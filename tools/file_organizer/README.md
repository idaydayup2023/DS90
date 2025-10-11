# File Organizer - 文件整理工具

一个智能的文件整理工具，能够按文件名将文件自动分类到对应的子目录中。

## 功能特点

- 🗂️ **智能分类**: 根据文件名（去除扩展名）自动创建目录并分类文件
- 🎬 **字幕文件支持**: 智能处理字幕文件，去除语言标识符（如 .ai, .en, .zh 等）
- 🔒 **安全操作**: 如果目标文件已存在，将跳过移动操作，避免覆盖
- 🌍 **多语言支持**: 完美支持中文文件名和特殊字符
- 📊 **详细统计**: 显示处理结果统计信息

## 使用方法

### 基本用法

```bash
# 整理当前目录
python3 file_organizer.py

# 整理指定目录
python3 file_organizer.py /path/to/files

# 显示帮助信息
python3 file_organizer.py --help
```

### 使用示例

假设有以下文件：
```
document.pdf
document.txt
document.docx
movie.mkv
movie.ai.srt
movie.en.srt
photo.jpg
photo.raw
```

运行 `python3 file_organizer.py` 后，文件将被整理为：
```
document/
├── document.pdf
├── document.txt
└── document.docx
movie/
├── movie.mkv
├── movie.ai.srt
└── movie.en.srt
photo/
├── photo.jpg
└── photo.raw
```

## 智能特性

### 字幕文件处理

工具能够智能识别字幕文件的语言标识符，确保同一电影的不同字幕文件归类到同一目录：

- `movie.ai.srt` → `movie/` 目录
- `movie.en.srt` → `movie/` 目录  
- `movie.zh.srt` → `movie/` 目录

支持的字幕标识符包括：
- 语言代码：`ai`, `en`, `zh`, `cn`, `jp`, `kr`, `fr`, `de`, `es`, `it`, `ru` 等
- 字幕类型：`gt`, `emb`, `asr`, `auto`, `forced`, `sdh`, `cc` 等
- 三字母代码：`chi`, `eng`, `jpn`, `kor`, `fre`, `ger`, `spa`, `ita`, `rus` 等
- 中文标识：`chs`, `cht`, `simplified`, `traditional` 等

### 支持的字幕格式

- `.srt` - SubRip 字幕
- `.ass` - Advanced SubStation Alpha
- `.ssa` - SubStation Alpha  
- `.vtt` - WebVTT
- `.sub` - MicroDVD/SubViewer
- `.idx` - VobSub 索引文件
- `.sup` - PGS 字幕

## 安全特性

- ✅ **权限检查**: 运行前检查目录读写权限
- ✅ **文件保护**: 不会覆盖已存在的文件
- ✅ **隐藏文件忽略**: 自动跳过以 `.` 开头的隐藏文件
- ✅ **错误处理**: 完善的错误处理和用户友好的错误信息

## 输出示例

```
开始整理文件...
创建目录: document/
移动文件: document.pdf → document/document.pdf
移动文件: document.txt → document/document.txt
创建目录: movie/
移动文件: movie.mkv → movie/movie.mkv
移动文件: movie.ai.srt → movie/movie.ai.srt

整理完成！
==========================================
总文件数: 5
已整理: 5
跳过: 0
创建目录: 2
==========================================
```

## 注意事项

1. 需要对目标目录有读写权限
2. 隐藏文件（以 `.` 开头）将被忽略
3. 如果目标文件已存在，将跳过移动操作
4. 脚本会根据文件名（去除扩展名）创建子目录
5. 支持中文文件名和特殊字符

## 系统要求

- Python 3.6+
- 支持的操作系统：Windows, macOS, Linux

## 许可证

本项目采用 MIT 许可证。