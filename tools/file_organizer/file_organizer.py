#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
文件整理脚本 - 按文件名将文件分类到对应目录
使用方法: python file_organizer.py [目标目录]
"""

import os
import sys
import argparse
import shutil
from pathlib import Path
from typing import Tuple, Dict, List


class FileOrganizer:
    """文件整理器类"""
    
    def __init__(self, target_directory: str = "."):
        """
        初始化文件整理器
        
        Args:
            target_directory: 目标目录路径，默认为当前目录
        """
        self.target_directory = Path(target_directory).resolve()
        self.total_files = 0
        self.organized_files = 0
        self.skipped_files = 0
        self.created_directories = []
        
    def validate_directory(self) -> bool:
        """
        验证目标目录是否存在且可访问
        
        Returns:
            bool: 目录有效返回True，否则返回False
        """
        if not self.target_directory.exists():
            self.print_error(f"目录 '{self.target_directory}' 不存在")
            return False
            
        if not self.target_directory.is_dir():
            self.print_error(f"'{self.target_directory}' 不是一个目录")
            return False
            
        if not os.access(self.target_directory, os.R_OK | os.W_OK):
            self.print_error(f"没有权限访问目录 '{self.target_directory}'")
            return False
            
        return True
    
    def extract_base_name(self, filename: str) -> str:
        """
        从文件名中提取基本名称，智能处理字幕文件和复杂文件名
        
        对于字幕文件，会去除语言/类型标识符，使同一电影的不同字幕文件归类到同一目录
        对于普通文件，只去除最后一个扩展名
        
        Args:
            filename: 文件名
            
        Returns:
            str: 基本文件名
            
        Examples:
            movie.mkv -> movie
            movie.mp4 -> movie
            movie.ai.srt -> movie
            movie.en.srt -> movie
            movie.gt.srt -> movie
            The.Salt.Path.2024.1080p.WEBRip.x265.10bit.AAC5.1-[YTS.MX].en.srt -> The.Salt.Path.2024.1080p.WEBRip.x265.10bit.AAC5.1-[YTS.MX]
            document.backup.pdf -> document.backup
        """
        # 使用Path对象处理文件名
        path = Path(filename)
        base_name = path.stem  # 去除最后一个扩展名
        
        # 定义常见的字幕文件语言/类型标识符
        subtitle_suffixes = {
            'ai', 'en', 'zh', 'cn', 'jp', 'kr', 'fr', 'de', 'es', 'it', 'ru',  # 语言代码
            'gt', 'emb', 'asr', 'auto', 'forced', 'sdh', 'cc',  # 字幕类型
            'chi', 'eng', 'jpn', 'kor', 'fre', 'ger', 'spa', 'ita', 'rus',  # 三字母语言代码
            'chs', 'cht', 'simplified', 'traditional'  # 中文简繁体
        }
        
        # 检查是否为字幕文件（.srt, .ass, .ssa, .vtt, .sub等）
        if path.suffix.lower() in {'.srt', '.ass', '.ssa', '.vtt', '.sub', '.idx', '.sup'}:
            # 对于字幕文件，尝试去除语言/类型标识符
            parts = base_name.split('.')
            if len(parts) > 1:
                last_part = parts[-1].lower()
                # 如果最后一部分是已知的字幕标识符，则去除它
                if last_part in subtitle_suffixes:
                    base_name = '.'.join(parts[:-1])
        
        return base_name
    
    def is_valid_base_name(self, base_name: str) -> bool:
        """
        检查基本文件名是否有效
        
        Args:
            base_name: 基本文件名
            
        Returns:
            bool: 有效返回True，否则返回False
        """
        return bool(base_name and base_name.strip() and not base_name.startswith('.'))
    
    def create_directory_if_needed(self, dir_name: str) -> bool:
        """
        如果需要，创建目录
        
        Args:
            dir_name: 目录名称
            
        Returns:
            bool: 成功返回True，否则返回False
        """
        dir_path = self.target_directory / dir_name
        
        try:
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                self.created_directories.append(dir_name)
                self.print_info(f"创建目录: {dir_name}/")
                return True
            elif not dir_path.is_dir():
                self.print_error(f"'{dir_name}' 已存在但不是目录")
                return False
            return True
        except PermissionError:
            self.print_error(f"没有权限创建目录 '{dir_name}'")
            return False
        except Exception as e:
            self.print_error(f"创建目录 '{dir_name}' 时发生错误: {e}")
            return False
    
    def move_file_safely(self, source_file: Path, target_dir: str) -> bool:
        """
        安全地移动文件到目标目录
        
        Args:
            source_file: 源文件路径
            target_dir: 目标目录名称
            
        Returns:
            bool: 成功返回True，否则返回False
        """
        target_path = self.target_directory / target_dir / source_file.name
        
        try:
            if target_path.exists():
                self.print_warning(f"目标文件已存在，跳过: {source_file.name}")
                self.skipped_files += 1
                return False
                
            shutil.move(str(source_file), str(target_path))
            print(f"  {source_file.name} -> {target_dir}/")
            self.organized_files += 1
            return True
        except PermissionError:
            self.print_error(f"没有权限移动文件 '{source_file.name}'")
            self.skipped_files += 1
            return False
        except Exception as e:
            self.print_error(f"移动文件 '{source_file.name}' 时发生错误: {e}")
            self.skipped_files += 1
            return False
    
    def organize_files(self) -> Dict[str, int]:
        """
        整理目录中的文件
        
        Returns:
            Dict[str, int]: 包含统计信息的字典
        """
        if not self.validate_directory():
            return {"total": 0, "organized": 0, "skipped": 0}
        
        self.print_info(f"开始整理目录: {self.target_directory}")
        
        # 获取所有文件（不包括目录）
        files = [f for f in self.target_directory.iterdir() 
                if f.is_file() and not f.name.startswith('.')]
        
        self.total_files = len(files)
        
        if self.total_files == 0:
            self.print_warning("目录中没有找到需要整理的文件")
            return {"total": 0, "organized": 0, "skipped": 0}
        
        print(f"找到 {self.total_files} 个文件需要整理")
        
        # 按基本文件名分组处理文件
        for file_path in files:
            base_name = self.extract_base_name(file_path.name)
            
            if not self.is_valid_base_name(base_name):
                self.print_warning(f"跳过无效文件名: {file_path.name}")
                self.skipped_files += 1
                continue
            
            # 创建目录并移动文件
            if self.create_directory_if_needed(base_name):
                self.move_file_safely(file_path, base_name)
            else:
                self.skipped_files += 1
        
        return {
            "total": self.total_files,
            "organized": self.organized_files,
            "skipped": self.skipped_files
        }
    
    def print_statistics(self):
        """打印整理统计信息"""
        print("\n" + "="*50)
        print("整理完成！统计信息:")
        print(f"  总文件数: {self.total_files}")
        print(f"  已整理: {self.organized_files}")
        print(f"  已跳过: {self.skipped_files}")
        
        if self.created_directories:
            print(f"  创建的目录数: {len(self.created_directories)}")
            print("  创建的目录:")
            for dir_name in self.created_directories:
                dir_path = self.target_directory / dir_name
                if dir_path.exists():
                    file_count = len([f for f in dir_path.iterdir() if f.is_file()])
                    print(f"    {dir_name}/ (包含 {file_count} 个文件)")
    
    @staticmethod
    def print_success(message: str):
        """打印成功信息"""
        print(message)
    
    @staticmethod
    def print_error(message: str):
        """打印错误信息"""
        print(f"错误: {message}")
    
    @staticmethod
    def print_warning(message: str):
        """打印警告信息"""
        print(f"警告: {message}")
    
    @staticmethod
    def print_info(message: str):
        """打印信息"""
        print(message)


def show_help():
    """显示帮助信息"""
    help_text = """
