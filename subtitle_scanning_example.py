#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕扫描功能使用示例
演示如何使用媒体管理系统的字幕检测和扫描功能
"""

import os
import sys
import logging
from pathlib import Path

# 添加项目路径到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from media_manager.scanner.file_scanner import MediaFileScanner
from media_manager.utils.subtitle_detector import SubtitleDetector
from media_manager.database.db_manager import get_db_manager
from media_manager.utils.directory_manager import get_directory_manager

def setup_logging():
    """设置日志配置"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('subtitle_scanning.log', encoding='utf-8')
        ]
    )

def create_test_subtitle_files():
    """创建测试字幕文件用于演示"""
    test_dir = Path("test_media")
    test_dir.mkdir(exist_ok=True)
    
    # 创建测试视频文件（空文件用于演示）
    video_files = [
        "test_movie.mp4",
        "TV_Show_S01E01.mkv",
        "Anime_Episode_01.mp4"
    ]
    
    # 创建测试字幕文件
    subtitle_files = [
        # AI字幕文件
        "test_movie.ai.srt",
        "TV_Show_S01E01.ai.srt", 
        "Anime_Episode_01.ai.srt",
        
        # 其他类型字幕
        "test_movie.zh-cn.srt",
        "test_movie.en-us.srt",
        "TV_Show_S01E01.chinese.ass",
        "Anime_Episode_01.japanese.vtt"
    ]
    
    # 创建文件
    for filename in video_files + subtitle_files:
        file_path = test_dir / filename
        if not file_path.exists():
            if filename.endswith(('.mp4', '.mkv')):
                # 创建小的测试视频文件
                file_path.write_bytes(b'fake video content for testing')
            else:
                # 创建测试字幕内容
                subtitle_content = create_test_subtitle_content(filename)
                file_path.write_text(subtitle_content, encoding='utf-8')
    
    return test_dir

def create_test_subtitle_content(filename: str) -> str:
    """创建测试字幕内容"""
    if filename.endswith('.srt'):
        return """1
00:00:01,000 --> 00:00:04,000
这是第一条字幕

2
00:00:05,000 --> 00:00:08,000
This is the second subtitle

3
00:00:09,000 --> 00:00:12,000
AI生成的字幕内容示例
"""
    elif filename.endswith('.ass'):
        return """[Script Info]
Title: Test Subtitle
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,这是ASS格式字幕
Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,ASS subtitle example
"""
    elif filename.endswith('.vtt'):
        return """WEBVTT

00:01.000 --> 00:04.000
这是VTT格式字幕

00:05.000 --> 00:08.000
VTT subtitle example
"""
    else:
        return "Test subtitle content"

def demonstrate_subtitle_detection():
    """演示字幕检测功能"""
    print("\n=== 字幕检测功能演示 ===")
    
    # 创建测试文件
    test_dir = create_test_subtitle_files()
    print(f"创建测试文件目录: {test_dir.absolute()}")
    
    # 初始化字幕检测器
    subtitle_detector = SubtitleDetector()
    
    # 测试视频文件
    test_videos = [
        test_dir / "test_movie.mp4",
        test_dir / "TV_Show_S01E01.mkv",
        test_dir / "Anime_Episode_01.mp4"
    ]
    
    for video_path in test_videos:
        print(f"\n--- 检测视频: {video_path.name} ---")
        
        # 检测字幕
        subtitles = subtitle_detector.detect_subtitles_for_video(str(video_path))
        
        if subtitles:
            print(f"找到 {len(subtitles)} 个字幕文件:")
            for i, subtitle in enumerate(subtitles, 1):
                print(f"  {i}. {subtitle['subtitle_name']}")
                print(f"     类型: {subtitle['subtitle_type']}")
                print(f"     语言: {subtitle['language_name']} ({subtitle['language_code']})")
                print(f"     格式: {subtitle['format']}")
                print(f"     AI生成: {'是' if subtitle['is_ai_generated'] else '否'}")
                print(f"     字幕数量: {subtitle['subtitle_count']}")
                print(f"     质量评分: {subtitle['quality_score']:.1f}")
                print()
        else:
            print("  未找到字幕文件")

def demonstrate_media_scanning_with_subtitles():
    """演示带字幕检测的媒体扫描功能"""
    print("\n=== 媒体扫描与字幕检测演示 ===")
    
    # 创建测试文件
    test_dir = create_test_subtitle_files()
    
    # 初始化扫描器
    scanner = MediaFileScanner(max_workers=2)
    
    print(f"开始扫描目录: {test_dir.absolute()}")
    
    # 扫描目录
    scan_result = scanner.scan_directory(str(test_dir), recursive=True)
    
    print("\n扫描结果:")
    print(f"  扫描文件数: {scan_result['files_scanned']}")
    print(f"  添加文件数: {scan_result['files_added']}")
    print(f"  更新文件数: {scan_result['files_updated']}")
    print(f"  跳过文件数: {scan_result['files_skipped']}")
    print(f"  错误数: {scan_result['errors']}")

