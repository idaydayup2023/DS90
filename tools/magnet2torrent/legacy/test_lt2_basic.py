#!/usr/bin/env python3
"""
简单的libtorrent 2.x测试脚本
"""

import libtorrent as lt  # type: ignore
import time

def test_basic_session():
    """测试基本会话功能"""
    print("创建会话...")
    session = lt.session()
    
    print("获取设置...")
    settings = session.get_settings()
    print(f"DHT启用状态: {settings.get('enable_dht', False)}")
    
    print("启用DHT...")
    settings['enable_dht'] = True
    settings['enable_lsd'] = True
    session.apply_settings(settings)
    
    print("添加DHT路由器...")
    session.add_dht_router('router.bittorrent.com', 6881)
    
    print("等待DHT连接...")
    for i in range(10):
        status = session.status()
        dht_nodes = getattr(status, 'dht_nodes', 0)
        print(f"DHT节点数: {dht_nodes}")
        if dht_nodes > 0:
            print("✅ DHT连接成功!")
            break
        time.sleep(2)
    
    print("测试add_torrent_params...")
    params = lt.add_torrent_params()
    params.url = "magnet:?xt=urn:btih:dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c&dn=Big+Buck+Bunny"
    params.save_path = "/tmp"
    
    print("添加磁力链接...")
    try:
        handle = session.add_torrent(params)
        print("✅ 磁力链接添加成功!")
        
        print("检查状态...")
        for i in range(5):
            status = handle.status()
            print(f"状态: {status.state}, 进度: {status.progress * 100:.1f}%")
            if handle.has_metadata():
                print("✅ 获取到元数据!")
                break
            time.sleep(2)
        
        session.remove_torrent(handle)
        print("✅ 移除torrent成功!")
        
    except Exception as e:
        print(f"❌ 错误: {e}")

if __name__ == "__main__":
    test_basic_session()