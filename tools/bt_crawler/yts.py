import re
from datetime import datetime
import logging
import hashlib
import time
import requests
from bs4 import BeautifulSoup
import os
import sys
import shutil
import time

# 设置日志级别
logging.basicConfig(level=logging.DEBUG)
torrents_path = "/volume1/Downloads/torrent.files" # NAS上存放种子文件的目录 "F:\\Downloads\\torrent.files"
SECRET_KEY = "08b473c56a51c9fc2a88e34bd44974040916baaaee9cc6b66116b7b9b0d407b5"
BASE_URL = "https://v.niff.cn/yts.php"
# 设置代理
proxies = {
    'http': 'http://127.0.0.1:7890',
    'https': 'http://127.0.0.1:7890',
}
proxies = {} # 不使用代理
'''
<div class="modal-content">
                                            
                        <div class="modal-torrent">
                            <div class="modal-quality" id="modal-quality-720p"><span>720p</span></div>
                            <p class="quality-size">WEB </p>
                            <br>
                            <p>文件大小</p>
                            <p class="quality-size">552 MB</p>
                            <a class="download-torrent button-green-download2-big" href="https://yts.mx/torrent/download/AC2ED93BCDDF2405C587830F021D4981DB137CB3" rel="nofollow" title="下载 Diddy: Monster's Fall 720p Torrent"><span class="icon-in"></span>下载</a>
                            <a data-torrent-id="143500" href="magnet:?xt=urn:btih:AC2ED93BCDDF2405C587830F021D4981DB137CB3&amp;dn=Diddy%3A+Monster%27s+Fall+%282025%29+%5B720p%5D+%5BYTS.MX%5D&amp;tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Fopen.tracker.cl%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Fp4p.arenabg.com%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce&amp;tr=udp%3A%2F%2Ftracker.dler.org%3A6969%2Fannounce&amp;tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&amp;tr=udp%3A%2F%2Fipv4.tracker.harry.lu%3A80%2Fannounce&amp;tr=https%3A%2F%2Fopentracker.i2p.rocks%3A443%2Fannounce" class="magnet-download download-torrent magnet" title="下载 Diddy: Monster's Fall 720p Magnet" rel="nofollow"><span>Magnet</span></a>
                        </div>
                                            
                        <div class="modal-torrent">
                            <div class="modal-quality" id="modal-quality-1080p"><span>1080p</span></div>
                            <p class="quality-size">WEB </p>
                            <br>
                            <p>文件大小</p>
                            <p class="quality-size">1023.62 MB</p>
                            <a class="download-torrent button-green-download2-big" href="https://yts.mx/torrent/download/C511A840E4F624947E0245D49BEC7E715EC706C1" rel="nofollow" title="下载 Diddy: Monster's Fall 1080p Torrent"><span class="icon-in"></span>下载</a>
                            <a data-torrent-id="143501" href="magnet:?xt=urn:btih:C511A840E4F624947E0245D49BEC7E715EC706C1&amp;dn=Diddy%3A+Monster%27s+Fall+%282025%29+%5B1080p%5D+%5BYTS.MX%5D&amp;tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Fopen.tracker.cl%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Fp4p.arenabg.com%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce&amp;tr=udp%3A%2F%2Ftracker.dler.org%3A6969%2Fannounce&amp;tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&amp;tr=udp%3A%2F%2Fipv4.tracker.harry.lu%3A80%2Fannounce&amp;tr=https%3A%2F%2Fopentracker.i2p.rocks%3A443%2Fannounce" class="magnet-download download-torrent magnet" title="下载 Diddy: Monster's Fall 1080p Magnet" rel="nofollow"><span>Magnet</span></a>
                        </div>
                                            
                        <div class="modal-torrent">
                            <div class="modal-quality" id="modal-quality-1080p"><span>1080p</span></div>
                            <p class="quality-size">WEB<small><font color="green">.x265.10bit</font></small> </p>
                            <br>
                            <p>文件大小</p>
                            <p class="quality-size">917.32 MB</p>
                            <a class="download-torrent button-green-download2-big" href="https://yts.mx/torrent/download/F9C89739B1C7EA2CC13B9F29154C273AC237F8CF" rel="nofollow" title="下载 Diddy: Monster's Fall 1080p Torrent"><span class="icon-in"></span>下载</a>
                            <a data-torrent-id="143591" href="magnet:?xt=urn:btih:F9C89739B1C7EA2CC13B9F29154C273AC237F8CF&amp;dn=Diddy%3A+Monster%27s+Fall+%282025%29+%5B1080p%5D+%5BYTS.MX%5D&amp;tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Fopen.tracker.cl%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Fp4p.arenabg.com%3A1337%2Fannounce&amp;tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce&amp;tr=udp%3A%2F%2Ftracker.dler.org%3A6969%2Fannounce&amp;tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&amp;tr=udp%3A%2F%2Fipv4.tracker.harry.lu%3A80%2Fannounce&amp;tr=https%3A%2F%2Fopentracker.i2p.rocks%3A443%2Fannounce" class="magnet-download download-torrent magnet" title="下载 Diddy: Monster's Fall 1080p Magnet" rel="nofollow"><span>Magnet</span></a>
                        </div>
                                    </div>
            </div>
'''
def regular_filename(filename):
    # 处理文件名：去掉空格、括号和方括号，并用点分隔    
    filename = re.sub(r'[\[\]\(\)（）【】　]', ' ', filename.strip())  # 替换括号和方括号等
    filename = re.sub(r'www\.\S+\.com', '', filename)  # 去除含 www.开头和以 .com 结尾的域名的字符串
    filename = re.sub(r'\s+', '.', filename.strip()) # 替换连续的空格为一个.
    # 使用正则表达式去除多余的点,将两个及以上的点替换为一个点
    filename = re.sub(r'\.{2,}', '.', filename) 
    # 替换Windows和类Unix系统中的非法字符
    illegal_chars = r'[<>:"/\\|?*:]'
    filename = re.sub(illegal_chars, '_', filename)
    return filename

