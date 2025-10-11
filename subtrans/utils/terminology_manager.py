#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 - 智能术语管理系统
自动构建和维护术语库，确保翻译一致性
"""

from utils.logger import get_logger
from core.config import SubTransConfig
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime  # 添加datetime导入
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 使用绝对导入

logger = get_logger(__name__)


@dataclass
class TermEntry:
    """术语条目"""

    original: str
    translation: str
    category: str
    confidence: float
    frequency: int
    context: List[str] = field(default_factory=list)
    last_used: str = ""


class TerminologyManager:
    """智能术语管理器"""

    def __init__(self, config: SubTransConfig):
        self.config = config
        # 不再依赖外部配置文件或实例方法获取配置目录，统一使用 config.py 中的临时目录
        base_dir = getattr(config, "TEMP_DIR", None) or tempfile.gettempdir()
        storage_dir = os.path.join(base_dir, "subtrans")
        os.makedirs(storage_dir, exist_ok=True)
        self.terminology_file = Path(storage_dir) / "terminology.json"

        # 术语分类
        self.categories = {
            "names": "人名",
            "places": "地名",
            "organizations": "组织机构",
            "technical": "技术术语",
            "medical": "医学术语",
            "legal": "法律术语",
            "military": "军事术语",
            "general": "通用术语",
        }

        # 术语库
        self.persistent_terms: Dict[str, TermEntry] = {}
        self.session_terms: Dict[str, TermEntry] = {}

        # 统计信息
        self.usage_stats = Counter()

        # 初始化名称一致性映射
        self.name_consistency_map: Dict[str, str] = {}

        # 初始化人名匹配模式
        self.name_patterns = {
            "bracketed_names": r"\[([^\]]+)\]",
            "western_names": r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",
            "company_names": r"\b[A-Z][a-zA-Z]*(?:-[A-Z][a-zA-Z]*)+\b",
        }

        # 加载术语库
        self.load_terminology()

    def load_terminology(self) -> None:
        """加载术语库"""
        try:
            if self.terminology_file.exists():
                with open(self.terminology_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 转换为TermEntry对象
                for term, entry_data in data.get("terms", {}).items():
                    self.persistent_terms[term] = TermEntry(**entry_data)

                # 加载统计信息
                self.usage_stats.update(data.get("usage_stats", {}))

                # 加载名称一致性映射
                self.name_consistency_map = data.get(
                    "name_consistency_map", {}
                )

                logger.info(
                    f"加载了 {len(self.persistent_terms)} 个持久化术语"
                )
            else:
                # 创建默认术语库
                self._create_default_terminology()
                logger.info("创建了默认术语库")

        except Exception as e:
            logger.error(f"加载术语库失败: {e}")
            self._create_default_terminology()

    def save_terminology(self) -> None:
        """保存术语库"""
        try:
            # 确保目录存在
            self.terminology_file.parent.mkdir(parents=True, exist_ok=True)

            # 准备保存数据
            data = {
                "terms": {
                    term: {
                        "original": entry.original,
                        "translation": entry.translation,
                        "category": entry.category,
                        "confidence": entry.confidence,
                        "frequency": entry.frequency,
                        "context": entry.context,
                        "last_used": entry.last_used,
                    }
                    for term, entry in self.persistent_terms.items()
                },
                "usage_stats": dict(self.usage_stats),
                "name_consistency_map": getattr(
                    self, "name_consistency_map", {}
                ),
                "last_updated": self._get_current_time(),
            }

            with open(self.terminology_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"保存了 {len(self.persistent_terms)} 个术语到文件")

        except Exception as e:
            logger.error(f"保存术语库失败: {e}")

    def _create_default_terminology(self) -> None:
        """创建默认术语库"""
        default_terms = {
            # 常见人名
            "John": TermEntry("John", "约翰", "names", 1.0, 0),
            "Mary": TermEntry("Mary", "玛丽", "names", 1.0, 0),
            "David": TermEntry("David", "大卫", "names", 1.0, 0),
            "Sarah": TermEntry("Sarah", "莎拉", "names", 1.0, 0),
            "Michael": TermEntry("Michael", "迈克尔", "names", 1.0, 0),
            "Jennifer": TermEntry("Jennifer", "詹妮弗", "names", 1.0, 0),
            # 常见地名
            "New York": TermEntry("New York", "纽约", "places", 1.0, 0),
            "London": TermEntry("London", "伦敦", "places", 1.0, 0),
            "Paris": TermEntry("Paris", "巴黎", "places", 1.0, 0),
            "Tokyo": TermEntry("Tokyo", "东京", "places", 1.0, 0),
            # 常见组织
            "FBI": TermEntry("FBI", "联邦调查局", "organizations", 1.0, 0),
            "CIA": TermEntry("CIA", "中央情报局", "organizations", 1.0, 0),
            "NASA": TermEntry("NASA", "美国宇航局", "organizations", 1.0, 0),
        }

        self.persistent_terms.update(default_terms)

    def extract_terms_from_text(self, text: str) -> List[str]:
        """从文本中提取潜在术语"""
        terms = []

        # 1. 专有名词（首字母大写）
        proper_nouns = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
        terms.extend(proper_nouns)

        # 2. 缩写词（全大写）
        abbreviations = re.findall(r"\b[A-Z]{2,}\b", text)
        terms.extend(abbreviations)

        # 3. 技术术语（包含特殊字符）
        technical_terms = re.findall(r"\b[A-Za-z]+[-_][A-Za-z]+\b", text)
        terms.extend(technical_terms)

        # 4. 数字+单位组合
        unit_terms = re.findall(r"\b\d+\s*[A-Za-z]+\b", text)
        terms.extend(unit_terms)

        # 去重并过滤
        unique_terms = list(set(terms))
        filtered_terms = [
            term for term in unique_terms if self._is_valid_term(term)
        ]

        return filtered_terms

    def _is_valid_term(self, term: str) -> bool:
        """判断是否为有效术语"""
        # 过滤条件
        if len(term) < 2:
            return False
        if term.lower() in [
            "the",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
        ]:
            return False
        if re.match(r"^\d+$", term):  # 纯数字
            return False
        if re.match(r"^[^A-Za-z]+$", term):  # 不包含字母
            return False

        return True

    def classify_term(self, term: str, context: str = "") -> str:
        """分类术语"""
        term_lower = term.lower()

        # 基于模式的分类
        if re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+$", term):  # 可能是人名
            return "names"
        elif re.match(r"^[A-Z]{2,}$", term):  # 可能是组织缩写
            return "organizations"
        elif "Dr." in context or "medical" in context.lower():
            return "medical"
        elif "court" in context.lower() or "law" in context.lower():
            return "legal"
        elif "military" in context.lower() or "army" in context.lower():
            return "military"
        elif any(
            tech_word in context.lower()
            for tech_word in ["computer", "software", "technology"]
        ):
            return "technical"
        else:
            return "general"

    def add_term(
        self,
        original: str,
        translation: str,
        category: Optional[str] = None,
        context: str = "",
        confidence: float = 0.8,
        persistent: bool = False,
    ) -> None:
        """添加术语"""
        if not category:
            category = self.classify_term(original, context)

        term_entry = TermEntry(
            original=original,
            translation=translation,
            category=category,
            confidence=confidence,
            frequency=1,
            context=[context] if context else [],
            last_used=self._get_current_time(),
        )

        if persistent:
            self.persistent_terms[original] = term_entry
        else:
            self.session_terms[original] = term_entry

        logger.debug(f"添加术语: {original} -> {translation} ({category})")

    def get_term_translation(self, term: str) -> Optional[str]:
        """获取术语翻译"""
        # 首先检查会话术语
        if term in self.session_terms:
            entry = self.session_terms[term]
            entry.frequency += 1
            entry.last_used = self._get_current_time()
            self.usage_stats[term] += 1
            return entry.translation

        # 然后检查持久术语
        if term in self.persistent_terms:
            entry = self.persistent_terms[term]
            entry.frequency += 1
            entry.last_used = self._get_current_time()
            self.usage_stats[term] += 1
            return entry.translation

        return None

    def update_term_translation(
        self,
        original: str,
        new_translation: str,
        confidence: Optional[float] = None,
    ) -> None:
        """更新术语翻译"""
        # 查找术语
        entry = None
        if original in self.session_terms:
            entry = self.session_terms[original]
        elif original in self.persistent_terms:
            entry = self.persistent_terms[original]

        if entry:
            entry.translation = new_translation
            if confidence is not None:
                entry.confidence = confidence
            entry.last_used = self._get_current_time()
            logger.info(f"更新术语翻译: {original} -> {new_translation}")
        else:
            # 如果术语不存在，添加新术语
            self.add_term(
                original, new_translation, confidence=confidence or 0.8
            )

    def apply_terminology_consistency(
        self, original_text: str, translated_text: str
    ) -> str:
        """应用术语一致性"""
        # 提取原文中的术语
        extracted_terms = self.extract_terms_from_text(original_text)

        # 应用已知术语翻译
        result_text = translated_text
        applied_terms = []

        for term in extracted_terms:
            known_translation = self.get_term_translation(term)
            if known_translation and known_translation != term:
                # 智能替换（避免误替换）
                result_text = self._smart_replace_term(
                    result_text, term, known_translation
                )
                applied_terms.append((term, known_translation))

        if applied_terms:
            logger.debug(f"应用术语一致性: {applied_terms}")

        return result_text

    def _smart_replace_term(
        self, text: str, original_term: str, target_translation: str
    ) -> str:
        """智能替换术语"""
        # 简单实现：直接替换
        # 在实际应用中，这里可以实现更复杂的逻辑来避免误替换
        return text.replace(original_term, target_translation)

    def learn_from_translation_pair(
        self, original: str, translated: str
    ) -> None:
        """从翻译对中学习术语"""
        # 提取原文术语
        original_terms = self.extract_terms_from_text(original)

        # 简单的术语对齐（实际应用中可以使用更复杂的对齐算法）
        for term in original_terms:
            if (
                term not in self.session_terms
                and term not in self.persistent_terms
            ):
                # 如果是新术语，暂时保持原文
                self.add_term(term, term, context=original, confidence=0.5)

    def get_terminology_stats(self) -> Dict:
        """获取术语库统计信息"""
        return {
            "persistent_terms": len(self.persistent_terms),
            "session_terms": len(self.session_terms),
            "total_usage": sum(self.usage_stats.values()),
            "categories": {
                cat: len(
                    [
                        t
                        for t in self.persistent_terms.values()
                        if t.category == cat
                    ]
                )
                for cat in self.categories.keys()
            },
            "most_used_terms": self.usage_stats.most_common(10),
        }

    def export_terminology(self, file_path: str) -> bool:
        """导出术语库"""
        try:
            export_data = {
                "persistent_terms": {
                    term: {
                        "translation": entry.translation,
                        "category": entry.category,
                        "confidence": entry.confidence,
                        "frequency": entry.frequency,
                    }
                    for term, entry in self.persistent_terms.items()
                },
                "session_terms": {
                    term: {
                        "translation": entry.translation,
                        "category": entry.category,
                        "confidence": entry.confidence,
                        "frequency": entry.frequency,
                    }
                    for term, entry in self.session_terms.items()
                },
                "export_time": self._get_current_time(),
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)

            logger.info(f"术语库已导出到: {file_path}")
            return True

        except Exception as e:
            logger.error(f"导出术语库失败: {e}")
            return False

    def import_terminology(self, file_path: str) -> bool:
        """导入术语库"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                import_data = json.load(f)

            # 导入持久术语
            imported_count = 0
            for term, data in import_data.get("persistent_terms", {}).items():
                if term not in self.persistent_terms:
                    self.persistent_terms[term] = TermEntry(
                        original=term,
                        translation=data["translation"],
                        category=data.get("category", "general"),
                        confidence=data.get("confidence", 0.8),
                        frequency=data.get("frequency", 0),
                    )
                    imported_count += 1

            logger.info(f"导入了 {imported_count} 个新术语")
            return True

        except Exception as e:
            logger.error(f"导入术语库失败: {e}")
            return False

    def cleanup_session(self) -> None:
        """清理会话术语"""
        # 将高频会话术语提升为持久术语
        promoted_count = 0
        for term, entry in list(self.session_terms.items()):
            if entry.frequency >= 3 and entry.confidence >= 0.7:
                self.persistent_terms[term] = entry
                del self.session_terms[term]
                promoted_count += 1

        if promoted_count > 0:
            logger.info(f"提升了 {promoted_count} 个会话术语为持久术语")
            self.save_terminology()

        # 清空剩余会话术语
        self.session_terms.clear()

    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        from datetime import datetime

        return datetime.now().isoformat()

    def extract_names_from_subtitle(
        self, subtitle_text: str
    ) -> List[Tuple[str, str]]:
        """从字幕中提取人名，返回(原文, 类型)列表"""
        names = []

        # 提取括号内的人名
        bracketed_matches = re.findall(
            self.name_patterns["bracketed_names"], subtitle_text
        )
        for name in bracketed_matches:
            names.append((name, "character"))

        # 提取西方人名
        western_matches = re.findall(
            self.name_patterns["western_names"], subtitle_text
        )
        for name in western_matches:
            if not any(name in existing[0] for existing in names):
                names.append((name, "person"))

        # 提取公司名称
        company_matches = re.findall(
            self.name_patterns["company_names"], subtitle_text
        )
        for name in company_matches:
            if len(name) > 3 and name not in [
                "The",
                "And",
                "But",
            ]:  # 过滤常见词
                names.append((name, "organization"))

        return names

    def build_name_consistency_map(self, subtitles: List) -> None:
        """构建人名一致性映射表"""
        name_frequency = defaultdict(int)
        name_translations = defaultdict(set)

        # 分析所有字幕中的人名
        for subtitle in subtitles:
            text = self._extract_subtitle_text(subtitle)
            names = self.extract_names_from_subtitle(text)

            for name, name_type in names:
                name_frequency[name] += 1

                # 如果是括号内的人名，检查是否有对应的中文翻译
                if name_type == "character":
                    # 查找同一字幕中的中文翻译
                    chinese_pattern = r"\[([^\]]*[\u4e00-\u9fff][^\]]*)\]"
                    chinese_matches = re.findall(chinese_pattern, text)
                    if chinese_matches:
                        for zh_name in chinese_matches:
                            name_translations[name].add(zh_name)

        # 调试输出：显示发现的人名和频率
        if logger.isEnabledFor(10):  # DEBUG level
            logger.debug("=== 人名统一对照分析结果 ===")
            logger.debug(f"发现人名总数: {len(name_frequency)}")

            # 按频率排序显示人名
            sorted_names = sorted(
                name_frequency.items(), key=lambda x: x[1], reverse=True
            )
            for name, freq in sorted_names[:20]:  # 显示前20个最常见的人名
                translations = list(name_translations.get(name, set()))
                if translations:
                    logger.debug(
                        f"  {name} (出现{freq}次) -> 翻译: {', '.join(translations)}"
                    )
                else:
                    logger.debug(f"  {name} (出现{freq}次) -> 无翻译")

        # 建立一致性映射
        for name, translations in name_translations.items():
            if translations:
                # 选择最常见的翻译
                most_common = max(
                    translations,
                    key=lambda x: sum(
                        1
                        for subtitle in subtitles
                        if x in self._extract_subtitle_text(subtitle)
                    ),
                )
                self.name_consistency_map[name] = most_common
            else:
                # 如果没有翻译，保持原文
                self.name_consistency_map[name] = name

        # 调试输出：显示最终的人名对照映射
        if logger.isEnabledFor(10):  # DEBUG level
            logger.debug("=== 最终人名对照映射 ===")
            logger.debug(f"映射条目总数: {len(self.name_consistency_map)}")
            for original, translated in self.name_consistency_map.items():
                if original != translated:
                    logger.debug(f"  {original} -> {translated}")
                else:
                    logger.debug(f"  {original} (保持原文)")
            logger.debug("=== 人名对照映射完成 ===")

    def apply_name_consistency(self, text: str) -> str:
        """应用人名一致性"""
        result = text
        applied_changes = []

        for (
            original_name,
            consistent_name,
        ) in self.name_consistency_map.items():
            # 替换括号内的人名
            pattern = rf"\[{re.escape(original_name)}\]"
            replacement = f"[{consistent_name}]"
            if re.search(pattern, result):
                result = re.sub(pattern, replacement, result)
                if original_name != consistent_name:
                    applied_changes.append(
                        f"[{original_name}] -> [{consistent_name}]"
                    )

            # 替换正文中的人名
            word_pattern = rf"\b{re.escape(original_name)}\b"
            if re.search(word_pattern, result):
                result = re.sub(word_pattern, consistent_name, result)
                if original_name != consistent_name:
                    applied_changes.append(
                        f"{original_name} -> {consistent_name}"
                    )

        # 调试输出：显示应用的人名替换
        if applied_changes and logger.isEnabledFor(10):  # DEBUG level
            logger.debug(f"人名一致性替换: {'; '.join(applied_changes)}")
            logger.debug(f"原文: {text}")
            logger.debug(f"替换后: {result}")

        return result

    def _extract_subtitle_text(self, subtitle) -> str:
        """提取字幕文本"""
        if hasattr(subtitle, "content"):
            return subtitle.content
        elif hasattr(subtitle, "text"):
            return subtitle.text
        elif isinstance(subtitle, dict):
            return subtitle.get("text", subtitle.get("content", ""))
        else:
            return str(subtitle)
