#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体库管理系统主程序
Media Library Management System Main Entry Point
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from config import get_config_manager
from database.db_manager import get_db_manager
from scanner.file_scanner import MediaFileScanner
from api.tmdb_client import TMDBClient
from utils.duplicate_detector import DuplicateDetector

def setup_logging(config_manager):
    """设置日志配置"""
    log_config = config_manager.get_log_config()
    
    # 创建日志目录
    log_file = Path(log_config.get('file', 'logs/media_manager.log'))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 配置日志格式
    log_format = log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    log_level = getattr(logging, log_config.get('level', 'INFO').upper())
    
    # 配置根日志记录器
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout) if log_config.get('console_output', True) else logging.NullHandler()
        ]
    )
    
    # 设置第三方库的日志级别
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

def init_database(config_manager):
    """初始化数据库"""
    logger = logging.getLogger(__name__)
    
    try:
        db_manager = get_db_manager(config_manager.get_database_path())
        
        if db_manager.initialize_database():
            logger.info("数据库初始化成功")
            
            # 设置默认配置
            default_settings = {
                'video_extensions': ','.join(config_manager.get_video_extensions()),
                'min_file_size_mb': str(config_manager.get('scanner.min_file_size_mb', 10)),
                'tmdb_api_key': config_manager.get_tmdb_api_key(),
                'language_preference': config_manager.get('tmdb.language_preference', 'zh-CN,en-US'),
                'duplicate_detection_enabled': str(config_manager.is_duplicate_detection_enabled()),
                'last_scan_time': '',
                'last_duplicate_check': ''
            }
            
            for key, value in default_settings.items():
                if not db_manager.get_setting(key):
                    db_manager.set_setting(key, value, f"默认{key}配置")
            
            return True
        else:
            logger.error("数据库初始化失败")
            return False
            
    except Exception as e:
        logger.error(f"数据库初始化异常: {e}")
        return False

def scan_media_files(directories: Optional[list] = None):
    """扫描媒体文件"""
    logger = logging.getLogger(__name__)
    config_manager = get_config_manager()
    
    try:
        # 获取扫描目录
        if not directories:
            directories = config_manager.get_media_directories()
        
        if not directories:
            logger.error("未配置媒体目录")
            return False
        
        # 验证目录存在
        valid_directories = []
        for directory in directories:
            if os.path.exists(directory):
                valid_directories.append(directory)
                logger.info(f"将扫描目录: {directory}")
            else:
                logger.warning(f"目录不存在，跳过: {directory}")
        
        if not valid_directories:
            logger.error("没有有效的媒体目录")
            return False
        
        # 创建扫描器
        scanner = MediaFileScanner()
        
        # 执行扫描
        logger.info("开始媒体文件扫描...")
        
        # 扫描所有目录并合并结果
        total_results = {
            'new_files': 0,
            'updated_files': 0,
            'skipped_files': 0,
            'error_files': 0,
            'total_time': 0
        }
        
        for directory in valid_directories:
            results = scanner.scan_directory(directory)
            for key in total_results:
                total_results[key] += results.get(key, 0)
        
        results = total_results
        
        # 输出结果
        logger.info(f"扫描完成:")
        logger.info(f"  - 新增文件: {results.get('new_files', 0)}")
        logger.info(f"  - 更新文件: {results.get('updated_files', 0)}")
        logger.info(f"  - 跳过文件: {results.get('skipped_files', 0)}")
        logger.info(f"  - 错误文件: {results.get('error_files', 0)}")
        logger.info(f"  - 总耗时: {results.get('total_time', 0):.2f}秒")
        
        return True
        
    except Exception as e:
        logger.error(f"媒体文件扫描失败: {e}")
        return False

def update_metadata(limit: int = 50):
    """更新元数据"""
    logger = logging.getLogger(__name__)
    config_manager = get_config_manager()
    
    try:
        if not config_manager.is_tmdb_configured():
            logger.error("TMDB API未配置，无法更新元数据")
            return False
        
        # 创建TMDB客户端
        tmdb_client = TMDBClient()
        
        # 批量更新元数据
        logger.info(f"开始更新元数据（限制{limit}条）...")
        stats = tmdb_client.batch_update_metadata(limit)
        
        # 输出结果
        logger.info(f"元数据更新完成:")
        logger.info(f"  - 更新成功: {stats.get('updated', 0)}")
        logger.info(f"  - 更新失败: {stats.get('failed', 0)}")
        logger.info(f"  - 跳过项目: {stats.get('skipped', 0)}")
        
        return True
        
    except Exception as e:
        logger.error(f"元数据更新失败: {e}")
        return False

