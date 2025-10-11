# 群晖NAS磁力链接转换器部署指南

## 📋 概述

本指南将帮助您在群晖NAS上部署磁力链接转换器，实现自动将`.magnet`文件转换为`.torrent`文件的功能。

## 🎯 功能特性

- ✅ 自动监控指定目录下的`.magnet`文件
- ✅ 将磁力链接转换为标准`.torrent`文件
- ✅ 支持单次运行和持续监控两种模式
- ✅ 完整的日志记录和错误处理
- ✅ 群晖任务计划集成
- ✅ 防重复处理机制

## 📁 目录结构

```
/volume1/Downloads/
├── magnet.files/          # 输入目录：放置.magnet文件
├── torrent.files/         # 输出目录：生成的.torrent文件
├── logs/                  # 日志目录
│   ├── magnet_converter.log
│   ├── processed_magnets.log
│   ├── task_execution.log
│   └── monitor.log
└── scripts/               # 脚本目录
    ├── synology_magnet_converter.py
    ├── start_converter.sh
    └── start_monitor.sh
```

## 🚀 快速部署

### 方法一：使用自动安装脚本（推荐）

1. **上传文件到群晖**
   ```bash
   # 将以下文件上传到群晖的任意目录
   - synology_magnet_converter.py          # 标准版本
   - synology_magnet_converter_simple.py   # 简化版本（兼容性更好）
   - synology_setup.sh                     # 安装脚本
   ```

2. **运行安装脚本**
   ```bash
   # SSH连接到群晖，进入文件所在目录
   chmod +x synology_setup.sh
   sudo ./synology_setup.sh
   ```

3. **按照脚本提示完成安装**

### 版本选择指南

- **标准版本** (`synology_magnet_converter.py`)：功能完整，适合较新的libtorrent版本
- **简化版本** (`synology_magnet_converter_simple.py`)：兼容性更好，适合群晖NAS的旧版本libtorrent

**推荐使用简化版本**，特别是遇到以下错误时：
- `module 'libtorrent' has no attribute 'settings_pack'`
- `AttributeError: 'module' object has no attribute 'add_torrent_params'`

### 方法二：手动部署

#### 步骤1：环境准备

1. **SSH登录群晖**
   ```bash
   ssh admin@your-nas-ip
   ```

2. **检查Python环境**
   ```bash
   python3 --version
   which python3
   ```

3. **安装pip（如果未安装）**
   ```bash
   # 方法1：使用get-pip.py（推荐）
   curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
   python3 get-pip.py --user
   
   # 添加到PATH
   export PATH="$HOME/.local/bin:$PATH"
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   ```

4. **验证pip安装**
   ```bash
   python3 -m pip --version
   ```

5. **安装依赖库**
   ```bash
   python3 -m pip install --user libtorrent
   ```

#### 步骤2：创建目录结构

```bash
# 创建必要目录
mkdir -p /volume1/Downloads/magnet.files
mkdir -p /volume1/Downloads/torrent.files
mkdir -p /volume1/Downloads/logs
mkdir -p /volume1/Downloads/scripts

# 设置权限
chmod 755 /volume1/Downloads/magnet.files
chmod 755 /volume1/Downloads/torrent.files
chmod 755 /volume1/Downloads/logs
chmod 755 /volume1/Downloads/scripts
```

#### 步骤3：上传脚本文件

1. **上传主脚本**
   - 将`synology_magnet_converter.py`上传到`/volume1/Downloads/scripts/`
   - 设置执行权限：`chmod +x /volume1/Downloads/scripts/synology_magnet_converter.py`

2. **创建启动脚本**
   ```bash
   cat > /volume1/Downloads/scripts/start_converter.sh << 'EOF'
   #!/bin/bash
   cd /volume1/Downloads/scripts
   export PATH="$HOME/.local/bin:$PATH"
   python3 synology_magnet_converter.py --once
   echo "$(date): 磁力链接转换任务执行完成" >> /volume1/Downloads/logs/task_execution.log
   EOF
   
   chmod +x /volume1/Downloads/scripts/start_converter.sh
   ```

