import os
import time
import logging
import libtorrent as lt  # type: ignore
from urllib.parse import urlparse, parse_qs
import binascii
from .dht_manager import get_global_dht_manager

logger = logging.getLogger(__name__)

class Magnet2TorrentConverter:
    """将磁力链接转换为torrent文件的转换器"""
    
    def __init__(self, timeout=60, verbose=False, use_shared_dht=True):
        """初始化转换器
        
        Args:
            timeout (int): 转换超时时间（秒）
            verbose (bool): 是否显示详细日志
            use_shared_dht (bool): 是否使用共享的DHT网络
        """
        self.timeout = timeout
        self.verbose = verbose
        self.use_shared_dht = use_shared_dht
        self._setup_logging()
        
    def _setup_logging(self):
        """设置日志级别"""
        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')
    
    def _parse_magnet_uri(self, magnet_uri):
        """解析磁力链接
        
        Args:
            magnet_uri (str): 磁力链接
            
        Returns:
            str: 解析出的info_hash
        """
        # 检查磁力链接格式
        if not magnet_uri.startswith('magnet:?'):
            raise ValueError("无效的磁力链接格式")
            
        # 解析URL参数
        parsed = urlparse(magnet_uri)
        params = parse_qs(parsed.query)
        
        # 提取info_hash
        if 'xt' not in params:
            raise ValueError("磁力链接中缺少xt参数")
            
        xt = params['xt'][0]
        if not xt.startswith('urn:btih:'):
            raise ValueError("不支持的磁力链接格式，仅支持BitTorrent info hash")
            
        info_hash = xt[9:].lower()
        if len(info_hash) != 40:
            # 尝试将base32编码的info_hash转换为十六进制
            try:
                # 将base32转换为bytes，再转换为十六进制字符串
                info_hash = binascii.b2a_hex(binascii.a2b_base32(info_hash.upper())).decode()  # type: ignore
            except Exception as e:
                raise ValueError(f"无效的info hash: {e}")
                
        logger.debug(f"解析到的info_hash: {info_hash}")
        return info_hash
    
    def parse_magnet_info(self, magnet_uri):
        """解析磁力链接的详细信息
        
        Args:
            magnet_uri (str): 磁力链接
            
        Returns:
            dict: 包含磁力链接信息的字典
        """
        # 解析URL参数
        parsed = urlparse(magnet_uri)
        params = parse_qs(parsed.query)
        
        # 获取info_hash
        info_hash = self._parse_magnet_uri(magnet_uri)
        
        # 提取其他信息
        info = {
            'info_hash': info_hash,
            'name': params.get('dn', ['未知'])[0] if 'dn' in params else '未知',
            'trackers': params.get('tr', []),
            'web_seeds': params.get('ws', []),
            'magnet_uri': magnet_uri
        }
        
        return info
    
    def convert(self, magnet_uri, output_dir="."):
        """将磁力链接转换为torrent文件
        
        Args:
            magnet_uri (str): 磁力链接
            output_dir (str): 输出目录
            
        Returns:
            str: 保存的torrent文件路径
        """
        # 确保输出目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 解析磁力链接
        info_hash = self._parse_magnet_uri(magnet_uri)
        
        # 选择使用共享DHT还是创建新的session
        if self.use_shared_dht:
            dht_manager = get_global_dht_manager()
            if not dht_manager.running:
                logger.info("启动共享DHT网络...")
                if not dht_manager.start():
                    logger.warning("启动共享DHT失败，使用独立session")
                    self.use_shared_dht = False
                else:
                    logger.info("等待DHT网络就绪...")
                    dht_manager.wait_for_ready(30)
            
            ses = dht_manager.get_session()
            if ses is None:
                logger.warning("无法获取共享DHT session，使用独立session")
                self.use_shared_dht = False
        
        if not self.use_shared_dht:
            # 创建独立session
            ses = lt.session({
                'listen_interfaces': '0.0.0.0:6881',
                'enable_dht': True,
                'enable_lsd': True,
                'enable_upnp': True,
                'enable_natpmp': True,
            })
            
            # 添加DHT路由器
            ses.add_dht_router("router.bittorrent.com", 6881)
            ses.add_dht_router("router.utorrent.com", 6881)
            ses.add_dht_router("dht.transmissionbt.com", 6881)
            
            # 启动DHT
            ses.start_dht()
        
        # 添加磁力链接
        params = lt.parse_magnet_uri(magnet_uri)
        params.save_path = output_dir  # 设置保存路径
        handle = ses.add_torrent(params)  # type: ignore
        
        logger.info(f"开始下载元数据，超时时间: {self.timeout}秒")
        start_time = time.time()
        
        # 等待元数据下载完成
        while not handle.has_metadata():
            time.sleep(1)
            elapsed = time.time() - start_time
            
            if self.verbose:
                logger.debug(f"等待元数据... 已用时: {elapsed:.1f}秒")
                
            if elapsed > self.timeout:
                ses.remove_torrent(handle)  # type: ignore
                raise TimeoutError(f"下载元数据超时（{self.timeout}秒）")
        
        logger.info("元数据下载完成")
        
        # 获取torrent信息
        torrent_info = handle.get_torrent_info()
        torrent_file = lt.create_torrent(torrent_info)
        torrent_data = lt.bencode(torrent_file.generate())
        
        # 生成文件名
        name = torrent_info.name() if torrent_info.name() else info_hash
        file_path = os.path.join(output_dir, f"{name}.torrent")
        
        # 保存torrent文件
        with open(file_path, 'wb') as f:
            f.write(torrent_data)
        
        # 移除torrent
        ses.remove_torrent(handle)  # type: ignore
        
        logger.info(f"已保存torrent文件: {file_path}")
        return file_path