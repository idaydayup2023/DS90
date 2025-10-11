#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计信息管理模块

负责处理所有的统计信息收集和报告功能。
"""
from typing import Any, Dict, Optional


class StatsManager:
    """统计信息管理器"""

    def __init__(self, existing_stats: Optional[Dict[str, Any]] = None):
        """初始化统计管理器

        :param existing_stats: 可选的外部统计字典。如果提供，则直接引用该字典，保持与调用方同步。
        """
        if existing_stats is not None:
            self.processing_stats: Dict[str, Any] = existing_stats
        else:
            self.processing_stats = {
                "total_files": 0,
                "successful_files": 0,
                "failed_files": 0,
                "start_time": None,
                "end_time": None,
            }

    def get_processing_stats(self) -> Dict[str, Any]:
        """获取处理统计信息"""
        return self.processing_stats.copy()

    def increment_total_files(self) -> None:
        """增加总文件数"""
        self.processing_stats["total_files"] += 1

    def increment_successful_files(self) -> None:
        """增加成功处理的文件数"""
        self.processing_stats["successful_files"] += 1

    def increment_failed_files(self) -> None:
        """增加失败处理的文件数"""
        self.processing_stats["failed_files"] += 1

    def set_start_time(self, start_time: Any) -> None:
        """设置开始时间"""
        self.processing_stats["start_time"] = start_time

    def set_end_time(self, end_time: Any) -> None:
        """设置结束时间"""
        self.processing_stats["end_time"] = end_time

    def reset_stats(self) -> None:
        """重置统计信息"""
        self.processing_stats.clear()
        self.processing_stats.update(
            {
                "total_files": 0,
                "successful_files": 0,
                "failed_files": 0,
                "start_time": None,
                "end_time": None,
            }
        )

    def update_stats(self, success: bool) -> None:
        """更新统计信息（便捷方法）"""
        self.increment_total_files()
        if success:
            self.increment_successful_files()
        else:
            self.increment_failed_files()