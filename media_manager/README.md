# 媒体库管理系统

一个功能强大的媒体库管理系统，专为群晖NAS设计，支持电影和电视剧的自动扫描、元数据获取、重复文件检测等功能。

## 功能特性

- 🎬 **智能媒体识别**: 自动识别电影和电视剧，支持多种命名格式
- 📊 **元数据获取**: 集成TMDB API，自动获取详细的媒体信息
- 🔍 **重复文件检测**: 基于文件哈希和相似度的智能重复文件检测
- 📁 **批量扫描**: 支持多目录并发扫描，提高处理效率
- 🗄️ **SQLite数据库**: 轻量级数据库，无需额外配置
- ⚙️ **灵活配置**: 支持YAML配置文件，可自定义各种参数
- 📝 **详细日志**: 完整的操作日志记录，便于问题排查

## 系统要求

- Python 3.7 或更高版本
- 操作系统: Linux, macOS, Windows
- 磁盘空间: 至少100MB（不包括媒体文件）
- 内存: 建议512MB以上

## 快速开始

### 1. 下载和安装

```bash
# 克隆或下载项目到你的NAS
git clone <repository_url> media_manager
cd media_manager

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置系统

编辑 `config/config.yaml` 文件：

```yaml
# 基本配置
database:
  path: "./database/media_library.db"

scanner:
  directories:
    - "/volume1/video/movies"    # 电影目录
    - "/volume1/video/tv_shows"  # 电视剧目录
  
tmdb:
  api_key: "your_tmdb_api_key_here"  # 在 https://www.themoviedb.org/settings/api 获取
```

### 3. 初始化数据库

```bash
# Linux/macOS
./run.sh init

# Windows
run.bat init

# 或直接使用Python
python main.py init
```

### 4. 开始扫描

```bash
# 扫描所有配置的目录
./run.sh scan

# 扫描指定目录
./run.sh scan /volume1/video/movies

# 执行完整流程（扫描 + 元数据 + 重复检测）
./run.sh full
```

## 详细使用说明

### 命令行界面

系统提供了丰富的命令行选项：

```bash
# 初始化数据库
python main.py init

# 扫描媒体文件
python main.py scan [目录路径]

# 更新元数据
python main.py metadata

# 检测重复文件
python main.py duplicates

# 显示统计信息
python main.py stats

# 执行完整流程
python main.py full
```

### 配置文件详解

#### 数据库配置
```yaml
database:
  path: "./database/media_library.db"  # 数据库文件路径
  backup_enabled: true                 # 是否启用自动备份
  backup_interval: 24                  # 备份间隔（小时）
```

#### 扫描器配置
```yaml
scanner:
  directories:                         # 扫描目录列表
    - "/volume1/video/movies"
    - "/volume1/video/tv_shows"
  video_extensions:                     # 支持的视频格式
    - ".mp4"
    - ".mkv"
    - ".avi"
    - ".mov"
  min_file_size: 100                   # 最小文件大小（MB）
  max_workers: 4                       # 并发处理数量
  skip_sample_files: true              # 跳过样本文件
```

#### TMDB API配置
```yaml
tmdb:
  api_key: "your_api_key"              # TMDB API密钥
  language: "zh-CN"                    # 语言设置
  region: "CN"                         # 地区设置
  timeout: 10                          # 请求超时时间
  rate_limit: 40                       # 每10秒请求限制
```

#### 重复文件检测配置
```yaml
duplicate_detection:
  hash_based: true                     # 启用基于哈希的检测
  similarity_based: true               # 启用基于相似度的检测
  similarity_threshold: 0.8            # 相似度阈值
  size_tolerance: 0.05                 # 文件大小容差
