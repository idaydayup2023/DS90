# DS90 部署指南

本文档详细介绍了DS90项目在不同环境下的部署方法。

## 📋 目录

- [系统要求](#系统要求)
- [通用部署](#通用部署)
- [群晖NAS部署](#群晖nas部署)
- [Docker部署](#docker部署)
- [生产环境部署](#生产环境部署)
- [性能优化](#性能优化)
- [监控和维护](#监控和维护)

## 🔧 系统要求

### 最低要求
- **CPU**: 双核 1.5GHz
- **内存**: 2GB RAM
- **存储**: 10GB 可用空间
- **Python**: 3.7+
- **操作系统**: Linux, macOS, Windows

### 推荐配置
- **CPU**: 四核 2.0GHz+
- **内存**: 4GB+ RAM
- **存储**: 50GB+ SSD
- **网络**: 千兆以太网
- **操作系统**: Ubuntu 20.04+ / CentOS 8+ / DSM 7.0+

## 🚀 通用部署

### 1. 环境准备
```bash
# 更新系统
sudo apt update && sudo apt upgrade -y  # Ubuntu/Debian
# 或
sudo yum update -y  # CentOS/RHEL

# 安装Python和pip
sudo apt install python3 python3-pip python3-venv -y  # Ubuntu/Debian
# 或
sudo yum install python3 python3-pip -y  # CentOS/RHEL

# 安装Git
sudo apt install git -y  # Ubuntu/Debian
# 或
sudo yum install git -y  # CentOS/RHEL
```

### 2. 下载和安装
```bash
# 克隆项目
git clone https://github.com/idaydayup2023/DS90.git
cd DS90

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

### 3. 配置
```bash
# 复制配置模板
cp media_manager/config/config.yaml.template media_manager/config/config.yaml

# 编辑配置文件
nano media_manager/config/config.yaml
```

### 4. 初始化和运行
```bash
# 初始化数据库
cd media_manager
./run.sh init

# 开始扫描
./run.sh scan /path/to/your/media
```

## 🏠 群晖NAS部署

### 方法1: 直接部署

#### 1. 启用SSH
1. 控制面板 → 终端机和SNMP
2. 启用SSH服务
3. 使用SSH客户端连接

#### 2. 安装Python3
```bash
# 通过套件中心安装Python3
# 或手动安装
sudo synopkg install Python3

# 验证安装
python3 --version
pip3 --version
```

#### 3. 部署项目
```bash
# 切换到共享文件夹
cd /volume1/homes/admin  # 或其他位置

# 克隆项目
git clone https://github.com/idaydayup2023/DS90.git
cd DS90

# 安装依赖
pip3 install --user -r requirements.txt
```

#### 4. 配置权限
```bash
# 设置执行权限
chmod +x media_manager/run.sh
chmod +x media_manager/run.bat

# 配置媒体目录权限
sudo chown -R admin:users /volume1/media
```

### 方法2: Docker部署 (推荐)

#### 1. 启用Docker
1. 套件中心 → 安装Docker
2. 启动Docker服务

#### 2. 创建Docker配置
```bash
# 创建项目目录
mkdir -p /volume1/docker/ds90
cd /volume1/docker/ds90

# 下载项目
git clone https://github.com/idaydayup2023/DS90.git .
```

#### 3. 使用Docker Compose
```yaml
# docker-compose.yml
version: '3.8'

services:
  ds90-media:
    build: ./media_manager
    container_name: ds90-media-manager
    volumes:
      - /volume1/media:/media:ro
      - /volume1/docker/ds90/data:/app/data
      - /volume1/docker/ds90/config:/app/config
    environment:
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
    
  ds90-subtrans:
    build: ./subtrans
    container_name: ds90-subtrans
    volumes:
      - /volume1/media:/media
      - /volume1/docker/ds90/subtrans:/app/output
    restart: unless-stopped
```

#### 4. 启动服务
```bash
docker-compose up -d
```

### 方法3: 任务计划器

#### 1. 创建脚本
```bash
# /volume1/scripts/ds90_scan.sh
#!/bin/bash
cd /volume1/docker/ds90/DS90/media_manager
source venv/bin/activate
python main.py scan /volume1/media --config config/config.yaml
```

#### 2. 设置定时任务
1. 控制面板 → 任务计划器
2. 新增 → 计划的任务 → 用户定义的脚本
3. 设置执行时间和脚本路径

## 🐳 Docker部署

### 1. 单容器部署

#### Dockerfile示例
```dockerfile
# media_manager/Dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY . .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 创建必要目录
RUN mkdir -p logs data

# 设置权限
RUN chmod +x run.sh

EXPOSE 8000

CMD ["python", "main.py", "scan", "/media"]
```

#### 构建和运行
```bash
# 构建镜像
docker build -t ds90-media-manager ./media_manager

# 运行容器
docker run -d \
  --name ds90-media \
  -v /path/to/media:/media:ro \
  -v /path/to/config:/app/config \
  -v /path/to/data:/app/data \
  ds90-media-manager
```

### 2. Docker Compose部署

#### 完整配置
```yaml
# docker-compose.yml
version: '3.8'

services:
  media-manager:
    build: ./media_manager
    container_name: ds90-media-manager
    volumes:
      - ${MEDIA_PATH}:/media:ro
      - ./data/media:/app/data
      - ./config/media:/app/config
    environment:
      - TMDB_API_KEY=${TMDB_API_KEY}
      - LOG_LEVEL=INFO
    restart: unless-stopped
    networks:
      - ds90-network

  subtrans:
    build: ./subtrans
    container_name: ds90-subtrans
    volumes:
      - ${MEDIA_PATH}:/media
      - ./data/subtrans:/app/data
      - ./config/subtrans:/app/config
    environment:
      - TRANSLATOR_API_KEY=${TRANSLATOR_API_KEY}
    restart: unless-stopped
    networks:
      - ds90-network

  tools:
    build: ./tools
    container_name: ds90-tools
    volumes:
      - ./data/tools:/app/data
      - ./config/tools:/app/config
      - /var/log:/host/logs:ro
    restart: unless-stopped
    networks:
      - ds90-network

networks:
  ds90-network:
    driver: bridge

volumes:
  ds90-data:
```

#### 环境变量配置
```bash
# .env
MEDIA_PATH=/volume1/media
TMDB_API_KEY=your_tmdb_api_key
TRANSLATOR_API_KEY=your_translator_key
LOG_LEVEL=INFO
```

#### 启动服务
```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 🏭 生产环境部署

### 1. 系统服务配置

#### Systemd服务
```ini
# /etc/systemd/system/ds90-media.service
[Unit]
Description=DS90 Media Manager
After=network.target

[Service]
Type=simple
User=ds90
Group=ds90
WorkingDirectory=/opt/ds90/media_manager
Environment=PATH=/opt/ds90/venv/bin
ExecStart=/opt/ds90/venv/bin/python main.py scan /media --daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

#### 启用服务
```bash
# 重载systemd配置
sudo systemctl daemon-reload

# 启用服务
sudo systemctl enable ds90-media

# 启动服务
sudo systemctl start ds90-media

# 查看状态
sudo systemctl status ds90-media
```

### 2. 反向代理配置

#### Nginx配置
```nginx
# /etc/nginx/sites-available/ds90
server {
    listen 80;
    server_name ds90.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/ds90/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

### 3. SSL证书配置
```bash
# 使用Let's Encrypt
sudo certbot --nginx -d ds90.yourdomain.com
```

## ⚡ 性能优化

### 1. 系统优化
```bash
# 增加文件描述符限制
echo "* soft nofile 65536" >> /etc/security/limits.conf
echo "* hard nofile 65536" >> /etc/security/limits.conf

# 优化内核参数
echo "vm.swappiness=10" >> /etc/sysctl.conf
echo "vm.vfs_cache_pressure=50" >> /etc/sysctl.conf
```

### 2. 数据库优化
```yaml
# config/config.yaml
database:
  connection_pool_size: 20
  max_overflow: 30
  pool_timeout: 30
  pool_recycle: 3600
  
  # SQLite优化
  sqlite_options:
    journal_mode: "WAL"
    synchronous: "NORMAL"
    cache_size: 10000
    temp_store: "MEMORY"
```

### 3. 并发优化
```yaml
# config/config.yaml
scanner:
  max_workers: 8  # CPU核心数
  batch_size: 100
  chunk_size: 1000
  
api:
  max_concurrent_requests: 10
  request_timeout: 30
  retry_count: 3
```

## 📊 监控和维护

### 1. 日志监控
```bash
# 设置日志轮转
# /etc/logrotate.d/ds90
/opt/ds90/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 ds90 ds90
    postrotate
        systemctl reload ds90-media
    endscript
}
```

### 2. 健康检查
```bash
#!/bin/bash
# /opt/ds90/scripts/health_check.sh

# 检查服务状态
if ! systemctl is-active --quiet ds90-media; then
    echo "DS90 Media Manager is not running"
    systemctl restart ds90-media
fi

# 检查磁盘空间
DISK_USAGE=$(df /opt/ds90 | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 90 ]; then
    echo "Disk usage is above 90%"
    # 清理日志或发送告警
fi

# 检查内存使用
MEMORY_USAGE=$(free | awk 'NR==2{printf "%.2f", $3*100/$2}')
if (( $(echo "$MEMORY_USAGE > 90" | bc -l) )); then
    echo "Memory usage is above 90%"
fi
```

### 3. 备份策略
```bash
#!/bin/bash
# /opt/ds90/scripts/backup.sh

BACKUP_DIR="/backup/ds90"
DATE=$(date +%Y%m%d_%H%M%S)

# 备份数据库
cp /opt/ds90/data/media_library.db $BACKUP_DIR/db_$DATE.db

# 备份配置
tar -czf $BACKUP_DIR/config_$DATE.tar.gz /opt/ds90/config/

# 清理旧备份 (保留30天)
find $BACKUP_DIR -name "*.db" -mtime +30 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete
```

## 🔧 故障排除

### 常见问题

#### 1. 权限问题
```bash
# 检查文件权限
ls -la /path/to/media

# 修复权限
sudo chown -R ds90:ds90 /opt/ds90
sudo chmod -R 755 /opt/ds90
```

#### 2. 依赖问题
```bash
# 重新安装依赖
pip install --force-reinstall -r requirements.txt

# 检查Python版本
python --version
```

#### 3. 数据库问题
```bash
# 检查数据库文件
sqlite3 /opt/ds90/data/media_library.db ".schema"

# 重建数据库
cd /opt/ds90/media_manager
python main.py init --force
```

### 日志分析
```bash
# 查看实时日志
tail -f /opt/ds90/logs/media_manager.log

# 搜索错误
grep -i error /opt/ds90/logs/*.log

# 分析性能
grep -i "slow\|timeout" /opt/ds90/logs/*.log
```

## 📞 技术支持

如果遇到部署问题，请：

1. 查看项目文档和FAQ
2. 检查GitHub Issues
3. 提交新的Issue并附上：
   - 系统信息
   - 错误日志
   - 配置文件（去除敏感信息）

---

**部署成功后，请记得定期更新和维护系统！** 🚀