文件整理脚本

用途:
    按文件名将文件分类到对应的子目录中。
    例如: document.pdf, document.txt, document.docx 会被移动到 document/ 目录下。

使用方法:
    python file_organizer.py [目标目录]

参数:
    目标目录    要整理的目录路径（可选，默认为当前目录）

选项:
    -h, --help  显示此帮助信息

示例:
    python file_organizer.py                    # 整理当前目录
    python file_organizer.py /path/to/files     # 整理指定目录
    python file_organizer.py --help             # 显示帮助信息

注意事项:
    1. 脚本会根据文件名（去除扩展名）创建子目录
    2. 如果目标文件已存在，将跳过移动操作
    3. 隐藏文件（以.开头）将被忽略
    4. 需要对目标目录有读写权限
    5. 支持中文文件名和特殊字符
    """
    print(help_text)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="文件整理脚本 - 按文件名将文件分类到对应目录",
        add_help=False  # 禁用默认的-h选项，使用自定义的帮助
    )
    
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='要整理的目录路径（默认为当前目录）'
    )
    
    parser.add_argument(
        '-h', '--help',
        action='store_true',
        help='显示帮助信息'
    )
    
    args = parser.parse_args()
    
    if args.help:
        show_help()
        return
    
    organizer = None
    try:
        organizer = FileOrganizer(args.directory)
        stats = organizer.organize_files()
        organizer.print_statistics()
        
        if stats["organized"] > 0:
            organizer.print_success(f"\n成功整理了 {stats['organized']} 个文件！")
        elif stats["total"] == 0:
            organizer.print_info("\n没有找到需要整理的文件。")
        else:
            organizer.print_warning(f"\n所有 {stats['total']} 个文件都被跳过了。")
            
    except KeyboardInterrupt:
        if organizer:
            organizer.print_warning("\n\n操作被用户中断")
        else:
            print("\n\n警告: 操作被用户中断")
        sys.exit(1)
    except Exception as e:
        if organizer:
            organizer.print_error(f"发生未预期的错误: {e}")
        else:
            print(f"错误: 发生未预期的错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()