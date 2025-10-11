#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
媒体文件扫描器
负责扫描指定目录，识别电影和电视剧文件，提取元数据
"""

import os
import re
import json
import hashlib
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from ..database.db_manager import get_db_manager

class MediaFileScanner:
    """媒体文件扫描器"""
    
    def __init__(self, max_workers: int = 4):
        """
        初始化扫描器
        
        Args:
            max_workers: 最大并发扫描线程数
        """
        self.db = get_db_manager()
        self.max_workers = max_workers
        self.logger = logging.getLogger(__name__)
        
        # 从数据库获取配置
        self.video_extensions = set(self.db.get_setting('video_extensions', [
            'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v', '3gp', 'ts', 'm2ts'
        ]))
        self.min_file_size = self.db.get_setting('min_file_size', 104857600)  # 100MB
        
        # 编译正则表达式
        self._compile_patterns()
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 统计信息
        self.stats = {
            'files_scanned': 0,
            'files_added': 0,
            'files_updated': 0,
            'files_skipped': 0,
            'errors': 0
        }
    
    def _compile_patterns(self):
        """编译文件名识别的正则表达式"""
        
        # 电影文件名模式
        self.movie_patterns = [
            # Movie.Name.2023.1080p.BluRay.x264-GROUP
            re.compile(r'^(.+?)[\.\s]+(\d{4})[\.\s]+.*$', re.IGNORECASE),
            # Movie Name (2023)
            re.compile(r'^(.+?)\s*\((\d{4})\).*$', re.IGNORECASE),
            # Movie.Name.2023
            re.compile(r'^(.+?)[\.\s]+(\d{4}).*$', re.IGNORECASE),
        ]
        
        # 电视剧文件名模式
        self.tv_patterns = [
            # Show.Name.S01E01.Episode.Title.1080p.WEB-DL.x264-GROUP
            re.compile(r'^(.+?)[\.\s]+[Ss](\d{1,2})[Ee](\d{1,2}).*$', re.IGNORECASE),
            # Show Name - S01E01 - Episode Title
            re.compile(r'^(.+?)\s*-\s*[Ss](\d{1,2})[Ee](\d{1,2}).*$', re.IGNORECASE),
            # Show.Name.1x01.Episode.Title
            re.compile(r'^(.+?)[\.\s]+(\d{1,2})x(\d{1,2}).*$', re.IGNORECASE),
            # Show Name 101 (season 1, episode 1)
            re.compile(r'^(.+?)[\.\s]+(\d)(\d{2})[\.\s]+.*$', re.IGNORECASE),
        ]
        
        # 质量信息提取模式
        self.quality_patterns = {
            'resolution': re.compile(r'(2160p|1080p|720p|480p|360p)', re.IGNORECASE),
            'source': re.compile(r'(BluRay|BDRip|WEB-DL|WEBRip|HDTV|DVDRip|Remux)', re.IGNORECASE),
            'codec': re.compile(r'(HEVC|H\.?265|H\.?264|x264|x265|AVC)', re.IGNORECASE),
            'release_group': re.compile(r'-([A-Za-z0-9]+)(?:\[.*\])?$'),
        }
    
    def scan_directory(self, scan_path: str, recursive: bool = True) -> Dict[str, Any]:
        """
        扫描指定目录
        
        Args:
            scan_path: 扫描路径
            recursive: 是否递归扫描子目录
            
        Returns:
            扫描结果统计
        """
        self.logger.info(f"开始扫描目录: {scan_path}")
        
        # 记录扫描开始
        scan_id = self._start_scan_record(scan_path)
        
        try:
            # 重置统计
            self.stats = {
                'files_scanned': 0,
                'files_added': 0,
                'files_updated': 0,
                'files_skipped': 0,
                'errors': 0
            }
            
            # 收集所有视频文件
            video_files = self._collect_video_files(scan_path, recursive)
            self.logger.info(f"发现 {len(video_files)} 个视频文件")
            
            # 并发处理文件
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(self._process_file, file_path): file_path 
                    for file_path in video_files
                }
                
                for future in as_completed(futures):
                    file_path = futures[future]
                    try:
                        result = future.result()
                        if result:
                            with self._lock:
                                if result['action'] == 'added':
                                    self.stats['files_added'] += 1
                                elif result['action'] == 'updated':
                                    self.stats['files_updated'] += 1
                                else:
                                    self.stats['files_skipped'] += 1
                    except Exception as e:
                        self.logger.error(f"处理文件失败 {file_path}: {e}")
                        with self._lock:
                            self.stats['errors'] += 1
                    
                    with self._lock:
                        self.stats['files_scanned'] += 1
                        
                        # 每处理100个文件输出一次进度
                        if self.stats['files_scanned'] % 100 == 0:
                            self.logger.info(f"已处理 {self.stats['files_scanned']}/{len(video_files)} 个文件")
            
            # 更新扫描记录
            self._complete_scan_record(scan_id, 'completed', self.stats)
            
            self.logger.info(f"扫描完成: {self.stats}")
            return self.stats
            
        except Exception as e:
            self.logger.error(f"扫描失败: {e}")
            self._complete_scan_record(scan_id, 'failed', self.stats, str(e))
            raise
    
    def _collect_video_files(self, scan_path: str, recursive: bool) -> List[str]:
        """收集所有视频文件路径"""
        video_files = []
        
        try:
            path_obj = Path(scan_path)
            if not path_obj.exists():
                raise FileNotFoundError(f"扫描路径不存在: {scan_path}")
            
            # 使用glob模式匹配视频文件
            patterns = [f"*.{ext}" for ext in self.video_extensions]
            
            for pattern in patterns:
                if recursive:
                    files = path_obj.rglob(pattern)
                else:
                    files = path_obj.glob(pattern)
                
                for file_path in files:
                    if file_path.is_file() and file_path.stat().st_size >= self.min_file_size:
                        # 跳过样本文件
                        if not self._is_sample_file(str(file_path)):
                            video_files.append(str(file_path))
            
            return sorted(video_files)
            
        except Exception as e:
            self.logger.error(f"收集视频文件失败: {e}")
            return []
    
    def _is_sample_file(self, file_path: str) -> bool:
        """判断是否为样本文件"""
        file_name = os.path.basename(file_path).lower()
        sample_keywords = ['sample', 'trailer', 'preview', 'demo']
        return any(keyword in file_name for keyword in sample_keywords)
    
    def _process_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        处理单个文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            处理结果
        """
        try:
            # 检查文件是否已存在
            existing_file = self.db.execute_query(
                "SELECT id, file_hash, updated_at FROM media_files WHERE file_path = ?",
                (file_path,)
            )
            
            # 获取文件信息
            file_info = self._get_file_info(file_path)
            if not file_info:
                return None
            
            # 如果文件已存在且哈希相同，跳过
            if existing_file and existing_file[0]['file_hash'] == file_info['file_hash']:
                return {'action': 'skipped', 'reason': 'unchanged'}
            
            # 解析文件名
            media_info = self._parse_filename(file_path)
            if not media_info:
                return {'action': 'skipped', 'reason': 'parse_failed'}
            
            # 合并文件信息和媒体信息
            media_info.update(file_info)
            
            # 保存到数据库
            if existing_file:
                self._update_media_file(existing_file[0]['id'], media_info)
                return {'action': 'updated'}
            else:
                self._insert_media_file(media_info)
                return {'action': 'added'}
                
        except Exception as e:
            self.logger.error(f"处理文件失败 {file_path}: {e}")
            return None
    
    def _get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """获取文件基本信息和技术参数"""
        try:
            # 获取文件统计信息
            stat = os.stat(file_path)
            
            # 计算文件哈希
            file_hash = self._calculate_file_hash(file_path)
            
            # 使用ffprobe获取媒体信息
            media_info = self._get_media_info_ffprobe(file_path)
            
            return {
                'file_path': file_path,
                'file_name': os.path.basename(file_path),
                'file_size': stat.st_size,
                'file_hash': file_hash,
                'duration': media_info.get('duration'),
                'width': media_info.get('width'),
                'height': media_info.get('height'),
                'resolution': media_info.get('resolution'),
                'video_codec': media_info.get('video_codec'),
                'audio_codec': media_info.get('audio_codec'),
                'audio_channels': media_info.get('audio_channels'),
                'container': media_info.get('container'),
                'bitrate': media_info.get('bitrate'),
                'frame_rate': media_info.get('frame_rate'),
                'subtitle_tracks': json.dumps(media_info.get('subtitle_tracks', [])),
                'audio_tracks': json.dumps(media_info.get('audio_tracks', [])),
            }
            
        except Exception as e:
            self.logger.error(f"获取文件信息失败 {file_path}: {e}")
            return None
    
    def _calculate_file_hash(self, file_path: str, chunk_size: int = 8192) -> str:
        """计算文件SHA256哈希值"""
        hash_sha256 = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                # 只读取文件开头和结尾部分来加速哈希计算
                # 对于大文件，读取前1MB和后1MB
                file_size = os.path.getsize(file_path)
                if file_size > 2 * 1024 * 1024:  # 2MB
                    # 读取前1MB
                    data = f.read(1024 * 1024)
                    hash_sha256.update(data)
                    
                    # 跳到文件末尾前1MB
                    f.seek(-1024 * 1024, 2)
                    data = f.read(1024 * 1024)
                    hash_sha256.update(data)
                else:
                    # 小文件直接读取全部
                    while chunk := f.read(chunk_size):
                        hash_sha256.update(chunk)
            
            return hash_sha256.hexdigest()
        except Exception as e:
            self.logger.error(f"计算文件哈希失败 {file_path}: {e}")
            return ""
    
    def _get_media_info_ffprobe(self, file_path: str) -> Dict[str, Any]:
        """使用ffprobe获取媒体技术信息"""
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                file_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                self.logger.warning(f"ffprobe执行失败 {file_path}: {result.stderr}")
                return {}
            
            data = json.loads(result.stdout)
            
            # 解析视频流信息
            video_stream = None
            audio_streams = []
            subtitle_streams = []
            
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    if video_stream is None:  # 取第一个视频流
                        video_stream = stream
                elif stream.get('codec_type') == 'audio':
                    audio_streams.append(stream)
                elif stream.get('codec_type') == 'subtitle':
                    subtitle_streams.append(stream)
            
            # 提取信息
            info = {}
            
            if video_stream:
                info['width'] = video_stream.get('width')
                info['height'] = video_stream.get('height')
                info['video_codec'] = video_stream.get('codec_name')
                info['frame_rate'] = self._parse_frame_rate(video_stream.get('r_frame_rate'))
                
                # 推断分辨率标签
                height = info.get('height', 0)
                if height >= 2160:
                    info['resolution'] = '2160p'
                elif height >= 1080:
                    info['resolution'] = '1080p'
                elif height >= 720:
                    info['resolution'] = '720p'
                elif height >= 480:
                    info['resolution'] = '480p'
                else:
                    info['resolution'] = f"{height}p"
            
            if audio_streams:
                # 取第一个音频流的信息
                audio_stream = audio_streams[0]
                info['audio_codec'] = audio_stream.get('codec_name')
                info['audio_channels'] = audio_stream.get('channels')
            
            # 格式信息
            format_info = data.get('format', {})
            info['duration'] = float(format_info.get('duration', 0))
            info['bitrate'] = int(format_info.get('bit_rate', 0))
            info['container'] = format_info.get('format_name', '').split(',')[0]
            
            # 音轨和字幕轨信息
            info['audio_tracks'] = [
                {
                    'index': stream.get('index'),
                    'codec': stream.get('codec_name'),
                    'language': stream.get('tags', {}).get('language'),
                    'title': stream.get('tags', {}).get('title'),
                    'channels': stream.get('channels')
                }
                for stream in audio_streams
            ]
            
            info['subtitle_tracks'] = [
                {
                    'index': stream.get('index'),
                    'codec': stream.get('codec_name'),
                    'language': stream.get('tags', {}).get('language'),
                    'title': stream.get('tags', {}).get('title')
                }
                for stream in subtitle_streams
            ]
            
            return info
            
        except subprocess.TimeoutExpired:
            self.logger.warning(f"ffprobe超时 {file_path}")
            return {}
        except Exception as e:
            self.logger.error(f"ffprobe解析失败 {file_path}: {e}")
            return {}
    
    def _parse_frame_rate(self, frame_rate_str: str) -> Optional[float]:
        """解析帧率字符串"""
        try:
            if not frame_rate_str or frame_rate_str == '0/0':
                return None
            
            if '/' in frame_rate_str:
                num, den = frame_rate_str.split('/')
                return float(num) / float(den)
            else:
                return float(frame_rate_str)
        except:
            return None
    
    def _parse_filename(self, file_path: str) -> Optional[Dict[str, Any]]:
        """解析文件名，识别电影或电视剧信息"""
        file_name = os.path.basename(file_path)
        name_without_ext = os.path.splitext(file_name)[0]
        
        # 提取质量信息
        quality_info = self._extract_quality_info(name_without_ext)
        
        # 尝试匹配电视剧模式
        for pattern in self.tv_patterns:
            match = pattern.match(name_without_ext)
            if match:
                show_name = self._clean_title(match.group(1))
                season = int(match.group(2))
                episode = int(match.group(3))
                
                return {
                    'type': 'tv_show',
                    'title': show_name,
                    'season_number': season,
                    'episode_number': episode,
                    **quality_info
                }
        
        # 尝试匹配电影模式
        for pattern in self.movie_patterns:
            match = pattern.match(name_without_ext)
            if match:
                movie_name = self._clean_title(match.group(1))
                year = int(match.group(2))
                
                return {
                    'type': 'movie',
                    'title': movie_name,
                    'year': year,
                    **quality_info
                }
        
        # 如果都不匹配，尝试从路径推断
        return self._parse_from_path(file_path, quality_info)
    
    def _extract_quality_info(self, filename: str) -> Dict[str, Any]:
        """从文件名提取质量信息"""
        info = {}
        
        for key, pattern in self.quality_patterns.items():
            match = pattern.search(filename)
            if match:
                if key == 'release_group':
                    info[key] = match.group(1)
                else:
                    info[key] = match.group(1).upper()
        
        return info
    
    def _clean_title(self, title: str) -> str:
        """清理标题，移除特殊字符"""
        # 替换点和下划线为空格
        title = re.sub(r'[\._]', ' ', title)
        # 移除多余空格
        title = re.sub(r'\s+', ' ', title)
        # 移除首尾空格
        return title.strip()
    
    def _parse_from_path(self, file_path: str, quality_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """从文件路径推断媒体信息"""
        path_parts = Path(file_path).parts
        
        # 查找包含季集信息的路径部分
        for part in reversed(path_parts):
            # 检查是否包含季信息
            season_match = re.search(r'[Ss]eason\s*(\d+)|[Ss](\d+)', part, re.IGNORECASE)
            if season_match:
                season = int(season_match.group(1) or season_match.group(2))
                
                # 从文件名提取集数
                filename = os.path.basename(file_path)
                episode_match = re.search(r'[Ee](\d+)', filename, re.IGNORECASE)
                if episode_match:
                    episode = int(episode_match.group(1))
                    
                    # 从上级目录获取剧集名称
                    show_name = None
                    for i, p in enumerate(path_parts):
                        if season_match.group(0).lower() in p.lower():
                            if i > 0:
                                show_name = self._clean_title(path_parts[i-1])
                            break
                    
                    if show_name:
                        return {
                            'type': 'tv_show',
                            'title': show_name,
                            'season_number': season,
                            'episode_number': episode,
                            **quality_info
                        }
        
        # 如果没有找到季集信息，假设是电影
        # 尝试从路径中提取年份
        for part in reversed(path_parts[:-1]):  # 排除文件名本身
            year_match = re.search(r'\((\d{4})\)|(\d{4})', part)
            if year_match:
                year = int(year_match.group(1) or year_match.group(2))
                title = self._clean_title(re.sub(r'\(\d{4}\)|\d{4}', '', part))
                
                return {
                    'type': 'movie',
                    'title': title,
                    'year': year,
                    **quality_info
                }
        
        return None
    
    def _insert_media_file(self, media_info: Dict[str, Any]) -> Optional[int]:
        """插入新的媒体文件记录"""
        try:
            # 首先处理媒体项目
            media_id = self._get_or_create_media_item(media_info)
            if not media_id:
                return None
            
            # 处理剧集（如果是电视剧）
            episode_id = None
            if media_info['type'] == 'tv_show':
                episode_id = self._get_or_create_episode(media_id, media_info)
            
            # 插入文件记录
            file_id = self.db.execute_insert("""
                INSERT INTO media_files (
                    media_id, episode_id, file_path, file_name, file_size, file_hash,
                    duration, width, height, resolution, video_codec, audio_codec,
                    audio_channels, container, bitrate, frame_rate, release_group,
                    source_type, subtitle_tracks, audio_tracks, scan_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                media_id, episode_id, media_info['file_path'], media_info['file_name'],
                media_info['file_size'], media_info['file_hash'], media_info.get('duration'),
                media_info.get('width'), media_info.get('height'), media_info.get('resolution'),
                media_info.get('video_codec'), media_info.get('audio_codec'),
                media_info.get('audio_channels'), media_info.get('container'),
                media_info.get('bitrate'), media_info.get('frame_rate'),
                media_info.get('release_group'), media_info.get('source_type'),
                media_info.get('subtitle_tracks'), media_info.get('audio_tracks'),
                'completed'
            ))
            
            return file_id
            
        except Exception as e:
            self.logger.error(f"插入媒体文件失败: {e}")
            return None
    
    def _update_media_file(self, file_id: int, media_info: Dict[str, Any]) -> bool:
        """更新现有媒体文件记录"""
        try:
            self.db.execute_update("""
                UPDATE media_files SET
                    file_size = ?, file_hash = ?, duration = ?, width = ?, height = ?,
                    resolution = ?, video_codec = ?, audio_codec = ?, audio_channels = ?,
                    container = ?, bitrate = ?, frame_rate = ?, release_group = ?,
                    source_type = ?, subtitle_tracks = ?, audio_tracks = ?,
                    scan_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                media_info['file_size'], media_info['file_hash'], media_info.get('duration'),
                media_info.get('width'), media_info.get('height'), media_info.get('resolution'),
                media_info.get('video_codec'), media_info.get('audio_codec'),
                media_info.get('audio_channels'), media_info.get('container'),
                media_info.get('bitrate'), media_info.get('frame_rate'),
                media_info.get('release_group'), media_info.get('source_type'),
                media_info.get('subtitle_tracks'), media_info.get('audio_tracks'),
                'completed', file_id
            ))
            
            return True
            
        except Exception as e:
            self.logger.error(f"更新媒体文件失败: {e}")
            return False
    
    def _get_or_create_media_item(self, media_info: Dict[str, Any]) -> Optional[int]:
        """获取或创建媒体项目记录"""
        try:
            # 查找现有记录
            if media_info['type'] == 'movie':
                existing = self.db.execute_query(
                    "SELECT id FROM media_items WHERE type = 'movie' AND title = ? AND year = ?",
                    (media_info['title'], media_info.get('year'))
                )
            else:
                existing = self.db.execute_query(
                    "SELECT id FROM media_items WHERE type = 'tv_show' AND title = ?",
                    (media_info['title'],)
                )
            
            if existing:
                return existing[0]['id']
            
            # 创建新记录
            media_id = self.db.execute_insert("""
                INSERT INTO media_items (type, title, year, status)
                VALUES (?, ?, ?, 'active')
            """, (
                media_info['type'],
                media_info['title'],
                media_info.get('year')
            ))
            
            # 如果是电视剧，创建tv_shows记录
            if media_info['type'] == 'tv_show' and media_id:
                self.db.execute_insert(
                    "INSERT INTO tv_shows (media_id) VALUES (?)",
                    (media_id,)
                )
            
            return media_id
            
        except Exception as e:
            self.logger.error(f"创建媒体项目失败: {e}")
            return None
    
    def _get_or_create_episode(self, tv_show_id: int, media_info: Dict[str, Any]) -> Optional[int]:
        """获取或创建剧集记录"""
        try:
            # 查找现有剧集
            existing = self.db.execute_query("""
                SELECT id FROM episodes 
                WHERE tv_show_id = ? AND season_number = ? AND episode_number = ?
            """, (tv_show_id, media_info['season_number'], media_info['episode_number']))
            
            if existing:
                return existing[0]['id']
            
            # 创建新剧集
            episode_id = self.db.execute_insert("""
                INSERT INTO episodes (tv_show_id, season_number, episode_number)
                VALUES (?, ?, ?)
            """, (tv_show_id, media_info['season_number'], media_info['episode_number']))
            
            return episode_id
            
        except Exception as e:
            self.logger.error(f"创建剧集记录失败: {e}")
            return None
    
    def _start_scan_record(self, scan_path: str) -> Optional[int]:
        """开始扫描记录"""
        try:
            return self.db.execute_insert("""
                INSERT INTO scan_history (scan_type, scan_path, status)
                VALUES ('full', ?, 'running')
            """, (scan_path,))
        except Exception as e:
            self.logger.error(f"创建扫描记录失败: {e}")
            return None
    
    def _complete_scan_record(self, scan_id: Optional[int], status: str, 
                            stats: Dict[str, int], error_log: Optional[str] = None):
        """完成扫描记录"""
        if not scan_id:
            return
        
        try:
            self.db.execute_update("""
                UPDATE scan_history SET
                    end_time = CURRENT_TIMESTAMP,
                    status = ?,
                    files_scanned = ?,
                    files_added = ?,
                    files_updated = ?,
                    errors_count = ?,
                    error_log = ?,
                    summary = ?
                WHERE id = ?
            """, (
                status,
                stats.get('files_scanned', 0),
                stats.get('files_added', 0),
                stats.get('files_updated', 0),
                stats.get('errors', 0),
                error_log,
                json.dumps(stats),
                scan_id
            ))
        except Exception as e:
            self.logger.error(f"更新扫描记录失败: {e}")


if __name__ == "__main__":
    # 测试扫描器
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    scanner = MediaFileScanner(max_workers=2)
    
    # 测试扫描（请根据实际路径修改）
    test_path = "/volume1/video"  # 群晖NAS典型路径
    if os.path.exists(test_path):
        results = scanner.scan_directory(test_path, recursive=True)
        print(f"扫描结果: {results}")
    else:
        print(f"测试路径不存在: {test_path}")