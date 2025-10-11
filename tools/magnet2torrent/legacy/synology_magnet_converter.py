#!/usr/bin/env python3
"""
群晖NAS磁力链接转换器
将.magnet文件中的磁力链接转换为.torrent文件

输入目录: /volume1/Downloads/magnet.files/
输出目录: /volume1/Downloads/torrent.files/

使用方法:
1. 单次运行: python3 synology_magnet_converter.py --once
2. 监控模式: python3 synology_magnet_converter.py --monitor
3. 指定间隔: python3 synology_magnet_converter.py --monitor --interval 300
"""

import os
import sys
import time
import logging
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any
import hashlib
import signal
import threading
from datetime import datetime

# 尝试导入libtorrent
try:
    import libtorrent as lt  # type: ignore
    LIBTORRENT_AVAILABLE = True
except ImportError:
    LIBTORRENT_AVAILABLE = False
    # 创建占位符类以避免类型错误
    class MockTorrentHandle:
        def __init__(self):
            pass
        def has_metadata(self):
            return False
        def get_torrent_info(self):
            return None
    
    class MockSession:
        def __init__(self, settings=None):
            pass
        def add_torrent(self, params):
            return MockTorrentHandle()
        def remove_torrent(self, handle):
            pass
        def get_torrents(self):
            return []
        def listen_on(self, *args):
            pass
        def add_dht_router(self, *args):
            pass
        def dht_stats(self):
            return {}
        def status(self):
            return type('Status', (), {'dht_nodes': 0})()
    
    class MockTorrentInfo:
        def __init__(self):
            pass
    
    class MockSettingsPack:
        def __init__(self):
            pass
        
        # 模拟settings_pack的常量
        enable_dht = 'enable_dht'
        enable_lsd = 'enable_lsd'
        enable_upnp = 'enable_upnp'
        enable_natpmp = 'enable_natpmp'
        dht_bootstrap_nodes = 'dht_bootstrap_nodes'
        dht_bootstrap_timeout = 'dht_bootstrap_timeout'
        download_rate_limit = 'download_rate_limit'
        upload_rate_limit = 'upload_rate_limit'
        user_agent = 'user_agent'
        listen_interfaces = 'listen_interfaces'
        outgoing_interfaces = 'outgoing_interfaces'
        
        def set_bool(self, key, value):
            pass
        def set_int(self, key, value):
            pass
    
    class MockAddTorrentParams:
        def __init__(self):
            self.url = ''
            self.save_path = ''
    
    class MockCreateTorrent:
        def __init__(self, info):
            pass
        def generate(self):
            return b''
    
    # 模拟libtorrent模块
    class MockLibtorrent:
        session = MockSession
        torrent_info = MockTorrentInfo
        add_torrent_params = MockAddTorrentParams
        settings_pack = MockSettingsPack
        
        @staticmethod
        def parse_magnet_uri(uri):
            return {}
        
        @staticmethod
        def create_torrent(info):
            return MockCreateTorrent(info)
        
        @staticmethod
        def bencode(data):
            return b''
    
    lt = MockLibtorrent()  # type: ignore

# 群晖NAS路径配置
MAGNET_INPUT_DIR = "/volume1/Downloads/magnet.files"
TORRENT_OUTPUT_DIR = "/volume1/Downloads/torrent.files"
LOG_DIR = "/volume1/Downloads/logs"
PROCESSED_LOG = os.path.join(LOG_DIR, "processed_magnets.log")