```

### 文件命名规范

系统支持多种常见的媒体文件命名格式：

#### 电影命名格式
```
电影名称 (年份).扩展名
Movie Title (2023).mp4
复仇者联盟 (2012).mkv
Avengers.Endgame.2019.1080p.BluRay.x264.mp4
```

#### 电视剧命名格式
```
剧集名称 S季数E集数.扩展名
Game of Thrones S01E01.mp4
权力的游戏 S01E01.mkv
Breaking.Bad.S01E01.1080p.WEB-DL.x264.mp4
```

### 数据库结构

系统使用SQLite数据库存储媒体信息，主要表结构：

- `media_items`: 媒体内容基本信息
- `tv_shows`: 电视剧专用信息
- `episodes`: 剧集信息
- `media_files`: 媒体文件详细信息
- `duplicate_files`: 重复文件组
- `scan_history`: 扫描历史记录

## 高级功能

### 1. 重复文件管理

系统提供两种重复文件检测方式：

- **基于哈希**: 通过文件内容哈希值检测完全相同的文件
- **基于相似度**: 通过文件名、大小、分辨率等特征检测相似文件

```bash
# 检测重复文件
python main.py duplicates

# 查看重复文件报告
# 系统会在日志中显示重复文件组和建议删除的文件
```

### 2. 元数据更新

系统会自动从TMDB获取媒体元数据，包括：

- 标题、简介、评分
- 海报、背景图片URL
- 演员、导演信息
- 发布日期、类型标签

### 3. 批量操作

系统支持大规模媒体库的批量处理：

```bash
# 批量更新所有媒体的元数据
python main.py metadata

# 执行完整的媒体库维护流程
python main.py full
```

## 部署指南

### 群晖NAS部署

1. **启用SSH**: 在群晖控制面板中启用SSH服务
2. **安装Python**: 通过Package Center安装Python3
3. **上传文件**: 将项目文件上传到NAS的共享文件夹
4. **配置路径**: 修改配置文件中的目录路径为NAS路径格式

```yaml
scanner:
  directories:
    - "/volume1/video/movies"
    - "/volume2/media/tv_shows"
```

5. **设置定时任务**: 在控制面板中设置定时任务自动执行扫描

### Docker部署

创建 `Dockerfile`:

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "main.py", "full"]
```

### 性能优化

1. **并发设置**: 根据NAS性能调整 `max_workers` 参数
2. **内存使用**: 大型媒体库建议增加系统内存
3. **存储优化**: 将数据库放在SSD上提高性能
4. **网络配置**: 确保TMDB API访问稳定

## 故障排除

### 常见问题

1. **Python版本错误**
   ```
   错误: Python 版本过低
   解决: 升级到Python 3.7+
   ```

2. **TMDB API限制**
   ```
   错误: API请求过于频繁
   解决: 调整rate_limit配置或等待
   ```

3. **文件权限问题**
   ```
   错误: 无法访问文件
   解决: 检查文件权限和路径配置
   ```

4. **数据库锁定**
   ```
   错误: database is locked
   解决: 确保没有其他进程在使用数据库
   ```

### 日志分析

系统日志位于 `logs/` 目录：

- `media_manager.log`: 主要操作日志
- `error.log`: 错误日志
- `scan_YYYYMMDD.log`: 扫描操作日志

### 数据备份

重要数据备份建议：

1. **数据库备份**: 定期备份 `database/media_library.db`
2. **配置备份**: 备份 `config/config.yaml`
3. **日志归档**: 定期归档日志文件

## API参考

### TMDB API密钥获取

1. 访问 [TMDB官网](https://www.themoviedb.org/)
2. 注册账户并登录
3. 进入 [API设置页面](https://www.themoviedb.org/settings/api)
4. 申请API密钥
5. 将密钥配置到 `config.yaml` 中

### 数据库查询示例

```python
from database.db_manager import get_db_manager

db = get_db_manager()

# 查询所有电影
movies = db.execute_query("SELECT * FROM media_items WHERE media_type = 'movie'")

# 查询重复文件
duplicates = db.execute_query("SELECT * FROM duplicate_files")
```

## 贡献指南

欢迎提交问题报告和功能建议！

### 开发环境设置

```bash
# 克隆项目
git clone <repository_url>
cd media_manager

# 安装开发依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/
```

## 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

## 更新日志

### v1.0.0
- 初始版本发布
- 支持电影和电视剧扫描
- 集成TMDB API
- 重复文件检测功能
- 完整的配置系统

## 联系方式

如有问题或建议，请通过以下方式联系：

- 提交Issue: [项目Issues页面]
- 邮件: [联系邮箱]

---

感谢使用媒体库管理系统！