def clean_folder (folder_path):
    # 遍历文件夹中的所有文件和子目录
    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)        
        # 删除所有 .jpg 和 .txt 文件
        if item.endswith('.jpg') or item.endswith('.txt'):
            os.remove(item_path)
            logging.info(f"已删除文件: {item_path}")        
        # 删除 Subs 子目录
        elif item == 'Subs' and os.path.isdir(item_path):
            shutil.rmtree(item_path)
            logging.info(f"已删除子目录: {item_path}")
# 这几个函数：regular_filename clean_folder organize_downloads_folders 功能都已迁移至另github项目中被替代，此处仅保留原代码
def organize_downloads_folders(source_directory, mov_1080p_dir, mov_2160p_dir):
    # 遍历源目录中的所有文件夹
    for folder_name in os.listdir(source_directory):
        folder_path = os.path.join(source_directory, folder_name)
        try:
            # 检查是否为文件夹
            if os.path.isdir(folder_path):
                
                # 处理文件夹名
                new_folder_name = regular_filename(folder_name)
                new_folder_path = os.path.join(source_directory, new_folder_name)

                # 重命名文件夹
                if folder_path != new_folder_path:
                    os.rename(folder_path, new_folder_path)
                    logging.info(f"重命名文件夹: {folder_name} -> {new_folder_name}")

                if '2160p' in new_folder_name.lower() or '4k' in new_folder_name.lower():
                    target_folder = mov_2160p_dir
                else:
                    target_folder = mov_1080p_dir
                # 检查文件夹名中是否包含年份信息，且从后向前提取年份信息
                year_matchs = re.findall(r'\b19|20\d{2}\b', new_folder_name)
                # for year in year_matchs:  print(year)
                if year_matchs and (not re.search(r'S\d{2}(E\d{2})?', new_folder_name.upper(), re.IGNORECASE)):
                    year = year_matchs[-1] # 从后向前提取年份避免：2073.2024.1080p.WEBRip.x265 这样的
                    target_year_folder = os.path.join(target_folder, year)

                    # 创建年份目录（如果不存在）
                    os.makedirs(target_year_folder, exist_ok=True)
                    logging.debug(f"年份目录：{year} --> {target_year_folder}")

                    # 移动文件夹到对应的年份目录
                    clean_folder (new_folder_path) # 移动之前先清除文件夹下一些无用的文件
                    logging.info(f"正在移动文件夹: {new_folder_name} -> {target_year_folder}")
                    shutil.move(new_folder_path, target_year_folder)
        except Exception as e:
            logging.debug("Except Error: %s", e)

