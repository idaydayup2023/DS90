#!/usr/bin/env python3
"""
测试DHT网络连通后的磁力链接转换功能
确保DHT网络完全就绪后再开始转换，提高成功率
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'magnet2torrent'))

from magnet2torrent.converter import Magnet2TorrentConverter
from magnet2torrent.dht_manager import DHTManager

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DHTReadinessChecker:
    """DHT网络就绪状态检查器"""
    
    def __init__(self, dht_manager):
        self.dht_manager = dht_manager
        self.is_monitoring = False
        self.monitor_thread = None
        
    def check_dht_connectivity(self, timeout=120):
        """检查DHT网络连通性
        
        Args:
            timeout (int): 超时时间（秒）
            
        Returns:
            bool: DHT网络是否就绪
        """
        print(f"🔍 开始检查DHT网络连通性（超时: {timeout}秒）...")
        
        start_time = time.time()
        last_node_count = 0
        stable_count = 0
        required_stable_checks = 3  # 需要连续3次检查都稳定
        
        while time.time() - start_time < timeout:
            try:
                # 使用DHT管理器的内置就绪检查方法
                if self.dht_manager.is_ready():
                    elapsed = time.time() - start_time
                    print(f"✅ DHT网络就绪！用时: {elapsed:.1f}秒")
                    return True
                
                # 获取详细统计信息
                stats = self.dht_manager.get_stats()
                current_nodes = stats.get('dht_nodes', 0)
                
                elapsed = time.time() - start_time
                print(f"⏱️  [{elapsed:6.1f}s] DHT节点数: {current_nodes:4d} | "
                      f"状态: {'运行中' if self.dht_manager.running else '已停止'}")
                
                # 检查节点数是否稳定增长
                if current_nodes > 0:
                    if current_nodes >= last_node_count:
                        stable_count += 1
                    else:
                        stable_count = 0
                    
                    # 如果节点数达到一定数量且稳定，认为网络就绪
                    if current_nodes >= 10 and stable_count >= required_stable_checks:
                        print(f"✅ DHT网络就绪！节点数: {current_nodes}")
                        return True
                        
                last_node_count = current_nodes
                time.sleep(5)  # 每5秒检查一次
                
            except Exception as e:
                print(f"❌ 获取DHT统计信息失败: {e}")
                time.sleep(2)
        
        print(f"⏰ DHT网络连通检查超时（{timeout}秒）")
        return False
    
    def wait_for_peers(self, info_hash, min_peers=1, timeout=60):
        """等待指定文件的peer出现
        
        Args:
            info_hash (str): 文件的info hash
            min_peers (int): 最少peer数量
            timeout (int): 超时时间
            
        Returns:
            bool: 是否找到足够的peer
        """
        print(f"🔍 等待文件 {info_hash[:8]}... 的peer（最少{min_peers}个）...")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                # 这里可以添加具体的peer查找逻辑
                # 由于libtorrent API的限制，我们主要依赖DHT网络状态
                elapsed = time.time() - start_time
                print(f"⏱️  [{elapsed:6.1f}s] 搜索peer中...")
                
                time.sleep(3)
                
            except Exception as e:
                print(f"❌ 搜索peer失败: {e}")
                time.sleep(2)
        
        print(f"⏰ Peer搜索超时（{timeout}秒）")
        return False

def test_dht_ready_conversion():
    """测试DHT网络就绪后的转换功能"""
    
    print("=" * 80)
    print("DHT网络就绪后的磁力链接转换测试")
    print("=" * 80)
    
    # 测试磁力链接
    magnet_uri = "magnet:?xt=urn:btih:1081822F880149A0AD32C221F47284D907D75991&dn=The.Walking.Dead.Daryl.Dixon.S03E03.1080p.x265-ELiTE&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce"
    
    print(f"📋 测试磁力链接: {magnet_uri[:60]}...")
    
    # 创建输出目录
    output_dir = "test_output_dht_ready"
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. 启动DHT网络
    print("\n🚀 第1步: 启动DHT网络")
    print("-" * 50)
    
    dht_manager = None
    try:
        dht_manager = DHTManager(verbose=True)
        
        if not dht_manager.start():
            print("❌ DHT网络启动失败")
            return False
            
        print("✅ DHT网络启动成功")
        
    except Exception as e:
        print(f"❌ DHT网络启动异常: {e}")
        return False
    
    # 2. 等待DHT网络就绪
    print("\n⏳ 第2步: 等待DHT网络就绪")
    print("-" * 50)
    
    try:
        checker = DHTReadinessChecker(dht_manager)
        
        if not checker.check_dht_connectivity(timeout=180):  # 3分钟超时
            print("❌ DHT网络未能在规定时间内就绪")
            if dht_manager:
                dht_manager.stop()
            return False
            
        print("✅ DHT网络已就绪")
        
    except Exception as e:
        print(f"❌ DHT网络就绪检查异常: {e}")
        if dht_manager:
            dht_manager.stop()
        return False
    
    # 3. 解析磁力链接
    print("\n🔍 第3步: 解析磁力链接")
    print("-" * 50)
    
    try:
        converter = Magnet2TorrentConverter(timeout=120, use_shared_dht=True, verbose=True)
        magnet_info = converter.parse_magnet_info(magnet_uri)
        
        print("✅ 磁力链接解析成功:")
        print(f"   - Info Hash: {magnet_info.get('info_hash', 'N/A')}")
        print(f"   - 文件名: {magnet_info.get('name', 'N/A')}")
        print(f"   - Tracker数量: {len(magnet_info.get('trackers', []))}")
        
    except Exception as e:
        print(f"❌ 磁力链接解析失败: {e}")
        if dht_manager:
            dht_manager.stop()
        return False
    
    # 4. 开始转换
    print("\n🔄 第4步: 开始转换（DHT网络已就绪）")
    print("-" * 50)
    
    conversion_success = False
    try:
        print("📡 使用已就绪的DHT网络进行转换...")
        start_time = time.time()
        
        result = converter.convert(magnet_uri, output_dir)
        
        if result:
            elapsed = time.time() - start_time
            print(f"✅ 转换成功！用时: {elapsed:.1f}秒")
            print(f"📁 输出文件: {result}")
            
            if os.path.exists(result):
                file_size = os.path.getsize(result)
                print(f"📊 文件大小: {file_size} bytes")
                conversion_success = True
            else:
                print("❌ 输出文件不存在")
        else:
            print("❌ 转换失败（返回None）")
            
    except Exception as e:
        print(f"❌ 转换过程异常: {e}")
    
    # 5. 清理资源
    print("\n🧹 第5步: 清理资源")
    print("-" * 50)
    
    try:
        if dht_manager:
            dht_manager.stop()
            print("✅ DHT网络已停止")
    except Exception as e:
        print(f"❌ 停止DHT网络异常: {e}")
    
    # 6. 检查输出文件
    print("\n📋 第6步: 检查输出结果")
    print("-" * 50)
    
    if os.path.exists(output_dir):
        files = os.listdir(output_dir)
        if files:
            print(f"✅ 输出目录包含 {len(files)} 个文件:")
            for file in files:
                file_path = os.path.join(output_dir, file)
                if os.path.isfile(file_path):
                    size = os.path.getsize(file_path)
                    print(f"   📄 {file} ({size} bytes)")
        else:
            print("❌ 输出目录为空")
    else:
        print("❌ 输出目录不存在")
    
    # 7. 总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    
    if conversion_success:
        print("🎉 测试成功！DHT网络就绪后的转换功能正常工作")
        print("💡 关键成功因素:")
        print("   ✅ DHT网络完全启动并连接到足够的节点")
        print("   ✅ 等待网络稳定后再开始转换")
        print("   ✅ 使用较长的超时时间")
    else:
        print("😞 测试未完全成功，但这可能由于以下原因:")
        print("   🌐 网络环境限制（防火墙、NAT等）")
        print("   👥 该文件的peer数量不足")
        print("   ⏰ 需要更长的等待时间")
        print("   🔧 可能需要调整DHT配置")
    
    return conversion_success

def run_multiple_attempts():
    """运行多次尝试，提高成功率"""
    
    print("\n" + "=" * 80)
    print("多次尝试测试")
    print("=" * 80)
    
    max_attempts = 3
    success_count = 0
    
    for attempt in range(1, max_attempts + 1):
        print(f"\n🔄 第 {attempt}/{max_attempts} 次尝试")
        print("=" * 40)
        
        if test_dht_ready_conversion():
            success_count += 1
            print(f"✅ 第 {attempt} 次尝试成功！")
            break
        else:
            print(f"❌ 第 {attempt} 次尝试失败")
            if attempt < max_attempts:
                print("⏳ 等待30秒后重试...")
                time.sleep(30)
    
    print(f"\n📊 总结: {success_count}/{max_attempts} 次成功")
    
    if success_count > 0:
        print("🎉 至少有一次转换成功，说明方法可行！")
    else:
        print("😞 所有尝试都失败了，可能需要:")
        print("   - 检查网络连接")
        print("   - 尝试不同的磁力链接")
        print("   - 调整DHT配置参数")

if __name__ == "__main__":
    # 运行单次测试
    test_dht_ready_conversion()
    
    # 可选：运行多次尝试
    # run_multiple_attempts()