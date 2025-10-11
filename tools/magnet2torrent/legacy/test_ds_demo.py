#!/usr/bin/env python3
"""
Download Station 功能演示脚本
用于展示如何使用 Download Station API 添加磁力链接
"""

import json
from synology_download_station import SynologyDownloadStation

def demo_download_station():
    """演示 Download Station 功能"""
    print("🎯 Synology Download Station 磁力链接管理器演示")
    print("=" * 60)
    
    # 演示配置 (请根据实际情况修改)
    demo_config = {
        "host": "192.168.1.100",  # 请修改为你的 NAS IP
        "port": 5000,
        "username": "demo_user",   # 请修改为你的用户名
        "password": "demo_pass",   # 请修改为你的密码
        "use_https": False
    }
    
    print("📋 演示配置:")
    print(f"   主机: {demo_config['host']}:{demo_config['port']}")
    print(f"   用户: {demo_config['username']}")
    print(f"   HTTPS: {demo_config['use_https']}")
    print()
    
    # 创建客户端
    print("🔧 创建 Download Station 客户端...")
    ds = SynologyDownloadStation(
        host=demo_config["host"],
        port=demo_config["port"],
        username=demo_config["username"],
        password=demo_config["password"],
        use_https=demo_config["use_https"]
    )
    
    # 演示连接流程
    print("🌐 测试 API 连接...")
    if not ds.get_api_info():
        print("❌ 无法获取 API 信息")
        print("💡 请检查:")
        print("   - NAS IP 地址是否正确")
        print("   - 网络连接是否正常")
        print("   - Download Station 是否已启用")
        return False
    
    print("✅ API 信息获取成功")
    
    print("🔐 测试登录...")
    if not ds.login():
        print("❌ 登录失败")
        print("💡 请检查:")
        print("   - 用户名和密码是否正确")
        print("   - 用户是否有 Download Station 权限")
        return False
    
    print("✅ 登录成功")
    
    # 演示功能
    try:
        # 获取当前任务列表
        print("\n📋 获取当前下载任务...")
        tasks = ds.get_task_list()
        print(f"✅ 当前有 {len(tasks)} 个下载任务")
        
        if tasks:
            print("\n当前任务列表:")
            for i, task in enumerate(tasks[:3], 1):  # 只显示前3个
                title = task.get('title', 'Unknown')
                status = task.get('status', 'unknown')
                print(f"  {i}. {title} [{status}]")
            if len(tasks) > 3:
                print(f"  ... 还有 {len(tasks) - 3} 个任务")
        
        # 演示添加磁力链接 (使用测试链接)
        print("\n🧲 演示添加磁力链接...")
        test_magnet = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
        print(f"测试磁力链接: {test_magnet[:50]}...")
        
        # 注意: 这里只是演示，不会真正添加
        print("💡 (演示模式 - 不会真正添加任务)")
        # task_id = ds.add_magnet_task(test_magnet)
        # if task_id:
        #     print(f"✅ 任务添加成功，ID: {task_id}")
        
    except Exception as e:
        print(f"❌ 演示过程中出错: {e}")
    
    finally:
        # 登出
        print("\n🚪 登出...")
        ds.logout()
        print("✅ 演示完成")
    
    return True

def show_usage_examples():
    """显示使用示例"""
    print("\n" + "=" * 60)
    print("📚 使用示例")
    print("=" * 60)
    
    examples = [
        {
            "title": "1. 配置文件设置",
            "code": """# 复制配置模板
cp ds_config.json.example ds_config.json

# 编辑配置文件
{
  "host": "192.168.1.100",
  "username": "your_username",
  "password": "your_password",
  ...
}"""
        },
        {
            "title": "2. 测试连接",
            "code": "python3 synology_magnet_manager.py test"
        },
        {
            "title": "3. 扫描并添加磁力链接",
            "code": "python3 synology_magnet_manager.py scan"
        },
        {
            "title": "4. 查看下载任务",
            "code": """# 简单列表
python3 synology_magnet_manager.py list

# 详细信息
python3 synology_magnet_manager.py list --detailed"""
        },
        {
            "title": "5. 添加单个磁力链接",
            "code": 'python3 synology_magnet_manager.py add "magnet:?xt=urn:btih:..."'
        },
        {
            "title": "6. 自动监控模式",
            "code": "python3 synology_magnet_manager.py monitor"
        }
    ]
    
    for example in examples:
        print(f"\n{example['title']}:")
        print("-" * 40)
        print(example['code'])

def show_advantages():
    """显示方案优势"""
    print("\n" + "=" * 60)
    print("🎯 方案优势")
    print("=" * 60)
    
    advantages = [
        "✅ 直接调用 Download Station API，无需转换",
        "✅ 完全兼容 VPN 环境",
        "✅ 即时添加，无需等待元数据下载",
        "✅ 高成功率，不依赖外部 tracker",
        "✅ 低资源占用，无额外依赖",
        "✅ 支持批量管理和自动监控",
        "✅ 详细的状态监控和错误处理"
    ]
    
    for advantage in advantages:
        print(f"  {advantage}")
    
    print("\n📊 对比 libtorrent 方案:")
    print("  - 网络依赖: 仅需 NAS 连接 vs 需要 DHT/Tracker")
    print("  - VPN 兼容: 完全兼容 vs 可能受限")
    print("  - 处理速度: 即时 vs 需要元数据下载")
    print("  - 成功率: 高 vs 依赖网络环境")

if __name__ == "__main__":
    print("🚀 启动 Download Station 演示...")
    
    # 显示使用示例
    show_usage_examples()
    
    # 显示方案优势
    show_advantages()
    
    # 运行演示
    print("\n" + "=" * 60)
    print("🎬 功能演示")
    print("=" * 60)
    print("💡 注意: 请先修改演示脚本中的 NAS 连接信息")
    print("💡 或者直接使用配置文件方式运行管理器")
    
    # demo_download_station()  # 取消注释以运行实际演示
    
    print("\n🎉 演示脚本准备完成!")
    print("💡 要运行实际演示，请:")
    print("   1. 修改脚本中的 demo_config")
    print("   2. 取消注释 demo_download_station() 调用")
    print("   3. 重新运行脚本")