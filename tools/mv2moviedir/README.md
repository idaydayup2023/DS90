# mv2moviedir

一个用于将电影文件移动到按电影名组织的目录结构中的 Python 脚本。

## 版本

v1.0.0

## 功能特性

- **电影文件识别**: 自动识别电影文件（排除电视剧文件）
- **智能分类**: 从文件名中提取电影名称、年份、分辨率和编码信息
- **目录结构**: 按电影名创建标准化的目录结构
- **字幕对齐**: 自动移动对应的字幕文件到相同目录
- **AI字幕检查**: 默认只处理有 `.ai.srt` 字幕的电影文件
- **中文广告去除**: 自动识别并去除文件名和目录名中的中文广告内容
- **高级过滤**: 支持按分辨率、编码过滤文件
- **年份分组**: 可选择按年份创建子目录
- **源目录清理**: 智能删除空的源子目录和垃圾文件
- **安全特性**: 两阶段处理、失败回滚、详细日志记录
- **预览模式**: 支持干运行模式，预览操作而不实际执行
- **用户确认**: 可选的删除确认功能，提高安全性

## 安装要求

- Python 3.6+
- 无需额外依赖包

## 使用方法

### 基本用法

```bash
python3 mv2moviedir.py 源目录 目标目录
```

### 命令行选项

```bash
usage: mv2moviedir.py [-h] [--resolution RESOLUTION] [--codec CODEC] [--year-group] [--remove-source]
                      [--force] [--no-override] [--dry-run] [--confirm-delete] [--version]
                      source_dir target_dir

将电影文件移动到按电影名组织的目录结构中

positional arguments:
  source_dir            源目录
  target_dir            目标目录

options:
  -h, --help            show this help message and exit
  --resolution RESOLUTION
                        只处理指定分辨率的文件 (例如: 1080p, 720p, 4K)
  --codec CODEC         只处理指定编码的文件 (例如: x265, x264, H.264)
  --year-group          按年份分组电影 (创建年份子目录)
  --remove-source       移动文件后删除源目录（如果源目录为空或只剩下nfo、txt、jpg等文件）
  --force               强制处理所有视频文件，忽略AI字幕检查（默认只处理有AI字幕的文件）
  --no-override         不覆盖已存在的目标文件（默认覆盖已存在的文件）
  --dry-run             预览模式：只显示将要执行的操作，不实际移动或删除文件
  --confirm-delete      删除目录前需要用户确认（与--remove-source一起使用）
  --version             show program's version number and exit
```

### 使用示例

#### 1. 基本整理
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized
```

#### 2. 只处理1080p电影
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized --resolution 1080p
```

#### 3. 只处理x265编码的电影
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized --codec x265
```

#### 4. 按年份分组
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized --year-group
```

#### 5. 强制处理所有电影（忽略AI字幕检查）
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized --force
```

#### 6. 处理后删除源目录
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized --remove-source
```

#### 7. 预览模式（不实际执行操作）
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized --remove-source --dry-run
```

#### 8. 删除前需要确认
```bash
python3 mv2moviedir.py /path/to/movies /path/to/organized --remove-source --confirm-delete
```

#### 9. 组合使用：预览 + 确认删除
```bash
# 先预览操作
python3 mv2moviedir.py /path/to/movies /path/to/organized --remove-source --dry-run

# 确认无误后实际执行
python3 mv2moviedir.py /path/to/movies /path/to/organized --remove-source --confirm-delete
```

## 支持的文件格式

### 视频文件
- `.mkv`, `.mp4`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`

### 字幕文件
- `.srt`, `.ai.srt`, `.en.srt`, `.zh.srt`, `.ass`, `.ssa`, `.vtt`, `.sub`

## 电影文件命名格式

脚本支持以下电影文件命名格式：

- `Movie.Name.2019.1080p.BluRay.x265-GROUP.mkv`
- `Movie Name (2019) 1080p BluRay x265.mp4`
- `Movie.Name.2019.4K.UHD.BluRay.x265.HDR-GROUP.mkv`
- `Movie.Name.2019.720p.WEBRip.x264-GROUP.avi`

