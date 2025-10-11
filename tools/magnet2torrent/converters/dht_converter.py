#!/usr/bin/env python3
"""
纯 Python DHT 客户端实现（简化版）
通过 DHT 网络获取磁力链接的元数据信息
"""

import socket
import struct
import hashlib
import time
import random
import threading
import argparse
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import binascii

# 简单的 bencode 实现
def bencode(data):
    """简单的 bencode 编码"""
    if isinstance(data, int):
        return str(data).encode() + b'e'
    elif isinstance(data, bytes):
        return str(len(data)).encode() + b':' + data
    elif isinstance(data, str):
        data = data.encode()
        return str(len(data)).encode() + b':' + data
    elif isinstance(data, list):
        result = b'l'
        for item in data:
            result += bencode(item)
        return result + b'e'
    elif isinstance(data, dict):
        result = b'd'
        for key in sorted(data.keys()):
            result += bencode(key) + bencode(data[key])
        return result + b'e'
    else:
        raise ValueError(f"不支持的数据类型: {type(data)}")

def bdecode(data):
    """简单的 bencode 解码"""
    def decode_next(data, index):
        if index >= len(data):
            raise ValueError("数据不完整")
        
        if data[index:index+1] == b'i':
            # 整数
            end = data.find(b'e', index + 1)
            if end == -1:
                raise ValueError("整数格式错误")
            return int(data[index+1:end]), end + 1
        
        elif data[index:index+1] == b'l':
            # 列表
            result = []
            index += 1
            while index < len(data) and data[index:index+1] != b'e':
                item, index = decode_next(data, index)
                result.append(item)
            return result, index + 1
        
        elif data[index:index+1] == b'd':
            # 字典
            result = {}
            index += 1
            while index < len(data) and data[index:index+1] != b'e':
                key, index = decode_next(data, index)
                value, index = decode_next(data, index)
                result[key] = value
            return result, index + 1
        
        elif data[index:index+1].isdigit():
            # 字符串
            colon = data.find(b':', index)
            if colon == -1:
                raise ValueError("字符串格式错误")
            length = int(data[index:colon])
            start = colon + 1
            end = start + length
            return data[start:end], end
        
        else:
            raise ValueError(f"未知数据类型: {data[index:index+1]}")
    
    try:
        result, _ = decode_next(data, 0)
        return result
    except Exception:
        return None

class DHTNode:
    """DHT 节点信息"""
    def __init__(self, ip, port, node_id=None):
        self.ip = ip
        self.port = port
        self.node_id = node_id or self._generate_node_id()
        self.last_seen = time.time()
    
    def _generate_node_id(self):
        """生成随机节点 ID"""
        return hashlib.sha1(f"{self.ip}:{self.port}:{random.random()}".encode()).digest()
    
    def __str__(self):
        return f"{self.ip}:{self.port}"
    
    def __hash__(self):
        return hash((self.ip, self.port))
    
    def __eq__(self, other):
        return isinstance(other, DHTNode) and self.ip == other.ip and self.port == other.port

