#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理器
负责加载和管理系统配置
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
import re

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置文件路径，如果不提供则使用默认路径
        """
        self.logger = logging.getLogger(__name__)
        
        # 确定配置文件路径
        if config_path:
            self.config_path = Path(config_path)
        else:
            # 默认配置文件路径
            current_dir = Path(__file__).parent
            self.config_path = current_dir / "config.yaml"
        
        # 项目根目录
        self.project_root = Path(__file__).parent.parent
        
        # 加载配置
        self.config = self._load_config()
        
        # 验证配置
        self._validate_config()
        
        # 目录管理器（延迟初始化，避免循环导入）
        self._directory_manager = None
    
    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件
        
        Returns:
            配置字典
        """
        try:
            if not self.config_path.exists():
                self.logger.error(f"配置文件不存在: {self.config_path}")
                return self._get_default_config()
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config:
                self.logger.warning("配置文件为空，使用默认配置")
                return self._get_default_config()
            
            self.logger.info(f"已加载配置文件: {self.config_path}")
            return config
            
        except yaml.YAMLError as e:
            self.logger.error(f"配置文件格式错误: {e}")
            return self._get_default_config()
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置
        
        Returns:
            默认配置字典
        """
        return {
            'database': {
                'path': 'data/media_library.db',
                'backup_dir': 'data/backups',
                'auto_backup_hours': 24
            },
            'scanner': {
                'media_directories': ['/volume1/video'],
                'video_extensions': ['.mp4', '.mkv', '.avi', '.mov'],
                'min_file_size_mb': 10,
                'max_workers': 4,
                'skip_hidden': True,
                'exclude_patterns': ['.*', 'Thumbs.db', '.DS_Store', '@eaDir']
            },
            'tmdb': {
                'api_key': '',
                'language_preference': 'zh-CN,en-US',
                'request_interval': 0.25,
                'auto_update_metadata': True,
                'batch_update_size': 50
            },
            'duplicate_detection': {
                'enabled': True,
                'name_similarity_threshold': 0.8,
                'size_difference_threshold': 0.05,
                'auto_detection_hours': 168
            },
            'logging': {
                'level': 'INFO',
                'file': 'logs/media_manager.log',
                'max_file_size_mb': 10,
                'backup_count': 5,
                'console_output': True
            }
        }
    
    def _validate_config(self):
        """验证配置的有效性"""
        try:
            # 验证数据库配置
            db_config = self.config.get('database', {})
            if not db_config.get('path'):
                self.logger.warning("数据库路径未配置，使用默认路径")
                self.config.setdefault('database', {})['path'] = 'data/media_library.db'
            
            # 验证扫描配置
            scanner_config = self.config.get('scanner', {})
            if not scanner_config.get('media_directories'):
                self.logger.warning("媒体目录未配置")
            
            # 验证TMDB配置
            tmdb_config = self.config.get('tmdb', {})
            if not tmdb_config.get('api_key'):
                self.logger.warning("TMDB API密钥未配置，元数据功能将不可用")
            
            # 创建必要的目录
            self._create_directories()
            
        except Exception as e:
            self.logger.error(f"配置验证失败: {e}")
    
    def _create_directories(self):
        """创建必要的目录"""
        try:
            # 数据目录
            data_dir = self.get_absolute_path(self.get('database.path')).parent
            data_dir.mkdir(parents=True, exist_ok=True)
            
            # 备份目录
            backup_dir = self.get_absolute_path(self.get('database.backup_dir'))
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # 日志目录
            log_file = self.get_absolute_path(self.get('logging.file'))
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
        except Exception as e:
            self.logger.error(f"创建目录失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点号分隔的嵌套键（如 'database.path'）
            default: 默认值
            
        Returns:
            配置值
        """
        try:
            keys = key.split('.')
            value = self.config
            
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    return default
            
            return value
            
        except Exception:
            return default
    
    def set(self, key: str, value: Any):
        """
        设置配置值
        
        Args:
            key: 配置键
            value: 配置值
        """
        try:
            keys = key.split('.')
            config = self.config
            
            # 导航到目标位置
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]
            
            # 设置值
            config[keys[-1]] = value
            
        except Exception as e:
            self.logger.error(f"设置配置失败 {key}: {e}")
    
    def get_absolute_path(self, path: str) -> Path:
        """
        获取绝对路径
        
        Args:
            path: 相对或绝对路径
            
        Returns:
            绝对路径
        """
        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        else:
            return self.project_root / path_obj
    
    def get_database_path(self) -> str:
        """获取数据库文件的绝对路径"""
        return str(self.get_absolute_path(self.get('database.path')))
    
    def get_media_directories(self) -> List[str]:
        """获取媒体目录列表"""
        return self.get('scanner.media_directories', [])
    
    def get_video_extensions(self) -> List[str]:
        """获取支持的视频文件扩展名"""
        return self.get('scanner.video_extensions', ['.mp4', '.mkv', '.avi'])
    
    def get_tmdb_api_key(self) -> str:
        """获取TMDB API密钥"""
        return self.get('tmdb.api_key', '')
    
    def get_log_config(self) -> Dict[str, Any]:
        """获取日志配置"""
        log_config = self.get('logging', {})
        
        # 转换文件路径为绝对路径
        if 'file' in log_config:
            log_config['file'] = str(self.get_absolute_path(log_config['file']))
        
        return log_config
    
    def save_config(self, config_path: Optional[str] = None):
        """
        保存配置到文件
        
        Args:
            config_path: 配置文件路径，如果不提供则使用当前路径
        """
        try:
            save_path = Path(config_path) if config_path else self.config_path
            
            with open(save_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, 
                         allow_unicode=True, indent=2)
            
            self.logger.info(f"配置已保存到: {save_path}")
            
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
    
    def reload_config(self):
        """重新加载配置文件"""
        self.config = self._load_config()
        self._validate_config()
        self.logger.info("配置已重新加载")
    
    def get_scanner_config(self) -> Dict[str, Any]:
        """获取扫描器配置"""
        return {
            'media_directories': self.get_media_directories(),
            'video_extensions': self.get_video_extensions(),
            'min_file_size_mb': self.get('scanner.min_file_size_mb', 10),
            'max_workers': self.get('scanner.max_workers', 4),
            'skip_hidden': self.get('scanner.skip_hidden', True),
            'exclude_patterns': self.get('scanner.exclude_patterns', [])
        }
    
    def get_tmdb_config(self) -> Dict[str, Any]:
        """获取TMDB配置"""
        return {
            'api_key': self.get_tmdb_api_key(),
            'language_preference': self.get('tmdb.language_preference', 'zh-CN,en-US'),
            'request_interval': self.get('tmdb.request_interval', 0.25),
            'auto_update_metadata': self.get('tmdb.auto_update_metadata', True),
            'batch_update_size': self.get('tmdb.batch_update_size', 50)
        }
    
    def get_duplicate_detection_config(self) -> Dict[str, Any]:
        """获取重复检测配置"""
        return {
            'enabled': self.get('duplicate_detection.enabled', True),
            'name_similarity_threshold': self.get('duplicate_detection.name_similarity_threshold', 0.8),
            'size_difference_threshold': self.get('duplicate_detection.size_difference_threshold', 0.05),
            'auto_detection_hours': self.get('duplicate_detection.auto_detection_hours', 168)
        }
    
    def is_tmdb_configured(self) -> bool:
        """检查TMDB是否已配置"""
        return bool(self.get_tmdb_api_key())
    
    def is_duplicate_detection_enabled(self) -> bool:
        """检查重复检测是否启用"""
        return self.get('duplicate_detection.enabled', True)
    
    def _get_directory_manager(self):
        """获取目录管理器实例（延迟加载）"""
        if self._directory_manager is None:
            try:
                from ..utils.directory_manager import get_directory_manager
                self._directory_manager = get_directory_manager()
            except ImportError as e:
                self.logger.warning(f"无法导入目录管理器: {e}")
                self._directory_manager = None
        return self._directory_manager
    
    def get_all_scan_paths(self) -> List[Dict[str, Any]]:
        """获取所有扫描路径（包括数据库中的多卷路径）"""
        paths = []
        
        # 获取传统配置中的媒体目录
        traditional_dirs = self.get_media_directories()
        for directory in traditional_dirs:
            paths.append({
                'path': directory,
                'type': 'traditional',
                'source': 'config',
                'enabled': True,
                'recursive': True
            })
        
        # 获取数据库中的扫描路径
        dm = self._get_directory_manager()
        if dm:
            try:
                scan_paths = dm.get_scan_paths()
                for scan_path in scan_paths:
                    paths.append({
                        'path': scan_path.full_path,
                        'type': scan_path.path_type,
                        'source': 'database',
                        'enabled': scan_path.is_enabled,
                        'recursive': scan_path.scan_recursive,
                        'volume_id': scan_path.volume_id,
                        'relative_path': scan_path.relative_path,
                        'exclude_patterns': scan_path.exclude_patterns,
                        'priority': scan_path.priority
                    })
            except Exception as e:
                self.logger.warning(f"获取数据库扫描路径失败: {e}")
        
        return paths
    
    def get_active_scan_paths(self, path_type: Optional[str] = None) -> List[str]:
        """获取活跃的扫描路径列表"""
        all_paths = self.get_all_scan_paths()
        
        # 过滤启用的路径
        active_paths = [p for p in all_paths if p.get('enabled', True)]
        
        # 按类型过滤
        if path_type:
            active_paths = [p for p in active_paths if p.get('type') == path_type]
        
        # 按优先级排序
        active_paths.sort(key=lambda x: x.get('priority', 0), reverse=True)
        
        return [p['path'] for p in active_paths]
    
    def validate_scan_paths(self) -> Dict[str, Any]:
        """验证所有扫描路径的状态"""
        result = {
            'valid_paths': [],
            'invalid_paths': [],
            'warnings': [],
            'total_paths': 0
        }
        
        dm = self._get_directory_manager()
        all_paths = self.get_all_scan_paths()
        result['total_paths'] = len(all_paths)
        
        for path_info in all_paths:
            path = path_info['path']
            
            if dm:
                # 使用目录管理器验证
                validation = dm.validate_directory(path)
                if validation['exists'] and validation['readable']:
                    result['valid_paths'].append({
                        'path': path,
                        'type': path_info.get('type', 'unknown'),
                        'source': path_info.get('source', 'unknown'),
                        'volume_info': validation.get('volume_info'),
                        'space_info': validation.get('space_info')
                    })
                else:
                    result['invalid_paths'].append({
                        'path': path,
                        'type': path_info.get('type', 'unknown'),
                        'source': path_info.get('source', 'unknown'),
                        'error': validation.get('error', '路径不存在或不可读')
                    })
                    
                # 检查写权限警告
                if validation['exists'] and validation['readable'] and not validation['writable']:
                    result['warnings'].append(f"路径只读: {path}")
            else:
                # 简单验证
                if os.path.exists(path) and os.access(path, os.R_OK):
                    result['valid_paths'].append({
                        'path': path,
                        'type': path_info.get('type', 'unknown'),
                        'source': path_info.get('source', 'unknown')
                    })
                else:
                    result['invalid_paths'].append({
                        'path': path,
                        'type': path_info.get('type', 'unknown'),
                        'source': path_info.get('source', 'unknown'),
                        'error': '路径不存在或不可读'
                    })
        
        return result
    
    def add_scan_path_to_database(self, volume_name: str, path_type: str, 
                                  relative_path: str, **kwargs) -> bool:
        """向数据库添加新的扫描路径"""
        dm = self._get_directory_manager()
        if not dm:
            self.logger.error("目录管理器不可用")
            return False
        
        try:
            # 查找卷ID
            volumes = dm.get_volumes()
            volume_id = None
            for volume in volumes:
                if volume.volume_name == volume_name:
                    volume_id = volume.id
                    break
            
            if volume_id is None:
                self.logger.error(f"未找到存储卷: {volume_name}")
                return False
            
            # 添加扫描路径
            scan_path_id = dm.add_scan_path(
                volume_id=volume_id,
                path_type=path_type,
                relative_path=relative_path,
                scan_recursive=kwargs.get('scan_recursive', True),
                exclude_patterns=kwargs.get('exclude_patterns', []),
                priority=kwargs.get('priority', 0)
            )
            
            if scan_path_id:
                self.logger.info(f"成功添加扫描路径: {volume_name}/{relative_path}")
                return True
            else:
                self.logger.error("添加扫描路径失败")
                return False
                
        except Exception as e:
            self.logger.error(f"添加扫描路径失败: {e}")
            return False
    
    def get_volume_statistics(self) -> Dict[str, Any]:
        """获取存储卷统计信息"""
        dm = self._get_directory_manager()
        if not dm:
            return {'error': '目录管理器不可用'}
        
        try:
            return dm.get_directory_stats()
        except Exception as e:
            self.logger.error(f"获取卷统计信息失败: {e}")
            return {'error': str(e)}
    
    def normalize_path(self, path: str) -> str:
        """标准化路径格式"""
        # 转换为绝对路径
        path = os.path.abspath(path)
        
        # 标准化路径分隔符
        path = path.replace('\\', '/')
        
        # 移除末尾的斜杠（除非是根目录）
        if len(path) > 1 and path.endswith('/'):
            path = path.rstrip('/')
        
        return path
    
    def is_path_excluded(self, file_path: str, exclude_patterns: Optional[List[str]] = None) -> bool:
        """检查路径是否被排除模式匹配"""
        if not exclude_patterns:
            exclude_patterns = self.get('scanner.exclude_patterns', [])
        
        if not exclude_patterns:  # 确保不为空
            return False
            
        file_name = os.path.basename(file_path)
        
        for pattern in exclude_patterns:
            try:
                # 支持通配符和正则表达式
                if '*' in pattern or '?' in pattern:
                    # 通配符模式
                    import fnmatch
                    if fnmatch.fnmatch(file_name, pattern) or fnmatch.fnmatch(file_path, pattern):
                        return True
                else:
                    # 精确匹配或正则表达式
                    if pattern == file_name or pattern in file_path:
                        return True
                    
                    # 尝试正则表达式匹配
                    if re.search(pattern, file_path):
                        return True
                        
            except re.error:
                # 正则表达式错误，使用字符串匹配
                if pattern in file_path:
                    return True
        
        return False


# 全局配置管理器实例
_config_manager = None

def get_config_manager(config_path: Optional[str] = None) -> ConfigManager:
    """
    获取配置管理器实例（单例模式）
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置管理器实例
    """
    global _config_manager
    
    if _config_manager is None:
        _config_manager = ConfigManager(config_path)
    
    return _config_manager


if __name__ == "__main__":
    # 测试配置管理器
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    config = get_config_manager()
    
    print(f"数据库路径: {config.get_database_path()}")
    print(f"媒体目录: {config.get_media_directories()}")
    print(f"TMDB已配置: {config.is_tmdb_configured()}")
    print(f"重复检测启用: {config.is_duplicate_detection_enabled()}")
    
    # 测试配置获取
    print(f"日志级别: {config.get('logging.level')}")
    print(f"扫描线程数: {config.get('scanner.max_workers')}")
    
    # 测试配置设置
    config.set('test.value', 'hello')
    print(f"测试值: {config.get('test.value')}")