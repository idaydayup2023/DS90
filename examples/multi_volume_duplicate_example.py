#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多卷重复文件管理示例
演示如何使用增强的重复文件检测器进行多卷重复文件管理
"""

import os
import sys
import json
from datetime import datetime
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from media_manager.utils.duplicate_detector import DuplicateDetector
from media_manager.utils.directory_manager import get_directory_manager
from media_manager.database.db_manager import get_db_manager


def format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes == 0:
        return "0B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size_float = float(size_bytes)
    while size_float >= 1024 and i < len(size_names) - 1:
        size_float /= 1024.0
        i += 1
    
    return f"{size_float:.1f}{size_names[i]}"


def print_separator(title: str = ""):
    """打印分隔线"""
    print("\n" + "=" * 80)
    if title:
        print(f" {title} ".center(80, "="))
        print("=" * 80)


def demonstrate_multi_volume_duplicate_detection():
    """演示多卷重复文件检测"""
    print_separator("多卷重复文件检测演示")
    
    # 初始化组件
    detector = DuplicateDetector()
    directory_manager = get_directory_manager()
    
    print("1. 获取所有存储卷信息")
    volumes = directory_manager.get_volumes()
    
    if not volumes:
        print("   ❌ 未找到任何存储卷，请先配置存储卷")
        return
    
    print(f"   ✅ 找到 {len(volumes)} 个存储卷:")
    for volume in volumes:
        print(f"      - {volume.volume_name}: {volume.mount_path} ({format_size(volume.total_space)})")
    
    print("\n2. 检测所有卷的重复文件")
    duplicate_groups = detector.detect_duplicates_by_hash()
    
    if not duplicate_groups:
        print("   ✅ 未发现重复文件")
        return
    
    print(f"   🔍 发现 {len(duplicate_groups)} 个重复文件组")
    
    # 显示前5个最大的重复文件组
    print("\n3. 最大的重复文件组:")
    sorted_groups = sorted(duplicate_groups, key=lambda g: g.total_size, reverse=True)
    
    for i, group in enumerate(sorted_groups[:5], 1):
        print(f"\n   组 {i}: {group.group_id}")
        print(f"      文件数量: {group.file_count}")
        print(f"      总大小: {format_size(group.total_size)}")
        
        # 显示文件分布
        volume_distribution = {}
        for file_info in group.files:
            try:
                path_info = directory_manager.parse_file_path(file_info['file_path'])
                volume_name = path_info.get('volume_name', 'unknown')
                if volume_name not in volume_distribution:
                    volume_distribution[volume_name] = []
                volume_distribution[volume_name].append(file_info['file_name'])
            except Exception:
                if 'unknown' not in volume_distribution:
                    volume_distribution['unknown'] = []
                volume_distribution['unknown'].append(file_info.get('file_name', 'unknown'))
        
        print(f"      卷分布:")
        for volume_name, files in volume_distribution.items():
            print(f"        {volume_name}: {len(files)} 个文件")


def demonstrate_cross_volume_analysis():
    """演示跨卷重复文件分析"""
    print_separator("跨卷重复文件分析")
    
    detector = DuplicateDetector()
    
    print("1. 分析跨卷重复文件")
    cross_volume_analysis = detector.analyze_cross_volume_duplicates()
    
    summary = cross_volume_analysis['summary']
    print(f"   📊 跨卷重复文件统计:")
    print(f"      重复组数量: {summary['total_groups']}")
    print(f"      总大小: {format_size(summary['total_size'])}")
    print(f"      可节省空间: {format_size(summary['potential_savings'])}")
    print(f"      节省比例: {summary['savings_percentage']:.1f}%")
    
    if cross_volume_analysis['cross_volume_groups']:
        print("\n2. 跨卷重复文件组详情:")
        
        for i, group in enumerate(cross_volume_analysis['cross_volume_groups'][:3], 1):
            print(f"\n   组 {i}: {group['group_id']}")
            print(f"      文件数量: {group['file_count']}")
            print(f"      总大小: {format_size(group['total_size'])}")
            print(f"      可节省: {format_size(group['potential_savings'])}")
            
            # 显示卷分布
            volume_counts = group['volume_distribution']['counts']
            volume_sizes = group['volume_distribution']['sizes']
            
            print(f"      卷分布:")
            for volume, count in volume_counts.items():
                size = volume_sizes.get(volume, 0)
                print(f"        {volume}: {count} 个文件, {format_size(size)}")
            
            # 显示建议
            print(f"      建议:")
            for rec in group['recommendations']:
                action_icon = "🗑️" if rec['action'] == 'delete' else "✅"
                print(f"        {action_icon} {rec['volume']}: {rec['action']} - {rec['reason']}")
                if rec['space_savings'] > 0:
                    print(f"           可节省: {format_size(rec['space_savings'])}")


def demonstrate_volume_specific_analysis():
    """演示特定卷的重复文件分析"""
    print_separator("特定卷重复文件分析")
    
    detector = DuplicateDetector()
    directory_manager = get_directory_manager()
    
    # 获取第一个卷进行演示
    volumes = directory_manager.get_volumes()
    if not volumes:
        print("   ❌ 未找到任何存储卷")
        return
    
    volume = volumes[0]
    print(f"1. 分析卷 '{volume.volume_name}' 的重复文件")
    
    # 检测特定卷的重复文件
    volume_duplicates = detector.detect_duplicates_by_hash(volume_ids=[volume.id])
    
    print(f"   🔍 在卷 '{volume.volume_name}' 中发现 {len(volume_duplicates)} 个重复文件组")
    
    # 获取卷摘要
    volume_summary = detector.get_volume_duplicate_summary(volume.id)
    
    print(f"\n2. 卷 '{volume.volume_name}' 重复文件摘要:")
    print(f"      总重复组: {volume_summary['total_groups']}")
    print(f"      本地重复组: {volume_summary['local_groups']}")
    print(f"      跨卷重复组: {volume_summary['cross_volume_groups']}")
    print(f"      总大小: {format_size(volume_summary['total_size'])}")
    print(f"      可节省空间: {format_size(volume_summary['potential_savings'])}")
    print(f"      节省比例: {volume_summary['savings_percentage']:.1f}%")


def demonstrate_space_analysis():
    """演示存储空间分析"""
    print_separator("存储空间分析")
    
    detector = DuplicateDetector()
    
    print("1. 全局重复文件空间分析")
    space_analysis = detector.analyze_duplicate_space()
    
    print(f"   📊 全局统计:")
    print(f"      重复组数量: {space_analysis.get('total_groups', 0)}")
    print(f"      重复文件数量: {space_analysis.get('total_duplicate_files', 0)}")
    print(f"      重复文件总大小: {format_size(space_analysis.get('total_duplicate_size', 0))}")
    print(f"      可节省空间: {format_size(space_analysis.get('potential_savings', 0))}")
    total_size = space_analysis.get('total_duplicate_size', 0)
    potential_savings = space_analysis.get('potential_savings', 0)
    savings_percentage = (potential_savings / total_size * 100) if total_size > 0 else 0.0
    print(f"      节省比例: {savings_percentage:.1f}%")
    print(f"      跨卷重复组: {space_analysis.get('cross_volume_groups', 0)}")
    
    # 显示卷分布
    if space_analysis['volume_distribution']:
        print(f"\n2. 卷分布统计:")
        for volume, stats in space_analysis['volume_distribution'].items():
            print(f"      {volume}:")
            print(f"        文件数量: {stats['count']}")
            print(f"        总大小: {format_size(stats['size'])}")


def demonstrate_duplicate_management_workflow():
    """演示完整的重复文件管理工作流"""
    print_separator("完整重复文件管理工作流")
    
    detector = DuplicateDetector()
    
    print("1. 运行完整重复检测")
    results = detector.run_full_detection()
    
    print(f"   ✅ 检测完成:")
    print(f"      哈希重复组: {results.get('hash_groups', 0)}")
    print(f"      相似重复组: {results.get('similarity_groups', 0)}")
    print(f"      总保存组数: {results.get('total_saved', 0)}")
    
    print("\n2. 空间分析")
    analysis = results.get('analysis', {})
    if analysis:
        total_size = analysis.get('total_duplicate_size', 0)
        potential_savings = analysis.get('potential_savings', 0)
        print(f"   📊 重复文件分析:")
        print(f"      重复文件总大小: {format_size(total_size)}")
        print(f"      可节省空间: {format_size(potential_savings)}")
        savings_percentage = (potential_savings / total_size * 100) if total_size > 0 else 0.0
        print(f"      节省比例: {savings_percentage:.1f}%")
        
        print("\n3. 获取已保存的重复文件组")
        saved_groups = detector.get_duplicate_groups(limit=5)
        
        print(f"   📋 数据库中的重复文件组 (前5个):")
        for group in saved_groups:
            print(f"      组 {group['group_id']}:")
            print(f"        文件数量: {group['file_count']}")
            print(f"        总大小: {format_size(group['total_size'])}")
            print(f"        检测类型: {group['detection_type']}")
            print(f"        跨卷: {'是' if group['cross_volume'] else '否'}")
    else:
        print("   ℹ️ 未发现重复文件")


def main():
    """主函数"""
    print("🎬 多卷重复文件管理系统演示")
    print("=" * 80)
    
    try:
        # 检查数据库连接
        db = get_db_manager()
        if not db:
            print("❌ 无法连接到数据库")
            return
        
        print("✅ 数据库连接成功")
        
        # 运行各种演示
        demonstrate_multi_volume_duplicate_detection()
        demonstrate_cross_volume_analysis()
        demonstrate_volume_specific_analysis()
        demonstrate_space_analysis()
        demonstrate_duplicate_management_workflow()
        
        print_separator("演示完成")
        print("🎉 多卷重复文件管理系统演示完成!")
        print("\n💡 提示:")
        print("   - 使用 detect_duplicates_by_hash() 进行基于哈希的重复检测")
        print("   - 使用 analyze_cross_volume_duplicates() 分析跨卷重复文件")
        print("   - 使用 get_volume_duplicate_summary() 获取特定卷的摘要")
        print("   - 使用 analyze_duplicate_space() 进行空间分析")
        print("   - 使用 run_full_detection() 运行完整检测流程")
        
    except Exception as e:
        print(f"❌ 演示过程中发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()