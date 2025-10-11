#!/usr/bin/env python3
"""
多卷多目录管理功能使用示例

这个示例展示了如何使用新的多卷多目录管理功能来：
1. 管理多个存储卷
2. 配置扫描路径
3. 执行多卷并发扫描
4. 获取存储统计信息
"""

import os
import sys
import logging
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from media_manager.config.config_manager import get_config_manager
from media_manager.utils.directory_manager import get_directory_manager
from media_manager.scanner.file_scanner import MediaFileScanner

def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def demonstrate_volume_management():
    """演示存储卷管理"""
    print("\n=== 存储卷管理演示 ===")
    
    # 获取目录管理器
    dir_manager = get_directory_manager()
    
    # 获取所有存储卷
    volumes = dir_manager.get_volumes(active_only=False)
    print(f"当前配置的存储卷数量: {len(volumes)}")
    
    for volume in volumes:
        print(f"  - 卷ID: {volume.id}")
        print(f"    名称: {volume.volume_name}")
        print(f"    挂载点: {volume.mount_path}")
        print(f"    状态: {'活跃' if volume.is_active else '非活跃'}")
        print(f"    总空间: {volume.total_space if volume.total_space else 'N/A'}")
        print(f"    可用空间: {volume.free_space if volume.free_space else 'N/A'}")
        print()

def demonstrate_scan_path_management():
    """演示扫描路径管理"""
    print("\n=== 扫描路径管理演示 ===")
    
    # 获取配置管理器
    config_manager = get_config_manager()
    
    # 获取所有扫描路径
    scan_paths = config_manager.get_all_scan_paths()
    print(f"当前配置的扫描路径数量: {len(scan_paths)}")
    
    # 按类型分组显示
    path_types = {}
    for path in scan_paths:
        path_type = path.get('type', 'unknown')
        if path_type not in path_types:
            path_types[path_type] = []
        path_types[path_type].append(path)
    
    for path_type, paths in path_types.items():
        print(f"\n{path_type.upper()} 路径:")
        for path in paths:
            print(f"  - {path['path']}")
            print(f"    卷ID: {path.get('volume_id', 'N/A')}")
            print(f"    状态: {'活跃' if path.get('enabled', True) else '非活跃'}")
            if path.get('exclude_patterns'):
                print(f"    排除模式: {path['exclude_patterns']}")

def demonstrate_path_validation():
    """演示路径验证"""
    print("\n=== 路径验证演示 ===")
    
    config_manager = get_config_manager()
    
    # 验证所有扫描路径
    validation_results = config_manager.validate_scan_paths()
    
    print("路径验证结果:")
    print(f"总路径数: {validation_results['total_paths']}")
    
    # 显示有效路径
    print(f"\n有效路径 ({len(validation_results['valid_paths'])}):")
    for result in validation_results['valid_paths']:
        print(f"  ✓ {result['path']}")
        print(f"    类型: {result['type']}")
        print(f"    来源: {result['source']}")
        if result.get('volume_info'):
            print(f"    卷: {result['volume_info']['volume_name']}")
    
    # 显示无效路径
    if validation_results['invalid_paths']:
        print(f"\n无效路径 ({len(validation_results['invalid_paths'])}):")
        for result in validation_results['invalid_paths']:
            print(f"  ✗ {result['path']}")
            print(f"    错误: {result.get('error', '未知错误')}")
    
    # 显示警告
    if validation_results['warnings']:
        print(f"\n警告 ({len(validation_results['warnings'])}):")
        for warning in validation_results['warnings']:
            print(f"  ⚠ {warning}")

def demonstrate_multi_volume_scanning():
    """演示多卷并发扫描"""
    print("\n=== 多卷并发扫描演示 ===")
    
    # 创建文件扫描器
    scanner = MediaFileScanner(max_workers=2)
    
    print("开始多卷扫描...")
    print("注意: 这是一个演示，实际扫描需要存在的媒体文件")
    
    # 扫描所有卷的电影路径
    try:
        results = scanner.scan_all_volumes(path_type='movies', max_volume_workers=2)
        
        print(f"扫描完成!")
        print(f"总卷数: {results.get('total_volumes', 0)}")
        print(f"总路径数: {results.get('total_paths', 0)}")
        print(f"扫描文件数: {results.get('files_scanned', 0)}")
        print(f"新增文件: {results.get('files_added', 0)}")
        print(f"更新文件: {results.get('files_updated', 0)}")
        print(f"跳过文件: {results.get('files_skipped', 0)}")
        print(f"错误数: {results.get('errors', 0)}")
        print(f"扫描耗时: {results.get('scan_time', 0):.2f} 秒")
        
        # 显示各卷统计
        volume_results = results.get('volume_results', [])
        for volume_result in volume_results:
            volume_info = volume_result.get('volume_info', 'Unknown')
            print(f"\n卷 {volume_info} 统计:")
            print(f"  文件数: {volume_result.get('files_scanned', 0)}")
            print(f"  新增: {volume_result.get('files_added', 0)}")
            print(f"  更新: {volume_result.get('files_updated', 0)}")
            print(f"  耗时: {volume_result.get('scan_time', 0):.2f} 秒")
            
    except Exception as e:
        print(f"扫描过程中出现错误: {e}")

def demonstrate_storage_statistics():
    """演示存储统计信息"""
    print("\n=== 存储统计信息演示 ===")
    
    config_manager = get_config_manager()
    
    try:
        # 获取存储卷统计信息
        stats = config_manager.get_volume_statistics()
        
        if 'error' in stats:
            print(f"获取统计信息失败: {stats['error']}")
            return
        
        print("存储卷统计信息:")
        
        # 显示卷统计
        volume_stats = stats.get('volumes', {})
        print(f"存储卷总数: {volume_stats.get('total', 0)}")
        print(f"活跃卷数: {volume_stats.get('active', 0)}")
        print(f"总空间: {volume_stats.get('total_space', 0):,} 字节")
        print(f"可用空间: {volume_stats.get('free_space', 0):,} 字节")
        print(f"使用率: {volume_stats.get('usage_percent', 0):.1f}%")
        
        # 显示扫描路径统计
        scan_path_stats = stats.get('scan_paths', {})
        print(f"\n扫描路径统计:")
        print(f"总路径数: {scan_path_stats.get('total', 0)}")
        print(f"启用路径数: {scan_path_stats.get('enabled', 0)}")
        
        # 按类型显示路径统计
        by_type = scan_path_stats.get('by_type', {})
        if by_type:
            print("按类型分布:")
            for path_type, count in by_type.items():
                print(f"  {path_type}: {count}")
            
    except Exception as e:
        print(f"获取统计信息时出现错误: {e}")

def main():
    """主函数"""
    setup_logging()
    
    print("多卷多目录管理功能演示")
    print("=" * 50)
    
    try:
        # 演示各项功能
        demonstrate_volume_management()
        demonstrate_scan_path_management()
        demonstrate_path_validation()
        demonstrate_storage_statistics()
        
        # 注意: 多卷扫描演示需要实际的媒体文件，在演示环境中可能会失败
        print("\n注意: 多卷扫描演示需要实际的媒体文件和配置的存储卷")
        user_input = input("是否要运行多卷扫描演示? (y/N): ").strip().lower()
        if user_input == 'y':
            demonstrate_multi_volume_scanning()
        
    except Exception as e:
        print(f"演示过程中出现错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()