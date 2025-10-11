import unittest
import os
import tempfile
from magnet2torrent.converter import Magnet2TorrentConverter

class TestMagnet2TorrentConverter(unittest.TestCase):
    
    def test_parse_magnet_uri(self):
        """测试解析磁力链接"""
        converter = Magnet2TorrentConverter()
        
        # 测试有效的磁力链接
        valid_magnet = "magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
        info_hash = converter._parse_magnet_uri(valid_magnet)
        self.assertEqual(info_hash, "c12fe1c06bba254a9dc9f519b335aa7c1367a88a")
        
        # 测试无效的磁力链接
        invalid_magnet = "http://example.com"
        with self.assertRaises(ValueError):
            converter._parse_magnet_uri(invalid_magnet)
            
        # 测试缺少xt参数的磁力链接
        invalid_magnet = "magnet:?dn=test"
        with self.assertRaises(ValueError):
            converter._parse_magnet_uri(invalid_magnet)
    
    def test_convert_timeout(self):
        """测试转换超时"""
        # 使用一个不存在的info_hash，应该会超时
        converter = Magnet2TorrentConverter(timeout=2)  # 设置较短的超时时间
        invalid_magnet = "magnet:?xt=urn:btih:0000000000000000000000000000000000000000"
        
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(TimeoutError):
                converter.convert(invalid_magnet, temp_dir)

if __name__ == "__main__":
    unittest.main()