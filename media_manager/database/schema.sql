-- 媒体库管理系统数据库表结构
-- 适用于群晖NAS环境，支持电影和电视剧管理

-- 统一的媒体内容表
CREATE TABLE IF NOT EXISTS media_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('movie', 'tv_show')),
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    tmdb_id INTEGER UNIQUE,
    imdb_id TEXT,
    overview TEXT,
    poster_path TEXT,
    backdrop_path TEXT,
    genres TEXT, -- JSON格式存储
    languages TEXT, -- JSON格式存储
    runtime INTEGER, -- 电影用，剧集为NULL
    status TEXT DEFAULT 'active',
    rating REAL,
    vote_count INTEGER,
    popularity REAL,
    adult BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_scanned TIMESTAMP
);

-- 电视剧专用表
CREATE TABLE IF NOT EXISTS tv_shows (
    media_id INTEGER PRIMARY KEY,
    total_seasons INTEGER DEFAULT 0,
    total_episodes INTEGER DEFAULT 0,
    first_air_date DATE,
    last_air_date DATE,
    episode_runtime TEXT, -- JSON格式，每集时长可能不同
    tvdb_id INTEGER,
    network TEXT,
    origin_country TEXT,
    in_production BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (media_id) REFERENCES media_items(id) ON DELETE CASCADE
);

-- 剧集表
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tv_show_id INTEGER NOT NULL,
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    title TEXT,
    overview TEXT,
    air_date DATE,
    runtime INTEGER,
    tmdb_id INTEGER,
    tvdb_id INTEGER,
    still_path TEXT,
    vote_average REAL,
    vote_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tv_show_id) REFERENCES tv_shows(media_id) ON DELETE CASCADE,
    UNIQUE(tv_show_id, season_number, episode_number)
);

-- 文件表（统一管理所有媒体文件）
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id INTEGER NOT NULL,
    episode_id INTEGER NULL, -- 电影为NULL，剧集指向具体集
    file_path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_size BIGINT,
    file_hash TEXT, -- SHA256哈希
    duration INTEGER, -- 秒
    resolution TEXT, -- 1080p, 2160p等
    width INTEGER,
    height INTEGER,
    video_codec TEXT,
    audio_codec TEXT,
    audio_channels TEXT,
    container TEXT, -- mkv, mp4等
    bitrate INTEGER,
    frame_rate REAL,
    release_group TEXT,
    source_type TEXT, -- BluRay, WEB-DL, HDTV等
    quality_score INTEGER DEFAULT 0, -- 自定义质量评分
    is_primary BOOLEAN DEFAULT FALSE, -- 是否为主版本
    is_sample BOOLEAN DEFAULT FALSE, -- 是否为样本文件
    subtitle_tracks TEXT, -- JSON格式存储字幕轨道信息
    audio_tracks TEXT, -- JSON格式存储音频轨道信息
    scan_status TEXT DEFAULT 'pending', -- pending, processing, completed, error
    error_message TEXT,
    volume_id INTEGER REFERENCES storage_volumes(id), -- 存储卷ID
    relative_path TEXT, -- 相对于卷根目录的路径
    directory_path TEXT, -- 文件所在目录的路径
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_verified TIMESTAMP,
    FOREIGN KEY (media_id) REFERENCES media_items(id) ON DELETE CASCADE,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);

-- 重复文件表
CREATE TABLE IF NOT EXISTS duplicate_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT UNIQUE NOT NULL, -- 重复组的唯一标识符
    file_count INTEGER NOT NULL DEFAULT 0,
    total_size BIGINT NOT NULL DEFAULT 0,
    detection_type TEXT DEFAULT 'hash', -- hash, similarity
    primary_file_id INTEGER, -- 指向主要保留的文件
    cross_volume BOOLEAN DEFAULT FALSE, -- 是否跨卷重复
    volume_distribution TEXT, -- JSON格式的卷分布信息
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (primary_file_id) REFERENCES media_files(id)
);

-- 重复文件关联表
CREATE TABLE IF NOT EXISTS duplicate_file_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    duplicate_group_id INTEGER NOT NULL,
    media_file_id INTEGER NOT NULL, -- 与代码中的字段名保持一致
    is_primary BOOLEAN DEFAULT FALSE,
    action_recommended TEXT, -- keep, delete, archive
    remove_reason TEXT, -- 删除原因
    space_savings BIGINT DEFAULT 0, -- 删除此文件可节省的空间
    FOREIGN KEY (duplicate_group_id) REFERENCES duplicate_files(id) ON DELETE CASCADE,
    FOREIGN KEY (media_file_id) REFERENCES media_files(id) ON DELETE CASCADE,
    UNIQUE(duplicate_group_id, media_file_id)
);

