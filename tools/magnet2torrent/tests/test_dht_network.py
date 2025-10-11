#!/usr/bin/env python3
"""
测试DHT网络功能
"""

import time
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from magnet2torrent.dht_manager import get_global_dht_manager
from magnet2torrent.converter import Magnet2TorrentConverter

def test_dht_network():
    """测试DHT网络启动和连接"""
    print("=== 测试DHT网络功能 ===")
    
    # 获取DHT管理器
    dht_manager = get_global_dht_manager()
    
    print(f"DHT管理器状态: {'运行中' if dht_manager.running else '未运行'}")
    
    # 启动DHT网络
    print("启动DHT网络...")
    if dht_manager.start():
        print("✓ DHT网络启动成功")
    else:
        print("✗ DHT网络启动失败")
        return False
    
    # 等待DHT就绪
    print("等待DHT网络就绪...")
    if dht_manager.wait_for_ready(30):
        print("✓ DHT网络就绪")
    else:
        print("⚠ DHT网络未完全就绪，但可以继续")
    
    # 显示DHT统计信息
    stats = dht_manager.get_stats()
    print(f"DHT统计信息:")
    print(f"  - 节点数: {stats.get('dht_nodes', 0)}")
    print(f"  - 全局节点数: {stats.get('dht_global_nodes', 0)}")
    print(f"  - 路由表大小: {stats.get('dht_routing_table_size', 0)}")
    
    return True

def test_shared_dht_conversion():
    """测试使用共享DHT进行转换"""
    print("\n=== 测试共享DHT转换功能 ===")
    
    # 使用共享DHT的转换器
    converter = Magnet2TorrentConverter(timeout=30, verbose=True, use_shared_dht=True)
    
    # 测试磁力链接
    magnet_uri = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
    
    print(f"测试磁力链接: {magnet_uri}")
    
    try:
        # 解析磁力链接
        info = converter.parse_magnet_info(magnet_uri)
        print(f"✓ 磁力链接解析成功:")
        print(f"  - Info Hash: {info['info_hash']}")
        print(f"  - 文件名: {info.get('name', '未知')}")
        print(f"  - Tracker数量: {len(info.get('trackers', []))}")
        
        # 尝试转换（可能会超时，这是正常的）
        print("尝试转换为torrent文件...")
        result = converter.convert(magnet_uri, ".")
        
        if result:
            print(f"✓ 转换成功: {result}")
        else:
            print("⚠ 转换超时（这在网络环境限制下是正常的）")
            
    except Exception as e:
        print(f"✗ 转换过程出错: {e}")
    
    return True

def test_multiple_conversions():
    """测试多个转换共享同一个DHT网络"""
    print("\n=== 测试多个转换共享DHT ===")
    
    magnet_uris = [
        "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a",
        "magnet:?xt=urn:btih:1234567890abcdef1234567890abcdef12345678"
    ]
    
    for i, magnet_uri in enumerate(magnet_uris, 1):
        print(f"\n转换 {i}: {magnet_uri}")
        
        # 每个转换器都使用共享DHT
        converter = Magnet2TorrentConverter(timeout=10, verbose=False, use_shared_dht=True)
        
        try:
            info = converter.parse_magnet_info(magnet_uri)
            print(f"  ✓ 解析成功: {info['info_hash']}")
        except Exception as e:
            print(f"  ✗ 解析失败: {e}")

def main():
    """主函数"""
    try:
        # 测试DHT网络
        if not test_dht_network():
            return
        
        # 测试共享DHT转换
        test_shared_dht_conversion()
        
        # 测试多个转换
        test_multiple_conversions()
        
        # 显示最终统计
        print("\n=== 最终DHT统计 ===")
        dht_manager = get_global_dht_manager()
        stats = dht_manager.get_stats()
        print(f"节点数: {stats.get('dht_nodes', 0)}")
        print(f"全局节点数: {stats.get('dht_global_nodes', 0)}")
        
        # 保持DHT运行一段时间
        print("\n保持DHT网络运行30秒...")
        for i in range(30):
            time.sleep(1)
            if i % 10 == 9:
                stats = dht_manager.get_stats()
                print(f"  {i+1}s - 节点数: {stats.get('dht_nodes', 0)}")
        
        print("\n测试完成！DHT网络将继续运行...")
        print("可以使用 dht_manager.stop() 停止DHT网络")
        
    except KeyboardInterrupt:
        print("\n\n用户中断测试")
    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 可以选择是否停止DHT
        # dht_manager = get_global_dht_manager()
        # dht_manager.stop()
        pass

if __name__ == "__main__":
    main()