#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字幕检测和下载模块

负责检测视频文件中的字幕、从外部源下载字幕等功能。
"""
import os
import subprocess
import tempfile
from typing import Optional, Protocol, runtime_checkable, Any


@runtime_checkable
class _SubtitleDetectorDeps(Protocol):
    """Protocol: 声明 SubtitleDetector 运行时依赖的属性与方法"""
    logger: Any


class SubtitleDetector:
    """字幕检测器"""

    def __init__(self, logger: Any):
        """初始化字幕检测器"""
        self.logger = logger

    def extract_subtitles_from_video(self, video_path: str) -> Optional[str]:
        """从视频文件中提取字幕"""
        try:
            # 检查是否有同名的字幕文件
            video_dir = os.path.dirname(video_path)
            video_name = os.path.splitext(os.path.basename(video_path))[0]

            # 常见字幕文件扩展名
            subtitle_extensions = [".srt", ".ass", ".ssa", ".vtt", ".sub"]

            for ext in subtitle_extensions:
                subtitle_path = os.path.join(video_dir, video_name + ext)
                if os.path.exists(subtitle_path):
                    self.logger.info(f"找到同名字幕文件: {subtitle_path}")
                    return subtitle_path

            self.logger.info("未找到外置字幕文件，检查内嵌字幕...")

            # 尝试使用 ffmpeg 提取内嵌字幕
            try:
                temp_subtitle = tempfile.NamedTemporaryFile(
                    suffix=".srt", delete=False
                )
                temp_subtitle.close()

                cmd = [
                    "ffmpeg",
                    "-i",
                    video_path,
                    "-map",
                    "0:s:0",  # 提取第一个字幕流
                    "-c:s",
                    "srt",  # 转换为 SRT 格式
                    temp_subtitle.name,
                    "-y",  # 覆盖输出文件
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0 and os.path.exists(
                    temp_subtitle.name
                ):
                    self.logger.info(
                        f"成功从视频中提取内嵌字幕: {temp_subtitle.name}"
                    )
                    return temp_subtitle.name
                else:
                    if os.path.exists(temp_subtitle.name):
                        os.unlink(temp_subtitle.name)
                    self.logger.info("未找到内嵌字幕，尝试音频转录...")

            except FileNotFoundError:
                self.logger.warning("未找到 ffmpeg，跳过内嵌字幕提取")
            except Exception as e:
                self.logger.warning(f"提取内嵌字幕时发生错误: {e}")

        except Exception as e:
            self.logger.error(f"检测字幕时发生错误: {e}")

        return None

    def download_from_opensubtitles(
        self, video_path: str, target_lang: str
    ) -> Optional[str]:
        """从OpenSubtitles下载字幕"""
        # TODO: 实现OpenSubtitles下载逻辑
        self.logger.warning("OpenSubtitles下载功能尚未实现")
        return None

    def get_video_duration(self, video_path: str) -> Optional[float]:
        """获取视频总时长（秒）"""
        try:
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(video_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
            pass
        return None