**注意**: 脚本会自动排除包含 `SxxExx` 格式的电视剧文件。

## 智能文件重命名功能

脚本具备智能的文件重命名功能，能够自动清理文件名和目录名中的广告内容，确保目标文件名干净整洁。

### 文件重命名特性

- **目录名清理**: 创建的目标目录名会自动去除广告内容
- **文件名清理**: 移动到目标目录的文件名也会自动清理
- **双重处理**: 目录名和文件名都经过相同的清理逻辑
- **保持一致**: 确保目录名和文件名的命名风格统一

### 支持的广告模式

脚本能够识别并去除以下类型的中文广告：

1. **网站域名**: `www.example.com`、`example.net` 等
2. **下载站点**: `下载站`、`电影下载` 等
3. **广告标识**: `广告`、`推广` 等
4. **特殊符号**: `【】`、`[]`、`()` 包围的广告内容
5. **数字序列**: 连续的数字串（如 `123456`）
6. **混合模式**: 包含中英文混合的广告内容

### 处理示例

#### 处理前
```
Bluff.2022.1080p.WEBRip.x264.AAC-[YTS.MX].mp4
Avatar.2009.1080p.BluRay.x264-(YIFY).mkv
阿凡达2：水之道.2022.1080p.BluRay.x265-【www.example.com】.mkv
蜘蛛侠：英雄无归.2021.4K.UHD.BluRay.x265.HDR-[电影下载站].mkv
```

#### 处理后
```
目录名: Bluff.2022.1080p.WEBRip.x264.AAC-YTS.MX/
文件名: Bluff.2022.1080p.WEBRip.x264.AAC-YTS.MX.mp4

目录名: Avatar.2009.1080p.BluRay.x264-.YIFY/
文件名: Avatar.2009.1080p.BluRay.x264-.YIFY.mkv

目录名: 阿凡达2：水之道.2022/
文件名: 阿凡达2：水之道.2022.1080p.BluRay.x265.mkv

目录名: 蜘蛛侠：英雄无归.2021/
文件名: 蜘蛛侠：英雄无归.2021.4K.UHD.BluRay.x265.HDR.mkv
```

#### 清理效果说明
- `[YTS.MX]` → `YTS.MX` (去除方括号)
- `(YIFY)` → `.YIFY` (去除圆括号，转换为点号分隔)
- `【www.example.com】` → 完全去除
- `[电影下载站]` → 完全去除

### 技术特点

- **智能识别**: 使用正则表达式精确匹配各种广告模式
- **保留核心**: 只去除广告内容，保留电影名称、年份、分辨率等核心信息
- **统一处理**: 目录名和文件名使用相同的清理逻辑，确保命名一致性
- **实时重命名**: 文件移动时自动清理文件名，无需额外步骤
- **日志记录**: 详细记录文件名清理过程，便于跟踪变更
- **安全清理**: 避免误删重要的电影信息

## AI字幕检查

默认情况下，脚本只处理存在对应 `.ai.srt` 字幕文件的电影：

- ✅ `Movie.2019.1080p.mkv` + `Movie.2019.1080p.ai.srt` → 会被处理
- ❌ `Movie.2019.1080p.mkv` (无 `.ai.srt`) → 会被跳过

使用 `--force` 选项可以忽略此检查，处理所有电影文件。

## 字幕文件对齐

脚本采用两阶段处理确保字幕文件正确对齐：

1. **第一阶段**: 移动视频文件到目标目录
2. **第二阶段**: 移动对应的字幕文件

### 支持的字幕类型
- `.ai.srt` - AI生成字幕
- `.en.srt` - 英文字幕
- `.zh.srt` - 中文字幕
- `.srt` - 通用字幕
- `.ass`, `.ssa`, `.vtt`, `.sub` - 其他格式

### 字幕匹配规则
字幕文件通过文件名前缀匹配对应的视频文件：
- `Movie.2019.1080p.mkv` ↔ `Movie.2019.1080p.ai.srt`
- `Movie.2019.1080p.mkv` ↔ `Movie.2019.1080p.en.srt`

