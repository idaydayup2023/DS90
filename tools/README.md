# Tools - 实用工具集

Tools是DS90项目的工具集模块，提供各种便捷的系统管理和文件处理工具。

## 🛠️ 现有工具

### 📁 文件处理工具 (已实现)

#### 🗂️ file_organizer - 文件整理工具
智能的文件整理工具，能够按文件名将文件自动分类到对应的子目录中。

**功能特点:**
- 根据文件名（去除扩展名）自动创建目录并分类文件
- 智能处理字幕文件，去除语言标识符（如 .ai, .en, .zh 等）
- 安全操作，避免覆盖现有文件
- 多语言支持，完美支持中文文件名

**使用方法:**
```bash
cd tools/file_organizer
python3 file_organizer.py [目录路径]
```

#### 🎬 mv2moviedir - 电影文件移动工具
将电影文件移动到按电影名组织的目录结构中的专业工具。

**功能特点:**
- 自动识别电影文件（排除电视剧文件）
- 智能分类：提取电影名称、年份、分辨率和编码信息
- 字幕对齐：自动移动对应的字幕文件
- AI字幕检查：默认只处理有 `.ai.srt` 字幕的电影文件
- 中文广告去除：自动识别并去除文件名中的广告内容
- 高级过滤：支持按分辨率、编码过滤文件

**使用方法:**
```bash
cd tools/mv2moviedir
python3 mv2moviedir.py 源目录 目标目录 [选项]
```

#### 📺 mv2tvdir - 电视剧文件移动工具
将电视剧文件移动到按剧名/季级组织的目录结构中的专业工具。

**功能特点:**
- 扫描并识别电视剧文件（区分电视剧和电影）
- 支持多种视频格式（mkv、mp4、avi）和字幕格式（srt、ass、sub）
- 按分辨率和编码过滤文件
- 从文件名中提取剧名和季数信息
- 字幕文件对齐：确保字幕文件与视频文件同步移动
- 标准化文件名和目录名

**使用方法:**
```bash
cd tools/mv2tvdir
python3 mv2tvdir.py 源目录 目标目录 [选项]
```

#### 🧲 magnet2torrent - 磁力链接转种子工具
将磁力链接转换为种子文件的实用工具。

**功能特点:**
- 磁力链接解析和转换
- 种子文件生成
- 批量处理支持

**使用方法:**
```bash
cd tools/magnet2torrent
python3 magnet2torrent.py [选项]
```

## 🚀 快速开始

### 环境要求
- Python 3.6+
- 根据具体工具可能需要额外依赖

### 通用使用流程

1. **选择工具**: 根据需求选择合适的工具
2. **进入目录**: `cd tools/[工具名]`
3. **查看帮助**: `python3 [工具名].py --help`
4. **执行操作**: 按照工具说明执行相应命令

### 使用示例

#### 整理下载文件
```bash
# 整理下载目录中的文件
cd tools/file_organizer
python3 file_organizer.py ~/Downloads
```

#### 整理电影文件
```bash
# 将下载的电影移动到媒体库
cd tools/mv2moviedir
python3 mv2moviedir.py ~/Downloads/Movies ~/Media/Movies --dry-run
```

#### 整理电视剧文件
```bash
# 将下载的电视剧移动到媒体库
cd tools/mv2tvdir
python3 mv2tvdir.py ~/Downloads/TV ~/Media/TV --resolution=1080p
```

## 📁 项目结构

```
tools/
├── README.md              # 工具集说明
├── file_organizer/        # 文件整理工具
│   ├── README.md
│   ├── file_organizer.py
│   └── example.py
├── mv2moviedir/          # 电影文件移动工具
│   ├── README.md
│   ├── mv2moviedir.py
│   └── example.py
├── mv2tvdir/             # 电视剧文件移动工具
│   ├── README.md
│   └── mv2tvdir.py
└── magnet2torrent/       # 磁力链接转种子工具
    ├── README.md
    ├── magnet2torrent.py
    └── [其他文件]
```

## 🔧 开发状态

| 工具名称 | 状态 | 版本 | 描述 |
|---------|------|------|------|
| file_organizer | ✅ 完成 | v1.0.0 | 文件自动整理 |
| mv2moviedir | ✅ 完成 | v1.0.0 | 电影文件移动 |
| mv2tvdir | ✅ 完成 | v1.0.3 | 电视剧文件移动 |
| magnet2torrent | ✅ 完成 | - | 磁力链接转换 |

## 🎯 规划中的工具

### 📊 系统监控工具 (规划中)
- **system_monitor.py** - 系统资源监控
- **disk_analyzer.py** - 磁盘空间分析
- **network_monitor.py** - 网络状态监控
- **service_checker.py** - 服务状态检查