-- 扫描历史表
CREATE TABLE IF NOT EXISTS scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_type TEXT NOT NULL, -- full, incremental, verify
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    status TEXT DEFAULT 'running', -- running, completed, failed, cancelled
    files_scanned INTEGER DEFAULT 0,
    files_added INTEGER DEFAULT 0,
    files_updated INTEGER DEFAULT 0,
    files_removed INTEGER DEFAULT 0,
    duplicates_found INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    scan_path TEXT,
    error_log TEXT,
    summary TEXT -- JSON格式的扫描摘要
);

-- 配置表
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 存储卷管理表
CREATE TABLE IF NOT EXISTS storage_volumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_name TEXT NOT NULL UNIQUE, -- 卷名称，如 volume1, volume2
    mount_path TEXT NOT NULL UNIQUE, -- 挂载路径，如 /volume1, /volume2
    volume_type TEXT DEFAULT 'local', -- 卷类型：local, network, cloud
    is_active BOOLEAN DEFAULT TRUE, -- 是否活跃可用
    total_space BIGINT DEFAULT 0, -- 总空间（字节）
    free_space BIGINT DEFAULT 0, -- 可用空间（字节）
    description TEXT, -- 卷描述
    priority INTEGER DEFAULT 0, -- 优先级，数字越大优先级越高
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_checked TIMESTAMP -- 最后检查时间
);

-- 扫描路径配置表
CREATE TABLE IF NOT EXISTS scan_paths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    volume_id INTEGER NOT NULL,
    path_type TEXT NOT NULL CHECK (path_type IN ('movies', 'tv_shows', 'documentaries', 'music', 'other')),
    relative_path TEXT NOT NULL, -- 相对于卷根目录的路径
    full_path TEXT NOT NULL, -- 完整路径（冗余字段，便于查询）
    is_enabled BOOLEAN DEFAULT TRUE, -- 是否启用扫描
    scan_recursive BOOLEAN DEFAULT TRUE, -- 是否递归扫描
    exclude_patterns TEXT, -- JSON格式的排除模式
    priority INTEGER DEFAULT 0, -- 扫描优先级
    last_scanned TIMESTAMP, -- 最后扫描时间
    file_count INTEGER DEFAULT 0, -- 文件数量
    total_size BIGINT DEFAULT 0, -- 总大小
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (volume_id) REFERENCES storage_volumes(id) ON DELETE CASCADE,
    UNIQUE(volume_id, relative_path)
);

