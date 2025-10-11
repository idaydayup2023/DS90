import re
import shutil
import urllib.parse
import logging
import requests
import os
import sys
import platform
import time
import tempfile
import subprocess
from datetime import datetime
from bs4 import BeautifulSoup


# 设置日志级别
logging.basicConfig(level=logging.DEBUG)
api_key = 'f53b36a1'  # 用户提供的OMDb API密钥
# 设置代理
proxies = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890',
}
#proxies = {} # 不使用代理
# BT 种子文件保存目录
if platform.system() == 'Windows':
    torrents_path = "F:\\Downloads\\torrent.files" # Windows NetDrive 客户端上存放种子文件的目录
elif platform.system() == 'Mac':
    torrents_path = "/Users/jun/OneDrive/torrent.files" # MacOS上存放种子文件的目录
else:  # 假设是Linux/Unix系统   
    torrents_path = "/volume1/Downloads/torrent.files" # NAS上存放种子文件的目录
    proxies = {} # 不使用代理

def regular_filename(filename):
    # 处理文件名：去掉空格、括号和方括号，并用点分隔    
    filename = re.sub(r'[\[\]\(\)（）【】　]', ' ', filename.strip())  # 替换括号和方括号等
    filename = re.sub(r'www\.\S+\.com', '', filename)  # 去除含 www.开头和以 .com 结尾的域名的字符串
    filename = re.sub(r'\s+', '.', filename.strip()) # 替换连续的空格为一个.
    # 使用正则表达式去除多余的点,将两个及以上的点替换为一个点
    filename = re.sub(r'\.{2,}', '.', filename) 
    return filename

# 使用aria2c在临时目录中将磁力链接转换为种子文件，然后重命名并移动到最终目的地。此函数也会使用代理。
def magnet2torrent(magnet, title, info_hash):
    final_filename = regular_filename(title) + '.torrent'
    final_filepath = os.path.join(torrents_path, final_filename)

    # 如果最终文件已存在，则跳过
    if os.path.isfile(final_filepath) or os.path.isfile(final_filepath + ".loaded"):
        logging.info(f"最终种子文件 {final_filename} 已存在，跳过转换。")
        return None

    # 使用临时目录下载初始 .torrent 文件
    with tempfile.TemporaryDirectory() as temp_dir:
        # 使用主目录作为“临时目录” # temp_dir = torrents_path
        temp_dir = os.path.expanduser("~") # 使用当前目录 temp_dir = os.getcwd()        
        aria2_hash_filename = f"{info_hash.lower()}.torrent"
        aria2_temp_filepath = os.path.join(temp_dir, aria2_hash_filename)

        logging.info(f"尝试在临时目录 {temp_dir} 中使用aria2c转换磁力链接...")
        
        # 从全局字典中获取代理
        proxy_url = proxies.get('http')
        
        cmd = [
            "./aria2c",
            # -- 代理设置 --
            # "--all-proxy=socks5://127.0.0.1:7891", # SOCKS5备用
        ]

        # 仅当代理URL存在时才添加代理参数
        if proxy_url:
            cmd.extend(["--all-proxy", proxy_url])

        # 添加核心参数
        cmd.extend([
            "--bt-metadata-only=true",
            "--bt-save-metadata=true",
            "--dir", temp_dir,
            magnet
        ])

        try:
            subprocess.run(cmd, check=True, timeout=60)
            
            # 检查aria2c是否在临时目录中创建了它的文件
            if os.path.isfile(aria2_temp_filepath):
                logging.info(f"aria2c 创建了临时文件，正在移动并重命名为 {final_filename}")
                # 将文件从临时目录移动并重命名到最终目的地 os.rename(aria2_temp_filepath, final_filepath)
                # 使用 shutil.move 而不是 os.rename 以支持跨文件系统移动
                shutil.move(aria2_temp_filepath, final_filepath)
                return final_filepath
            else:
                logging.error(f"aria2c 运行了但未创建预期的临时文件: {aria2_hash_filename}")
                return None
        except FileNotFoundError:
            logging.error("`aria2c` 命令未找到。请确保 aria2 已安装并在您的PATH中。")
            raise
        except subprocess.CalledProcessError as e:
            logging.error(f"aria2c 执行失败: {e}")
            return None
        except subprocess.TimeoutExpired:
            logging.error("aria2c 获取元数据超时。")
            return None


