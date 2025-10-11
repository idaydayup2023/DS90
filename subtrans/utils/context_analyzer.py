#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 - 智能上下文分析器
分析电影内容，提供上下文感知的翻译优化
"""

from utils.imdb_info_fetcher import IMDBInfoFetcher
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import requests

from core.config import SubTransConfig
from utils.logger import get_logger

logger = get_logger(__name__)

# 在文件顶部导入


# 确保MovieContext类正确定义了所有必需的字段
@dataclass
class MovieContext:
    title: str = ""
    year: str = ""
    genre: List[str] = field(default_factory=list)
    director: str = ""
    plot: str = ""
    characters: Dict[str, str] = field(default_factory=dict)
    terminology: Dict[str, str] = field(default_factory=dict)
    theme: str = "通用"
    style: str = "标准"
    country: str = ""
    language: str = "en"

    def get_translation_context(self, context: str = "") -> str:
        """获取翻译上下文信息"""
        context_parts = []

        if self.title:
            context_parts.append(f"电影：{self.title}")

        if self.genre:
            context_parts.append(f"类型：{', '.join(self.genre)}")

        if self.theme != "通用":
            context_parts.append(f"主题：{self.theme}")

        if self.characters:
            char_list = [f"{en}({zh})" for en, zh in self.characters.items()]
            context_parts.append(f"主要角色：{', '.join(char_list)}")

        if self.terminology:
            term_list = [f"{en}({zh})" for en, zh in self.terminology.items()]
            context_parts.append(f"专业术语：{', '.join(term_list)}")

        if context:
            context_parts.append(f"额外上下文：{context}")

        return "; ".join(context_parts) if context_parts else ""


@dataclass
class ContextAnalysisResult:
    """上下文分析结果"""

    movie_context: MovieContext
    confidence: float
    analysis_time: float
    extracted_terms: List[str]
    character_names: List[str]
    genre_indicators: List[str]


class ContextAnalyzer:
    """智能上下文分析器"""

    def __init__(self, config: SubTransConfig):
        self.config = config
        self.ollama_url = config.OLLAMA_URL
        self.model_name = config.OLLAMA_MODEL
        self.timeout = config.OLLAMA_TIMEOUT
        self.imdb_fetcher = IMDBInfoFetcher(config.OMDB_API_KEY)

        # 类型指示词
        self.genre_indicators = {
            "动作片": [
                "fight",
                "gun",
                "shoot",
                "kill",
                "weapon",
                "battle",
                "war",
                "explosion",
            ],
            "爱情片": [
                "love",
                "heart",
                "kiss",
                "marry",
                "wedding",
                "romance",
                "date",
                "relationship",
            ],
            "科幻片": [
                "space",
                "alien",
                "robot",
                "future",
                "technology",
                "laser",
                "spaceship",
                "planet",
            ],
            "恐怖片": [
                "scary",
                "ghost",
                "monster",
                "blood",
                "scream",
                "nightmare",
                "haunted",
                "evil",
            ],
            "喜剧片": [
                "funny",
                "laugh",
                "joke",
                "humor",
                "comedy",
                "hilarious",
                "amusing",
                "witty",
            ],
            "犯罪片": [
                "police",
                "detective",
                "crime",
                "murder",
                "investigation",
                "suspect",
                "evidence",
            ],
            "剧情片": [
                "family",
                "life",
                "emotion",
                "relationship",
                "society",
                "human",
                "story",
            ],
            "纪录片": [
                "documentary",
                "real",
                "fact",
                "history",
                "nature",
                "science",
                "research",
            ],
        }

    def analyze_movie_context(
        self, video_path: str, subtitles: List = []
    ) -> ContextAnalysisResult:
        """分析电影上下文"""
        import time

        start_time = time.time()

        # 从文件名提取基本信息
        movie_context = self._extract_basic_info(video_path)

        # 如果有字幕，进行深度分析
        if subtitles:
            enhanced_context = self._analyze_subtitle_content(
                subtitles, movie_context
            )
            movie_context = enhanced_context

        analysis_time = time.time() - start_time

        # 提取关键信息
        extracted_terms = list(movie_context.terminology.keys())
        character_names = list(movie_context.characters.keys())
        genre_indicators = (
            self._detect_genre_indicators(subtitles) if subtitles else []
        )

        # 计算置信度
        confidence = self._calculate_analysis_confidence(
            movie_context, subtitles
        )

        result = ContextAnalysisResult(
            movie_context=movie_context,
            confidence=confidence,
            analysis_time=analysis_time,
            extracted_terms=extracted_terms,
            character_names=character_names,
            genre_indicators=genre_indicators,
        )

        logger.info(
            f"上下文分析完成: 主题={movie_context.theme}, "
            f"风格={movie_context.style}, 置信度={confidence:.2f}"
        )

        return result

    # 修改_extract_basic_info方法
    def _extract_basic_info(self, video_path: str) -> MovieContext:
        """从文件名提取基本信息"""
        filename = Path(video_path).stem

        # 提取年份
        year_match = re.search(r"(19|20)\d{2}", filename)
        year = year_match.group(0) if year_match else ""

        # 清理文件名作为标题
        title = re.sub(r"\.(19|20)\d{2}.*", "", filename)
        title = re.sub(r"[._-]", " ", title)
        title = re.sub(r"\s+", " ", title).strip()

        context = MovieContext(title=title, year=year)

        # 尝试获取IMDB信息
        imdb_info = self.imdb_fetcher.get_imdb_info_from_nfo(video_path)
        if not imdb_info and title:
            # 如果没有从NFO获取到，尝试通过标题搜索
            imdb_info = self.imdb_fetcher.get_imdb_info_by_title(title, year)

        # 如果获取到IMDB信息，更新上下文
        if imdb_info:
            context.title = imdb_info.get("Title", context.title)
            context.year = imdb_info.get("Year", context.year)
            context.genre = (
                imdb_info.get("Genre", "").split(", ")
                if imdb_info.get("Genre")
                else []
            )
            context.director = imdb_info.get("Director", "")
            context.plot = imdb_info.get("Plot", "")
            context.country = imdb_info.get("Country", "")
            context.language = (
                imdb_info.get("Language", "").split(", ")[0].lower()
                if imdb_info.get("Language")
                else "en"
            )

            # 根据类型设置主题
            if context.genre:
                genre_map = {
                    "Action": "动作片",
                    "Adventure": "冒险片",
                    "Animation": "动画片",
                    "Biography": "传记片",
                    "Comedy": "喜剧片",
                    "Crime": "犯罪片",
                    "Documentary": "纪录片",
                    "Drama": "剧情片",
                    "Family": "家庭片",
                    "Fantasy": "奇幻片",
                    "Film-Noir": "黑色电影",
                    "History": "历史片",
                    "Horror": "恐怖片",
                    "Music": "音乐片",
                    "Musical": "音乐剧",
                    "Mystery": "悬疑片",
                    "Romance": "爱情片",
                    "Sci-Fi": "科幻片",
                    "Sport": "体育片",
                    "Thriller": "惊悚片",
                    "War": "战争片",
                    "Western": "西部片",
                }

                for genre in context.genre:
                    if genre in genre_map:
                        context.theme = genre_map[genre]
                        break

            logger.info(
                f"从IMDB获取到电影信息: {context.title} ({context.year})"
            )

        return context

    def _analyze_subtitle_content(
        self, subtitles: List, base_context: MovieContext
    ) -> MovieContext:
        """分析字幕内容获取上下文"""
        if not subtitles:
            return base_context

        # 获取字幕样本
        sample_size = min(100, len(subtitles))
        sample_subtitles = subtitles[:sample_size]

        # 提取文本内容
        sample_texts = []
        for sub in sample_subtitles:
            text = self._extract_subtitle_text(sub)
            if text:
                sample_texts.append(text)

        sample_text = " ".join(sample_texts)

        # 使用AI分析上下文
        ai_context = self._ai_analyze_context(sample_text, base_context)

        # 合并分析结果
        enhanced_context = base_context
        if ai_context:
            enhanced_context.characters.update(
                ai_context.get("characters", {})
            )
            enhanced_context.terminology.update(
                ai_context.get("terminology", {})
            )
            enhanced_context.theme = ai_context.get(
                "theme", base_context.theme
            )
            enhanced_context.style = ai_context.get(
                "style", base_context.style
            )
            if ai_context.get("genre"):
                enhanced_context.genre = ai_context["genre"]

        return enhanced_context

    def _ai_analyze_context(
        self, text: str, base_context: MovieContext
    ) -> Optional[Dict]:
        """使用AI分析上下文"""
        try:
            analysis_prompt = f"""
