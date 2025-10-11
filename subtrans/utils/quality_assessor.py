#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 - 字幕质量评估器
评估字幕文件的质量，包括语言检测、内容完整性等
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union  # 添加Any导入

from core.config import SubTransConfig
from utils.logger import get_logger

logger = get_logger(__name__)


class QualityMetric(Enum):
    """质量评估指标"""

    SUBTITLE_COUNT = "subtitle_count"  # 字幕数量
    LANGUAGE_DETECTION = "language_detection"  # 语言检测
    CONTENT_QUALITY = "content_quality"  # 内容质量
    TIMING_ACCURACY = "timing_accuracy"  # 时间轴准确性
    TEXT_COMPLETENESS = "text_completeness"  # 文本完整性
    ENCODING_QUALITY = "encoding_quality"  # 编码质量


@dataclass
class QualityScore:
    """质量评分"""

    total_score: float
    metric_scores: Dict[QualityMetric, float]
    confidence: float
    issues: List[str]
    recommendations: List[str]


class SubtitleQualityAssessor:
    """智能字幕质量评估器"""

    def __init__(self, config: SubTransConfig):
        self.config = config

        # 评估权重配置 - 提高字幕数量权重，确保优先选择条数更多的字幕
        self.metric_weights = {
            QualityMetric.SUBTITLE_COUNT: 0.40,  # 提高字幕数量权重从25%到40%
            QualityMetric.LANGUAGE_DETECTION: 0.20,
            QualityMetric.CONTENT_QUALITY: 0.15,  # 降低内容质量权重
            QualityMetric.TIMING_ACCURACY: 0.10,  # 降低时间轴权重
            QualityMetric.TEXT_COMPLETENESS: 0.10,  # 降低文本完整性权重
            QualityMetric.ENCODING_QUALITY: 0.05,
        }

        # 英文常用词汇（用于语言检测）
        self.english_words = {
            "common": [
                "the",
                "and",
                "you",
                "that",
                "was",
                "for",
                "are",
                "with",
                "his",
                "they",
                "have",
                "this",
                "will",
                "your",
                "from",
                "they",
                "know",
                "want",
                "been",
                "good",
            ],
            "pronouns": [
                "i",
                "you",
                "he",
                "she",
                "it",
                "we",
                "they",
                "me",
                "him",
                "her",
                "us",
                "them",
            ],
            "verbs": [
                "is",
                "are",
                "was",
                "were",
                "be",
                "been",
                "being",
                "have",
                "has",
                "had",
                "do",
                "does",
                "did",
                "will",
                "would",
                "could",
                "should",
                "can",
                "may",
                "might",
            ],
        }

    def assess_subtitle_quality(
        self,
        subtitles: List[Any],
        source_info: Optional[Dict[str, Any]] = None,
    ) -> QualityScore:
        """评估字幕质量"""
        try:
            if not subtitles:
                return QualityScore(
                    total_score=0.0,
                    metric_scores={},
                    confidence=1.0,
                    issues=["字幕为空"],
                    recommendations=["检查字幕文件是否正确"],
                )
    
            metric_scores = {}
            issues = []
            recommendations = []
    
            # 1. 字幕数量评估 - 添加异常处理
            try:
                count_score = self._assess_subtitle_count(subtitles)
                metric_scores[QualityMetric.SUBTITLE_COUNT] = count_score
                if count_score < 30:
                    issues.append(f"字幕数量较少 ({len(subtitles)} 条)")
                    recommendations.append("检查是否为完整字幕文件")
            except Exception as e:
                logger.warning(f"字幕数量评估失败: {e}")
                metric_scores[QualityMetric.SUBTITLE_COUNT] = 0.0
                issues.append("字幕数量评估失败")
    
            # 2. 语言检测评估 - 添加异常处理
            try:
                lang_score = self._assess_language_detection(subtitles)
                metric_scores[QualityMetric.LANGUAGE_DETECTION] = lang_score
                if lang_score < 50:
                    issues.append("语言检测置信度较低")
                    recommendations.append("确认字幕语言是否正确")
            except Exception as e:
                logger.warning(f"语言检测评估失败: {e}")
                metric_scores[QualityMetric.LANGUAGE_DETECTION] = 0.0
                issues.append("语言检测评估失败")
    
            # 3. 内容质量评估 - 添加异常处理
            try:
                content_score = self._assess_content_quality(subtitles)
                metric_scores[QualityMetric.CONTENT_QUALITY] = content_score
                if content_score < 40:
                    issues.append("内容质量较低")
                    recommendations.append("检查字幕内容是否完整")
            except Exception as e:
                logger.warning(f"内容质量评估失败: {e}")
                metric_scores[QualityMetric.CONTENT_QUALITY] = 0.0
                issues.append("内容质量评估失败")
    
            # 4. 时间轴准确性评估 - 添加异常处理
            try:
                timing_score = self._assess_timing_accuracy(subtitles)
                metric_scores[QualityMetric.TIMING_ACCURACY] = timing_score
                if timing_score < 50:
                    issues.append("时间轴可能存在问题")
                    recommendations.append("检查字幕时间轴是否准确")
            except Exception as e:
                logger.warning(f"时间轴评估失败: {e}")
                metric_scores[QualityMetric.TIMING_ACCURACY] = 0.0
                issues.append("时间轴评估失败")
    
            # 5. 文本完整性评估 - 添加异常处理
            try:
                completeness_score = self._assess_text_completeness(subtitles)
                metric_scores[QualityMetric.TEXT_COMPLETENESS] = completeness_score
                if completeness_score < 60:
                    issues.append("文本完整性较低")
                    recommendations.append("检查是否有缺失的字幕内容")
            except Exception as e:
                logger.warning(f"文本完整性评估失败: {e}")
                metric_scores[QualityMetric.TEXT_COMPLETENESS] = 0.0
                issues.append("文本完整性评估失败")
    
            # 6. 编码质量评估 - 添加异常处理
            try:
                encoding_score = self._assess_encoding_quality(subtitles)
                metric_scores[QualityMetric.ENCODING_QUALITY] = encoding_score
                if encoding_score < 70:
                    issues.append("编码质量问题")
                    recommendations.append("检查字符编码是否正确")
            except Exception as e:
                logger.warning(f"编码质量评估失败: {e}")
                metric_scores[QualityMetric.ENCODING_QUALITY] = 0.0
                issues.append("编码质量评估失败")
    
            # 计算总分 - 所有指标都参与计算，包括评分为0的指标
            if metric_scores:
                total_score = sum(
                    score * self.metric_weights[metric]
                    for metric, score in metric_scores.items()
                    if metric in self.metric_weights
                )
                # 使用所有权重的总和进行标准化
                weight_sum = sum(self.metric_weights.values())
                if weight_sum > 0:
                    total_score = total_score / weight_sum * 100
            else:
                total_score = 0.0
    
            # 计算置信度
            try:
                confidence = self._calculate_confidence(metric_scores, len(subtitles))
            except Exception as e:
                logger.warning(f"置信度计算失败: {e}")
                confidence = 0.5  # 默认置信度
    
            return QualityScore(
                total_score=total_score,
                metric_scores=metric_scores,
                confidence=confidence,
                issues=issues,
                recommendations=recommendations,
            )
        except Exception as e:
            logger.error(f"字幕质量评估完全失败: {e}")
            return QualityScore(
                total_score=0.0,
                metric_scores={},
                confidence=0.0,
                issues=[f"质量评估失败: {str(e)}"],
                recommendations=["请检查字幕文件格式和内容"],
            )

    def _classify_subtitle_content(self, subtitles: List) -> Dict[str, int]:
        """分类字幕内容，区分对话、音乐和场景说明字幕"""
        dialogue_count = 0
        music_count = 0
        scene_description_count = 0
        
        # 音乐字幕的常见标识符
        music_indicators = [
            '♪', '♫', '♬', '♩', '♭', '♯',  # 音乐符号
            '🎵', '🎶', '🎼',  # 音乐emoji
            '(music)', '(singing)', '(song)', '(instrumental)',  # 英文标识
            '(音乐)', '(歌曲)', '(唱歌)', '(演奏)',  # 中文标识
        ]
        
        # 场景说明的常见模式
        scene_patterns = [
            r'^\[.*\]$',  # [场景描述]
            r'^\(.*\)$',  # (场景描述)
            r'^\*.*\*$',  # *场景描述*
        ]
        
        for subtitle in subtitles:
            text = self._extract_text(subtitle).strip()
            if not text:
                continue
                
            # 检查是否为音乐字幕
            is_music = any(indicator in text for indicator in music_indicators)
            
            # 检查是否为场景说明字幕
            is_scene = any(re.match(pattern, text, re.IGNORECASE) for pattern in scene_patterns)
            
            if is_music:
                music_count += 1
            elif is_scene:
                scene_description_count += 1
            else:
                dialogue_count += 1
        
        return {
            'dialogue': dialogue_count,
            'music': music_count,
            'scene_description': scene_description_count,
            'total': len(subtitles)
        }

    def _assess_subtitle_count(self, subtitles: List) -> float:
        """评估字幕数量 - 优先考虑对话字幕数量，而非总字幕数量"""
        # 分类字幕内容
        content_stats = self._classify_subtitle_content(subtitles)
        
        total_count = content_stats['total']
        dialogue_count = content_stats['dialogue']
        music_count = content_stats['music']
        scene_count = content_stats['scene_description']
        
        # 记录分析结果
        logger.info(f"字幕内容分析: 总计{total_count}条, 对话{dialogue_count}条, 音乐{music_count}条, 场景{scene_count}条")
        
        # 如果音乐字幕或场景说明字幕占比过高，优先考虑对话字幕数量
        non_dialogue_ratio = (music_count + scene_count) / total_count if total_count > 0 else 0
        
        if non_dialogue_ratio > 0.3:  # 如果非对话字幕超过30%
            logger.info(f"检测到大量非对话字幕(占比{non_dialogue_ratio:.1%})，优先评估对话字幕数量")
            count_to_evaluate = dialogue_count
            
            # 如果对话字幕太少，给予惩罚
            if dialogue_count < total_count * 0.5:
                logger.warning(f"对话字幕占比过低({dialogue_count}/{total_count}={dialogue_count/total_count:.1%})")
        else:
            count_to_evaluate = total_count
        
        # 使用更精细的评分算法，确保字幕条数的差异能够明显体现在分数上
        if count_to_evaluate < 10:
            return 0  # 数量太少，不可用
        elif count_to_evaluate < 30:
            return 10  # 数量很少
        elif count_to_evaluate < 50:
            return 25  # 数量较少
        elif count_to_evaluate < 100:
            return 40  # 数量偏少
        elif count_to_evaluate < 200:
            return 60  # 数量适中
        elif count_to_evaluate < 500:
            return 75  # 数量较多
        elif count_to_evaluate < 1000:
            return 85  # 数量很多
        elif count_to_evaluate < 2000:
            return 95  # 数量非常多
        else:
            return 100  # 数量极多

    def _assess_language_detection(self, subtitles: List) -> float:
        """评估语言检测准确性"""
        sample_size = min(20, len(subtitles))
        english_count = 0

        for i in range(sample_size):
            subtitle = subtitles[i]
            text = self._extract_text(subtitle).lower()

            if not text:
                continue

            # 检查中文字符（如果有中文，则不是英文字幕）
            if re.search(r"[\u4e00-\u9fff]", text):
                continue

            # 检查英文特征
            english_features = 0

            # 常用词检查
            for word_list in self.english_words.values():
                if any(word in text for word in word_list):
                    english_features += 1
                    break

            # 英文单词模式检查
            if re.search(r"\b[a-z]{3,}\b", text):
                english_features += 1

            # 英文句子结构检查
            if re.search(r"\b(a|an|the)\s+\w+", text):
                english_features += 1

            if english_features >= 2:
                english_count += 1

        if sample_size == 0:
            return 0

        english_ratio = english_count / sample_size
        return english_ratio * 100

    def _assess_content_quality(self, subtitles: List) -> float:
        """评估内容质量"""
        if not subtitles:
            return 0

        total_length = 0
        valid_subtitles = 0

        for subtitle in subtitles:
            text = self._extract_text(subtitle)
            if text and text.strip():
                total_length += len(text)
                valid_subtitles += 1

        if valid_subtitles == 0:
            return 0

        # 平均长度评估
        avg_length = total_length / valid_subtitles

        if avg_length < 5:
            length_score = 20  # 太短
        elif avg_length < 15:
            length_score = 60  # 较短
        elif avg_length < 50:
            length_score = 100  # 合适
        else:
            length_score = 80  # 较长

        # 有效字幕比例
        valid_ratio = valid_subtitles / len(subtitles)
        ratio_score = valid_ratio * 100

        return (length_score + ratio_score) / 2

    def _assess_timing_accuracy(self, subtitles: List) -> float:
        """评估时间轴准确性"""
        if not subtitles:
            return 0

        valid_timing_count = 0
        total_checked = 0

        for subtitle in subtitles:
            if hasattr(subtitle, "start") and hasattr(subtitle, "end"):
                try:
                    if hasattr(subtitle.start, "total_seconds"):
                        start_seconds = subtitle.start.total_seconds()
                        end_seconds = subtitle.end.total_seconds()
                    else:
                        # 处理其他时间格式
                        start_seconds = float(subtitle.start)
                        end_seconds = float(subtitle.end)

                    duration = end_seconds - start_seconds

                    # 检查时长是否合理（0.5秒到10秒）
                    if 0.5 <= duration <= 10:
                        valid_timing_count += 1

                    total_checked += 1

                except (AttributeError, ValueError, TypeError):
                    continue

        if total_checked == 0:
            return 50  # 无法检测时间轴，给中等分数

        return (valid_timing_count / total_checked) * 100

    def _assess_text_completeness(self, subtitles: List) -> float:
        """评估文本完整性"""
        if not subtitles:
            return 0

        # 检查空字幕比例
        empty_count = 0
        incomplete_count = 0

        for subtitle in subtitles:
            text = self._extract_text(subtitle)

            if not text or not text.strip():
                empty_count += 1
            elif len(text.strip()) < 3:
                incomplete_count += 1

        empty_ratio = empty_count / len(subtitles)
        incomplete_ratio = incomplete_count / len(subtitles)

        # 完整性分数
        completeness = 1 - (empty_ratio + incomplete_ratio * 0.5)
        return max(0, completeness * 100)

    def _assess_encoding_quality(self, subtitles: List) -> float:
        """评估编码质量"""
        if not subtitles:
            return 0

        encoding_issues = 0
        total_checked = 0

        for subtitle in subtitles:
            text = self._extract_text(subtitle)
            if text:
                total_checked += 1

                # 检查常见编码问题
                if "�" in text:  # 替换字符
                    encoding_issues += 1
                elif re.search(
                    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]", text
                ):  # 控制字符
                    encoding_issues += 1

        if total_checked == 0:
            return 100

        quality_ratio = 1 - (encoding_issues / total_checked)
        return quality_ratio * 100

    def _extract_text(self, subtitle) -> str:
        """提取字幕文本"""
        if hasattr(subtitle, "content"):
            return subtitle.content
        elif hasattr(subtitle, "text"):
            return subtitle.text
        elif isinstance(subtitle, str):
            return subtitle
        else:
            return str(subtitle)

    def _calculate_confidence(
        self, metric_scores: Dict, subtitle_count: int
    ) -> float:
        """计算评估置信度"""
        # 基础置信度基于字幕数量
        if subtitle_count < 10:
            base_confidence = 0.3
        elif subtitle_count < 50:
            base_confidence = 0.6
        elif subtitle_count < 200:
            base_confidence = 0.8
        else:
            base_confidence = 0.9

        # 根据各项指标的一致性调整置信度
        scores = list(metric_scores.values())
        if scores:
            score_variance = sum(
                (s - sum(scores) / len(scores)) ** 2 for s in scores
            ) / len(scores)
            consistency_factor = max(0.5, 1 - score_variance / 1000)
            base_confidence *= consistency_factor

        return min(1.0, base_confidence)

    def compare_subtitles(
        self, subtitle_candidates: List[Tuple[str, Any]]
    ) -> Tuple[Optional[str], Optional[QualityScore]]:
        """比较多个字幕候选，选择最佳字幕"""
        if not subtitle_candidates:
            logger.warning("没有字幕候选可供比较")
            return None, None
    
        if len(subtitle_candidates) == 1:
            logger.info("只有一个字幕候选，直接返回")
            return subtitle_candidates[0][0], None
    
        logger.info(f"开始比较 {len(subtitle_candidates)} 个字幕候选")
        
        best_subtitles = None
        best_score = None
        successful_evaluations = 0
        
        for i, (subtitle_path, subtitles) in enumerate(subtitle_candidates):
            try:
                subtitle_count = len(subtitles)
                logger.debug(f"评估字幕候选 {i+1}: {subtitle_path} (字幕条数: {subtitle_count})")
                score = self.assess_subtitle_quality(subtitles)
                
                # 详细的调试日志，显示每个候选的条数和评分详情
                if score is not None:
                    count_score = score.metric_scores.get(QualityMetric.SUBTITLE_COUNT, 0)
                    lang_score = score.metric_scores.get(QualityMetric.LANGUAGE_DETECTION, 0)
                    content_score = score.metric_scores.get(QualityMetric.CONTENT_QUALITY, 0)
                    
                    logger.info(
                        f"📊 候选 {i+1}/{len(subtitle_candidates)}: {subtitle_path}\n"
                        f"   字幕条数: {subtitle_count} -> 数量评分: {count_score:.1f}\n"
                        f"   语言检测评分: {lang_score:.1f}, 内容质量评分: {content_score:.1f}\n"
                        f"   总分: {score.total_score:.1f}, 置信度: {score.confidence:.2f}"
                    )
                
                if score and score.total_score > 0:
                    successful_evaluations += 1
                    if best_score is None or score.total_score > best_score.total_score:
                        best_subtitles = subtitle_path
                        best_score = score
                        logger.debug(f"新的最佳候选: {subtitle_path}, 得分: {score.total_score:.1f}")
                    else:
                        # 修正：这里不是“0或无效”，而是“未超过当前最佳”
                        logger.debug(
                            f"未超过当前最佳: {subtitle_path} 得分 {score.total_score:.1f} "
                            f"<= 当前最佳 {best_score.total_score:.1f}"
                        )
                else:
                    # 只有在确实为0或无效时才告警
                    logger.warning(f"字幕候选 {subtitle_path} 评估得分为0或无效")
                        
            except Exception as e:
                logger.warning(f"评估字幕候选 {subtitle_path} 时出错: {e}")
                continue
        
        # 如果所有评估都失败，返回第一个候选
        if successful_evaluations == 0:
            logger.warning("所有字幕候选评估都失败，返回第一个候选")
            return subtitle_candidates[0][0], None
        
        if best_score:
            logger.info(
                f"✅ 选择最佳字幕: {best_subtitles}, 总分={best_score.total_score:.1f}, "
                f"置信度={best_score.confidence:.2f} (成功评估 {successful_evaluations}/{len(subtitle_candidates)} 个候选)"
            )
            
            if best_score.issues:
                logger.warning(f"发现问题: {', '.join(best_score.issues)}")
            
            if best_score.recommendations:
                logger.info(f"建议: {', '.join(best_score.recommendations)}")
        
        return best_subtitles, best_score

    def get_quality_report(self, quality_score: QualityScore) -> str:
        """生成质量评估报告"""
        report = []
        report.append(f"字幕质量评估报告")
        report.append(f"=" * 30)
        report.append(f"总分: {quality_score.total_score:.1f}/100")
        report.append(f"置信度: {quality_score.confidence:.2f}")
        report.append("")

        report.append("详细评分:")
        for metric, score in quality_score.metric_scores.items():
            report.append(f"  {metric.value}: {score:.1f}/100")
        report.append("")

        if quality_score.issues:
            report.append("发现问题:")
            for issue in quality_score.issues:
                report.append(f"  - {issue}")
            report.append("")

        if quality_score.recommendations:
            report.append("改进建议:")
            for rec in quality_score.recommendations:
                report.append(f"  - {rec}")

        return "\n".join(report)
