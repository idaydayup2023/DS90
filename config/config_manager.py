#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理器
负责加载和管理系统配置
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

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