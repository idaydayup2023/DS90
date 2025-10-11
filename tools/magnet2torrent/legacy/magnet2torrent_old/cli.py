import argparse
import sys
import logging
from .converter import Magnet2TorrentConverter

def main():
    """命令行入口函数"""
    # 创建参数解析器
    parser = argparse.ArgumentParser(
        description="将磁力链接转换为.torrent文件",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # 添加参数
    parser.add_argument(
        "magnet_uri",
        help="要转换的磁力链接"
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=".",
        help="保存torrent文件的目录"
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=60,
        help="下载元数据的超时时间（秒）"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细日志"
    )
    
    # 解析参数
    args = parser.parse_args()
    
    # 设置日志级别
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    
    try:
        # 创建转换器
        converter = Magnet2TorrentConverter(
            timeout=args.timeout,
            verbose=args.verbose
        )
        
        # 执行转换
        output_path = converter.convert(
            args.magnet_uri,
            args.output_dir
        )
        
        print(f"转换成功: {output_path}")
        return 0
        
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    except TimeoutError as e:
        print(f"超时: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"未知错误: {e}", file=sys.stderr)
        logging.exception("发生异常")
        return 3

if __name__ == "__main__":
    sys.exit(main())