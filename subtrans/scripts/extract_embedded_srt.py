#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立的英文内嵌字幕提取脚本
从 MKV 视频文件中提取英文内嵌字幕，支持质量评估和最优选择
"""

import argparse
import chardet
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union

try:
    import srt
except ImportError:
    print("错误: 需要安装 srt 库")
    print("请运行: pip install srt")
    sys.exit(1)


# ============================================================================
# 配置类
# ============================================================================

@dataclass
class ExtractConfig:
    """字幕提取配置"""
    # 字幕质量评估权重
    subtitle_count_weight: float = 0.40
    language_detection_weight: float = 0.20
    content_quality_weight: float = 0.15
    timing_accuracy_weight: float = 0.10
    text_completeness_weight: float = 0.10
    encoding_quality_weight: float = 0.05
    
    # 英文检测阈值
    english_word_threshold: float = 0.3
    min_subtitle_count: int = 5


# ============================================================================
# 日志配置
# ============================================================================

class SafeStreamHandler(logging.StreamHandler):
    """安全的流处理器，忽略 BrokenPipeError"""
    
    def handleError(self, record) -> None:
        exc_type, exc_value, _ = sys.exc_info()
        if isinstance(exc_value, BrokenPipeError):
            try:
                self.flush()
                self.close()
            except Exception:
                pass
            return
        super().handleError(record)


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    """设置日志记录器"""
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    log_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    console_handler = SafeStreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    logger.propagate = False
    return logger


# ============================================================================
# 质量评估
# ============================================================================

class QualityMetric(Enum):
    """质量评估指标"""
    SUBTITLE_COUNT = "subtitle_count"
    LANGUAGE_DETECTION = "language_detection"
    CONTENT_QUALITY = "content_quality"
    TIMING_ACCURACY = "timing_accuracy"
    TEXT_COMPLETENESS = "text_completeness"
    ENCODING_QUALITY = "encoding_quality"


@dataclass
class QualityScore:
    """质量评分"""
    total_score: float
    metric_scores: Dict[QualityMetric, float]
    confidence: float
    issues: List[str]
    recommendations: List[str]


class SubtitleQualityAssessor:
    """字幕质量评估器"""
    
    def __init__(self, config: ExtractConfig):
        self.config = config
        
        # 评估权重
        self.metric_weights = {
            QualityMetric.SUBTITLE_COUNT: config.subtitle_count_weight,
            QualityMetric.LANGUAGE_DETECTION: config.language_detection_weight,
            QualityMetric.CONTENT_QUALITY: config.content_quality_weight,
            QualityMetric.TIMING_ACCURACY: config.timing_accuracy_weight,
            QualityMetric.TEXT_COMPLETENESS: config.text_completeness_weight,
            QualityMetric.ENCODING_QUALITY: config.encoding_quality_weight,
        }
        
        # 英文常用词汇
        self.english_words = {
            "common": [
                "the", "and", "you", "that", "was", "for", "are", "with", "his", "they",
                "have", "this", "will", "your", "from", "know", "want", "been", "good",
                "time", "what", "when", "where", "who", "how", "can", "could", "would",
                "should", "must", "may", "might", "shall", "will", "do", "does", "did"
            ],
            "pronouns": [
                "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them"
            ],
            "verbs": [
                "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
                "do", "does", "did", "will", "would", "could", "should", "can", "may", "might"
            ],
        }
    
    def assess_subtitle_quality(self, subtitles: List[srt.Subtitle]) -> QualityScore:
        """评估字幕质量"""
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
        
        try:
            # 字幕数量评估
            count_score = self._assess_subtitle_count(subtitles)
            metric_scores[QualityMetric.SUBTITLE_COUNT] = count_score
            if count_score < 30:
                issues.append(f"字幕数量较少 ({len(subtitles)} 条)")
                recommendations.append("检查是否为完整字幕文件")
            
            # 语言检测评估
            lang_score = self._assess_language_detection(subtitles)
            metric_scores[QualityMetric.LANGUAGE_DETECTION] = lang_score
            if lang_score < 50:
                issues.append("英文内容比例较低")
                recommendations.append("确认是否为英文字幕")
            
            # 内容质量评估
            content_score = self._assess_content_quality(subtitles)
            metric_scores[QualityMetric.CONTENT_QUALITY] = content_score
            
            # 时间轴准确性评估
            timing_score = self._assess_timing_accuracy(subtitles)
            metric_scores[QualityMetric.TIMING_ACCURACY] = timing_score
            
            # 文本完整性评估
            completeness_score = self._assess_text_completeness(subtitles)
            metric_scores[QualityMetric.TEXT_COMPLETENESS] = completeness_score
            
            # 编码质量评估
            encoding_score = self._assess_encoding_quality(subtitles)
            metric_scores[QualityMetric.ENCODING_QUALITY] = encoding_score
            
        except Exception as e:
            logger.warning(f"质量评估过程中出现错误: {e}")
            issues.append(f"评估错误: {e}")
        
        # 计算总分
        total_score = sum(
            score * self.metric_weights.get(metric, 0.0)
            for metric, score in metric_scores.items()
        )
        
        # 计算置信度
        confidence = self._calculate_confidence(metric_scores, len(subtitles))
        
        return QualityScore(
            total_score=total_score,
            metric_scores=metric_scores,
            confidence=confidence,
            issues=issues,
            recommendations=recommendations,
        )
    
    def _assess_subtitle_count(self, subtitles: List[srt.Subtitle]) -> float:
        """评估字幕数量"""
        count = len(subtitles)
        if count < self.config.min_subtitle_count:
            return 0.0
        elif count < 50:
            return 30.0
        elif count < 100:
            return 60.0
        elif count < 200:
            return 80.0
        else:
            return 100.0
    
    def _assess_language_detection(self, subtitles: List[srt.Subtitle]) -> float:
        """评估语言检测（英文比例）"""
        if not subtitles:
            return 0.0
        
        english_count = 0
        total_words = 0
        
        all_english_words = set()
        for word_list in self.english_words.values():
            all_english_words.update(word_list)
        
        for subtitle in subtitles:
            text = self._extract_text(subtitle).lower()
            words = re.findall(r'\b[a-zA-Z]+\b', text)
            total_words += len(words)
            
            for word in words:
                if word in all_english_words:
                    english_count += 1
        
        if total_words == 0:
            return 0.0
        
        english_ratio = english_count / total_words
        if english_ratio >= self.config.english_word_threshold:
            return min(100.0, english_ratio * 200)  # 放大评分
        else:
            return english_ratio * 100
    
    def _assess_content_quality(self, subtitles: List[srt.Subtitle]) -> float:
        """评估内容质量"""
        if not subtitles:
            return 0.0
        
        quality_score = 0.0
        total_chars = 0
        
        for subtitle in subtitles:
            text = self._extract_text(subtitle)
            total_chars += len(text)
            
            # 检查是否包含有意义的内容
            if re.search(r'[a-zA-Z]', text):
                quality_score += 1
            
            # 检查是否有过多的特殊字符
            special_chars = len(re.findall(r'[^\w\s\.,!?;:\'"()-]', text))
            if special_chars / max(len(text), 1) < 0.1:
                quality_score += 0.5
        
        return min(100.0, (quality_score / len(subtitles)) * 100)
    
    def _assess_timing_accuracy(self, subtitles: List[srt.Subtitle]) -> float:
        """评估时间轴准确性"""
        if not subtitles:
            return 0.0
        
        valid_timing = 0
        
        for subtitle in subtitles:
            # 检查时间轴是否合理
            duration = (subtitle.end - subtitle.start).total_seconds()
            if 0.5 <= duration <= 10.0:  # 合理的字幕持续时间
                valid_timing += 1
        
        return (valid_timing / len(subtitles)) * 100
    
    def _assess_text_completeness(self, subtitles: List[srt.Subtitle]) -> float:
        """评估文本完整性"""
        if not subtitles:
            return 0.0
        
        complete_count = 0
        
        for subtitle in subtitles:
            text = self._extract_text(subtitle).strip()
            if text and len(text) > 2:  # 非空且有意义的文本
                complete_count += 1
        
        return (complete_count / len(subtitles)) * 100
    
    def _assess_encoding_quality(self, subtitles: List[srt.Subtitle]) -> float:
        """评估编码质量"""
        if not subtitles:
            return 0.0
        
        good_encoding = 0
        
        for subtitle in subtitles:
            text = self._extract_text(subtitle)
            # 检查是否有编码问题（如乱码）
            if not re.search(r'[^\x00-\x7F\u00A0-\uFFFF]', text):
                good_encoding += 1
        
        return (good_encoding / len(subtitles)) * 100
    
    def _extract_text(self, subtitle: srt.Subtitle) -> str:
        """提取字幕文本"""
        return subtitle.content if hasattr(subtitle, 'content') else str(subtitle)
    
    def _calculate_confidence(self, metric_scores: Dict, subtitle_count: int) -> float:
        """计算置信度"""
        if not metric_scores:
            return 0.0
        
        # 基础置信度基于评分的一致性
        scores = list(metric_scores.values())
        avg_score = sum(scores) / len(scores)
        variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)
        consistency = max(0, 100 - variance)
        
        # 字幕数量影响置信度
        count_factor = min(1.0, subtitle_count / 100)
        
        return (consistency * 0.7 + count_factor * 30) / 100
    
    def compare_subtitles(self, subtitle_candidates: List[Tuple[str, List[srt.Subtitle]]]) -> Tuple[Optional[str], Optional[QualityScore]]:
        """比较多个字幕候选并选择最佳"""
        if not subtitle_candidates:
            return None, None
        
        if len(subtitle_candidates) == 1:
            path, subtitles = subtitle_candidates[0]
            score = self.assess_subtitle_quality(subtitles)
            return path, score
        
        best_path = None
        best_score = None
        best_total = -1
        
        logger.info(f"开始比较 {len(subtitle_candidates)} 个字幕候选...")
        
        for path, subtitles in subtitle_candidates:
            try:
                score = self.assess_subtitle_quality(subtitles)
                logger.info(f"字幕评估 {Path(path).name}: 总分={score.total_score:.1f}, 置信度={score.confidence:.2f}")
                
                if score.total_score > best_total:
                    best_total = score.total_score
                    best_path = path
                    best_score = score
                    
            except Exception as e:
                logger.warning(f"评估字幕失败 {path}: {e}")
                continue
        
        if best_path:
            logger.info(f"选择最佳字幕: {Path(best_path).name} (总分: {best_total:.1f})")
        
        return best_path, best_score


# ============================================================================
# 字幕提取功能
# ============================================================================

def is_english_stream(language: str, title: str) -> bool:
    """判断是否为英文字幕流"""
    language = language.lower() if language else ""
    title = title.lower() if title else ""
    
    # 语言代码检查
    english_codes = ["en", "eng", "english"]
    if any(code in language for code in english_codes):
        return True
    
    # 标题检查
    english_keywords = ["english", "en", "eng"]
    if any(keyword in title for keyword in english_keywords):
        return True
    
    return False


def read_subtitle_file_with_encoding_detection(subtitle_path: str) -> Tuple[str, str]:
    """读取字幕文件并自动检测编码"""
    try:
        # 首先尝试 UTF-8
        with open(subtitle_path, 'r', encoding='utf-8') as f:
            content = f.read()
            return content, 'utf-8'
    except UnicodeDecodeError:
        pass
    
    # 自动检测编码
    try:
        with open(subtitle_path, 'rb') as f:
            raw_data = f.read()
            detected = chardet.detect(raw_data)
            encoding = detected.get('encoding') or 'utf-8'  # 确保不为 None
            
        with open(subtitle_path, 'r', encoding=encoding) as f:
            content = f.read()
            return content, encoding
    except Exception as e:
        logger.warning(f"编码检测失败 {subtitle_path}: {e}")
        # 最后尝试 latin-1
        try:
            with open(subtitle_path, 'r', encoding='latin-1') as f:
                content = f.read()
                return content, 'latin-1'
        except Exception:
            raise


def is_english_subtitle_content(subtitle_path: str) -> bool:
    """基于内容判断是否为英文字幕"""
    try:
        content, _ = read_subtitle_file_with_encoding_detection(subtitle_path)
        subtitles = list(srt.parse(content))
        
        if not subtitles:
            return False
        
        # 简单的英文检测
        english_words = {"the", "and", "you", "that", "was", "for", "are", "with", "his", "they"}
        total_words = 0
        english_count = 0
        
        for subtitle in subtitles[:10]:  # 只检查前10条
            text = subtitle.content.lower()
            words = re.findall(r'\b[a-zA-Z]+\b', text)
            total_words += len(words)
            
            for word in words:
                if word in english_words:
                    english_count += 1
        
        if total_words == 0:
            return False
        
        return (english_count / total_words) >= 0.2
        
    except Exception as e:
        logger.debug(f"内容检测失败 {subtitle_path}: {e}")
        return False


def extract_embedded_subtitles(video_path: Path) -> List[Dict[str, str]]:
    """提取内嵌字幕流"""
    try:
        # 使用 ffprobe 获取字幕流信息
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams",
            "-select_streams", "s", str(video_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning(f"ffprobe 执行失败: {result.stderr}")
            return []
        
        data = json.loads(result.stdout)
        subtitle_streams = data.get("streams", [])
        
        if not subtitle_streams:
            logger.info(f"未找到内嵌字幕流: {video_path.name}")
            return []
        
        logger.info(f"发现 {len(subtitle_streams)} 个内嵌字幕流")
        
        # 提取字幕流
        streams = []
        temp_dir = tempfile.mkdtemp(prefix="subtitle_extract_")
        
        for i, stream in enumerate(subtitle_streams):
            stream_index = stream.get("index", i)
            language = stream.get("tags", {}).get("language", "")
            title = stream.get("tags", {}).get("title", "")
            
            # 生成输出文件名
            output_file = Path(temp_dir) / f"stream_{stream_index}.srt"
            
            # 提取字幕流
            extract_cmd = [
                "ffmpeg", "-y", "-v", "quiet", "-i", str(video_path),
                "-map", f"0:s:{i}", "-c:s", "srt", str(output_file)
            ]
            
            try:
                subprocess.run(extract_cmd, check=True, timeout=60)
                if output_file.exists() and output_file.stat().st_size > 0:
                    streams.append({
                        "index": stream_index,
                        "language": language,
                        "title": title,
                        "path": str(output_file)
                    })
                    logger.debug(f"提取成功: stream {stream_index} -> {output_file}")
                else:
                    logger.warning(f"提取失败或文件为空: stream {stream_index}")
            except subprocess.TimeoutExpired:
                logger.warning(f"提取超时: stream {stream_index}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"提取失败: stream {stream_index}, 错误: {e}")
        
        return streams
        
    except FileNotFoundError:
        logger.error("系统未找到 ffprobe/ffmpeg，请确保它们已安装并在 PATH 中。")
        return []
    except Exception as e:
        logger.error(f"提取内嵌字幕失败: {e}")
        return []


def select_best_english_subtitle(streams: List[Dict[str, str]], config: ExtractConfig) -> Optional[str]:
    """选择最佳英文字幕"""
    if not streams:
        return None
    
    # 步骤1: 基于流信息过滤英文字幕
    english_streams = [s for s in streams if is_english_stream(s.get("language", ""), s.get("title", ""))]
    
    # 步骤2: 如果没有找到，基于内容检测
    if not english_streams:
        english_streams = [s for s in streams if is_english_subtitle_content(s.get("path", ""))]
    
    if not english_streams:
        logger.info("未找到英文内嵌字幕流")
        return None
    
    if len(english_streams) == 1:
        logger.info(f"找到1个英文字幕流: lang={english_streams[0].get('language')} title={english_streams[0].get('title')}")
        return english_streams[0]["path"]
    
    # 多个英文字幕流：进行质量评估
    logger.info(f"发现 {len(english_streams)} 个英文字幕流，开始质量评估...")
    assessor = SubtitleQualityAssessor(config)
    subtitle_candidates: List[Tuple[str, List[srt.Subtitle]]] = []
    
    for s in english_streams:
        p = s.get("path")
        if not p or not os.path.exists(p):
            continue
        try:
            content, _ = read_subtitle_file_with_encoding_detection(p)
            subs = list(srt.parse(content))
            if subs:
                subtitle_candidates.append((p, subs))
                logger.debug(f"解析成功: {p} ({len(subs)} 条)")
        except Exception as e:
            logger.warning(f"解析字幕失败 {p}: {e}")
            continue
    
    if not subtitle_candidates:
        logger.warning("所有英文字幕流解析失败")
        return None
    
    best_path, best_score = assessor.compare_subtitles(subtitle_candidates)
    if best_path and best_score:
        logger.info(f"选择最佳字幕: {Path(best_path).name} (评分: {best_score.total_score:.1f})")
        return best_path
    
    return None


def process_single_video(video_path: Path, config: ExtractConfig) -> None:
    """处理单个视频文件"""
    logger.info(f"处理视频: {video_path}")
    
    # 检查是否已存在 .emb.srt 文件
    target_emb = video_path.with_suffix(".emb.srt")
    if target_emb.exists():
        logger.info(f"已存在 .emb.srt 文件，跳过: {target_emb}")
        return
    
    try:
        # 提取内嵌字幕流
        streams = extract_embedded_subtitles(video_path)
        if not streams:
            logger.info(f"未找到内嵌字幕: {video_path.name}")
            return
        
        # 选择最佳英文字幕
        best_path = select_best_english_subtitle(streams, config)
        if not best_path:
            logger.info(f"未找到合适的英文字幕: {video_path.name}")
            return
        
        # 保存为 .emb.srt
        try:
            shutil.move(best_path, str(target_emb))
            logger.info(f"✅ 已保存英文内嵌字幕: {target_emb}")
        except Exception as e:
            logger.error(f"保存 .emb.srt 失败: {e}")
        finally:
            # 清理其他临时文件
            for s in streams:
                p = s.get("path")
                if p and os.path.exists(p) and Path(p) != target_emb:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
                        
    except Exception as e:
        logger.error(f"处理视频失败 {video_path}: {e}")


def scan_directory(root: Path, recursive: bool, config: ExtractConfig) -> None:
    """扫描目录中的 MKV 视频并处理"""
    if recursive:
        for path in root.rglob("*.mkv"):
            process_single_video(path, config)
    else:
        for path in root.glob("*.mkv"):
            process_single_video(path, config)


# ============================================================================
# 命令行接口
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "独立的英文内嵌字幕提取工具\n"
            "扫描目标目录下的 MKV 视频，当不存在 .emb.srt 时，尝试提取内嵌英文字幕；"
            "若存在多个英文内嵌字幕则进行质量评估并选择最优"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "target_dir",
        type=str,
        help="目标目录路径"
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="递归扫描子目录"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="日志级别 (默认: INFO)"
    )
    return parser.parse_args()


def main() -> None:
    """主函数"""
    args = parse_args()
    
    # 设置日志
    global logger
    logger = setup_logger(__name__, args.log_level)
    
    # 验证目标目录
    target = Path(args.target_dir).expanduser().resolve()
    if not target.exists() or not target.is_dir():
        logger.error(f"目标目录不存在或不可访问: {target}")
        sys.exit(2)
    
    # 检查依赖
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error("未找到 ffmpeg/ffprobe，请确保已安装并在 PATH 中")
        sys.exit(1)
    
    # 创建配置
    config = ExtractConfig()
    
    logger.info(f"开始扫描目录: {target} (recursive={args.recursive})")
    logger.info(f"配置: 英文词汇阈值={config.english_word_threshold}, 最小字幕数={config.min_subtitle_count}")
    
    try:
        scan_directory(target, args.recursive, config)
        logger.info("扫描完成")
    except KeyboardInterrupt:
        logger.info("用户中断操作")
        sys.exit(1)
    except Exception as e:
        logger.error(f"扫描过程中发生错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()