class PythonDHTClient:
    """纯 Python DHT 客户端"""
    
    def __init__(self, port=6881, timeout=300):
        """初始化 DHT 客户端"""
        self.port = port
        self.timeout = timeout
        self.node_id = self._generate_node_id()
        self.socket = None
        self.running = False
        
        # 节点表
        self.nodes = set()
        self.bootstrap_nodes = [
            DHTNode("router.bittorrent.com", 6881),
            DHTNode("dht.transmissionbt.com", 6881),
            DHTNode("router.utorrent.com", 6881),
            DHTNode("dht.aelitis.com", 6881),
        ]
        
        # 事务表
        self.transactions = {}
        self.transaction_id = 0
        
        # 设置日志
        self.logger = self._setup_logging()
    
    def _setup_logging(self):
        """设置日志"""
        logger = logging.getLogger("PythonDHTClient")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _generate_node_id(self):
        """生成节点 ID"""
        return hashlib.sha1(f"python_dht_{random.random()}_{time.time()}".encode()).digest()
    
    def _generate_transaction_id(self):
        """生成事务 ID"""
        self.transaction_id += 1
        return struct.pack(">H", self.transaction_id % 65536)
    
    def start(self):
        """启动 DHT 客户端"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind(("0.0.0.0", self.port))
            self.socket.settimeout(1.0)
            self.running = True
            
            self.logger.info(f"✅ DHT 客户端启动成功，监听端口: {self.port}")
            
            # 启动接收线程
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            # 引导连接
            self._bootstrap()
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 启动 DHT 客户端失败: {e}")
            return False
    
    def stop(self):
        """停止 DHT 客户端"""
        self.running = False
        if self.socket:
            self.socket.close()
        self.logger.info("✅ DHT 客户端已停止")
    
    def _bootstrap(self):
        """引导连接到 DHT 网络"""
        self.logger.info("🔄 引导连接到 DHT 网络...")
        
        for node in self.bootstrap_nodes:
            self._ping_node(node)
            time.sleep(0.1)
    
    def _ping_node(self, node):
        """Ping 节点"""
        transaction_id = self._generate_transaction_id()
        
        message = {
            b"t": transaction_id,
            b"y": b"q",
            b"q": b"ping",
            b"a": {
                b"id": self.node_id
            }
        }
        
        return self._send_message(node, message, transaction_id)
    
    def _get_peers(self, node, info_hash):
        """获取 peers"""
        transaction_id = self._generate_transaction_id()
        
        message = {
            b"t": transaction_id,
            b"y": b"q",
            b"q": b"get_peers",
            b"a": {
                b"id": self.node_id,
                b"info_hash": info_hash
            }
        }
        
        return self._send_message(node, message, transaction_id)
    
    def _send_message(self, node, message, transaction_id):
        """发送消息"""
        try:
            if not self.socket:
                return False
            data = bencode(message)
            self.socket.sendto(data, (node.ip, node.port))
            
            # 记录事务
            self.transactions[transaction_id] = {
                "node": node,
                "message": message,
                "timestamp": time.time()
            }
            
            return True
            
        except Exception as e:
            self.logger.debug(f"发送消息失败 {node}: {e}")
            return False
    
    def _receive_loop(self):
        """接收消息循环"""
        while self.running:
            try:
                if not self.socket:
                    break
                data, addr = self.socket.recvfrom(65536)
                self._handle_message(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    self.logger.debug(f"接收消息异常: {e}")
    
    def _handle_message(self, data, addr):
        """处理接收到的消息"""
        message = bdecode(data)
        if not message or not isinstance(message, dict):
            return
        
        try:
            msg_type = message.get(b"y")
            transaction_id = message.get(b"t")
            
            if msg_type == b"r":  # 响应
                self._handle_response(message, addr, transaction_id)
                
        except Exception as e:
            self.logger.debug(f"处理消息异常: {e}")
    
    def _handle_response(self, message, addr, transaction_id):
        """处理响应消息"""
        if transaction_id not in self.transactions:
            return
        
        transaction = self.transactions.pop(transaction_id)
        original_query = transaction["message"].get(b"q")
        
        response_data = message.get(b"r", {})
        
        if original_query == b"ping":
            self._handle_ping_response(response_data, addr)
        elif original_query == b"get_peers":
            self._handle_get_peers_response(response_data, addr)
    
    def _handle_ping_response(self, data, addr):
        """处理 ping 响应"""
        node_id = data.get(b"id")
        if node_id:
            node = DHTNode(addr[0], addr[1], node_id)
            self.nodes.add(node)
            self.logger.debug(f"添加节点: {node}")
    
    def _handle_get_peers_response(self, data, addr):
        """处理 get_peers 响应"""
        # 获取 peers
        peers_data = data.get(b"values")
        if peers_data:
            self.logger.info(f"📥 获取到 {len(peers_data)} 个 peers")
        
        # 获取更多节点
        nodes_data = data.get(b"nodes")
        if nodes_data:
            self._parse_nodes(nodes_data)
    
    def _parse_nodes(self, nodes_data):
        """解析节点数据"""
        try:
            # 每个节点 26 字节：20 字节 ID + 4 字节 IP + 2 字节端口
            for i in range(0, len(nodes_data), 26):
                if i + 26 > len(nodes_data):
                    break
                
                node_data = nodes_data[i:i+26]
                node_id = node_data[:20]
                ip_bytes = node_data[20:24]
                port_bytes = node_data[24:26]
                
                ip = ".".join(str(b) for b in ip_bytes)
                port = struct.unpack(">H", port_bytes)[0]
                
                if self._is_valid_ip(ip) and 1 <= port <= 65535:
                    node = DHTNode(ip, port, node_id)
                    self.nodes.add(node)
                    
        except Exception as e:
            self.logger.debug(f"解析节点数据失败: {e}")
    
    def _is_valid_ip(self, ip):
        """检查 IP 地址是否有效"""
        try:
            parts = ip.split(".")
            if len(parts) != 4:
                return False
            
            for part in parts:
                num = int(part)
                if not 0 <= num <= 255:
                    return False
            
            # 排除私有和保留地址
            first = int(parts[0])
            if first in [0, 10, 127, 169, 172, 192, 224, 240]:
                return False
            
            return True
            
        except:
            return False
    
    def _extract_info_hash_from_magnet(self, magnet_uri):
        """从磁力链接提取 info hash"""
        try:
            parsed = urlparse(magnet_uri)
            params = parse_qs(parsed.query)
            
            xt_list = params.get('xt', [])
            for xt in xt_list:
                if xt.startswith('urn:btih:'):
                    hash_str = xt[9:]  # 移除 'urn:btih:' 前缀
                    
                    # 处理不同长度的哈希
                    if len(hash_str) == 40:  # 十六进制
                        return binascii.unhexlify(hash_str)
                    elif len(hash_str) == 32:  # Base32
                        import base64
                        # 补齐 Base32 填充
                        hash_str += '=' * (8 - len(hash_str) % 8)
                        return base64.b32decode(hash_str)
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ 提取 info hash 失败: {e}")
            return None
    
    def find_peers_for_magnet(self, magnet_uri, max_attempts=50):
        """为磁力链接查找 peers"""
        info_hash = self._extract_info_hash_from_magnet(magnet_uri)
        if not info_hash:
            self.logger.error("❌ 无法从磁力链接提取 info hash")
            return []
        
        self.logger.info(f"🔍 查找 peers，info hash: {binascii.hexlify(info_hash).decode()}")
        
        peers = []
        attempts = 0
        
        # 等待一些节点连接
        time.sleep(2)
        
        while attempts < max_attempts and len(peers) < 10:
            if not self.nodes:
                self.logger.warning("⚠️ 没有可用的 DHT 节点")
                break
            
            # 随机选择节点查询
            available_nodes = list(self.nodes)[:20]  # 限制查询的节点数量
            
            for node in available_nodes:
                if attempts >= max_attempts:
                    break
                
                self._get_peers(node, info_hash)
                attempts += 1
                time.sleep(0.1)
            
            # 等待响应
            time.sleep(1)
        
        self.logger.info(f"📊 查找完成，尝试 {attempts} 次，找到 {len(peers)} 个 peers")
        return peers
    
    def convert_magnet_to_torrent(self, magnet_uri, output_path=None):
        """
        将磁力链接转换为种子文件
        
        注意：这是一个演示实现，实际的元数据获取需要完整的 BitTorrent 协议
        """
        self.logger.info("🧲 开始使用 DHT 转换磁力链接...")
        
        # 提取 info hash
        info_hash = self._extract_info_hash_from_magnet(magnet_uri)
        if not info_hash:
            return None
        
        hash_hex = binascii.hexlify(info_hash).decode()
        self.logger.info(f"📋 Info Hash: {hash_hex}")
        
        # 查找 peers
        peers = self.find_peers_for_magnet(magnet_uri)
        
        if not peers:
            self.logger.error("❌ 未找到任何 peers，无法获取元数据")
            return None
        
        # 注意：这里只是演示框架
        # 实际的元数据获取需要实现 BitTorrent 协议的元数据扩展
        # 这是一个复杂的过程，需要与 peers 建立 TCP 连接并交换元数据
        
        self.logger.warning("⚠️ DHT 客户端找到了 peers，但元数据获取需要完整的 BitTorrent 协议实现")
        self.logger.info("💡 建议使用 aria2 或 qBittorrent 方案，它们有完整的协议实现")
        
        return None
    
    def get_stats(self):
        """获取统计信息"""
        return {
            "nodes_count": len(self.nodes),
            "transactions_count": len(self.transactions),
            "running": self.running,
            "port": self.port
        }

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="纯 Python DHT 客户端")
    parser.add_argument("--port", type=int, default=6881, help="监听端口")
    parser.add_argument("--timeout", type=int, default=300, help="超时时间")
    parser.add_argument("--magnet", help="要转换的磁力链接")
    parser.add_argument("--output", help="输出种子文件路径")
    parser.add_argument("--test", action="store_true", help="测试 DHT 连接")
    
    args = parser.parse_args()
    
    # 创建 DHT 客户端
    client = PythonDHTClient(port=args.port, timeout=args.timeout)
    
    try:
        if not client.start():
            print("❌ DHT 客户端启动失败")
            return 1
        
        if args.test:
            print("🔄 测试 DHT 连接...")
            time.sleep(10)  # 等待连接建立
            
            stats = client.get_stats()
            print(f"📊 统计信息:")
            print(f"   节点数量: {stats['nodes_count']}")
            print(f"   事务数量: {stats['transactions_count']}")
            print(f"   运行状态: {stats['running']}")
            print(f"   监听端口: {stats['port']}")
            
            if stats['nodes_count'] > 0:
                print("✅ DHT 连接测试成功")
                return 0
            else:
                print("❌ DHT 连接测试失败")
                return 1
        
        elif args.magnet:
            result = client.convert_magnet_to_torrent(args.magnet, args.output)
            if result:
                print(f"✅ 转换成功: {result}")
                return 0
            else:
                print("❌ 转换失败")
                return 1
        
        else:
            print("💡 使用 --test 测试连接或 --magnet 转换磁力链接")
            return 0
    
    except KeyboardInterrupt:
        print("\n🛑 用户中断")
        return 1
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        return 1
    finally:
        client.stop()

if __name__ == "__main__":
    import sys
    sys.exit(main())