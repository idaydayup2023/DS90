#!/usr/bin/env python3
"""
Synology Download Station 磁力链接管理器 (增强版)
支持配置文件、自动监控、批量管理等功能
"""

import json
import time
import argparse
import os
import signal
import sys
from pathlib import Path
from typing import Dict, Any, List
from synology_download_station import SynologyDownloadStation

class SynologyMagnetManager:
    """Synology磁力链接管理器"""
    
    def __init__(self, config_file: str = "ds_config.json"):
        """
        初始化管理器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.config = self.load_config()
        self.ds = None
        self.running = False
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        config_path = Path(self.config_file)
        
        if not config_path.exists():
            print(f"⚠️ 配置文件不存在: {self.config_file}")
            print("💡 请复制 ds_config.json.example 为 ds_config.json 并修改配置")
            return self._get_default_config()
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            print(f"✅ 成功加载配置文件: {self.config_file}")
            return config
        except Exception as e:
            print(f"❌ 加载配置文件失败: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "host": "192.168.1.100",
            "port": 5000,
            "username": "",
            "password": "",
            "use_https": False,
            "default_destination": "",
            "scan_directories": ["./test_input"],
            "auto_scan_interval": 300,
            "max_concurrent_downloads": 5,
            "retry_failed_tasks": True,
            "cleanup_completed_files": False
        }
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        print(f"\n🛑 收到信号 {signum}，正在停止...")
        self.running = False
    
    def connect(self) -> bool:
        """连接到Download Station"""
        try:
            self.ds = SynologyDownloadStation(
                host=self.config["host"],
                port=self.config["port"],
                username=self.config["username"],
                password=self.config["password"],
                use_https=self.config["use_https"]
            )
            
            # 获取API信息并登录
            if not self.ds.get_api_info():
                print("❌ 无法获取API信息")
                return False
            
            if not self.ds.login():
                print("❌ 登录失败")
                return False
            
            print("✅ 成功连接到Download Station")
            return True
            
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def disconnect(self):
        """断开连接"""
        if self.ds:
            self.ds.logout()
            self.ds = None
    
    def scan_once(self) -> int:
        """执行一次扫描"""
        if not self.ds:
            print("❌ 未连接到Download Station")
            return 0
        
        total_added = 0
        scan_dirs = self.config.get("scan_directories", ["./test_input"])
        destination = self.config.get("default_destination", "")
        
        for scan_dir in scan_dirs:
            print(f"📁 扫描目录: {scan_dir}")
            added = self.ds.scan_and_add_magnets(scan_dir, destination)
            total_added += added
        
        return total_added
    
    def auto_monitor(self):
        """自动监控模式"""
        if not self.connect():
            return False
        
        interval = self.config.get("auto_scan_interval", 300)
        print(f"🔄 开始自动监控模式，扫描间隔: {interval}秒")
        print("💡 按 Ctrl+C 停止监控")
        
        self.running = True
        try:
            while self.running:
                print(f"\n⏰ {time.strftime('%Y-%m-%d %H:%M:%S')} - 开始扫描...")
                
                added_count = self.scan_once()
                if added_count > 0:
                    print(f"✅ 本次扫描添加了 {added_count} 个任务")
                else:
                    print("📭 本次扫描没有新的磁力链接")
                
                # 检查任务状态
                self.check_task_status()
                
                # 等待下次扫描
                for i in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            print("\n🛑 用户中断监控")
        finally:
            self.disconnect()
            print("👋 监控已停止")
    
    def check_task_status(self):
        """检查任务状态"""
        if not self.ds:
            return
        
        try:
            if self.ds is None:
                return
            tasks = self.ds.get_task_list()
            if not tasks:
                return
            
            # 统计任务状态
            status_count = {}
            for task in tasks:
                status = task.get('status', 'unknown')
                status_count[status] = status_count.get(status, 0) + 1
            
            # 显示统计信息
            status_info = []
            for status, count in status_count.items():
                status_info.append(f"{status}: {count}")
            
            print(f"📊 任务状态: {', '.join(status_info)}")
            
        except Exception as e:
            print(f"❌ 检查任务状态失败: {e}")
    
    def list_tasks(self, detailed: bool = False):
        """列出任务"""
        if not self.connect():
            return
        
        try:
            if self.ds is None:
                return
            tasks = self.ds.get_task_list()
            if not tasks:
                print("📋 当前没有下载任务")
                return
            
            print(f"\n📋 当前有 {len(tasks)} 个下载任务:")
            print("-" * 80)
            
            for i, task in enumerate(tasks, 1):
                title = task.get('title', 'Unknown')
                status = task.get('status', 'unknown')
                size = task.get('size', 0)
                
                # 格式化大小
                if size > 0:
                    if size > 1024**3:  # GB
                        size_str = f"{size / (1024**3):.2f} GB"
                    elif size > 1024**2:  # MB
                        size_str = f"{size / (1024**2):.2f} MB"
                    else:
                        size_str = f"{size / 1024:.2f} KB"
                else:
                    size_str = "未知大小"
                
                print(f"{i:2d}. {title}")
                print(f"    状态: {status} | 大小: {size_str}")
                
                if detailed:
                    # 显示详细信息
                    detail = task.get('additional', {}).get('detail', {})
                    transfer = task.get('additional', {}).get('transfer', {})
                    
                    if detail:
                        create_time = detail.get('create_time', 0)
                        if create_time:
                            create_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(create_time))
                            print(f"    创建时间: {create_time_str}")
                    
                    if transfer and status == 'downloading':
                        downloaded = transfer.get('size_downloaded', 0)
                        speed = transfer.get('speed_download', 0)
                        
                        if size > 0:
                            progress = (downloaded / size) * 100
                            print(f"    进度: {progress:.1f}% ({downloaded}/{size})")
                        
                        if speed > 0:
                            speed_str = f"{speed / 1024:.1f} KB/s" if speed < 1024*1024 else f"{speed / (1024*1024):.1f} MB/s"
                            print(f"    下载速度: {speed_str}")
                
                print()
                
        except Exception as e:
            print(f"❌ 获取任务列表失败: {e}")
        finally:
            self.disconnect()
    
    def add_magnet_url(self, magnet_url: str, destination: str = ""):
        """添加单个磁力链接"""
        if not self.connect():
            return False
        
        try:
            if not destination:
                destination = self.config.get("default_destination", "")
            
            if self.ds is None:
                return False
            task_id = self.ds.add_magnet_task(magnet_url, destination)
            if task_id:
                print(f"✅ 成功添加磁力链接，任务ID: {task_id}")
                return True
            else:
                print("❌ 添加磁力链接失败")
                return False
                
        finally:
            self.disconnect()

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Synology Download Station 磁力链接管理器")
    parser.add_argument("--config", default="ds_config.json", help="配置文件路径")
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # 扫描命令
    scan_parser = subparsers.add_parser("scan", help="扫描并添加磁力链接")
    
    # 监控命令
    monitor_parser = subparsers.add_parser("monitor", help="自动监控模式")
    
    # 列表命令
    list_parser = subparsers.add_parser("list", help="列出下载任务")
    list_parser.add_argument("--detailed", action="store_true", help="显示详细信息")
    
    # 添加命令
    add_parser = subparsers.add_parser("add", help="添加磁力链接")
    add_parser.add_argument("magnet_url", help="磁力链接URL")
    add_parser.add_argument("--destination", help="下载目录")
    
    # 测试连接命令
    test_parser = subparsers.add_parser("test", help="测试连接")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # 创建管理器
    manager = SynologyMagnetManager(args.config)
    
    try:
        if args.command == "scan":
            if manager.connect():
                added = manager.scan_once()
                print(f"\n🎉 扫描完成，添加了 {added} 个任务")
            else:
                return 1
                
        elif args.command == "monitor":
            manager.auto_monitor()
            
        elif args.command == "list":
            manager.list_tasks(detailed=args.detailed)
            
        elif args.command == "add":
            success = manager.add_magnet_url(args.magnet_url, args.destination or "")
            return 0 if success else 1
            
        elif args.command == "test":
            if manager.connect():
                print("✅ 连接测试成功")
                manager.disconnect()
                return 0
            else:
                print("❌ 连接测试失败")
                return 1
                
    except Exception as e:
        print(f"❌ 执行命令失败: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())