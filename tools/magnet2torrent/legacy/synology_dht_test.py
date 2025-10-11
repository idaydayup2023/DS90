#!/usr/bin/env python3
"""
群晖NAS系统DHT网络测试脚本
专门为群晖DSM系统设计，考虑与Download Station的兼容性
"""

import os
import sys
import time
import socket
import platform
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'magnet2torrent'))

# 尝试导入libtorrent
try:
    import libtorrent as lt  # type: ignore[import]
    LIBTORRENT_AVAILABLE = True
except ImportError:
    LIBTORRENT_AVAILABLE = False
    print("❌ libtorrent库未安装，请运行: pip install libtorrent")
    lt = None  # type: ignore[assignment]

# 初始化变量
MAGNET2TORRENT_AVAILABLE = False
DHTManager = None  # type: ignore[assignment]
Magnet2TorrentConverter = None  # type: ignore[assignment]

# 尝试导入magnet2torrent模块
try:
    from magnet2torrent.converter import Magnet2TorrentConverter  # type: ignore[import,misc]
    from magnet2torrent.dht_manager import DHTManager  # type: ignore[import,misc]
    MAGNET2TORRENT_AVAILABLE = True
except ImportError as e:
    print(f"❌ 导入magnet2torrent失败: {e}")
    MAGNET2TORRENT_AVAILABLE = False
    
    # 定义占位符类
    class DHTManager:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            return False
        def stop(self):
            pass
        def is_ready(self):
            return False
        def get_stats(self):
            return {}
    
    class Magnet2TorrentConverter:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass
        def parse_magnet_info(self, magnet_uri):
            return {}
        def convert(self, magnet_uri, output_dir):
            return None

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/synology_dht_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SynologyEnvironmentChecker:
    """群晖环境检测器"""
    
    def __init__(self):
        self.is_synology = self._detect_synology()
        self.system_info = self._get_system_info()
        
    def _detect_synology(self) -> bool:
        """检测是否为群晖系统"""
        try:
            # 检查特征文件
            synology_files = [
                '/etc/synoinfo.conf',
                '/usr/syno/etc/synoinfo.conf',
                '/etc.defaults/synoinfo.conf'
            ]
            
            for file_path in synology_files:
                if os.path.exists(file_path):
                    return True
            
            # 检查系统信息
            if 'synology' in platform.platform().lower():
                return True
                
            return False
        except:
            return False
    
    def _get_system_info(self) -> dict:
        """获取系统信息"""
        info = {
            'platform': platform.platform(),
            'architecture': platform.architecture(),
            'python_version': platform.python_version(),
            'is_synology': self.is_synology
        }
        
        if self.is_synology:
            try:
                # 尝试获取DSM版本
                result = subprocess.run(['cat', '/etc.defaults/VERSION'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    info['dsm_version'] = result.stdout.strip()
            except:
                pass
        
        return info
    
    def check_environment(self) -> dict:
        """全面环境检查"""
        print("🔍 群晖NAS环境检测")
        print("=" * 50)
        
        results = {
            'system_compatible': True,
            'python_available': True,
            'libtorrent_available': False,
            'ports_available': [],
            'download_station_running': False,
            'network_accessible': True,
            'recommendations': []
        }
        
        # 1. 系统兼容性检查
        print(f"📱 系统平台: {self.system_info['platform']}")
        print(f"🏗️  系统架构: {self.system_info['architecture']}")
        print(f"🐍 Python版本: {self.system_info['python_version']}")
        
        if self.is_synology:
            print("✅ 检测到群晖系统")
            if 'dsm_version' in self.system_info:
                print(f"📦 DSM版本: {self.system_info['dsm_version']}")
        else:
            print("⚠️  未检测到群晖系统（可能在其他Linux系统上运行）")
        
        # 2. Python环境检查
        try:
            import libtorrent
            print("✅ libtorrent库可用")
            results['libtorrent_available'] = True
        except ImportError:
            print("❌ libtorrent库不可用")
            results['recommendations'].append("安装libtorrent: pip3 install libtorrent")
        
        # 检查libtorrent可用性
        if not LIBTORRENT_AVAILABLE or lt is None:
            print("❌ libtorrent库不可用")
            return results
        
        try:
            # 创建libtorrent会话进行测试
            settings = lt.settings_pack()  # type: ignore[attr-defined]
            settings.set_bool(lt.settings_pack.enable_dht, True)  # type: ignore[attr-defined]
            settings.set_int(lt.settings_pack.dht_bootstrap_timeout, 30)  # type: ignore[attr-defined]
            
            session = lt.session(settings)  # type: ignore[attr-defined]
            session.listen_on(6881, 6890)  # type: ignore[attr-defined]
            
            # 等待一小段时间
            time.sleep(2)
            
            # 检查DHT状态
            stats = session.status()  # type: ignore[attr-defined]
            dht_nodes = stats.dht_nodes if hasattr(stats, 'dht_nodes') else 0  # type: ignore[attr-defined]
            
            print(f"✅ libtorrent DHT测试成功，节点数: {dht_nodes}")
            
        except Exception as e:
            print(f"❌ libtorrent DHT测试失败: {e}")
        
        # 3. 端口可用性检查
        print("\n🔌 端口可用性检查:")
        test_ports = [6881, 6882, 6883, 6884, 6885]
        for port in test_ports:
            if self._is_port_available(port):
                print(f"✅ 端口 {port} 可用")
                results['ports_available'].append(port)
            else:
                print(f"❌ 端口 {port} 被占用")
        
        # 4. Download Station检查
        print("\n📥 Download Station状态检查:")
        if self._check_download_station():
            print("✅ 检测到Download Station正在运行")
            results['download_station_running'] = True
            results['recommendations'].append("建议使用6882端口避免与Download Station冲突")
        else:
            print("ℹ️  未检测到Download Station运行")
        
        # 5. 网络连接检查
        print("\n🌐 网络连接检查:")
        if self._check_network_connectivity():
            print("✅ 网络连接正常")
        else:
            print("❌ 网络连接异常")
            results['network_accessible'] = False
            results['recommendations'].append("检查网络连接和防火墙设置")
        
        return results
    
    def _is_port_available(self, port: int) -> bool:
        """检查端口是否可用"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return True
        except OSError:
            return False
    
    def _check_download_station(self) -> bool:
        """检查Download Station是否运行"""
        try:
            # 检查进程
            result = subprocess.run(['pgrep', '-f', 'download'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                return True
            
            # 检查端口6881
            result = subprocess.run(['netstat', '-tulpn'], 
                                  capture_output=True, text=True)
            if ':6881' in result.stdout:
                return True
                
            return False
        except:
            return False
    
    def _check_network_connectivity(self) -> bool:
        """检查网络连接"""
        try:
            # 尝试连接DHT引导节点
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect(('router.bittorrent.com', 6881))
                return True
        except:
            return False

class SynologyDHTManager:
    """群晖专用DHT管理器"""
    
    def __init__(self, preferred_port=6882):
        self.preferred_port = preferred_port
        self.env_checker = SynologyEnvironmentChecker()
        self.dht_manager = None
        
    def find_optimal_port(self) -> int:
        """找到最佳可用端口"""
        # 优先使用6882（避开Download Station的6881）
        test_ports = [6882, 6883, 6884, 6885, 6886]
        
        for port in test_ports:
            if self.env_checker._is_port_available(port):
                print(f"✅ 选择端口: {port}")
                return port
        
        print("⚠️  所有推荐端口都被占用，使用默认端口6882")
        return 6882
    
    def start_dht_network(self) -> bool:
        """启动DHT网络"""
        if not MAGNET2TORRENT_AVAILABLE:
            print("❌ magnet2torrent库不可用")
            return False
        
        try:
            optimal_port = self.find_optimal_port()
            
            print(f"🚀 启动DHT网络（端口: {optimal_port}）...")
            self.dht_manager = DHTManager(
                listen_port=optimal_port,
                verbose=True
            )
            
            if self.dht_manager.start():
                print("✅ DHT网络启动成功")
                return True
            else:
                print("❌ DHT网络启动失败")
                return False
                
        except Exception as e:
            print(f"❌ DHT网络启动异常: {e}")
            return False
    
    def test_dht_connectivity(self, timeout=60) -> bool:
        """测试DHT连通性"""
        if not self.dht_manager:
            return False
        
        print(f"🔍 测试DHT连通性（超时: {timeout}秒）...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                if self.dht_manager.is_ready():
                    elapsed = time.time() - start_time
                    print(f"✅ DHT网络就绪！用时: {elapsed:.1f}秒")
                    return True
                
                stats = self.dht_manager.get_stats()
                nodes = stats.get('dht_nodes', 0)
                elapsed = time.time() - start_time
                
                print(f"⏱️  [{elapsed:6.1f}s] DHT节点数: {nodes:4d}")
                time.sleep(5)
                
            except Exception as e:
                print(f"❌ DHT连通性测试异常: {e}")
                break
        
        print(f"⏰ DHT连通性测试超时（{timeout}秒）")
        return False
    
    def stop_dht_network(self):
        """停止DHT网络"""
        if self.dht_manager:
            try:
                self.dht_manager.stop()
                print("✅ DHT网络已停止")
            except Exception as e:
                print(f"❌ 停止DHT网络异常: {e}")

def test_magnet_conversion_on_synology():
    """在群晖系统上测试磁力链接转换"""
    
    print("=" * 80)
    print("群晖NAS系统 - DHT磁力链接转换测试")
    print("=" * 80)
    
    # 1. 环境检查
    print("\n📋 第1步: 环境检查")
    print("-" * 50)
    
    env_checker = SynologyEnvironmentChecker()
    env_results = env_checker.check_environment()
    
    if not env_results['libtorrent_available']:
        print("\n❌ 测试终止: libtorrent库不可用")
        print("请先安装: pip3 install libtorrent")
        return False
    
    if not env_results['ports_available']:
        print("\n❌ 测试终止: 没有可用端口")
        return False
    
    # 2. 启动DHT网络
    print("\n🚀 第2步: 启动DHT网络")
    print("-" * 50)
    
    synology_dht = SynologyDHTManager()
    
    if not synology_dht.start_dht_network():
        print("❌ 测试终止: DHT网络启动失败")
        return False
    
    # 3. 等待DHT就绪
    print("\n⏳ 第3步: 等待DHT网络就绪")
    print("-" * 50)
    
    if not synology_dht.test_dht_connectivity(timeout=120):
        print("❌ DHT网络未就绪，但继续测试...")
    
    # 4. 测试磁力链接转换
    print("\n🔄 第4步: 测试磁力链接转换")
    print("-" * 50)
    
    test_magnet = "magnet:?xt=urn:btih:1081822F880149A0AD32C221F47284D907D75991&dn=The.Walking.Dead.Daryl.Dixon.S03E03.1080p.x265-ELiTE&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337"
    
    try:
        # 创建输出目录
        output_dir = "/tmp/synology_magnet_test"
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"📋 测试磁力链接: {test_magnet[:60]}...")
        print(f"📁 输出目录: {output_dir}")
        
        # 创建转换器
        converter = Magnet2TorrentConverter(
            timeout=60,
            use_shared_dht=True,
            verbose=True
        )
        
        # 解析磁力链接
        magnet_info = converter.parse_magnet_info(test_magnet)
        print("✅ 磁力链接解析成功:")
        print(f"   - Info Hash: {magnet_info.get('info_hash', 'N/A')}")
        print(f"   - 文件名: {magnet_info.get('name', 'N/A')}")
        
        # 尝试转换
        print("🔄 开始转换...")
        result = converter.convert(test_magnet, output_dir)
        
        if result and os.path.exists(result):
            file_size = os.path.getsize(result)
            print(f"✅ 转换成功！")
            print(f"📄 输出文件: {result}")
            print(f"📊 文件大小: {file_size} bytes")
            conversion_success = True
        else:
            print("❌ 转换失败或文件不存在")
            conversion_success = False
            
    except Exception as e:
        print(f"❌ 转换过程异常: {e}")
        conversion_success = False
    
    # 5. 清理资源
    print("\n🧹 第5步: 清理资源")
    print("-" * 50)
    
    synology_dht.stop_dht_network()
    
    # 6. 总结报告
    print("\n" + "=" * 80)
    print("群晖NAS DHT测试总结报告")
    print("=" * 80)
    
    print(f"🖥️  系统环境: {'群晖DSM' if env_checker.is_synology else '其他Linux系统'}")
    print(f"🐍 Python版本: {env_checker.system_info['python_version']}")
    print(f"📦 libtorrent: {'可用' if env_results['libtorrent_available'] else '不可用'}")
    print(f"🔌 可用端口: {len(env_results['ports_available'])}个")
    print(f"📥 Download Station: {'运行中' if env_results['download_station_running'] else '未运行'}")
    print(f"🔄 磁力转换: {'成功' if conversion_success else '失败'}")
    
    if env_results['recommendations']:
        print("\n💡 建议:")
        for rec in env_results['recommendations']:
            print(f"   - {rec}")
    
    print(f"\n🎯 结论: 群晖NAS系统{'完全支持' if conversion_success else '部分支持'}DHT磁力链接转换")
    
    return conversion_success

def create_synology_deployment_guide():
    """创建群晖部署指南"""
    
    guide_content = """
# 群晖NAS部署指南

## 快速部署步骤

### 1. SSH登录群晖
```bash
ssh admin@your-nas-ip
```

### 2. 安装Python依赖
```bash
# 通过包中心安装Python3（如果未安装）
# 或使用命令行
sudo pip3 install libtorrent
```

### 3. 上传脚本
```bash
# 通过File Station上传脚本文件
# 或使用SCP
scp magnet2torrent/ admin@your-nas-ip:/volume1/scripts/
```

### 4. 配置权限
```bash
chmod +x /volume1/scripts/magnet2torrent/*.py
```

### 5. 运行测试
```bash
cd /volume1/scripts/magnet2torrent
python3 synology_dht_test.py
```

## 防火墙配置

1. 登录DSM管理界面
2. 控制面板 > 安全性 > 防火墙
3. 编辑规则 > 创建 > 自定义
4. 端口: 6882-6890
5. 协议: TCP+UDP
6. 来源IP: 全部

## 定时任务设置

1. 控制面板 > 任务计划
2. 创建 > 计划的任务 > 用户定义的脚本
3. 设置运行时间和脚本路径

## 性能监控

使用资源监控器查看：
- CPU使用率
- 内存使用率
- 网络流量
- 磁盘I/O

确保DHT服务不影响其他应用。
"""
    
    guide_path = "/tmp/synology_deployment_guide.md"
    with open(guide_path, 'w', encoding='utf-8') as f:
        f.write(guide_content)
    
    print(f"📖 部署指南已创建: {guide_path}")

if __name__ == "__main__":
    # 运行完整测试
    success = test_magnet_conversion_on_synology()
    
    # 创建部署指南
    create_synology_deployment_guide()
    
    # 退出码
    sys.exit(0 if success else 1)