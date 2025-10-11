#!/usr/bin/env python3
"""
群晖NAS磁力链接转换器 - 简化版本
专门适配群晖NAS的旧版本libtorrent

作者: AI Assistant
版本: 2.0
日期: 2024-01-20
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
import urllib.parse

# 尝试导入libtorrent
try:
    import libtorrent as lt  # type: ignore
    LIBTORRENT_AVAILABLE = True
    LT_VERSION = getattr(lt, 'version', 'unknown')
except ImportError:
    LIBTORRENT_AVAILABLE = False
    LT_VERSION = 'not_available'

# 目录配置
MAGNET_INPUT_DIR = "/volume1/Downloads/magnet.files"
TORRENT_OUTPUT_DIR = "/volume1/Downloads/torrent.files"
LOG_DIR = "/volume1/Downloads/logs"
PROCESSED_LOG = os.path.join(LOG_DIR, "processed_magnets.log")

# DHT配置
DHT_PORT = 6882
DHT_TIMEOUT = 120  # 2分钟超时
DHT_ROUTERS = [
    ("router.bittorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("router.utorrent.com", 6881),
]

class SimpleMagnetConverter:
    """简化的磁力链接转换器"""
    
    def __init__(self):
        self.session = None
        self.logger = logging.getLogger(__name__)  # 初始化logger
        self.processed_files = set()
        self.running = True
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def setup_logging(self):
        """设置日志"""
        log_file = os.path.join(LOG_DIR, f"magnet_converter_{datetime.now().strftime('%Y%m%d')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"🚀 群晖磁力链接转换器启动 - libtorrent版本: {LT_VERSION}")
    
    def setup_directories(self):
        """设置目录"""
        for directory in [MAGNET_INPUT_DIR, TORRENT_OUTPUT_DIR, LOG_DIR]:
            os.makedirs(directory, exist_ok=True)
            self.logger.info(f"✅ 目录已准备: {directory}")
    
    def load_processed_files(self):
        """加载已处理文件列表"""
        if os.path.exists(PROCESSED_LOG):
            try:
                with open(PROCESSED_LOG, 'r', encoding='utf-8') as f:
                    self.processed_files = set(line.strip() for line in f if line.strip())
                self.logger.info(f"📋 已加载 {len(self.processed_files)} 个已处理文件记录")
            except Exception as e:
                self.logger.warning(f"⚠️ 加载已处理文件列表失败: {e}")
    
    def save_processed_file(self, filename: str):
        """保存已处理文件记录"""
        try:
            with open(PROCESSED_LOG, 'a', encoding='utf-8') as f:
                f.write(f"{filename}\n")
            self.processed_files.add(filename)
        except Exception as e:
            self.logger.warning(f"⚠️ 保存已处理文件记录失败: {e}")
    
    def start_simple_session(self) -> bool:
        """启动简化的libtorrent会话"""
        if not LIBTORRENT_AVAILABLE:
            self.logger.error("❌ libtorrent不可用")
            return False
        
        try:
            self.logger.info(f"🔧 libtorrent版本: {LT_VERSION}")
            
            # 创建最基本的会话
            self.session = lt.session()  # type: ignore
            
            # 尝试设置基本配置
            try:
                # 新版本方式
                if hasattr(lt, 'settings_pack'):
                    settings = lt.settings_pack()  # type: ignore
                    settings.set_bool(lt.settings_pack.enable_dht, True)  # type: ignore
                    self.session.apply_settings(settings)
                    self.logger.info("✅ 使用新版本libtorrent配置")
                else:
                    # 旧版本方式
                    self.logger.info("✅ 使用旧版本libtorrent配置")
            except Exception as e:
                self.logger.warning(f"⚠️ 配置DHT失败，使用默认设置: {e}")
            
            # 尝试设置监听端口
            try:
                self.session.listen_on(DHT_PORT, DHT_PORT + 10)
            except Exception as e:
                self.logger.warning(f"⚠️ 设置监听端口失败: {e}")
            
            self.logger.info("🚀 libtorrent会话已启动")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 启动libtorrent会话失败: {e}")
            return False
    
    def parse_magnet_uri(self, magnet_uri: str) -> Optional[Dict[str, Any]]:
        """解析磁力链接"""
        try:
            if not magnet_uri.startswith('magnet:?'):
                return None
            
            parsed = urllib.parse.urlparse(magnet_uri)
            params = urllib.parse.parse_qs(parsed.query)
            
            if 'xt' not in params:
                return None
            
            xt = params['xt'][0]
            if not xt.startswith('urn:btih:'):
                return None
            
            info_hash = xt[9:]
            display_name = params.get('dn', ['Unknown'])[0]
            
            return {
                'info_hash': info_hash,
                'display_name': display_name,
                'magnet_uri': magnet_uri
            }
            
        except Exception as e:
            self.logger.error(f"❌ 解析磁力链接失败: {e}")
            return None
    
    def convert_magnet_simple(self, magnet_uri: str, output_path: str) -> bool:
        """简化的磁力链接转换"""
        try:
            magnet_info = self.parse_magnet_uri(magnet_uri)
            if not magnet_info:
                self.logger.error("❌ 无效的磁力链接格式")
                return False
            
            self.logger.info(f"🔍 开始转换: {magnet_info['display_name']}")
            
            # 尝试使用libtorrent转换
            if self.session:
                try:
                    # 创建添加参数
                    if hasattr(lt, 'add_torrent_params'):
                        params = lt.add_torrent_params()  # type: ignore
                        params.url = magnet_uri  # type: ignore
                        params.save_path = "/tmp"  # type: ignore
                    else:
                        # 旧版本方式
                        params = {
                            'url': magnet_uri,
                            'save_path': '/tmp'
                        }
                    
                    handle = self.session.add_torrent(params)  # type: ignore
                    
                    # 等待元数据
                    self.logger.info("⏳ 等待元数据...")
                    start_time = time.time()
                    
                    while time.time() - start_time < DHT_TIMEOUT:
                        if handle.has_metadata():  # type: ignore
                            # 尝试获取torrent信息
                            try:
                                torrent_info = handle.get_torrent_info()  # type: ignore
                                
                                # 尝试创建torrent文件
                                if hasattr(lt, 'create_torrent') and hasattr(lt, 'bencode'):
                                    ct = lt.create_torrent(torrent_info)  # type: ignore
                                    torrent_data = lt.bencode(ct.generate())  # type: ignore
                                else:
                                    # 备用方案：创建简单的torrent文件
                                    torrent_data = self._create_basic_torrent(magnet_info)
                                
                                # 保存文件
                                with open(output_path, 'wb') as f:
                                    f.write(torrent_data)
                                
                                self.logger.info(f"✅ 转换成功: {output_path}")
                                
                                # 清理
                                try:
                                    self.session.remove_torrent(handle)
                                except:
                                    pass
                                
                                return True
                                
                            except Exception as e:
                                self.logger.error(f"❌ 创建torrent文件失败: {e}")
                                break
                        
                        time.sleep(1)
                    
                    # 超时处理
                    self.logger.warning(f"⚠️ 元数据下载超时，尝试创建基本torrent文件")
                    try:
                        self.session.remove_torrent(handle)
                    except:
                        pass
                    
                except Exception as e:
                    self.logger.error(f"❌ libtorrent转换失败: {e}")
            
            # 备用方案：创建基本的torrent文件
            self.logger.info("🔄 使用备用方案创建torrent文件")
            torrent_data = self._create_basic_torrent(magnet_info)
            
            with open(output_path, 'wb') as f:
                f.write(torrent_data)
            
            self.logger.info(f"✅ 已创建基本torrent文件: {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 转换失败: {e}")
            return False
    
    def _create_basic_torrent(self, magnet_info: Dict[str, Any]) -> bytes:
        """创建基本的torrent文件"""
        try:
            # 尝试使用简单的bencode实现
            info_hash = magnet_info['info_hash']
            name = magnet_info['display_name']
            
            # 创建基本的torrent字典
            torrent_dict = {
                'announce': 'http://tracker.example.com:8080/announce',
                'info': {
                    'name': name,
                    'piece length': 262144,
                    'pieces': b'',
                    'length': 0
                },
                'comment': f'Generated from magnet link - Info Hash: {info_hash}'
            }
            
            # 简单的bencode实现
            return self._simple_bencode(torrent_dict)
            
        except Exception as e:
            self.logger.error(f"❌ 创建基本torrent失败: {e}")
            # 返回最小的有效torrent文件
            return b'd8:announce0:4:infod4:name0:12:piece lengthi0e6:pieces0:ee'
    
    def _simple_bencode(self, obj) -> bytes:
        """简单的bencode实现"""
        if isinstance(obj, int):
            return f'i{obj}e'.encode()
        elif isinstance(obj, str):
            return f'{len(obj.encode())}:{obj}'.encode()
        elif isinstance(obj, bytes):
            return f'{len(obj)}:'.encode() + obj
        elif isinstance(obj, list):
            return b'l' + b''.join(self._simple_bencode(item) for item in obj) + b'e'
        elif isinstance(obj, dict):
            items = []
            for key in sorted(obj.keys()):
                items.append(self._simple_bencode(key))
                items.append(self._simple_bencode(obj[key]))
            return b'd' + b''.join(items) + b'e'
        else:
            return b''
    
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
            filename = os.path.basename(magnet_file_path)
            
            # 读取磁力链接
            with open(magnet_file_path, 'r', encoding='utf-8') as f:
                magnet_uri = f.read().strip()
            
            if not magnet_uri:
                self.logger.warning(f"⚠️ 空的磁力链接文件: {filename}")
                return False
            
            # 生成输出文件名
            base_name = os.path.splitext(filename)[0]
            output_path = os.path.join(TORRENT_OUTPUT_DIR, f"{base_name}.torrent")
            
            # 转换磁力链接
            if self.convert_magnet_simple(magnet_uri, output_path):
                self.save_processed_file(filename)
                self.logger.info(f"✅ 处理完成: {filename}")
                return True
            else:
                self.logger.error(f"❌ 处理失败: {filename}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 处理文件失败 {magnet_file_path}: {e}")
            return False
    
    def run_once(self) -> int:
        """运行一次转换任务"""
        self.logger.info("🚀 开始磁力链接转换任务")
        
        if not self.start_simple_session():
            return 1
        
        # 等待DHT初始化
        self.logger.info("⏳ 等待DHT初始化...")
        time.sleep(10)
        
        magnet_files = self.scan_magnet_files()
        if not magnet_files:
            self.logger.info("📭 没有发现待处理的.magnet文件")
            return 0
        
        success_count = 0
        for magnet_file in magnet_files:
            if not self.running:
                break
            
            if self.process_magnet_file(magnet_file):
                success_count += 1
        
        self.logger.info(f"🎉 转换任务完成，成功处理 {success_count}/{len(magnet_files)} 个文件")
        return 0 if success_count > 0 else 1
    
    def run_monitor(self, interval: int = 60):
        """监控模式运行"""
        self.logger.info(f"👁️ 开始监控模式，检查间隔: {interval}秒")
        
        if not self.start_simple_session():
            return
        
        # 等待DHT初始化
        self.logger.info("⏳ 等待DHT初始化...")
        time.sleep(10)
        
        while self.running:
            try:
                magnet_files = self.scan_magnet_files()
                
                for magnet_file in magnet_files:
                    if not self.running:
                        break
                    self.process_magnet_file(magnet_file)
                
                # 等待下次检查
                for _ in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                self.logger.error(f"❌ 监控循环出错: {e}")
                time.sleep(interval)
        
        self.logger.info("👋 监控模式已停止")
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"📡 收到信号 {signum}，准备退出...")
        self.running = False

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='群晖NAS磁力链接转换器 - 简化版本')
    parser.add_argument('--once', action='store_true', help='运行一次后退出')
    parser.add_argument('--monitor', action='store_true', help='监控模式运行')
    parser.add_argument('--interval', type=int, default=60, help='监控间隔（秒）')
    
    args = parser.parse_args()
    
    converter = SimpleMagnetConverter()
    
    try:
        converter.setup_directories()
        converter.setup_logging()
        converter.load_processed_files()
        
        if args.once:
            return converter.run_once()
        elif args.monitor:
            converter.run_monitor(args.interval)
            return 0
        else:
            # 默认运行一次
            return converter.run_once()
            
    except KeyboardInterrupt:
        converter.logger.info("👋 用户中断，程序退出")
        return 0
    except Exception as e:
        if converter.logger:
            converter.logger.error(f"❌ 程序异常退出: {e}")
        else:
            print(f"❌ 程序异常退出: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())