def download_torrents(movie_link):
    """下载电影页面中的 BT 种子和磁力链接"""
    response = requests.get(getUrlPHP(movie_link), proxies=proxies)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    # 查找 id 为 movie-content 的 div 元素
    movie_content = soup.find('div', id='movie-content')
    # logging.debug(f"HTML LINE: {movie_content}")
    
    if movie_content:
        # 查找所有 modal-torrent 元素
        torrents = movie_content.find_all('div', class_='modal-torrent')
        
        for torrent in torrents:
            try :
                # 查找 1080p x265 或 4k 2160p 的链接
                quality = torrent.find('div', class_='modal-quality').text.strip()            
                quality_size = torrent.find('p', class_='quality-size').text.strip()
                # 获取 BT 下载链接
                bt_link = torrent.find('a', class_='download-torrent')['href']
                # 获取磁力链接
                magnet_link = torrent.find('a', class_='magnet-download')['href']
                # 输出提取的信息
                logging.info(f"分辨率: {quality}, 尺寸规格: {quality_size}, BT链接: {bt_link}") # , 磁力链接: {magnet_link}")        
                if 'x265' in quality_size and quality in ["1080p", "2160p"]: # 仅下载 x265 编码 1080p 或 4k 的BT种子
                    bt_response = requests.get(getUrlPHP(bt_link), proxies=proxies)
                    bt_response.raise_for_status()
                    # 尝试从响应头中获取文件名, 如果没有 Content-Disposition 头，使用默认名称
                    filename = f"{quality}.torrent"
                    content_disposition = bt_response.headers.get('Content-Disposition')
                    if content_disposition:
                        # 使用正则表达式提取文件名
                        filename_match = re.findall('filename="(.+?)"', content_disposition)
                        if filename_match: filename = filename_match[0]
                    filename = os.path.join(torrents_path, regular_filename(filename))
                    logging.debug(f"{os.path.isfile(filename+'.loaded')} : {filename+'.loaded'}")
                    if os.path.isfile(filename+'.loaded'): # 如果存在 .loaded 后缀文件则表示已经下载过
                        logging.info(f"已下载过种子文件: {filename} ，本次下载跳过")
                    else:
                        with open(filename, 'wb') as file: file.write(bt_response.content)
                        logging.info(f"下载了种子文件: {filename}")
            except Exception as e:
                logging.debug("Except Error: %s", e)

