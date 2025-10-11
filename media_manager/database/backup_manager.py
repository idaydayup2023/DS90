#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库备份和恢复管理器
提供自动备份、定时备份、增量备份和数据恢复功能
"""

import os
import sqlite3
import shutil
import gzip
import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from .db_manager import get_db_manager

class BackupManager:
    """数据库备份和恢复管理器"""
    
    def __init__(self, backup_dir: Optional[str] = None, max_backups: int = 10):
        """
        初始化备份管理器
        
        Args:
            backup_dir: 备份目录，默认为数据库目录下的backups文件夹
            max_backups: 最大备份文件数量
        """
        self.db_manager = get_db_manager()
        
        if backup_dir is None:
            db_dir = os.path.dirname(self.db_manager.db_path)
            backup_dir = os.path.join(db_dir, 'backups')
        
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_backups = max_backups
        self.logger = logging.getLogger(__name__)
        
        # 自动备份配置
        self.auto_backup_enabled = False
        self.backup_interval_hours = 24  # 默认每24小时备份一次
        self.backup_thread = None
        self.backup_stop_event = threading.Event()
        
        # 备份元数据文件
        self.metadata_file = self.backup_dir / 'backup_metadata.json'
        self._load_metadata()
    
    def _load_metadata(self):
        """加载备份元数据"""
        try:
            if self.metadata_file.exists():
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
            else:
                self.metadata = {
                    'backups': [],
                    'last_backup': None,
                    'auto_backup_enabled': False,
                    'backup_interval_hours': 24
                }
        except Exception as e:
            self.logger.error(f"加载备份元数据失败: {e}")
            self.metadata = {
                'backups': [],
                'last_backup': None,
                'auto_backup_enabled': False,
                'backup_interval_hours': 24
            }
    
    def _save_metadata(self):
        """保存备份元数据"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"保存备份元数据失败: {e}")
    
    def create_backup(self, backup_name: Optional[str] = None, compress: bool = True) -> Optional[str]:
        """
        创建数据库备份
        
        Args:
            backup_name: 备份名称，默认使用时间戳
            compress: 是否压缩备份文件
            
        Returns:
            备份文件路径，失败返回None
        """
        try:
            # 生成备份文件名
            if backup_name is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"backup_{timestamp}"
            
            # 确定文件扩展名
            if compress:
                backup_filename = f"{backup_name}.db.gz"
            else:
                backup_filename = f"{backup_name}.db"
            
            backup_path = self.backup_dir / backup_filename
            
            # 创建备份
            if compress:
                # 压缩备份
                with open(self.db_manager.db_path, 'rb') as source:
                    with gzip.open(backup_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
            else:
                # 直接复制
                shutil.copy2(self.db_manager.db_path, backup_path)
            
            # 获取备份文件信息
            backup_info = {
                'name': backup_name,
                'filename': backup_filename,
                'path': str(backup_path),
                'created_at': datetime.now().isoformat(),
                'size_bytes': backup_path.stat().st_size,
                'compressed': compress,
                'database_stats': self.db_manager.get_database_stats()
            }
            
            # 更新元数据
            self.metadata['backups'].append(backup_info)
            self.metadata['last_backup'] = backup_info['created_at']
            self._save_metadata()
            
            # 清理旧备份
            self._cleanup_old_backups()
            
            self.logger.info(f"数据库备份创建成功: {backup_path}")
            return str(backup_path)
            
        except Exception as e:
            self.logger.error(f"创建数据库备份失败: {e}")
            return None
    
    def restore_backup(self, backup_path: str, verify: bool = True) -> bool:
        """
        从备份恢复数据库
        
        Args:
            backup_path: 备份文件路径
            verify: 是否验证恢复后的数据库
            
        Returns:
            是否恢复成功
        """
        try:
            backup_path_obj = Path(backup_path)
            
            if not backup_path_obj.exists():
                self.logger.error(f"备份文件不存在: {backup_path}")
                return False
            
            # 创建当前数据库的临时备份
            temp_backup = self.backup_dir / f"temp_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(self.db_manager.db_path, temp_backup)
            
            try:
                # 关闭所有数据库连接
                self.db_manager.close_all_connections()
                
                # 恢复数据库
                if backup_path_obj.suffix == '.gz':
                    # 解压缩恢复
                    with gzip.open(backup_path_obj, 'rb') as source:
                        with open(self.db_manager.db_path, 'wb') as target:
                            shutil.copyfileobj(source, target)
                else:
                    # 直接复制
                    shutil.copy2(backup_path_obj, self.db_manager.db_path)
                
                # 验证恢复的数据库
                if verify:
                    # 重新初始化数据库管理器
                    self.db_manager._pool_initialized = False
                    self.db_manager._initialize_connection_pool()
                    
                    if not self.db_manager.check_database_integrity():
                        raise Exception("恢复的数据库完整性检查失败")
                
                # 删除临时备份
                temp_backup.unlink()
                
                self.logger.info(f"数据库恢复成功: {backup_path_obj}")
                return True
                
            except Exception as e:
                # 恢复失败，回滚到临时备份
                self.logger.error(f"数据库恢复失败，正在回滚: {e}")
                shutil.copy2(temp_backup, self.db_manager.db_path)
                temp_backup.unlink()
                
                # 重新初始化连接池
                self.db_manager._pool_initialized = False
                self.db_manager._initialize_connection_pool()
                
                return False
                
        except Exception as e:
            self.logger.error(f"数据库恢复失败: {e}")
            return False
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        列出所有备份
        
        Returns:
            备份信息列表
        """
        # 刷新备份列表
        self._refresh_backup_list()
        return self.metadata['backups']
    
    def _refresh_backup_list(self):
        """刷新备份列表，扫描备份目录"""
        try:
            existing_backups = []
            
            # 扫描备份目录
            for backup_file in self.backup_dir.glob("*.db*"):
                if backup_file.name == 'backup_metadata.json':
                    continue
                
                # 查找现有元数据
                existing_info = None
                for backup_info in self.metadata['backups']:
                    if backup_info['filename'] == backup_file.name:
                        existing_info = backup_info
                        break
                
                if existing_info:
                    # 更新文件大小
                    existing_info['size_bytes'] = backup_file.stat().st_size
                    existing_backups.append(existing_info)
                else:
                    # 新发现的备份文件
                    backup_info = {
                        'name': backup_file.stem.replace('.db', ''),
                        'filename': backup_file.name,
                        'path': str(backup_file),
                        'created_at': datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat(),
                        'size_bytes': backup_file.stat().st_size,
                        'compressed': backup_file.suffix == '.gz',
                        'database_stats': None
                    }
                    existing_backups.append(backup_info)
            
            # 按创建时间排序
            existing_backups.sort(key=lambda x: x['created_at'], reverse=True)
            
            self.metadata['backups'] = existing_backups
            self._save_metadata()
            
        except Exception as e:
            self.logger.error(f"刷新备份列表失败: {e}")
    
    def delete_backup(self, backup_name: str) -> bool:
        """
        删除指定备份
        
        Args:
            backup_name: 备份名称或文件名
            
        Returns:
            是否删除成功
        """
        try:
            backup_info = None
            
            # 查找备份信息
            for info in self.metadata['backups']:
                if info['name'] == backup_name or info['filename'] == backup_name:
                    backup_info = info
                    break
            
            if not backup_info:
                self.logger.error(f"未找到备份: {backup_name}")
                return False
            
            # 删除备份文件
            backup_path = Path(backup_info['path'])
            if backup_path.exists():
                backup_path.unlink()
            
            # 从元数据中移除
            self.metadata['backups'].remove(backup_info)
            self._save_metadata()
            
            self.logger.info(f"备份删除成功: {backup_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"删除备份失败: {e}")
            return False
    
    def _cleanup_old_backups(self):
        """清理旧备份，保持最大备份数量"""
        try:
            if len(self.metadata['backups']) <= self.max_backups:
                return
            
            # 按创建时间排序，保留最新的备份
            self.metadata['backups'].sort(key=lambda x: x['created_at'], reverse=True)
            
            # 删除超出数量的备份
            backups_to_delete = self.metadata['backups'][self.max_backups:]
            
            for backup_info in backups_to_delete:
                backup_path = Path(backup_info['path'])
                if backup_path.exists():
                    backup_path.unlink()
                    self.logger.info(f"清理旧备份: {backup_info['filename']}")
            
            # 更新元数据
            self.metadata['backups'] = self.metadata['backups'][:self.max_backups]
            self._save_metadata()
            
        except Exception as e:
            self.logger.error(f"清理旧备份失败: {e}")
    
    def start_auto_backup(self, interval_hours: int = 24):
        """
        启动自动备份
        
        Args:
            interval_hours: 备份间隔（小时）
        """
        if self.auto_backup_enabled:
            self.logger.warning("自动备份已启用")
            return
        
        self.backup_interval_hours = interval_hours
        self.auto_backup_enabled = True
        self.backup_stop_event.clear()
        
        # 启动备份线程
        self.backup_thread = threading.Thread(target=self._auto_backup_worker, daemon=True)
        self.backup_thread.start()
        
        # 更新元数据
        self.metadata['auto_backup_enabled'] = True
        self.metadata['backup_interval_hours'] = interval_hours
        self._save_metadata()
        
        self.logger.info(f"自动备份已启动，间隔: {interval_hours}小时")
    
    def stop_auto_backup(self):
        """停止自动备份"""
        if not self.auto_backup_enabled:
            return
        
        self.auto_backup_enabled = False
        self.backup_stop_event.set()
        
        if self.backup_thread and self.backup_thread.is_alive():
            self.backup_thread.join(timeout=5)
        
        # 更新元数据
        self.metadata['auto_backup_enabled'] = False
        self._save_metadata()
        
        self.logger.info("自动备份已停止")
    
    def _auto_backup_worker(self):
        """自动备份工作线程"""
        while self.auto_backup_enabled and not self.backup_stop_event.is_set():
            try:
                # 检查是否需要备份
                if self._should_create_backup():
                    backup_name = f"auto_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    self.create_backup(backup_name, compress=True)
                
                # 等待下次检查（每小时检查一次）
                self.backup_stop_event.wait(timeout=3600)
                
            except Exception as e:
                self.logger.error(f"自动备份工作线程错误: {e}")
                time.sleep(300)  # 出错后等待5分钟再重试
    
    def _should_create_backup(self) -> bool:
        """检查是否应该创建备份"""
        if not self.metadata['last_backup']:
            return True
        
        try:
            last_backup_time = datetime.fromisoformat(self.metadata['last_backup'])
            time_since_backup = datetime.now() - last_backup_time
            
            return time_since_backup >= timedelta(hours=self.backup_interval_hours)
        except Exception:
            return True
    
    def get_backup_stats(self) -> Dict[str, Any]:
        """
        获取备份统计信息
        
        Returns:
            备份统计信息
        """
        self._refresh_backup_list()
        
        stats = {
            'total_backups': len(self.metadata['backups']),
            'last_backup': self.metadata['last_backup'],
            'auto_backup_enabled': self.auto_backup_enabled,
            'backup_interval_hours': self.backup_interval_hours,
            'backup_directory': str(self.backup_dir),
            'max_backups': self.max_backups,
            'total_backup_size_bytes': sum(b['size_bytes'] for b in self.metadata['backups']),
            'oldest_backup': None,
            'newest_backup': None
        }
        
        if self.metadata['backups']:
            sorted_backups = sorted(self.metadata['backups'], key=lambda x: x['created_at'])
            stats['oldest_backup'] = sorted_backups[0]['created_at']
            stats['newest_backup'] = sorted_backups[-1]['created_at']
        
        # 计算总大小（MB）
        stats['total_backup_size_mb'] = round(stats['total_backup_size_bytes'] / (1024 * 1024), 2)
        
        return stats

# 全局备份管理器实例
backup_manager = None

def get_backup_manager(backup_dir: Optional[str] = None, max_backups: int = 10) -> BackupManager:
    """获取全局备份管理器实例"""
    global backup_manager
    if backup_manager is None:
        backup_manager = BackupManager(backup_dir, max_backups)
    return backup_manager

if __name__ == "__main__":
    # 测试代码
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    # 创建备份管理器
    backup_mgr = BackupManager()
    
    # 创建备份
    backup_path = backup_mgr.create_backup("test_backup")
    if backup_path:
        print(f"备份创建成功: {backup_path}")
    
    # 列出备份
    backups = backup_mgr.list_backups()
    print(f"当前备份数量: {len(backups)}")
    
    # 获取统计信息
    stats = backup_mgr.get_backup_stats()
    print("备份统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # 启动自动备份（测试用，实际使用时间间隔会更长）
    # backup_mgr.start_auto_backup(interval_hours=1)
    
    print("备份管理器测试完成")