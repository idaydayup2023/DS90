#!/usr/bin/env python3
"""
基于 aria2 的磁力链接转换器
aria2 是一个轻量级、稳定的多协议下载工具，支持磁力链接
"""

import json
import time
import requests
import subprocess
import os
import signal
import argparse
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import quote, unquote

class Aria2MagnetConverter:
    """基于 aria2 的磁力链接转换器"""
    
    def __init__(self, aria2_host: str = "localhost", aria2_port: int = 6800, 
                 aria2_secret: str = "", download_dir: str = "./aria2_downloads"):
        """
        初始化 aria2 转换器
        
        Args:
            aria2_host: aria2 RPC 服务器地址
            aria2_port: aria2 RPC 端口
            aria2_secret: aria2 RPC 密钥
            download_dir: 下载目录
        """
        self.host = aria2_host
        self.port = aria2_port
        self.secret = aria2_secret
        self.download_dir = Path(download_dir)
        self.rpc_url = f"http://{aria2_host}:{aria2_port}/jsonrpc"
        self.aria2_process = None
        
        # 创建下载目录
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # 设置日志
        self.logger = self._setup_logging()
        
        # RPC 请求 ID 计数器
        self.request_id = 1
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger("Aria2MagnetConverter")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def start_aria2_daemon(self, config_file: Optional[str] = None) -> bool:
        """
        启动 aria2 守护进程
        
        Args:
            config_file: aria2 配置文件路径
            
        Returns:
            是否启动成功
        """
        try:
            # 检查 aria2c 是否可用
            result = subprocess.run(['aria2c', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                self.logger.error("❌ aria2c 未安装或不可用")
                self.logger.info("💡 请安装 aria2: brew install aria2 (macOS) 或 apt install aria2 (Ubuntu)")
                return False
            
            # 构建启动命令
            cmd = [
                'aria2c',
                '--enable-rpc',
                f'--rpc-listen-port={self.port}',
                '--rpc-allow-origin-all',
                '--rpc-listen-all',
                f'--dir={self.download_dir}',
                '--continue=true',
                '--max-connection-per-server=16',
                '--max-concurrent-downloads=5',
                '--split=16',
                '--min-split-size=1M',
                '--bt-max-peers=100',
                '--seed-time=0',  # 不做种
                '--bt-detach-seed-only=true',
                '--daemon=true'
            ]
            
            # 添加密钥
            if self.secret:
                cmd.append(f'--rpc-secret={self.secret}')
            
            # 添加配置文件
            if config_file and Path(config_file).exists():
                cmd.append(f'--conf-path={config_file}')
            
            self.logger.info("🚀 启动 aria2 守护进程...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                self.logger.info("✅ aria2 守护进程启动成功")
                # 等待服务启动
                time.sleep(2)
                return self.test_connection()
            else:
                self.logger.error(f"❌ aria2 启动失败: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("❌ aria2 启动超时")
            return False
        except FileNotFoundError:
            self.logger.error("❌ 未找到 aria2c 命令")
            return False
        except Exception as e:
            self.logger.error(f"❌ 启动 aria2 异常: {e}")
            return False
    
    def stop_aria2_daemon(self) -> bool:
        """停止 aria2 守护进程"""
        try:
            response = self._rpc_call('aria2.shutdown')
            if response:
                self.logger.info("✅ aria2 守护进程已停止")
                return True
            else:
                # 尝试强制停止
                subprocess.run(['pkill', '-f', 'aria2c'], capture_output=True)
                self.logger.info("🔄 强制停止 aria2 进程")
                return True
        except Exception as e:
            self.logger.error(f"❌ 停止 aria2 失败: {e}")
            return False
    
    def test_connection(self) -> bool:
        """测试与 aria2 的连接"""
        try:
            response = self._rpc_call('aria2.getVersion')
            if response and 'result' in response:
                version = response['result']['version']
                self.logger.info(f"✅ 连接成功，aria2 版本: {version}")
                return True
            else:
                self.logger.error("❌ 连接失败")
                return False
        except Exception as e:
            self.logger.error(f"❌ 连接测试异常: {e}")
            return False
    
    def _rpc_call(self, method: str, params: Optional[List[Any]] = None) -> Optional[Dict[str, Any]]:
        """
        调用 aria2 RPC 方法
        
        Args:
            method: RPC 方法名
            params: 参数列表
            
        Returns:
            RPC 响应
        """
        if params is None:
            params = []
        
        # 如果有密钥，添加到参数开头
        if self.secret:
            params.insert(0, f"token:{self.secret}")
        
        payload = {
            "jsonrpc": "2.0",
            "id": str(self.request_id),
            "method": method,
            "params": params
        }
        
        self.request_id += 1
        
        try:
            response = requests.post(
                self.rpc_url,
                json=payload,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"❌ RPC 调用失败 {method}: {e}")
            return None
    
    def add_magnet(self, magnet_uri: str, options: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """
        添加磁力链接下载任务
        
        Args:
            magnet_uri: 磁力链接
            options: 下载选项
            
        Returns:
            任务 GID，失败返回 None
        """
        if options is None:
            options = {}
        
        # 设置默认选项
        default_options = {
            "bt-metadata-only": "true",  # 只下载元数据
            "bt-save-metadata": "true",  # 保存元数据
            "follow-torrent": "false",   # 不自动开始下载
        }
        default_options.update(options)
        
        try:
            response = self._rpc_call('aria2.addUri', [[magnet_uri], default_options])
            if response and 'result' in response:
                gid = response['result']
                self.logger.info(f"✅ 磁力链接添加成功，GID: {gid}")
                return gid
            else:
                error = response.get('error', {}) if response else {}
                self.logger.error(f"❌ 添加磁力链接失败: {error}")
                return None
        except Exception as e:
            self.logger.error(f"❌ 添加磁力链接异常: {e}")
            return None
    
    def get_task_status(self, gid: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        try:
            response = self._rpc_call('aria2.tellStatus', [gid])
            if response and 'result' in response:
                return response['result']
            else:
                return None
        except Exception as e:
            self.logger.error(f"❌ 获取任务状态失败: {e}")
            return None
    
    def wait_for_metadata(self, gid: str, timeout: int = 300) -> bool:
        """
        等待元数据下载完成
        
        Args:
            gid: 任务 GID
            timeout: 超时时间（秒）
            
        Returns:
            是否成功获取元数据
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.get_task_status(gid)
            if not status:
                self.logger.error(f"❌ 无法获取任务状态: {gid}")
                return False
            
            task_status = status.get('status', '')
            
            if task_status == 'complete':
                self.logger.info(f"✅ 元数据下载完成: {gid}")
                return True
            elif task_status == 'error':
                error_msg = status.get('errorMessage', '未知错误')
                self.logger.error(f"❌ 任务失败: {error_msg}")
                return False
            elif task_status in ['active', 'waiting', 'paused']:
                # 显示进度
                total_length = int(status.get('totalLength', 0))
                completed_length = int(status.get('completedLength', 0))
                
                if total_length > 0:
                    progress = (completed_length / total_length) * 100
                    self.logger.info(f"📥 下载元数据中... {progress:.1f}% ({completed_length}/{total_length})")
                else:
                    self.logger.info(f"📥 连接中... 状态: {task_status}")
            
            time.sleep(5)
        
        self.logger.error(f"⏰ 等待元数据超时: {gid}")
        return False
    
    def find_torrent_file(self, gid: str) -> Optional[Path]:
        """查找生成的种子文件"""
        try:
            status = self.get_task_status(gid)
            if not status:
                return None
            
            # 获取任务信息
            files = status.get('files', [])
            if not files:
                return None
            
            # 查找 .torrent 文件
            for file_info in files:
                file_path = Path(file_info.get('path', ''))
                if file_path.suffix.lower() == '.torrent':
                    if file_path.exists():
                        return file_path
            
            # 在下载目录中搜索
            for torrent_file in self.download_dir.glob("*.torrent"):
                return torrent_file
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ 查找种子文件失败: {e}")
            return None
    
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
        gid = self.add_magnet(magnet_uri)
        if not gid:
            return None
        
        try:
            # 等待元数据下载
            if not self.wait_for_metadata(gid, timeout):
                return None
            
            # 查找种子文件
            torrent_file = self.find_torrent_file(gid)
            if not torrent_file:
                self.logger.error("❌ 未找到生成的种子文件")
                return None
            
            # 移动到指定位置
            if output_path:
                output_file = Path(output_path)
                output_file.parent.mkdir(parents=True, exist_ok=True)
                torrent_file = torrent_file.rename(output_file)
            
            self.logger.info(f"✅ 转换成功: {torrent_file}")
            return torrent_file
            
        finally:
            # 清理任务
            try:
                self._rpc_call('aria2.remove', [gid])
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
    parser = argparse.ArgumentParser(description="基于 aria2 的磁力链接转换器")
    parser.add_argument("--host", default="localhost", help="aria2 RPC 主机")
    parser.add_argument("--port", type=int, default=6800, help="aria2 RPC 端口")
    parser.add_argument("--secret", default="", help="aria2 RPC 密钥")
    parser.add_argument("--download-dir", default="./aria2_downloads", help="aria2 下载目录")
    parser.add_argument("--scan-dir", default="./test_input", help="磁力链接文件扫描目录")
    parser.add_argument("--output-dir", default="./torrent_output", help="种子文件输出目录")
    parser.add_argument("--start-daemon", action="store_true", help="启动 aria2 守护进程")
    parser.add_argument("--stop-daemon", action="store_true", help="停止 aria2 守护进程")
    parser.add_argument("--test-connection", action="store_true", help="测试连接")
    parser.add_argument("--magnet", help="直接转换单个磁力链接")
    
    args = parser.parse_args()
    
    # 创建转换器
    converter = Aria2MagnetConverter(
        aria2_host=args.host,
        aria2_port=args.port,
        aria2_secret=args.secret,
        download_dir=args.download_dir
    )
    
    try:
        if args.start_daemon:
            if converter.start_aria2_daemon():
                print("✅ aria2 守护进程启动成功")
                return 0
            else:
                print("❌ aria2 守护进程启动失败")
                return 1
        
        elif args.stop_daemon:
            if converter.stop_aria2_daemon():
                print("✅ aria2 守护进程停止成功")
                return 0
            else:
                print("❌ aria2 守护进程停止失败")
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

if __name__ == "__main__":
    import sys
    sys.exit(main())