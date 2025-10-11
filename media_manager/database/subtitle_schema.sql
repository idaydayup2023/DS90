-- 字幕信息管理扩展表结构
-- 用于存储和管理媒体文件的字幕信息，特别是ai.srt字幕

-- 字幕文件表
CREATE TABLE IF NOT EXISTS subtitle_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_file_id INTEGER NOT NULL, -- 关联的媒体文件ID
    subtitle_path TEXT NOT NULL, -- 字幕文件完整路径
    subtitle_name TEXT NOT NULL, -- 字幕文件名
    subtitle_type TEXT NOT NULL CHECK (subtitle_type IN ('ai', 'manual', 'downloaded', 'embedded', 'other')), -- 字幕类型
    language_code TEXT NOT NULL DEFAULT 'zh-CN', -- 语言代码 (ISO 639-1)
    language_name TEXT DEFAULT '中文', -- 语言名称
    encoding TEXT DEFAULT 'UTF-8', -- 字符编码
    format TEXT NOT NULL CHECK (format IN ('srt', 'ass', 'ssa', 'vtt', 'sub', 'idx', 'sup')), -- 字幕格式
    file_size BIGINT DEFAULT 0, -- 文件大小（字节）
    file_hash TEXT, -- 文件哈希值
    is_default BOOLEAN DEFAULT FALSE, -- 是否为默认字幕
    is_forced BOOLEAN DEFAULT FALSE, -- 是否为强制字幕
    is_ai_generated BOOLEAN DEFAULT FALSE, -- 是否为AI生成
    ai_model TEXT, -- AI模型名称（如果是AI生成）
    ai_confidence REAL, -- AI生成置信度 (0.0-1.0)
    subtitle_count INTEGER DEFAULT 0, -- 字幕条目数量
    duration INTEGER, -- 字幕总时长（秒）
    sync_offset INTEGER DEFAULT 0, -- 同步偏移量（毫秒）
    quality_score REAL DEFAULT 0.0, -- 质量评分 (0.0-10.0)
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'error', 'missing')), -- 状态
    error_message TEXT, -- 错误信息
    volume_id INTEGER, -- 存储卷ID
    relative_path TEXT, -- 相对于卷根目录的路径
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_verified TIMESTAMP, -- 最后验证时间
    FOREIGN KEY (media_file_id) REFERENCES media_files(id) ON DELETE CASCADE,
    FOREIGN KEY (volume_id) REFERENCES storage_volumes(id),
    UNIQUE(media_file_id, subtitle_path)
);

-- 字幕内容分析表（用于存储字幕的详细分析信息）
CREATE TABLE IF NOT EXISTS subtitle_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subtitle_file_id INTEGER NOT NULL,
    total_lines INTEGER DEFAULT 0, -- 总行数
    dialogue_lines INTEGER DEFAULT 0, -- 对话行数
    avg_line_length REAL DEFAULT 0.0, -- 平均行长度
    max_line_length INTEGER DEFAULT 0, -- 最大行长度
    reading_speed REAL DEFAULT 0.0, -- 阅读速度（字符/秒）
    timing_accuracy REAL DEFAULT 0.0, -- 时间轴准确度
    overlap_count INTEGER DEFAULT 0, -- 重叠字幕数量
    gap_count INTEGER DEFAULT 0, -- 间隙数量
    style_consistency REAL DEFAULT 0.0, -- 样式一致性评分
    language_detection TEXT, -- 检测到的语言
    contains_music BOOLEAN DEFAULT FALSE, -- 是否包含音乐标记
    contains_sound_effects BOOLEAN DEFAULT FALSE, -- 是否包含音效标记
    analysis_version TEXT DEFAULT '1.0', -- 分析版本
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subtitle_file_id) REFERENCES subtitle_files(id) ON DELETE CASCADE
);

