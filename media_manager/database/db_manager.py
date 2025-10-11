#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理器
负责SQLite数据库的初始化、连接管理和基本操作
优化版本：启用WAL模式、性能调优、连接池支持
"""

import sqlite3
import os
import json
import logging
import threading
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple
from queue import Queue, Empty

class DatabaseManager:
    """数据库管理器类 - 优化版本"""
    
    def __init__(self, db_path: Optional[str] = None, pool_size: int = 5):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径，默认为当前目录下的media_library.db
            pool_size: 连接池大小
        """
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'media_library.db')
        
        self.db_path = os.path.abspath(db_path)
        self.schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        self.pool_size = pool_size
        
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # 设置日志
        self.logger = logging.getLogger(__name__)
        
        # 连接池
        self._connection_pool = Queue(maxsize=pool_size)
        self._pool_lock = threading.Lock()
        self._pool_initialized = False
        
        # 初始化数据库
        self.initialize_database()
        
        # 初始化连接池
        self._initialize_connection_pool()
    
    def _initialize_connection_pool(self):
        """初始化连接池"""
        with self._pool_lock:
            if self._pool_initialized:
                return
                
            for _ in range(self.pool_size):
                conn = self._create_optimized_connection()
                self._connection_pool.put(conn)
            
            self._pool_initialized = True
            self.logger.info(f"连接池初始化完成，大小: {self.pool_size}")
    
    def _create_optimized_connection(self) -> sqlite3.Connection:
        """创建优化的数据库连接"""
        conn = sqlite3.connect(
            self.db_path, 
            timeout=30.0,
            check_same_thread=False  # 允许多线程使用
        )
        conn.row_factory = sqlite3.Row
        
        # SQLite性能优化设置
        optimizations = [
            "PRAGMA foreign_keys = ON",           # 启用外键约束
            "PRAGMA journal_mode = WAL",          # 启用WAL模式，提高并发性能
            "PRAGMA synchronous = NORMAL",        # 平衡安全性和性能
            "PRAGMA cache_size = 10000",          # 增加缓存大小（约40MB）
            "PRAGMA temp_store = MEMORY",         # 临时表存储在内存中
            "PRAGMA mmap_size = 268435456",       # 启用内存映射（256MB）
            "PRAGMA optimize",                    # 自动优化
        ]
        
        for pragma in optimizations:
            try:
                conn.execute(pragma)
            except Exception as e:
                self.logger.warning(f"执行优化设置失败 {pragma}: {e}")
        
        return conn
    
    def initialize_database(self):
        """初始化数据库，创建表结构"""
        try:
            # 使用临时连接进行初始化
            conn = self._create_optimized_connection()
            
            try:
                # 读取并执行schema文件
                if os.path.exists(self.schema_path):
                    with open(self.schema_path, 'r', encoding='utf-8') as f:
                        schema_sql = f.read()
                    
                    # 分割SQL语句并执行
                    statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]
                    for statement in statements:
                        conn.execute(statement)
                    
                    conn.commit()
                    self.logger.info(f"数据库初始化完成: {self.db_path}")
                else:
                    self.logger.error(f"Schema文件不存在: {self.schema_path}")
                    raise FileNotFoundError(f"Schema文件不存在: {self.schema_path}")
            finally:
                conn.close()
                    
        except Exception as e:
            self.logger.error(f"数据库初始化失败: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器（使用连接池）"""
        conn = None
        try:
            # 从连接池获取连接
            try:
                conn = self._connection_pool.get(timeout=5.0)
            except Empty:
                # 连接池为空，创建新连接
                conn = self._create_optimized_connection()
                self.logger.warning("连接池为空，创建新连接")
            
            yield conn
            
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"数据库连接错误: {e}")
            raise
        finally:
            if conn:
                try:
                    # 将连接返回连接池
                    if self._connection_pool.qsize() < self.pool_size:
                        self._connection_pool.put(conn)
                    else:
                        conn.close()
                except:
                    conn.close()
    
    def execute_query(self, query: str, params: Optional[tuple] = None) -> List[sqlite3.Row]:
        """
        执行查询语句
        
        Args:
            query: SQL查询语句
            params: 查询参数
            
        Returns:
            查询结果列表
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()
    
    def execute_update(self, query: str, params: Optional[tuple] = None) -> int:
        """
        执行更新语句
        
        Args:
            query: SQL更新语句
            params: 更新参数
            
        Returns:
            影响的行数
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            return cursor.rowcount
    
    def execute_insert(self, query: str, params: Optional[tuple] = None) -> Optional[int]:
        """
        执行插入语句
        
        Args:
            query: SQL插入语句
            params: 插入参数
            
        Returns:
            新插入记录的ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            return cursor.lastrowid
    
    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """
        批量执行语句（优化版本）
        
        Args:
            query: SQL语句
            params_list: 参数列表
            
        Returns:
            影响的行数
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor.rowcount
    
    def get_setting(self, key: str, default_value: Any = None) -> Any:
        """
        获取配置项
        
        Args:
            key: 配置键
            default_value: 默认值
            
        Returns:
            配置值
        """
        try:
            result = self.execute_query(
                "SELECT value FROM settings WHERE key = ?", (key,)
            )
            if result:
                value = result[0]['value']
                # 尝试解析JSON
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            return default_value
        except Exception as e:
            self.logger.error(f"获取配置失败 {key}: {e}")
            return default_value
    
    def set_setting(self, key: str, value: Any, description: Optional[str] = None) -> bool:
        """
        设置配置项
        
        Args:
            key: 配置键
            value: 配置值
            description: 配置描述
            
        Returns:
            是否设置成功
        """
        try:
            # 如果值是字典或列表，转换为JSON
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value)
            
            # 检查是否已存在
            existing = self.execute_query(
                "SELECT id FROM settings WHERE key = ?", (key,)
            )
            
            if existing:
                # 更新现有配置
                self.execute_update(
                    "UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (value_str, key)
                )
            else:
                # 插入新配置
                self.execute_insert(
                    "INSERT INTO settings (key, value, description) VALUES (?, ?, ?)",
                    (key, value_str, description)
                )
            
            return True
        except Exception as e:
            self.logger.error(f"设置配置失败 {key}: {e}")
            return False
    
    def get_database_stats(self) -> Dict[str, Any]:
        """
        获取数据库统计信息
        
        Returns:
            统计信息字典
        """
        stats = {}
        
        try:
            # 基本统计
            tables = [
                'media_items', 'tv_shows', 'episodes', 'media_files', 
                'duplicate_files', 'scan_history', 'settings'
            ]
            
            for table in tables:
                try:
                    result = self.execute_query(f"SELECT COUNT(*) as count FROM {table}")
                    stats[f"{table}_count"] = result[0]['count'] if result else 0
                except:
                    stats[f"{table}_count"] = 0
            
            # 数据库大小
            try:
                result = self.execute_query("PRAGMA page_count")
                page_count = result[0][0] if result else 0
                result = self.execute_query("PRAGMA page_size")
                page_size = result[0][0] if result else 0
                stats['database_size_bytes'] = page_count * page_size
                stats['database_size_mb'] = round(stats['database_size_bytes'] / (1024 * 1024), 2)
            except:
                stats['database_size_bytes'] = 0
                stats['database_size_mb'] = 0
            
            # WAL模式状态
            try:
                result = self.execute_query("PRAGMA journal_mode")
                stats['journal_mode'] = result[0][0] if result else 'unknown'
            except:
                stats['journal_mode'] = 'unknown'
            
            # 缓存大小
            try:
                result = self.execute_query("PRAGMA cache_size")
                stats['cache_size'] = result[0][0] if result else 0
            except:
                stats['cache_size'] = 0
                
            stats['connection_pool_size'] = self.pool_size
            stats['last_updated'] = datetime.now().isoformat()
            
        except Exception as e:
            self.logger.error(f"获取数据库统计失败: {e}")
            
        return stats
    
    def vacuum_database(self) -> bool:
        """
        清理数据库，回收空间
        
        Returns:
            是否成功
        """
        try:
            with self.get_connection() as conn:
                conn.execute("VACUUM")
                conn.commit()
            self.logger.info("数据库清理完成")
            return True
        except Exception as e:
            self.logger.error(f"数据库清理失败: {e}")
            return False
    
    def backup_database(self, backup_path: str) -> bool:
        """
        备份数据库
        
        Args:
            backup_path: 备份文件路径
            
        Returns:
            是否备份成功
        """
        try:
            # 确保备份目录存在
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            
            with self.get_connection() as source:
                backup = sqlite3.connect(backup_path)
                try:
                    source.backup(backup)
                    self.logger.info(f"数据库备份完成: {backup_path}")
                    return True
                finally:
                    backup.close()
                    
        except Exception as e:
            self.logger.error(f"数据库备份失败: {e}")
            return False
    
    def check_database_integrity(self) -> bool:
        """
        检查数据库完整性
        
        Returns:
            数据库是否完整
        """
        try:
            result = self.execute_query("PRAGMA integrity_check")
            if result and result[0][0] == 'ok':
                self.logger.info("数据库完整性检查通过")
                return True
            else:
                self.logger.error(f"数据库完整性检查失败: {result}")
                return False
        except Exception as e:
            self.logger.error(f"数据库完整性检查失败: {e}")
            return False
    
    def close_all_connections(self):
        """关闭所有连接池中的连接"""
        with self._pool_lock:
            while not self._connection_pool.empty():
                try:
                    conn = self._connection_pool.get_nowait()
                    conn.close()
                except Empty:
                    break
            self.logger.info("所有数据库连接已关闭")


# 全局数据库管理器实例
db_manager = None

def get_db_manager(db_path: Optional[str] = None, pool_size: int = 5) -> DatabaseManager:
    """获取全局数据库管理器实例"""
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager(db_path, pool_size)
    return db_manager


if __name__ == "__main__":
    # 测试代码
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    # 创建数据库管理器实例
    db = DatabaseManager()
    
    # 检查数据库完整性
    db.check_database_integrity()
    
    # 获取数据库统计信息
    stats = db.get_database_stats()
    print("数据库统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # 测试配置功能
    db.set_setting("test_key", {"test": "value"}, "测试配置")
    test_value = db.get_setting("test_key")
    print(f"测试配置值: {test_value}")
    
    # 关闭连接
    db.close_all_connections()