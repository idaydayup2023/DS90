#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable, TYPE_CHECKING

from core.types import ProcessingResult

if TYPE_CHECKING:
    from utils.ftp_handler import FTPHandler, FTPFileInfo


@runtime_checkable
class _FTPDeps(Protocol):
    """Protocol: 声明 FTPMixin 运行时依赖的属性与方法"""
    logger: Any
    config: Any

    # 主类中实现的方法
    def process_single_file(self, file_path: str, output_dir: Optional[str]) -> ProcessingResult:
        ...

    def _read_subtitle_file_with_encoding_detection(self, file_path: str) -> tuple[str, str]:
        ...

    def _generate_final_subtitle_path(self, video_path: str, tag: str, output_dir: Optional[str] = None) -> str:
        ...

    # 转录相关方法（由 TranscriptionMixin 提供）
    def _extract_from_audio_with_asr_naming_and_upload(
        self, video_path: str, video_dir: str, ftp_handler, output_dir: Optional[str]
    ) -> ProcessingResult:
        ...


class FTPMixin:
    """FTP相关的功能模块"""

    # 由主类提供的依赖（用于类型检查）
    logger: Any
    config: Any

    def process_single_file(self, file_path: str, output_dir: Optional[str]) -> ProcessingResult:  # type: ignore[override]
        ...

    def _read_subtitle_file_with_encoding_detection(self, file_path: str) -> tuple[str, str]:  # type: ignore[override]
        ...

    def _generate_final_subtitle_path(self, video_path: str, tag: str, output_dir: Optional[str] = None) -> str:  # type: ignore[override]
        ...

    def _extract_from_audio_with_asr_naming_and_upload(
        self, video_path: str, video_dir: str, ftp_handler, output_dir: Optional[str]
    ) -> ProcessingResult:  # type: ignore[override]
        ...

    def _scan_videos_recursive(
        self, ftp_handler: "FTPHandler", remote_path: str, max_depth: int = 10
    ) -> List["FTPFileInfo"]:
        """递归扫描所有子目录中的视频文件"""
        video_extensions = [
            ".mkv",
            ".mp4",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".m4v",
            ".ts",
        ]
        video_files = []

        def scan_directory(path: str, current_depth: int = 0):
            if current_depth >= max_depth:
                return

            try:
                files = ftp_handler.list_directory(path)

                for file_info in files:
                    if file_info.is_directory:
                        # 递归扫描子目录
                        scan_directory(file_info.path, current_depth + 1)
                    else:
                        # 检查是否为视频文件
                        file_ext = Path(file_info.name).suffix.lower()
                        if file_ext in video_extensions:
                            video_files.append(file_info)
                            self.logger.debug(
                                f"发现视频文件: {file_info.path}"
                            )
            except Exception as e:
                self.logger.warning(f"扫描目录失败 {path}: {e}")

        scan_directory(remote_path)
        return video_files

    def _process_single_video_smart(
        self,
        ftp_handler: "FTPHandler",
        ftp_connection,
        video_file: "FTPFileInfo",
        temp_dir: str,
        output_dir: Optional[str],
    ) -> ProcessingResult:
        """智能处理单个视频文件"""
        video_dir = os.path.dirname(video_file.path)
        video_name = Path(video_file.name).stem

        # 步骤1: 检查是否已存在翻译字幕（带连接重试）
        translated_subtitle_name = f"{video_name}.ai.srt"
        translated_subtitle_path = f"{video_dir}/{translated_subtitle_name}"

        try:
            # 重新获取有效连接
            ftp_connection = ftp_handler._ensure_connection(ftp_connection)

            if ftp_handler.file_exists(
                translated_subtitle_path, ftp_connection
            ):
                self.logger.info(
                    f"跳过已翻译的视频: {video_file.name} (已存在 {translated_subtitle_name})"
                )
                return ProcessingResult(
                    success=True,
                    input_file=video_file.path,
                    output_files=[translated_subtitle_path],
                    error_message="已存在翻译字幕，跳过处理",
                )
        except Exception as e:
            self.logger.warning(f"检查翻译字幕时出错: {e}，继续处理")

        # 步骤2: 检查是否存在内嵌字幕文件 (.emb.srt)
        self.logger.info(f"🔍 步骤2/5: 检查内嵌字幕文件...")
        video_dir = os.path.dirname(video_file.path)
        video_name = Path(video_file.name).stem
        emb_subtitle_name = f"{video_name}.emb.srt"
        emb_subtitle_path = f"{video_dir}/{emb_subtitle_name}"

        try:
            # 重新获取有效连接
            ftp_connection = ftp_handler._ensure_connection(ftp_connection)
            
            if ftp_handler.file_exists(emb_subtitle_path, ftp_connection):
                self.logger.info(f"✅ 发现内嵌字幕文件: {emb_subtitle_path}")
                return self._process_existing_subtitle(
                    ftp_handler,
                    ftp_connection,
                    emb_subtitle_path,
                    temp_dir,
                    output_dir,
                )
        except Exception as e:
            self.logger.warning(f"检查内嵌字幕文件时出错: {e}，继续处理")

        # 步骤3: 下载视频文件进行内嵌字幕提取
        self.logger.info(
            f"📥 步骤3/5: 下载视频文件进行内嵌字幕提取: {video_file.name}"
        )
        local_video_path = os.path.join(temp_dir, video_file.name)

        if not ftp_handler.download_file(
            video_file.path, local_video_path, ftp_connection=ftp_connection
        ):
            return ProcessingResult(
                success=False,
                input_file=video_file.path,
                error_message="视频文件下载失败",
            )

        # 步骤4: 检查视频内嵌字幕
        self.logger.info(f"🎬 步骤4/5: 分析视频内嵌字幕...")
        embedded_subtitles = self._extract_embedded_subtitles(local_video_path)

        if embedded_subtitles:
            self.logger.info(f"✅ 发现 {len(embedded_subtitles)} 个内嵌字幕流")
            
            # 过滤英文字幕
            english_embedded = [
                s for s in embedded_subtitles if s["is_english"]
            ]

            if english_embedded:
                self.logger.info(
                    f"找到 {len(english_embedded)} 个内嵌英文字幕"
                )

                # 选择最佳英文字幕
                best_subtitle = self._select_best_english_subtitle(
                    embedded_subtitles
                )
                
                if best_subtitle:
                    self.logger.info(f"🎯 选择最佳内嵌英文字幕: {best_subtitle}")

                    # 生成 .emb.srt 文件名
                    emb_subtitle_name = f"{video_name}.emb.srt"
                    emb_subtitle_local_path = os.path.join(
                        temp_dir, emb_subtitle_name
                    )
                    emb_subtitle_remote_path = f"{video_dir}/{emb_subtitle_name}"

                    try:
                        # 复制最佳字幕到标准命名
                        import shutil

                        shutil.copy2(best_subtitle, emb_subtitle_local_path)
                        self.logger.info(
                            f"📝 内嵌字幕已保存为: {emb_subtitle_local_path}"
                        )
                        self.logger.warning(
                            f"开始翻译字幕文件: {Path(emb_subtitle_local_path).name} (来源视频: {video_file.name}, 路径: {emb_subtitle_local_path})"
                        )

                        # 先上传提取的英文字幕到FTP
                        self.logger.info(
                            f"📤 上传提取的英文字幕到FTP: {emb_subtitle_remote_path}"
                        )
                        if ftp_handler.upload_file(
                            emb_subtitle_local_path, emb_subtitle_remote_path
                        ):
                            self.logger.info(
                                f"✅ 英文字幕上传成功: {emb_subtitle_remote_path}"
                            )
                        else:
                            self.logger.warning(
                                f"⚠️ 英文字幕上传失败: {emb_subtitle_remote_path}"
                            )

                        # 然后进行翻译
                        self.logger.info(f"🌐 步骤5/5: 开始翻译字幕...")

                        # 生成正确的翻译文件路径（基于视频文件名，而不是 .emb.srt 文件名）
                        video_path_for_naming = os.path.join(
                            temp_dir, video_file.name
                        )
                        ai_subtitle_local_path = (
                            self._generate_final_subtitle_path(
                                video_path_for_naming, "ai", output_dir
                            )
                        )

                        # 调用翻译引擎，指定输出路径
                        result = self.process_single_file(
                            emb_subtitle_local_path, output_dir
                        )

                        # 如果翻译成功，重命名文件以确保正确的命名格式
                        if result.success and result.output_files:
                            original_ai_file = result.output_files[0]
                            if (
                                os.path.exists(original_ai_file)
                                and original_ai_file != ai_subtitle_local_path
                            ):
                                # 重命名为正确的格式
                                import shutil

                                shutil.move(
                                    original_ai_file, ai_subtitle_local_path
                                )
                                result.output_files = [ai_subtitle_local_path]
                                self.logger.info(
                                    f"📝 翻译文件已重命名为: {ai_subtitle_local_path}"
                                )

                        # 上传翻译结果到FTP
                        if result.success:
                            self.logger.info(f"📤 上传翻译结果到FTP...")
                            self._upload_result_to_ftp(
                                ftp_handler, result, video_dir
                            )

                        # 清理临时文件
                        for subtitle_info in embedded_subtitles:
                            try:
                                if os.path.exists(subtitle_info["path"]):
                                    os.remove(subtitle_info["path"])
                            except Exception:
                                pass

                        return result

                    except Exception as e:
                        self.logger.error(f"❌ 处理内嵌字幕失败: {e}")
                else:
                    self.logger.info(f"⚠️ 内嵌字幕中未找到英文字幕")
        else:
            self.logger.info(f"ℹ️ 未发现内嵌字幕")

        # 步骤5: 查找外置英文字幕文件
        self.logger.info(f"🔍 步骤5/6: 查找外置英文字幕文件...")
        english_subtitle = self._find_english_subtitle(
            ftp_handler, ftp_connection, video_file
        )

        if english_subtitle:
            self.logger.info(f"✅ 发现外置英文字幕: {english_subtitle}")
            return self._process_existing_subtitle(
                ftp_handler,
                ftp_connection,
                english_subtitle,
                temp_dir,
                output_dir,
            )

        # 步骤6: 从音轨提取字幕
        self.logger.info(f"🎵 步骤6/6: 开始音轨转录识别字幕...")

        # 使用带ASR命名的音轨提取方法
        result = self._extract_from_audio_with_asr_naming_and_upload(
            local_video_path, video_dir, ftp_handler, output_dir
        )

        return result

    def _find_english_subtitle(
        self,
        ftp_handler: "FTPHandler",
        ftp_connection,
        video_file: "FTPFileInfo",
    ) -> Optional[str]:
        """查找视频对应的英文字幕文件"""
        video_dir = os.path.dirname(video_file.path)
        video_name = Path(video_file.name).stem

        # 可能的外置英文字幕文件名模式（按优先级排序）
        # 注意：.emb.srt 已在主逻辑中单独处理，此处不再查找
        subtitle_patterns = [
            # 优先级1：通用字幕文件
            f"{video_name}.srt",
            # 优先级2：外置英文字幕
            f"{video_name}.en.srt",
            f"{video_name}.eng.srt",
            f"{video_name}.english.srt",
            f"{video_name}.en.vtt",
            f"{video_name}.eng.vtt",
            # 优先级3：音轨转录字幕
            f"{video_name}.asr.srt",
        ]

        try:
            # 获取视频所在目录的文件列表
            files = ftp_handler.list_directory(video_dir)
            file_names = {f.name for f in files if not f.is_directory}

            # 按优先级查找字幕文件
            for pattern in subtitle_patterns:
                if pattern in file_names:
                    subtitle_path = f"{video_dir}/{pattern}"
                    self.logger.info(f"找到英文字幕: {subtitle_path}")
                    return subtitle_path

            self.logger.info(f"未找到英文字幕文件: {video_name}")
            return None
        except Exception as e:
            self.logger.error(f"查找英文字幕时出错: {e}")
            return None

    def _is_english_subtitle_stream(self, language: str, title: str) -> bool:
        """检测字幕流是否为英文"""
        # 检查语言代码
        english_lang_codes = ["en", "eng", "english"]
        if language.lower() in english_lang_codes:
            return True

        # 检查标题中的英文关键词
        title_lower = title.lower()
        english_keywords = ["english", "eng", "en", "subtitle", "sub"]
        if any(keyword in title_lower for keyword in english_keywords):
            return True

        return False

    def _process_existing_subtitle(
        self,
        ftp_handler: "FTPHandler",
        ftp_connection,
        subtitle_path: str,
        temp_dir: str,
        output_dir: Optional[str],
    ) -> ProcessingResult:
        """处理现有的字幕文件"""
        try:
            # 下载字幕文件
            subtitle_name = os.path.basename(subtitle_path)
            local_subtitle_path = os.path.join(temp_dir, subtitle_name)

            if not ftp_handler.download_file(
                subtitle_path,
                local_subtitle_path,
                ftp_connection=ftp_connection,
            ):
                return ProcessingResult(
                    success=False,
                    input_file=subtitle_path,
                    error_message="字幕文件下载失败",
                )

            # 处理字幕文件
            # 在翻译前明确打印来源字幕名称与本地路径
            self.logger.warning(
                f"开始翻译字幕文件: {os.path.basename(local_subtitle_path)} (来自FTP路径: {subtitle_path}, 本地: {local_subtitle_path})"
            )
            result = self.process_single_file(local_subtitle_path, output_dir)

            # 上传结果到FTP
            if result.success:
                subtitle_dir = os.path.dirname(subtitle_path)
                self._upload_result_to_ftp(ftp_handler, result, subtitle_dir)

            return result

        except Exception as e:
            return ProcessingResult(
                success=False,
                input_file=subtitle_path,
                error_message=f"处理字幕文件失败: {e}",
            )

    def _extract_embedded_subtitles(
        self, video_path: str
    ) -> List[Dict[str, str]]:
        """提取视频内嵌字幕，返回字幕信息列表"""
        try:
            # 使用ffprobe检查字幕流
            cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "s",
                video_path,
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return []

            data = json.loads(result.stdout)

            subtitle_streams = []
            video_name = Path(video_path).stem

            for i, stream in enumerate(data.get("streams", [])):
                if stream.get("codec_type") == "subtitle":
                    # 获取字幕流信息
                    language = stream.get("tags", {}).get(
                        "language", "unknown"
                    )
                    title = stream.get("tags", {}).get("title", "")

                    # 提取字幕流到临时文件
                    temp_subtitle = tempfile.NamedTemporaryFile(
                        suffix=".srt",
                        prefix=f"{video_name}_stream_{i}_",
                        delete=False,
                    )
                    output_path = temp_subtitle.name
                    temp_subtitle.close()

                    extract_cmd = [
                        "ffmpeg",
                        "-i",
                        video_path,
                        "-map",
                        f"0:s:{i}",
                        "-c:s",
                        "srt",
                        output_path,
                        "-y",
                    ]

                    extract_result = subprocess.run(
                        extract_cmd, capture_output=True
                    )
                    if extract_result.returncode == 0 and os.path.exists(
                        output_path
                    ):
                        subtitle_streams.append(
                            {
                                "path": output_path,
                                "stream_index": i,
                                "language": language,
                                "title": title,
                                "is_english": self._is_english_subtitle_stream(
                                    language, title
                                ),
                            }
                        )
                    else:
                        # 清理失败的临时文件
                        if os.path.exists(output_path):
                            os.remove(output_path)

            return subtitle_streams

        except Exception as e:
            self.logger.error(f"提取内嵌字幕失败: {e}")
            return []

    def _select_best_english_subtitle(
        self, subtitle_streams: List[Dict[str, str]]
    ) -> Optional[str]:
        """从多个字幕流中选择最佳的英文字幕"""
        if not subtitle_streams:
            return None

        # 过滤出英文字幕
        english_subtitles = []
        for stream in subtitle_streams:
            language = stream.get("language", "").lower()
            title = stream.get("title", "").lower()
            if self._is_english_subtitle_stream(language, title):
                english_subtitles.append(stream)

        if not english_subtitles:
            self.logger.warning("未找到英文字幕流")
            return None

        if len(english_subtitles) == 1:
            self.logger.info(
                f"找到1个英文字幕流: {english_subtitles[0]['language']}"
            )
            return english_subtitles[0]["path"]

        # 多个英文字幕时，使用质量评估器选择最佳
        self.logger.info(
            f"🔍 发现 {len(english_subtitles)} 个英文字幕流，开始质量评估..."
        )

        # 尝试使用质量评估器
        try:
            from utils.quality_assessor import SubtitleQualityAssessor
            assessor = SubtitleQualityAssessor(self.config)
            
            # 构建字幕候选列表
            subtitle_candidates = []
            for stream in english_subtitles:
                subtitle_path = stream.get('path')
                if subtitle_path and os.path.exists(subtitle_path):
                    try:
                        # 读取并解析字幕
                        content, _ = self._read_subtitle_file_with_encoding_detection(subtitle_path)
                        
                        import srt
                        subtitles = list(srt.parse(content))
                        if subtitles:
                            subtitle_candidates.append((subtitle_path, subtitles))
                            self.logger.debug(f"成功解析字幕: {subtitle_path} ({len(subtitles)} 条)")
                    except Exception as e:
                        self.logger.warning(f"解析字幕失败 {subtitle_path}: {e}")
                        continue
            
            if subtitle_candidates:
                best_subtitle, score = assessor.compare_subtitles(subtitle_candidates)
                if best_subtitle:
                    self.logger.info(f"✅ 质量评估完成，选择最佳字幕: {best_subtitle}")
                    return best_subtitle
                else:
                    self.logger.warning("质量评估未能选出最佳字幕")
            
        except Exception as e:
            self.logger.warning(f"⚠️ 质量评估模块异常: {e}，使用降级策略")
        
        # 降级策略：选择第一个有效的字幕文件
        for stream in english_subtitles:
            subtitle_path = stream.get('path')
            if subtitle_path and os.path.exists(subtitle_path):
                self.logger.info(f"🔄 使用降级策略，选择第一个字幕: {subtitle_path}")
                return subtitle_path
        
        self.logger.warning("未找到有效的字幕文件")
        return None

    def _upload_result_to_ftp(
        self,
        ftp_handler: "FTPHandler",
        result: ProcessingResult,
        remote_dir: str,
    ) -> None:
        """上传处理结果到FTP服务器"""
        if not result.success or not result.output_files:
            return

        for output_file in result.output_files:
            if os.path.exists(output_file):
                output_filename = os.path.basename(output_file)
                remote_output_path = f"{remote_dir.rstrip('/')}/{output_filename}"

                self.logger.info(
                    f"上传处理结果: {output_file} -> {remote_output_path}"
                )
                if ftp_handler.upload_file(output_file, remote_output_path):
                    self.logger.info(f"上传成功: {remote_output_path}")
                    # 更新结果中的输出文件路径为远程路径
                    result.output_files = [
                        remote_output_path if f == output_file else f
                        for f in result.output_files
                    ]
                else:
                    self.logger.warning(f"上传失败: {remote_output_path}")