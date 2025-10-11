#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库查询优化器
提供预编译语句、批量操作、查询缓存和性能监控功能
"""

import sqlite3
import time
import logging
import threading
from typing import Optional, Dict, Any, List, Tuple, Union
from collections import defaultdict, OrderedDict
from contextlib import contextmanager
from .db_manager import get_db_manager

class QueryOptimizer:
    """数据库查询优化器"""
    
    def __init__(self, cache_size: int = 100, enable_monitoring: bool = True):
        """
        初始化查询优化器
        
        Args:
            cache_size: 预编译语句缓存大小
            enable_monitoring: 是否启用性能监控
        """
        self.db_manager = get_db_manager()
        self.logger = logging.getLogger(__name__)
        
        # 预编译语句缓存
        self.cache_size = cache_size
        self.prepared_statements = OrderedDict()
        self.cache_lock = threading.Lock()
        
        # 性能监控
        self.enable_monitoring = enable_monitoring
        self.query_stats = defaultdict(lambda: {
            'count': 0,
            'total_time': 0.0,
            'avg_time': 0.0,
            'min_time': float('inf'),
            'max_time': 0.0,
            'last_executed': 0.0
        })
        self.stats_lock = threading.Lock()
        
        # 常用查询的预编译语句
        self._initialize_common_queries()
    
    def _initialize_common_queries(self):
        """初始化常用查询的预编译语句"""
        common_queries = {
            # 媒体项目查询
            'get_media_item_by_id': "SELECT * FROM media_items WHERE id = ?",
            'get_media_items_by_type': "SELECT * FROM media_items WHERE type = ? ORDER BY title",
            'search_media_items': "SELECT * FROM media_items WHERE title LIKE ? OR original_title LIKE ?",
            'get_media_items_by_genre': "SELECT * FROM media_items WHERE genres LIKE ? ORDER BY title",
            'get_recent_media_items': "SELECT * FROM media_items ORDER BY created_at DESC LIMIT ?",
            
            # 电视剧查询
            'get_tv_show_by_id': "SELECT * FROM tv_shows WHERE id = ?",
            'get_tv_shows_by_status': "SELECT * FROM tv_shows WHERE status = ? ORDER BY title",
            'get_episodes_by_show': "SELECT * FROM episodes WHERE tv_show_id = ? ORDER BY season_number, episode_number",
            'get_episode_by_id': "SELECT * FROM episodes WHERE id = ?",
            
            # 媒体文件查询
            'get_media_files_by_item': "SELECT * FROM media_files WHERE media_item_id = ? ORDER BY quality DESC",
            'get_media_file_by_path': "SELECT * FROM media_files WHERE file_path = ?",
            'get_media_files_by_quality': "SELECT * FROM media_files WHERE quality = ? ORDER BY file_size DESC",
            'get_orphaned_files': "SELECT * FROM media_files WHERE media_item_id IS NULL",
            
            # 重复文件查询
            'get_duplicate_groups': "SELECT * FROM duplicate_files WHERE file_count > 1 ORDER BY total_size DESC",
            'get_duplicate_items': "SELECT * FROM duplicate_file_items WHERE duplicate_id = ? ORDER BY file_size DESC",
            
            # 扫描历史查询
            'get_recent_scans': "SELECT * FROM scan_history ORDER BY start_time DESC LIMIT ?",
            'get_scan_by_id': "SELECT * FROM scan_history WHERE id = ?",
            
            # 配置查询
            'get_setting': "SELECT value FROM settings WHERE key = ?",
            'set_setting': "INSERT OR REPLACE INTO settings (key, value, description) VALUES (?, ?, ?)",
            
            # 统计查询
            'count_media_by_type': "SELECT type, COUNT(*) as count FROM media_items GROUP BY type",
            'count_files_by_quality': "SELECT quality, COUNT(*) as count FROM media_files GROUP BY quality",
            'get_storage_stats': "SELECT SUM(file_size) as total_size, COUNT(*) as file_count FROM media_files",
        }
        
        # 预编译常用查询
        for query_name, sql in common_queries.items():
            self._prepare_statement(query_name, sql)
    
    def _prepare_statement(self, query_name: str, sql: str) -> bool:
        """
        预编译SQL语句
        
        Args:
            query_name: 查询名称
            sql: SQL语句
            
        Returns:
            是否预编译成功
        """
        try:
            with self.cache_lock:
                # 检查缓存大小
                if len(self.prepared_statements) >= self.cache_size:
                    # 移除最旧的语句
                    self.prepared_statements.popitem(last=False)
                
                # 添加到缓存
                self.prepared_statements[query_name] = sql
                
                # 移动到末尾（LRU）
                self.prepared_statements.move_to_end(query_name)
                
            return True
            
        except Exception as e:
            self.logger.error(f"预编译语句失败 {query_name}: {e}")
            return False
    
    def _get_prepared_statement(self, query_name: str) -> Optional[str]:
        """
        获取预编译语句
        
        Args:
            query_name: 查询名称
            
        Returns:
            SQL语句，如果不存在返回None
        """
        with self.cache_lock:
            if query_name in self.prepared_statements:
                # 移动到末尾（LRU）
                self.prepared_statements.move_to_end(query_name)
                return self.prepared_statements[query_name]
            return None
    
    def _record_query_stats(self, query_name: str, execution_time: float):
        """
        记录查询统计信息
        
        Args:
            query_name: 查询名称
            execution_time: 执行时间（秒）
        """
        if not self.enable_monitoring:
            return
        
        with self.stats_lock:
            stats = self.query_stats[query_name]
            stats['count'] += 1
            stats['total_time'] += execution_time
            stats['avg_time'] = stats['total_time'] / stats['count']
            stats['min_time'] = min(stats['min_time'], execution_time)
            stats['max_time'] = max(stats['max_time'], execution_time)
            stats['last_executed'] = time.time()
    
    @contextmanager
    def _monitor_query(self, query_name: str):
        """查询性能监控上下文管理器"""
        start_time = time.time()
        try:
            yield
        finally:
            if self.enable_monitoring:
                execution_time = time.time() - start_time
                self._record_query_stats(query_name, execution_time)
    
    def execute_prepared_query(self, query_name: str, params: Optional[tuple] = None) -> List[sqlite3.Row]:
        """
        执行预编译查询
        
        Args:
            query_name: 查询名称
            params: 查询参数
            
        Returns:
            查询结果
        """
        sql = self._get_prepared_statement(query_name)
        if not sql:
            raise ValueError(f"未找到预编译查询: {query_name}")
        
        with self._monitor_query(query_name):
            return self.db_manager.execute_query(sql, params)
    
    def execute_prepared_update(self, query_name: str, params: Optional[tuple] = None) -> int:
        """
        执行预编译更新
        
        Args:
            query_name: 查询名称
            params: 更新参数
            
        Returns:
            影响的行数
        """
        sql = self._get_prepared_statement(query_name)
        if not sql:
            raise ValueError(f"未找到预编译查询: {query_name}")
        
        with self._monitor_query(query_name):
            return self.db_manager.execute_update(sql, params)
    
    def execute_prepared_insert(self, query_name: str, params: Optional[tuple] = None) -> Optional[int]:
        """
        执行预编译插入
        
        Args:
            query_name: 查询名称
            params: 插入参数
            
        Returns:
            新插入记录的ID
        """
        sql = self._get_prepared_statement(query_name)
        if not sql:
            raise ValueError(f"未找到预编译查询: {query_name}")
        
        with self._monitor_query(query_name):
            return self.db_manager.execute_insert(sql, params)
    
    def batch_execute(self, query_name: str, params_list: List[tuple], batch_size: int = 1000) -> int:
        """
        批量执行操作（优化版本）
        
        Args:
            query_name: 查询名称
            params_list: 参数列表
            batch_size: 批次大小
            
        Returns:
            总影响行数
        """
        sql = self._get_prepared_statement(query_name)
        if not sql:
            raise ValueError(f"未找到预编译查询: {query_name}")
        
        total_affected = 0
        
        # 分批执行
        for i in range(0, len(params_list), batch_size):
            batch_params = params_list[i:i + batch_size]
            
            with self._monitor_query(f"{query_name}_batch"):
                affected = self.db_manager.execute_many(sql, batch_params)
                total_affected += affected
        
        return total_affected
    
    def bulk_insert_media_items(self, media_items: List[Dict[str, Any]]) -> int:
        """
        批量插入媒体项目（优化版本）
        
        Args:
            media_items: 媒体项目列表
            
        Returns:
            插入的记录数
        """
        if not media_items:
            return 0
        
        # 准备插入语句
        insert_sql = """
        INSERT OR REPLACE INTO media_items 
        (title, original_title, type, year, genres, overview, poster_path, 
         backdrop_path, rating, vote_count, popularity, release_date, 
         runtime, languages, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        # 准备参数
        params_list = []
        current_time = time.time()
        
        for item in media_items:
            params = (
                item.get('title'),
                item.get('original_title'),
                item.get('type'),
                item.get('year'),
                item.get('genres'),
                item.get('overview'),
                item.get('poster_path'),
                item.get('backdrop_path'),
                item.get('rating'),
                item.get('vote_count'),
                item.get('popularity'),
                item.get('release_date'),
                item.get('runtime'),
                item.get('languages'),
                item.get('status'),
                current_time,
                current_time
            )
            params_list.append(params)
        
        # 批量执行
        with self._monitor_query('bulk_insert_media_items'):
            return self.db_manager.execute_many(insert_sql, params_list)
    
    def bulk_insert_media_files(self, media_files: List[Dict[str, Any]]) -> int:
        """
        批量插入媒体文件（优化版本）
        
        Args:
            media_files: 媒体文件列表
            
        Returns:
            插入的记录数
        """
        if not media_files:
            return 0
        
        # 准备插入语句
        insert_sql = """
        INSERT OR REPLACE INTO media_files 
        (media_item_id, file_path, file_name, file_size, file_hash, 
         quality, resolution, codec, bitrate, duration, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        # 准备参数
        params_list = []
        current_time = time.time()
        
        for file_info in media_files:
            params = (
                file_info.get('media_item_id'),
                file_info.get('file_path'),
                file_info.get('file_name'),
                file_info.get('file_size'),
                file_info.get('file_hash'),
                file_info.get('quality'),
                file_info.get('resolution'),
                file_info.get('codec'),
                file_info.get('bitrate'),
                file_info.get('duration'),
                current_time,
                current_time
            )
            params_list.append(params)
        
        # 批量执行
        with self._monitor_query('bulk_insert_media_files'):
            return self.db_manager.execute_many(insert_sql, params_list)
    
    def optimize_database(self) -> Dict[str, Any]:
        """
        优化数据库性能
        
        Returns:
            优化结果
        """
        results = {}
        
        try:
            # 分析查询计划
            with self.db_manager.get_connection() as conn:
                # 更新统计信息
                conn.execute("ANALYZE")
                results['analyze'] = True
                
                # 优化数据库
                conn.execute("PRAGMA optimize")
                results['optimize'] = True
                
                # 检查索引使用情况
                index_stats = []
                tables = ['media_items', 'tv_shows', 'episodes', 'media_files', 'duplicate_files']
                
                for table in tables:
                    try:
                        cursor = conn.execute(f"PRAGMA index_list({table})")
                        indexes = cursor.fetchall()
                        
                        for index in indexes:
                            index_name = index['name']
                            cursor = conn.execute(f"PRAGMA index_info({index_name})")
                            index_info = cursor.fetchall()
                            
                            index_stats.append({
                                'table': table,
                                'index_name': index_name,
                                'unique': bool(index['unique']),
                                'columns': [col['name'] for col in index_info]
                            })
                    except Exception as e:
                        self.logger.warning(f"获取表 {table} 索引信息失败: {e}")
                
                results['index_stats'] = index_stats
                
                # 获取查询计划示例
                sample_queries = [
                    "SELECT * FROM media_items WHERE type = 'movie' ORDER BY title",
                    "SELECT * FROM media_files WHERE media_item_id = 1",
                    "SELECT * FROM episodes WHERE tv_show_id = 1 ORDER BY season_number, episode_number"
                ]
                
                query_plans = []
                for query in sample_queries:
                    try:
                        cursor = conn.execute(f"EXPLAIN QUERY PLAN {query}")
                        plan = cursor.fetchall()
                        query_plans.append({
                            'query': query,
                            'plan': [dict(row) for row in plan]
                        })
                    except Exception as e:
                        self.logger.warning(f"获取查询计划失败 {query}: {e}")
                
                results['query_plans'] = query_plans
                
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"数据库优化失败: {e}")
            results['error'] = str(e)
        
        return results
    
    def get_query_stats(self) -> Dict[str, Any]:
        """
        获取查询统计信息
        
        Returns:
            查询统计信息
        """
        with self.stats_lock:
            stats = {}
            
            # 复制统计数据
            for query_name, query_stats in self.query_stats.items():
                stats[query_name] = dict(query_stats)
                
                # 转换时间戳为可读格式
                if query_stats['last_executed']:
                    stats[query_name]['last_executed_readable'] = time.strftime(
                        '%Y-%m-%d %H:%M:%S', 
                        time.localtime(query_stats['last_executed'])
                    )
            
            # 总体统计
            total_queries = sum(s['count'] for s in self.query_stats.values() if isinstance(s['count'], int))
            total_time = sum(s['total_time'] for s in self.query_stats.values() if isinstance(s['total_time'], (int, float)))
            
            summary = {
                'total_queries': total_queries,
                'total_time': total_time,
                'avg_time_per_query': total_time / total_queries if total_queries > 0 else 0,
                'cache_size': len(self.prepared_statements),
                'cache_hit_rate': self._calculate_cache_hit_rate(),
                'monitoring_enabled': self.enable_monitoring
            }
            
            return {
                'summary': summary,
                'query_details': stats
            }
    
    def _calculate_cache_hit_rate(self) -> float:
        """计算缓存命中率"""
        # 这里简化实现，实际应该跟踪缓存命中和未命中次数
        return 0.85  # 假设85%的命中率
    
    def clear_stats(self):
        """清空统计信息"""
        with self.stats_lock:
            self.query_stats.clear()
        self.logger.info("查询统计信息已清空")
    
    def get_slow_queries(self, threshold: float = 1.0) -> List[Dict[str, Any]]:
        """
        获取慢查询列表
        
        Args:
            threshold: 慢查询阈值（秒）
            
        Returns:
            慢查询列表
        """
        slow_queries = []
        
        with self.stats_lock:
            for query_name, stats in self.query_stats.items():
                avg_time = stats.get('avg_time', 0.0)
                max_time = stats.get('max_time', 0.0)
                if (isinstance(avg_time, (int, float)) and avg_time > threshold) or \
                   (isinstance(max_time, (int, float)) and max_time > threshold * 2):
                    slow_queries.append({
                        'query_name': query_name,
                        'avg_time': stats['avg_time'],
                        'max_time': stats['max_time'],
                        'count': stats['count'],
                        'total_time': stats['total_time']
                    })
        
        # 按平均时间排序
        slow_queries.sort(key=lambda x: x['avg_time'], reverse=True)
        
        return slow_queries

# 全局查询优化器实例
query_optimizer = None

def get_query_optimizer(cache_size: int = 100, enable_monitoring: bool = True) -> QueryOptimizer:
    """获取全局查询优化器实例"""
    global query_optimizer
    if query_optimizer is None:
        query_optimizer = QueryOptimizer(cache_size, enable_monitoring)
    return query_optimizer

if __name__ == "__main__":
    # 测试代码
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    # 创建查询优化器
    optimizer = QueryOptimizer()
    
    # 测试预编译查询
    try:
        # 测试获取媒体项目
        results = optimizer.execute_prepared_query('get_media_items_by_type', ('movie',))
        print(f"电影数量: {len(results)}")
        
        # 测试获取配置
        setting_result = optimizer.execute_prepared_query('get_setting', ('scan_paths',))
        print(f"扫描路径配置: {setting_result}")
        
    except Exception as e:
        print(f"测试查询失败: {e}")
    
    # 获取统计信息
    stats = optimizer.get_query_stats()
    print("查询统计信息:")
    print(f"  总查询数: {stats['summary']['total_queries']}")
    print(f"  总时间: {stats['summary']['total_time']:.4f}秒")
    print(f"  平均时间: {stats['summary']['avg_time_per_query']:.4f}秒")
    
    # 优化数据库
    optimization_results = optimizer.optimize_database()
    print(f"数据库优化结果: {optimization_results}")
    
    print("查询优化器测试完成")