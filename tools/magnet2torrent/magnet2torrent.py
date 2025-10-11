#!/usr/bin/env python3
"""
磁力链接转种子文件工具集 - 主入口
Magnet2Torrent Tool Suite - Main Entry Point
"""

import sys
import os
import argparse
from pathlib import Path

# 添加converters目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'converters'))

def print_banner():
    """打印工具横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                        磁力链接转种子文件工具集                              ║
║                     Magnet2Torrent Tool Suite                               ║
║                                                                              ║
║  提供多种可靠的磁力链接转换解决方案，解决libtorrent稳定性问题                ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)

def show_available_converters():
    """显示可用的转换器"""
    print("\n🔧 可用的转换器:")
    print("   1. aria2      - Aria2转换器 (推荐)")
    print("   2. qbittorrent - qBittorrent Web API转换器")
    print("   3. dht        - 纯Python DHT客户端")
    print("   4. info       - 磁力链接信息提取器")
    print()
    print("💡 使用方法:")
    print("   python3 magnet2torrent.py <converter> [options]")
    print()
    print("📖 查看具体转换器帮助:")
    print("   python3 magnet2torrent.py aria2 --help")
    print("   python3 magnet2torrent.py qbittorrent --help")
    print("   python3 magnet2torrent.py dht --help")
    print("   python3 magnet2torrent.py info --help")
    print()
    print("🎬 运行演示:")
    print("   python3 demos/aria2_demo.py")
    print("   python3 demos/qbittorrent_demo.py")
    print("   python3 demos/info_extractor_demo.py")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='磁力链接转种子文件工具集',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
可用的转换器:
  aria2         Aria2转换器 (推荐)
  qbittorrent   qBittorrent Web API转换器  
  dht           纯Python DHT客户端
  info          磁力链接信息提取器

示例:
  python3 magnet2torrent.py aria2 --magnet "magnet:?xt=urn:btih:..." --output ./torrents/
  python3 magnet2torrent.py info --magnet "magnet:?xt=urn:btih:..." --extract --json
        """
    )
    
    parser.add_argument('converter', nargs='?', 
                       choices=['aria2', 'qbittorrent', 'dht', 'info'],
                       help='要使用的转换器')
    
    # 如果没有参数，显示帮助
    if len(sys.argv) == 1:
        print_banner()
        show_available_converters()
        return 0
    
    args, remaining_args = parser.parse_known_args()
    
    if not args.converter:
        print_banner()
        show_available_converters()
        return 0
    
    # 根据选择的转换器调用相应的模块
    try:
        if args.converter == 'aria2':
            from converters.aria2_converter import main as aria2_main
            sys.argv = ['aria2_converter.py'] + remaining_args
            return aria2_main()
        elif args.converter == 'qbittorrent':
            from converters.qbittorrent_converter import main as qbt_main
            sys.argv = ['qbittorrent_converter.py'] + remaining_args
            return qbt_main()
        elif args.converter == 'dht':
            from converters.dht_converter import main as dht_main
            sys.argv = ['dht_converter.py'] + remaining_args
            return dht_main()
        elif args.converter == 'info':
            from converters.info_extractor import main as info_main
            sys.argv = ['info_extractor.py'] + remaining_args
            return info_main()
    except ImportError as e:
        print(f"❌ 导入转换器失败: {e}")
        print("请确保所有转换器文件都在converters目录中")
        return 1
    except Exception as e:
        print(f"❌ 运行转换器时出错: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())