#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TMDB API客户端
负责从The Movie Database获取电影和电视剧的元数据
"""

import json
import time
import logging
import requests
from typing import Dict, List, Optional, Any
from urllib.parse import quote

from ..database.db_manager import get_db_manager

class TMDBClient:
    """TMDB API客户端"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化TMDB客户端
        
        Args:
            api_key: TMDB API密钥，如果不提供则从数据库配置中获取
        """
        self.db = get_db_manager()
        self.logger = logging.getLogger(__name__)
        
        # 获取API密钥
        self.api_key = api_key or self.db.get_setting('tmdb_api_key', '')
        if not self.api_key:
            self.logger.warning("TMDB API密钥未配置，元数据获取功能将不可用")
        
        # API配置
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/"
        
        # 语言偏好
        self.language = self.db.get_setting('language_preference', 'zh-CN,en-US').split(',')[0]
        
        # 请求会话
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MediaManager/1.0'
        })
        
        # 速率限制
        self.last_request_time = 0
        self.min_request_interval = 0.25  # 250ms，每秒最多4个请求
    
    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        发送API请求
        
        Args:
            endpoint: API端点
            params: 请求参数
            
        Returns:
            API响应数据
        """
        if not self.api_key:
            self.logger.error("TMDB API密钥未配置")
            return None
        
        # 速率限制
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)
        
        try:
            # 准备请求参数
            request_params = {
                'api_key': self.api_key,
                'language': self.language
            }
            if params:
                request_params.update(params)
            
            # 发送请求
            url = f"{self.base_url}/{endpoint}"
            response = self.session.get(url, params=request_params, timeout=10)
            self.last_request_time = time.time()
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                # 速率限制，等待后重试
                self.logger.warning("TMDB API速率限制，等待重试")
                time.sleep(1)
                return self._make_request(endpoint, params)
            else:
                self.logger.error(f"TMDB API请求失败: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            self.logger.error(f"TMDB API请求异常: {e}")
            return None
    
    def search_movie(self, title: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        搜索电影
        
        Args:
            title: 电影标题
            year: 发行年份（可选）
            
        Returns:
            搜索结果列表
        """
        params = {'query': title}
        if year:
            params['year'] = str(year)
        
        data = self._make_request('search/movie', params)
        if data:
            return data.get('results', [])
        return []
    
    def search_tv(self, title: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        搜索电视剧
        
        Args:
            title: 电视剧标题
            year: 首播年份（可选）
            
        Returns:
            搜索结果列表
        """
        params = {'query': title}
        if year:
            params['first_air_date_year'] = str(year)
        
        data = self._make_request('search/tv', params)
        if data:
            return data.get('results', [])
        return []
    
    def get_movie_details(self, movie_id: int) -> Optional[Dict[str, Any]]:
        """
        获取电影详细信息
        
        Args:
            movie_id: TMDB电影ID
            
        Returns:
            电影详细信息
        """
        return self._make_request(f'movie/{movie_id}')
    
    def get_tv_details(self, tv_id: int) -> Optional[Dict[str, Any]]:
        """
        获取电视剧详细信息
        
        Args:
            tv_id: TMDB电视剧ID
            
        Returns:
            电视剧详细信息
        """
        return self._make_request(f'tv/{tv_id}')
    
    def get_tv_season_details(self, tv_id: int, season_number: int) -> Optional[Dict[str, Any]]:
        """
        获取电视剧季详细信息
        
        Args:
            tv_id: TMDB电视剧ID
            season_number: 季数
            
        Returns:
            季详细信息
        """
        return self._make_request(f'tv/{tv_id}/season/{season_number}')
    
    def get_tv_episode_details(self, tv_id: int, season_number: int, episode_number: int) -> Optional[Dict[str, Any]]:
        """
        获取电视剧集详细信息
        
        Args:
            tv_id: TMDB电视剧ID
            season_number: 季数
            episode_number: 集数
            
        Returns:
            集详细信息
        """
        return self._make_request(f'tv/{tv_id}/season/{season_number}/episode/{episode_number}')
    
    def find_best_match(self, title: str, year: Optional[int], media_type: str) -> Optional[Dict[str, Any]]:
        """
        查找最佳匹配的媒体项目
        
        Args:
            title: 标题
            year: 年份
            media_type: 媒体类型 ('movie' 或 'tv_show')
            
        Returns:
            最佳匹配结果
        """
        if media_type == 'movie':
            results = self.search_movie(title, year)
        elif media_type == 'tv_show':
            results = self.search_tv(title, year)
        else:
            return None
        
        if not results:
            return None
        
        # 简单的匹配算法：优先考虑年份匹配，然后是标题相似度
        best_match = None
        best_score = 0
        
        for result in results:
            score = 0
            
            # 标题匹配度（简单的字符串相似度）
            result_title = result.get('title') or result.get('name', '')
            title_similarity = self._calculate_title_similarity(title, result_title)
            score += title_similarity * 0.7
            
            # 年份匹配
            if year:
                if media_type == 'movie':
                    result_year = self._extract_year(result.get('release_date', ''))
                else:
                    result_year = self._extract_year(result.get('first_air_date', ''))
                
                if result_year and abs(result_year - year) <= 1:
                    score += 0.3
            
            # 流行度加分
            popularity = result.get('popularity', 0)
            if popularity > 10:
                score += 0.1
            
            if score > best_score:
                best_score = score
                best_match = result
        
        return best_match if best_score > 0.5 else None
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """
        计算标题相似度（简单实现）
        
        Args:
            title1: 标题1
            title2: 标题2
            
        Returns:
            相似度分数 (0-1)
        """
        # 转换为小写并移除特殊字符
        t1 = ''.join(c.lower() for c in title1 if c.isalnum() or c.isspace()).strip()
        t2 = ''.join(c.lower() for c in title2 if c.isalnum() or c.isspace()).strip()
        
        # 完全匹配
        if t1 == t2:
            return 1.0
        
        # 包含关系
        if t1 in t2 or t2 in t1:
            return 0.8
        
        # 简单的词汇重叠度
        words1 = set(t1.split())
        words2 = set(t2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union)
    
    def _extract_year(self, date_str: str) -> Optional[int]:
        """从日期字符串提取年份"""
        if not date_str:
            return None
        try:
            return int(date_str.split('-')[0])
        except (ValueError, IndexError):
            return None
    
    def update_media_metadata(self, media_id: int) -> bool:
        """
        更新媒体项目的元数据
        
        Args:
            media_id: 媒体项目ID
            
        Returns:
            是否更新成功
        """
        try:
            # 获取媒体项目信息
            media_item = self.db.execute_query(
                "SELECT * FROM media_items WHERE id = ?", (media_id,)
            )
            
            if not media_item:
                return False
            
            item = media_item[0]
            
            # 查找TMDB匹配
            match = self.find_best_match(item['title'], item['year'], item['type'])
            if not match:
                self.logger.warning(f"未找到TMDB匹配: {item['title']} ({item['year']})")
                return False
            
            # 获取详细信息
            tmdb_id = match['id']
            if item['type'] == 'movie':
                details = self.get_movie_details(tmdb_id)
            else:
                details = self.get_tv_details(tmdb_id)
            
            if not details:
                return False
            
            # 更新媒体项目
            self._update_media_item_from_tmdb(media_id, details, item['type'])
            
            # 如果是电视剧，更新剧集信息
            if item['type'] == 'tv_show':
                self._update_tv_episodes_from_tmdb(media_id, tmdb_id)
            
            return True
            
        except Exception as e:
            self.logger.error(f"更新元数据失败 {media_id}: {e}")
            return False
    
    def _update_media_item_from_tmdb(self, media_id: int, details: Dict[str, Any], media_type: str):
        """从TMDB数据更新媒体项目"""
        try:
            # 提取通用信息
            tmdb_id = details['id']
            overview = details.get('overview', '')
            poster_path = details.get('poster_path', '')
            backdrop_path = details.get('backdrop_path', '')
            genres = json.dumps([g['name'] for g in details.get('genres', [])])
            rating = details.get('vote_average', 0)
            vote_count = details.get('vote_count', 0)
            popularity = details.get('popularity', 0)
            adult = details.get('adult', False)
            
            # 提取语言信息
            if media_type == 'movie':
                languages = json.dumps([details.get('original_language', '')])
                runtime = details.get('runtime')
                original_title = details.get('original_title', '')
            else:
                languages = json.dumps(details.get('origin_country', []))
                runtime = None
                original_title = details.get('original_name', '')
            
            # 更新数据库
            self.db.execute_update("""
                UPDATE media_items SET
                    tmdb_id = ?, original_title = ?, overview = ?, poster_path = ?,
                    backdrop_path = ?, genres = ?, languages = ?, runtime = ?,
                    rating = ?, vote_count = ?, popularity = ?, adult = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                tmdb_id, original_title, overview, poster_path, backdrop_path,
                genres, languages, runtime, rating, vote_count, popularity,
                adult, media_id
            ))
            
            # 如果是电视剧，更新tv_shows表
            if media_type == 'tv_show':
                first_air_date = details.get('first_air_date')
                last_air_date = details.get('last_air_date')
                total_seasons = details.get('number_of_seasons', 0)
                total_episodes = details.get('number_of_episodes', 0)
                episode_runtime = json.dumps(details.get('episode_run_time', []))
                network = ', '.join([n['name'] for n in details.get('networks', [])])
                origin_country = ', '.join(details.get('origin_country', []))
                in_production = details.get('in_production', False)
                
                self.db.execute_update("""
                    UPDATE tv_shows SET
                        total_seasons = ?, total_episodes = ?, first_air_date = ?,
                        last_air_date = ?, episode_runtime = ?, network = ?,
                        origin_country = ?, in_production = ?
                    WHERE media_id = ?
                """, (
                    total_seasons, total_episodes, first_air_date, last_air_date,
                    episode_runtime, network, origin_country, in_production, media_id
                ))
            
            self.logger.info(f"已更新媒体元数据: {details.get('title') or details.get('name')}")
            
        except Exception as e:
            self.logger.error(f"更新媒体项目失败: {e}")
    
    def _update_tv_episodes_from_tmdb(self, media_id: int, tmdb_id: int):
        """从TMDB更新电视剧集信息"""
        try:
            # 获取现有剧集
            existing_episodes = self.db.execute_query("""
                SELECT DISTINCT season_number, episode_number 
                FROM episodes WHERE tv_show_id = ?
            """, (media_id,))
            
            for episode in existing_episodes:
                season_num = episode['season_number']
                episode_num = episode['episode_number']
                
                # 获取剧集详细信息
                episode_details = self.get_tv_episode_details(tmdb_id, season_num, episode_num)
                if episode_details:
                    self.db.execute_update("""
                        UPDATE episodes SET
                            title = ?, overview = ?, air_date = ?, runtime = ?,
                            tmdb_id = ?, still_path = ?, vote_average = ?, vote_count = ?
                        WHERE tv_show_id = ? AND season_number = ? AND episode_number = ?
                    """, (
                        episode_details.get('name', ''),
                        episode_details.get('overview', ''),
                        episode_details.get('air_date'),
                        episode_details.get('runtime'),
                        episode_details.get('id'),
                        episode_details.get('still_path', ''),
                        episode_details.get('vote_average', 0),
                        episode_details.get('vote_count', 0),
                        media_id, season_num, episode_num
                    ))
                
                # 避免过于频繁的请求
                time.sleep(0.1)
            
        except Exception as e:
            self.logger.error(f"更新剧集信息失败: {e}")
    
    def batch_update_metadata(self, limit: int = 50) -> Dict[str, int]:
        """
        批量更新元数据
        
        Args:
            limit: 每次处理的最大数量
            
        Returns:
            更新统计信息
        """
        stats = {'updated': 0, 'failed': 0, 'skipped': 0}
        
        try:
            # 获取需要更新的媒体项目（没有TMDB ID的）
            items = self.db.execute_query("""
                SELECT id, title, year, type FROM media_items 
                WHERE tmdb_id IS NULL 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
            
            for item in items:
                try:
                    if self.update_media_metadata(item['id']):
                        stats['updated'] += 1
                    else:
                        stats['failed'] += 1
                    
                    # 避免过于频繁的请求
                    time.sleep(0.3)
                    
                except Exception as e:
                    self.logger.error(f"批量更新失败 {item['id']}: {e}")
                    stats['failed'] += 1
            
            self.logger.info(f"批量更新完成: {stats}")
            return stats
            
        except Exception as e:
            self.logger.error(f"批量更新异常: {e}")
            return stats
    
    def get_image_url(self, image_path: str, size: str = 'w500') -> str:
        """
        获取完整的图片URL
        
        Args:
            image_path: 图片路径
            size: 图片尺寸
            
        Returns:
            完整的图片URL
        """
        if not image_path:
            return ''
        return f"{self.image_base_url}{size}{image_path}"


if __name__ == "__main__":
    # 测试TMDB客户端
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    # 需要设置TMDB API密钥
    client = TMDBClient()
    
    if client.api_key:
        # 测试搜索电影
        movies = client.search_movie("阿凡达", 2009)
        if movies:
            print(f"找到电影: {movies[0]['title']}")
            
            # 获取详细信息
            details = client.get_movie_details(movies[0]['id'])
            if details:
                print(f"电影详情: {details['title']} - {details['overview'][:100]}...")
        
        # 测试搜索电视剧
        tv_shows = client.search_tv("权力的游戏")
        if tv_shows:
            print(f"找到电视剧: {tv_shows[0]['name']}")
    else:
        print("请先配置TMDB API密钥")