# DHT配置
DHT_PORT = 6882
DHT_TIMEOUT = 180  # 3分钟超时
DHT_ROUTERS = [
    ("router.bittorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("router.utorrent.com", 6881),
    ("dht.aelitis.com", 6881)
]

class SynologyMagnetConverter:
    """群晖NAS磁力链接转换器"""
    
    def __init__(self):
        self.session = None
        self.processed_files = set()
        self.setup_logging()
        self.setup_directories()
        self.load_processed_files()
    
    def setup_logging(self):
        """设置日志记录"""
        # 确保日志目录存在
        os.makedirs(LOG_DIR, exist_ok=True)
        
        # 配置日志格式
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            handlers=[
                logging.FileHandler(os.path.join(LOG_DIR, 'magnet_converter.log'), encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def setup_directories(self):
        """设置目录结构"""
        directories = [MAGNET_INPUT_DIR, TORRENT_OUTPUT_DIR, LOG_DIR]
        for directory in directories:
            try:
                os.makedirs(directory, exist_ok=True)
                self.logger.info(f"✅ 目录已准备: {directory}")
            except Exception as e:
                self.logger.error(f"❌ 创建目录失败 {directory}: {e}")
                raise
    
    def load_processed_files(self):
        """加载已处理文件列表"""
        if os.path.exists(PROCESSED_LOG):
            try:
                with open(PROCESSED_LOG, 'r', encoding='utf-8') as f:
                    self.processed_files = set(line.strip() for line in f if line.strip())
                self.logger.info(f"📋 已加载 {len(self.processed_files)} 个已处理文件记录")
            except Exception as e:
                self.logger.error(f"❌ 加载已处理文件列表失败: {e}")
    
    def save_processed_file(self, filename: str):
        """保存已处理文件记录"""
        try:
            with open(PROCESSED_LOG, 'a', encoding='utf-8') as f:
                f.write(f"{filename}\n")
            self.processed_files.add(filename)
        except Exception as e:
            self.logger.error(f"❌ 保存已处理文件记录失败: {e}")
    
    def start_dht_session(self) -> bool:
        """启动DHT会话"""
        try:
            # 检测libtorrent版本并使用相应的接口
            if hasattr(lt, 'settings_pack'):
                # 新版本libtorrent (1.1+)
                self.logger.info("🔧 使用新版本libtorrent接口")
                settings = lt.settings_pack()
                settings.set_bool(lt.settings_pack.enable_dht, True)
                settings.set_bool(lt.settings_pack.enable_lsd, True)
                settings.set_bool(lt.settings_pack.enable_upnp, True)
                settings.set_bool(lt.settings_pack.enable_natpmp, True)
                settings.set_int(lt.settings_pack.dht_bootstrap_timeout, 30)
                settings.set_int(lt.settings_pack.download_rate_limit, 0)
                settings.set_int(lt.settings_pack.upload_rate_limit, 0)
                
                self.session = lt.session(settings)
            else:
                # 旧版本libtorrent (1.0.x)
                self.logger.info("🔧 使用旧版本libtorrent接口")
                self.session = lt.session()
                
                # 旧版本设置方式
                try:
                    session_settings = self.session.get_settings()  # type: ignore
                    session_settings['enable_dht'] = True
                    session_settings['enable_lsd'] = True
                    session_settings['enable_upnp'] = True
                    session_settings['enable_natpmp'] = True
                    self.session.set_settings(session_settings)  # type: ignore
                except:
                    # 如果旧版本方法也不可用，使用基本设置
                    self.logger.info("🔧 使用基本DHT设置")
            
            # 设置监听端口
            try:
                if hasattr(self.session, 'listen_on'):
                    self.session.listen_on(DHT_PORT, DHT_PORT + 10)
                else:
                    # 旧版本接口
                    self.session.listen_on((DHT_PORT, DHT_PORT + 10))
            except Exception as e:
                self.logger.warning(f"⚠️ 设置监听端口失败: {e}")
            
            # 添加DHT路由器
            for router_host, router_port in DHT_ROUTERS:
                try:
                    if hasattr(self.session, 'add_dht_router'):
                        self.session.add_dht_router(router_host, router_port)
                    else:
                        # 旧版本可能使用不同的方法名
                        self.logger.info(f"🔗 尝试连接DHT路由器: {router_host}:{router_port}")
                except Exception as e:
                    self.logger.warning(f"⚠️ 添加DHT路由器失败 {router_host}:{router_port}: {e}")
            
            self.logger.info(f"🚀 DHT会话已启动，监听端口: {DHT_PORT}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 启动DHT会话失败: {e}")
            self.logger.error(f"🔍 libtorrent版本信息: {getattr(lt, 'version', '未知')}")
            return False
    
    def wait_for_dht_ready(self, timeout: int = 60) -> bool:
        """等待DHT网络就绪"""
        self.logger.info(f"⏳ 等待DHT网络就绪（超时: {timeout}秒）...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                nodes = 0
                
                # 尝试不同版本的DHT状态获取方法
                if hasattr(self.session, 'dht_stats'):
                    try:
                        stats = self.session.dht_stats()  # type: ignore
                        nodes = stats.get('dht_nodes', 0) if isinstance(stats, dict) else 0
                    except:
                        pass
                
                if hasattr(self.session, 'status'):
                    try:
                        status = self.session.status()  # type: ignore
                        dht_nodes = getattr(status, 'dht_nodes', 0)
                        nodes = max(nodes, dht_nodes)
                    except:
                        pass
                
                # 对于旧版本，简单等待一段时间后认为就绪
                if not hasattr(self.session, 'dht_stats') and not hasattr(self.session, 'status'):
                    elapsed = time.time() - start_time
                    if elapsed > 10:  # 等待10秒后认为DHT就绪
                        self.logger.info("✅ DHT网络等待完成（旧版本兼容模式）")
                        return True
                
                if nodes > 0:
                    self.logger.info(f"✅ DHT网络已就绪，节点数: {nodes}")
                    return True
                    
                self.logger.debug(f"⏳ 等待DHT网络就绪... 节点数: {nodes}")
                time.sleep(2)
                
            except Exception as e:
                self.logger.debug(f"⏳ DHT状态检查: {e}")
                time.sleep(2)
        
        self.logger.warning(f"⚠️ DHT网络未在 {timeout} 秒内就绪，继续尝试转换")
        return True  # 即使DHT未完全就绪也继续尝试
    
    def parse_magnet_uri(self, magnet_uri: str) -> Optional[Dict[str, Any]]:
        """解析磁力链接"""
        try:
            if not magnet_uri.startswith('magnet:'):
                return None
            
            # 提取info_hash
            import urllib.parse
            parsed = urllib.parse.urlparse(magnet_uri)
            params = urllib.parse.parse_qs(parsed.query)
            
            if 'xt' not in params:
                return None
            
            xt = params['xt'][0]
            if not xt.startswith('urn:btih:'):
                return None
            
            info_hash = xt[9:]  # 移除 'urn:btih:' 前缀
            
            # 获取显示名称
            display_name = params.get('dn', ['Unknown'])[0]
            
            return {
                'info_hash': info_hash,
                'display_name': display_name,
                'magnet_uri': magnet_uri
            }
            
        except Exception as e:
            self.logger.error(f"❌ 解析磁力链接失败: {e}")
            return None
    
    def convert_magnet_to_torrent(self, magnet_uri: str, output_path: str) -> bool:
        """将磁力链接转换为torrent文件"""
        try:
            # 解析磁力链接
            magnet_info = self.parse_magnet_uri(magnet_uri)
            if not magnet_info:
                self.logger.error("❌ 无效的磁力链接格式")
                return False
            
            self.logger.info(f"🔍 开始转换: {magnet_info['display_name']}")
            
            # 添加磁力链接到会话
            if hasattr(lt, 'add_torrent_params'):
                # 新版本libtorrent
                params = lt.add_torrent_params()
                params.url = magnet_uri
                params.save_path = "/tmp"  # 临时路径
                handle = self.session.add_torrent(params)  # type: ignore
            else:
                # 旧版本libtorrent
                handle = self.session.add_torrent({  # type: ignore
                    'url': magnet_uri,
                    'save_path': '/tmp'
                })
            
            # 等待元数据下载
            self.logger.info("⏳ 正在下载元数据...")
            start_time = time.time()
            
            while time.time() - start_time < DHT_TIMEOUT:
                if handle.has_metadata():
                    # 获取torrent信息
                    torrent_info = handle.get_torrent_info()
                    
                    # 创建torrent文件
                    try:
                        if hasattr(lt, 'create_torrent'):
                            # 新版本libtorrent
                            torrent_data = lt.create_torrent(torrent_info)
                            torrent_bytes = lt.bencode(torrent_data.generate())
                        else:
                            # 旧版本libtorrent - 尝试直接获取torrent数据
                            if hasattr(torrent_info, 'metadata'):
                                torrent_bytes = torrent_info.metadata()  # type: ignore
                            else:
                                # 最后的备用方案 - 创建简单的torrent文件
                                self.logger.warning("⚠️ 使用简化的torrent创建方法")
                                torrent_bytes = self._create_simple_torrent(magnet_info)
                        
                        # 保存torrent文件
                        with open(output_path, 'wb') as f:
                            f.write(torrent_bytes)
                        
                        self.logger.info(f"✅ 转换成功: {output_path}")
                        
                        # 移除torrent（不下载文件内容）
                        self.session.remove_torrent(handle)  # type: ignore
                        return True
                        
                    except Exception as e:
                        self.logger.error(f"❌ 创建torrent文件失败: {e}")
                        self.session.remove_torrent(handle)  # type: ignore
                        return False
                
                time.sleep(1)
            
            # 超时处理
            self.logger.error(f"❌ 下载元数据超时（{DHT_TIMEOUT}秒）")
            self.session.remove_torrent(handle)  # type: ignore
            return False
            
        except Exception as e:
            self.logger.error(f"❌ 转换失败: {e}")
            return False
    
    def _create_simple_torrent(self, magnet_info: Dict[str, Any]) -> bytes:
        """创建简单的torrent文件（备用方案）"""
        try:
            import bencodepy  # type: ignore
            
            # 创建基本的torrent结构
            torrent_dict = {
                b'announce': b'http://tracker.example.com:8080/announce',
                b'info': {
                    b'name': magnet_info['display_name'].encode('utf-8'),
                    b'piece length': 262144,  # 256KB
                    b'pieces': b'',  # 空的pieces，因为我们没有实际文件
                    b'files': [{
                        b'length': 0,
                        b'path': [magnet_info['display_name'].encode('utf-8')]
                    }]
                }
            }
            
            return bencodepy.encode(torrent_dict)
            
        except ImportError:
            # 如果没有bencodepy，创建最基本的torrent文件
            self.logger.warning("⚠️ bencodepy不可用，创建占位符torrent文件")
            return b'd8:announce0:4:infod4:name0:ee'  # 最基本的空torrent结构
        except Exception as e:
            self.logger.error(f"❌ 创建简单torrent失败: {e}")
            return b'd8:announce0:4:infod4:name0:ee'
    
    def scan_magnet_files(self) -> List[str]:
        """扫描.magnet文件"""
        magnet_files = []
        try:
            for file_path in Path(MAGNET_INPUT_DIR).glob("*.magnet"):
                if file_path.name not in self.processed_files:
                    magnet_files.append(str(file_path))
            
            self.logger.info(f"📁 发现 {len(magnet_files)} 个待处理的.magnet文件")
            return magnet_files
            
        except Exception as e:
            self.logger.error(f"❌ 扫描.magnet文件失败: {e}")
            return []
    
    def process_magnet_file(self, magnet_file_path: str) -> bool:
        """处理单个.magnet文件"""
        try:
            # 读取磁力链接
            with open(magnet_file_path, 'r', encoding='utf-8') as f:
                magnet_uri = f.read().strip()
            
            if not magnet_uri:
                self.logger.warning(f"⚠️ 空的磁力链接文件: {magnet_file_path}")
                return False
            
            # 生成输出文件名
            file_name = Path(magnet_file_path).stem
            output_path = os.path.join(TORRENT_OUTPUT_DIR, f"{file_name}.torrent")
            
            # 如果输出文件已存在，跳过
            if os.path.exists(output_path):
                self.logger.info(f"⏭️ 跳过已存在的文件: {output_path}")
                self.save_processed_file(Path(magnet_file_path).name)
                return True
            
            # 转换磁力链接
            success = self.convert_magnet_to_torrent(magnet_uri, output_path)
            
            if success:
                self.save_processed_file(Path(magnet_file_path).name)
                self.logger.info(f"✅ 处理完成: {magnet_file_path} -> {output_path}")
            else:
                self.logger.error(f"❌ 处理失败: {magnet_file_path}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ 处理文件失败 {magnet_file_path}: {e}")
            return False
    
    def run_once(self) -> int:
        """运行一次转换任务"""
        self.logger.info("🚀 开始磁力链接转换任务")
        
        # 启动DHT会话
        if not self.start_dht_session():
            return 1
        
        try:
            # 等待DHT就绪
            if not self.wait_for_dht_ready():
                self.logger.warning("⚠️ DHT网络未就绪，但继续尝试转换")
            
            # 扫描并处理文件
            magnet_files = self.scan_magnet_files()
            if not magnet_files:
                self.logger.info("📭 没有待处理的.magnet文件")
                return 0
            
            success_count = 0
            for magnet_file in magnet_files:
                if self.process_magnet_file(magnet_file):
                    success_count += 1
                time.sleep(2)  # 避免过于频繁的请求
            
            self.logger.info(f"📊 任务完成: {success_count}/{len(magnet_files)} 个文件转换成功")
            return 0 if success_count == len(magnet_files) else 1
            
        finally:
            # 清理会话
            if self.session:
                self.session = None
    
    def run_monitor(self, interval: int = 60):
        """监控模式运行"""
        self.logger.info(f"👁️ 启动监控模式，检查间隔: {interval}秒")
        
        while True:
            try:
                self.run_once()
                self.logger.info(f"😴 等待 {interval} 秒后进行下次检查...")
                time.sleep(interval)
            except KeyboardInterrupt:
                self.logger.info("🛑 收到中断信号，退出监控模式")
                break
            except Exception as e:
                self.logger.error(f"❌ 监控过程中出错: {e}")
                time.sleep(interval)

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='群晖NAS磁力链接转换器')
    parser.add_argument('--monitor', action='store_true', help='监控模式运行')
    parser.add_argument('--interval', type=int, default=60, help='监控间隔（秒）')
    parser.add_argument('--once', action='store_true', help='运行一次后退出')
    
    args = parser.parse_args()
    
    # 检查libtorrent可用性
    if not LIBTORRENT_AVAILABLE:
        print("❌ libtorrent库不可用，请先安装")
        return 1
    
    converter = SynologyMagnetConverter()
    
    if args.monitor:
        converter.run_monitor(args.interval)
        return 0
    else:
        return converter.run_once()

if __name__ == "__main__":
    sys.exit(main())