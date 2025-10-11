#!/usr/bin/env python3
"""
DHT网络状态监控脚本
"""

import time
import sys
import os
import signal

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from magnet2torrent.dht_manager import get_global_dht_manager

def signal_handler(sig, frame):
    """处理中断信号"""
    print("\n\n收到中断信号，正在停止DHT网络...")
    dht_manager = get_global_dht_manager()
    dht_manager.stop()
    print("DHT网络已停止")
    sys.exit(0)

def monitor_dht():
    """监控DHT网络状态"""
    print("=== DHT网络监控器 ===")
    print("按 Ctrl+C 停止监控并关闭DHT网络")
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    
    # 获取DHT管理器
    dht_manager = get_global_dht_manager()
    
    # 启动DHT网络
    if not dht_manager.running:
        print("启动DHT网络...")
        if dht_manager.start():
            print("✓ DHT网络启动成功")
        else:
            print("✗ DHT网络启动失败")
            return
    else:
        print("DHT网络已在运行中")
    
    print(f"监听端口: {dht_manager.listen_port}")
    print("等待DHT网络连接到其他节点...")
    print("-" * 50)
    
    # 监控循环
    start_time = time.time()
    while True:
        try:
            # 获取运行时间
            runtime = int(time.time() - start_time)
            hours = runtime // 3600
            minutes = (runtime % 3600) // 60
            seconds = runtime % 60
            
            # 获取统计信息
            stats = dht_manager.get_stats()
            
            # 显示状态
            print(f"\r运行时间: {hours:02d}:{minutes:02d}:{seconds:02d} | "
                  f"DHT节点: {stats.get('dht_nodes', 0)} | "
                  f"全局节点: {stats.get('dht_global_nodes', 0)} | "
                  f"路由表: {stats.get('dht_routing_table_size', 0)}", 
                  end="", flush=True)
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            signal_handler(signal.SIGINT, None)
        except Exception as e:
            print(f"\n监控出错: {e}")
            break

def main():
    """主函数"""
    try:
        monitor_dht()
    except Exception as e:
        print(f"程序出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()