def yts_browse_movies(url="https://yts.mx/"):  
    # 发送请求 response = requests.get(url, proxies=proxies)
    response = requests.get(url, proxies=proxies)
    response.raise_for_status()  # 确保请求成功
    logging.debug(f"HTML LINE: {response}")

    # 解析网页内容
    soup = BeautifulSoup(response.text, 'html.parser')

    # 创建一个文件夹来保存下载的种子文件
    # os.makedirs(torrents_path, exist_ok=True)

    # 查找所有电影条目  <div class="browse-movie-wrap col-xs-10 col-sm-4 col-md-5 col-lg-4">
    movies = soup.find_all('div', class_='browse-movie-wrap')
    # logging.info(f"HTML LINE: {movies}")

    # 遍历每部电影，获取种子下载链接
    for movie in movies:
        # title = movie.h2.text.strip()  # 获取电影标题
        # torrent_link = movie.find('a', class_='torrent')['href']  # 获取种子链接
        # 获取评分
        try :
            rating_str = movie.find('h4', class_='rating').text.strip() if movie.find('h4', class_='rating') else 'N/A'
            # 提取数字部分 rating = float(rating_str.split(' / ')[0]) if ' / ' in rating_str else None
            # 使用正则表达式提取数字
            match = re.search(r'(\d+\.\d+)', rating_str)
            rating = float(match.group(1)) if match else 0.0
            
            # 获取电影详情页链接
            browse_movie_link = movie.find('a', class_='browse-movie-link')['href']
            
            # 获取电影标题
            browse_movie_title = movie.find('a', class_='browse-movie-title').text.strip()
            
            # 获取电影年份, 使用了海象运算符（:=），可以在一行中赋值并进行判断。在 Python 3.8 及以上版本中可用
            # browse_movie_year = int((year := movie.find('div', class_='browse-movie-year').text.strip()) if year else 0)
            # 获取电影年份，检查是否为 None 并转换为正整形
            browse_movie_year = movie.find('div', class_='browse-movie-year')            
            if browse_movie_year is not None: 
                try:
                    # 提取年份字符串并清理，只保留数字部分
                    year_text = browse_movie_year.text.strip()
                    # 如果包含换行符或空格，只取第一部分
                    year_text = year_text.split()[0]
                    browse_movie_year = int(year_text)
                except (ValueError, IndexError):
                    logging.debug("年份解析错误，使用默认值0: %s", browse_movie_year.text.strip())
                    browse_movie_year = 0
            else: 
                browse_movie_year = 0
            
            # 获取图片链接
            img_src = movie.find('img', class_='img-responsive')['src']

            # 输出提取的信息
            logging.info(f"标题: {browse_movie_title}, 年份: {browse_movie_year}, 评分: {rating}, 链接: {browse_movie_link}, 图片: {img_src}")        
            # 下载评分在 5.5 以上的今年或去年的电影种子
            if rating>=5.5 and browse_movie_year >= (datetime.now().year-1): 
                download_torrents(browse_movie_link)
        except Exception as e:
            logging.debug("Except Error: %s", e)


# 通过YTS API获取电影信息并直接下载.torrent文件。
def yts_movies_api(API_URL = "https://yts.mx/api/v2/list_movies.json"):

    params = {
        "minimum_rating": 5.0,
        "quality": "1080p",
        "limit": 50,
        "sort_by": "date_added",
        # "video_codec":"x265",
    }

    try:
        # response = requests.get(API_URL, params=params, proxies=proxies, timeout=10)
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data["status"] != "ok" or data["data"].get("movie_count", 0) == 0:
            logging.warning("YTS API: 未找到满足条件的电影。")
            return

        movies = data["data"]["movies"]
        logging.info(f"YTS API: 找到 {len(movies)} 部电影。")

        for movie in movies:
            title = movie.get("title_long", "Unknown Movie")
            
            target_torrent = None
            for t in movie.get("torrents", []):
                if t.get("quality") == params.get("quality"):
                    target_torrent = t
                    break
            
            if not target_torrent:
                logging.warning(f"跳过 '{title}', 未找到 '{params.get('quality')}' 画质的种子。")
                continue

            torrent_url = target_torrent.get("url")
            if not torrent_url:
                logging.warning(f"跳过 '{title}', 种子链接不存在。")
                continue

            logging.info(f"YTS: 正在从 {torrent_url} 下载 '{title}' 的种子文件")
            try:
                torrent_response = requests.get(getUrlPHP(torrent_url), proxies=proxies, timeout=20)
                torrent_response.raise_for_status()

                # 优先尝试从响应头中获取文件名
                final_filename = None
                content_disposition = torrent_response.headers.get('Content-Disposition')
                if content_disposition:
                    filename_match = re.search(r'filename="(.+?)"', content_disposition)
                    if filename_match:
                        final_filename = filename_match.group(1)
                        logging.info(f"从响应头中找到文件名: {final_filename}")

                # 如果响应头中没有文件名，则使用备选方案
                if not final_filename:
                    final_filename = regular_filename(title) + '.torrent'
                    logging.info(f"响应头中未找到文件名，使用标题生成: {final_filename}")

                final_filepath = os.path.join(torrents_path, final_filename)

                try:
                    if os.path.isfile(final_filepath) or os.path.isfile(final_filepath + ".loaded"):
                        logging.info(f"YTS: 种子文件 '{final_filename}' 已存在，跳过。")
                        continue

                    with open(final_filepath, 'wb') as f:
                        f.write(torrent_response.content)
                    logging.info(f"YTS: 成功保存种子文件到 {final_filepath}")
                except (IOError, OSError) as e:
                    logging.error(f"YTS: 保存种子文件 '{final_filename}' 失败: {e}")
                    # 继续处理下一个种子，不中断程序

            except requests.exceptions.RequestException as e:
                logging.error(f"YTS: 下载 '{title}' 的种子失败: {e}")

    except Exception as e:
        logging.error(f"获取YTS API时发生错误: {e}")

