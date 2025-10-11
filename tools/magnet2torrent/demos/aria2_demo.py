#!/usr/bin/env python3
"""
aria2 磁力链接转换方案演示
展示如何使用 aria2 稳定地转换磁力链接
"""

import sys
import time
from pathlib import Path
import sys
import os
# 添加converters目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from converters.aria2_converter import Aria2MagnetConverter

def print_banner():
    """打印横幅"""
    print("=" * 60)
    print("🚀 aria2 磁力链接转换方案演示")
    print("=" * 60)
    print()

def print_advantages():
    """打印方案优势"""
    print("🎯 aria2 方案优势:")
    print("   ✅ 极高稳定性 - aria2 是成熟的下载工具")
    print("   ✅ 轻量级 - 资源占用少，性能优秀")
    print("   ✅ 跨平台 - 支持 Windows/macOS/Linux")
    print("   ✅ 丰富配置 - 可精细调优下载参数")
    print("   ✅ 活跃维护 - 持续更新和bug修复")
    print("   ✅ 广泛使用 - 被众多下载工具采用")
    print()

def print_vs_libtorrent():
    """对比 libtorrent"""
    print("🆚 与 libtorrent 对比:")
    print("   aria2:")
    print("     ✅ 稳定性更好，很少崩溃")
    print("     ✅ 内存使用更少")
    print("     ✅ 配置更灵活")
    print("     ✅ 错误处理更完善")
    print("     ✅ 支持更多协议")
    print()
    print("   libtorrent:")
    print("     ❌ 在某些环境下不稳定")
    print("     ❌ 内存泄漏问题")
    print("     ❌ Python绑定有时出问题")
    print("     ❌ 错误信息不够详细")
    print()

def demo_installation():
    """演示安装步骤"""
    print("📦 安装 aria2:")
    print("   macOS:   brew install aria2")
    print("   Ubuntu:  sudo apt install aria2")
    print("   CentOS:  sudo yum install aria2")
    print("   Windows: 下载二进制文件或使用 chocolatey")
    print()

def demo_basic_usage():
    """演示基本使用"""
    print("🔧 基本使用演示:")
    print()
    
    # 创建转换器
    converter = Aria2MagnetConverter()
    
    print("1. 启动 aria2 守护进程...")
    if converter.start_aria2_daemon():
        print("   ✅ aria2 启动成功")
        
        print("\n2. 测试连接...")
        if converter.test_connection():
            print("   ✅ 连接正常")
            
            print("\n3. 演示磁力链接转换...")
            print("   (这里只是演示，实际使用时请提供真实的磁力链接)")
            
            # 示例磁力链接（这里只是格式示例）
            example_magnet = "magnet:?xt=urn:btih:example_hash&dn=example_name"
            print(f"   磁力链接: {example_magnet[:50]}...")
            
            print("\n4. 转换过程:")
            print("   📥 添加下载任务")
            print("   🔄 等待元数据下载")
            print("   💾 保存种子文件")
            print("   🧹 清理临时文件")
            
            print("\n5. 停止 aria2 守护进程...")
            converter.stop_aria2_daemon()
            print("   ✅ aria2 已停止")
        else:
            print("   ❌ 连接失败")
    else:
        print("   ❌ aria2 启动失败")
        print("   💡 请确保已安装 aria2: brew install aria2")

def demo_advanced_features():
    """演示高级功能"""
    print("\n🚀 高级功能:")
    print("   📁 批量转换 - 扫描目录中的所有磁力链接文件")
    print("   ⚙️  自定义配置 - 使用配置文件优化下载参数")
    print("   🔄 自动重试 - 失败时自动重试")
    print("   📊 进度显示 - 实时显示下载进度")
    print("   🛡️  错误处理 - 完善的异常处理机制")
    print()

def demo_command_examples():
    """演示命令行使用示例"""
    print("💻 命令行使用示例:")
    print()
    print("# 启动 aria2 守护进程")
    print("python3 aria2_magnet_converter.py --start-daemon")
    print()
    print("# 测试连接")
    print("python3 aria2_magnet_converter.py --test-connection")
    print()
    print("# 转换单个磁力链接")
    print("python3 aria2_magnet_converter.py --magnet 'magnet:?xt=urn:btih:...'")
    print()
    print("# 批量转换目录中的磁力链接文件")
    print("python3 aria2_magnet_converter.py --scan-dir ./magnets --output-dir ./torrents")
    print()
    print("# 停止 aria2 守护进程")
    print("python3 aria2_magnet_converter.py --stop-daemon")
    print()

def demo_configuration():
    """演示配置说明"""
    print("⚙️ 配置文件说明:")
    print("   📄 aria2_config.conf - aria2 配置文件")
    print("   🔧 可调整下载参数、网络设置、BT选项等")
    print("   📝 详细注释说明每个配置项的作用")
    print()
    print("   主要配置项:")
    print("     • max-concurrent-downloads: 最大同时下载数")
    print("     • max-connection-per-server: 单文件最大连接数")
    print("     • bt-max-peers: 最大连接节点数")
    print("     • seed-time: 做种时间（设为0不做种）")
    print()

def demo_troubleshooting():
    """演示故障排除"""
    print("🔧 故障排除:")
    print()
    print("❓ 常见问题:")
    print("   Q: aria2c 命令不存在")
    print("   A: 请先安装 aria2: brew install aria2")
    print()
    print("   Q: 连接 RPC 失败")
    print("   A: 检查 aria2 是否启动，端口是否被占用")
    print()
    print("   Q: 磁力链接下载慢")
    print("   A: 调整配置文件中的连接数和节点数")
    print()
    print("   Q: 转换失败")
    print("   A: 检查磁力链接是否有效，网络是否正常")
    print()

def main():
    """主演示函数"""
    print_banner()
    
    print("🎬 这是 aria2 磁力链接转换方案的演示")
    print("   aria2 是一个稳定、高效的下载工具")
    print("   相比 libtorrent，它具有更好的稳定性和更少的问题")
    print()
    
    print_advantages()
    print_vs_libtorrent()
    demo_installation()
    demo_basic_usage()
    demo_advanced_features()
    demo_command_examples()
    demo_configuration()
    demo_troubleshooting()
    
    print("=" * 60)
    print("🎉 aria2 方案演示完成!")
    print("💡 这是一个比 libtorrent 更稳定的替代方案")
    print("🚀 开始使用: python3 aria2_magnet_converter.py --help")
    print("=" * 60)

if __name__ == "__main__":
    main()