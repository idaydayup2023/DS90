#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File Organizer 使用示例脚本

演示 file_organizer.py 的各种使用方法和功能特性
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def create_test_environment():
    """创建测试环境，生成示例文件"""
    # 创建临时目录
    test_dir = tempfile.mkdtemp(prefix="file_organizer_test_")
    print(f"创建测试目录: {test_dir}")
    
    # 创建各种类型的测试文件
    test_files = [
        # 文档文件
        "report.pdf",
        "report.docx", 
        "report.txt",
        
        # 电影文件和字幕
        "movie.mkv",
        "movie.ai.srt",
        "movie.en.srt",
        "movie.zh.srt",
        
        # 照片文件
        "vacation.jpg",
        "vacation.raw",
        "vacation.png",
        
        # 音乐文件
        "song.mp3",
        "song.flac",
        
        # 程序文件
        "script.py",
        "script.js",
        "script.sh",
        
        # 中文文件名
        "中文文档.pdf",
        "中文文档.txt",
        "电影.mkv",
        "电影.chs.srt",
        "电影.cht.srt",
    ]
    
    # 创建测试文件
    for filename in test_files:
        file_path = os.path.join(test_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"这是测试文件: {filename}")
    
    print(f"创建了 {len(test_files)} 个测试文件")
    return test_dir

def demo_basic_usage():
    """演示基本使用方法"""
    print("\n" + "="*60)
    print("演示 1: 基本文件整理功能")
    print("="*60)
    
    # 创建测试环境
    test_dir = create_test_environment()
    
    print(f"\n整理前的文件列表:")
    for file in sorted(os.listdir(test_dir)):
        print(f"  {file}")
    
    # 运行 file_organizer
    print(f"\n运行 file_organizer.py...")
    os.system(f"cd {test_dir} && python3 {os.path.join(os.path.dirname(__file__), 'file_organizer.py')}")
    
    print(f"\n整理后的目录结构:")
    for root, dirs, files in os.walk(test_dir):
        level = root.replace(test_dir, '').count(os.sep)
        indent = ' ' * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        subindent = ' ' * 2 * (level + 1)
        for file in files:
            print(f"{subindent}{file}")
    
    # 清理
    shutil.rmtree(test_dir)
    print(f"\n测试完成，已清理测试目录")

def demo_subtitle_intelligence():
    """演示字幕文件智能处理"""
    print("\n" + "="*60)
    print("演示 2: 字幕文件智能处理")
    print("="*60)
    
    # 创建专门的字幕测试环境
    test_dir = tempfile.mkdtemp(prefix="subtitle_test_")
    print(f"创建字幕测试目录: {test_dir}")
    
    subtitle_files = [
        "movie1.mkv",
        "movie1.ai.srt",      # AI生成字幕
        "movie1.en.srt",      # 英文字幕
        "movie1.zh.srt",      # 中文字幕
        "movie1.forced.srt",  # 强制字幕
        
        "movie2.mp4",
        "movie2.chs.ass",     # 简体中文ASS字幕
        "movie2.cht.ass",     # 繁体中文ASS字幕
        "movie2.eng.vtt",     # 英文VTT字幕
        
        "series.s01e01.mkv",
        "series.s01e01.auto.srt",  # 自动生成字幕
        "series.s01e01.sdh.srt",   # 听障字幕
    ]
    
    for filename in subtitle_files:
        file_path = os.path.join(test_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"测试内容: {filename}")
    
    print(f"\n字幕测试文件:")
    for file in sorted(subtitle_files):
        print(f"  {file}")
    
    # 运行整理
    print(f"\n运行字幕智能整理...")
    os.system(f"cd {test_dir} && python3 {os.path.join(os.path.dirname(__file__), 'file_organizer.py')}")
    
    print(f"\n整理后的字幕分组:")
    for root, dirs, files in os.walk(test_dir):
        if root != test_dir:  # 只显示子目录
            level = root.replace(test_dir, '').count(os.sep)
            indent = ' ' * 2 * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = ' ' * 2 * (level + 1)
            for file in sorted(files):
                print(f"{subindent}{file}")
    
    # 清理
    shutil.rmtree(test_dir)
    print(f"\n字幕测试完成，已清理测试目录")

def demo_help_and_info():
    """演示帮助信息和版本信息"""
    print("\n" + "="*60)
    print("演示 3: 帮助信息和脚本信息")
    print("="*60)
    
    script_path = os.path.join(os.path.dirname(__file__), 'file_organizer.py')
    
    print("\n显示帮助信息:")
    print("-" * 40)
    os.system(f"python3 {script_path} --help")

def demo_error_handling():
    """演示错误处理"""
    print("\n" + "="*60)
    print("演示 4: 错误处理和边界情况")
    print("="*60)
    
    script_path = os.path.join(os.path.dirname(__file__), 'file_organizer.py')
    
    print("\n1. 测试不存在的目录:")
    print("-" * 30)
    os.system(f"python3 {script_path} /nonexistent/directory")
    
    print("\n2. 测试空目录:")
    print("-" * 30)
    empty_dir = tempfile.mkdtemp(prefix="empty_test_")
    os.system(f"python3 {script_path} {empty_dir}")
    shutil.rmtree(empty_dir)

def main():
    """主函数 - 运行所有演示"""
    print("File Organizer 使用示例演示")
    print("=" * 60)
    print("本脚本将演示 file_organizer.py 的各种功能和使用方法")
    
    try:
        # 检查 file_organizer.py 是否存在
        script_path = os.path.join(os.path.dirname(__file__), 'file_organizer.py')
        if not os.path.exists(script_path):
            print(f"错误: 找不到 file_organizer.py 文件")
            print(f"请确保 file_organizer.py 与本示例脚本在同一目录下")
            return
        
        # 运行各种演示
        demo_basic_usage()
        demo_subtitle_intelligence()
        demo_help_and_info()
        demo_error_handling()
        
        print("\n" + "="*60)
        print("所有演示完成！")
        print("="*60)
        print("\n要在实际项目中使用 file_organizer.py，请运行:")
        print("  python3 file_organizer.py [目录路径]")
        print("\n更多信息请查看 README.md 文档")
        
    except KeyboardInterrupt:
        print("\n\n演示被用户中断")
    except Exception as e:
        print(f"\n演示过程中出现错误: {e}")

if __name__ == "__main__":
    main()