## 生成的目录结构

### 默认结构
```
目标目录/
├── Avengers.Endgame.2019/
│   ├── Avengers.Endgame.2019.1080p.BluRay.x265.mkv
│   ├── Avengers.Endgame.2019.1080p.BluRay.x265.ai.srt
│   └── Avengers.Endgame.2019.1080p.BluRay.x265.en.srt
├── The.Matrix.1999/
│   ├── The.Matrix.1999.4K.UHD.BluRay.x265.HDR.mkv
│   └── The.Matrix.1999.4K.UHD.BluRay.x265.HDR.ai.srt
├── 阿凡达2：水之道.2022/
│   ├── 阿凡达2：水之道.2022.1080p.BluRay.x265.mkv
│   └── 阿凡达2：水之道.2022.1080p.BluRay.x265.ai.srt
└── 蜘蛛侠：英雄无归.2021/
    ├── 蜘蛛侠：英雄无归.2021.4K.UHD.BluRay.x265.HDR.mkv
    └── 蜘蛛侠：英雄无归.2021.4K.UHD.BluRay.x265.HDR.ai.srt
```

**注意**: 所有文件名和目录名都已自动去除中文广告内容，保持清洁的命名格式。

### 按年份分组结构 (--year-group)
```
目标目录/
├── 1999/
│   └── The.Matrix.1999/
│       ├── The.Matrix.1999.4K.UHD.BluRay.x265.HDR.mkv
│       └── The.Matrix.1999.4K.UHD.BluRay.x265.HDR.ai.srt
├── 2019/
│   └── Avengers.Endgame.2019/
│       ├── Avengers.Endgame.2019.1080p.BluRay.x265.mkv
│       ├── Avengers.Endgame.2019.1080p.BluRay.x265.ai.srt
│       └── Avengers.Endgame.2019.1080p.BluRay.x265.en.srt
├── 2021/
│   └── 蜘蛛侠：英雄无归.2021/
│       ├── 蜘蛛侠：英雄无归.2021.4K.UHD.BluRay.x265.HDR.mkv
│       └── 蜘蛛侠：英雄无归.2021.4K.UHD.BluRay.x265.HDR.ai.srt
└── 2022/
    └── 阿凡达2：水之道.2022/
        ├── 阿凡达2：水之道.2022.1080p.BluRay.x265.mkv
        └── 阿凡达2：水之道.2022.1080p.BluRay.x265.ai.srt
```

## 日志输出

脚本提供详细的日志输出，包括：

- 处理开始信息（版本、参数）
- 目录创建信息
- 文件移动操作
- 跳过文件的原因
- 错误和警告信息
- 处理结果统计

### 日志示例
```
2025-09-28 11:28:24,280 - INFO - mv2moviedir v1.0.0 - 开始处理: 源目录 = movies, 目标目录 = organized
2025-09-28 11:28:24,280 - INFO - 创建电影目录: organized/阿凡达2：水之道.2022
2025-09-28 11:28:24,280 - INFO - 目标目录: organized/阿凡达2：水之道.2022 (电影: 阿凡达2：水之道, 年份: 2022)
2025-09-28 11:28:24,280 - INFO - 移动文件: movies/阿凡达2：水之道.2022.1080p.BluRay.x265-【www.example.com】.mkv -> organized/阿凡达2：水之道.2022/阿凡达2：水之道.2022.1080p.BluRay.x265.mkv
2025-09-28 11:28:24,280 - INFO - 成功移动视频文件: 阿凡达2：水之道.2022.1080p.BluRay.x265.mkv (已去除广告)
2025-09-28 11:28:24,281 - INFO - 移动文件: movies/阿凡达2：水之道.2022.1080p.BluRay.x265-【www.example.com】.ai.srt -> organized/阿凡达2：水之道.2022/阿凡达2：水之道.2022.1080p.BluRay.x265.ai.srt
2025-09-28 11:28:24,281 - INFO - 成功移动字幕文件: 阿凡达2：水之道.2022.1080p.BluRay.x265.ai.srt (已去除广告)
2025-09-28 11:28:24,281 - INFO - 处理完成: 成功 = 6, 失败 = 0, 跳过 = 0
```

