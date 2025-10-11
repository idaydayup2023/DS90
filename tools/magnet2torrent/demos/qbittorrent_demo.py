#!/usr/bin/env python3
"""
qBittorrent 磁力链接转换方案演示
展示如何使用 qBittorrent Web API 稳定地转换磁力链接
"""

import sys
import time
from pathlib import Path
import sys
import os
# 添加converters目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from converters.qbittorrent_converter import QBittorrentMagnetConverter

def print_banner():
    """打印横幅"""
    print("=" * 60)
    print("🚀 qBittorrent 磁力链接转换方案演示")
    print("=" * 60)
    print()

def print_advantages():
    """打印方案优势"""
    print("🎯 qBittorrent 方案优势:")
    print("   ✅ 极高稳定性 - 成熟的 BitTorrent 客户端")
    print("   ✅ 功能完整 - 完整的种子管理功能")
    print("   ✅ Web API - 强大的 RESTful API 接口")
    print("   ✅ 跨平台 - 支持所有主流操作系统")
    print("   ✅ 活跃开发 - 持续更新和维护")
    print("   ✅ 用户友好 - 可视化界面和命令行并存")
    print("   ✅ 高性能 - 优秀的下载和上传性能")
    print()

def print_vs_others():
    """对比其他方案"""
    print("🆚 与其他方案对比:")
    print("   qBittorrent:")
    print("     ✅ 稳定性最佳，很少出现问题")
    print("     ✅ API 功能最完整")
    print("     ✅ 支持完整的种子生命周期管理")
    print("     ✅ 可以作为常驻服务运行")
    print("     ✅ 支持远程管理")
    print()
    print("   aria2:")
    print("     ✅ 轻量级，启动快")
    print("     ❌ BT 功能相对简单")
    print("     ❌ 种子管理功能有限")
    print()
    print("   libtorrent:")
    print("     ❌ Python 绑定不够稳定")
    print("     ❌ 错误处理复杂")
    print("     ❌ 内存管理问题")
    print()

def demo_installation():
    """演示安装步骤"""
    print("📦 安装 qBittorrent:")
    print("   macOS:   brew install qbittorrent")
    print("   Ubuntu:  sudo apt install qbittorrent-nox")
    print("   CentOS:  sudo yum install qbittorrent-nox")
    print("   Windows: 下载官方安装包")
    print()
    print("💡 注意: 需要安装 qbittorrent-nox (无界面版本) 用于命令行")
    print()

def demo_basic_usage():
    """演示基本使用"""
    print("🔧 基本使用演示:")
    print()
    
    # 创建转换器
    converter = QBittorrentMagnetConverter()
    
    print("1. 启动 qBittorrent 守护进程...")
    if converter.start_qbittorrent():
        print("   ✅ qBittorrent 启动成功")
        
        print("\n2. 测试连接和登录...")
        if converter.test_connection():
            print("   ✅ 连接和登录成功")
            
            print("\n3. 演示磁力链接转换...")
            print("   (这里只是演示，实际使用时请提供真实的磁力链接)")
            
            # 示例磁力链接（这里只是格式示例）
            example_magnet = "magnet:?xt=urn:btih:example_hash&dn=example_name"
            print(f"   磁力链接: {example_magnet[:50]}...")
            
            print("\n4. 转换过程:")
            print("   📥 添加磁力链接任务")
            print("   ⏸️  暂停状态等待元数据")
            print("   📊 监控下载进度")
            print("   💾 导出种子文件")
            print("   🧹 清理临时任务")
            
            print("\n5. 登出和停止服务...")
            converter.logout()
            converter.stop_qbittorrent()
            print("   ✅ qBittorrent 已停止")
        else:
            print("   ❌ 连接失败")
    else:
        print("   ❌ qBittorrent 启动失败")
        print("   💡 请确保已安装 qBittorrent: brew install qbittorrent")

def demo_advanced_features():
    """演示高级功能"""
    print("\n🚀 高级功能:")
    print("   📁 批量转换 - 扫描目录中的所有磁力链接文件")
    print("   🌐 Web 界面 - 可通过浏览器访问管理界面")
    print("   🔄 任务管理 - 完整的下载任务生命周期管理")
    print("   📊 实时监控 - 详细的下载进度和状态信息")
    print("   🛡️  权限控制 - 用户名密码认证")
    print("   🔧 远程管理 - 支持远程服务器部署")
    print("   📈 性能优化 - 丰富的性能调优选项")
    print()

