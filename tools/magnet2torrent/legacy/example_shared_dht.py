#!/usr/bin/env python3
"""
共享DHT网络使用示例
"""

import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from magnet2torrent.dht_manager import get_global_dht_manager, start_global_dht, stop_global_dht
from magnet2torrent.converter import Magnet2TorrentConverter

def example_basic_usage():
    """基本使用示例"""
    print("=== 基本DHT使用示例 ===")
    
    # 启动全局DHT网络
    print("1. 启动全局DHT网络...")
    if start_global_dht():
        print("   ✓ DHT网络启动成功")
    else:
        print("   ✗ DHT网络启动失败")
        return
    
    # 获取DHT管理器
    dht_manager = get_global_dht_manager()
    print(f"   监听端口: {dht_manager.listen_port}")
    
    # 等待一段时间让DHT连接
    print("2. 等待DHT网络连接...")
    for i in range(10):
        stats = dht_manager.get_stats()
        print(f"   {i+1}s - DHT节点: {stats.get('dht_nodes', 0)}")
        time.sleep(1)
    
    # 使用共享DHT进行转换
    print("3. 使用共享DHT转换磁力链接...")
    converter = Magnet2TorrentConverter(timeout=15, verbose=True, use_shared_dht=True)
    
    # 测试磁力链接
    magnet_uri = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
    
    try:
        # 解析磁力链接信息
        info = converter.parse_magnet_info(magnet_uri)
        print(f"   磁力链接信息:")
        print(f"   - Info Hash: {info['info_hash']}")
        print(f"   - 文件名: {info['name']}")
        print(f"   - Tracker数量: {len(info['trackers'])}")
        
        # 尝试转换
        print("   尝试转换...")
        result = converter.convert(magnet_uri, ".")
        if result:
            print(f"   ✓ 转换成功: {result}")
        else:
            print("   ⚠ 转换超时（网络环境限制）")
            
    except Exception as e:
        print(f"   ✗ 转换失败: {e}")
    
    # 显示最终统计
    print("4. 最终DHT统计:")
    stats = dht_manager.get_stats()
    print(f"   - DHT节点: {stats.get('dht_nodes', 0)}")
    print(f"   - 全局节点: {stats.get('dht_global_nodes', 0)}")
    
    # 停止DHT网络
    print("5. 停止DHT网络...")
    stop_global_dht()
    print("   ✓ DHT网络已停止")

def example_multiple_conversions():
    """多个转换共享DHT示例"""
    print("\n=== 多个转换共享DHT示例 ===")
    
    # 启动DHT
    print("1. 启动DHT网络...")
    start_global_dht()
    
    # 多个磁力链接
    magnet_uris = [
        "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a",
        "magnet:?xt=urn:btih:1234567890abcdef1234567890abcdef12345678",
        "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
    ]
    
    print("2. 批量解析磁力链接...")
    for i, magnet_uri in enumerate(magnet_uris, 1):
        print(f"   转换 {i}:")
        
        # 每个转换器都使用共享DHT
        converter = Magnet2TorrentConverter(timeout=5, verbose=False, use_shared_dht=True)
        
        try:
            info = converter.parse_magnet_info(magnet_uri)
            print(f"     ✓ Info Hash: {info['info_hash']}")
        except Exception as e:
            print(f"     ✗ 解析失败: {e}")
    
    # 显示DHT状态
    print("3. DHT网络状态:")
    dht_manager = get_global_dht_manager()
    stats = dht_manager.get_stats()
    print(f"   - 运行状态: {'运行中' if dht_manager.running else '已停止'}")
    print(f"   - DHT节点: {stats.get('dht_nodes', 0)}")
    
    # 停止DHT
    print("4. 停止DHT网络...")
    stop_global_dht()

def example_persistent_dht():
    """持久化DHT示例"""
    print("\n=== 持久化DHT示例 ===")
    
    # 启动DHT并保存状态
    print("1. 启动DHT并保存状态...")
    dht_manager = get_global_dht_manager()
    
    if dht_manager.start():
        print("   ✓ DHT启动成功")
        
        # 等待一段时间积累节点
        print("2. 等待积累DHT节点...")
        time.sleep(10)
        
        # 保存DHT状态
        if dht_manager.save_state():
            print("   ✓ DHT状态已保存")
        else:
            print("   ⚠ DHT状态保存失败")
        
        # 显示统计
        stats = dht_manager.get_stats()
        print(f"   当前节点数: {stats.get('dht_nodes', 0)}")
        
        # 停止并重启
        print("3. 停止并重启DHT...")
        dht_manager.stop()
        time.sleep(2)
        
        if dht_manager.start():
            print("   ✓ DHT重启成功")
            time.sleep(5)
            
            stats = dht_manager.get_stats()
            print(f"   重启后节点数: {stats.get('dht_nodes', 0)}")
        
        dht_manager.stop()
    else:
        print("   ✗ DHT启动失败")

def main():
    """主函数"""
    print("DHT网络使用示例")
    print("=" * 50)
    
    try:
        # 基本使用
        example_basic_usage()
        
        # 多个转换
        example_multiple_conversions()
        
        # 持久化DHT
        example_persistent_dht()
        
        print("\n所有示例完成！")
        
    except KeyboardInterrupt:
        print("\n\n用户中断")
        stop_global_dht()
    except Exception as e:
        print(f"\n示例出错: {e}")
        import traceback
        traceback.print_exc()
        stop_global_dht()

if __name__ == "__main__":
    main()