## 源目录清理功能

### 智能目录删除 (--remove-source)

当使用 `--remove-source` 参数时，脚本会在成功移动文件后智能清理源目录：

#### 清理规则
1. **递归删除空目录**: 自动删除不包含任何文件的子目录
2. **清理垃圾文件**: 删除以下类型的文件：
   - `.nfo` - 电影信息文件
   - `.txt` - 文本文件
   - `.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff` - 图片文件
3. **保留源目录根**: 源目录本身会被保留（但会被清空）
4. **安全检查**: 只删除确认为空或只包含垃圾文件的目录

#### 清理示例

**处理前的源目录结构:**
```
源目录/
├── movie1/
│   ├── The.Matrix.1999.1080p.BluRay.x264.mkv
│   ├── The.Matrix.1999.1080p.BluRay.x264.srt
│   ├── movie.nfo
│   └── poster.jpg
├── movie2/
│   ├── subdir/
│   │   └── readme.txt
│   ├── Inception.2010.720p.WEBRip.x265.mp4
│   └── info.nfo
└── junk.txt
```

**处理后的源目录结构:**
```
源目录/
(空目录 - 所有子目录和垃圾文件已被清理)
```

### 预览模式 (--dry-run)

预览模式让您在实际执行前查看所有将要进行的操作：

#### 预览功能
- **文件移动预览**: 显示哪些文件将被移动到哪里
- **目录删除预览**: 显示哪些目录和文件将被删除
- **安全无风险**: 不会实际修改任何文件或目录
- **详细日志**: 所有预览操作都标记为 `[预览]`

#### 预览日志示例
```
2025-09-29 08:09:57,148 - INFO - [预览] 将移动文件: source/movie.mkv -> target/Movie.2019/movie.mkv
2025-09-29 08:09:57,148 - INFO - [预览] 将删除垃圾文件: source/movie1/junk.txt
2025-09-29 08:09:57,148 - INFO - [预览] 将删除空目录: source/movie1
2025-09-29 08:09:57,149 - INFO - [预览] 将清理源目录下的空目录和垃圾文件: source
```

### 确认删除 (--confirm-delete)

为了提高安全性，可以启用删除确认功能：

#### 确认机制
- **用户提示**: 在删除目录前会提示用户确认
- **安全警告**: 显示将要删除的目录路径
- **可中断**: 用户可以选择取消操作
- **与预览配合**: 建议先使用 `--dry-run` 预览，再使用 `--confirm-delete` 执行

#### 确认提示示例
```
警告: 即将删除源目录中的空目录和垃圾文件
源目录: /path/to/source
这个操作不可逆，请确认是否继续？ (y/N): 
```

### 安全检查

脚本内置多重安全检查机制：

1. **目录权限检查**: 确保对源目录和目标目录有适当权限
2. **路径安全检查**: 防止删除重要系统目录
3. **目录关系检查**: 防止目标目录是源目录的子目录
4. **同目录检查**: 防止源目录和目标目录相同

## 安全特性

### 两阶段处理
1. 先移动视频文件
2. 再移动对应的字幕文件

### 失败回滚
- 如果移动操作失败，会尝试回滚已移动的文件
- 详细的错误日志帮助诊断问题

### 孤立字幕保护
- 只移动有对应视频文件的字幕
- 避免孤立字幕文件被错误处理

## 与 mv2tvdir 的区别

| 特性 | mv2moviedir | mv2tvdir |
|------|-------------|----------|
| 目标文件 | 电影文件 | 电视剧文件 |
| 识别模式 | 排除 SxxExx 格式 | 要求 SxxExx 格式 |
| 目录结构 | 电影名/年份 | 剧名/季数 |
| 年份分组 | 可选 | 不支持 |
| 信息提取 | 电影名、年份 | 剧名、季数、集数 |

## 许可证

MIT License

## 作者

基于 mv2tvdir 项目改进而来，专门用于电影文件整理。