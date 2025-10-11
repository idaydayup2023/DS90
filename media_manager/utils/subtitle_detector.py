#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕文件检测器
负责检测、分析和管理媒体文件的字幕信息，特别是AI生成的字幕文件
"""

import os
import re
import hashlib
import logging
import chardet
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime

from ..database.db_manager import get_db_manager
from ..config.config_manager import get_config_manager
from ..utils.directory_manager import get_directory_manager

class SubtitleDetector:
    """字幕文件检测器"""
    
    def __init__(self):
        """初始化字幕检测器"""
        self.db = get_db_manager()
        self.config = get_config_manager()
        self.directory_manager = get_directory_manager()
        self.logger = logging.getLogger(__name__)
        
        # 从数据库获取配置
        self.subtitle_extensions = set(self.db.get_setting('subtitle_extensions', [
            'srt', 'ass', 'ssa', 'vtt', 'sub', 'idx', 'sup'
        ]))
        self.supported_languages = self.db.get_setting('subtitle_languages', [
            'zh-CN', 'en-US', 'ja-JP', 'ko-KR'
        ])
        self.ai_subtitle_required = self.db.get_setting('ai_subtitle_required', True)
        self.ai_subtitle_format = self.db.get_setting('ai_subtitle_format', 'srt')
        
        # 编译正则表达式
        self._compile_patterns()
        
        # 加载匹配规则
        self._load_matching_rules()
    
    def _compile_patterns(self):
        """编译字幕文件识别的正则表达式"""
        
        # AI字幕文件模式
        self.ai_subtitle_patterns = [
            re.compile(r'^(.+)\.ai\.srt$', re.IGNORECASE),  # filename.ai.srt
            re.compile(r'^(.+)\.ai\.(\w+)$', re.IGNORECASE),  # filename.ai.ext
            re.compile(r'^(.+)_ai\.srt$', re.IGNORECASE),   # filename_ai.srt
            re.compile(r'^(.+)-ai\.srt$', re.IGNORECASE),   # filename-ai.srt
        ]
        
        # 语言识别模式
        self.language_patterns = {
            'zh-CN': [
                re.compile(r'\.zh[-_]?cn\.', re.IGNORECASE),
                re.compile(r'\.chinese\.', re.IGNORECASE),
                re.compile(r'\.chs\.', re.IGNORECASE),
                re.compile(r'\.中文\.', re.IGNORECASE),
            ],
            'zh-TW': [
                re.compile(r'\.zh[-_]?tw\.', re.IGNORECASE),
                re.compile(r'\.cht\.', re.IGNORECASE),
                re.compile(r'\.繁体\.', re.IGNORECASE),
            ],
            'en-US': [
                re.compile(r'\.en[-_]?us\.', re.IGNORECASE),
                re.compile(r'\.english\.', re.IGNORECASE),
                re.compile(r'\.eng\.', re.IGNORECASE),
            ],
            'ja-JP': [
                re.compile(r'\.ja[-_]?jp\.', re.IGNORECASE),
                re.compile(r'\.japanese\.', re.IGNORECASE),
                re.compile(r'\.jpn\.', re.IGNORECASE),
            ],
            'ko-KR': [
                re.compile(r'\.ko[-_]?kr\.', re.IGNORECASE),
                re.compile(r'\.korean\.', re.IGNORECASE),
                re.compile(r'\.kor\.', re.IGNORECASE),
            ]
        }
        
        # 字幕格式识别模式
        self.format_patterns = {
            'srt': re.compile(r'\.srt$', re.IGNORECASE),
            'ass': re.compile(r'\.ass$', re.IGNORECASE),
            'ssa': re.compile(r'\.ssa$', re.IGNORECASE),
            'vtt': re.compile(r'\.vtt$', re.IGNORECASE),
            'sub': re.compile(r'\.sub$', re.IGNORECASE),
            'idx': re.compile(r'\.idx$', re.IGNORECASE),
            'sup': re.compile(r'\.sup$', re.IGNORECASE),
        }
    
    def _load_matching_rules(self):
        """从数据库加载字幕匹配规则"""
        try:
            rules = self.db.execute_query("""
                SELECT rule_name, rule_type, pattern, priority, is_enabled
                FROM subtitle_matching_rules
                WHERE is_enabled = 1
                ORDER BY priority DESC
            """)
            
            self.matching_rules = []
            for rule in rules:
                compiled_pattern = None
                if rule['rule_type'] in ['filename', 'directory', 'pattern']:
                    # 将通配符模式转换为正则表达式
                    pattern = rule['pattern'].replace('*', '.*').replace('?', '.')
                    compiled_pattern = re.compile(pattern, re.IGNORECASE)
                
                self.matching_rules.append({
                    'name': rule['rule_name'],
                    'type': rule['rule_type'],
                    'pattern': compiled_pattern,
                    'priority': rule['priority'],
                    'original_pattern': rule['pattern']
                })
                
        except Exception as e:
            self.logger.error(f"加载字幕匹配规则失败: {e}")
            self.matching_rules = []
    
    def detect_subtitles_for_video(self, video_path: str) -> List[Dict[str, Any]]:
        """
        为指定视频文件检测字幕文件
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            检测到的字幕文件信息列表
        """
        subtitles = []
        video_file = Path(video_path)
        
        if not video_file.exists():
            self.logger.warning(f"视频文件不存在: {video_path}")
            return subtitles
        
        # 获取视频文件的基本信息
        video_dir = video_file.parent
        video_name = video_file.stem
        
        # 搜索字幕文件的位置
        search_paths = self._get_subtitle_search_paths(video_dir, video_name)
        
        for search_path in search_paths:
            found_subtitles = self._scan_directory_for_subtitles(
                search_path, video_name, video_path
            )
            subtitles.extend(found_subtitles)
        
        # 去重和排序
        subtitles = self._deduplicate_and_sort_subtitles(subtitles)
        
        # 检查是否缺少AI字幕
        if self.ai_subtitle_required:
            ai_subtitle_exists = any(sub['is_ai_generated'] for sub in subtitles)
            if not ai_subtitle_exists:
                self.logger.warning(f"视频文件缺少AI字幕: {video_path}")
        
        return subtitles
    
    def _get_subtitle_search_paths(self, video_dir: Path, video_name: str) -> List[Path]:
        """获取字幕文件搜索路径"""
        search_paths = [video_dir]  # 首先搜索视频文件所在目录
        
        # 添加常见的字幕子目录
        subtitle_subdirs = ['Subs', 'Subtitles', 'Sub', 'Subtitle', '字幕']
        for subdir in subtitle_subdirs:
            sub_path = video_dir / subdir
            if sub_path.exists() and sub_path.is_dir():
                search_paths.append(sub_path)
        
        # 添加语言特定的子目录
        for lang in self.supported_languages:
            lang_dir = video_dir / lang
            if lang_dir.exists() and lang_dir.is_dir():
                search_paths.append(lang_dir)
        
        return search_paths
    
    def _scan_directory_for_subtitles(self, directory: Path, video_name: str, video_path: str) -> List[Dict[str, Any]]:
        """扫描目录中的字幕文件"""
        subtitles = []
        
        try:
            for file_path in directory.iterdir():
                if not file_path.is_file():
                    continue
                
                # 检查文件扩展名
                file_ext = file_path.suffix.lower().lstrip('.')
                if file_ext not in self.subtitle_extensions:
                    continue
                
                # 检查是否与视频文件匹配
                if self._is_subtitle_match(file_path.name, video_name):
                    subtitle_info = self._analyze_subtitle_file(file_path, video_path)
                    if subtitle_info:
                        subtitles.append(subtitle_info)
                        
        except Exception as e:
            self.logger.error(f"扫描字幕目录失败 {directory}: {e}")
        
        return subtitles
    
    def _is_subtitle_match(self, subtitle_filename: str, video_name: str) -> bool:
        """检查字幕文件是否与视频文件匹配"""
        
        # 首先检查是否为完全匹配（同名）
        subtitle_stem = Path(subtitle_filename).stem
        if subtitle_stem.startswith(video_name):
            return True
        
        # 使用匹配规则检查
        for rule in self.matching_rules:
            if rule['type'] == 'filename' and rule['pattern']:
                if rule['pattern'].match(subtitle_filename):
                    # 进一步检查是否与视频名称相关
                    if video_name.lower() in subtitle_filename.lower():
                        return True
        
        return False
    
    def _analyze_subtitle_file(self, subtitle_path: Path, video_path: str) -> Optional[Dict[str, Any]]:
        """分析字幕文件并提取信息"""
        try:
            # 基本文件信息
            file_stat = subtitle_path.stat()
            file_size = file_stat.st_size
            
            # 计算文件哈希
            file_hash = self._calculate_file_hash(str(subtitle_path))
            
            # 检测字幕类型和语言
            subtitle_type = self._detect_subtitle_type(subtitle_path.name)
            language_info = self._detect_language(subtitle_path.name)
            subtitle_format = self._detect_format(subtitle_path.name)
            
            # 检测文件编码
            encoding = self._detect_encoding(str(subtitle_path))
            
            # 分析字幕内容
            content_analysis = self._analyze_subtitle_content(str(subtitle_path), encoding)
            
            # 解析文件路径信息
            path_info = self.directory_manager.parse_file_path(str(subtitle_path))
            
            subtitle_info = {
                'subtitle_path': str(subtitle_path),
                'subtitle_name': subtitle_path.name,
                'subtitle_type': subtitle_type,
                'language_code': language_info['code'],
                'language_name': language_info['name'],
                'encoding': encoding,
                'format': subtitle_format,
                'file_size': file_size,
                'file_hash': file_hash,
                'is_ai_generated': subtitle_type == 'ai',
                'volume_id': path_info['volume_id'],
                'relative_path': path_info['relative_path'],
                'status': 'active',
                **content_analysis
            }
            
            return subtitle_info
            
        except Exception as e:
            self.logger.error(f"分析字幕文件失败 {subtitle_path}: {e}")
            return None
    
    def _detect_subtitle_type(self, filename: str) -> str:
        """检测字幕类型"""
        filename_lower = filename.lower()
        
        # 检查是否为AI字幕
        for pattern in self.ai_subtitle_patterns:
            if pattern.match(filename):
                return 'ai'
        
        # 检查其他类型标识
        if any(keyword in filename_lower for keyword in ['download', 'dl', 'web']):
            return 'downloaded'
        elif any(keyword in filename_lower for keyword in ['manual', 'hand', 'custom']):
            return 'manual'
        else:
            return 'other'
    
    def _detect_language(self, filename: str) -> Dict[str, str]:
        """检测字幕语言"""
        for lang_code, patterns in self.language_patterns.items():
            for pattern in patterns:
                if pattern.search(filename):
                    return {
                        'code': lang_code,
                        'name': self._get_language_name(lang_code)
                    }
        
        # 默认返回中文
        return {'code': 'zh-CN', 'name': '中文'}
    
    def _get_language_name(self, lang_code: str) -> str:
        """获取语言名称"""
        language_names = {
            'zh-CN': '中文(简体)',
            'zh-TW': '中文(繁体)',
            'en-US': 'English',
            'ja-JP': '日本語',
            'ko-KR': '한국어'
        }
        return language_names.get(lang_code, '未知')
    
    def _detect_format(self, filename: str) -> str:
        """检测字幕格式"""
        for format_name, pattern in self.format_patterns.items():
            if pattern.search(filename):
                return format_name
        return 'unknown'
    
    def _detect_encoding(self, file_path: str) -> str:
        """检测文件编码"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(8192)  # 读取前8KB用于检测
                result = chardet.detect(raw_data)
                return result.get('encoding', 'UTF-8') or 'UTF-8'
        except Exception as e:
            self.logger.warning(f"检测文件编码失败 {file_path}: {e}")
            return 'UTF-8'
    
    def _analyze_subtitle_content(self, file_path: str, encoding: str) -> Dict[str, Any]:
        """分析字幕内容"""
        analysis = {
            'subtitle_count': 0,
            'duration': 0,
            'quality_score': 0.0,
            'ai_confidence': 0.0
        }
        
        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read()
            
            # 基于格式分析内容
            format_type = self._detect_format(file_path)
            
            if format_type == 'srt':
                analysis.update(self._analyze_srt_content(content))
            elif format_type in ['ass', 'ssa']:
                analysis.update(self._analyze_ass_content(content))
            elif format_type == 'vtt':
                analysis.update(self._analyze_vtt_content(content))
            
        except Exception as e:
            self.logger.warning(f"分析字幕内容失败 {file_path}: {e}")
        
        return analysis
    
    def _analyze_srt_content(self, content: str) -> Dict[str, Any]:
        """分析SRT格式字幕内容"""
        lines = content.strip().split('\n')
        subtitle_count = 0
        total_duration = 0
        
        # 简单的SRT解析
        i = 0
        while i < len(lines):
            if lines[i].strip().isdigit():  # 字幕序号
                subtitle_count += 1
                if i + 1 < len(lines):
                    # 解析时间轴
                    time_line = lines[i + 1].strip()
                    duration = self._parse_srt_duration(time_line)
                    if duration > total_duration:
                        total_duration = duration
                i += 2
                # 跳过字幕文本
                while i < len(lines) and lines[i].strip():
                    i += 1
            i += 1
        
        # 计算质量评分
        quality_score = min(10.0, subtitle_count / 100.0 * 8.0 + 2.0)
        
        return {
            'subtitle_count': subtitle_count,
            'duration': total_duration,
            'quality_score': quality_score
        }
    
    def _analyze_ass_content(self, content: str) -> Dict[str, Any]:
        """分析ASS/SSA格式字幕内容"""
        lines = content.split('\n')
        subtitle_count = 0
        
        for line in lines:
            if line.startswith('Dialogue:'):
                subtitle_count += 1
        
        quality_score = min(10.0, subtitle_count / 100.0 * 8.0 + 2.0)
        
        return {
            'subtitle_count': subtitle_count,
            'duration': 0,  # ASS格式需要更复杂的解析
            'quality_score': quality_score
        }
    
    def _analyze_vtt_content(self, content: str) -> Dict[str, Any]:
        """分析VTT格式字幕内容"""
        lines = content.split('\n')
        subtitle_count = 0
        
        for line in lines:
            if '-->' in line:  # VTT时间轴标识
                subtitle_count += 1
        
        quality_score = min(10.0, subtitle_count / 100.0 * 8.0 + 2.0)
        
        return {
            'subtitle_count': subtitle_count,
            'duration': 0,  # 需要解析时间轴
            'quality_score': quality_score
        }
    
    def _parse_srt_duration(self, time_line: str) -> int:
        """解析SRT时间轴，返回结束时间（秒）"""
        try:
            # 格式: 00:00:00,000 --> 00:00:04,000
            if '-->' in time_line:
                end_time = time_line.split('-->')[1].strip()
                time_parts = end_time.replace(',', ':').split(':')
                if len(time_parts) >= 4:
                    hours = int(time_parts[0])
                    minutes = int(time_parts[1])
                    seconds = int(time_parts[2])
                    return hours * 3600 + minutes * 60 + seconds
        except Exception:
            pass
        return 0
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """计算文件哈希值"""
        try:
            hash_sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except Exception as e:
            self.logger.warning(f"计算文件哈希失败 {file_path}: {e}")
            return ""
    
    def _deduplicate_and_sort_subtitles(self, subtitles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """去重和排序字幕列表"""
        # 按路径去重
        seen_paths = set()
        unique_subtitles = []
        
        for subtitle in subtitles:
            path = subtitle['subtitle_path']
            if path not in seen_paths:
                seen_paths.add(path)
                unique_subtitles.append(subtitle)
        
        # 排序：AI字幕优先，然后按语言和质量排序
        def sort_key(sub):
            priority = 0
            if sub['is_ai_generated']:
                priority += 1000
            if sub['language_code'] == 'zh-CN':
                priority += 100
            priority += sub['quality_score']
            return -priority  # 降序排列
        
        unique_subtitles.sort(key=sort_key)
        return unique_subtitles
    
    def save_subtitle_info(self, media_file_id: int, subtitle_info: Dict[str, Any]) -> Optional[int]:
        """保存字幕信息到数据库"""
        try:
            subtitle_id = self.db.execute_insert("""
                INSERT INTO subtitle_files (
                    media_file_id, subtitle_path, subtitle_name, subtitle_type,
                    language_code, language_name, encoding, format, file_size,
                    file_hash, is_ai_generated, subtitle_count, duration,
                    quality_score, volume_id, relative_path, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                media_file_id, subtitle_info['subtitle_path'], subtitle_info['subtitle_name'],
                subtitle_info['subtitle_type'], subtitle_info['language_code'],
                subtitle_info['language_name'], subtitle_info['encoding'],
                subtitle_info['format'], subtitle_info['file_size'],
                subtitle_info['file_hash'], subtitle_info['is_ai_generated'],
                subtitle_info['subtitle_count'], subtitle_info['duration'],
                subtitle_info['quality_score'], subtitle_info['volume_id'],
                subtitle_info['relative_path'], subtitle_info['status']
            ))
            
            return subtitle_id
            
        except Exception as e:
            self.logger.error(f"保存字幕信息失败: {e}")
            return None
    
    def check_missing_ai_subtitles(self, media_file_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """检查缺失AI字幕的媒体文件"""
        try:
            if media_file_ids:
                placeholders = ','.join(['?'] * len(media_file_ids))
                query = f"""
                    SELECT mf.id, mf.file_path, mf.file_name
                    FROM media_files mf
                    LEFT JOIN subtitle_files sf ON mf.id = sf.media_file_id AND sf.is_ai_generated = 1
                    WHERE mf.id IN ({placeholders}) AND sf.id IS NULL
                """
                params = tuple(media_file_ids)
            else:
                query = """
                    SELECT mf.id, mf.file_path, mf.file_name
                    FROM media_files mf
                    LEFT JOIN subtitle_files sf ON mf.id = sf.media_file_id AND sf.is_ai_generated = 1
                    WHERE sf.id IS NULL
                """
                params = ()
            
            missing_files = self.db.execute_query(query, params)
            if missing_files:
                return [dict(row) for row in missing_files]
            return []
            
        except Exception as e:
            self.logger.error(f"检查缺失AI字幕失败: {e}")
            return []