# elite4piratebay 已经是老的代码不再使用，仅作保留用，新代码已移至 torrent.py
def elite4piratebay(url="https://thepiratebay.org/search.php?q=user:Saturn5:threedays"):
    """通过API从海盗湾特定用户页面提取满足x265 + 1080p条件的磁力链接并下载种子文件"""
    try:
        # 提取搜索查询参数
        query_params = url.split('?')[1] if '?' in url else 'q=user:Saturn5:threedays'
        api_url = f"https://apibay.org/q.php?{query_params}&format=json"
        logging.info(f"尝试通过API获取数据: {api_url}")
        
        # 添加重试机制，最多重试3次
        max_retries = 3
        retry_count = 0
        api_response = None
        
        while retry_count < max_retries:
            try:
                # 发送API请求，设置适当的超时和重试策略
                api_response = requests.get(
                    api_url, 
                    proxies=proxies, 
                    timeout=15,  # 增加超时时间
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                )
                api_response.raise_for_status()
                break  # 成功获取响应后跳出循环
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                retry_count += 1
                if retry_count >= max_retries:
                    raise  # 达到最大重试次数后抛出异常
                logging.warning(f"连接失败，第{retry_count}次重试... 错误: {str(e)[:100]}")
                time.sleep(2)  # 等待2秒后重试
        
        if not api_response:
            raise Exception("无法获取API响应")
        
        # 解析JSON数据
        torrents_data = api_response.json()
        logging.info(f"通过API获取到 {len(torrents_data)} 个种子数据")
        
        # 确保torrents_path目录存在
        os.makedirs(torrents_path, exist_ok=True)
        
        # 过滤满足x265 + 1080p条件的种子
        found_count = 0
        downloaded_count = 0
        
        for torrent in torrents_data:
            title = torrent.get('name', '')
            if 'x265' in title.lower() and '1080p' in title.lower():
                # 构建磁力链接
                info_hash = torrent.get('info_hash', '')
                if info_hash:
                    magnet_link = f"magnet:?xt=urn:btih:{info_hash}&dn={title}&tr=udp://tracker.coppersurfer.tk:6969/announce&tr=udp://9.rarbg.to:2710/announce&tr=udp://9.rarbg.me:2710/announce&tr=udp://tracker.opentrackr.org:1337&tr=udp://exodus.desync.com:6969"
                    logging.info(f"通过API找到满足条件的种子：")
                    logging.info(f"标题: {title}")
                    logging.info(f"磁力链接: {magnet_link}")
                    found_count += 1
                    
                    # 尝试下载种子文件
                    try:
                        # 生成种子文件名
                        filename = os.path.join(torrents_path, regular_filename(title) + '.torrent')
                        loaded_marker = filename + '.loaded'
                        
                        # 检查文件是否已下载
                        if os.path.isfile(loaded_marker):
                            logging.info(f"已下载过种子文件: {filename} ，本次跳过")
                            continue
                        
                        # 使用更可靠的方式获取种子文件
                        # 添加重试机制和备用API
                        max_download_retries = 2
                        download_retry_count = 0
                        downloaded = False
                        
                        while download_retry_count < max_download_retries and not downloaded:
                            try:
                                # 方法1：尝试使用torrage.info获取种子文件
                                torrent_api_url = f"https://torrage.info/torrent/{info_hash}.torrent"
                                
                                torrent_response = requests.get(
                                    torrent_api_url,
                                    proxies=proxies,
                                    timeout=20,
                                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                                )
                                
                                if torrent_response.status_code == 200 and len(torrent_response.content) > 0:
                                    # 保存种子文件
                                    with open(filename, 'wb') as file:
                                        file.write(torrent_response.content)
                                    
                                    # 创建已加载标记文件
                                    with open(loaded_marker, 'w') as f:
                                        f.write(f"Downloaded on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nInfo Hash: {info_hash}\nMagnet: {magnet_link}")
                                    
                                    logging.info(f"成功下载种子文件: {filename}")
                                    downloaded_count += 1
                                    downloaded = True
                                else:
                                    # 如果torrage失败，尝试使用itorrents作为备用
                                    logging.warning(f"torrage.info下载失败，尝试备用API...")
                                    torrent_api_url = f"https://itorrents.org/torrent/{info_hash}.torrent"
                                    
                                    torrent_response = requests.get(
                                        torrent_api_url,
                                        proxies=proxies,
                                        timeout=20,
                                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                                    )
                                    
                                    if torrent_response.status_code == 200 and len(torrent_response.content) > 0:
                                        with open(filename, 'wb') as file:
                                            file.write(torrent_response.content)
                                        
                                        with open(loaded_marker, 'w') as f:
                                            f.write(f"Downloaded on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nInfo Hash: {info_hash}\nMagnet: {magnet_link}")
                                        
                                        logging.info(f"成功下载种子文件: {filename}")
                                        downloaded_count += 1
                                        downloaded = True
                                    else:
                                        # 如果所有API都失败，记录磁力链接
                                        logging.warning(f"无法获取种子文件，磁力链接已记录")
                                        
                                        # 保存磁力链接到文本文件
                                        magnet_links_file = os.path.join(torrents_path, "magnet_links.txt")
                                        with open(magnet_links_file, 'a', encoding='utf-8') as f:
                                            f.write(f"{title}\n{magnet_link}\n\n")
                                        
                                        downloaded = True  # 标记为已处理，避免无限重试
                            except Exception as e:
                                download_retry_count += 1
                                logging.warning(f"下载尝试 {download_retry_count} 失败: {str(e)[:100]}")
                                if download_retry_count >= max_download_retries:
                                    # 保存磁力链接到文本文件
                                    magnet_links_file = os.path.join(torrents_path, "magnet_links.txt")
                                    with open(magnet_links_file, 'a', encoding='utf-8') as f:
                                        f.write(f"{title}\n{magnet_link}\n\n")
                                    
                                    logging.warning(f"已将磁力链接保存到 {magnet_links_file}")
                                time.sleep(1)  # 等待1秒后重试
                    except Exception as e:
                        logging.error(f"下载种子文件时出错({title}): {str(e)[:100]}")
                        # 继续处理下一个，不中断整个过程
        
        logging.info(f"总计找到 {found_count} 个满足x265 + 1080p条件的种子")
        logging.info(f"成功下载 {downloaded_count} 个种子文件到 {torrents_path}")
        
    except requests.exceptions.ConnectionError as e:
        logging.error(f"连接API时出错: {e}")
    except requests.exceptions.Timeout as e:
        logging.error(f"API请求超时: {e}")
    except ValueError as e:
        logging.error(f"解析API响应JSON失败: {e}")
    except Exception as e:
        logging.error(f"获取种子数据时发生错误: {e}")