-- 字幕匹配规则表（用于定义字幕文件与视频文件的匹配规则）
CREATE TABLE IF NOT EXISTS subtitle_matching_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name TEXT NOT NULL UNIQUE, -- 规则名称
    rule_type TEXT NOT NULL CHECK (rule_type IN ('filename', 'directory', 'pattern', 'ai_special')), -- 规则类型
    pattern TEXT NOT NULL, -- 匹配模式
    priority INTEGER DEFAULT 0, -- 优先级
    is_enabled BOOLEAN DEFAULT TRUE, -- 是否启用
    description TEXT, -- 规则描述
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 字幕扫描历史表
CREATE TABLE IF NOT EXISTS subtitle_scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER, -- 关联主扫描历史
    media_file_id INTEGER, -- 关联的媒体文件
    subtitles_found INTEGER DEFAULT 0, -- 发现的字幕数量
    ai_subtitles_found INTEGER DEFAULT 0, -- 发现的AI字幕数量
    missing_ai_subtitles INTEGER DEFAULT 0, -- 缺失的AI字幕数量
    scan_duration REAL DEFAULT 0.0, -- 扫描耗时（秒）
    errors_count INTEGER DEFAULT 0, -- 错误数量
    warnings_count INTEGER DEFAULT 0, -- 警告数量
    scan_status TEXT DEFAULT 'completed' CHECK (scan_status IN ('pending', 'running', 'completed', 'failed')),
    error_details TEXT, -- 错误详情
    scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scan_id) REFERENCES scan_history(id) ON DELETE CASCADE,
    FOREIGN KEY (media_file_id) REFERENCES media_files(id) ON DELETE CASCADE
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_subtitle_files_media_file ON subtitle_files(media_file_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_type ON subtitle_files(subtitle_type);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_language ON subtitle_files(language_code);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_format ON subtitle_files(format);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_ai_generated ON subtitle_files(is_ai_generated);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_default ON subtitle_files(is_default);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_status ON subtitle_files(status);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_volume ON subtitle_files(volume_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_path ON subtitle_files(subtitle_path);
CREATE INDEX IF NOT EXISTS idx_subtitle_files_hash ON subtitle_files(file_hash);

CREATE INDEX IF NOT EXISTS idx_subtitle_analysis_file ON subtitle_analysis(subtitle_file_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_analysis_analyzed_at ON subtitle_analysis(analyzed_at);

CREATE INDEX IF NOT EXISTS idx_subtitle_matching_rules_type ON subtitle_matching_rules(rule_type);
CREATE INDEX IF NOT EXISTS idx_subtitle_matching_rules_enabled ON subtitle_matching_rules(is_enabled);
CREATE INDEX IF NOT EXISTS idx_subtitle_matching_rules_priority ON subtitle_matching_rules(priority DESC);

CREATE INDEX IF NOT EXISTS idx_subtitle_scan_history_scan ON subtitle_scan_history(scan_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_scan_history_media_file ON subtitle_scan_history(media_file_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_scan_history_status ON subtitle_scan_history(scan_status);
CREATE INDEX IF NOT EXISTS idx_subtitle_scan_history_scanned_at ON subtitle_scan_history(scanned_at);

-- 插入默认的字幕匹配规则
INSERT OR IGNORE INTO subtitle_matching_rules (rule_name, rule_type, pattern, priority, description) VALUES
('AI字幕文件', 'filename', '*.ai.srt', 100, '匹配AI生成的字幕文件，格式为 filename.ai.srt'),
('同名SRT字幕', 'filename', '*.srt', 90, '匹配与视频文件同名的SRT字幕文件'),
('中文字幕', 'filename', '*.zh*.srt', 85, '匹配包含中文标识的字幕文件'),
('英文字幕', 'filename', '*.en*.srt', 80, '匹配包含英文标识的字幕文件'),
('ASS字幕文件', 'filename', '*.ass', 75, '匹配ASS格式字幕文件'),
('VTT字幕文件', 'filename', '*.vtt', 70, '匹配WebVTT格式字幕文件'),
('字幕目录', 'directory', 'Subs/*', 60, '匹配Subs子目录中的字幕文件'),
('字幕目录2', 'directory', 'Subtitles/*', 55, '匹配Subtitles子目录中的字幕文件');

-- 插入字幕相关的系统设置
INSERT OR IGNORE INTO settings (key, value, description) VALUES
('subtitle_extensions', '["srt", "ass", "ssa", "vtt", "sub", "idx", "sup"]', '支持的字幕文件扩展名'),
('subtitle_languages', '["zh-CN", "en-US", "ja-JP", "ko-KR"]', '支持的字幕语言'),
('ai_subtitle_required', 'true', '是否要求所有视频都有AI字幕'),
('ai_subtitle_format', 'srt', 'AI字幕的默认格式'),
('subtitle_encoding_detection', 'true', '是否启用字幕编码自动检测'),
('subtitle_quality_check', 'true', '是否启用字幕质量检查'),
('subtitle_sync_tolerance', '500', '字幕同步容差（毫秒）'),
('subtitle_scan_recursive', 'true', '是否递归扫描字幕文件'),
('subtitle_backup_enabled', 'true', '是否启用字幕文件备份');