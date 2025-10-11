#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from tqdm import tqdm

from core.types import ProcessingResult


@runtime_checkable
class _LocalDeps(Protocol):
    """Protocol: 声明 LocalMixin 运行时依赖的属性与方法"""
    logger: Any
    config: Any
    processing_stats: Dict[str, Any]

    # 主类中实现的方法
    def process_single_file(self, file_path: str, output_dir: Optional[str]) -> ProcessingResult:
        ...

    def _read_subtitle_file_with_encoding_detection(self, file_path: str) -> tuple[str, str]:
        ...

    def _generate_final_subtitle_path(self, video_path: str, tag: str, output_dir: Optional[str] = None) -> str:
        ...

    def _extract_embedded_subtitles(self, video_path: str) -> List[Dict[str, str]]:
        ...

    def _select_best_english_subtitle(self, subtitle_streams: List[Dict[str, str]]) -> Optional[str]:
        ...

    # 转录相关方法（由 TranscriptionMixin 提供）
    def _extract_from_audio_with_asr_naming(
        self, video_path: str, output_dir: Optional[str]
    ) -> ProcessingResult:
        ...


class LocalMixin:
    """本地处理相关的功能模块"""

    # 由主类提供的依赖（用于类型检查）
    logger: Any
    config: Any
    processing_stats: Dict[str, Any]

    def process_single_file(self, file_path: str, output_dir: Optional[str]) -> ProcessingResult:  # type: ignore[override]
        ...

    def _read_subtitle_file_with_encoding_detection(self, file_path: str) -> tuple[str, str]:  # type: ignore[override]
        ...

    def _generate_final_subtitle_path(self, video_path: str, tag: str, output_dir: Optional[str] = None) -> str:  # type: ignore[override]
        ...

    def _extract_embedded_subtitles(self, video_path: str) -> List[Dict[str, str]]:  # type: ignore[override]
        ...

    def _select_best_english_subtitle(self, subtitle_streams: List[Dict[str, str]]) -> Optional[str]:  # type: ignore[override]
        ...

    def _extract_from_audio_with_asr_naming(
        self, video_path: str, output_dir: Optional[str]
    ) -> ProcessingResult:  # type: ignore[override]
        ...

    def process_directory(
        self, directory_path: str, output_dir: Optional[str] = None
    ) -> List[ProcessingResult]:
        """智能批量处理本地目录"""
        results = []
        directory = Path(directory_path)

        if not directory.exists() or not directory.is_dir():
            self.logger.error(f"目录不存在: {directory_path}")
            return results

        self.logger.info(f"开始处理目录: {directory_path}")

        # 递归扫描所有视频文件
        video_files = self._scan_local_videos_recursive(directory)

        if not video_files:
            self.logger.info("未找到视频文件")
            return results

        self.logger.info(f"找到 {len(video_files)} 个视频文件")
        total_videos = len(video_files)

        # 处理每个视频文件
        for i, video_file in enumerate(tqdm(video_files, desc="处理视频文件"), 1):
            self.logger.info(
                f"开始处理视频 {i}/{total_videos}: {video_file.name} ({video_file})"
            )
            try:
                result = self._process_single_video_local_smart(
                    video_file, output_dir
                )
                results.append(result)

                # 更新统计信息
                self.processing_stats["total_files"] += 1
                if result.success:
                    self.processing_stats["successful_files"] += 1
                else:
                    self.processing_stats["failed_files"] += 1

            except Exception as e:
                self.logger.error(f"处理视频文件失败 {video_file}: {str(e)}")
                results.append(
                    ProcessingResult(
                        success=False,
                        input_file=str(video_file),
                        error_message=str(e),
                    )
                )
                self.processing_stats["failed_files"] += 1

        return results

    def _scan_local_videos_recursive(self, directory: Path) -> List[Path]:
        """递归扫描本地视频文件"""
        video_extensions = {
            ".mkv",
            ".mp4",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".m4v",
            ".mpg",
            ".mpeg",
        }
        video_files = []

        for file_path in directory.rglob("*"):
            if (
                file_path.is_file()
                and file_path.suffix.lower() in video_extensions
            ):
                video_files.append(file_path)

        return sorted(video_files)

    def _process_single_video_local_smart(
        self, video_path: Path, output_dir: Optional[str]
    ) -> ProcessingResult:
        """智能处理单个本地视频文件"""
        start_time = time.time()
        video_path_str = str(video_path)

        self.logger.warning(f"处理视频: {video_path.name}")

        # 1. 检查是否已存在翻译字幕
        ai_subtitle_path = video_path.with_suffix(".ai.srt")
        if ai_subtitle_path.exists():
            self.logger.info(f"跳过已翻译的视频: {video_path.name}")
            return ProcessingResult(
                success=True,
                input_file=video_path_str,
                output_files=[str(ai_subtitle_path)],
                processing_time=time.time() - start_time,
            )

        # 2. 检查是否已存在 emb.srt 文件（优先级最高）
        emb_subtitle_path = self._generate_final_subtitle_path(video_path_str, "emb")
        if os.path.exists(emb_subtitle_path):
            self.logger.info(f"找到已存在的 emb.srt 文件: {emb_subtitle_path}")
            return self._process_local_subtitle(emb_subtitle_path, output_dir)

        # 3. 当 emb.srt 不存在时，优先提取内嵌字幕
        self.logger.info("未找到 emb.srt 文件，尝试从视频提取内嵌字幕...")
        embedded_subtitles = self._extract_embedded_subtitles(video_path_str)
        
        if embedded_subtitles:
            # 过滤英文字幕
            english_embedded = [
                s for s in embedded_subtitles if s["is_english"]
            ]

            if english_embedded:
                self.logger.info(
                    f"找到 {len(english_embedded)} 个内嵌英文字幕"
                )

                # 选择最佳英文字幕
                best_subtitle_path = self._select_best_english_subtitle(
                    embedded_subtitles
                )

                if best_subtitle_path:
                    try:
                        # 复制最佳字幕到标准位置
                        import shutil

                        shutil.copy2(best_subtitle_path, emb_subtitle_path)
                        self.logger.info(
                            f"内嵌英文字幕已保存: {emb_subtitle_path}"
                        )

                        # 处理字幕进行翻译
                        result = self._process_local_subtitle(
                            emb_subtitle_path, output_dir
                        )

                        # 清理临时文件
                        for subtitle_info in embedded_subtitles:
                            try:
                                if subtitle_info.get("path") and os.path.exists(subtitle_info["path"]):
                                    os.remove(subtitle_info["path"])
                            except Exception:
                                pass

                        return result

                    except Exception as e:
                        self.logger.error(f"处理内嵌字幕失败: {e}")
            else:
                self.logger.info("内嵌字幕中未找到英文字幕")
        else:
            self.logger.info("未找到内嵌字幕")

        # 4. 如果没有内嵌字幕，则查找外置英文字幕文件
        english_subtitle = self._find_local_english_subtitle(video_path)
        if english_subtitle:
            self.logger.info(f"找到外置英文字幕: {english_subtitle}")
            return self._process_local_subtitle(english_subtitle, output_dir)

        # 5. 音轨转录
        self.logger.info(f"开始音轨转录: {video_path.name}")
        return self._extract_from_audio_with_asr_naming(
            video_path_str, output_dir
        )

    def _find_local_english_subtitle(self, video_path: Path) -> Optional[str]:
        """查找本地外置英文字幕文件，按优先级排序（不包括emb.srt，因为它在主逻辑中单独处理）"""
        base_name = video_path.stem
        parent_dir = video_path.parent

        # 按优先级排序的外置英文字幕文件名
        # 1. .srt - 优先级最高（通用字幕文件）
        # 2. .en.srt, .eng.srt, .english.srt - 优先级第二（外置英文字幕）
        # 3. .asr.srt - 优先级最低（音轨转录字幕）
        possible_names = [
            # 优先级1：通用字幕文件
            f"{base_name}.srt",
            # 优先级2：外置英文字幕
            f"{base_name}.en.srt",
            f"{base_name}.eng.srt",
            f"{base_name}.english.srt",
            # 优先级3：音轨转录字幕
            f"{base_name}.asr.srt",
        ]

        for name in possible_names:
            subtitle_path = parent_dir / name
            if subtitle_path.exists():
                # 对于 .srt 文件，需要检查是否为英文字幕
                # 对于 .asr.srt，默认认为是英文字幕
                if name.endswith(".asr.srt"):
                    self.logger.info(
                        f"找到{name.split('.')[-2]}字幕: {subtitle_path}"
                    )
                    return str(subtitle_path)
                elif self._is_english_subtitle(str(subtitle_path)):
                    self.logger.info(f"找到外置英文字幕: {subtitle_path}")
                    return str(subtitle_path)

        return None

    def _is_english_subtitle(self, subtitle_path: str) -> bool:
        """检查字幕文件是否为英文"""
        try:
            content, _ = self._read_subtitle_file_with_encoding_detection(
                subtitle_path
            )
            # 简单的英文检测：检查是否包含常见英文单词
            english_words = [
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
            ]
            content_lower = content.lower()
            english_count = sum(
                1 for word in english_words if word in content_lower
            )
            return english_count >= 3
        except Exception:
            return False

    def _process_local_subtitle(
        self, subtitle_path: str, output_dir: Optional[str]
    ) -> ProcessingResult:
        """处理本地字幕文件"""
        return self.process_single_file(subtitle_path, output_dir)