-- 目录映射表（用于处理目录重命名和移动）
CREATE TABLE IF NOT EXISTS directory_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    old_path TEXT NOT NULL,
    new_path TEXT NOT NULL,
    volume_id INTEGER NOT NULL,
    mapping_type TEXT DEFAULT 'moved', -- moved, renamed, merged
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    FOREIGN KEY (volume_id) REFERENCES storage_volumes(id) ON DELETE CASCADE
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_media_items_type ON media_items(type);
CREATE INDEX IF NOT EXISTS idx_media_items_title ON media_items(title);
CREATE INDEX IF NOT EXISTS idx_media_items_year ON media_items(year);
CREATE INDEX IF NOT EXISTS idx_media_items_tmdb_id ON media_items(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_media_items_imdb_id ON media_items(imdb_id);

CREATE INDEX IF NOT EXISTS idx_episodes_tv_show ON episodes(tv_show_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season ON episodes(tv_show_id, season_number);

CREATE INDEX IF NOT EXISTS idx_media_files_media_id ON media_files(media_id);
CREATE INDEX IF NOT EXISTS idx_media_files_episode_id ON media_files(episode_id);
CREATE INDEX IF NOT EXISTS idx_media_files_hash ON media_files(file_hash);
CREATE INDEX IF NOT EXISTS idx_media_files_size ON media_files(file_size);
CREATE INDEX IF NOT EXISTS idx_media_files_path ON media_files(file_path);
CREATE INDEX IF NOT EXISTS idx_media_files_primary ON media_files(is_primary);

CREATE INDEX IF NOT EXISTS idx_duplicate_files_group_id ON duplicate_files(group_id);
CREATE INDEX IF NOT EXISTS idx_duplicate_files_total_size ON duplicate_files(total_size);
CREATE INDEX IF NOT EXISTS idx_duplicate_files_detection_type ON duplicate_files(detection_type);
CREATE INDEX IF NOT EXISTS idx_duplicate_files_cross_volume ON duplicate_files(cross_volume);
CREATE INDEX IF NOT EXISTS idx_duplicate_file_items_group ON duplicate_file_items(duplicate_group_id);
CREATE INDEX IF NOT EXISTS idx_duplicate_file_items_file ON duplicate_file_items(media_file_id);

CREATE INDEX IF NOT EXISTS idx_scan_history_status ON scan_history(status);
CREATE INDEX IF NOT EXISTS idx_scan_history_start_time ON scan_history(start_time);

-- 存储卷和目录管理相关索引
CREATE INDEX IF NOT EXISTS idx_storage_volumes_name ON storage_volumes(volume_name);
CREATE INDEX IF NOT EXISTS idx_storage_volumes_active ON storage_volumes(is_active);
CREATE INDEX IF NOT EXISTS idx_storage_volumes_priority ON storage_volumes(priority DESC);

CREATE INDEX IF NOT EXISTS idx_scan_paths_volume ON scan_paths(volume_id);
CREATE INDEX IF NOT EXISTS idx_scan_paths_type ON scan_paths(path_type);
CREATE INDEX IF NOT EXISTS idx_scan_paths_enabled ON scan_paths(is_enabled);
CREATE INDEX IF NOT EXISTS idx_scan_paths_full_path ON scan_paths(full_path);
CREATE INDEX IF NOT EXISTS idx_scan_paths_priority ON scan_paths(priority DESC);

CREATE INDEX IF NOT EXISTS idx_directory_mappings_volume ON directory_mappings(volume_id);
CREATE INDEX IF NOT EXISTS idx_directory_mappings_old_path ON directory_mappings(old_path);
CREATE INDEX IF NOT EXISTS idx_directory_mappings_new_path ON directory_mappings(new_path);
CREATE INDEX IF NOT EXISTS idx_directory_mappings_active ON directory_mappings(is_active);

-- 插入默认配置
INSERT OR IGNORE INTO settings (key, value, description) VALUES
('tmdb_api_key', '', 'TMDB API密钥'),
('scan_paths', '[]', 'JSON格式的扫描路径列表'),
('video_extensions', '["mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "3gp", "ts", "m2ts"]', '支持的视频文件扩展名'),
('min_file_size', '104857600', '最小文件大小（字节），默认100MB'),
('quality_preferences', '{"resolution": ["2160p", "1080p", "720p", "480p"], "source": ["BluRay", "WEB-DL", "HDTV"], "codec": ["HEVC", "H264"]}', 'JSON格式的质量偏好设置'),
('duplicate_action', 'mark_only', '重复文件处理方式：mark_only, move_to_folder, delete'),
('backup_folder', '/volume1/media_backup', '备份文件夹路径'),
('max_concurrent_scans', '4', '最大并发扫描数'),
('enable_metadata_fetch', 'true', '是否启用元数据获取'),
('language_preference', 'zh-CN,en-US', '语言偏好设置');

-- 插入默认存储卷配置（群晖NAS典型配置）
INSERT OR IGNORE INTO storage_volumes (volume_name, mount_path, volume_type, description, priority) VALUES
('volume1', '/volume1', 'local', '主存储卷 - 系统和应用', 100),
('volume2', '/volume2', 'local', '媒体存储卷 - 电影和电视剧', 90),
('volume3', '/volume3', 'local', '备份存储卷', 80);

-- 插入默认扫描路径配置
INSERT OR IGNORE INTO scan_paths (volume_id, path_type, relative_path, full_path, priority) VALUES
(1, 'movies', 'video/movies', '/volume1/video/movies', 100),
(1, 'tv_shows', 'video/tv_shows', '/volume1/video/tv_shows', 95),
(2, 'movies', 'movies', '/volume2/movies', 90),
(2, 'tv_shows', 'tv_shows', '/volume2/tv_shows', 85),
(2, 'documentaries', 'documentaries', '/volume2/documentaries', 80);

-- 为新字段创建索引
CREATE INDEX IF NOT EXISTS idx_media_files_volume ON media_files(volume_id);
CREATE INDEX IF NOT EXISTS idx_media_files_relative_path ON media_files(relative_path);
CREATE INDEX IF NOT EXISTS idx_media_files_directory ON media_files(directory_path);