### 📈 日志分析工具 (规划中)
- **log_analyzer.py** - 日志文件分析
- **error_tracker.py** - 错误追踪统计
- **performance_analyzer.py** - 性能分析
- **report_generator.py** - 报告生成器

### 🔄 数据同步工具 (规划中)
- **rsync_manager.py** - Rsync同步管理
- **cloud_sync.py** - 云存储同步
- **database_sync.py** - 数据库同步
- **config_sync.py** - 配置文件同步

## 🚀 快速开始

### 环境要求
- Python 3.7+
- 根据具体工具可能需要额外依赖

### 安装
```bash
cd tools
pip install -r requirements.txt
```

### 使用示例

#### 系统监控
```bash
# 实时系统监控
python system_monitor.py --interval 5 --output monitor.log

# 磁盘分析
python disk_analyzer.py --path /home --format json
```

#### 文件处理
```bash
# 批量重命名
python batch_rename.py --pattern "*.jpg" --template "photo_{counter:04d}.jpg"

# 查找重复文件
python duplicate_finder.py --path /media --algorithm md5
```

#### 日志分析
```bash
# 分析访问日志
python log_analyzer.py --input access.log --type nginx --output report.html

# 错误统计
python error_tracker.py --log-dir /var/log --time-range 24h
```

#### 数据同步
```bash
# Rsync同步
python rsync_manager.py --source /data --target backup:/data --dry-run

# 云存储同步
python cloud_sync.py --provider s3 --bucket mybucket --local-path /backup
```

## 📁 项目结构

```
tools/
├── main.py                 # 工具集主入口
├── config/                 # 配置文件
│   └── tools.yaml         # 工具配置
├── system/                # 系统监控工具
│   ├── system_monitor.py
│   ├── disk_analyzer.py
│   └── network_monitor.py
├── files/                 # 文件处理工具
│   ├── batch_rename.py
│   ├── duplicate_finder.py
│   └── file_organizer.py
├── logs/                  # 日志分析工具
│   ├── log_analyzer.py
│   └── error_tracker.py
├── sync/                  # 同步工具
│   ├── rsync_manager.py
│   └── cloud_sync.py
├── utils/                 # 通用工具函数
├── tests/                 # 测试文件
└── requirements.txt       # 依赖包
```

## ⚙️ 配置说明

### 主配置文件
```yaml
# config/tools.yaml
general:
  log_level: "INFO"
  max_workers: 4
  temp_dir: "/tmp/ds90_tools"

system_monitor:
  interval: 60
  metrics:
    - cpu
    - memory
    - disk
    - network
  
file_tools:
  backup_dir: "/backup"
  max_file_size: "1GB"
  excluded_extensions:
    - ".tmp"
    - ".log"

sync_tools:
  rsync_options: "-avz --progress"
  retry_count: 3
  timeout: 3600
```

## 🔧 开发状态

| 工具类别 | 状态 | 完成度 | 描述 |
|---------|------|--------|------|
| 系统监控 | 📋 规划中 | 0% | 需求分析阶段 |
| 文件处理 | 📋 规划中 | 0% | 设计阶段 |
| 日志分析 | 📋 规划中 | 0% | 概念验证 |
| 数据同步 | 📋 规划中 | 0% | 技术调研 |

## 🎯 开发计划

### Phase 1 - 基础工具 (v0.1.0)
- [ ] 系统监控基础功能
- [ ] 文件批量处理
- [ ] 简单日志分析
- [ ] 基础同步功能

### Phase 2 - 增强功能 (v0.2.0)
- [ ] Web界面
- [ ] 定时任务
- [ ] 邮件通知
- [ ] 配置管理

### Phase 3 - 高级特性 (v0.3.0)
- [ ] 插件系统
- [ ] API接口
- [ ] 集群支持
- [ ] 性能优化

## 📖 详细文档

- [工具使用指南](./docs/USAGE.md)
- [配置参考](./docs/CONFIG.md)
- [开发指南](./docs/DEVELOPMENT.md)
- [API文档](./docs/API.md)

## 🤝 贡献指南

### 添加新工具
1. 在相应目录下创建工具脚本
2. 遵循命名规范: `tool_name.py`
3. 添加配置项到 `config/tools.yaml`
4. 编写测试用例
5. 更新文档

### 代码规范
- 使用Python类型注解
- 遵循PEP 8代码风格
- 添加详细的docstring
- 包含错误处理

## 📄 许可证

MIT License - 详见根目录LICENSE文件

---

**注意**: 此模块目前处于规划阶段，大部分功能尚未实现。欢迎贡献想法和代码！