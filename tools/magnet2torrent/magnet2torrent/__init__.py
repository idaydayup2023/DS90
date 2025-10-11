# magnet2torrent package

__version__ = '1.0.0'

# 尝试导入核心模块，如果依赖不满足则设置为None
try:
    from .converter import Magnet2TorrentConverter
    from .dht_manager import DHTManager, get_global_dht_manager
    LIBTORRENT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: libtorrent not available, some features will be disabled: {e}")
    Magnet2TorrentConverter = None
    DHTManager = None
    get_global_dht_manager = None
    LIBTORRENT_AVAILABLE = False

__all__ = ['Magnet2TorrentConverter', 'DHTManager', 'get_global_dht_manager', 'LIBTORRENT_AVAILABLE']