你是一个专业的电影字幕分析师。请分析以下英文字幕内容，提取关键信息用于指导后续翻译。

电影基本信息：
- 标题：{base_context.title}
- 年份：{base_context.year}

请分析并返回以下信息：
1. characters: 主要角色名字映射（英文原名 -> 中文译名）
2. terminology: 专业术语映射（英文 -> 中文）
3. theme: 主题类型（如：动作片、爱情片、科幻片、纪录片等）
4. style: 语言风格（如：正式、口语化、幽默、严肃等）
5. genre: 类型标签列表

重要指令：
1. 只返回JSON格式的结果，不要添加任何解释
2. 确保JSON格式正确，所有字符串都用双引号包围
3. 角色名字要提供合适的中文译名
4. 专业术语要提供准确的中文翻译
5. 如果某项信息不明确，使用合理的默认值

返回格式示例：
{{
  "characters": {{"John": "约翰", "Mary": "玛丽"}},
  "terminology": {{"medical": "医疗", "surgery": "手术"}},
  "theme": "医疗剧",
  "style": "专业",
  "genre": ["剧情", "医疗"]
}}

现在请分析以下内容：
{text[:2000]}  # 限制文本长度
"""

            url = f"{self.ollama_url}/api/chat"
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的电影字幕分析师。",
                    },
                    {"role": "user", "content": analysis_prompt},
                ],
                "stream": False,
            }

            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()

            # 提取和解析AI返回的内容
            raw_content = result["message"]["content"]
            cleaned_content = self._extract_json_from_response(raw_content)

            try:
                context_data = json.loads(cleaned_content)
                logger.debug(
                    f"AI上下文分析成功: {context_data.get('theme', '未知')}"
                )
                return context_data
            except json.JSONDecodeError as e:
                logger.warning(f"AI返回内容JSON解析失败: {e}")
                return self._parse_context_with_fallback(raw_content)

        except Exception as e:
            logger.warning(f"AI上下文分析失败: {e}")
            return None

    def _extract_json_from_response(self, content: str) -> str:
        """从AI响应中提取JSON内容"""
        # 移除markdown代码块标记
        content = re.sub(r"```json\s*", "", content)
        content = re.sub(r"```\s*$", "", content)

        # 尝试找到JSON对象
        json_match = re.search(
            r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL
        )
        if json_match:
            return json_match.group(0).strip()

        return content.strip()

    def _parse_context_with_fallback(self, content: str) -> Dict:
        """使用正则表达式解析上下文信息"""
        result = {
            "characters": {},
            "terminology": {},
            "theme": "通用",
            "style": "标准",
            "genre": [],
        }

        try:
            # 提取主题
            theme_match = re.search(r'"theme"\s*:\s*"([^"]+)"', content)
            if theme_match:
                result["theme"] = theme_match.group(1)

            # 提取风格
            style_match = re.search(r'"style"\s*:\s*"([^"]+)"', content)
            if style_match:
                result["style"] = style_match.group(1)

            # 提取角色（简单实现）
            characters_match = re.search(
                r'"characters"\s*:\s*\{([^}]+)\}', content
            )
            if characters_match:
                chars_content = characters_match.group(1)
                char_pairs = re.findall(
                    r'"([^"]+)"\s*:\s*"([^"]+)"', chars_content
                )
                result["characters"] = dict(char_pairs)

        except Exception as e:
            logger.warning(f"正则解析上下文失败: {e}")

        return result

    def _detect_genre_indicators(self, subtitles: List) -> List[str]:
        """检测类型指示词"""
        if not subtitles:
            return []

        # 提取所有文本
        all_text = " ".join(
            [
                self._extract_subtitle_text(sub).lower()
                for sub in subtitles[:50]  # 检查前50条字幕
            ]
        )

        detected_genres = []
        for genre, indicators in self.genre_indicators.items():
            matches = sum(
                1 for indicator in indicators if indicator in all_text
            )
            if matches >= 2:  # 至少匹配2个指示词
                detected_genres.append(genre)

        return detected_genres

    def _extract_subtitle_text(self, subtitle) -> str:
        """提取字幕文本"""
        if hasattr(subtitle, "content"):
            return subtitle.content
        elif hasattr(subtitle, "text"):
            return subtitle.text
        elif isinstance(subtitle, str):
            return subtitle
        else:
            return str(subtitle)

    def _calculate_analysis_confidence(
        self, context: MovieContext, subtitles: List
    ) -> float:
        """计算分析置信度"""
        confidence = 0.5  # 基础置信度

        # 基于字幕数量
        if subtitles:
            subtitle_count = len(subtitles)
            if subtitle_count > 100:
                confidence += 0.2
            elif subtitle_count > 50:
                confidence += 0.1

        # 基于提取的信息量
        if context.characters:
            confidence += 0.1
        if context.terminology:
            confidence += 0.1
        if context.theme != "通用":
            confidence += 0.1

        return min(1.0, confidence)

    # 修改get_translation_context方法，添加IMDB信息
    def get_translation_context(self, context: MovieContext) -> str:
        """获取翻译上下文字符串"""
        context_parts = []

        if context.title:
            context_parts.append(f"影片：《{context.title}》")

        if context.year:
            context_parts.append(f"({context.year})")

        if context.genre:
            genre_str = "、".join(context.genre[:3])
            context_parts.append(f"类型：{genre_str}")

        if context.director:
            context_parts.append(f"导演：{context.director}")

        if context.plot:
            # 提取关键剧情要素
            plot_summary = (
                context.plot[:150] + "..."
                if len(context.plot) > 150
                else context.plot
            )
            context_parts.append(f"剧情：{plot_summary}")

        # 语言风格指导
        style_guide = self._get_style_guide(context)
        if style_guide:
            context_parts.append(f"语言风格：{style_guide}")

        return " ".join(context_parts)

    def _get_style_guide(self, context: MovieContext) -> str:
        """根据电影类型获取语言风格指导 - 增强版"""
        style_map = {
            "动作片": "简洁有力，多用短句，体现紧张感",
            "爱情片": "温柔细腻，注重情感表达，语言优美浪漫",
            "喜剧片": "轻松幽默，口语化表达，保持喜剧效果和趣味性",
            "科幻片": "准确使用科技术语，保持未来感，专业名词统一",
            "恐怖片": "营造紧张氛围，用词谨慎，传达恐惧感",
            "犯罪片": "专业术语准确，语言严谨，保持悬疑感",
            "剧情片": "情感丰富，层次分明，贴近生活，自然真实",
            "纪录片": "客观准确，用词严谨，信息完整，保持权威性",
            "战争片": "严肃庄重，军事术语准确，体现历史感",
            "音乐片": "富有韵律感，注重情感表达，保持艺术性",
            "传记片": "严谨客观，尊重历史，语言得体",
            "家庭片": "温馨自然，贴近生活，适合全年龄观看",
        }

        if context.genre:
            # 支持多类型组合
            guides = []
            for genre in context.genre[:2]:  # 最多考虑前两个类型
                if genre in style_map:
                    guides.append(style_map[genre])

            if guides:
                return "；".join(guides)

        return "自然流畅，符合影视对话习惯，保持原文风格"

        # 删除以下死代码（第551-565行）：
        # if context.characters:
        #     char_list = ", ".join(
        #         [f"{en}({zh})" for en, zh in list(context.characters.items())[:5]]
        #     )
        #     context_parts.append(f"主要角色：{char_list}")
        #
        # if context.terminology:
        #     term_list = ", ".join(
        #         [f"{en}({zh})" for en, zh in list(context.terminology.items())[:5]]
        #     )
        #     context_parts.append(f"专业术语：{term_list}")
        #
        # return "; ".join(context_parts)