def get_omdb_rating(imdb_id):
    """使用OMDb API根据给定的IMDb ID获取官方IMDb评分。"""
    if not imdb_id or not imdb_id.startswith('tt'):
        return 0.0

    url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={api_key}"

    try:
        response = requests.get(url, proxies=proxies, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("Response") == "True":
            rating_str = data.get("imdbRating", "N/A")
            if rating_str != "N/A":
                rating = float(rating_str)
                logging.info(f"找到 IMDb 评分 {imdb_id}: {rating}")
                return rating
        else:
            logging.warning(f"OMDb API 错误 {imdb_id}: {data.get('Error')}")
        time.sleep(3)  # 遵守API速率限制
        return 5.0

    except requests.exceptions.RequestException as e:
        logging.error(f"从 OMDb 获取评分失败 {imdb_id}: {e}")
        return 5.0
    except (ValueError, KeyError) as e:
        logging.error(f"解析 OMDb 响应失败 {imdb_id}: {e}")
        return 5.0
    finally:
        time.sleep(1)

# 从海盗湾特定用户页面提取满足x265 + 1080p条件的种子
def piratebay(url="https://thepiratebay.org/search.php?q=user:Saturn5:0"):
    try:
        # 提取搜索查询参数
        query_params = url.split('?')[1] if '?' in url else 'q=user:Saturn5:0'
        api_url = f"https://apibay.org/q.php?{query_params}&format=json"
        logging.info(f"尝试通过API获取数据: {api_url}")
        
        # 重试机制
        max_retries = 3
        retry_count = 0
        api_response = None
        
        while retry_count < max_retries:
            try:
                api_response = requests.get(
                    api_url, 
                    proxies=proxies, 
                    timeout=15,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                )
                api_response.raise_for_status()
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                retry_count += 1
                if retry_count >= max_retries:
                    raise
                logging.warning(f"连接失败，第{retry_count}次重试... 错误: {str(e)[:100]}")
                time.sleep(2)
        
        if not api_response:
            raise Exception("无法获取API响应")
        
        # 解析JSON数据
        torrents_data = api_response.json()
        logging.info(f"通过API获取到 {len(torrents_data)} 个种子数据")
        
        # 确保目录存在
        os.makedirs(torrents_path, exist_ok=True)
        
        found_count = 0
        saved_count = 0
        
        for torrent in torrents_data:
            title = torrent.get('name', '')
            imdb_id = torrent.get('imdb', '')
            
            # 获取评分
            rating = get_omdb_rating(imdb_id)
            title_upper = title.upper()

            # 根据标题、x265、1080p、评分以及关键字(CAM, HDRIP)进行过滤
            if ('X265' in title_upper and '1080P' in title_upper and 
                rating >= 5.0 and  ('CAM' not in title and 'HDRIP' not in title_upper)):
                
                info_hash = torrent.get('info_hash', '')
                if info_hash:
                    # 构建磁力链接，确保URL编码正确
                    encoded_title = urllib.parse.quote(title)
                    magnet_link = f"magnet:?xt=urn:btih:{info_hash}&dn={encoded_title}"
                    
                    # 添加tracker
                    trackers = [
                        'udp://tracker.opentrackr.org:1337/announce',
                        'udp://open.tracker.cl:1337/announce',
                        'udp://p4p.arenabg.com:1337/announce',
                        'udp://tracker.torrent.eu.org:451/announce',
                        'udp://exodus.desync.com:6969/announce'
                    ]
                    for tracker in trackers:
                        magnet_link += f"&tr={urllib.parse.quote(tracker)}"
                    
                    logging.info(f"找到满足条件的种子：{title} (IMDb 评分: {rating:.1f})")
                    found_count += 1
                    
                    try:
                        # 将 magnet, title, 和 info_hash 传递给辅助函数
                        saved_path = magnet2torrent(magnet_link, title, info_hash)
                        
                        if saved_path:
                            saved_count += 1

                    except Exception as e:
                        logging.error(f"An unexpected error occurred during aria2c conversion for '{title}': {e}")
            else:
                logging.info(f"跳过种子: {title} (IMDb 评分: {rating:.1f}) - 不满足过滤要求: x265, 1080p, 评分>=5.0, 无 CAM/HDRIP")

        
        logging.info(f"成功创建 {saved_count} 个种子文件到 {torrents_path}")
        
    except Exception as e:
        logging.error(f"处理过程中发生错误: {e}")

if __name__ == "__main__":
    # 获取命令行参数
    try: parameter = sys.argv[1]
    except IndexError: parameter = "default"
    
    if parameter == "DS90":
        logging.info(f"脚本在群晖NAS服务器上运行: {sys.argv[0]} {parameter}")
        # organize_downloads_folders("/volume1/Downloads", "/volume3/X-Movie", "/volume2/MOVIE")
    elif parameter == "F:":
        logging.info(f"脚本在 NetDrive 客户端 Windows 上运行: {sys.argv[0]} {parameter}")
        # organize_downloads_folders("F:\\Downloads", "F:\\X-Movie", "F:\\MOVIE")

    logging.info(f"种子文件保存路径： {torrents_path}")
    
    piratebay(url="https://thepiratebay.org/search.php?q=user:BONE:0")
    piratebay(url="https://thepiratebay.org/search.php?q=user:Saturn5:2")
    piratebay(url="https://thepiratebay.org/search.php?q=user:Saturn5:1")
    piratebay(url="https://thepiratebay.org/search.php?q=user:Saturn5:0")
    