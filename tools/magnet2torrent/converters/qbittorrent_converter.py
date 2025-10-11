#!/usr/bin/env python3
"""
基于 qBittorrent Web API 的磁力链接转换器
qBittorrent 是一个功能强大且稳定的 BitTorrent 客户端
"""

import json
import time
import requests
import subprocess
import os
import argparse
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from urllib.parse import quote, unquote
import hashlib

class QBittorrentMagnetConverter:
    """基于 qBittorrent Web API 的磁力链接转换器"""
    
    def __init__(self, host: str = "localhost", port: int = 8080, 
                 username: str = "admin", password: str = "adminadmin",
                 download_dir: str = "./qbt_downloads"):
        """
        初始化 qBittorrent 转换器
        
        Args:
            host: qBittorrent Web UI 地址
            port: qBittorrent Web UI 端口
            username: 用户名
            password: 密码
            download_dir: 下载目录
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.download_dir = Path(download_dir)
        self.base_url = f"http://{host}:{port}"
        self.session = requests.Session()
        self.qbt_process = None
        
        # 创建下载目录
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # 设置日志
        self.logger = self._setup_logging()
        
        # 登录状态
        self.logged_in = False
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger("QBittorrentMagnetConverter")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def start_qbittorrent(self, config_dir: Optional[str] = None) -> bool:
        """
        启动 qBittorrent 守护进程
        
        Args:
            config_dir: 配置目录
            
        Returns:
            是否启动成功
        """
        try:
            # 检查 qbittorrent-nox 是否可用
            result = subprocess.run(['qbittorrent-nox', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                self.logger.error("❌ qbittorrent-nox 未安装或不可用")
                self.logger.info("💡 请安装 qBittorrent: brew install qbittorrent (macOS)")
                return False
            
            # 构建启动命令
            cmd = [
                'qbittorrent-nox',
                '--daemon',
                f'--webui-port={self.port}',
                '--confirm-legal-notice'
            ]
            
            # 添加配置目录
            if config_dir:
                cmd.extend(['--configuration', config_dir])
            
            self.logger.info("🚀 启动 qBittorrent 守护进程...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.logger.info("✅ qBittorrent 守护进程启动成功")
                # 等待服务启动
                time.sleep(3)
                return self.test_connection()
            else:
                self.logger.error(f"❌ qBittorrent 启动失败: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("❌ qBittorrent 启动超时")
            return False
        except FileNotFoundError:
            self.logger.error("❌ 未找到 qbittorrent-nox 命令")
            return False
        except Exception as e:
            self.logger.error(f"❌ 启动 qBittorrent 异常: {e}")
            return False
    
    def stop_qbittorrent(self) -> bool:
        """停止 qBittorrent 守护进程"""
        try:
            if self.logged_in:
                response = self.session.post(f"{self.base_url}/api/v2/app/shutdown")
                if response.status_code == 200:
                    self.logger.info("✅ qBittorrent 守护进程已停止")
                    return True
            
            # 尝试强制停止
            subprocess.run(['pkill', '-f', 'qbittorrent-nox'], capture_output=True)
            self.logger.info("🔄 强制停止 qBittorrent 进程")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 停止 qBittorrent 失败: {e}")
            return False
    
    def login(self) -> bool:
        """登录到 qBittorrent Web UI"""
        try:
            login_data = {
                'username': self.username,
                'password': self.password
            }
            
            response = self.session.post(
                f"{self.base_url}/api/v2/auth/login",
                data=login_data,
                timeout=10
            )
            
            if response.status_code == 200 and response.text == "Ok.":
                self.logged_in = True
                self.logger.info("✅ 登录成功")
                return True
            else:
                self.logger.error(f"❌ 登录失败: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 登录异常: {e}")
            return False
    
    def logout(self) -> bool:
        """登出"""
        try:
            if self.logged_in:
                response = self.session.post(f"{self.base_url}/api/v2/auth/logout")
                self.logged_in = False
                self.logger.info("✅ 登出成功")
            return True
        except Exception as e:
            self.logger.error(f"❌ 登出异常: {e}")
            return False
    
    def test_connection(self) -> bool:
        """测试与 qBittorrent 的连接"""
        try:
            response = self.session.get(f"{self.base_url}/api/v2/app/version", timeout=10)
            if response.status_code == 200:
                version = response.text.strip('"')
                self.logger.info(f"✅ 连接成功，qBittorrent 版本: {version}")
                return self.login()
            else:
                self.logger.error("❌ 连接失败")
                return False
        except Exception as e:
            self.logger.error(f"❌ 连接测试异常: {e}")
            return False
    
    def add_magnet(self, magnet_uri: str, save_path: Optional[str] = None) -> Optional[str]:
        """
        添加磁力链接下载任务
        
        Args:
            magnet_uri: 磁力链接
            save_path: 保存路径
            
        Returns:
            任务哈希，失败返回 None
        """
        if not self.logged_in:
            if not self.login():
                return None
        
        try:
            # 准备数据
            data = {
                'urls': magnet_uri,
                'paused': 'true',  # 暂停状态添加
                'skip_checking': 'false',
                'root_folder': 'true'
            }
            
            if save_path:
                data['savepath'] = save_path
            else:
                data['savepath'] = str(self.download_dir)
            
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/add",
                data=data,
                timeout=30
            )
            
            if response.status_code == 200 and response.text == "Ok.":
                # 从磁力链接提取哈希
                hash_value = self._extract_hash_from_magnet(magnet_uri)
                if hash_value:
                    self.logger.info(f"✅ 磁力链接添加成功，哈希: {hash_value}")
                    return hash_value
                else:
                    self.logger.error("❌ 无法从磁力链接提取哈希")
                    return None
            else:
                self.logger.error(f"❌ 添加磁力链接失败: {response.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 添加磁力链接异常: {e}")
            return None
    
    def _extract_hash_from_magnet(self, magnet_uri: str) -> Optional[str]:
        """从磁力链接提取哈希值"""
        try:
            if 'xt=urn:btih:' in magnet_uri:
                start = magnet_uri.find('xt=urn:btih:') + 12
                end = magnet_uri.find('&', start)
                if end == -1:
                    hash_value = magnet_uri[start:]
                else:
                    hash_value = magnet_uri[start:end]
                return hash_value.lower()
            return None
        except Exception:
            return None
    
    def get_torrent_info(self, hash_value: str) -> Optional[Dict[str, Any]]:
        """获取种子信息"""
        if not self.logged_in:
            if not self.login():
                return None
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/torrents/info",
                params={'hashes': hash_value},
                timeout=10
            )
            
            if response.status_code == 200:
                torrents = response.json()
                if torrents:
                    return torrents[0]
            return None
            
        except Exception as e:
            self.logger.error(f"❌ 获取种子信息失败: {e}")
            return None
    
    def wait_for_metadata(self, hash_value: str, timeout: int = 300) -> bool:
        """
        等待元数据下载完成
        
        Args:
            hash_value: 种子哈希
            timeout: 超时时间（秒）
            
        Returns:
            是否成功获取元数据
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            info = self.get_torrent_info(hash_value)
            if not info:
                self.logger.error(f"❌ 无法获取种子信息: {hash_value}")
                return False
            
            state = info.get('state', '')
            
            if state in ['pausedDL', 'queuedDL', 'stalledDL']:
                # 检查是否有元数据
                if info.get('size', 0) > 0:
                    self.logger.info(f"✅ 元数据获取完成: {hash_value}")
                    return True
            elif state == 'error':
                self.logger.error(f"❌ 种子错误状态: {hash_value}")
                return False
            
            # 显示进度
            progress = info.get('progress', 0)
            self.logger.info(f"📥 获取元数据中... 进度: {progress:.1f}% 状态: {state}")
            
            time.sleep(5)
        
        self.logger.error(f"⏰ 等待元数据超时: {hash_value}")
        return False
    
    def export_torrent(self, hash_value: str, output_path: Optional[str] = None) -> Optional[Path]:
        """
        导出种子文件
        
        Args:
            hash_value: 种子哈希
            output_path: 输出文件路径
            
        Returns:
            种子文件路径，失败返回 None
        """
        if not self.logged_in:
            if not self.login():
                return None
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/v2/torrents/export",
                params={'hash': hash_value},
                timeout=30
            )
            
            if response.status_code == 200:
                # 确定输出文件路径
                if output_path:
                    torrent_file = Path(output_path)
                else:
                    torrent_file = self.download_dir / f"{hash_value}.torrent"
                
                # 创建目录
                torrent_file.parent.mkdir(parents=True, exist_ok=True)
                
                # 保存文件
                with open(torrent_file, 'wb') as f:
                    f.write(response.content)
                
                self.logger.info(f"✅ 种子文件导出成功: {torrent_file}")
                return torrent_file
            else:
                self.logger.error(f"❌ 导出种子文件失败: {response.status_code}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 导出种子文件异常: {e}")
            return None
    
    def remove_torrent(self, hash_value: str, delete_files: bool = False) -> bool:
        """删除种子任务"""
        if not self.logged_in:
            if not self.login():
                return False
        
        try:
            data = {
                'hashes': hash_value,
                'deleteFiles': 'true' if delete_files else 'false'
            }
            
            response = self.session.post(
                f"{self.base_url}/api/v2/torrents/delete",
                data=data,
                timeout=10
            )
            
            if response.status_code == 200:
                self.logger.info(f"✅ 种子任务删除成功: {hash_value}")
                return True
            else:
                self.logger.error(f"❌ 删除种子任务失败: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 删除种子任务异常: {e}")
            return False
    
    def convert_magnet_to_torrent(self, magnet_uri: str, output_path: Optional[str] = None, 
                                timeout: int = 300) -> Optional[Path]:
        """
        将磁力链接转换为种子文件
        
        Args:
            magnet_uri: 磁力链接
            output_path: 输出文件路径
            timeout: 超时时间
            
        Returns:
            种子文件路径，失败返回 None
        """
        self.logger.info(f"🧲 开始转换磁力链接...")
        
        # 添加下载任务
        hash_value = self.add_magnet(magnet_uri)
        if not hash_value:
            return None
        
        try:
            # 等待元数据下载
            if not self.wait_for_metadata(hash_value, timeout):
                return None
            
            # 导出种子文件
            torrent_file = self.export_torrent(hash_value, output_path)
            if not torrent_file:
                return None
            
            self.logger.info(f"✅ 转换成功: {torrent_file}")
            return torrent_file
            
        finally:
            # 清理任务
            try:
                self.remove_torrent(hash_value, delete_files=True)
            except:
                pass
    
    def process_magnet_file(self, file_path: str, output_dir: str = "./torrent_output") -> bool:
        """处理磁力链接文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                magnet_uri = f.read().strip()
            
            if not magnet_uri.startswith('magnet:'):
                self.logger.error(f"❌ 无效的磁力链接文件: {file_path}")
                return False
            
            # 生成输出文件名
            file_name = Path(file_path).stem
            output_file = Path(output_dir) / f"{file_name}.torrent"
            
            # 转换
            result = self.convert_magnet_to_torrent(magnet_uri, str(output_file))
            return result is not None
            
        except Exception as e:
            self.logger.error(f"❌ 处理文件失败 {file_path}: {e}")
            return False
    
    def scan_and_convert(self, scan_dir: str, output_dir: str = "./torrent_output") -> int:
        """扫描目录并转换所有磁力链接"""
        scan_path = Path(scan_dir)
        if not scan_path.exists():
            self.logger.error(f"❌ 扫描目录不存在: {scan_dir}")
            return 0
        
        magnet_files = list(scan_path.glob("*.magnet"))
        if not magnet_files:
            self.logger.info(f"📁 在 {scan_dir} 中未找到磁力链接文件")
            return 0
        
        self.logger.info(f"📁 找到 {len(magnet_files)} 个磁力链接文件")
        
        success_count = 0
        for magnet_file in magnet_files:
            self.logger.info(f"🔄 处理: {magnet_file.name}")
            if self.process_magnet_file(str(magnet_file), output_dir):
                success_count += 1
        
        self.logger.info(f"✅ 成功转换 {success_count}/{len(magnet_files)} 个文件")
        return success_count

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="基于 qBittorrent Web API 的磁力链接转换器")
    parser.add_argument("--host", default="localhost", help="qBittorrent Web UI 主机")
    parser.add_argument("--port", type=int, default=8080, help="qBittorrent Web UI 端口")
    parser.add_argument("--username", default="admin", help="用户名")
    parser.add_argument("--password", default="adminadmin", help="密码")
    parser.add_argument("--download-dir", default="./qbt_downloads", help="下载目录")
    parser.add_argument("--scan-dir", default="./test_input", help="磁力链接文件扫描目录")
    parser.add_argument("--output-dir", default="./torrent_output", help="种子文件输出目录")
    parser.add_argument("--start-daemon", action="store_true", help="启动 qBittorrent 守护进程")
    parser.add_argument("--stop-daemon", action="store_true", help="停止 qBittorrent 守护进程")
    parser.add_argument("--test-connection", action="store_true", help="测试连接")
    parser.add_argument("--magnet", help="直接转换单个磁力链接")
    
    args = parser.parse_args()
    
    # 创建转换器
    converter = QBittorrentMagnetConverter(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        download_dir=args.download_dir
    )
    
    try:
        if args.start_daemon:
            if converter.start_qbittorrent():
                print("✅ qBittorrent 守护进程启动成功")
                return 0
            else:
                print("❌ qBittorrent 守护进程启动失败")
                return 1
        
        elif args.stop_daemon:
            if converter.stop_qbittorrent():
                print("✅ qBittorrent 守护进程停止成功")
                return 0
            else:
                print("❌ qBittorrent 守护进程停止失败")
                return 1
        
        elif args.test_connection:
            if converter.test_connection():
                print("✅ 连接测试成功")
                return 0
            else:
                print("❌ 连接测试失败")
                return 1
        
        elif args.magnet:
            # 转换单个磁力链接
            result = converter.convert_magnet_to_torrent(args.magnet)
            if result:
                print(f"✅ 转换成功: {result}")
                return 0
            else:
                print("❌ 转换失败")
                return 1
        
        else:
            # 扫描并转换
            success_count = converter.scan_and_convert(args.scan_dir, args.output_dir)
            if success_count > 0:
                print(f"🎉 成功转换 {success_count} 个磁力链接")
                return 0
            else:
                print("❌ 没有成功转换任何文件")
                return 1
    
    except KeyboardInterrupt:
        print("\n🛑 用户中断")
        return 1
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        return 1
    finally:
        # 确保登出
        converter.logout()

if __name__ == "__main__":
    import sys
    sys.exit(main())