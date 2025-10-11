# 🌐 bt_crawler - BT种子爬取与管理工具

bt_crawler是DS90项目的BT种子爬取与管理工具，提供电影种子的自动化爬取、处理和下载功能。

## ✨ 功能特点

- 🔍 **YTS电影种子爬取**: 自动从YTS网站爬取最新电影种子
- 🧲 **磁力链接转种子**: 将磁力链接转换为种子文件
- 📁 **智能文件命名**: 规范化种子文件名，便于管理
- 🔄 **多平台支持**: 适配Windows、MacOS和Linux/NAS系统
- 🌍 **代理支持**: 可配置代理服务器访问被限制的资源

## 🚀 使用方法

### YTS电影种子爬取

```bash
cd tools/bt_crawler
python3 yts.py
```

### 磁力链接转种子

```bash
cd tools/bt_crawler
python3 torrent.py 
```

## ⚙️ 配置说明

### 代理设置

在`yts.py`和`torrent.py`中可以配置代理服务器：

```python
# 使用代理
proxies = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890',
}

# 不使用代理
proxies = {}
```

### 种子保存路径

根据不同操作系统，可以在`torrent.py`中配置种子文件保存路径：

```python
if platform.system() == 'Windows':
    torrents_path = "F:\\Downloads\\torrent.files"
elif platform.system() == 'Mac':
    torrents_path = "/Users/jun/OneDrive/torrent.files"
else:  # Linux/Unix系统   
    torrents_path = "/volume1/Downloads/torrent.files"
```

## 🔧 依赖项

- Python 3.7+
- requests
- BeautifulSoup4
- aria2c (用于磁力链接转换)

## 📝 注意事项

- 请确保已安装aria2c并添加到系统PATH中
- 使用前请确认种子保存路径已正确配置
- 爬取操作可能需要代理服务器，请根据网络环境配置

## 🔗 相关链接

- [DS90项目主页](https://github.com/idaydayup2023/DS90)
- [aria2下载页面](https://github.com/aria2/aria2/releases)