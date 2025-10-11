#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
应用字幕Schema到现有数据库
"""

import os
import sys
import logging

# 添加项目路径到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from media_manager.database.db_manager import get_db_manager

def apply_subtitle_schema():
    """应用字幕Schema到数据库"""
    
    db = get_db_manager()
    
    # 字幕文件表
    subtitle_files_sql = """
    CREATE TABLE IF NOT EXISTS subtitle_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        media_file_id INTEGER NOT NULL,
        subtitle_path TEXT NOT NULL UNIQUE,
        subtitle_name TEXT NOT NULL,
        subtitle_type TEXT NOT NULL DEFAULT 'other',
        language_code TEXT NOT NULL DEFAULT 'zh-CN',
        language_name TEXT NOT NULL DEFAULT '中文',
        encoding TEXT NOT NULL DEFAULT 'UTF-8',
        format TEXT NOT NULL DEFAULT 'srt',
        file_size INTEGER NOT NULL DEFAULT 0,
        file_hash TEXT NOT NULL DEFAULT '',
        is_ai_generated BOOLEAN NOT NULL DEFAULT 0,
        subtitle_count INTEGER NOT NULL DEFAULT 0,
        duration INTEGER NOT NULL DEFAULT 0,
        quality_score REAL NOT NULL DEFAULT 0.0,
        ai_confidence REAL NOT NULL DEFAULT 0.0,
        volume_id INTEGER,
        relative_path TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (media_file_id) REFERENCES media_files(id) ON DELETE CASCADE,
        FOREIGN KEY (volume_id) REFERENCES storage_volumes(id) ON DELETE SET NULL
    )
    """
    
    # 字幕分析表
    subtitle_analysis_sql = """
    CREATE TABLE IF NOT EXISTS subtitle_analysis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subtitle_file_id INTEGER NOT NULL,
        analysis_type TEXT NOT NULL DEFAULT 'content',
        analysis_data TEXT,
        confidence_score REAL NOT NULL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (subtitle_file_id) REFERENCES subtitle_files(id) ON DELETE CASCADE
    )
    """
    
    # 字幕匹配规则表
    subtitle_matching_rules_sql = """
    CREATE TABLE IF NOT EXISTS subtitle_matching_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name TEXT NOT NULL UNIQUE,
        rule_type TEXT NOT NULL DEFAULT 'filename',
        pattern TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 0,
        is_enabled BOOLEAN NOT NULL DEFAULT 1,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    
    # 字幕扫描历史表
    subtitle_scan_history_sql = """
    CREATE TABLE IF NOT EXISTS subtitle_scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_path TEXT NOT NULL,
        subtitles_found INTEGER NOT NULL DEFAULT 0,
        subtitles_processed INTEGER NOT NULL DEFAULT 0,
        ai_subtitles_found INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        scan_duration REAL NOT NULL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    
    # 创建索引
    indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_subtitle_files_media_file_id ON subtitle_files(media_file_id)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_files_type ON subtitle_files(subtitle_type)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_files_language ON subtitle_files(language_code)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_files_ai_generated ON subtitle_files(is_ai_generated)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_files_path ON subtitle_files(subtitle_path)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_files_hash ON subtitle_files(file_hash)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_analysis_file_id ON subtitle_analysis(subtitle_file_id)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_matching_rules_enabled ON subtitle_matching_rules(is_enabled)",
        "CREATE INDEX IF NOT EXISTS idx_subtitle_scan_history_path ON subtitle_scan_history(scan_path)"
    ]
    
    try:
        print("开始应用字幕Schema...")
        
        # 创建表
        print("创建字幕文件表...")
        db.execute_update(subtitle_files_sql)
        
        print("创建字幕分析表...")
        db.execute_update(subtitle_analysis_sql)
        
        print("创建字幕匹配规则表...")
        db.execute_update(subtitle_matching_rules_sql)
        
        print("创建字幕扫描历史表...")
        db.execute_update(subtitle_scan_history_sql)
        
        # 创建索引
        print("创建索引...")
        for index_sql in indexes_sql:
            db.execute_update(index_sql)
        
        # 插入默认匹配规则
        print("插入默认匹配规则...")
        default_rules = [
            ('AI字幕匹配', 'filename', '*.ai.srt', 100, 1, 'AI生成的字幕文件'),
            ('同名字幕匹配', 'filename', '*', 90, 1, '与视频文件同名的字幕'),
            ('中文字幕匹配', 'filename', '*.zh*.srt', 80, 1, '中文字幕文件'),
            ('英文字幕匹配', 'filename', '*.en*.srt', 70, 1, '英文字幕文件'),
            ('字幕目录匹配', 'directory', 'Subs/*', 60, 1, '字幕子目录中的文件')
        ]
        
        for rule_name, rule_type, pattern, priority, is_enabled, description in default_rules:
            try:
                db.execute_insert("""
                    INSERT OR IGNORE INTO subtitle_matching_rules 
                    (rule_name, rule_type, pattern, priority, is_enabled, description)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (rule_name, rule_type, pattern, priority, is_enabled, description))
            except Exception as e:
                print(f"插入规则失败 {rule_name}: {e}")
        
        # 插入字幕相关设置
        print("插入字幕相关设置...")
        subtitle_settings = [
            ('subtitle_extensions', '["srt", "ass", "ssa", "vtt", "sub", "idx", "sup"]', '支持的字幕文件扩展名'),
            ('subtitle_languages', '["zh-CN", "en-US", "ja-JP", "ko-KR"]', '支持的字幕语言'),
            ('ai_subtitle_required', 'true', '是否要求AI字幕'),
            ('ai_subtitle_format', 'srt', 'AI字幕的默认格式'),
            ('subtitle_quality_threshold', '5.0', '字幕质量评分阈值'),
            ('subtitle_encoding_detection', 'true', '是否启用字幕编码检测')
        ]
        
        for key, value, description in subtitle_settings:
            try:
                db.execute_insert("""
                    INSERT OR IGNORE INTO settings (key, value, description)
                    VALUES (?, ?, ?)
                """, (key, value, description))
            except Exception as e:
                print(f"插入设置失败 {key}: {e}")
        
        print("字幕Schema应用完成！")
        
        # 验证表创建
        tables = db.execute_query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%subtitle%' ORDER BY name")
        print("\n创建的字幕相关表:")
        for table in tables:
            print(f"  - {table['name']}")
        
        return True
        
    except Exception as e:
        print(f"应用字幕Schema失败: {e}")
        return False

def main():
    """主函数"""
    logging.basicConfig(level=logging.INFO)
    
    print("字幕Schema应用工具")
    print("=" * 30)
    
    success = apply_subtitle_schema()
    
    if success:
        print("\n✅ 字幕Schema应用成功！")
    else:
        print("\n❌ 字幕Schema应用失败！")
        sys.exit(1)

if __name__ == "__main__":
    main()