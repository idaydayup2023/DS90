#!/usr/bin/env python3
"""
磁力链接信息提取和种子文件生成工具
提供多种方法来处理磁力链接并生成种子文件
"""

import re
import hashlib
import base64
import binascii
import argparse
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
from typing import Dict, Any, List, Optional
import json
import time

class MagnetInfoExtractor:
    """磁力链接信息提取器"""
    
    def __init__(self):
        """初始化提取器"""
        self.logger = self._setup_logging()
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger("MagnetInfoExtractor")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def extract_magnet_info(self, magnet_uri: str) -> Optional[Dict[str, Any]]:
        """
        提取磁力链接信息
        
        Args:
            magnet_uri: 磁力链接
            
        Returns:
            包含磁力链接信息的字典，失败返回 None
        """
        try:
            self.logger.info("🔍 开始提取磁力链接信息...")
            
            # 验证磁力链接格式
            if not magnet_uri.startswith('magnet:?'):
                self.logger.error("❌ 无效的磁力链接格式")
                return None
            
            # 解析 URL
            parsed = urlparse(magnet_uri)
            params = parse_qs(parsed.query)
            
            info = {
                "original_magnet": magnet_uri,
                "info_hash": None,
                "info_hash_hex": None,
                "info_hash_base32": None,
                "display_name": None,
                "trackers": [],
                "web_seeds": [],
                "file_size": None,
                "keywords": [],
                "manifest_topic": None,
                "acceptable_source": None,
                "exact_source": None,
                "exact_length": None,
                "select_only": None,
                "supplement": None
            }
            
            # 提取 XT (eXact Topic) - Info Hash
            xt_list = params.get('xt', [])
            for xt in xt_list:
                if xt.startswith('urn:btih:'):
                    hash_str = xt[9:]  # 移除 'urn:btih:' 前缀
                    
                    if len(hash_str) == 40:  # 十六进制格式
                        info["info_hash"] = binascii.unhexlify(hash_str)
                        info["info_hash_hex"] = hash_str.upper()
                        # 转换为 Base32
                        info["info_hash_base32"] = base64.b32encode(info["info_hash"]).decode().rstrip('=')
                    elif len(hash_str) == 32:  # Base32 格式
                        # 补齐 Base32 填充
                        hash_str_padded = hash_str + '=' * (8 - len(hash_str) % 8)
                        info["info_hash"] = base64.b32decode(hash_str_padded)
                        info["info_hash_hex"] = binascii.hexlify(info["info_hash"]).decode().upper()
                        info["info_hash_base32"] = hash_str.upper()
                    
                    self.logger.info(f"📋 Info Hash (Hex): {info['info_hash_hex']}")
                    self.logger.info(f"📋 Info Hash (Base32): {info['info_hash_base32']}")
                    break
            
            # 提取 DN (Display Name) - 显示名称
            dn_list = params.get('dn', [])
            if dn_list:
                info["display_name"] = unquote(dn_list[0])
                self.logger.info(f"📝 显示名称: {info['display_name']}")
            
            # 提取 TR (TRacker) - 追踪器列表
            tr_list = params.get('tr', [])
            info["trackers"] = [unquote(tr) for tr in tr_list]
            if info["trackers"]:
                self.logger.info(f"🔗 追踪器数量: {len(info['trackers'])}")
                for i, tracker in enumerate(info["trackers"][:3]):  # 只显示前3个
                    self.logger.info(f"   {i+1}. {tracker}")
                if len(info["trackers"]) > 3:
                    self.logger.info(f"   ... 还有 {len(info['trackers']) - 3} 个追踪器")
            
            # 提取 WS (Web Seed) - Web 种子
            ws_list = params.get('ws', [])
            info["web_seeds"] = [unquote(ws) for ws in ws_list]
            if info["web_seeds"]:
                self.logger.info(f"🌐 Web 种子数量: {len(info['web_seeds'])}")
            
            # 提取 XL (eXact Length) - 精确长度
            xl_list = params.get('xl', [])
            if xl_list:
                try:
                    info["exact_length"] = int(xl_list[0])
                    info["file_size"] = self._format_file_size(info["exact_length"])
                    self.logger.info(f"📏 文件大小: {info['file_size']}")
                except ValueError:
                    pass
            
            # 提取 KT (KeyworD Topic) - 关键词
            kt_list = params.get('kt', [])
            if kt_list:
                info["keywords"] = [unquote(kt) for kt in kt_list]
                self.logger.info(f"🏷️ 关键词: {', '.join(info['keywords'])}")
            
            # 提取 MT (Manifest Topic) - 清单主题
            mt_list = params.get('mt', [])
            if mt_list:
                info["manifest_topic"] = unquote(mt_list[0])
                self.logger.info(f"📄 清单主题: {info['manifest_topic']}")
            
            # 提取 AS (Acceptable Source) - 可接受来源
            as_list = params.get('as', [])
            if as_list:
                info["acceptable_source"] = unquote(as_list[0])
                self.logger.info(f"✅ 可接受来源: {info['acceptable_source']}")
            
            # 提取 XS (eXact Source) - 精确来源
            xs_list = params.get('xs', [])
            if xs_list:
                info["exact_source"] = unquote(xs_list[0])
                self.logger.info(f"🎯 精确来源: {info['exact_source']}")
            
            # 提取 SO (Select Only) - 仅选择
            so_list = params.get('so', [])
            if so_list:
                info["select_only"] = unquote(so_list[0])
                self.logger.info(f"🎯 仅选择: {info['select_only']}")
            
            # 提取 SUP (SUPplement) - 补充
            sup_list = params.get('sup', [])
            if sup_list:
                info["supplement"] = unquote(sup_list[0])
                self.logger.info(f"➕ 补充: {info['supplement']}")
            
            if not info["info_hash"]:
                self.logger.error("❌ 未找到有效的 Info Hash")
                return None
            
            self.logger.info("✅ 磁力链接信息提取完成")
            return info
            
        except Exception as e:
            self.logger.error(f"❌ 提取磁力链接信息失败: {e}")
            return None
    
    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB", "PB"]
        i = 0
        size_float = float(size_bytes)
        while size_float >= 1024 and i < len(size_names) - 1:
            size_float /= 1024.0
            i += 1
        
        return f"{size_float:.2f} {size_names[i]}"
    
    def generate_basic_torrent_info(self, magnet_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成基本的种子文件信息
        
        Args:
            magnet_info: 磁力链接信息
            
        Returns:
            基本的种子文件信息字典
        """
        try:
            self.logger.info("🔧 生成基本种子文件信息...")
            
            # 基本种子文件结构
            torrent_info = {
                "announce": "",  # 主要追踪器
                "announce-list": [],  # 追踪器列表
                "creation date": int(time.time()),  # 创建时间
                "comment": f"Generated from magnet link by MagnetInfoExtractor",
                "created by": "MagnetInfoExtractor v1.0",
                "encoding": "UTF-8",
                "info": {
                    "name": magnet_info.get("display_name", "Unknown"),
                    "piece length": 262144,  # 256KB 片段长度
                    "pieces": b"",  # 空的片段哈希（无法从磁力链接获取）
                }
            }
            
            # 设置追踪器
            if magnet_info["trackers"]:
                torrent_info["announce"] = magnet_info["trackers"][0]
                # 将追踪器分组
                announce_list = []
                for tracker in magnet_info["trackers"]:
                    announce_list.append([tracker])
                torrent_info["announce-list"] = announce_list
            
            # 设置文件长度
            if magnet_info.get("exact_length"):
                torrent_info["info"]["length"] = magnet_info["exact_length"]
            
            # 添加 Web 种子
            if magnet_info["web_seeds"]:
                torrent_info["url-list"] = magnet_info["web_seeds"]
            
            # 计算 info hash（应该与磁力链接中的一致）
            # 注意：由于我们没有实际的文件数据，这里只是占位符
            if magnet_info["info_hash"]:
                # 验证 info hash
                self.logger.info(f"📋 预期 Info Hash: {magnet_info['info_hash_hex']}")
            
            self.logger.info("✅ 基本种子文件信息生成完成")
            return torrent_info
            
        except Exception as e:
            self.logger.error(f"❌ 生成种子文件信息失败: {e}")
            return {}
    
    def save_magnet_info_to_json(self, magnet_info: Dict[str, Any], output_path: str) -> bool:
        """
        将磁力链接信息保存为 JSON 文件
        
        Args:
            magnet_info: 磁力链接信息
            output_path: 输出文件路径
            
        Returns:
            成功返回 True，失败返回 False
        """
        try:
            self.logger.info(f"💾 保存磁力链接信息到: {output_path}")
            
            # 准备可序列化的数据
            serializable_info = magnet_info.copy()
            
            # 将 bytes 类型转换为 hex 字符串
            if serializable_info.get("info_hash"):
                serializable_info["info_hash"] = serializable_info["info_hash_hex"]
            
            # 添加时间戳
            serializable_info["extracted_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # 保存到文件
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_info, f, indent=2, ensure_ascii=False)
            
            self.logger.info("✅ 磁力链接信息保存成功")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 保存磁力链接信息失败: {e}")
            return False
    
    def create_magnet_from_info(self, info_hash: str, display_name: Optional[str] = None, 
                               trackers: Optional[List[str]] = None, file_size: Optional[int] = None) -> str:
        """
        从信息创建磁力链接
        
        Args:
            info_hash: Info Hash (十六进制)
            display_name: 显示名称
            trackers: 追踪器列表
            file_size: 文件大小
            
        Returns:
            生成的磁力链接
        """
        try:
            self.logger.info("🧲 创建磁力链接...")
            
            # 验证 info hash
            if len(info_hash) != 40:
                raise ValueError("Info Hash 必须是 40 个字符的十六进制字符串")
            
            # 构建磁力链接
            magnet_parts = [f"magnet:?xt=urn:btih:{info_hash.upper()}"]
            
            # 添加显示名称
            if display_name:
                from urllib.parse import quote
                magnet_parts.append(f"dn={quote(display_name)}")
            
            # 添加文件大小
            if file_size:
                magnet_parts.append(f"xl={file_size}")
            
            # 添加追踪器
            if trackers:
                for tracker in trackers:
                    from urllib.parse import quote
                    magnet_parts.append(f"tr={quote(tracker)}")
            
            magnet_uri = "&".join(magnet_parts)
            
            self.logger.info(f"✅ 磁力链接创建成功")
            self.logger.info(f"🧲 {magnet_uri}")
            
            return magnet_uri
            
        except Exception as e:
            self.logger.error(f"❌ 创建磁力链接失败: {e}")
            return ""
    
    def validate_magnet_link(self, magnet_uri: str) -> Dict[str, Any]:
        """
        验证磁力链接的有效性
        
        Args:
            magnet_uri: 磁力链接
            
        Returns:
            验证结果字典
        """
        result = {
            "valid": False,
            "errors": [],
            "warnings": [],
            "info": {}
        }
        
        try:
            self.logger.info("🔍 验证磁力链接...")
            
            # 基本格式检查
            if not magnet_uri.startswith('magnet:?'):
                result["errors"].append("磁力链接必须以 'magnet:?' 开头")
                return result
            
            # 提取信息
            info = self.extract_magnet_info(magnet_uri)
            if not info:
                result["errors"].append("无法解析磁力链接")
                return result
            
            result["info"] = info
            
            # 检查必需的字段
            if not info.get("info_hash"):
                result["errors"].append("缺少 Info Hash (xt 参数)")
            
            # 检查可选但推荐的字段
            if not info.get("display_name"):
                result["warnings"].append("缺少显示名称 (dn 参数)")
            
            if not info.get("trackers"):
                result["warnings"].append("缺少追踪器 (tr 参数)")
            
            if not info.get("exact_length"):
                result["warnings"].append("缺少文件大小 (xl 参数)")
            
            # 检查 Info Hash 格式
            if info.get("info_hash_hex"):
                if len(info["info_hash_hex"]) != 40:
                    result["errors"].append("Info Hash 长度不正确")
                elif not re.match(r'^[0-9A-Fa-f]{40}$', info["info_hash_hex"]):
                    result["errors"].append("Info Hash 包含无效字符")
            
            # 检查追踪器 URL
            for tracker in info.get("trackers", []):
                if not (tracker.startswith('http://') or tracker.startswith('https://') or 
                       tracker.startswith('udp://')):
                    result["warnings"].append(f"追踪器 URL 格式可能不正确: {tracker}")
            
            # 如果没有错误，则认为有效
            if not result["errors"]:
                result["valid"] = True
                self.logger.info("✅ 磁力链接验证通过")
            else:
                self.logger.error(f"❌ 磁力链接验证失败: {', '.join(result['errors'])}")
            
            if result["warnings"]:
                self.logger.warning(f"⚠️ 警告: {', '.join(result['warnings'])}")
            
            return result
            
        except Exception as e:
            result["errors"].append(f"验证过程中发生错误: {e}")
            self.logger.error(f"❌ 验证磁力链接时发生错误: {e}")
            return result

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="磁力链接信息提取和种子文件生成工具")
    parser.add_argument("--magnet", help="要处理的磁力链接")
    parser.add_argument("--extract", action="store_true", help="提取磁力链接信息")
    parser.add_argument("--validate", action="store_true", help="验证磁力链接")
    parser.add_argument("--create", action="store_true", help="创建磁力链接")
    parser.add_argument("--info-hash", help="Info Hash (用于创建磁力链接)")
    parser.add_argument("--name", help="显示名称 (用于创建磁力链接)")
    parser.add_argument("--tracker", action="append", help="追踪器 URL (可多次使用)")
    parser.add_argument("--size", type=int, help="文件大小 (字节)")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    
    args = parser.parse_args()
    
    extractor = MagnetInfoExtractor()
    
    try:
        if args.create:
            # 创建磁力链接
            if not args.info_hash:
                print("❌ 创建磁力链接需要 --info-hash 参数")
                return 1
            
            magnet = extractor.create_magnet_from_info(
                args.info_hash, 
                args.name, 
                args.tracker or [], 
                args.size
            )
            
            if magnet:
                print(f"✅ 创建的磁力链接:")
                print(magnet)
                
                if args.output:
                    with open(args.output, 'w') as f:
                        f.write(magnet)
                    print(f"💾 已保存到: {args.output}")
                
                return 0
            else:
                return 1
        
        elif args.magnet:
            if args.validate:
                # 验证磁力链接
                result = extractor.validate_magnet_link(args.magnet)
                
                if args.json:
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                else:
                    print(f"验证结果: {'✅ 有效' if result['valid'] else '❌ 无效'}")
                    
                    if result["errors"]:
                        print("错误:")
                        for error in result["errors"]:
                            print(f"  - {error}")
                    
                    if result["warnings"]:
                        print("警告:")
                        for warning in result["warnings"]:
                            print(f"  - {warning}")
                
                return 0 if result["valid"] else 1
            
            elif args.extract:
                # 提取磁力链接信息
                info = extractor.extract_magnet_info(args.magnet)
                
                if not info:
                    print("❌ 提取磁力链接信息失败")
                    return 1
                
                if args.json:
                    # 输出 JSON 格式
                    if args.output:
                        extractor.save_magnet_info_to_json(info, args.output)
                    else:
                        # 准备可序列化的数据
                        serializable_info = info.copy()
                        if serializable_info.get("info_hash"):
                            serializable_info["info_hash"] = serializable_info["info_hash_hex"]
                        print(json.dumps(serializable_info, indent=2, ensure_ascii=False))
                else:
                    # 输出人类可读格式
                    print("\n📋 磁力链接信息:")
                    print(f"Info Hash: {info.get('info_hash_hex', 'N/A')}")
                    print(f"显示名称: {info.get('display_name', 'N/A')}")
                    print(f"文件大小: {info.get('file_size', 'N/A')}")
                    print(f"追踪器数量: {len(info.get('trackers', []))}")
                    print(f"Web 种子数量: {len(info.get('web_seeds', []))}")
                    
                    if args.output and not args.json:
                        extractor.save_magnet_info_to_json(info, args.output)
                
                return 0
            
            else:
                # 默认：提取并验证
                print("🔍 提取并验证磁力链接...")
                
                # 提取信息
                info = extractor.extract_magnet_info(args.magnet)
                if not info:
                    return 1
                
                # 验证
                result = extractor.validate_magnet_link(args.magnet)
                print(f"\n验证结果: {'✅ 有效' if result['valid'] else '❌ 无效'}")
                
                return 0 if result["valid"] else 1
        
        else:
            print("💡 使用示例:")
            print("  提取信息: python magnet_info_extractor.py --magnet 'magnet:?...' --extract")
            print("  验证链接: python magnet_info_extractor.py --magnet 'magnet:?...' --validate")
            print("  创建链接: python magnet_info_extractor.py --create --info-hash 'abc123...' --name 'filename'")
            return 0
    
    except KeyboardInterrupt:
        print("\n🛑 用户中断")
        return 1
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())