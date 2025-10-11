#!/usr/bin/env python3
"""DHT网络管理器 - 用于启动和维护本地DHT网络连接"""

import os
import time
import logging
import threading
import socket
from typing import Optional, Any, Dict

# 尝试导入libtorrent，如果失败则设置为None
try:
    import libtorrent as lt  # type: ignore
    LIBTORRENT_AVAILABLE = True
except ImportError:
    lt = None  # type: ignore
    LIBTORRENT_AVAILABLE = False

logger = logging.getLogger(__name__)

class DHTManager:
    """DHT网络管理器"""
    
    def __init__(self, listen_port: int = 6881, dht_state_file: str = "dht_state.dat", verbose: bool = False):
        """初始化DHT管理器
        
        Args:
            listen_port (int): 监听端口，默认6881
            dht_state_file (str): DHT状态文件路径
            verbose (bool): 是否显示详细日志
        """
        if not LIBTORRENT_AVAILABLE:
            raise ImportError("libtorrent库未安装，无法使用DHT功能")
            
        self.listen_port = listen_port
        self.dht_state_file = dht_state_file
        self.verbose = verbose
        self.session: Optional[Any] = None
        self.running = False
        self._lock = threading.Lock()
        self.stats_thread: Optional[threading.Thread] = None
        
        self._setup_logging()
    
    def _setup_logging(self):
        """设置日志级别"""
        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')
    
    def _find_available_port(self, start_port: int) -> int:
        """查找可用端口
        
        Args:
            start_port (int): 起始端口号
            
        Returns:
            int: 可用的端口号
        """
        for port in range(start_port, start_port + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
                    return port
            except OSError:
                continue
        
        # 如果找不到可用端口，返回原始端口
        logger.warning(f"无法找到可用端口，使用默认端口: {start_port}")
        return start_port
    
    def start(self) -> bool:
        """启动DHT网络
        
        Returns:
            bool: 启动是否成功
        """
        with self._lock:
            if self.running:
                logger.warning("DHT网络已在运行")
                return True
            
            try:
                # 查找可用端口
                self.listen_port = self._find_available_port(self.listen_port)
                
                # 创建session配置
                settings = {
                    'listen_interfaces': f'0.0.0.0:{self.listen_port}',
                    'enable_dht': True,
                    'enable_lsd': True,
                    'enable_upnp': True,
                    'enable_natpmp': True,
                    'dht_bootstrap_nodes': 'router.bittorrent.com:6881,router.utorrent.com:6881,dht.transmissionbt.com:6881'
                }
                
                # 创建session
                self.session = lt.session(settings)  # type: ignore
                
                # 设置alert mask
                # 设置alert mask以接收DHT通知
                try:
                    if hasattr(lt, 'alert') and hasattr(lt.alert, 'category_t'):
                        self.session.set_alert_mask(lt.alert.category_t.dht_notification)  # type: ignore
                except Exception as e:
                    logger.debug(f"设置alert mask失败: {e}")
                
                # 启动DHT
                if hasattr(self.session, 'start_dht'):
                    self.session.start_dht()  # type: ignore
                
                # 加载DHT状态
                self._load_dht_state()
                
                # 添加DHT路由器
                self._add_dht_routers()
                
                self.running = True
                logger.info(f"DHT网络已启动，监听端口: {self.listen_port}")
                return True
                
            except Exception as e:
                logger.error(f"启动DHT网络失败: {e}")
                self.session = None
                return False
    
    def stop(self):
        """停止DHT网络"""
        if not self.running:
            return
        
        self.running = False
        
        if self.session:
            # 保存DHT状态
            self._save_dht_state()
            
            # 停止session
            self.session = None
        
        logger.info("DHT网络已停止")
    
    def _add_dht_routers(self):
        """添加DHT引导路由器"""
        routers = [
            ("router.bittorrent.com", 6881),
            ("router.utorrent.com", 6881),
            ("dht.transmissionbt.com", 6881),
            ("dht.libtorrent.org", 25401),
        ]
        
        for host, port in routers:
            try:
                self.session.add_dht_router(host, port)  # type: ignore
                logger.debug(f"添加DHT路由器: {host}:{port}")
            except Exception as e:
                logger.debug(f"添加DHT路由器失败 {host}:{port}: {e}")
    
    def _load_dht_state(self):
        """加载DHT状态"""
        if os.path.exists(self.dht_state_file):
            try:
                with open(self.dht_state_file, 'rb') as f:
                    dht_state = f.read()
                self.session.load_dht_state(dht_state)  # type: ignore
                logger.debug(f"已加载DHT状态文件: {self.dht_state_file}")
            except Exception as e:
                logger.debug(f"加载DHT状态失败: {e}")
    
    def _save_dht_state(self):
        """保存DHT状态"""
        if self.session:
            try:
                dht_state = self.session.save_dht_state()
                with open(self.dht_state_file, 'wb') as f:
                    f.write(dht_state)
                logger.debug(f"已保存DHT状态文件: {self.dht_state_file}")
            except Exception as e:
                logger.debug(f"保存DHT状态失败: {e}")
    
    def _stats_monitor(self):
        """监控DHT统计信息"""
        while self.running and self.session:
            try:
                stats = self.session.dht_stats()
                logger.debug(f"DHT统计 - 节点数: {stats.nodes}, 全局节点数: {stats.global_nodes}")
                time.sleep(30)  # 每30秒输出一次统计
            except Exception as e:
                logger.debug(f"获取DHT统计失败: {e}")
                break
    
    def get_stats(self) -> Dict[str, Any]:
        """获取DHT统计信息
        
        Returns:
            Dict: DHT统计信息
        """
        if not self.session or not self.running:
            return {}
        
        try:
            # 使用dht_stats获取DHT统计信息
            if hasattr(self.session, 'dht_stats'):
                dht_stats = self.session.dht_stats()
                return {
                    'dht_nodes': getattr(dht_stats, 'nodes', 0),
                    'dht_global_nodes': getattr(dht_stats, 'global_nodes', 0),
                    'dht_running': self.running,
                    'listen_port': self.listen_port
                }
            else:
                # 如果没有dht_stats方法，返回基本信息
                return {
                    'dht_nodes': 0,
                    'dht_global_nodes': 0,
                    'dht_running': self.running,
                    'listen_port': self.listen_port
                }
        except Exception as e:
            logger.error(f"获取DHT统计失败: {e}")
            return {
                'dht_nodes': 0,
                'dht_global_nodes': 0,
                'dht_running': self.running,
                'listen_port': self.listen_port
            }
    
    def is_ready(self) -> bool:
        """检查DHT网络是否就绪
        
        Returns:
            bool: DHT网络是否就绪
        """
        if not self.running or not self.session:
            return False
        
        try:
            stats = self.session.dht_stats()
            # 当有足够的节点连接时认为就绪
            return stats.nodes > 10
        except:
            return False
    
    def wait_for_ready(self, timeout: int = 60) -> bool:
        """等待DHT网络就绪
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            bool: 是否在超时前就绪
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.is_ready():
                logger.info("DHT网络已就绪")
                return True
            
            if self.verbose:
                stats = self.get_stats()
                logger.debug(f"等待DHT就绪... 当前节点数: {stats.get('nodes', 0)}")
            
            time.sleep(2)
        
        logger.warning(f"DHT网络在{timeout}秒内未就绪")
        return False
    
    def get_session(self) -> Optional[Any]:
        """获取libtorrent session对象
        
        Returns:
            Optional[lt.session]: session对象，如果未启动则返回None
        """
        return self.session if self.running else None


# 全局DHT管理器实例
_global_dht_manager: Optional[DHTManager] = None

def get_global_dht_manager() -> DHTManager:
    """获取全局DHT管理器实例"""
    global _global_dht_manager
    if _global_dht_manager is None:
        _global_dht_manager = DHTManager()
    return _global_dht_manager

def start_global_dht(verbose: bool = False) -> bool:
    """启动全局DHT网络"""
    manager = get_global_dht_manager()
    manager.verbose = verbose
    return manager.start()

def stop_global_dht():
    """停止全局DHT网络"""
    global _global_dht_manager
    if _global_dht_manager:
        _global_dht_manager.stop()
        _global_dht_manager = None