def demonstrate_missing_ai_subtitles_report():
    """演示缺失AI字幕报告功能"""
    print("\n=== 缺失AI字幕报告演示 ===")
    
    scanner = MediaFileScanner()
    
    # 获取缺失AI字幕报告
    report = scanner.get_missing_ai_subtitles_report()
    
    print(f"缺失AI字幕统计:")
    print(f"  总计缺失: {report['total_missing']} 个文件")
    print(f"  电影缺失: {report['missing_by_type']['movies']} 个")
    print(f"  电视剧缺失: {report['missing_by_type']['tv_shows']} 个")
    
    if report['missing_files']:
        print("\n缺失AI字幕的文件列表:")
        for i, file_info in enumerate(report['missing_files'][:10], 1):  # 只显示前10个
            print(f"  {i}. {file_info['file_name']}")
            print(f"     路径: {file_info['file_path']}")
        
        if len(report['missing_files']) > 10:
            print(f"  ... 还有 {len(report['missing_files']) - 10} 个文件")

def demonstrate_subtitle_database_operations():
    """演示字幕数据库操作"""
    print("\n=== 字幕数据库操作演示 ===")
    
    db = get_db_manager()
    
    # 查询字幕统计信息
    try:
        # 总字幕文件数
        total_subtitles = db.execute_query(
            "SELECT COUNT(*) as count FROM subtitle_files"
        )
        if total_subtitles:
            print(f"数据库中总字幕文件数: {total_subtitles[0]['count']}")
        
        # AI字幕统计
        ai_subtitles = db.execute_query(
            "SELECT COUNT(*) as count FROM subtitle_files WHERE is_ai_generated = 1"
        )
        if ai_subtitles:
            print(f"AI生成字幕数: {ai_subtitles[0]['count']}")
        
        # 按语言统计
        lang_stats = db.execute_query("""
            SELECT language_code, language_name, COUNT(*) as count
            FROM subtitle_files
            GROUP BY language_code, language_name
            ORDER BY count DESC
        """)
        
        if lang_stats:
            print("\n按语言统计:")
            for stat in lang_stats:
                print(f"  {stat['language_name']} ({stat['language_code']}): {stat['count']} 个")
        
        # 按格式统计
        format_stats = db.execute_query("""
            SELECT format, COUNT(*) as count
            FROM subtitle_files
            GROUP BY format
            ORDER BY count DESC
        """)
        
        if format_stats:
            print("\n按格式统计:")
            for stat in format_stats:
                print(f"  {stat['format'].upper()}: {stat['count']} 个")
                
    except Exception as e:
        print(f"查询数据库失败: {e}")

def demonstrate_subtitle_quality_analysis():
    """演示字幕质量分析"""
    print("\n=== 字幕质量分析演示 ===")
    
    db = get_db_manager()
    
    try:
        # 质量评分统计
        quality_stats = db.execute_query("""
            SELECT 
                CASE 
                    WHEN quality_score >= 8.0 THEN '优秀 (8.0+)'
                    WHEN quality_score >= 6.0 THEN '良好 (6.0-7.9)'
                    WHEN quality_score >= 4.0 THEN '一般 (4.0-5.9)'
                    ELSE '较差 (<4.0)'
                END as quality_level,
                COUNT(*) as count,
                AVG(quality_score) as avg_score
            FROM subtitle_files
            GROUP BY quality_level
            ORDER BY avg_score DESC
        """)
        
        if quality_stats:
            print("字幕质量分布:")
            for stat in quality_stats:
                print(f"  {stat['quality_level']}: {stat['count']} 个 (平均分: {stat['avg_score']:.2f})")
        
        # 字幕数量统计
        subtitle_count_stats = db.execute_query("""
            SELECT 
                CASE 
                    WHEN subtitle_count >= 1000 THEN '长片 (1000+)'
                    WHEN subtitle_count >= 500 THEN '中等 (500-999)'
                    WHEN subtitle_count >= 100 THEN '短片 (100-499)'
                    ELSE '片段 (<100)'
                END as length_category,
                COUNT(*) as count,
                AVG(subtitle_count) as avg_count
            FROM subtitle_files
            WHERE subtitle_count > 0
            GROUP BY length_category
            ORDER BY avg_count DESC
        """)
        
        if subtitle_count_stats:
            print("\n按字幕数量分类:")
            for stat in subtitle_count_stats:
                print(f"  {stat['length_category']}: {stat['count']} 个 (平均: {stat['avg_count']:.0f} 条字幕)")
                
    except Exception as e:
        print(f"分析字幕质量失败: {e}")

def cleanup_test_files():
    """清理测试文件"""
    test_dir = Path("test_media")
    if test_dir.exists():
        import shutil
        shutil.rmtree(test_dir)
        print(f"\n已清理测试文件目录: {test_dir.absolute()}")

def main():
    """主函数"""
    print("字幕扫描功能演示程序")
    print("=" * 50)
    
    # 设置日志
    setup_logging()
    
    try:
        # 演示各项功能
        demonstrate_subtitle_detection()
        demonstrate_media_scanning_with_subtitles()
        demonstrate_missing_ai_subtitles_report()
        demonstrate_subtitle_database_operations()
        demonstrate_subtitle_quality_analysis()
        
    except Exception as e:
        print(f"\n演示过程中发生错误: {e}")
        logging.exception("演示程序异常")
    
    finally:
        # 清理测试文件
        try:
            cleanup_test_files()
        except Exception as e:
            print(f"清理测试文件失败: {e}")
    
    print("\n演示完成！")

if __name__ == "__main__":
    main()