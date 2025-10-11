# Synology Download Station 磁力链接管理器

这是一个直接调用 Synology Download Station API 来下载磁力链接的解决方案，无需转换为 torrent 文件。

## 功能特点

- ✅ 直接调用 Download Station API
- ✅ 支持批量添加磁力链接
- ✅ 自动监控目录变化
- ✅ 任务状态查看和管理
- ✅ 配置文件支持
- ✅ 详细的日志输出

## 文件说明

- `synology_download_station.py` - 核心 API 客户端
- `synology_magnet_manager.py` - 增强版管理器
- `ds_config.json.example` - 配置文件模板
- `README_DownloadStation.md` - 使用说明

## 快速开始

### 1. 配置设置

复制配置文件模板并修改：

```bash
cp ds_config.json.example ds_config.json
```

编辑 `ds_config.json`：

```json
{
  "host": "192.168.1.100",          # 你的 NAS IP 地址
  "port": 5000,                     # 端口号 (HTTP: 5000, HTTPS: 5001)
  "username": "your_username",      # NAS 用户名
  "password": "your_password",      # NAS 密码
  "use_https": false,               # 是否使用 HTTPS
  "default_destination": "/downloads/magnets",  # 默认下载目录
  "scan_directories": [             # 扫描目录列表
    "./test_input",
    "./magnet_files"
  ],
  "auto_scan_interval": 300,        # 自动扫描间隔(秒)
  "max_concurrent_downloads": 5,    # 最大并发下载数
  "retry_failed_tasks": true,       # 是否重试失败任务
  "cleanup_completed_files": false  # 是否清理已完成文件
}
```

### 2. 基本使用

#### 测试连接
```bash
python3 synology_magnet_manager.py test
```

#### 扫描并添加磁力链接
```bash
python3 synology_magnet_manager.py scan
```

#### 查看下载任务
```bash
# 简单列表
python3 synology_magnet_manager.py list

# 详细信息
python3 synology_magnet_manager.py list --detailed
```

#### 添加单个磁力链接
```bash
python3 synology_magnet_manager.py add "magnet:?xt=urn:btih:..."
```

#### 自动监控模式
```bash
python3 synology_magnet_manager.py monitor
```

### 3. 直接使用 API 客户端

```python
from synology_download_station import SynologyDownloadStation

# 创建客户端
ds = SynologyDownloadStation(
    host="192.168.1.100",
    port=5000,
    username="your_username",
    password="your_password"
)

# 连接
if ds.get_api_info() and ds.login():
    # 添加磁力链接
    task_id = ds.add_magnet_task("magnet:?xt=urn:btih:...")
    if task_id:
        print(f"任务添加成功: {task_id}")
    
    # 获取任务列表
    tasks = ds.get_task_list()
    for task in tasks:
        print(f"任务: {task['title']} - 状态: {task['status']}")
    
    # 登出
    ds.logout()
```

## 命令行参数

### synology_magnet_manager.py

```bash
# 基本命令
python3 synology_magnet_manager.py <command> [options]

# 可用命令:
scan      # 扫描并添加磁力链接
monitor   # 自动监控模式
list      # 列出下载任务
add       # 添加磁力链接
test      # 测试连接

# 选项:
--config CONFIG_FILE    # 指定配置文件 (默认: ds_config.json)
--detailed             # 显示详细信息 (仅用于 list 命令)
--destination DIR      # 指定下载目录 (仅用于 add 命令)
```

### synology_download_station.py

```bash
python3 synology_download_station.py [options]

# 必需参数:
--host HOST           # NAS IP 地址或域名
--username USERNAME   # 用户名
--password PASSWORD   # 密码

# 可选参数:
--port PORT          # 端口号 (默认: 5000)
--https              # 使用 HTTPS 连接
--scan-dir DIR       # 磁力链接文件扫描目录 (默认: ./test_input)
--destination DIR    # 下载目录
--list-tasks         # 列出当前任务
```

## 使用示例

### 示例 1: 批量添加磁力链接

1. 将磁力链接文件放入 `./test_input/` 目录
2. 运行扫描命令：
   ```bash
   python3 synology_magnet_manager.py scan
   ```

### 示例 2: 自动监控

启动自动监控，每 5 分钟扫描一次：
```bash
python3 synology_magnet_manager.py monitor
```

### 示例 3: 查看下载进度

```bash
# 查看所有任务
python3 synology_magnet_manager.py list

# 查看详细进度
python3 synology_magnet_manager.py list --detailed
```

## 错误处理

### 常见错误及解决方案

1. **连接失败**
   - 检查 NAS IP 地址和端口
   - 确认网络连接正常
   - 验证防火墙设置

2. **登录失败**
   - 检查用户名和密码
   - 确认用户有 Download Station 权限
   - 检查账户是否被锁定

3. **API 错误**
   - 确认 Download Station 已启用
   - 检查 DSM 版本兼容性
   - 查看详细错误代码

### 错误代码说明

- `100`: 未知错误
- `101`: 无效参数
- `102`: 请求的API不存在
- `103`: 请求的方法不存在
- `104`: 请求的版本不支持
- `105`: 登录的会话没有权限
- `106`: 会话超时
- `107`: 会话被中断
- `400`: 文件上传失败
- `401`: 最大任务数量限制
- `402`: 目标已存在
- `403`: 目标不存在
- `404`: 无效的任务操作
- `405`: 无效的任务ID
- `406`: 无法读取任务配置

## 优势对比

### 相比 libtorrent 转换方案：

| 特性 | Download Station API | libtorrent 转换 |
|------|---------------------|-----------------|
| 网络依赖 | 仅需 NAS 连接 | 需要 DHT/Tracker 连接 |
| VPN 兼容性 | ✅ 完全兼容 | ❌ 可能受限 |
| 转换速度 | ⚡ 即时添加 | ⏳ 需要元数据下载 |
| 成功率 | ✅ 高 | ❓ 依赖网络环境 |
| 资源占用 | 💡 低 | 💻 中等 |
| 依赖项 | 📦 无额外依赖 | 📦 需要 libtorrent |

## 注意事项

1. **权限要求**：用户需要有 Download Station 的使用权限
2. **网络要求**：需要能够访问 NAS 的网络连接
3. **版本兼容**：支持 DSM 6.0 及以上版本
4. **安全建议**：建议使用 HTTPS 连接并定期更换密码

## 故障排除

### 调试模式

启用详细日志输出：
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 网络诊断

使用之前创建的网络测试工具：
```bash
python3 network_test.py
```

### API 测试

直接测试 API 连接：
```bash
curl "http://your-nas-ip:5000/webapi/query.cgi?api=SYNO.API.Info&version=1&method=query&query=SYNO.API.Auth"
```

## 更新日志

- v1.0: 初始版本，支持基本的磁力链接添加
- v1.1: 添加自动监控功能
- v1.2: 增强错误处理和日志输出
- v1.3: 添加配置文件支持和批量管理

## 许可证

MIT License - 详见 LICENSE 文件