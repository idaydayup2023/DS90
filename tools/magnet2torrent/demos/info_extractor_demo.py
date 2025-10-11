#!/usr/bin/env python3
"""
磁力链接信息提取器演示脚本
"""

import sys
import os
from typing import Dict, Any

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 添加converters目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from converters.info_extractor import MagnetInfoExtractor
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保info_extractor.py文件存在于converters目录中")
    sys.exit(1)

def print_banner():
    """打印横幅"""
    banner = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                        磁力链接信息提取器演示                                ║
║                     Magnet Link Info Extractor Demo                         ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """
    print(banner)

def print_advantages():
    """打印优势"""
    print("\n🌟 磁力链接信息提取器的优势:")
    print("   ✅ 纯Python实现，无需外部依赖")
    print("   ✅ 支持磁力链接解析和验证")
    print("   ✅ 可以提取Info Hash、显示名称、追踪器等信息")
    print("   ✅ 支持生成基本的种子文件信息")
    print("   ✅ 提供JSON格式的信息导出")
    print("   ✅ 支持从信息重新创建磁力链接")
    print("   ✅ 内置文件大小格式化功能")

def demo_basic_usage():
    """演示基本使用"""
    print("\n📋 基本使用演示:")
    
    # 示例磁力链接
    sample_magnets = [
        "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a&dn=Sample+Movie&tr=udp://tracker.example.com:80",
        "magnet:?xt=urn:btih:1234567890abcdef1234567890abcdef12345678&dn=Test+File&xl=1073741824",
        "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
    ]
    
    extractor = MagnetInfoExtractor()
    
    for i, magnet in enumerate(sample_magnets, 1):
        print(f"\n   示例 {i}: 解析磁力链接")
        print(f"   磁力链接: {magnet[:60]}...")
        
        try:
            # 解析磁力链接
            info = extractor.extract_magnet_info(magnet)
            if info:
                print(f"   ✅ Info Hash: {info.get('info_hash', 'N/A')}")
                print(f"   ✅ 显示名称: {info.get('display_name', 'N/A')}")
                print(f"   ✅ 追踪器数量: {len(info.get('trackers', []))}")
                
                # 验证磁力链接
                validation = extractor.validate_magnet_link(magnet)
                print(f"   ✅ 链接有效性: {'有效' if validation.get('is_valid', False) else '无效'}")
            else:
                print(f"   ❌ 解析失败: 无法提取磁力链接信息")
            
        except Exception as e:
            print(f"   ❌ 解析失败: {e}")

def demo_advanced_features():
    """演示高级功能"""
    print("\n🔧 高级功能演示:")
    
    extractor = MagnetInfoExtractor()
    
    # 示例信息
    sample_info = {
        'info_hash': 'c12fe1c06bba254a9dc9f519b335aa7c1367a88a',
        'display_name': 'Sample Movie 2023',
        'trackers': [
            'udp://tracker.example.com:80',
            'udp://tracker2.example.com:80'
        ],
        'file_size': 1073741824  # 1GB
    }
    
    print("\n   📊 生成种子信息:")
    try:
        torrent_info = extractor.generate_basic_torrent_info(sample_info)
        print(f"   ✅ 种子名称: {torrent_info.get('name', 'N/A')}")
        print(f"   ✅ Info Hash: {torrent_info.get('info_hash', 'N/A')}")
        print(f"   ✅ 创建时间: {torrent_info.get('creation_date', 'N/A')}")
        print(f"   ✅ 追踪器: {len(torrent_info.get('announce_list', []))} 个")
    except Exception as e:
        print(f"   ❌ 生成失败: {e}")
    
    print("\n   🔗 重新创建磁力链接:")
    try:
        new_magnet = extractor.create_magnet_from_info(
            info_hash=sample_info['info_hash'],
            display_name=sample_info['display_name'],
            trackers=sample_info['trackers'],
            file_size=sample_info['file_size']
        )
        print(f"   ✅ 新磁力链接: {new_magnet[:80]}...")
    except Exception as e:
        print(f"   ❌ 创建失败: {e}")
    
    print("\n   📁 文件大小格式化:")
    sizes = [1024, 1048576, 1073741824, 1099511627776]
    for size in sizes:
        formatted = extractor._format_file_size(size)
        print(f"   ✅ {size} 字节 = {formatted}")

def demo_json_export():
    """演示JSON导出功能"""
    print("\n💾 JSON导出功能演示:")
    
    extractor = MagnetInfoExtractor()
    
    # 示例磁力链接
    magnet = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a&dn=Sample+Movie&tr=udp://tracker.example.com:80"
    
    try:
        # 解析磁力链接
        info = extractor.extract_magnet_info(magnet)
        
        if info:
            # 保存为JSON
            json_file = "sample_magnet_info.json"
            success = extractor.save_magnet_info_to_json(info, json_file)
            
            if success:
                print(f"   ✅ 信息已保存到: {json_file}")
                
                # 检查文件是否存在
                if os.path.exists(json_file):
                    file_size = os.path.getsize(json_file)
                    print(f"   ✅ 文件大小: {file_size} 字节")
                    
                    # 清理演示文件
                    os.remove(json_file)
                    print(f"   🧹 已清理演示文件: {json_file}")
                else:
                    print(f"   ❌ 文件未找到: {json_file}")
            else:
                print(f"   ❌ 保存失败")
        else:
            print(f"   ❌ 解析磁力链接失败")
            
    except Exception as e:
        print(f"   ❌ JSON导出失败: {e}")

def show_command_line_usage():
    """显示命令行使用方法"""
    print("\n📝 命令行使用方法:")
    print("   # 解析磁力链接")
    print("   python3 magnet_info_extractor.py --parse 'magnet:?xt=urn:btih:...'")
    print()
    print("   # 验证磁力链接")
    print("   python3 magnet_info_extractor.py --validate 'magnet:?xt=urn:btih:...'")
    print()
    print("   # 生成种子信息")
    print("   python3 magnet_info_extractor.py --generate-torrent 'magnet:?xt=urn:btih:...'")
    print()
    print("   # 导出为JSON")
    print("   python3 magnet_info_extractor.py --export-json 'magnet:?xt=urn:btih:...' output.json")
    print()
    print("   # 显示帮助")
    print("   python3 magnet_info_extractor.py --help")

def show_integration_examples():
    """显示集成示例"""
    print("\n🔧 集成示例:")
    print("   # 在Python脚本中使用")
    print("   from magnet_info_extractor import MagnetInfoExtractor")
    print("   ")
    print("   extractor = MagnetInfoExtractor()")
    print("   info = extractor.parse_magnet_link(magnet_url)")
    print("   print(f'Info Hash: {info[\"info_hash\"]}')") 
    print()
    print("   # 批量处理磁力链接")
    print("   magnets = ['magnet1', 'magnet2', 'magnet3']")
    print("   for magnet in magnets:")
    print("       try:")
    print("           info = extractor.parse_magnet_link(magnet)")
    print("           print(f'处理成功: {info[\"display_name\"]}')") 
    print("       except Exception as e:")
    print("           print(f'处理失败: {e}')")

def show_troubleshooting():
    """显示故障排除"""
    print("\n🔧 故障排除:")
    print("   常见问题:")
    print("   ❓ 磁力链接解析失败")
    print("      - 检查磁力链接格式是否正确")
    print("      - 确保包含有效的Info Hash")
    print("      - 验证URL编码是否正确")
    print()
    print("   ❓ JSON导出失败")
    print("      - 检查目标目录是否存在")
    print("      - 确保有写入权限")
    print("      - 验证磁力链接信息是否完整")
    print()
    print("   ❓ 种子信息生成失败")
    print("      - 确保提供了必要的信息")
    print("      - 检查Info Hash格式")
    print("      - 验证追踪器URL格式")

def main():
    """主函数"""
    print_banner()
    print_advantages()
    demo_basic_usage()
    demo_advanced_features()
    demo_json_export()
    show_command_line_usage()
    show_integration_examples()
    show_troubleshooting()
    
    print("\n" + "="*80)
    print("🎉 磁力链接信息提取器演示完成!")
    print("💡 使用 'python3 magnet_info_extractor.py --help' 查看更多选项")
    print("="*80)

if __name__ == "__main__":
    main()