def detect_duplicates():
    """检测重复文件"""
    logger = logging.getLogger(__name__)
    config_manager = get_config_manager()
    
    try:
        if not config_manager.is_duplicate_detection_enabled():
            logger.warning("重复检测功能已禁用")
            return False
        
        # 创建重复检测器
        detector = DuplicateDetector()
        
        # 运行检测
        logger.info("开始重复文件检测...")
        results = detector.run_full_detection()
        
        # 输出结果
        logger.info(f"重复检测完成:")
        logger.info(f"  - 哈希重复组: {results.get('hash_groups', 0)}")
        logger.info(f"  - 相似重复组: {results.get('similarity_groups', 0)}")
        logger.info(f"  - 保存组数: {results.get('total_saved', 0)}")
        
        # 空间分析
        analysis = results.get('analysis', {})
        if analysis:
            total_size = analysis.get('total_duplicate_size', 0) / (1024 * 1024 * 1024)
            potential_savings = analysis.get('potential_savings', 0) / (1024 * 1024 * 1024)
            logger.info(f"  - 重复文件总大小: {total_size:.2f}GB")
            logger.info(f"  - 可节省空间: {potential_savings:.2f}GB")
        
        return True
        
    except Exception as e:
        logger.error(f"重复检测失败: {e}")
        return False

def show_statistics():
    """显示统计信息"""
    logger = logging.getLogger(__name__)
    
    try:
        db_manager = get_db_manager()
        stats = db_manager.get_database_stats()
        
        print("\n=== 媒体库统计信息 ===")
        print(f"电影数量: {stats.get('movies', 0)}")
        print(f"电视剧数量: {stats.get('tv_shows', 0)}")
        print(f"总文件数: {stats.get('total_files', 0)}")
        print(f"总文件大小: {stats.get('total_size', 0) / (1024**3):.2f} GB")
        print(f"重复文件组: {stats.get('duplicate_groups', 0)}")
        
        # 最近扫描信息
        last_scan = db_manager.get_setting('last_scan_time')
        if last_scan:
            print(f"最后扫描时间: {last_scan}")
        
        return True
        
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        return False

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="媒体库管理系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s init                    # 初始化数据库
  %(prog)s scan                    # 扫描媒体文件
  %(prog)s scan -d /path/to/movies # 扫描指定目录
  %(prog)s metadata                # 更新元数据
  %(prog)s duplicates              # 检测重复文件
  %(prog)s stats                   # 显示统计信息
  %(prog)s full                    # 执行完整流程
        """
    )
    
    parser.add_argument(
        'command',
        choices=['init', 'scan', 'metadata', 'duplicates', 'stats', 'full'],
        help='要执行的命令'
    )
    
    parser.add_argument(
        '-c', '--config',
        help='配置文件路径'
    )
    
    parser.add_argument(
        '-d', '--directories',
        nargs='+',
        help='要扫描的目录列表'
    )
    
    parser.add_argument(
        '-l', '--limit',
        type=int,
        default=50,
        help='元数据更新限制数量'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='详细输出'
    )
    
    args = parser.parse_args()
    
    try:
        # 初始化配置管理器
        config_manager = get_config_manager(args.config)
        
        # 设置日志
        if args.verbose:
            config_manager.set('logging.level', 'DEBUG')
        setup_logging(config_manager)
        
        logger = logging.getLogger(__name__)
        logger.info(f"媒体库管理系统启动，执行命令: {args.command}")
        
        # 执行命令
        success = True
        
        if args.command == 'init':
            success = init_database(config_manager)
            
        elif args.command == 'scan':
            success = scan_media_files(args.directories)
            
        elif args.command == 'metadata':
            success = update_metadata(args.limit)
            
        elif args.command == 'duplicates':
            success = detect_duplicates()
            
        elif args.command == 'stats':
            success = show_statistics()
            
        elif args.command == 'full':
            # 执行完整流程
            logger.info("执行完整流程...")
            
            # 1. 初始化数据库
            if not init_database(config_manager):
                success = False
            
            # 2. 扫描媒体文件
            elif not scan_media_files(args.directories):
                success = False
            
            # 3. 更新元数据
            elif config_manager.is_tmdb_configured():
                if not update_metadata(args.limit):
                    logger.warning("元数据更新失败，但继续执行")
            
            # 4. 检测重复文件
            if success and config_manager.is_duplicate_detection_enabled():
                if not detect_duplicates():
                    logger.warning("重复检测失败，但继续执行")
            
            # 5. 显示统计信息
            if success:
                show_statistics()
        
        # 退出
        if success:
            logger.info("命令执行成功")
            sys.exit(0)
        else:
            logger.error("命令执行失败")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n用户中断操作")
        sys.exit(1)
    except Exception as e:
        print(f"程序异常: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()