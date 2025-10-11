#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
群晖NAS磁力链接转种子文件工具 - libtorrent 2.x版本
专门适配libtorrent 2.x版本的API

作者: Assistant
版本: 2.0.0 (libtorrent 2.x)
日期: 2024-01-01

功能:
- 磁力链接转换为种子文件
- 适配libtorrent 2.x版本的新API
- 使用session_params进行会话配置
- 支持现代DHT和会话管理

使用方法:
    python synology_magnet_converter_v2.py --once
    python synology_magnet_converter_v2.py --monitor
"""

import os
import sys
import time
import logging
import argparse
import hashlib
import re
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import libtorrent as lt  # type: ignore
    LIBTORRENT_AVAILABLE = True
    LT_VERSION = getattr(lt, 'version', 'unknown')
    print(f"✅ libtorrent版本: {LT_VERSION}")
except ImportError:
    print("❌ 错误: 无法导入libtorrent库")
    print("请确保已安装libtorrent-python包")
    sys.exit(1)

class SynologyMagnetConverterV2:
    """群晖NAS磁力链接转换器 - libtorrent 2.x版本"""
    
    def __init__(self, download_dir: str = "/tmp", output_dir: str = "/tmp"):
        self.download_dir = Path(download_dir)
        self.output_dir = Path(output_dir)
        self.session = None
        self.logger = self._setup_logging()
        
        # 确保目录存在
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"初始化转换器 - libtorrent {LT_VERSION}")
        self.logger.info(f"下载目录: {self.download_dir}")
        self.logger.info(f"输出目录: {self.output_dir}")
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志记录"""
        logger = logging.getLogger('SynologyMagnetConverterV2')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def start_session(self) -> bool:
        """启动libtorrent会话 - 使用2.x API"""
        try:
            self.logger.info("启动libtorrent会话...")
            
            # 创建会话
            self.session = lt.session()
            
            # 获取当前设置
            settings = self.session.get_settings()
            
            # 修改设置 - 针对VPN环境优化
            settings['enable_dht'] = True
            settings['enable_lsd'] = True
            settings['enable_upnp'] = True
            settings['enable_natpmp'] = True
            
            # VPN环境下的监听接口优化
            # 使用多个端口范围，提高连接成功率
            listen_ports = [
                '0.0.0.0:6881',
                '0.0.0.0:6882', 
                '0.0.0.0:6883',
                '0.0.0.0:51413',  # 常用的BitTorrent端口
                '0.0.0.0:0'       # 让系统自动分配端口
            ]
            settings['listen_interfaces'] = ','.join(listen_ports)
            
            # 优化DHT和连接设置 (兼容libtorrent 2.0.9.0+)
            # 只使用确认支持的设置参数
            safe_settings = {
                'dht_bootstrap_nodes': 'router.bittorrent.com:6881,dht.transmissionbt.com:6881,router.utorrent.com:6881',
                'connections_limit': 200,
                'max_peerlist_size': 3000,
                'max_paused_peerlist_size': 1000,
                'request_timeout': 60,
                'peer_timeout': 120,
                'inactivity_timeout': 600,
                'connection_speed': 30,  # 连接速度
                'announce_to_all_trackers': True,  # 向所有tracker宣告
                'announce_to_all_tiers': True,     # 向所有层级宣告
                'enable_outgoing_utp': True,       # 启用出站uTP
                'enable_incoming_utp': True,       # 启用入站uTP
                'enable_outgoing_tcp': True,       # 启用出站TCP
                'enable_incoming_tcp': True,       # 启用入站TCP
            }
            
            # 尝试设置每个参数，忽略不支持的设置
            for key, value in safe_settings.items():
                try:
                    settings[key] = value
                except Exception as e:
                    self.logger.debug(f"跳过不支持的设置 {key}: {e}")
            
            # 注意：每个torrent的连接限制在当前版本中通过其他方式设置
            # 这些设置名称在libtorrent 2.0.9+中已不再支持
            
            # 应用设置 (包装在异常处理中)
            try:
                self.session.apply_settings(settings)
                self.logger.info("会话设置应用成功")
            except Exception as e:
                self.logger.warning(f"应用部分设置时出错: {e}")
                # 尝试只应用基本设置
                basic_settings = self.session.get_settings()
                basic_settings['enable_dht'] = True
                basic_settings['enable_lsd'] = True
                basic_settings['enable_upnp'] = True
                basic_settings['enable_natpmp'] = True
                basic_settings['listen_interfaces'] = '0.0.0.0:6881'
                
                try:
                    self.session.apply_settings(basic_settings)
                    self.logger.info("基本设置应用成功")
                except Exception as e2:
                    self.logger.error(f"应用基本设置也失败: {e2}")
                    return False
            
            # 启动DHT
            try:
                self.session.start_dht()
                self.logger.info("✅ DHT已启动")
            except Exception as e:
                self.logger.error(f"启动DHT失败: {e}")
                return False
            
            # 添加多个DHT bootstrap节点
            try:
                bootstrap_nodes = [
                    ("router.bittorrent.com", 6881),
                    ("dht.transmissionbt.com", 6881),
                    ("router.utorrent.com", 6881),
                    ("dht.aelitis.com", 6881),
                    ("dht.libtorrent.org", 25401),
                    ("bootstrap.ring.cx", 4222),
                    ("87.98.162.88", 6881),
                    ("67.215.246.10", 6881),
                    ("82.221.103.244", 6881),
                    ("91.121.59.153", 6881)
                ]
                
                # 在libtorrent 2.x中，DHT节点通过设置自动连接
                # 或者使用session.dht_bootstrap()方法
                if hasattr(self.session, 'dht_bootstrap'):
                    for host, port in bootstrap_nodes:
                        self.session.dht_bootstrap(host, port)  # type: ignore
                elif hasattr(self.session, 'add_dht_node'):
                    for host, port in bootstrap_nodes:
                        try:
                            self.session.add_dht_node((host, port))
                        except Exception as e:
                            self.logger.debug(f"添加DHT节点 {host}:{port} 失败: {e}")
                else:
                    # 备用方案：通过设置配置DHT
                    self.logger.info("使用默认DHT bootstrap节点")
                
                self.logger.info(f"✅ 已添加 {len(bootstrap_nodes)} 个DHT bootstrap节点")
                    
            except Exception as e:
                self.logger.warning(f"配置DHT bootstrap节点时出错: {e}")
                self.logger.info("将使用默认DHT配置")
            
            # 启动UPnP和NAT-PMP
            try:
                self.session.start_upnp()
                self.session.start_natpmp()
                self.logger.info("✅ UPnP和NAT-PMP已启动")
            except Exception as e:
                self.logger.warning(f"启动UPnP/NAT-PMP失败: {e}")
            
            # 显示网络诊断信息
            self._log_network_diagnostics()
            
            self.logger.info("✅ libtorrent会话启动成功")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 启动会话失败: {e}")
            return False
    
    def _log_network_diagnostics(self):
        """记录网络诊断信息"""
        try:
            import socket
            import subprocess
            
            self.logger.info("=== 网络诊断信息 ===")
            
            # 获取本地IP地址
            try:
                # 连接到外部地址来获取本地IP
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
                self.logger.info(f"本地IP地址: {local_ip}")
            except Exception as e:
                self.logger.debug(f"获取本地IP失败: {e}")
            
            # 检查网络连接
            try:
                result = subprocess.run(['ping', '-c', '1', '8.8.8.8'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    self.logger.info("✅ 外网连接正常")
                else:
                    self.logger.warning("⚠️ 外网连接可能有问题")
            except Exception as e:
                self.logger.debug(f"网络连接测试失败: {e}")
            
            # 显示监听端口信息
            try:
                if self.session:
                    settings = self.session.get_settings()
                    if hasattr(settings, 'get'):
                        listen_interfaces = settings.get('listen_interfaces', 'unknown')
                    else:
                        listen_interfaces = getattr(settings, 'listen_interfaces', 'unknown')
                    self.logger.info(f"监听接口: {listen_interfaces}")
            except Exception as e:
                self.logger.debug(f"获取监听接口信息失败: {e}")
                
            self.logger.info("=== 诊断信息结束 ===")
            
        except Exception as e:
            self.logger.debug(f"网络诊断失败: {e}")
    
    def _log_tracker_status(self, handle):
        """记录tracker连接状态"""
        try:
            trackers = handle.trackers()
            if trackers:
                self.logger.info(f"Tracker状态 (共{len(trackers)}个):")
                for i, tracker in enumerate(trackers[:5]):  # 只显示前5个
                    status_msg = "未知"
                    if hasattr(tracker, 'last_error') and tracker.last_error:
                        status_msg = f"错误: {tracker.last_error.message()}"
                    elif hasattr(tracker, 'verified') and tracker.verified:
                        status_msg = "已验证"
                    elif hasattr(tracker, 'updating') and tracker.updating:
                        status_msg = "更新中"
                    
                    self.logger.info(f"  [{i+1}] {tracker.url} - {status_msg}")
                    
                if len(trackers) > 5:
                    self.logger.info(f"  ... 还有 {len(trackers) - 5} 个tracker")
        except Exception as e:
            self.logger.debug(f"获取tracker状态失败: {e}")
    
    def wait_for_dht_ready(self, timeout: int = 30) -> bool:
        """等待DHT网络就绪 - 缩短等待时间，不强制要求DHT连接"""
        self.logger.info("等待DHT网络连接...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 获取会话状态 (使用新的API)
                try:
                    # 尝试使用新的session_stats方法
                    stats = self.session.session_stats()  # type: ignore
                    dht_nodes = 0
                    
                    # 在stats中查找DHT节点数
                    for stat in stats:
                        if hasattr(stat, 'name') and 'dht.nodes' in stat.name:
                            dht_nodes = stat.value
                            break
                    
                    if dht_nodes > 0:
                        self.logger.info(f"✅ DHT网络已连接，节点数: {dht_nodes}")
                        return True
                    
                    # 每5秒输出一次状态，减少日志噪音
                    if int(time.time() - start_time) % 5 == 0:
                        self.logger.info(f"DHT连接中... 节点数: {dht_nodes}")
                    
                except AttributeError:
                    # 备用方案：使用旧的status方法但忽略警告
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        status = self.session.status()  # type: ignore
                        
                        dht_nodes = getattr(status, 'dht_nodes', 0)
                        if dht_nodes > 0:
                            self.logger.info(f"✅ DHT网络已连接，节点数: {dht_nodes}")
                            return True
                        
                        if int(time.time() - start_time) % 5 == 0:
                            self.logger.info(f"DHT连接中... 节点数: {dht_nodes}")
                
                time.sleep(1)
                
            except Exception as e:
                self.logger.warning(f"检查DHT状态时出错: {e}")
                time.sleep(1)
        
        self.logger.warning(f"⚠️ DHT连接超时({timeout}秒)，但继续尝试转换（tracker可能仍然有效）...")
        return False
    
    def parse_magnet_link(self, magnet_link: str) -> Optional[Dict[str, Any]]:
        """解析磁力链接"""
        try:
            # 提取info_hash
            hash_match = re.search(r'urn:btih:([a-fA-F0-9]{40})', magnet_link)
            if not hash_match:
                hash_match = re.search(r'urn:btih:([a-fA-F0-9]{32})', magnet_link)
            
            if not hash_match:
                self.logger.error("无法从磁力链接中提取info_hash")
                return None
            
            info_hash = hash_match.group(1).upper()
            
            # 提取显示名称
            name_match = re.search(r'dn=([^&]+)', magnet_link)
            display_name = name_match.group(1) if name_match else f"torrent_{info_hash[:8]}"
            
            # URL解码
            import urllib.parse
            display_name = urllib.parse.unquote(display_name)
            
            return {
                'info_hash': info_hash,
                'display_name': display_name,
                'magnet_link': magnet_link
            }
            
        except Exception as e:
            self.logger.error(f"解析磁力链接失败: {e}")
            return None
    
    def convert_magnet_to_torrent(self, magnet_link: str, timeout: int = 300) -> Optional[str]:
        """转换磁力链接为种子文件"""
        try:
            # 解析磁力链接
            magnet_info = self.parse_magnet_link(magnet_link)
            if not magnet_info:
                return None
            
            info_hash = magnet_info['info_hash']
            display_name = magnet_info['display_name']
            
            self.logger.info(f"开始转换: {display_name}")
            self.logger.info(f"Info Hash: {info_hash}")
            
            # 快速检查DHT状态，但不强制等待
            self.logger.info("检查DHT状态...")
            dht_ready = self.wait_for_dht_ready(10)  # 只等待10秒
            if dht_ready:
                self.logger.info("DHT网络已连接，将使用DHT+Tracker进行转换")
            else:
                self.logger.info("DHT网络未连接，将主要依赖Tracker进行转换")
            
            # 创建add_torrent_params
            params = lt.add_torrent_params()  # type: ignore
            params.url = magnet_link  # type: ignore
            params.save_path = str(self.download_dir)  # type: ignore
            params.flags = lt.torrent_flags.upload_mode | lt.torrent_flags.stop_when_ready  # type: ignore
            
            # 添加更多tracker来提高连接成功率
            try:
                common_trackers = [
                    # 公共tracker
                    'udp://tracker.opentrackr.org:1337/announce',
                    'udp://open.stealth.si:80/announce',
                    'udp://tracker.torrent.eu.org:451/announce',
                    'udp://exodus.desync.com:6969/announce',
                    'udp://tracker.moeking.me:6969/announce',
                    'udp://tracker.openbittorrent.com:6969/announce',
                    'udp://tracker.publicbt.com:80/announce',
                    'udp://tracker.istole.it:6969/announce',
                    'udp://open.demonii.com:1337/announce',
                    'udp://denis.stalker.upeer.me:6969/announce',
                    # 更多备用tracker
                    'http://tracker.opentrackr.org:1337/announce',
                    'http://open.acgtracker.com:1096/announce',
                    'udp://tracker.tiny-vps.com:6969/announce',
                    'udp://tracker.port443.xyz:6969/announce',
                    'udp://thetracker.org:80/announce',
                    'udp://bt.xxx-tracker.com:2710/announce',
                    'udp://retracker.lanta-net.ru:2710/announce',
                    'udp://tracker.cyberia.is:6969/announce',
                    'udp://tracker.ds.is:6969/announce'
                ]
                
                # 从磁力链接中提取现有的tracker
                existing_trackers = []
                import urllib.parse
                parsed_magnet = urllib.parse.urlparse(magnet_link)
                query_params = urllib.parse.parse_qs(parsed_magnet.query)
                if 'tr' in query_params:
                    existing_trackers = query_params['tr']
                
                # 合并tracker列表
                all_trackers = existing_trackers + common_trackers
                # 去重
                all_trackers = list(dict.fromkeys(all_trackers))
                
                if hasattr(params, 'trackers'):
                    params.trackers = all_trackers  # type: ignore
                elif hasattr(params, 'tracker_urls'):
                    params.tracker_urls = all_trackers  # type: ignore
                    
                self.logger.info(f"添加了 {len(all_trackers)} 个tracker")
                
            except Exception as e:
                self.logger.debug(f"添加tracker时出错: {e}")
                
            # 设置更积极的连接参数
            try:
                if hasattr(params, 'max_connections'):
                    params.max_connections = 200  # type: ignore
                if hasattr(params, 'max_uploads'):
                    params.max_uploads = 50  # type: ignore
                    
                # 移除upload_mode标志，允许下载
                params.flags = lt.torrent_flags.stop_when_ready  # type: ignore
                
            except Exception as e:
                self.logger.debug(f"设置连接参数时出错: {e}")
            
            # 添加到会话
            handle = self.session.add_torrent(params)  # type: ignore
            
            self.logger.info(f"等待元数据下载... (超时时间: {timeout}秒)")
            start_time = time.time()
            last_log_time = start_time
            
            while time.time() - start_time < timeout:
                # 检查状态
                status = handle.status()  # type: ignore
                current_time = time.time()
                elapsed_time = current_time - start_time
                
                # 使用新的方法检查是否有元数据 (避免弃用警告)
                has_metadata = False
                try:
                    # 在libtorrent 2.x中，可以通过status检查元数据状态
                    if hasattr(status, 'has_metadata'):
                        has_metadata = status.has_metadata
                    else:
                        # 备用方案：检查torrent_file是否可用
                        torrent_info = handle.torrent_file()  # type: ignore
                        has_metadata = torrent_info is not None
                except:
                    # 最后备用方案：使用旧方法但忽略警告
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", DeprecationWarning)
                        try:
                            has_metadata = handle.has_metadata()  # type: ignore
                        except:
                            has_metadata = False
                
                if has_metadata:
                    self.logger.info("✅ 元数据下载完成")
                    
                    # 获取torrent信息
                    torrent_info = handle.torrent_file()  # type: ignore
                    if torrent_info:
                        # 创建torrent文件
                        torrent_data = lt.bencode(lt.create_torrent(torrent_info).generate())  # type: ignore
                        
                        # 保存文件
                        safe_name = re.sub(r'[^\w\-_\.]', '_', display_name)
                        torrent_filename = f"{safe_name}.torrent"
                        torrent_path = self.output_dir / torrent_filename
                        
                        with open(torrent_path, 'wb') as f:
                            f.write(torrent_data)
                        
                        self.logger.info(f"✅ 种子文件已保存: {torrent_path}")
                        
                        # 移除torrent
                        self.session.remove_torrent(handle)  # type: ignore
                        
                        return str(torrent_path)
                    else:
                        self.logger.error("无法获取torrent信息")
                        break
                
                # 每10秒输出一次详细状态信息
                if current_time - last_log_time >= 10:
                    num_peers = getattr(status, 'num_peers', 0)
                    num_seeds = getattr(status, 'num_seeds', 0)
                    state = getattr(status, 'state', 'unknown')
                    
                    # 获取状态名称
                    state_name = 'unknown'
                    try:
                        state_names = {
                            0: 'queued_for_checking',
                            1: 'checking_files', 
                            2: 'downloading_metadata',
                            3: 'downloading',
                            4: 'finished',
                            5: 'seeding',
                            6: 'allocating',
                            7: 'checking_resume_data'
                        }
                        if isinstance(state, int):
                            state_name = state_names.get(state, f'state_{state}')
                        else:
                            state_name = str(state)
                    except Exception:
                        state_name = f'state_{state}'
                    
                    self.logger.info(f"[{elapsed_time:.0f}s] 状态: {state_name}, 连接: {num_peers} peers, {num_seeds} seeds, 进度: {status.progress * 100:.1f}%")
                    
                    # 显示详细的tracker状态
                    self._log_tracker_status(handle)
                    
                    last_log_time = current_time
                
                time.sleep(2)
            
            self.logger.error(f"❌ 转换超时({timeout}秒)")
            self.session.remove_torrent(handle)  # type: ignore
            return None
            
        except Exception as e:
            self.logger.error(f"❌ 转换失败: {e}")
            return None
    
    def process_magnet_file(self, file_path: str) -> int:
        """处理磁力链接文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            
            if not content.startswith('magnet:'):
                self.logger.error(f"文件不包含有效的磁力链接: {file_path}")
                return 0
            
            self.logger.info(f"处理磁力链接文件: {file_path}")
            
            result = self.convert_magnet_to_torrent(content)
            if result:
                # 删除原文件
                os.remove(file_path)
                self.logger.info(f"✅ 已删除原文件: {file_path}")
                return 1
            else:
                self.logger.error(f"❌ 转换失败: {file_path}")
                return 0
                
        except Exception as e:
            self.logger.error(f"❌ 处理文件失败 {file_path}: {e}")
            return 0
    
    def scan_and_convert(self, scan_dir: str) -> int:
        """扫描目录并转换磁力链接文件"""
        scan_path = Path(scan_dir)
        if not scan_path.exists():
            self.logger.error(f"扫描目录不存在: {scan_dir}")
            return 0
        
        magnet_files = list(scan_path.glob("*.magnet"))
        if not magnet_files:
            self.logger.info("未找到磁力链接文件")
            return 0
        
        self.logger.info(f"找到 {len(magnet_files)} 个磁力链接文件")
        
        success_count = 0
        for magnet_file in magnet_files:
            success_count += self.process_magnet_file(str(magnet_file))
        
        self.logger.info(f"转换完成: {success_count}/{len(magnet_files)} 成功")
        return success_count
    
    def monitor_mode(self, scan_dir: str, interval: int = 10):
        """监控模式"""
        self.logger.info(f"启动监控模式，扫描目录: {scan_dir}")
        self.logger.info(f"扫描间隔: {interval} 秒")
        
        try:
            while True:
                self.scan_and_convert(scan_dir)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.logger.info("监控模式已停止")
    
    def cleanup(self):
        """清理资源"""
        if self.session:
            self.logger.info("清理会话资源...")
            self.session = None

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='群晖NAS磁力链接转种子工具 - libtorrent 2.x版本')
    parser.add_argument('--once', action='store_true', help='单次扫描模式')
    parser.add_argument('--monitor', action='store_true', help='监控模式')
    parser.add_argument('--scan-dir', default='/volume1/downloads', help='扫描目录')
    parser.add_argument('--output-dir', default='/volume1/downloads', help='输出目录')
    parser.add_argument('--download-dir', default='/tmp/magnet2torrent', help='临时下载目录')
    parser.add_argument('--interval', type=int, default=10, help='监控间隔(秒)')
    
    args = parser.parse_args()
    
    if not args.once and not args.monitor:
        print("请指定运行模式: --once 或 --monitor")
        parser.print_help()
        return 1
    
    # 创建转换器
    converter = SynologyMagnetConverterV2(
        download_dir=args.download_dir,
        output_dir=args.output_dir
    )
    
    try:
        # 启动会话
        if not converter.start_session():
            print("❌ 启动会话失败")
            return 1
        
        # 等待DHT就绪
        converter.wait_for_dht_ready()
        
        if args.once:
            # 单次模式
            result = converter.scan_and_convert(args.scan_dir)
            print(f"转换完成: {result} 个文件")
        else:
            # 监控模式
            converter.monitor_mode(args.scan_dir, args.interval)
    
    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"❌ 程序错误: {e}")
        return 1
    finally:
        converter.cleanup()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())