def demo_command_examples():
    """演示命令行使用示例"""
    print("💻 命令行使用示例:")
    print()
    print("# 启动 qBittorrent 守护进程")
    print("python3 qbittorrent_magnet_converter.py --start-daemon")
    print()
    print("# 测试连接")
    print("python3 qbittorrent_magnet_converter.py --test-connection")
    print()
    print("# 转换单个磁力链接")
    print("python3 qbittorrent_magnet_converter.py --magnet 'magnet:?xt=urn:btih:...'")
    print()
    print("# 批量转换目录中的磁力链接文件")
    print("python3 qbittorrent_magnet_converter.py --scan-dir ./magnets --output-dir ./torrents")
    print()
    print("# 自定义连接参数")
    print("python3 qbittorrent_magnet_converter.py --host 192.168.1.100 --port 8080 --username admin --password mypass")
    print()
    print("# 停止 qBittorrent 守护进程")
    print("python3 qbittorrent_magnet_converter.py --stop-daemon")
    print()

def demo_web_interface():
    """演示 Web 界面"""
    print("🌐 Web 界面访问:")
    print("   启动 qBittorrent 后，可通过浏览器访问:")
    print("   📍 地址: http://localhost:8080")
    print("   👤 默认用户名: admin")
    print("   🔑 默认密码: adminadmin")
    print()
    print("   Web 界面功能:")
    print("     • 可视化任务管理")
    print("     • 实时下载统计")
    print("     • 种子详细信息")
    print("     • 设置和配置管理")
    print("     • 日志查看")
    print()

def demo_api_features():
    """演示 API 功能"""
    print("🔌 API 功能特性:")
    print("   📡 RESTful API - 标准的 HTTP API 接口")
    print("   🔐 认证机制 - 基于 Cookie 的会话管理")
    print("   📊 丰富接口 - 涵盖所有种子操作")
    print("   📈 实时数据 - 获取实时下载状态")
    print("   ⚙️  配置管理 - 动态修改客户端设置")
    print()
    print("   主要 API 端点:")
    print("     • /api/v2/auth/login - 登录认证")
    print("     • /api/v2/torrents/add - 添加种子")
    print("     • /api/v2/torrents/info - 获取种子信息")
    print("     • /api/v2/torrents/export - 导出种子文件")
    print("     • /api/v2/torrents/delete - 删除种子")
    print()

def demo_troubleshooting():
    """演示故障排除"""
    print("🔧 故障排除:")
    print()
    print("❓ 常见问题:")
    print("   Q: qbittorrent-nox 命令不存在")
    print("   A: 请安装 qBittorrent: brew install qbittorrent")
    print()
    print("   Q: Web UI 无法访问")
    print("   A: 检查端口是否被占用，防火墙设置")
    print()
    print("   Q: 登录失败")
    print("   A: 检查用户名密码，首次启动可能需要设置")
    print()
    print("   Q: 磁力链接添加失败")
    print("   A: 检查磁力链接格式，网络连接状态")
    print()
    print("   Q: 元数据下载慢")
    print("   A: 检查 DHT 设置，尝试添加更多 tracker")
    print()

def demo_configuration():
    """演示配置说明"""
    print("⚙️ 配置说明:")
    print("   📁 配置目录: ~/.config/qBittorrent/")
    print("   📄 主配置文件: qBittorrent.conf")
    print("   🌐 Web UI 设置可通过界面或 API 修改")
    print()
    print("   重要配置项:")
    print("     • WebUI\\Port - Web 界面端口")
    print("     • WebUI\\Username - 用户名")
    print("     • WebUI\\Password_PBKDF2 - 密码哈希")
    print("     • BitTorrent\\Session\\DefaultSavePath - 默认下载路径")
    print("     • BitTorrent\\Session\\MaxConnections - 最大连接数")
    print()

def main():
    """主演示函数"""
    print_banner()
    
    print("🎬 这是 qBittorrent 磁力链接转换方案的演示")
    print("   qBittorrent 是一个功能完整、稳定可靠的 BitTorrent 客户端")
    print("   它提供了强大的 Web API，非常适合自动化任务")
    print()
    
    print_advantages()
    print_vs_others()
    demo_installation()
    demo_basic_usage()
    demo_advanced_features()
    demo_command_examples()
    demo_web_interface()
    demo_api_features()
    demo_configuration()
    demo_troubleshooting()
    
    print("=" * 60)
    print("🎉 qBittorrent 方案演示完成!")
    print("💡 这是功能最完整、最稳定的磁力链接转换方案")
    print("🚀 开始使用: python3 qbittorrent_magnet_converter.py --help")
    print("🌐 Web 界面: http://localhost:8080 (启动后)")
    print("=" * 60)

if __name__ == "__main__":
    main()