#!/usr/bin/env python3
"""
Synology Download Station API 客户端
直接调用Download Station下载磁力链接，无需转换为torrent文件
"""

import requests
import json
import time
import logging
import argparse
import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import quote, unquote

class SynologyDownloadStation:
    """Synology Download Station API 客户端"""
    
    def __init__(self, host: str, port: int = 5000, username: str = "", password: str = "", use_https: bool = False):
        """
        初始化Download Station客户端
        
        Args:
            host: Synology NAS的IP地址或域名
            port: 端口号，默认5000 (HTTP) 或 5001 (HTTPS)
            username: 用户名
            password: 密码
            use_https: 是否使用HTTPS
        """
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.session_id = None
        
        # 设置基础URL
        protocol = "https" if use_https else "http"
        self.base_url = f"{protocol}://{host}:{port}/webapi"
        
        # 设置日志
        self.logger = self._setup_logging()
        
        # API信息
        self.api_info = {}
        
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger("SynologyDownloadStation")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def get_api_info(self) -> bool:
        """获取API信息"""
        try:
            url = f"{self.base_url}/query.cgi"
            params = {
                'api': 'SYNO.API.Info',
                'version': '1',
                'method': 'query',
                'query': 'SYNO.API.Auth,SYNO.DownloadStation.Task'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                self.api_info = result.get('data', {})
                self.logger.info("✅ 成功获取API信息")
                return True
            else:
                self.logger.error(f"❌ 获取API信息失败: {result.get('error')}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 获取API信息异常: {e}")
            return False
    
    def login(self) -> bool:
        """登录到Download Station"""
        try:
            # 获取Auth API信息
            auth_info = self.api_info.get('SYNO.API.Auth', {})
            if not auth_info:
                self.logger.error("❌ 未找到Auth API信息")
                return False
            
            url = f"{self.base_url}/auth.cgi"
            params = {
                'api': 'SYNO.API.Auth',
                'version': auth_info.get('maxVersion', '3'),
                'method': 'login',
                'account': self.username,
                'passwd': self.password,
                'session': 'DownloadStation',
                'format': 'sid'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                self.session_id = result.get('data', {}).get('sid')
                self.logger.info("✅ 登录成功")
                return True
            else:
                error_code = result.get('error', {}).get('code')
                self.logger.error(f"❌ 登录失败，错误代码: {error_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ 登录异常: {e}")
            return False
    
    def logout(self) -> bool:
        """登出"""
        if not self.session_id:
            return True
            
        try:
            auth_info = self.api_info.get('SYNO.API.Auth', {})
            url = f"{self.base_url}/auth.cgi"
            params = {
                'api': 'SYNO.API.Auth',
                'version': auth_info.get('maxVersion', '3'),
                'method': 'logout',
                'session': 'DownloadStation',
                '_sid': self.session_id
            }
            
            response = requests.get(url, params=params, timeout=10)
            result = response.json()
            
            if result.get('success'):
                self.logger.info("✅ 登出成功")
            else:
                self.logger.warning(f"⚠️ 登出失败: {result.get('error')}")
            
            self.session_id = None
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 登出异常: {e}")
            return False
    
    def add_magnet_task(self, magnet_link: str, destination: str = "") -> Optional[str]:
        """
        添加磁力链接下载任务
        
        Args:
            magnet_link: 磁力链接
            destination: 下载目录，为空则使用默认目录
            
        Returns:
            任务ID，失败返回None
        """
        if not self.session_id:
            self.logger.error("❌ 未登录，无法添加任务")
            return None
        
        try:
            # 获取DownloadStation Task API信息
            task_info = self.api_info.get('SYNO.DownloadStation.Task', {})
            if not task_info:
                self.logger.error("❌ 未找到DownloadStation Task API信息")
                return None
            
            url = f"{self.base_url}/DownloadStation/task.cgi"
            params = {
                'api': 'SYNO.DownloadStation.Task',
                'version': task_info.get('maxVersion', '3'),
                'method': 'create',
                '_sid': self.session_id,
                'uri': magnet_link
            }
            
            # 如果指定了下载目录
            if destination:
                params['destination'] = destination
            
            response = requests.post(url, data=params, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                task_id = result.get('data', {}).get('task_id')
                self.logger.info(f"✅ 成功添加下载任务，任务ID: {task_id}")
                return task_id
            else:
                error_code = result.get('error', {}).get('code')
                error_msg = self._get_error_message(error_code)
                self.logger.error(f"❌ 添加任务失败: {error_msg} (代码: {error_code})")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ 添加任务异常: {e}")
            return None
    
    def get_task_list(self) -> List[Dict[str, Any]]:
        """获取任务列表"""
        if not self.session_id:
            self.logger.error("❌ 未登录，无法获取任务列表")
            return []
        
        try:
            task_info = self.api_info.get('SYNO.DownloadStation.Task', {})
            url = f"{self.base_url}/DownloadStation/task.cgi"
            params = {
                'api': 'SYNO.DownloadStation.Task',
                'version': task_info.get('maxVersion', '3'),
                'method': 'list',
                '_sid': self.session_id,
                'additional': 'detail,transfer'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            if result.get('success'):
                tasks = result.get('data', {}).get('tasks', [])
                return tasks
            else:
                self.logger.error(f"❌ 获取任务列表失败: {result.get('error')}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ 获取任务列表异常: {e}")
            return []
    
    def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取指定任务信息"""
        tasks = self.get_task_list()
        for task in tasks:
            if task.get('id') == task_id:
                return task
        return None
    
    def _get_error_message(self, error_code: int) -> str:
        """获取错误信息"""
        error_messages = {
            100: "未知错误",
            101: "无效参数",
            102: "请求的API不存在",
            103: "请求的方法不存在",
            104: "请求的版本不支持",
            105: "登录的会话没有权限",
            106: "会话超时",
            107: "会话被中断",
            400: "文件上传失败",
            401: "最大任务数量限制",
            402: "目标已存在",
            403: "目标不存在",
            404: "无效的任务操作",
            405: "无效的任务ID",
            406: "无法读取任务配置"
        }
        return error_messages.get(error_code, f"未知错误代码: {error_code}")
    
    def process_magnet_file(self, file_path: str, destination: str = "") -> int:
        """
        处理磁力链接文件
        
        Args:
            file_path: 磁力链接文件路径
            destination: 下载目录
            
        Returns:
            成功添加的任务数量
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                magnet_link = f.read().strip()
            
            if not magnet_link.startswith('magnet:'):
                self.logger.error(f"❌ 无效的磁力链接文件: {file_path}")
                return 0
            
            # 解析磁力链接获取文件名
            file_name = "未知文件"
            if '&dn=' in magnet_link:
                try:
                    dn_part = magnet_link.split('&dn=')[1].split('&')[0]
                    file_name = unquote(dn_part)
                except:
                    pass
            
            self.logger.info(f"处理磁力链接: {file_name}")
            
            task_id = self.add_magnet_task(magnet_link, destination)
            if task_id:
                self.logger.info(f"✅ 成功添加到Download Station: {file_name}")
                return 1
            else:
                self.logger.error(f"❌ 添加失败: {file_name}")
                return 0
                
        except Exception as e:
            self.logger.error(f"❌ 处理文件失败 {file_path}: {e}")
            return 0
    
    def scan_and_add_magnets(self, scan_dir: str, destination: str = "") -> int:
        """
        扫描目录并添加所有磁力链接到Download Station
        
        Args:
            scan_dir: 扫描目录
            destination: 下载目录
            
        Returns:
            成功添加的任务数量
        """
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
            success_count += self.process_magnet_file(str(magnet_file), destination)
        
        self.logger.info(f"✅ 成功添加 {success_count}/{len(magnet_files)} 个任务到Download Station")
        return success_count

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Synology Download Station 磁力链接管理器")
    parser.add_argument("--host", required=True, help="Synology NAS IP地址或域名")
    parser.add_argument("--port", type=int, default=5000, help="端口号 (默认: 5000)")
    parser.add_argument("--username", required=True, help="用户名")
    parser.add_argument("--password", required=True, help="密码")
    parser.add_argument("--https", action="store_true", help="使用HTTPS连接")
    parser.add_argument("--scan-dir", default="./test_input", help="磁力链接文件扫描目录")
    parser.add_argument("--destination", default="", help="下载目录")
    parser.add_argument("--list-tasks", action="store_true", help="列出当前任务")
    
    args = parser.parse_args()
    
    # 创建Download Station客户端
    ds = SynologyDownloadStation(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        use_https=args.https
    )
    
    try:
        # 获取API信息
        if not ds.get_api_info():
            print("❌ 无法获取API信息，请检查网络连接和NAS地址")
            return 1
        
        # 登录
        if not ds.login():
            print("❌ 登录失败，请检查用户名和密码")
            return 1
        
        if args.list_tasks:
            # 列出任务
            tasks = ds.get_task_list()
            if tasks:
                print(f"\n📋 当前有 {len(tasks)} 个下载任务:")
                for task in tasks:
                    status = task.get('status', 'unknown')
                    title = task.get('title', 'Unknown')
                    size = task.get('size', 0)
                    progress = task.get('additional', {}).get('detail', {}).get('completed_time', 0)
                    print(f"  - {title} [{status}] ({size} bytes)")
            else:
                print("📋 当前没有下载任务")
        else:
            # 扫描并添加磁力链接
            success_count = ds.scan_and_add_magnets(args.scan_dir, args.destination)
            if success_count > 0:
                print(f"\n🎉 成功添加 {success_count} 个下载任务到Download Station!")
                print("💡 您可以在Download Station中查看下载进度")
            else:
                print("❌ 没有成功添加任何任务")
        
    finally:
        # 登出
        ds.logout()
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())