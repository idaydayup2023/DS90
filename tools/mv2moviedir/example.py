#!/usr/bin/env python3
"""
mv2moviedir 使用示例

这个脚本展示了如何使用 mv2moviedir.py 来组织电影文件
"""

import os
import sys

def show_usage():
    """显示使用方法"""
    print("mv2moviedir 使用示例:")
    print()
    print("1. 基本用法 - 将电影文件组织到目标目录:")
    print("   python3 mv2moviedir.py /path/to/source/ /path/to/target/")
    print()
    print("2. 使用年份归集:")
    print("   python3 mv2moviedir.py /path/to/source/ /path/to/target/ --year-group")
    print()
    print("3. 强制覆盖已存在的文件:")
    print("   python3 mv2moviedir.py /path/to/source/ /path/to/target/ --force")
    print()
    print("4. 不覆盖已存在的文件:")
    print("   python3 mv2moviedir.py /path/to/source/ /path/to/target/ --no-override")
    print()
    print("5. 完整示例 - 年份归集 + 强制覆盖:")
    print("   python3 mv2moviedir.py /path/to/source/ /path/to/target/ --year-group --force")
    print()
    print("支持的文件格式:")
    print("   视频: .mkv, .mp4, .avi, .mov, .wmv, .flv, .webm")
    print("   字幕: .srt, .ass, .sub, .vtt, .ssa")
    print()
    print("文件命名要求:")
    print("   - 必须包含4位数字年份 (1900-2099)")
    print("   - 建议格式: Movie.Name.YYYY.Resolution.Source.Codec.ext")
    print("   - 示例: The.Matrix.1999.1080p.BluRay.x264.mkv")

def create_test_environment():
    """创建测试环境"""
    print("创建测试环境...")
    
    # 创建测试目录
    test_dir = "test_example"
    source_dir = os.path.join(test_dir, "source")
    target_dir = os.path.join(test_dir, "target")
    
    os.makedirs(source_dir, exist_ok=True)
    os.makedirs(target_dir, exist_ok=True)
    
    # 创建示例文件
    test_files = [
        "The.Matrix.1999.1080p.BluRay.x264.mkv",
        "The.Matrix.1999.1080p.BluRay.x264.srt",
        "Inception.2010.1080p.BluRay.x264.mkv",
        "Inception.2010.1080p.BluRay.x264.srt",
        "Interstellar.2014.4K.UHD.BluRay.x265.mkv",
        "Interstellar.2014.4K.UHD.BluRay.x265.srt"
    ]
    
    for filename in test_files:
        filepath = os.path.join(source_dir, filename)
        with open(filepath, 'w') as f:
            f.write(f"# 测试文件: {filename}\n")
    
    print(f"测试环境已创建在: {test_dir}/")
    print(f"源文件目录: {source_dir}/")
    print(f"目标目录: {target_dir}/")
    print()
    print("运行测试命令:")
    print(f"python3 mv2moviedir.py {source_dir}/ {target_dir}/ --year-group --force")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-test":
        create_test_environment()
    else:
        show_usage()