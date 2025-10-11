# DHT网络功能使用指南

本项目现在支持本地启动和维护一个持久的DHT网络，可以在多个磁力链接转换之间共享，提高转换效率。

## 功能特点

- **共享DHT网络**: 多个转换器实例可以共享同一个DHT网络
- **持久连接**: DHT网络可以保持长时间运行，积累更多节点
- **自动管理**: 自动处理DHT网络的启动、停止和状态监控
- **向后兼容**: 支持传统的独立session模式

## 基本使用

### 1. 使用共享DHT进行转换

```python
from magnet2torrent.converter import Magnet2TorrentConverter

# 创建使用共享DHT的转换器
converter = Magnet2TorrentConverter(
    timeout=30, 
    verbose=True, 
    use_shared_dht=True  # 启用共享DHT
)

# 转换磁力链接
magnet_uri = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
result = converter.convert(magnet_uri, "./downloads")
```

### 2. 手动管理DHT网络

```python
from magnet2torrent.dht_manager import get_global_dht_manager, start_global_dht, stop_global_dht

# 启动全局DHT网络
start_global_dht()

# 获取DHT管理器
dht_manager = get_global_dht_manager()
print(f"DHT状态: {'运行中' if dht_manager.running else '已停止'}")
print(f"监听端口: {dht_manager.listen_port}")

# 获取统计信息
stats = dht_manager.get_stats()
print(f"DHT节点数: {stats.get('dht_nodes', 0)}")

# 停止DHT网络
stop_global_dht()
```

### 3. 解析磁力链接信息

```python
from magnet2torrent.converter import Magnet2TorrentConverter

converter = Magnet2TorrentConverter()
magnet_uri = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a"

# 解析磁力链接详细信息
info = converter.parse_magnet_info(magnet_uri)
print(f"Info Hash: {info['info_hash']}")
print(f"文件名: {info['name']}")
print(f"Tracker数量: {len(info['trackers'])}")
```

## 示例脚本

项目提供了几个示例脚本：

### 1. DHT网络测试 (`test_dht_network.py`)

```bash
python test_dht_network.py
```

测试DHT网络的启动、连接和转换功能。

### 2. DHT状态监控 (`dht_monitor.py`)

```bash
python dht_monitor.py
```

实时监控DHT网络状态，显示节点数量和连接信息。按Ctrl+C停止。

### 3. 使用示例 (`example_shared_dht.py`)

```bash
python example_shared_dht.py
```

演示各种DHT使用场景，包括基本使用、批量转换等。

## DHT网络优势

### 1. 提高转换成功率

- **更多节点**: 共享DHT网络可以积累更多的节点连接
- **持久连接**: 长时间运行的DHT网络有更好的连接性
- **资源共享**: 多个转换任务共享同一个网络资源

### 2. 减少资源消耗

- **避免重复启动**: 不需要为每个转换创建新的DHT网络
- **端口复用**: 多个转换共享同一个监听端口
- **内存优化**: 减少多个session的内存占用

### 3. 更好的性能

- **快速启动**: 已建立的DHT网络可以立即使用
- **预热效果**: 网络连接预热后转换速度更快
- **批量处理**: 适合批量转换多个磁力链接

## 配置选项

### 转换器参数

```python
converter = Magnet2TorrentConverter(
    timeout=60,           # 转换超时时间（秒）
    verbose=False,        # 是否显示详细日志
    use_shared_dht=True   # 是否使用共享DHT（默认True）
)
```

### DHT管理器参数

DHT管理器会自动选择可用端口（默认从6881开始），并配置最佳的DHT设置。

## 注意事项

### 1. 网络环境

- DHT网络需要能够连接到互联网
- 防火墙可能会阻止DHT连接
- 某些网络环境可能限制P2P流量

### 2. 转换超时

- 即使使用共享DHT，某些磁力链接仍可能转换失败
- 这通常是由于：
  - 磁力链接本身无效
  - 没有足够的种子节点
  - 网络连接问题

### 3. 资源使用

- DHT网络会持续使用一定的网络带宽
- 长时间运行会积累更多内存使用
- 建议在不需要时停止DHT网络

## 故障排除

### 1. DHT启动失败

```python
# 检查端口是否被占用
dht_manager = get_global_dht_manager()
if not dht_manager.start():
    print("DHT启动失败，可能端口被占用")
```

### 2. 转换超时

```python
# 增加超时时间
converter = Magnet2TorrentConverter(timeout=120)

# 或使用独立session
converter = Magnet2TorrentConverter(use_shared_dht=False)
```

### 3. 统计信息获取失败

这是由于libtorrent版本差异导致的，不影响DHT网络的实际功能。

## 最佳实践

1. **长期运行**: 让DHT网络运行更长时间以积累更多节点
2. **批量处理**: 一次性处理多个磁力链接时使用共享DHT
3. **监控状态**: 使用监控脚本观察DHT网络健康状态
4. **合理超时**: 根据网络环境设置合适的超时时间
5. **资源清理**: 完成任务后及时停止DHT网络

## API参考

### DHTManager类

- `start()`: 启动DHT网络
- `stop()`: 停止DHT网络
- `get_stats()`: 获取统计信息
- `get_session()`: 获取libtorrent session
- `wait_for_ready(timeout)`: 等待DHT就绪

### 全局函数

- `get_global_dht_manager()`: 获取全局DHT管理器实例
- `start_global_dht()`: 启动全局DHT网络
- `stop_global_dht()`: 停止全局DHT网络

这个DHT功能为磁力链接转换提供了更稳定和高效的网络基础设施。