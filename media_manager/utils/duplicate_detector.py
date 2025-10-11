#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重复文件检测器
负责检测和管理重复的媒体文件
"""

import os
import json
import hashlib
import logging
from typing import Dict, List, Set, Tuple, Optional, Any
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from ..database.db_manager import get_db_manager
from .directory_manager import get_directory_manager

@dataclass
class DuplicateGroup:
    """重复文件组"""
    group_id: str
    files: List[Dict[str, Any]]
    total_size: int
    file_count: int
    created_at: datetime

class DuplicateDetector:
    """重复文件检测器"""
    
    def __init__(self):
        """初始化重复文件检测器"""
        self.db = get_db_manager()
        self.directory_manager = get_directory_manager()
        self.logger = logging.getLogger(__name__)
        
        # 检测配置
        self.min_file_size = int(self.db.get_setting('min_file_size_mb', '10')) * 1024 * 1024
        self.hash_chunk_size = 8192
        
        # 相似度阈值
        self.name_similarity_threshold = 0.8
        self.size_difference_threshold = 0.05  # 5%
    
    def detect_duplicates_by_hash(self, volume_ids: Optional[List[int]] = None) -> List[DuplicateGroup]:
        """
        基于文件哈希检测重复文件
        
        Args:
            volume_ids: 指定要检测的卷ID列表，None表示检测所有卷
            
        Returns:
            重复文件组列表
        """
        self.logger.info("开始基于哈希值检测重复文件...")
        
        try:
            # 构建查询条件
            where_conditions = ["mf.file_size >= ?"]
            params = [self.min_file_size]
            
            if volume_ids:
                placeholders = ','.join(['?'] * len(volume_ids))
                where_conditions.append(f"mf.volume_id IN ({placeholders})")
                params.extend(volume_ids)
            
            # 获取所有媒体文件
            query = f"""
                SELECT mf.*, mi.title, mi.year, mi.type
                FROM media_files mf
                LEFT JOIN media_items mi ON mf.media_id = mi.id
                WHERE {' AND '.join(where_conditions)}
                ORDER BY mf.file_hash
            """
            
            files = self.db.execute_query(query, tuple(params))
            
            # 按哈希值分组
            hash_groups = defaultdict(list)
            for file_info in files:
                if file_info['file_hash']:
                    hash_groups[file_info['file_hash']].append(file_info)
            
            # 找出重复组
            duplicate_groups = []
            for file_hash, file_list in hash_groups.items():
                if len(file_list) > 1:
                    group = self._create_duplicate_group(file_list, 'hash')
                    duplicate_groups.append(group)
            
            self.logger.info(f"检测到 {len(duplicate_groups)} 个哈希重复组")
            return duplicate_groups
            
        except Exception as e:
            self.logger.error(f"哈希重复检测失败: {e}")
            return []
    
    def detect_duplicates_by_similarity(self) -> List[DuplicateGroup]:
        """
        基于文件相似度检测可能的重复文件
        
        Returns:
            可能重复的文件组列表
        """
        self.logger.info("开始基于相似度检测重复文件...")
        
        try:
            # 获取所有媒体文件
            files = self.db.execute_query("""
                SELECT mf.*, mi.title, mi.year, mi.type
                FROM media_files mf
                LEFT JOIN media_items mi ON mf.media_id = mi.id
                WHERE mf.file_size >= ?
                ORDER BY mi.title, mf.file_size DESC
            """, (self.min_file_size,))
            
            # 按标题和类型分组
            title_groups = defaultdict(list)
            for file_info in files:
                if file_info['title']:
                    key = (file_info['title'].lower(), file_info['type'])
                    title_groups[key].append(file_info)
            
            # 检测相似文件
            similar_groups = []
            for (title, media_type), file_list in title_groups.items():
                if len(file_list) > 1:
                    # 进一步检查文件相似度
                    similar_files = self._find_similar_files(file_list)
                    if similar_files:
                        for group in similar_files:
                            similar_group = self._create_duplicate_group(group, 'similarity')
                            similar_groups.append(similar_group)
            
            self.logger.info(f"检测到 {len(similar_groups)} 个相似重复组")
            return similar_groups
            
        except Exception as e:
            self.logger.error(f"相似度重复检测失败: {e}")
            return []
    
    def _find_similar_files(self, files: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        在文件列表中查找相似文件
        
        Args:
            files: 文件列表
            
        Returns:
            相似文件组列表
        """
        similar_groups = []
        processed = set()
        
        for i, file1 in enumerate(files):
            if i in processed:
                continue
            
            similar_group = [file1]
            processed.add(i)
            
            for j, file2 in enumerate(files[i+1:], i+1):
                if j in processed:
                    continue
                
                if self._are_files_similar(file1, file2):
                    similar_group.append(file2)
                    processed.add(j)
            
            if len(similar_group) > 1:
                similar_groups.append(similar_group)
        
        return similar_groups
    
    def _are_files_similar(self, file1: Dict[str, Any], file2: Dict[str, Any]) -> bool:
        """
        判断两个文件是否相似
        
        Args:
            file1: 文件1信息
            file2: 文件2信息
            
        Returns:
            是否相似
        """
        # 文件大小相似度检查
        size1, size2 = file1['file_size'], file2['file_size']
        if size1 and size2:
            size_diff = abs(size1 - size2) / max(size1, size2)
            if size_diff > self.size_difference_threshold:
                return False
        
        # 文件名相似度检查
        name1 = os.path.splitext(os.path.basename(file1['file_path']))[0].lower()
        name2 = os.path.splitext(os.path.basename(file2['file_path']))[0].lower()
        
        name_similarity = self._calculate_string_similarity(name1, name2)
        if name_similarity < self.name_similarity_threshold:
            return False
        
        # 分辨率和质量检查
        if file1.get('resolution') and file2.get('resolution'):
            if file1['resolution'] != file2['resolution']:
                # 不同分辨率可能是同一内容的不同版本
                return True
        
        # 编码格式检查
        if file1.get('video_codec') and file2.get('video_codec'):
            if file1['video_codec'] != file2['video_codec']:
                # 不同编码可能是同一内容的不同版本
                return True
        
        return True
    
    def _calculate_string_similarity(self, str1: str, str2: str) -> float:
        """
        计算字符串相似度
        
        Args:
            str1: 字符串1
            str2: 字符串2
            
        Returns:
            相似度分数 (0-1)
        """
        # 简单的编辑距离算法
        if not str1 or not str2:
            return 0.0
        
        if str1 == str2:
            return 1.0
        
        # 计算最长公共子序列
        m, n = len(str1), len(str2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if str1[i-1] == str2[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])
        
        lcs_length = dp[m][n]
        return (2.0 * lcs_length) / (m + n)
    
    def _analyze_volume_distribution(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        分析文件的卷分布
        
        Args:
            files: 文件列表
            
        Returns:
            卷分布信息
        """
        volume_counts = {}
        volume_sizes = {}
        
        for file_info in files:
            try:
                path_info = self.directory_manager.parse_file_path(file_info['file_path'])
                volume_name = path_info.get('volume_name', 'unknown')
                file_size = file_info.get('file_size', 0) or 0
                
                volume_counts[volume_name] = volume_counts.get(volume_name, 0) + 1
                volume_sizes[volume_name] = volume_sizes.get(volume_name, 0) + file_size
                
            except Exception:
                volume_name = 'unknown'
                file_size = file_info.get('file_size', 0) or 0
                volume_counts[volume_name] = volume_counts.get(volume_name, 0) + 1
                volume_sizes[volume_name] = volume_sizes.get(volume_name, 0) + file_size
        
        return {
            'volume_counts': volume_counts,
            'volume_sizes': volume_sizes,
            'cross_volume': len(volume_counts) > 1,
            'total_volumes': len(volume_counts)
        }
    
    def _create_duplicate_group(self, files: List[Dict[str, Any]], detection_type: str) -> DuplicateGroup:
        """
        创建重复文件组
        
        Args:
            files: 重复文件列表
            detection_type: 检测类型
            
        Returns:
            重复文件组
        """
        # 生成组ID
        file_ids = sorted([str(f['id']) for f in files])
        group_id = hashlib.md5(f"{detection_type}_{','.join(file_ids)}".encode()).hexdigest()[:16]
        
        # 计算总大小
        total_size = sum(f['file_size'] or 0 for f in files)
        
        # 分析卷分布
        volume_distribution = self._analyze_volume_distribution(files)
        
        # 为每个文件添加卷信息
        for file_info in files:
            try:
                path_info = self.directory_manager.parse_file_path(file_info['file_path'])
                file_info['volume_id'] = path_info.get('volume_id')
                file_info['volume_name'] = path_info.get('volume_name')
                file_info['relative_path'] = path_info.get('relative_path')
            except Exception as e:
                self.logger.warning(f"解析文件路径失败 {file_info['file_path']}: {e}")
                file_info['volume_id'] = None
                file_info['volume_name'] = 'unknown'
                file_info['relative_path'] = file_info['file_path']
        
        return DuplicateGroup(
            group_id=group_id,
            files=files,
            total_size=total_size,
            file_count=len(files),
            created_at=datetime.now()
        )
    
    def save_duplicate_groups(self, groups: List[DuplicateGroup]) -> int:
        """
        保存重复文件组到数据库
        
        Args:
            groups: 重复文件组列表
            
        Returns:
            保存的组数量
        """
        saved_count = 0
        
        try:
            for group in groups:
                # 检查组是否已存在
                existing = self.db.execute_query(
                    "SELECT id FROM duplicate_files WHERE group_id = ?",
                    (group.group_id,)
                )
                
                if existing:
                    continue
                
                # 分析卷分布
                volume_distribution = self._analyze_volume_distribution(group.files)
                
                # 插入重复文件组
                group_db_id = self.db.execute_insert("""
                    INSERT INTO duplicate_files (
                        group_id, file_count, total_size, detection_type,
                        cross_volume, volume_distribution, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    group.group_id, group.file_count, group.total_size, 'hash',
                    volume_distribution['cross_volume'], json.dumps(volume_distribution),
                    group.created_at
                ))
                
                if group_db_id:
                    # 选择最佳文件作为主文件
                    best_file = self._select_best_file(group.files)
                    
                    # 插入组内文件关联
                    for file_info in group.files:
                        is_primary = file_info['id'] == best_file.get('id', 0)
                        
                        # 计算删除此文件可节省的空间
                        space_savings = 0 if is_primary else (file_info.get('file_size', 0) or 0)
                        
                        # 获取删除原因
                        remove_reason = '' if is_primary else self._get_remove_reason(file_info, best_file)
                        
                        self.db.execute_insert("""
                            INSERT INTO duplicate_file_items (
                                duplicate_group_id, media_file_id, is_primary,
                                action_recommended, remove_reason, space_savings
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            group_db_id, file_info['id'], is_primary,
                            'keep' if is_primary else 'delete',
                            remove_reason, space_savings
                        ))
                    
                    # 更新主文件ID
                    if best_file:
                        self.db.execute_update("""
                            UPDATE duplicate_files SET primary_file_id = ? WHERE id = ?
                        """, (best_file['id'], group_db_id))
                    
                    saved_count += 1
            
            self.logger.info(f"保存了 {saved_count} 个重复文件组")
            return saved_count
            
        except Exception as e:
            self.logger.error(f"保存重复文件组失败: {e}")
            return saved_count
    
    def get_duplicate_groups(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取重复文件组
        
        Args:
            limit: 返回数量限制
            
        Returns:
            重复文件组列表
        """
        try:
            groups = self.db.execute_query("""
                SELECT df.*, COUNT(dfi.media_file_id) as actual_file_count
                FROM duplicate_files df
                LEFT JOIN duplicate_file_items dfi ON df.id = dfi.duplicate_group_id
                GROUP BY df.id
                ORDER BY df.total_size DESC, df.created_at DESC
                LIMIT ?
            """, (limit,))
            
            # 转换为字典列表并获取每组的文件详情
            result_groups = []
            for group in groups:
                group_dict = dict(group)
                
                files = self.db.execute_query("""
                    SELECT mf.*, mi.title, mi.year, mi.type
                    FROM duplicate_file_items dfi
                    JOIN media_files mf ON dfi.media_file_id = mf.id
                    LEFT JOIN media_items mi ON mf.media_id = mi.id
                    WHERE dfi.duplicate_group_id = ?
                    ORDER BY mf.file_size DESC
                """, (group_dict['id'],))
                
                # 转换为字典列表
                group_dict['files'] = [dict(file) for file in files]
                result_groups.append(group_dict)
            
            return result_groups
            
        except Exception as e:
            self.logger.error(f"获取重复文件组失败: {e}")
            return []
    
    def analyze_duplicate_space(self, volume_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        分析重复文件占用的空间
        
        Args:
            volume_ids: 指定要分析的卷ID列表，None表示分析所有卷
            
        Returns:
            空间分析结果
        """
        try:
            # 构建查询条件
            where_conditions = []
            params = []
            
            if volume_ids:
                # 查询涉及指定卷的重复文件组
                placeholders = ','.join(['?'] * len(volume_ids))
                where_conditions.append(f"""
                    df.id IN (
                        SELECT DISTINCT dfi.duplicate_group_id 
                        FROM duplicate_file_items dfi
                        JOIN media_files mf ON dfi.media_file_id = mf.id
                        WHERE mf.volume_id IN ({placeholders})
                    )
                """)
                params.extend(volume_ids)
            
            where_clause = f"WHERE {' AND '.join(where_conditions)}" if where_conditions else ""
            
            # 总体统计
            stats_query = f"""
                SELECT 
                    COUNT(DISTINCT df.id) as group_count,
                    SUM(df.total_size) as total_duplicate_size,
                    SUM(df.file_count) as total_duplicate_files,
                    COUNT(CASE WHEN df.cross_volume = 1 THEN 1 END) as cross_volume_groups
                FROM duplicate_files df
                {where_clause}
            """
            
            stats = self.db.execute_query(stats_query, tuple(params) if params else None)[0]
            
            # 可节省空间（保留每组中最大的文件）
            potential_savings_query = f"""
                SELECT SUM(
                    df.total_size - (
                        SELECT MAX(mf.file_size)
                        FROM duplicate_file_items dfi
                        JOIN media_files mf ON dfi.media_file_id = mf.id
                        WHERE dfi.duplicate_group_id = df.id
                    )
                ) as potential_savings
                FROM duplicate_files df
                {where_clause}
            """
            
            potential_savings = self.db.execute_query(potential_savings_query, tuple(params) if params else None)[0]
            
            # 按类型分组统计
            type_stats_query = f"""
                SELECT 
                    mi.type,
                    COUNT(DISTINCT df.id) as group_count,
                    SUM(df.total_size) as total_size
                FROM duplicate_files df
                JOIN duplicate_file_items dfi ON df.id = dfi.duplicate_group_id
                JOIN media_files mf ON dfi.media_file_id = mf.id
                JOIN media_items mi ON mf.media_id = mi.id
                {where_clause}
                GROUP BY mi.type
            """
            
            type_stats = self.db.execute_query(type_stats_query, tuple(params) if params else None)
            
            # 卷分布统计
            volume_distribution = {}
            if volume_ids:
                volume_stats = self.db.execute_query("""
                    SELECT 
                        JSON_EXTRACT(df.volume_distribution, '$.volume_counts') as volume_counts,
                        JSON_EXTRACT(df.volume_distribution, '$.volume_sizes') as volume_sizes
                    FROM duplicate_files df
                    WHERE df.id IN (
                        SELECT DISTINCT dfi.duplicate_group_id 
                        FROM duplicate_file_items dfi
                        JOIN media_files mf ON dfi.media_file_id = mf.id
                        WHERE mf.volume_id IN ({})
                    )
                """.format(','.join(['?'] * len(volume_ids))), tuple(volume_ids))
                
                for row in volume_stats:
                    if row['volume_counts']:
                        try:
                            counts = json.loads(row['volume_counts'])
                            sizes = json.loads(row['volume_sizes'])
                            
                            for volume, count in counts.items():
                                if volume not in volume_distribution:
                                    volume_distribution[volume] = {'count': 0, 'size': 0}
                                volume_distribution[volume]['count'] += count
                                volume_distribution[volume]['size'] += sizes.get(volume, 0)
                        except (json.JSONDecodeError, TypeError):
                            continue
            
            return {
                'total_groups': stats['group_count'] or 0,
                'total_duplicate_size': stats['total_duplicate_size'] or 0,
                'total_duplicate_files': stats['total_duplicate_files'] or 0,
                'potential_savings': potential_savings['potential_savings'] or 0,
                'cross_volume_groups': stats['cross_volume_groups'] or 0,
                'type_breakdown': type_stats,
                'volume_distribution': volume_distribution
            }
            
        except Exception as e:
            self.logger.error(f"分析重复空间失败: {e}")
            return {}
    
    def analyze_cross_volume_duplicates(self) -> Dict[str, Any]:
        """
        分析跨卷重复文件
        
        Returns:
            跨卷重复文件分析结果
        """
        try:
            # 获取跨卷重复文件组
            cross_volume_groups = self.db.execute_query("""
                SELECT 
                    df.group_id,
                    df.file_count,
                    df.total_size,
                    df.volume_distribution,
                    df.created_at
                FROM duplicate_files df
                WHERE df.cross_volume = 1
                ORDER BY df.total_size DESC
            """)
            
            analysis_results = []
            total_cross_volume_size = 0
            total_cross_volume_savings = 0
            
            for group in cross_volume_groups:
                # 解析卷分布
                try:
                    volume_dist = json.loads(group['volume_distribution'])
                    volume_counts = volume_dist.get('volume_counts', {})
                    volume_sizes = volume_dist.get('volume_sizes', {})
                except (json.JSONDecodeError, TypeError):
                    volume_counts = {}
                    volume_sizes = {}
                
                # 计算潜在节省空间（保留最大文件）
                max_file_size = max(volume_sizes.values()) if volume_sizes else 0
                potential_savings = group['total_size'] - max_file_size
                
                total_cross_volume_size += group['total_size']
                total_cross_volume_savings += potential_savings
                
                # 生成建议
                recommendations = self._generate_cross_volume_recommendations(
                    group['group_id'], volume_counts, volume_sizes
                )
                
                analysis_results.append({
                    'group_id': group['group_id'],
                    'file_count': group['file_count'],
                    'total_size': group['total_size'],
                    'potential_savings': potential_savings,
                    'volume_distribution': {
                        'counts': volume_counts,
                        'sizes': volume_sizes
                    },
                    'recommendations': recommendations,
                    'created_at': group['created_at']
                })
            
            return {
                'cross_volume_groups': analysis_results,
                'summary': {
                    'total_groups': len(cross_volume_groups),
                    'total_size': total_cross_volume_size,
                    'potential_savings': total_cross_volume_savings,
                    'savings_percentage': (total_cross_volume_savings / total_cross_volume_size * 100) 
                                        if total_cross_volume_size > 0 else 0.0
                }
            }
            
        except Exception as e:
            self.logger.error(f"分析跨卷重复文件失败: {e}")
            return {
                'cross_volume_groups': [],
                'summary': {
                    'total_groups': 0,
                    'total_size': 0,
                    'potential_savings': 0,
                    'savings_percentage': 0.0
                }
            }
    
    def _generate_cross_volume_recommendations(self, group_id: str, volume_counts: Dict[str, int], 
                                             volume_sizes: Dict[str, int]) -> List[Dict[str, Any]]:
        """
        为跨卷重复文件组生成建议
        
        Args:
            group_id: 重复文件组ID
            volume_counts: 各卷文件数量
            volume_sizes: 各卷文件大小
            
        Returns:
            建议列表
        """
        recommendations = []
        
        try:
            # 找出最大文件所在的卷
            if volume_sizes:
                best_volume = max(volume_sizes.items(), key=lambda x: x[1])[0]
                
                # 为每个卷生成建议
                for volume, count in volume_counts.items():
                    if volume != best_volume:
                        size = volume_sizes.get(volume, 0)
                        recommendations.append({
                            'volume': volume,
                            'action': 'delete',
                            'reason': f'保留{best_volume}卷中的最大文件',
                            'file_count': count,
                            'space_savings': size,
                            'priority': 'high' if size > 100 * 1024 * 1024 else 'medium'  # 100MB
                        })
                
                # 为最佳卷添加保留建议
                recommendations.append({
                    'volume': best_volume,
                    'action': 'keep',
                    'reason': '包含最大文件',
                    'file_count': volume_counts.get(best_volume, 0),
                    'space_savings': 0,
                    'priority': 'keep'
                })
            
        except Exception as e:
            self.logger.error(f"生成跨卷建议失败: {e}")
        
        return recommendations
    
    def get_volume_duplicate_summary(self, volume_id: int) -> Dict[str, Any]:
        """
        获取指定卷的重复文件摘要
        
        Args:
            volume_id: 卷ID
            
        Returns:
            卷重复文件摘要
        """
        try:
            # 获取该卷涉及的重复文件组
            groups = self.db.execute_query("""
                SELECT DISTINCT 
                    df.group_id,
                    df.file_count,
                    df.total_size,
                    df.cross_volume,
                    df.volume_distribution
                FROM duplicate_files df
                JOIN duplicate_file_items dfi ON df.id = dfi.duplicate_group_id
                JOIN media_files mf ON dfi.media_file_id = mf.id
                WHERE mf.volume_id = ?
            """, (volume_id,))
            
            total_groups = len(groups)
            cross_volume_groups = sum(1 for g in groups if g['cross_volume'])
            local_groups = total_groups - cross_volume_groups
            
            total_size = sum(g['total_size'] for g in groups)
            
            # 计算该卷可节省的空间
            potential_savings = 0
            for group in groups:
                try:
                    volume_dist = json.loads(group['volume_distribution'])
                    volume_sizes = volume_dist.get('volume_sizes', {})
                    
                    # 获取卷名 - 从卷分布中获取
                    volume_name = None
                    for vol_name in volume_sizes.keys():
                        if vol_name != 'unknown':
                            volume_name = vol_name
                            break
                    
                    if not volume_name:
                        volume_name = str(volume_id)
                    
                    # 如果这个卷不是最大文件所在的卷，则可以删除
                    if volume_sizes:
                        max_volume = max(volume_sizes.items(), key=lambda x: x[1])[0]
                        if volume_name != max_volume:
                            potential_savings += volume_sizes.get(volume_name, 0)
                            
                except (json.JSONDecodeError, TypeError, KeyError):
                    continue
            
            return {
                'volume_id': volume_id,
                'total_groups': total_groups,
                'local_groups': local_groups,
                'cross_volume_groups': cross_volume_groups,
                'total_size': total_size,
                'potential_savings': potential_savings,
                'savings_percentage': (potential_savings / total_size * 100) if total_size > 0 else 0.0
            }
            
        except Exception as e:
            self.logger.error(f"获取卷{volume_id}重复文件摘要失败: {e}")
            return {
                'volume_id': volume_id,
                'total_groups': 0,
                'local_groups': 0,
                'cross_volume_groups': 0,
                'total_size': 0,
                'potential_savings': 0,
                'savings_percentage': 0.0
            }
    
    def suggest_files_to_remove(self, group_id: int) -> List[Dict[str, Any]]:
        """
        建议删除的文件
        
        Args:
            group_id: 重复组ID
            
        Returns:
            建议删除的文件列表
        """
        try:
            # 获取组内所有文件
            files_raw = self.db.execute_query("""
                SELECT mf.*, mi.title, mi.year, mi.type
                FROM duplicate_file_items dfi
                JOIN media_files mf ON dfi.media_file_id = mf.id
                LEFT JOIN media_items mi ON mf.media_id = mi.id
                WHERE dfi.duplicate_group_id = ?
                ORDER BY mf.file_size DESC, mf.created_at ASC
            """, (group_id,))
            
            # 转换为字典列表
            files = [dict(file) for file in files_raw]
            
            if len(files) <= 1:
                return []
            
            # 保留策略：保留最大的文件，或者最新的高质量文件
            keep_file = self._select_best_file(files)
            
            # 建议删除其他文件
            to_remove = [f for f in files if f['id'] != keep_file['id']]
            
            # 为每个文件添加删除原因
            for file_info in to_remove:
                file_info['remove_reason'] = self._get_remove_reason(file_info, keep_file)
            
            return to_remove
            
        except Exception as e:
            self.logger.error(f"生成删除建议失败: {e}")
            return []
    
    def _select_best_file(self, files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        从重复文件中选择最佳文件
        
        Args:
            files: 文件列表
            
        Returns:
            最佳文件
        """
        if not files:
            return {}
        
        # 评分系统
        scored_files = []
        
        for file_info in files:
            score = 0
            
            # 文件大小权重（更大通常质量更好）
            max_size = max(f['file_size'] or 0 for f in files)
            if max_size > 0:
                score += (file_info['file_size'] or 0) / max_size * 40
            
            # 分辨率权重
            resolution = file_info.get('resolution', '')
            if '4K' in resolution or '2160' in resolution:
                score += 30
            elif '1080' in resolution:
                score += 20
            elif '720' in resolution:
                score += 10
            
            # 编码格式权重
            codec = file_info.get('video_codec', '').lower()
            if 'h265' in codec or 'hevc' in codec:
                score += 15
            elif 'h264' in codec:
                score += 10
            
            # 文件路径权重（更规范的路径结构）
            path = file_info.get('file_path', '').lower()
            if any(keyword in path for keyword in ['remux', 'bluray', 'web-dl']):
                score += 10
            if 'cam' in path or 'ts' in path or 'hdcam' in path:
                score -= 20
            
            scored_files.append((score, file_info))
        
        # 返回得分最高的文件
        scored_files.sort(key=lambda x: x[0], reverse=True)
        return scored_files[0][1]
    
    def _get_remove_reason(self, file_to_remove: Dict[str, Any], keep_file: Dict[str, Any]) -> str:
        """
        获取删除文件的原因
        
        Args:
            file_to_remove: 要删除的文件
            keep_file: 保留的文件
            
        Returns:
            删除原因
        """
        reasons = []
        
        # 文件大小比较
        if (file_to_remove['file_size'] or 0) < (keep_file['file_size'] or 0):
            size_diff = ((keep_file['file_size'] or 0) - (file_to_remove['file_size'] or 0)) / (1024 * 1024)
            reasons.append(f"文件较小 (小 {size_diff:.1f}MB)")
        
        # 分辨率比较
        remove_res = file_to_remove.get('resolution', '')
        keep_res = keep_file.get('resolution', '')
        if remove_res != keep_res and keep_res:
            reasons.append(f"分辨率较低 ({remove_res} vs {keep_res})")
        
        # 编码格式比较
        remove_codec = file_to_remove.get('video_codec', '')
        keep_codec = keep_file.get('video_codec', '')
        if 'h265' in keep_codec.lower() and 'h264' in remove_codec.lower():
            reasons.append("编码格式较旧 (H.264 vs H.265)")
        
        return '; '.join(reasons) if reasons else "重复文件"
    
    def run_full_detection(self) -> Dict[str, Any]:
        """
        运行完整的重复检测
        
        Returns:
            检测结果统计
        """
        self.logger.info("开始完整重复文件检测...")
        
        results = {
            'hash_groups': 0,
            'similarity_groups': 0,
            'total_saved': 0,
            'analysis': {}
        }
        
        try:
            # 清理旧的重复记录
            self.db.execute_update("DELETE FROM duplicate_file_items")
            self.db.execute_update("DELETE FROM duplicate_files")
            
            # 基于哈希的检测
            hash_groups = self.detect_duplicates_by_hash()
            hash_saved = self.save_duplicate_groups(hash_groups)
            results['hash_groups'] = len(hash_groups)
            
            # 基于相似度的检测
            similarity_groups = self.detect_duplicates_by_similarity()
            similarity_saved = self.save_duplicate_groups(similarity_groups)
            results['similarity_groups'] = len(similarity_groups)
            
            results['total_saved'] = hash_saved + similarity_saved
            
            # 空间分析
            results['analysis'] = self.analyze_duplicate_space()
            
            self.logger.info(f"重复检测完成: {results}")
            return results
            
        except Exception as e:
            self.logger.error(f"完整重复检测失败: {e}")
            return results


if __name__ == "__main__":
    # 测试重复文件检测器
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    detector = DuplicateDetector()
    
    # 运行检测
    results = detector.run_full_detection()
    print(f"检测结果: {results}")
    
    # 获取重复组
    groups = detector.get_duplicate_groups(10)
    for group in groups:
        print(f"重复组 {group['group_id']}: {group['file_count']} 个文件, {group['total_size']/1024/1024:.1f}MB")
        for file_info in group['files']:
            print(f"  - {file_info['file_path']} ({file_info['file_size']/1024/1024:.1f}MB)")