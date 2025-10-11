#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库管理器
负责SQLite数据库的初始化、连接管理和基本操作
"""

import sqlite3
import os
import json
import logging
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, Any, List, Tuple

class DatabaseManager:
    """数据库管理器类"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        初始化数据库管理器
        
        Args:
            db_path: 数据库文件路径，默认为当前目录下的media_library.db
        """
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'media_library.db')
        
        self.db_path = os.path.abspath(db_path)
        self.schema_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # 设置日志
        self.logger = logging.getLogger(__name__)
        
        # 初始化数据库
        self.initialize_database()
    
    def initialize_database(self):
        """初始化数据库，创建表结构"""
        try:
            with self.get_connection() as conn:
                # 启用外键约束
                conn.execute("PRAGMA foreign_keys = ON")
                
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
                    
        except Exception as e:
            self.logger.error(f"数据库初始化失败: {e}")
            raise
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
            conn.execute("PRAGMA foreign_keys = ON")  # 启用外键约束
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            self.logger.error(f"数据库连接错误: {e}")
            raise
        finally:
            if conn:
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
        批量执行语句
        
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
        try:
            stats = {}
            
            # 媒体项目统计
            result = self.execute_query(
                "SELECT type, COUNT(*) as count FROM media_items GROUP BY type"
            )
            for row in result:
                stats[f"{row['type']}_count"] = row['count']
            
            # 文件统计
            file_stats = self.execute_query(
                "SELECT COUNT(*) as total_files, SUM(file_size) as total_size FROM media_files"
            )[0]
            stats['total_files'] = file_stats['total_files']
            stats['total_size'] = file_stats['total_size'] or 0
            
            # 重复文件统计
            duplicate_stats = self.execute_query(
                "SELECT COUNT(*) as duplicate_groups FROM duplicate_files WHERE file_count > 1"
            )[0]
            stats['duplicate_groups'] = duplicate_stats['duplicate_groups']
            
            # 最近扫描统计
            recent_scan = self.execute_query(
                "SELECT * FROM scan_history ORDER BY start_time DESC LIMIT 1"
            )
            if recent_scan:
                stats['last_scan'] = recent_scan[0]['start_time']
                stats['last_scan_status'] = recent_scan[0]['status']
            
            return stats
        except Exception as e:
            self.logger.error(f"获取数据库统计失败: {e}")
            return {}
    
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
            import shutil
            
            # 确保备份目录存在
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            
            # 复制数据库文件
            shutil.copy2(self.db_path, backup_path)
            
            self.logger.info(f"数据库备份完成: {backup_path}")
            return True
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
                self.logger.error("数据库完整性检查失败")
                return False
        except Exception as e:
            self.logger.error(f"数据库完整性检查错误: {e}")
            return False


# 全局数据库管理器实例
db_manager = None

def get_db_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """获取数据库管理器实例（单例模式）"""
    global db_manager
    if db_manager is None:
        db_manager = DatabaseManager(db_path)
    return db_manager


if __name__ == "__main__":
    # 测试数据库管理器
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    # 创建数据库管理器
    db = DatabaseManager()
    
    # 检查数据库完整性
    db.check_database_integrity()
    
    # 获取统计信息
    stats = db.get_database_stats()
    print("数据库统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # 测试配置管理
    db.set_setting("test_key", {"test": "value"}, "测试配置")
    test_value = db.get_setting("test_key")
    print(f"测试配置值: {test_value}")