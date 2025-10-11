#!/usr/bin/env python3
"""
网络连接测试脚本 - 专门用于诊断VPN环境下的BitTorrent连接问题
"""

import socket
import subprocess
import time
import sys
import urllib.request
import urllib.parse

def test_basic_connectivity():
    """测试基本网络连接"""
    print("=== 基本网络连接测试 ===")
    
    # 测试DNS解析
    try:
        import socket
        socket.gethostbyname('google.com')
        print("✅ DNS解析正常")
    except Exception as e:
        print(f"❌ DNS解析失败: {e}")
    
    # 测试HTTP连接
    try:
        response = urllib.request.urlopen('http://httpbin.org/ip', timeout=10)
        data = response.read().decode()
        print(f"✅ HTTP连接正常，外部IP信息: {data.strip()}")
    except Exception as e:
        print(f"❌ HTTP连接失败: {e}")
    
    # 测试HTTPS连接
    try:
        response = urllib.request.urlopen('https://httpbin.org/ip', timeout=10)
        data = response.read().decode()
        print(f"✅ HTTPS连接正常")
    except Exception as e:
        print(f"❌ HTTPS连接失败: {e}")

def test_udp_connectivity():
    """测试UDP连接（BitTorrent tracker常用）"""
    print("\n=== UDP连接测试 ===")
    
    # 测试常见的BitTorrent tracker端口
    test_hosts = [
        ('tracker.openbittorrent.com', 80),
        ('tracker.publicbt.com', 80),
        ('9.rarbg.to', 2710),
        ('tracker.coppersurfer.tk', 6969),
        ('exodus.desync.com', 6969)
    ]
    
    for host, port in test_hosts:
        try:
            # 创建UDP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            
            # 尝试连接
            sock.connect((host, port))
            print(f"✅ UDP连接到 {host}:{port} 成功")
            sock.close()
        except Exception as e:
            print(f"❌ UDP连接到 {host}:{port} 失败: {e}")

def test_tcp_connectivity():
    """测试TCP连接"""
    print("\n=== TCP连接测试 ===")
    
    # 测试常见的BitTorrent端口
    test_hosts = [
        ('tracker.openbittorrent.com', 80),
        ('tracker.publicbt.com', 80),
        ('9.rarbg.to', 2710),
    ]
    
    for host, port in test_hosts:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            if result == 0:
                print(f"✅ TCP连接到 {host}:{port} 成功")
            else:
                print(f"❌ TCP连接到 {host}:{port} 失败，错误码: {result}")
            sock.close()
        except Exception as e:
            print(f"❌ TCP连接到 {host}:{port} 失败: {e}")

def test_port_availability():
    """测试本地端口可用性"""
    print("\n=== 本地端口测试 ===")
    
    test_ports = [6881, 6882, 6883, 51413]
    
    for port in test_ports:
        try:
            # 测试TCP端口
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', port))
            sock.listen(1)
            print(f"✅ TCP端口 {port} 可用")
            sock.close()
        except Exception as e:
            print(f"❌ TCP端口 {port} 不可用: {e}")
        
        try:
            # 测试UDP端口
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('0.0.0.0', port))
            print(f"✅ UDP端口 {port} 可用")
            sock.close()
        except Exception as e:
            print(f"❌ UDP端口 {port} 不可用: {e}")

def test_vpn_info():
    """获取VPN相关信息"""
    print("\n=== VPN环境信息 ===")
    
    try:
        # 获取本地IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print(f"本地IP地址: {local_ip}")
        
        # 判断是否为VPN IP
        if local_ip.startswith('10.') or local_ip.startswith('192.168.') or local_ip.startswith('172.'):
            print("✅ 检测到内网IP，可能使用VPN")
        else:
            print("⚠️ 检测到公网IP")
            
    except Exception as e:
        print(f"❌ 获取本地IP失败: {e}")
    
    # 检查路由信息
    try:
        result = subprocess.run(['route', '-n', 'get', 'default'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("路由信息:")
            print(result.stdout)
        else:
            print("❌ 获取路由信息失败")
    except Exception as e:
        print(f"❌ 获取路由信息失败: {e}")

def test_firewall():
    """测试防火墙设置"""
    print("\n=== 防火墙测试 ===")
    
    try:
        # 检查macOS防火墙状态
        result = subprocess.run(['sudo', 'pfctl', '-s', 'info'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("防火墙状态:")
            print(result.stdout)
        else:
            print("❌ 无法获取防火墙状态（可能需要管理员权限）")
    except Exception as e:
        print(f"❌ 防火墙检查失败: {e}")

def main():
    """主函数"""
    print("BitTorrent网络连接诊断工具")
    print("=" * 50)
    
    test_basic_connectivity()
    test_vpn_info()
    test_port_availability()
    test_tcp_connectivity()
    test_udp_connectivity()
    test_firewall()
    
    print("\n" + "=" * 50)
    print("诊断完成！")
    print("\n建议:")
    print("1. 如果UDP连接失败，可能是VPN不支持UDP或被防火墙阻止")
    print("2. 如果端口不可用，可能需要配置端口转发")
    print("3. 如果是企业VPN，可能有BitTorrent流量限制")
    print("4. 尝试使用不同的tracker或启用TCP连接")

if __name__ == "__main__":
    main()