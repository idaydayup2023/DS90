#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 - 人名一致性管理器
专门处理字幕中的人名识别和统一性问题
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class NameEntry:
    """人名条目"""

    original: str
    translation: str
    category: str  # character, person, organization
    confidence: float
    frequency: int
    contexts: List[str]


@dataclass
class NameStats:
    """人名统计信息"""

    frequency: int = 0
    contexts: List[str] = field(default_factory=list)
    translations: Set[str] = field(default_factory=set)


class NameConsistencyManager:
    """人名一致性管理器"""

    def __init__(self):
        self.name_database: Dict[str, NameEntry] = {}
        self.consistency_rules: Dict[str, Any] = {}

    def analyze_subtitle_names(
        self, subtitles: List[Any]
    ) -> Dict[str, NameEntry]:
        """分析字幕中的所有人名"""

        # 创建一个返回 NameStats 实例的工厂函数
        def name_stats_factory() -> NameStats:
            return NameStats()

        name_stats: Dict[str, NameStats] = defaultdict(name_stats_factory)

        for subtitle in subtitles:
            text = self._extract_text(subtitle)

            # 查找所有可能的人名模式
            patterns = {
                "bracketed": r"\[([^\]]+)\]",
                "capitalized": r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
                "company": r"\b[A-Z][a-zA-Z]*(?:-[A-Z][a-zA-Z]*)+\b",
            }

            for pattern_name, pattern in patterns.items():
                matches = re.findall(pattern, text)
                for match in matches:
                    if self._is_likely_name(match):
                        name_stats[match].frequency += 1
                        name_stats[match].contexts.append(text[:100])

        # 构建人名数据库
        for name, stats in name_stats.items():
            if stats.frequency >= 2:  # 至少出现2次才认为是重要人名
                self.name_database[name] = NameEntry(
                    original=name,
                    translation=self._find_best_translation(name, stats),
                    category=self._classify_name(name),
                    confidence=min(stats.frequency / 10, 1.0),
                    frequency=stats.frequency,
                    contexts=stats.contexts[:5],  # 保留前5个上下文
                )

        return self.name_database

    def generate_consistency_report(self) -> str:
        """生成人名一致性报告"""
        report = ["# 人名一致性分析报告\n"]

        # 按类别分组
        by_category: Dict[str, List[NameEntry]] = defaultdict(list)
        for name, entry in self.name_database.items():
            by_category[entry.category].append(entry)

        for category, entries in by_category.items():
            report.append(f"## {category.upper()}\n")
            for entry in sorted(
                entries, key=lambda x: x.frequency, reverse=True
            ):
                report.append(
                    f"- **{entry.original}** → {entry.translation} (出现{entry.frequency}次, 置信度{entry.confidence:.2f})"
                )
            report.append("")

        return "\n".join(report)

    def apply_consistency_fixes(self, text: str) -> str:
        """应用一致性修复"""
        result = text

        for name, entry in self.name_database.items():
            if entry.confidence > 0.7:  # 只应用高置信度的修复
                # 替换括号内的名称
                result = re.sub(
                    rf"\[{re.escape(name)}\]", f"[{entry.translation}]", result
                )
                # 替换正文中的名称
                result = re.sub(
                    rf"\b{re.escape(name)}\b",
                    entry.translation,
                    result,
                )

        return result

    def _is_likely_name(self, text: str) -> bool:
        """判断是否可能是人名"""
        # 过滤明显不是人名的词汇
        exclude_words = {
            "The",
            "And",
            "But",
            "For",
            "With",
            "music",
            "laughter",
            "screams",
        }
        if text in exclude_words:
            return False

        # 长度检查
        if len(text) < 2 or len(text) > 50:
            return False

        # 包含数字或特殊符号的一般不是人名
        if re.search(r'[0-9!@#$%^&*()_+={}|:"<>?`~]', text):
            return False

        return True

    def _find_best_translation(self, name: str, stats: NameStats) -> str:
        """找到最佳翻译"""
        # 简单实现：如果有中文翻译就用中文，否则保持原文
        for context in stats.contexts:
            chinese_match = re.search(
                rf"\[([^\]]*[\u4e00-\u9fff][^\]]*)\].*{re.escape(name)}|{re.escape(name)}.*\[([^\]]*[\u4e00-\u9fff][^\]]*)\]",
                context,
            )
            if chinese_match:
                return chinese_match.group(1) or chinese_match.group(2)

        return name  # 保持原文

    def _classify_name(self, name: str) -> str:
        """分类人名"""
        if "-" in name and name[0].isupper():
            return "organization"
        elif len(name.split()) > 1:
            return "person"
        else:
            return "character"

    def _extract_text(self, subtitle: Any) -> str:
        """提取字幕文本"""
        if hasattr(subtitle, "text"):
            return subtitle.text
        elif isinstance(subtitle, dict):
            return subtitle.get("text", "")
        else:
            return str(subtitle)
