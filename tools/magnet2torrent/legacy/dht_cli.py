#!/usr/bin/env python3
"""
DHT网络命令行管理工具
"""

import sys
import os
import time
import argparse

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from magnet2torrent.dht_manager import get_global_dht_manager, start_global_dht, stop_global_dht

def cmd_start(args):
    """启动DHT网络"""
    print("启动DHT网络...")
    if start_global_dht():
        dht_manager = get_global_dht_manager()
        print(f"✓ DHT网络启动成功")
        print(f"  监听端口: {dht_manager.listen_port}")
        
        if args.wait:
            print(f"等待DHT网络就绪（{args.wait}秒）...")
            if dht_manager.wait_for_ready(args.wait):
                print("✓ DHT网络就绪")
            else:
                print("⚠ DHT网络未完全就绪，但可以使用")
    else:
        print("✗ DHT网络启动失败")
        return 1
    
    return 0

def cmd_stop(args):
    """停止DHT网络"""
    print("停止DHT网络...")
    stop_global_dht()
    print("✓ DHT网络已停止")
    return 0

def cmd_status(args):
    """显示DHT网络状态"""
    dht_manager = get_global_dht_manager()
    
    print("DHT网络状态:")
    print(f"  运行状态: {'运行中' if dht_manager.running else '已停止'}")
    
    if dht_manager.running:
        print(f"  监听端口: {dht_manager.listen_port}")
        
        # 获取统计信息
        stats = dht_manager.get_stats()
        print(f"  DHT节点: {stats.get('dht_nodes', 0)}")
        print(f"  全局节点: {stats.get('dht_global_nodes', 0)}")
        print(f"  路由表大小: {stats.get('dht_routing_table_size', 0)}")
    
    return 0

def cmd_monitor(args):
    """监控DHT网络状态"""
    print("DHT网络监控（按Ctrl+C停止）")
    print("-" * 40)
    
    dht_manager = get_global_dht_manager()
    
    if not dht_manager.running:
        print("DHT网络未运行，正在启动...")
        if not start_global_dht():
            print("✗ DHT网络启动失败")
            return 1
    
    try:
        start_time = time.time()
        while True:
            # 计算运行时间
            runtime = int(time.time() - start_time)
            hours = runtime // 3600
            minutes = (runtime % 3600) // 60
            seconds = runtime % 60
            
            # 获取统计信息
            stats = dht_manager.get_stats()
            
            # 显示状态
            print(f"\r时间: {hours:02d}:{minutes:02d}:{seconds:02d} | "
                  f"DHT节点: {stats.get('dht_nodes', 0):4d} | "
                  f"全局节点: {stats.get('dht_global_nodes', 0):6d} | "
                  f"路由表: {stats.get('dht_routing_table_size', 0):4d}", 
                  end="", flush=True)
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n监控已停止")
        if args.stop_on_exit:
            print("停止DHT网络...")
            stop_global_dht()
    
    return 0

def cmd_test(args):
    """测试DHT网络功能"""
    from magnet2torrent.converter import Magnet2TorrentConverter
    
    print("测试DHT网络功能...")
    
    # 启动DHT
    if not start_global_dht():
        print("✗ DHT网络启动失败")
        return 1
    
    print("✓ DHT网络启动成功")
    
    # 等待连接
    dht_manager = get_global_dht_manager()
    print("等待DHT网络连接...")
    dht_manager.wait_for_ready(10)
    
    # 测试磁力链接解析
    print("测试磁力链接解析...")
    converter = Magnet2TorrentConverter(use_shared_dht=True)
    
    test_magnet = args.magnet or "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
    
    try:
        info = converter.parse_magnet_info(test_magnet)
        print(f"✓ 解析成功:")
        print(f"  Info Hash: {info['info_hash']}")
        print(f"  文件名: {info['name']}")
        print(f"  Tracker数量: {len(info['trackers'])}")
        
        if args.convert:
            print("尝试转换...")
            result = converter.convert(test_magnet, ".")
            if result:
                print(f"✓ 转换成功: {result}")
            else:
                print("⚠ 转换超时")
        
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return 1
    
    # 显示最终统计
    stats = dht_manager.get_stats()
    print(f"DHT统计: 节点={stats.get('dht_nodes', 0)}, 全局={stats.get('dht_global_nodes', 0)}")
    
    if not args.keep_running:
        print("停止DHT网络...")
        stop_global_dht()
    
    return 0

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="DHT网络管理工具")
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # start命令
    start_parser = subparsers.add_parser('start', help='启动DHT网络')
    start_parser.add_argument('--wait', type=int, default=0, 
                             help='等待DHT就绪的时间（秒）')
    
    # stop命令
    subparsers.add_parser('stop', help='停止DHT网络')
    
    # status命令
    subparsers.add_parser('status', help='显示DHT网络状态')
    
    # monitor命令
    monitor_parser = subparsers.add_parser('monitor', help='监控DHT网络状态')
    monitor_parser.add_argument('--interval', type=int, default=1,
                               help='监控间隔（秒）')
    monitor_parser.add_argument('--stop-on-exit', action='store_true',
                               help='退出时停止DHT网络')
    
    # test命令
    test_parser = subparsers.add_parser('test', help='测试DHT网络功能')
    test_parser.add_argument('--magnet', help='测试用的磁力链接')
    test_parser.add_argument('--convert', action='store_true',
                            help='尝试转换磁力链接')
    test_parser.add_argument('--keep-running', action='store_true',
                            help='测试后保持DHT运行')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # 执行命令
    commands = {
        'start': cmd_start,
        'stop': cmd_stop,
        'status': cmd_status,
        'monitor': cmd_monitor,
        'test': cmd_test
    }
    
    try:
        return commands[args.command](args)
    except KeyboardInterrupt:
        print("\n操作被中断")
        return 1
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())