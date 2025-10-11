# 磁力链接转种子文件工具集

这是一个综合性的磁力链接转种子文件解决方案，提供多种可靠的转换方法，解决了libtorrent在某些环境下的稳定性问题。

## 🌟 特性

- **多种转换方案**: Aria2、qBittorrent Web API、纯Python DHT客户端
- **高可靠性**: 解决libtorrent稳定性问题
- **易于使用**: 提供统一的命令行接口
- **跨平台**: 支持Windows、macOS、Linux
- **详细日志**: 完整的转换过程记录
- **模块化设计**: 清晰的目录结构，易于维护

## 🚀 快速开始

### 统一入口使用

```bash
# 查看所有可用转换器
python3 magnet2torrent.py

# 使用Aria2转换器 (推荐)
python3 magnet2torrent.py aria2 --magnet "magnet:?xt=urn:btih:..." --output ./torrents/

# 使用qBittorrent转换器
python3 magnet2torrent.py qbittorrent --magnet "magnet:?xt=urn:btih:..." --host localhost --port 8080

# 使用DHT客户端
python3 magnet2torrent.py dht --magnet "magnet:?xt=urn:btih:..." --output ./torrents/

# 提取磁力链接信息
python3 magnet2torrent.py info --magnet "magnet:?xt=urn:btih:..." --extract --json
```

### 运行演示

```bash
# Aria2演示
python3 demos/aria2_demo.py

# qBittorrent演示  
python3 demos/qbittorrent_demo.py

# 信息提取演示
python3 demos/info_extractor_demo.py
```

## 📁 项目结构

```
magnet2torrent/
├── magnet2torrent.py              # 统一主入口
├── converters/                    # 转换器模块
│   ├── aria2_converter.py         # Aria2转换器
│   ├── qbittorrent_converter.py   # qBittorrent转换器
│   ├── dht_converter.py           # 纯Python DHT客户端
│   └── info_extractor.py          # 磁力链接信息提取
├── demos/                         # 演示脚本
│   ├── aria2_demo.py              # Aria2演示
│   ├── qbittorrent_demo.py        # qBittorrent演示
│   └── info_extractor_demo.py     # 信息提取演示
├── tests/                         # 测试文件
├── configs/                       # 配置文件
│   └── aria2.conf                 # Aria2配置
├── docs/                          # 文档目录
├── legacy/                        # 旧版本和实验性文件
├── aria2_downloads/               # Aria2下载目录
├── test_input/                    # 测试输入文件
└── README.md                      # 主说明文档
```

## 🔧 依赖安装

```bash
pip3 install requests bencode.py
```

## 📖 详细文档

- [Aria2转换器说明](aria2_README.md)
- [qBittorrent转换器说明](qbittorrent_README.md)  
- [DHT客户端说明](docs/DHT_README.md)
- [Synology部署指南](docs/SYNOLOGY_DEPLOYMENT_GUIDE.md)

## 🎯 使用场景

1. **批量转换**: 处理大量磁力链接
2. **自动化脚本**: 集成到自动化工作流
3. **NAS部署**: 在群晖等NAS设备上运行
4. **开发调试**: 分析磁力链接结构

## ⚠️ 注意事项

- 确保网络连接稳定
- 某些磁力链接可能需要较长时间才能获取到种子信息
- 建议使用Aria2方案，稳定性最佳

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目。

## 📄 许可证

MIT License