3. **创建监控脚本**
   ```bash
   cat > /volume1/Downloads/scripts/start_monitor.sh << 'EOF'
   #!/bin/bash
   cd /volume1/Downloads/scripts
   export PATH="$HOME/.local/bin:$PATH"
   nohup python3 synology_magnet_converter.py --monitor --interval 300 > /volume1/Downloads/logs/monitor.log 2>&1 &
   echo "监控进程已启动，PID: $!"
   EOF
   
   chmod +x /volume1/Downloads/scripts/start_monitor.sh
   ```

## ⚙️ 群晖任务计划配置

### 配置定时任务

1. **打开DSM控制面板**
   - 登录群晖DSM
   - 进入"控制面板" → "任务计划"

2. **创建新任务**
   - 点击"新增" → "计划的任务" → "用户定义的脚本"

3. **基本设置**
   - 任务名称：`磁力链接转换器`
   - 用户账号：`root`（或具有足够权限的用户）
   - 已启用：✅

4. **计划设置**
   - 运行日期：每日
   - 频率：每5分钟
   - 或自定义：`*/5 * * * *`

5. **任务设置**
   - 运行命令：
     ```bash
     bash /volume1/Downloads/scripts/start_converter.sh
     ```
   - 通过电子邮件发送运行详细信息：✅（可选）

6. **保存并启用任务**

### 配置监控模式（可选）

如果希望持续监控而不是定时执行：

1. **创建监控任务**
   - 任务名称：`磁力链接监控器`
   - 用户账号：`root`
   - 运行命令：
     ```bash
     bash /volume1/Downloads/scripts/start_monitor.sh
     ```

2. **设置为开机启动**
   - 计划：开机

## 📝 使用方法

### 基本使用流程

1. **准备磁力链接文件**
   - 创建`.magnet`文件，内容为磁力链接
   - 文件名示例：`movie.magnet`
   - 文件内容示例：
     ```
     magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a&dn=Example+Movie
     ```

2. **放置文件**
   - 将`.magnet`文件放入`/volume1/Downloads/magnet.files/`目录

3. **等待转换**
   - 任务计划会自动执行转换
   - 或手动运行：`bash /volume1/Downloads/scripts/start_converter.sh`

4. **获取结果**
   - 转换后的`.torrent`文件保存在`/volume1/Downloads/torrent.files/`
   - 原`.magnet`文件会被移动到已处理目录

### 手动运行命令

#### 推荐使用简化版本
```bash
# 单次运行（推荐）
python3 /volume1/Downloads/scripts/synology_magnet_converter_simple.py --once

# 监控模式（每5分钟检查一次）
python3 /volume1/Downloads/scripts/synology_magnet_converter_simple.py --monitor --interval 300

# 查看帮助
python3 /volume1/Downloads/scripts/synology_magnet_converter_simple.py --help
```

#### 标准版本（如果简化版本无法满足需求）
```bash
# 单次运行
python3 /volume1/Downloads/scripts/synology_magnet_converter.py --once

# 监控模式（每5分钟检查一次）
python3 /volume1/Downloads/scripts/synology_magnet_converter.py --monitor --interval 300

# 查看帮助
python3 /volume1/Downloads/scripts/synology_magnet_converter.py --help
```

#### 版本差异说明
- **简化版本**：兼容性更好，适合群晖NAS，处理逻辑更稳定
- **标准版本**：功能更完整，但可能在某些群晖系统上遇到兼容性问题

## 📊 监控和日志

### 日志文件说明

| 日志文件 | 说明 |
|---------|------|
| `magnet_converter.log` | 主程序运行日志 |
| `processed_magnets.log` | 已处理文件记录 |
| `task_execution.log` | 任务执行时间记录 |
| `monitor.log` | 监控模式运行日志 |

### 查看日志

```bash
# 查看主日志
tail -f /volume1/Downloads/logs/magnet_converter.log

# 查看已处理文件
cat /volume1/Downloads/logs/processed_magnets.log

# 查看任务执行记录
tail -20 /volume1/Downloads/logs/task_execution.log

# 查看监控日志
tail -f /volume1/Downloads/logs/monitor.log
```

### 监控脚本状态

```bash
# 检查监控进程
ps aux | grep synology_magnet_converter

# 检查任务计划状态
# 在DSM控制面板 → 任务计划中查看

# 检查目录权限
ls -la /volume1/Downloads/
```

