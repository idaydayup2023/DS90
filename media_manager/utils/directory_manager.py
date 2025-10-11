#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目录管理器
负责处理NAS多卷多目录的路径解析、卷映射和目录验证
"""

import os
import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass

from ..database.db_manager import get_db_manager


@dataclass
class VolumeInfo:
    """存储卷信息"""
    id: int
    volume_name: str
    mount_path: str
    volume_type: str
    is_active: bool
    total_space: int
    free_space: int
    description: str
    priority: int


@dataclass
class ScanPathInfo:
    """扫描路径信息"""
    id: int
    volume_id: int
    path_type: str
    relative_path: str
    full_path: str
    is_enabled: bool
    scan_recursive: bool
    exclude_patterns: List[str]
    priority: int
    last_scanned: Optional[datetime]
    file_count: int
    total_size: int


class DirectoryManager:
    """目录管理器"""
    
    def __init__(self):
        """初始化目录管理器"""
        self.logger = logging.getLogger(__name__)
        self.db_manager = get_db_manager()
        self._volumes_cache = {}
        self._scan_paths_cache = {}
        self._last_cache_update = None
        
    def refresh_cache(self):
        """刷新缓存"""
        self._volumes_cache = {}
        self._scan_paths_cache = {}
        self._load_volumes()
        self._load_scan_paths()
        self._last_cache_update = datetime.now()
        
    def _load_volumes(self):
        """加载存储卷信息"""
        try:
            query = """
            SELECT id, volume_name, mount_path, volume_type, is_active,
                   total_space, free_space, description, priority
            FROM storage_volumes
            ORDER BY priority DESC, volume_name
            """
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.execute(query)
                for row in cursor.fetchall():
                    volume = VolumeInfo(
                        id=row[0],
                        volume_name=row[1],
                        mount_path=row[2],
                        volume_type=row[3],
                        is_active=bool(row[4]),
                        total_space=row[5] or 0,
                        free_space=row[6] or 0,
                        description=row[7] or '',
                        priority=row[8] or 0
                    )
                    self._volumes_cache[volume.volume_name] = volume
                    
        except Exception as e:
            self.logger.error(f"加载存储卷信息失败: {e}")
            
    def _load_scan_paths(self):
        """加载扫描路径信息"""
        try:
            query = """
            SELECT sp.id, sp.volume_id, sp.path_type, sp.relative_path, sp.full_path,
                   sp.is_enabled, sp.scan_recursive, sp.exclude_patterns, sp.priority,
                   sp.last_scanned, sp.file_count, sp.total_size
            FROM scan_paths sp
            JOIN storage_volumes sv ON sp.volume_id = sv.id
            WHERE sp.is_enabled = 1 AND sv.is_active = 1
            ORDER BY sp.priority DESC, sp.path_type
            """
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.execute(query)
                for row in cursor.fetchall():
                    exclude_patterns = []
                    if row[7]:  # exclude_patterns
                        try:
                            exclude_patterns = json.loads(row[7])
                        except json.JSONDecodeError:
                            pass
                    
                    last_scanned = None
                    if row[9]:  # last_scanned
                        try:
                            last_scanned = datetime.fromisoformat(row[9])
                        except ValueError:
                            pass
                    
                    scan_path = ScanPathInfo(
                        id=row[0],
                        volume_id=row[1],
                        path_type=row[2],
                        relative_path=row[3],
                        full_path=row[4],
                        is_enabled=bool(row[5]),
                        scan_recursive=bool(row[6]),
                        exclude_patterns=exclude_patterns,
                        priority=row[8] or 0,
                        last_scanned=last_scanned,
                        file_count=row[10] or 0,
                        total_size=row[11] or 0
                    )
                    
                    if scan_path.path_type not in self._scan_paths_cache:
                        self._scan_paths_cache[scan_path.path_type] = []
                    self._scan_paths_cache[scan_path.path_type].append(scan_path)
                    
        except Exception as e:
            self.logger.error(f"加载扫描路径信息失败: {e}")
    
    def get_volumes(self, active_only: bool = True) -> List[VolumeInfo]:
        """获取存储卷列表"""
        if not self._volumes_cache:
            self._load_volumes()
            
        volumes = list(self._volumes_cache.values())
        if active_only:
            volumes = [v for v in volumes if v.is_active]
            
        return sorted(volumes, key=lambda x: (-x.priority, x.volume_name))
    
    def get_volume_by_path(self, file_path: str) -> Optional[VolumeInfo]:
        """根据文件路径获取对应的存储卷"""
        if not self._volumes_cache:
            self._load_volumes()
            
        file_path = os.path.abspath(file_path)
        
        # 按优先级排序，优先匹配高优先级的卷
        volumes = sorted(self._volumes_cache.values(), 
                        key=lambda x: (-x.priority, -len(x.mount_path)))
        
        for volume in volumes:
            if volume.is_active and file_path.startswith(volume.mount_path):
                return volume
                
        return None
    
    def get_scan_paths(self, path_type: Optional[str] = None) -> List[ScanPathInfo]:
        """获取扫描路径列表"""
        if not self._scan_paths_cache:
            self._load_scan_paths()
            
        if path_type:
            return self._scan_paths_cache.get(path_type, [])
        
        # 返回所有扫描路径
        all_paths = []
        for paths in self._scan_paths_cache.values():
            all_paths.extend(paths)
            
        return sorted(all_paths, key=lambda x: (-x.priority, x.path_type))
    
    def parse_file_path(self, file_path: str) -> Dict[str, Any]:
        """解析文件路径，提取卷信息和相对路径"""
        file_path = os.path.abspath(file_path)
        
        # 获取对应的存储卷
        volume = self.get_volume_by_path(file_path)
        if not volume:
            return {
                'volume_id': None,
                'volume_name': None,
                'relative_path': file_path,
                'directory_path': os.path.dirname(file_path),
                'file_name': os.path.basename(file_path),
                'full_path': file_path
            }
        
        # 计算相对路径
        relative_path = os.path.relpath(file_path, volume.mount_path)
        directory_path = os.path.dirname(file_path)
        
        return {
            'volume_id': volume.id,
            'volume_name': volume.volume_name,
            'relative_path': relative_path,
            'directory_path': directory_path,
            'file_name': os.path.basename(file_path),
            'full_path': file_path
        }
    
    def resolve_path(self, volume_id: int, relative_path: str) -> str:
        """根据卷ID和相对路径解析完整路径"""
        if not self._volumes_cache:
            self._load_volumes()
            
        # 查找对应的卷
        volume = None
        for vol in self._volumes_cache.values():
            if vol.id == volume_id:
                volume = vol
                break
                
        if not volume:
            raise ValueError(f"未找到卷ID: {volume_id}")
            
        return os.path.join(volume.mount_path, relative_path)
    
    def validate_directory(self, directory_path: str) -> Dict[str, Any]:
        """验证目录状态"""
        result = {
            'exists': False,
            'readable': False,
            'writable': False,
            'volume_info': None,
            'space_info': None,
            'error': None
        }
        
        try:
            path = Path(directory_path)
            result['exists'] = path.exists()
            
            if result['exists']:
                result['readable'] = os.access(directory_path, os.R_OK)
                result['writable'] = os.access(directory_path, os.W_OK)
                
                # 获取卷信息
                volume = self.get_volume_by_path(directory_path)
                if volume:
                    result['volume_info'] = {
                        'volume_name': volume.volume_name,
                        'mount_path': volume.mount_path,
                        'volume_type': volume.volume_type
                    }
                
                # 获取空间信息
                try:
                    stat = shutil.disk_usage(directory_path)
                    result['space_info'] = {
                        'total': stat.total,
                        'used': stat.total - stat.free,
                        'free': stat.free,
                        'usage_percent': ((stat.total - stat.free) / stat.total) * 100
                    }
                except Exception as e:
                    self.logger.warning(f"获取磁盘空间信息失败: {e}")
                    
        except Exception as e:
            result['error'] = str(e)
            self.logger.error(f"验证目录失败 {directory_path}: {e}")
            
        return result
    
    def update_volume_space(self, volume_id: int) -> bool:
        """更新存储卷空间信息"""
        try:
            # 获取卷信息
            volume = None
            for vol in self._volumes_cache.values():
                if vol.id == volume_id:
                    volume = vol
                    break
                    
            if not volume or not os.path.exists(volume.mount_path):
                return False
                
            # 获取空间信息
            stat = shutil.disk_usage(volume.mount_path)
            
            # 更新数据库
            query = """
            UPDATE storage_volumes 
            SET total_space = ?, free_space = ?, last_checked = ?
            WHERE id = ?
            """
            
            with self.db_manager.get_connection() as conn:
                conn.execute(query, (
                    stat.total,
                    stat.free,
                    datetime.now().isoformat(),
                    volume_id
                ))
                conn.commit()
                
            # 更新缓存
            volume.total_space = stat.total
            volume.free_space = stat.free
            
            return True
            
        except Exception as e:
            self.logger.error(f"更新卷空间信息失败: {e}")
            return False
    
    def add_volume(self, volume_name: str, mount_path: str, 
                   volume_type: str = 'local', description: str = '',
                   priority: int = 0) -> Optional[int]:
        """添加新的存储卷"""
        try:
            # 验证路径
            if not os.path.exists(mount_path):
                raise ValueError(f"挂载路径不存在: {mount_path}")
                
            # 获取空间信息
            stat = shutil.disk_usage(mount_path)
            
            query = """
            INSERT INTO storage_volumes 
            (volume_name, mount_path, volume_type, description, priority,
             total_space, free_space, last_checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.execute(query, (
                    volume_name,
                    mount_path,
                    volume_type,
                    description,
                    priority,
                    stat.total,
                    stat.free,
                    datetime.now().isoformat()
                ))
                conn.commit()
                volume_id = cursor.lastrowid
                
            # 刷新缓存
            self.refresh_cache()
            
            self.logger.info(f"添加存储卷成功: {volume_name} -> {mount_path}")
            return volume_id
            
        except Exception as e:
            self.logger.error(f"添加存储卷失败: {e}")
            return None
    
    def add_scan_path(self, volume_id: int, path_type: str, relative_path: str,
                      scan_recursive: bool = True, exclude_patterns: Optional[List[str]] = None,
                      priority: int = 0) -> Optional[int]:
        """添加新的扫描路径"""
        try:
            # 构建完整路径
            full_path = self.resolve_path(volume_id, relative_path)
            
            # 验证路径
            if not os.path.exists(full_path):
                self.logger.warning(f"扫描路径不存在，将在首次扫描时创建: {full_path}")
            
            exclude_patterns_json = json.dumps(exclude_patterns or [])
            
            query = """
            INSERT INTO scan_paths 
            (volume_id, path_type, relative_path, full_path, scan_recursive,
             exclude_patterns, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.execute(query, (
                    volume_id,
                    path_type,
                    relative_path,
                    full_path,
                    scan_recursive,
                    exclude_patterns_json,
                    priority
                ))
                conn.commit()
                scan_path_id = cursor.lastrowid
                
            # 刷新缓存
            self.refresh_cache()
            
            self.logger.info(f"添加扫描路径成功: {full_path}")
            return scan_path_id
            
        except Exception as e:
            self.logger.error(f"添加扫描路径失败: {e}")
            return None
    
    def get_directory_stats(self) -> Dict[str, Any]:
        """获取目录统计信息"""
        stats = {
            'volumes': {
                'total': 0,
                'active': 0,
                'total_space': 0,
                'free_space': 0,
                'usage_percent': 0
            },
            'scan_paths': {
                'total': 0,
                'enabled': 0,
                'by_type': {}
            }
        }
        
        try:
            # 统计存储卷
            volumes = self.get_volumes(active_only=False)
            stats['volumes']['total'] = len(volumes)
            
            active_volumes = [v for v in volumes if v.is_active]
            stats['volumes']['active'] = len(active_volumes)
            
            total_space = sum(v.total_space for v in active_volumes)
            free_space = sum(v.free_space for v in active_volumes)
            
            stats['volumes']['total_space'] = total_space
            stats['volumes']['free_space'] = free_space
            
            if total_space > 0:
                stats['volumes']['usage_percent'] = ((total_space - free_space) / total_space) * 100
            
            # 统计扫描路径
            scan_paths = self.get_scan_paths()
            stats['scan_paths']['total'] = len(scan_paths)
            stats['scan_paths']['enabled'] = len([p for p in scan_paths if p.is_enabled])
            
            # 按类型统计
            for path in scan_paths:
                if path.path_type not in stats['scan_paths']['by_type']:
                    stats['scan_paths']['by_type'][path.path_type] = 0
                stats['scan_paths']['by_type'][path.path_type] += 1
                
        except Exception as e:
            self.logger.error(f"获取目录统计信息失败: {e}")
            
        return stats


# 全局实例
_directory_manager = None


def get_directory_manager() -> DirectoryManager:
    """获取目录管理器实例"""
    global _directory_manager
    if _directory_manager is None:
        _directory_manager = DirectoryManager()
    return _directory_manager


if __name__ == "__main__":
    # 测试目录管理器
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    dm = DirectoryManager()
    
    # 测试获取卷信息
    volumes = dm.get_volumes()
    print(f"发现 {len(volumes)} 个存储卷:")
    for vol in volumes:
        print(f"  {vol.volume_name}: {vol.mount_path} ({vol.volume_type})")
    
    # 测试获取扫描路径
    scan_paths = dm.get_scan_paths()
    print(f"\n发现 {len(scan_paths)} 个扫描路径:")
    for path in scan_paths:
        print(f"  {path.path_type}: {path.full_path}")
    
    # 测试路径解析
    test_path = "/volume1/video/movies/test.mkv"
    if os.path.exists("/volume1"):
        parsed = dm.parse_file_path(test_path)
        print(f"\n路径解析测试: {test_path}")
        print(f"  卷: {parsed['volume_name']}")
        print(f"  相对路径: {parsed['relative_path']}")
    
    # 获取统计信息
    stats = dm.get_directory_stats()
    print(f"\n目录统计信息:")
    print(f"  存储卷: {stats['volumes']['active']}/{stats['volumes']['total']}")
    print(f"  扫描路径: {stats['scan_paths']['enabled']}/{stats['scan_paths']['total']}")