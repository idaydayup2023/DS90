# 安装和部署指南

本文档提供媒体库管理系统的详细安装和部署说明。

## 目录

- [系统要求](#系统要求)
- [安装步骤](#安装步骤)
- [群晖NAS部署](#群晖nas部署)
- [Docker部署](#docker部署)
- [配置说明](#配置说明)
- [首次运行](#首次运行)
- [故障排除](#故障排除)

## 系统要求

### 最低要求
- **操作系统**: Linux, macOS, Windows 10+
- **Python版本**: 3.7 或更高版本
- **内存**: 512MB RAM
- **存储空间**: 100MB（不包括媒体文件）
- **网络**: 稳定的互联网连接（用于TMDB API）

### 推荐配置
- **操作系统**: Linux (Ubuntu 20.04+) 或 群晖DSM 7.0+
- **Python版本**: 3.9 或更高版本
- **内存**: 2GB RAM 或更多
- **存储空间**: 1GB SSD空间（用于数据库和日志）
- **CPU**: 多核处理器（用于并发扫描）

## 安装步骤

### 1. 下载项目

#### 方式一：Git克隆（推荐）
```bash
git clone <repository_url> media_manager
cd media_manager
```

#### 方式二：直接下载
1. 下载项目压缩包
2. 解压到目标目录
3. 进入项目目录

### 2. 检查Python环境

```bash
# 检查Python版本
python3 --version

# 如果版本低于3.7，需要升级Python
```

#### Ubuntu/Debian安装Python 3.9
```bash
sudo apt update
sudo apt install python3.9 python3.9-pip python3.9-venv
```

#### CentOS/RHEL安装Python 3.9
```bash
sudo yum install python39 python39-pip
```

#### macOS安装Python（使用Homebrew）
```bash
brew install python@3.9
```

#### Windows安装Python
1. 访问 [Python官网](https://www.python.org/downloads/)
2. 下载Python 3.9+安装包
3. 运行安装程序，确保勾选"Add Python to PATH"

### 3. 安装依赖包

```bash
# 使用pip安装依赖
pip3 install -r requirements.txt

# 或者使用虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 4. 验证安装

```bash
# 检查主要依赖是否正确安装
python3 -c "import yaml, requests; print('依赖安装成功')"
```

## 群晖NAS部署

### 1. 准备工作

#### 启用SSH
1. 登录群晖DSM管理界面
2. 进入"控制面板" > "终端机和SNMP"
3. 勾选"启动SSH功能"
4. 设置端口（默认22）

#### 安装Python3
1. 打开"套件中心"
2. 搜索并安装"Python 3"
3. 等待安装完成

### 2. 上传项目文件

#### 方式一：通过File Station
1. 打开File Station
2. 创建目录 `/volume1/apps/media_manager`
3. 上传所有项目文件

#### 方式二：通过SSH
```bash
# 连接到NAS
ssh admin@your_nas_ip

# 创建目录
sudo mkdir -p /volume1/apps/media_manager
cd /volume1/apps/media_manager

# 下载项目（如果NAS能访问外网）
git clone <repository_url> .
```

### 3. 安装依赖

```bash
# 进入项目目录
cd /volume1/apps/media_manager

# 安装依赖
python3 -m pip install -r requirements.txt --user
```

### 4. 配置权限

```bash
# 设置执行权限
chmod +x run.sh

# 确保Python脚本可执行
chmod +x main.py
```

### 5. 配置路径

编辑 `config/config.yaml`，设置正确的NAS路径：

```yaml
database:
  path: "/volume1/apps/media_manager/database/media_library.db"

scanner:
  directories:
    - "/volume1/video/movies"      # 电影目录
    - "/volume1/video/tv_shows"    # 电视剧目录
    - "/volume2/media/documentaries"  # 纪录片目录

logging:
  log_dir: "/volume1/apps/media_manager/logs"
```

### 6. 设置定时任务

1. 登录DSM管理界面
2. 进入"控制面板" > "任务计划"
3. 创建"用户定义的脚本"任务
4. 设置执行时间（如每天凌晨2点）
5. 脚本内容：

```bash
#!/bin/bash
cd /volume1/apps/media_manager
./run.sh full >> /volume1/apps/media_manager/logs/cron.log 2>&1
```

## Docker部署

### 1. 创建Dockerfile

```dockerfile
FROM python:3.9-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建必要目录
RUN mkdir -p logs database

# 设置权限
RUN chmod +x run.sh

# 暴露端口（如果有Web界面）
# EXPOSE 8080

# 设置环境变量
ENV PYTHONPATH=/app

# 默认命令
CMD ["python", "main.py", "full"]
```

### 2. 创建docker-compose.yml

```yaml
version: '3.8'

services:
  media-manager:
    build: .
    container_name: media_manager
    restart: unless-stopped
    volumes:
      - ./config:/app/config
      - ./database:/app/database
      - ./logs:/app/logs
      - /path/to/your/media:/media:ro  # 媒体文件目录（只读）
    environment:
      - TZ=Asia/Shanghai
    # ports:
    #   - "8080:8080"  # 如果有Web界面
```

### 3. 构建和运行

```bash
# 构建镜像
docker-compose build

# 运行容器
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 4. Docker配置调整

修改 `config/config.yaml` 中的路径：

```yaml
scanner:
  directories:
    - "/media/movies"
    - "/media/tv_shows"
```

## 配置说明

### 1. 基础配置

复制并编辑配置文件：

```bash
# 如果没有配置文件，创建一个
cp config/config.yaml.example config/config.yaml
```

### 2. 必需配置项

#### TMDB API密钥
1. 访问 [TMDB官网](https://www.themoviedb.org/)
2. 注册并登录账户
3. 进入 [API设置](https://www.themoviedb.org/settings/api)
4. 申请API密钥
5. 在配置文件中设置：

```yaml
tmdb:
  api_key: "your_tmdb_api_key_here"
```

#### 扫描目录
```yaml
scanner:
  directories:
    - "/path/to/your/movies"
    - "/path/to/your/tv_shows"
```

### 3. 可选配置项

#### 性能调优
```yaml
scanner:
  max_workers: 4          # 并发处理数量
  min_file_size: 100      # 最小文件大小(MB)

duplicate_detection:
  similarity_threshold: 0.8  # 相似度阈值
```

#### 日志配置
```yaml
logging:
  level: "INFO"           # DEBUG, INFO, WARNING, ERROR
  max_file_size: 10       # 日志文件最大大小(MB)
  backup_count: 5         # 保留的日志文件数量
```

## 首次运行

### 1. 初始化数据库

```bash
# 使用启动脚本
./run.sh init

# 或直接使用Python
python3 main.py init
```

### 2. 测试配置

```bash
# 测试扫描单个目录
./run.sh scan /path/to/test/directory

# 查看统计信息
./run.sh stats
```

### 3. 执行完整扫描

```bash
# 执行完整流程
./run.sh full
```

### 4. 验证结果

检查以下内容确认系统正常运行：

1. **数据库文件**: `database/media_library.db` 已创建
2. **日志文件**: `logs/` 目录下有日志文件
3. **扫描结果**: 日志中显示扫描到的文件数量
4. **元数据**: 检查是否成功获取TMDB数据

## 故障排除

### 常见问题

#### 1. Python版本问题
```
错误: Python 版本过低
解决方案:
- 升级Python到3.7+
- 使用python3命令而不是python
```

#### 2. 依赖安装失败
```
错误: pip install失败
解决方案:
- 升级pip: pip install --upgrade pip
- 使用国内镜像: pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

#### 3. 权限问题
```
错误: Permission denied
解决方案:
- 检查文件权限: chmod +x run.sh
- 使用sudo运行（谨慎使用）
- 检查目录访问权限
```

#### 4. TMDB API问题
```
错误: API请求失败
解决方案:
- 检查API密钥是否正确
- 检查网络连接
- 检查API请求频率限制
```

#### 5. 数据库锁定
```
错误: database is locked
解决方案:
- 确保没有其他进程在使用数据库
- 重启系统
- 检查数据库文件权限
```

### 日志分析

#### 查看实时日志
```bash
# 查看主日志
tail -f logs/media_manager.log

# 查看错误日志
tail -f logs/error.log
```

#### 日志级别说明
- **DEBUG**: 详细的调试信息
- **INFO**: 一般信息
- **WARNING**: 警告信息
- **ERROR**: 错误信息

### 性能优化

#### 1. 调整并发数量
```yaml
scanner:
  max_workers: 8  # 根据CPU核心数调整
```

#### 2. 优化数据库
```bash
# 定期优化数据库
sqlite3 database/media_library.db "VACUUM;"
```

#### 3. 清理日志
```bash
# 清理旧日志文件
find logs/ -name "*.log" -mtime +30 -delete
```

### 备份和恢复

#### 备份重要数据
```bash
# 备份数据库
cp database/media_library.db database/media_library_backup_$(date +%Y%m%d).db

# 备份配置
cp config/config.yaml config/config_backup_$(date +%Y%m%d).yaml
```

#### 恢复数据
```bash
# 恢复数据库
cp database/media_library_backup_YYYYMMDD.db database/media_library.db

# 重新初始化（如果需要）
python3 main.py init
```

## 升级指南

### 1. 备份数据
```bash
# 备份整个项目
tar -czf media_manager_backup_$(date +%Y%m%d).tar.gz media_manager/
```

### 2. 更新代码
```bash
# 如果使用Git
git pull origin main

# 或下载新版本并替换文件
```

### 3. 更新依赖
```bash
pip install -r requirements.txt --upgrade
```

### 4. 检查配置
```bash
# 比较新旧配置文件
diff config/config.yaml config/config.yaml.example
```

### 5. 测试运行
```bash
# 测试新版本
./run.sh stats
```

---

如有其他问题，请参考主文档或提交Issue。