## 🔧 故障排除

### 常见问题

#### 1. libtorrent版本兼容性问题

**问题**：`module 'libtorrent' has no attribute 'settings_pack'`

**解决方案**：
```bash
# 错误：module 'libtorrent' has no attribute 'settings_pack'
# 解决方案：使用简化版本
python3 /volume1/Downloads/scripts/synology_magnet_converter_simple.py --once

# 检查libtorrent版本
python3 -c "import libtorrent as lt; print(getattr(lt, 'version', 'unknown'))"
```

#### 2. pip安装失败

**问题**：`ModuleNotFoundError: No module named 'pip._internal'`

**解决方案**：
```bash
# 重新安装pip
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python3 get-pip.py --user --force-reinstall

# 或使用ensurepip
python3 -m ensurepip --user
```

#### 3. libtorrent安装失败

**问题**：无法安装libtorrent库

**解决方案**：
```bash
# 尝试不同的安装方法
python3 -m pip install --user python-libtorrent
# 或
python3 -m pip install --user libtorrent-python
```

#### 4. 权限问题

**问题**：无法创建目录或写入文件

**解决方案**：
```bash
# 检查权限
ls -la /volume1/Downloads/

# 修改权限
sudo chown -R admin:users /volume1/Downloads/magnet.files
sudo chown -R admin:users /volume1/Downloads/torrent.files
sudo chmod -R 755 /volume1/Downloads/
```

#### 5. 网络连接问题

**问题**：DHT网络连接失败

**解决方案**：
- 检查防火墙设置
- 确保端口6882可用
- 检查网络连接
- 尝试更换DHT路由器
- 简化版本对DHT依赖较少，更稳定

#### 6. 转换失败

**问题**：磁力链接转换失败

**解决方案**：
- 检查磁力链接格式是否正确
- 确保DHT网络连接正常
- 增加超时时间
- 检查磁力链接是否有效

### 版本选择建议

| 问题症状 | 推荐版本 | 说明 |
|---------|---------|------|
| `settings_pack` 错误 | 简化版本 | 兼容旧版本libtorrent |
| `add_torrent_params` 错误 | 简化版本 | 使用兼容性更好的接口 |
| DHT连接不稳定 | 简化版本 | 降低对DHT的依赖 |
| 转换成功率低 | 简化版本 | 更稳定的转换逻辑 |
| 需要完整功能 | 标准版本 | 功能更完整 |

### 性能优化

#### 1. 调整超时时间

编辑脚本中的`DHT_TIMEOUT`参数：
```python
DHT_TIMEOUT = 300  # 增加到5分钟
```

#### 2. 调整监控间隔

```bash
# 减少检查频率以降低系统负载
python3 synology_magnet_converter.py --monitor --interval 600  # 10分钟
```

#### 3. 限制并发数量

在任务计划中设置：
- 不允许多个实例同时运行
- 设置合理的执行间隔

## 🔄 更新和维护

### 更新脚本

1. **备份当前版本**
   ```bash
   cp /volume1/Downloads/scripts/synology_magnet_converter.py \
      /volume1/Downloads/scripts/synology_magnet_converter.py.backup
   ```

2. **上传新版本**
   - 替换主脚本文件
   - 重新设置执行权限

3. **重启服务**
   ```bash
   # 停止监控进程（如果运行）
   pkill -f synology_magnet_converter
   
   # 重新启动
   bash /volume1/Downloads/scripts/start_monitor.sh
   ```

### 清理日志

```bash
# 清理旧日志（保留最近30天）
find /volume1/Downloads/logs/ -name "*.log" -mtime +30 -delete

# 或手动清理
> /volume1/Downloads/logs/magnet_converter.log
> /volume1/Downloads/logs/monitor.log
```

## 📞 技术支持

如果遇到问题，请：

1. 检查日志文件获取详细错误信息
2. 确认所有依赖库已正确安装
3. 验证目录权限和网络连接
4. 参考故障排除章节

## 📄 许可证

本项目基于MIT许可证开源。

---

**注意**：本指南适用于群晖DSM 6.0及以上版本。不同版本的DSM界面可能略有差异，请根据实际情况调整。