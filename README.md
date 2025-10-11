# DS90 - 全站管理代码库

DS90是一个综合性的管理工具集合，专为群晖NAS和媒体服务器环境设计，提供媒体管理、字幕处理和各种实用工具。

## 📁 项目结构

```
DS90/
├── media_manager/          # 媒体库管理系统
├── subtrans/              # 字幕翻译和管理工具
├── tools/                 # 各种实用小工具
├── docs/                  # 项目文档
├── README.md              # 项目说明
└── requirements.txt       # 全局依赖
```

## 🎯 核心模块

### 📺 Media Manager - 媒体库管理系统
完整的媒体文件管理解决方案，支持：
- 🎬 电影和电视剧的智能识别和分类
- 📊 TMDB API集成，自动获取元数据
- 🔍 重复文件检测和管理
- 📁 批量扫描和并发处理
- 🗄️ SQLite数据库存储

**快速开始:**
```bash
cd media_manager
./run.sh init
./run.sh scan /path/to/your/media
```

### 🔤 SubTrans - 字幕翻译管理工具
智能字幕处理和翻译系统（开发中）：
- 🌐 多语言字幕翻译
- 📝 字幕格式转换
- 🎯 字幕同步和校准
- 🤖 AI辅助翻译

### 🛠️ Tools - 实用工具集
各种便捷的小工具（规划中）：
- 📊 系统监控工具
- 🔧 文件批处理工具
- 📈 日志分析工具
- 🔄 数据同步工具

## 🚀 快速开始

### 1. 环境要求
- Python 3.7+
- 操作系统: Linux, macOS, Windows
- 推荐: 群晖NAS DSM 7.0+

### 2. 安装依赖
```bash
# 克隆项目
git clone https://github.com/idaydayup2023/DS90.git
cd DS90

# 安装全局依赖
pip install -r requirements.txt
```

### 3. 模块使用
每个模块都有独立的文档和启动方式：

```bash
# 媒体管理
cd media_manager
./run.sh full

# 字幕管理（开发中）
cd subtrans
python main.py

# 工具集（规划中）
cd tools
```

## 📖 详细文档

- [媒体管理系统文档](./media_manager/README.md)
- [字幕管理工具文档](./subtrans/README.md)
- [工具集文档](./tools/README.md)
- [部署指南](./docs/DEPLOYMENT.md)

## 🏗️ 开发状态

| 模块 | 状态 | 版本 | 描述 |
|------|------|------|------|
| Media Manager | ✅ 完成 | v1.0.0 | 功能完整，可生产使用 |
| SubTrans | 🚧 开发中 | v0.1.0 | 基础功能开发中 |
| Tools | 📋 规划中 | v0.0.1 | 需求收集阶段 |

## 🔧 配置说明

### 全局配置
项目根目录的配置文件用于管理全局设置：

```yaml
# config/global.yaml
project:
  name: "DS90"
  version: "1.0.0"
  
modules:
  media_manager:
    enabled: true
    config_path: "./media_manager/config/config.yaml"
  
  subtrans:
    enabled: false
    config_path: "./subtrans/config/config.yaml"
```

### 模块配置
每个模块都有独立的配置文件，详见各模块文档。

## 🐳 Docker部署

### 完整部署
```bash
# 构建所有模块
docker-compose up -d

# 或单独部署模块
docker-compose up media-manager
```

### 群晖NAS部署
1. 通过Docker套件安装
2. 或直接在DSM中运行Python脚本
3. 详见 [部署指南](./docs/DEPLOYMENT.md)

## 📊 系统架构

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Media Manager │    │    SubTrans     │    │     Tools       │
│                 │    │                 │    │                 │
│ ┌─────────────┐ │    │ ┌─────────────┐ │    │ ┌─────────────┐ │
│ │   Scanner   │ │    │ │ Translator  │ │    │ │  Monitor    │ │
│ │   TMDB API  │ │    │ │ Converter   │ │    │ │  Analyzer   │ │
│ │  Duplicate  │ │    │ │  Sync Tool  │ │    │ │  Utilities  │ │
│ └─────────────┘ │    │ └─────────────┘ │    │ └─────────────┘ │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │  Shared Core    │
                    │                 │
                    │ ┌─────────────┐ │
                    │ │  Database   │ │
                    │ │   Config    │ │
                    │ │   Logger    │ │
                    │ └─────────────┘ │
                    └─────────────────┘
```

## 🤝 贡献指南

### 开发环境
```bash
# 克隆项目
git clone https://github.com/idaydayup2023/DS90.git
cd DS90

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 安装开发依赖
pip install -r requirements-dev.txt
```

### 提交规范
- 功能开发: `feat: 添加新功能`
- 问题修复: `fix: 修复问题`
- 文档更新: `docs: 更新文档`
- 代码重构: `refactor: 重构代码`

### 分支管理
- `main`: 主分支，稳定版本
- `develop`: 开发分支
- `feature/*`: 功能分支
- `hotfix/*`: 热修复分支

## 📝 更新日志

### v1.0.0 (2024-01-XX)
- ✨ 完成媒体管理系统v1.0.0
- 📁 建立项目整体架构
- 📖 完善项目文档

### 计划中的功能
- 🔤 字幕翻译管理工具
- 🛠️ 实用工具集合
- 🌐 Web管理界面
- 📱 移动端应用

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 📞 联系方式

- 项目主页: https://github.com/idaydayup2023/DS90
- 问题反馈: [Issues](https://github.com/idaydayup2023/DS90/issues)
- 功能建议: [Discussions](https://github.com/idaydayup2023/DS90/discussions)

---

**DS90** - 让媒体管理更简单，让工作更高效！ 🚀