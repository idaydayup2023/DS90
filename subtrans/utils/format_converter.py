#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import pysubs2
except ImportError:
    pysubs2 = None
    print("警告: pysubs2 未安装，ASS/SSA 格式支持将受限")

try:
    import srt
except ImportError:
    srt = None
    print("警告: srt 未安装，SRT 格式支持将受限")

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class SubtitleEntry:
    """字幕条目"""

    start: float  # 开始时间（秒）
    end: float  # 结束时间（秒）
    text: str  # 字幕文本
    style: Optional[str] = None  # 样式名称
    language: Optional[str] = None  # 语言标识


class FormatConverter:
    """统一格式转换器"""

    def __init__(self):
        self.supported_formats = {
            ".srt",
            ".ass",
            ".ssa",
            ".vtt",
            ".sub",
            ".json",
        }

        # 默认样式配置
        self.default_styles = {
            "chinese": {
                "fontname": "Microsoft YaHei",
                "fontsize": 16,
                "bold": True,
                "alignment": 2,  # 底部居中
                "marginv": 10,
            },
            "english": {
                "fontname": "Arial",
                "fontsize": 12,
                "bold": False,
                "alignment": 8,  # 顶部居中
                "marginv": 30,
            },
            "default": {
                "fontname": "Arial",
                "fontsize": 14,
                "bold": False,
                "alignment": 2,  # 底部居中
                "marginv": 10,
            },
        }

    # ==================== 格式检测 ====================

    def detect_format(self, file_path: Union[str, Path]) -> Optional[str]:
        """检测字幕文件格式"""
        file_path = Path(file_path)

        if not file_path.exists():
            logger.error(f"文件不存在: {file_path}")
            return None

        extension = file_path.suffix.lower()

        if extension in self.supported_formats:
            return extension[1:]  # 移除点号

        # 尝试通过内容检测
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(1024)  # 读取前1024字符

            if "[Script Info]" in content or "[V4+ Styles]" in content:
                return "ass"
            elif "WEBVTT" in content:
                return "vtt"
            elif re.search(
                r"\d+\n\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}",
                content,
            ):
                return "srt"
            elif content.strip().startswith("{"):
                return "json"

        except Exception as e:
            logger.warning(f"内容检测失败: {e}")

        return None

    def is_supported_format(self, file_path: Union[str, Path]) -> bool:
        """检查是否为支持的格式"""
        return self.detect_format(file_path) is not None

    # ==================== 通用读取 ====================

    def load_subtitles(
        self, file_path: Union[str, Path]
    ) -> List[SubtitleEntry]:
        """加载字幕文件"""
        file_path = Path(file_path)
        format_type = self.detect_format(file_path)

        if not format_type:
            logger.error(f"不支持的字幕格式: {file_path}")
            return []

        try:
            if format_type == "srt":
                return self._load_srt(file_path)
            elif format_type in ["ass", "ssa"]:
                return self._load_ass(file_path)
            elif format_type == "vtt":
                return self._load_vtt(file_path)
            elif format_type == "json":
                return self._load_json(file_path)
            else:
                logger.error(f"暂不支持读取格式: {format_type}")
                return []

        except Exception as e:
            logger.error(f"加载字幕文件失败 {file_path}: {e}")
            return []

    def _load_srt(self, file_path: Path) -> List[SubtitleEntry]:
        """加载SRT格式字幕"""
        if not srt:
            raise ImportError("需要安装 srt 库")

        subtitles = []

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        for subtitle in srt.parse(content):
            entry = SubtitleEntry(
                start=subtitle.start.total_seconds(),
                end=subtitle.end.total_seconds(),
                text=subtitle.content.strip(),
                language=self._detect_language(subtitle.content),
            )
            subtitles.append(entry)

        logger.info(f"加载SRT字幕: {len(subtitles)} 条")
        return subtitles

    def _load_ass(self, file_path: Path) -> List[SubtitleEntry]:
        """加载ASS/SSA格式字幕"""
        if not pysubs2:
            raise ImportError("需要安装 pysubs2 库")

        subtitles = []

        ass_file = pysubs2.load(str(file_path))

        for event in ass_file:
            # 清理文本
            text = self._clean_ass_text(event.text)

            entry = SubtitleEntry(
                start=event.start / 1000.0,  # 转换为秒
                end=event.end / 1000.0,
                text=text,
                style=event.style,
                language=self._detect_language(text),
            )
            subtitles.append(entry)

        logger.info(f"加载ASS字幕: {len(subtitles)} 条")
        return subtitles

    def _load_vtt(self, file_path: Path) -> List[SubtitleEntry]:
        """加载VTT格式字幕"""
        subtitles = []

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # 简单的VTT解析
        lines = content.split("\n")
        current_subtitle = None

        for line in lines:
            line = line.strip()

            if "-->" in line:
                # 时间行
                time_parts = line.split(" --> ")
                if len(time_parts) == 2:
                    start_time = self._parse_vtt_time(time_parts[0])
                    end_time = self._parse_vtt_time(time_parts[1])

                    current_subtitle = {
                        "start": start_time,
                        "end": end_time,
                        "text": [],
                    }
            elif line and current_subtitle is not None:
                # 字幕文本
                if not line.startswith("WEBVTT") and not line.isdigit():
                    current_subtitle["text"].append(line)
            elif not line and current_subtitle:
                # 空行，结束当前字幕
                text = "\n".join(current_subtitle["text"]).strip()
                if text:
                    entry = SubtitleEntry(
                        start=current_subtitle["start"],
                        end=current_subtitle["end"],
                        text=text,
                        language=self._detect_language(text),
                    )
                    subtitles.append(entry)
                current_subtitle = None

        # 处理最后一条字幕
        if current_subtitle and current_subtitle["text"]:
            text = "\n".join(current_subtitle["text"]).strip()
            if text:
                entry = SubtitleEntry(
                    start=current_subtitle["start"],
                    end=current_subtitle["end"],
                    text=text,
                    language=self._detect_language(text),
                )
                subtitles.append(entry)

        logger.info(f"加载VTT字幕: {len(subtitles)} 条")
        return subtitles

    def _load_json(self, file_path: Path) -> List[SubtitleEntry]:
        """加载JSON格式字幕"""
        subtitles = []

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and all(
                    k in item for k in ["start", "end", "text"]
                ):
                    entry = SubtitleEntry(
                        start=float(item["start"]),
                        end=float(item["end"]),
                        text=str(item["text"]),
                        style=item.get("style"),
                        language=item.get("language")
                        or self._detect_language(item["text"]),
                    )
                    subtitles.append(entry)

        logger.info(f"加载JSON字幕: {len(subtitles)} 条")
        return subtitles

    # ==================== 通用保存 ====================

    def save_subtitles(
        self,
        subtitles: List[SubtitleEntry],
        output_path: Union[str, Path],
        format_type: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """保存字幕文件"""
        output_path = Path(output_path)

        if not format_type:
            format_type = output_path.suffix[1:].lower()

        if format_type not in ["srt", "ass", "ssa", "vtt", "json"]:
            logger.error(f"不支持的输出格式: {format_type}")
            return False

        # 创建输出目录
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if format_type == "srt":
                return self._save_srt(subtitles, output_path, **kwargs)
            elif format_type in ["ass", "ssa"]:
                return self._save_ass(subtitles, output_path, **kwargs)
            elif format_type == "vtt":
                return self._save_vtt(subtitles, output_path, **kwargs)
            elif format_type == "json":
                return self._save_json(subtitles, output_path, **kwargs)
            else:
                logger.error(f"暂不支持保存格式: {format_type}")
                return False

        except Exception as e:
            logger.error(f"保存字幕文件失败 {output_path}: {e}")
            return False

    def _save_srt(
        self, subtitles: List[SubtitleEntry], output_path: Path, **kwargs
    ) -> bool:
        """保存为SRT格式"""
        if not srt:
            raise ImportError("需要安装 srt 库")

        srt_subtitles = []

        for i, subtitle in enumerate(subtitles, 1):
            srt_subtitle = srt.Subtitle(
                index=i,
                start=timedelta(seconds=subtitle.start),
                end=timedelta(seconds=subtitle.end),
                content=subtitle.text,
            )
            srt_subtitles.append(srt_subtitle)

        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(srt.compose(srt_subtitles))

        logger.info(f"保存SRT字幕: {output_path} ({len(subtitles)} 条)")
        return True

    def _save_ass(
        self, subtitles: List[SubtitleEntry], output_path: Path, **kwargs
    ) -> bool:
        """保存为ASS格式"""
        if not pysubs2:
            raise ImportError("需要安装 pysubs2 库")

        # 创建ASS文件
        ass_file = pysubs2.SSAFile()

        # 添加样式
        styles = self._create_ass_styles(**kwargs)
        for style_name, style in styles.items():
            ass_file.styles[style_name] = style

        # 添加字幕事件
        for subtitle in subtitles:
            # 确定样式
            style_name = subtitle.style or self._get_style_for_language(
                subtitle.language
            )

            event = pysubs2.SSAEvent(
                start=int(subtitle.start * 1000),  # 转换为毫秒
                end=int(subtitle.end * 1000),
                text=subtitle.text,
                style=style_name,
            )
            ass_file.append(event)

        ass_file.save(str(output_path), encoding="utf-8")

        logger.info(f"保存ASS字幕: {output_path} ({len(subtitles)} 条)")
        return True

    def _save_vtt(
        self, subtitles: List[SubtitleEntry], output_path: Path, **kwargs
    ) -> bool:
        """保存为VTT格式"""
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("WEBVTT\n\n")

            for i, subtitle in enumerate(subtitles, 1):
                start_time = self._format_vtt_time(subtitle.start)
                end_time = self._format_vtt_time(subtitle.end)

                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{subtitle.text}\n\n")

        logger.info(f"保存VTT字幕: {output_path} ({len(subtitles)} 条)")
        return True

    def _save_json(
        self, subtitles: List[SubtitleEntry], output_path: Path, **kwargs
    ) -> bool:
        """保存为JSON格式"""
        data = []

        for subtitle in subtitles:
            item = {
                "start": subtitle.start,
                "end": subtitle.end,
                "text": subtitle.text,
            }

            if subtitle.style:
                item["style"] = subtitle.style
            if subtitle.language:
                item["language"] = subtitle.language

            data.append(item)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"保存JSON字幕: {output_path} ({len(subtitles)} 条)")
        return True

    # ==================== 格式转换 ====================

    def convert_format(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        target_format: Optional[str] = None,
        **kwargs,
    ) -> bool:
        """转换字幕格式"""
        input_path = Path(input_path)
        output_path = Path(output_path)

        if not input_path.exists():
            logger.error(f"输入文件不存在: {input_path}")
            return False

        # 加载字幕
        subtitles = self.load_subtitles(input_path)
        if not subtitles:
            logger.error("无法加载字幕")
            return False

        # 确定目标格式
        if not target_format:
            target_format = output_path.suffix[1:].lower()

        # 保存字幕
        return self.save_subtitles(
            subtitles, output_path, target_format, **kwargs
        )

    def batch_convert(
        self,
        input_dir: Union[str, Path],
        output_dir: Union[str, Path],
        target_format: str,
        **kwargs,
    ) -> Dict[str, bool]:
        """批量转换字幕格式"""
        input_dir = Path(input_dir)
        output_dir = Path(output_dir)

        if not input_dir.exists():
            logger.error(f"输入目录不存在: {input_dir}")
            return {}

        output_dir.mkdir(parents=True, exist_ok=True)

        results = {}

        for file_path in input_dir.rglob("*"):
            if file_path.is_file() and self.is_supported_format(file_path):
                # 构建输出路径
                relative_path = file_path.relative_to(input_dir)
                output_path = output_dir / relative_path.with_suffix(
                    f".{target_format}"
                )

                # 转换文件
                success = self.convert_format(
                    file_path, output_path, target_format, **kwargs
                )
                results[str(file_path)] = success

                if success:
                    logger.info(f"转换成功: {file_path} -> {output_path}")
                else:
                    logger.error(f"转换失败: {file_path}")

        logger.info(
            f"批量转换完成: {sum(results.values())}/{len(results)} 成功"
        )
        return results

    # ==================== 辅助方法 ====================

    def _detect_language(self, text: str) -> str:
        """检测文本语言"""
        if re.search(r"[\u4e00-\u9fff]", text):
            return "chinese"
        elif re.search(r"[a-zA-Z]", text):
            return "english"
        else:
            return "unknown"

    def _clean_ass_text(self, text: str) -> str:
        """清理ASS文本标签"""
        # 移除ASS标签
        text = re.sub(r"\{[^}]*\}", "", text)
        # 移除HTML标签
        text = re.sub(r"<[^>]*>", "", text)
        # 清理空白字符
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _parse_vtt_time(self, time_str: str) -> float:
        """解析VTT时间格式"""
        # 移除可能的样式信息
        time_str = time_str.split()[0]

        # 解析时间 (HH:MM:SS.mmm 或 MM:SS.mmm)
        parts = time_str.split(":")

        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        elif len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        else:
            return float(parts[0])

    def _format_vtt_time(self, seconds: float) -> str:
        """格式化VTT时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60

        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

    def _create_ass_styles(self, **kwargs) -> Dict[str, Any]:
        """创建ASS样式"""
        if not pysubs2:
            return {}

        styles = {}

        # 获取样式配置
        chinese_config = {
            **self.default_styles["chinese"],
            **kwargs.get("chinese_style", {}),
        }
        english_config = {
            **self.default_styles["english"],
            **kwargs.get("english_style", {}),
        }
        default_config = {
            **self.default_styles["default"],
            **kwargs.get("default_style", {}),
        }

        # 定义颜色
        white = pysubs2.Color(255, 255, 255)
        black = pysubs2.Color(0, 0, 0)

        # 中文样式
        chinese_style = pysubs2.SSAStyle(
            fontname=chinese_config["fontname"],
            fontsize=chinese_config["fontsize"],
            primarycolor=white,
            secondarycolor=black,
            outlinecolor=black,
            backcolor=black,
            bold=chinese_config["bold"],
            italic=False,
            underline=False,
            strikeout=False,
            scalex=100,
            scaley=100,
            spacing=0,
            angle=0,
            borderstyle=1,
            outline=1,
            shadow=0,
            alignment=chinese_config["alignment"],
            marginl=10,
            marginr=10,
            marginv=chinese_config["marginv"],
        )
        styles["Chinese"] = chinese_style

        # 英文样式
        english_style = pysubs2.SSAStyle(
            fontname=english_config["fontname"],
            fontsize=english_config["fontsize"],
            primarycolor=white,
            secondarycolor=black,
            outlinecolor=black,
            backcolor=black,
            bold=english_config["bold"],
            italic=False,
            underline=False,
            strikeout=False,
            scalex=100,
            scaley=100,
            spacing=0,
            angle=0,
            borderstyle=1,
            outline=1,
            shadow=0,
            alignment=english_config["alignment"],
            marginl=10,
            marginr=10,
            marginv=english_config["marginv"],
        )
        styles["English"] = english_style

        # 默认样式
        default_style = pysubs2.SSAStyle(
            fontname=default_config["fontname"],
            fontsize=default_config["fontsize"],
            primarycolor=white,
            secondarycolor=black,
            outlinecolor=black,
            backcolor=black,
            bold=default_config["bold"],
            italic=False,
            underline=False,
            strikeout=False,
            scalex=100,
            scaley=100,
            spacing=0,
            angle=0,
            borderstyle=1,
            outline=1,
            shadow=0,
            alignment=default_config["alignment"],
            marginl=10,
            marginr=10,
            marginv=default_config["marginv"],
        )
        styles["Default"] = default_style

        return styles

    def _get_style_for_language(self, language: Optional[str]) -> str:
        """根据语言获取样式名称"""
        if language == "chinese":
            return "Chinese"
        elif language == "english":
            return "English"
        else:
            return "Default"

    # ==================== 字幕处理 ====================

    def merge_subtitles(
        self,
        subtitle_lists: List[List[SubtitleEntry]],
        strategy: str = "interleave",
    ) -> List[SubtitleEntry]:
        """合并多个字幕列表"""
        if not subtitle_lists:
            return []

        if len(subtitle_lists) == 1:
            return subtitle_lists[0]

        if strategy == "interleave":
            # 交错合并（按时间排序）
            all_subtitles = []
            for subtitle_list in subtitle_lists:
                all_subtitles.extend(subtitle_list)

            # 按开始时间排序
            all_subtitles.sort(key=lambda x: x.start)
            return all_subtitles

        elif strategy == "separate":
            # 分离合并（保持原有顺序）
            merged = []
            for subtitle_list in subtitle_lists:
                merged.extend(subtitle_list)
            return merged

        else:
            logger.error(f"不支持的合并策略: {strategy}")
            return subtitle_lists[0]

    def filter_subtitles(
        self,
        subtitles: List[SubtitleEntry],
        language: Optional[str] = None,
        min_duration: float = 0.0,
        max_duration: float = float("inf"),
        text_filter: Optional[str] = None,
    ) -> List[SubtitleEntry]:
        """过滤字幕"""
        filtered = []

        for subtitle in subtitles:
            # 语言过滤
            if language and subtitle.language != language:
                continue

            # 时长过滤
            duration = subtitle.end - subtitle.start
            if duration < min_duration or duration > max_duration:
                continue

            # 文本过滤
            if (
                text_filter
                and text_filter.lower() not in subtitle.text.lower()
            ):
                continue

            filtered.append(subtitle)

        logger.info(f"字幕过滤: {len(subtitles)} -> {len(filtered)} 条")
        return filtered

    def adjust_timing(
        self,
        subtitles: List[SubtitleEntry],
        offset: float = 0.0,
        speed_factor: float = 1.0,
    ) -> List[SubtitleEntry]:
        """调整字幕时间"""
        adjusted = []

        for subtitle in subtitles:
            # 修正速度调整逻辑：速度越快，时间应该越短
            new_start = (subtitle.start / speed_factor) + offset
            new_end = (subtitle.end / speed_factor) + offset

            # 确保时间不为负
            new_start = max(0, new_start)
            new_end = max(new_start + 0.1, new_end)  # 最小持续时间0.1秒

            adjusted_subtitle = SubtitleEntry(
                start=new_start,
                end=new_end,
                text=subtitle.text,
                style=subtitle.style,
                language=subtitle.language,
            )
            adjusted.append(adjusted_subtitle)

        logger.info(f"时间调整: 偏移 {offset}s, 速度 {speed_factor}x")
        return adjusted

    def split_by_language(
        self, subtitles: List[SubtitleEntry]
    ) -> Dict[str, List[SubtitleEntry]]:
        """按语言分离字幕"""
        language_groups = {}

        for subtitle in subtitles:
            language = subtitle.language or "unknown"

            if language not in language_groups:
                language_groups[language] = []

            language_groups[language].append(subtitle)

        for language, group in language_groups.items():
            logger.info(f"{language} 字幕: {len(group)} 条")

        return language_groups