def getUrlPHP (q=1):
        timestamp = str(int(time.time()))
        signature = hashlib.sha256((timestamp + str(q) + SECRET_KEY).encode()).hexdigest()
        return f"{BASE_URL}?q={q}&timestamp={timestamp}&signature={signature}"       

if __name__ == "__main__":
    # 获取命令行参数
    try: parameter = sys.argv[1]
    except IndexError: parameter = "default"
    # 字符串参数比较
    if parameter == "DS90":
        logging.info(f"脚本在群晖NAS服务器上运行: {sys.argv[0]} {parameter}")
        organize_downloads_folders("/volume1/Downloads", "/volume3/X-Movie", "/volume2/MOVIE")     
    else:        
        if parameter == "F:":
            logging.info(f"脚本在 NetDrive 客户端 Windows 上运行: {sys.argv[0]} {parameter}")
            organize_downloads_folders("F:\\Downloads", "F:\\X-Movie", "F:\\MOVIE")
        # download_torrents ("https://yts.mx/movies/diddy-monsters-fall-2025")

        yts_browse_movies (getUrlPHP(1)) # "https://yoursite.com/yts.php?q=1" 代理转发默认参数就是首页：https://yts.mx/
        yts_browse_movies (getUrlPHP(2)) # "https://yoursite.com/yts.php?q=2" 代理转发页面：https://yts.mx/browse-movies/0/all/all/0/featured/0/all
        yts_browse_movies (getUrlPHP(3)) # "https://yoursite.com/yts.php?q=3" 代理转发页面：https://yts.mx/trending-movies
        yts_movies_api(getUrlPHP(0)) # "https://yoursite.com/yts.php?q=0" 代理实际请求页面：https://yts.mx/api/v2/list_movies.json
    

    '''
    # 下载种子文件
    torrent_response = requests.get(torrent_link, proxies=proxies)
    torrent_response.raise_for_status()  # 确保请求成功

    # 保存种子文件
    filename = os.path.join('torrents', f"{title}.torrent")
    with open(filename, 'wb') as file:
        file.write(torrent_response.content)

    print(f"下载了种子文件: {title}.torrent")


    <div class="browse-movie-wrap col-xs-10 col-sm-4 col-md-5 col-lg-4">
                            <a href="https://yts.mx/movies/2073-2024" class="browse-movie-link">
                                <figure>
                                    <img class="img-responsive" src="https://img.yts.mx/assets/images/movies/2073_2024/medium-cover.jpg" alt="2073 (2024) 下载" width="170" height="255">
                                    <figcaption class="hidden-xs hidden-sm">
                                        <span class="icon-star"></span>
                                        <h4 class="rating">5.2 / 10</h4>                                                                                    <h4>Documentary</h4>
                                                                                    <h4>Thriller</h4>
                                                                                <span class="button-green-download2-big">查看详情</span>
                                    </figcaption>
                                </figure>
                            </a>

                            <div class="browse-movie-bottom">
                                <a href="https://yts.mx/movies/2073-2024" class="browse-movie-title">2073</a>
                                <div class="browse-movie-year">2024</div>
                                                            </div>



                                                            
import requests

# 替换为您的 Access Token
access_token = "your_access_token"

# 替换为目标文件路径和上传的文件名
file_path = "path/to/your/file.txt"
file_name = "file.txt"

# 获取上传地址
upload_url = "https://api.aliyundrive.com/v2/file/create"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}
data = {
    "drive_id": "your_drive_id",
    "parent_file_id": "root",
    "name": file_name,
    "type": "file"
}
response = requests.post(upload_url, headers=headers, json=data, proxies=proxies)
upload_info = response.json()

# 上传文件
with open(file_path, "rb") as f:
    upload_response = requests.put(upload_info["upload_url"], data=f, proxies=proxies)

if upload_response.status_code == 200:
    print("文件上传成功！")
else:
    print("文件上传失败！")

import hashlib
import time
import requests

SECRET_KEY = "your_secret_key_change_this_to_random_string"
BASE_URL = "https://yoursite.com/yts.php"

def make_request(q):
    timestamp = str(int(time.time()))
    signature = hashlib.sha256((timestamp + q + SECRET_KEY).encode()).hexdigest()
    
    url = f"{BASE_URL}?q={q}&timestamp={timestamp}&signature={signature}"
    response = requests.get(url)
    return response.text

# 使用示例
result = make_request("0")
print(result)
'''