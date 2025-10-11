"""流程编排器 - 负责协调各个组件完成字幕处理的核心业务逻辑"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chardet
from tqdm import tqdm
from urllib.parse import urlparse

from utils.ftp_handler import FTPFileInfo, FTPHandler
from utils.logger import get_logger
from utils.name_consistency_manager import NameConsistencyManager

from .config import ProcessingMode
from .types import ProcessingResult
from .mixins.transcription_mixin import TranscriptionMixin
from .mixins.ftp_mixin import FTPMixin
from .mixins.utils_mixin import UtilsMixin


class ProcessingOrchestrator(TranscriptionMixin, FTPMixin, UtilsMixin):
    """处理流程编排器 - 负责主要的处理流程编排"""

    def __init__(self, config, stats_manager, detector, logger_instance=None):
        self.config = config
        self.stats = stats_manager
        self.detector = detector
        self.logger = logger_instance or get_logger(__name__)
        
        # 初始化组件
        self.opensubtitles_downloader = None
        self.audio_extractor = None
        self.context_analyzer = None
        self.translation_engine = None
        self.format_converter = None
        self.name_manager = NameConsistencyManager()

    def process_single_file(
        self, file_path: str, output_dir: Optional[str] = None
    ) -> ProcessingResult:
        """处理单个字幕文件"""
        start_time = time.time()
        self.logger.info(f"开始处理输入文件: {file_path}")
        # 追踪即将翻译的字幕来源路径（可能来自视频提取或直接字幕）
        subtitle_source_path = file_path

        try:
            # 更新统计
            self.stats.increment_total_files()

            # 检查文件是否存在
            if not Path(file_path).exists():
                self.logger.error(f"文件不存在: {file_path}")
                self.stats.increment_failed_files()
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message=f"文件不存在: {file_path}",
                )

            # 检查文件类型
            file_path_obj = Path(file_path)
            file_extension = file_path_obj.suffix.lower()

            # 支持的字幕文件格式
            subtitle_extensions = {
                ".srt",
                ".ass",
                ".ssa",
                ".vtt",
                ".sub",
                ".sbv",
            }
            video_extensions = {
                ".mkv",
                ".mp4",
                ".avi",
                ".mov",
                ".wmv",
                ".flv",
                ".webm",
            }

            subtitle_content = None
            detected_encoding = "utf-8"

            if file_extension in video_extensions:
                self.logger.info(f"检测到视频文件: {file_path}")
                # 尝试从视频文件提取字幕或使用Whisper转录
                extracted_subtitle_path = self.detector.extract_subtitles_from_video(
                    file_path
                )
                if not extracted_subtitle_path:
                    self.stats.increment_failed_files()
                    return ProcessingResult(
                        success=False,
                        input_file=file_path,
                        output_files=[],
                        error_message="无法从视频文件提取字幕，请提供字幕文件",
                    )
                # 读取提取的字幕文件
                subtitle_content, detected_encoding = (
                    self._read_subtitle_file_with_encoding_detection(
                        extracted_subtitle_path
                    )
                )
                subtitle_source_path = extracted_subtitle_path
            elif file_extension in subtitle_extensions:
                self.logger.debug(f"检测到字幕文件: {file_path}")
                # 智能编码检测和读取
                subtitle_content, detected_encoding = (
                    self._read_subtitle_file_with_encoding_detection(file_path)
                )
                subtitle_source_path = file_path
            else:
                self.stats.increment_failed_files()
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message=f"不支持的文件格式: {file_extension}",
                )

            if not subtitle_content or not subtitle_content.strip():
                self.stats.increment_failed_files()
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message="文件内容为空",
                )

            self.logger.debug(
                f"文件读取成功，内容长度: {len(subtitle_content)}"
            )

            # 初始化翻译引擎
            self.logger.debug("正在初始化翻译引擎...")
            try:
                from .translation_engine import TranslationEngine

                self.logger.debug("TranslationEngine 导入成功")

                # 在初始化翻译引擎后，添加以下代码
                self.translation_engine = TranslationEngine(self.config)
                self.logger.debug("TranslationEngine 初始化成功")

                # 初始化上下文分析器（如果尚未初始化）
                if (
                    not hasattr(self, "context_analyzer")
                    or not self.context_analyzer
                ):
                    from utils.context_analyzer import ContextAnalyzer

                    self.context_analyzer = ContextAnalyzer(self.config)
                    self.logger.debug("ContextAnalyzer 初始化成功")

                # 分析电影上下文
                try:
                    import srt

                    subtitles = list(srt.parse(subtitle_content))
                    context_result = (
                        self.context_analyzer.analyze_movie_context(
                            file_path, subtitles[:50]
                        )
                    )
                    if context_result and context_result.movie_context:
                        # 将上下文信息传递给翻译引擎
                        self.translation_engine.set_movie_context(
                            {
                                "title": context_result.movie_context.title,
                                "year": context_result.movie_context.year,
                                "genre": context_result.movie_context.genre,
                                "plot": context_result.movie_context.plot,
                                "director": context_result.movie_context.director,
                                "characters": context_result.movie_context.characters,
                                "terminology": context_result.movie_context.terminology,
                            }
                        )
                        self.logger.debug(
                            f"电影上下文分析成功，置信度: {context_result.confidence}"
                        )
                    else:
                        self.logger.warning("电影上下文分析未返回有效结果")
                except Exception as context_error:
                    self.logger.warning(f"电影上下文分析失败: {context_error}")
            except Exception as import_error:
                self.logger.error(f"翻译引擎初始化失败: {import_error}")
                import traceback

                self.logger.error(f"详细错误: {traceback.format_exc()}")
                self.stats.increment_failed_files()
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message=f"翻译引擎初始化失败: {import_error}",
                )

            # 执行翻译
            self.logger.debug("开始执行翻译...")
            try:
                self.logger.warning(
                    f"正在翻译字幕文件: {Path(subtitle_source_path).name} ({subtitle_source_path})"
                )
                # 定义进度回调函数
                def translation_progress(progress, current, total):
                    self.logger.info(
                        f"翻译进度: {current}/{total} ({progress:.1f}%)"
                    )

                # 解析字幕用于人名一致性分析
                try:
                    import srt

                    subtitles = list(srt.parse(subtitle_content))
                    # 分析人名一致性
                    self.name_manager.analyze_subtitle_names(subtitles)
                    self.logger.debug(
                        f"人名一致性分析完成，发现 {len(self.name_manager.name_database)} 个人名映射"
                    )
                except Exception as name_error:
                    self.logger.warning(f"人名一致性分析失败: {name_error}")

                translated_content = (
                    self.translation_engine.translate_subtitle_content(
                        subtitle_content,
                        progress_callback=translation_progress,
                    )
                )

                # 应用人名一致性修复
                try:
                    consistent_content = (
                        self.name_manager.apply_consistency_fixes(
                            translated_content
                        )
                    )
                    if consistent_content != translated_content:
                        self.logger.debug("已应用人名一致性修复")
                        translated_content = consistent_content
                except Exception as consistency_error:
                    self.logger.warning(
                        f"人名一致性修复失败: {consistency_error}"
                    )

                self.logger.debug(
                    f"翻译完成，输出内容长度: {len(translated_content)}"
                )
            except Exception as translate_error:
                self.logger.error(f"翻译过程失败: {translate_error}")
                import traceback

                self.logger.error(f"翻译错误详情: {traceback.format_exc()}")
                self.stats.increment_failed_files()
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message=f"翻译失败: {translate_error}",
                )

            # 生成输出文件路径
            output_file = self._generate_output_path(file_path, output_dir)
            self.logger.debug(f"输出文件路径: {output_file}")

            # 写入翻译结果
            try:
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(translated_content)
                self.logger.debug("文件写入成功")
            except Exception as write_error:
                self.logger.error(f"文件写入失败: {write_error}")
                self.stats.increment_failed_files()
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message=f"文件写入失败: {write_error}",
                )

            # 更新成功统计
            processing_time = time.time() - start_time
            self.stats.increment_successful_files()
            self.stats.add_processing_time(processing_time)
            self.logger.info(f"文件处理成功: {file_path} -> {output_file}")

            return ProcessingResult(
                success=True,
                input_file=file_path,
                output_files=[str(output_file)],
                processing_time=processing_time,
                original_encoding=detected_encoding,
            )

        except Exception as e:
            # 更新失败统计
            self.stats.increment_failed_files()
            self.logger.error(f"处理文件失败 {file_path}: {e}")
            import traceback

            self.logger.error(f"完整错误堆栈: {traceback.format_exc()}")
            return ProcessingResult(
                success=False,
                input_file=file_path,
                output_files=[],
                error_message=str(e),
            )

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
                self.stats.increment_total_files()
                if result.success:
                    self.stats.increment_successful_files()
                else:
                    self.stats.increment_failed_files()

            except Exception as e:
                self.logger.error(f"处理视频文件失败 {video_file}: {str(e)}")
                results.append(
                    ProcessingResult(
                        success=False,
                        input_file=str(video_file),
                        error_message=str(e),
                    )
                )
                self.stats.increment_failed_files()

        return results

    def process_ftp_directory(
        self, ftp_url: str, output_dir: Optional[str] = None
    ) -> List[ProcessingResult]:
        """处理FTP目录 - 重新设计的智能处理逻辑"""
        results = []

        try:
            from utils.file_handler import FileHandler

            # 创建FTP处理器
            ftp_handler = FTPHandler.from_url(ftp_url)
            file_handler = FileHandler()

            # 解析FTP URL获取路径
            parsed = urlparse(ftp_url)
            remote_path = parsed.path or "/"

            self.logger.info(f"开始智能扫描FTP目录: {remote_path}")

            # 递归扫描所有视频文件
            video_files = self._scan_videos_recursive(ftp_handler, remote_path)
            self.logger.info(f"发现 {len(video_files)} 个视频文件")

            # 创建临时目录
            with tempfile.TemporaryDirectory() as temp_dir:
                try:
                    # 启动FTP保活
                    ftp_handler.start_keepalive()

                    # 处理每个视频文件
                    for i, video_file in enumerate(video_files, 1):
                        self.logger.info(
                            f"处理视频 {i}/{len(video_files)}: {video_file.name}"
                        )

                        try:
                            # 在每个视频处理前检查连接
                            ftp_connection = ftp_handler._ensure_connection()

                            result = self._process_single_video_smart(
                                ftp_handler,
                                ftp_connection,
                                video_file,
                                temp_dir,
                                output_dir,
                            )
                            results.append(result)

                        except Exception as e:
                            self.logger.error(
                                f"处理视频文件失败 {video_file.path}: {e}"
                            )
                            results.append(
                                ProcessingResult(
                                    success=False,
                                    input_file=video_file.path,
                                    error_message=str(e),
                                )
                            )

                finally:
                    # 停止保活并清理
                    ftp_handler.stop_keepalive()

        except Exception as e:
            self.logger.error(f"FTP处理失败: {e}")
            return [
                ProcessingResult(
                    success=False,
                    input_file=ftp_url,
                    error_message=f"FTP处理失败: {e}",
                )
            ]

        success_count = len([r for r in results if r.success])
        self.logger.info(
            f"FTP处理完成: {success_count}/{len(results)} 个文件成功"
        )
        return results

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

    # 辅助方法需要从 SubtitleProcessor 迁移
    def _read_subtitle_file_with_encoding_detection(self, file_path: str) -> Tuple[str, str]:
        """使用编码检测读取字幕文件 - 从 UtilsMixin 迁移

        Returns:
            Tuple[str, str]: (文件内容, 编码类型)
        """
        try:
            # 首先尝试检测文件编码
            with open(file_path, "rb") as f:
                raw_data = f.read()

            # 使用 chardet 检测编码
            detected = chardet.detect(raw_data)
            encoding = detected.get("encoding")

            # 确保 encoding 不为 None
            if encoding is None:
                encoding = "utf-8"

            confidence = detected.get("confidence", 0.0)

            self.logger.debug(
                f"检测到文件编码: {encoding} (置信度: {confidence:.2f})"
            )

            # 如果置信度太低，尝试常见编码
            if confidence < 0.7:
                common_encodings = ["utf-8", "gbk", "gb2312", "big5", "latin1"]
                for enc in common_encodings:
                    try:
                        content = raw_data.decode(enc)
                        self.logger.info(f"使用编码 {enc} 成功读取文件")
                        return content, enc
                    except UnicodeDecodeError:
                        continue

            # 使用检测到的编码读取文件
            try:
                content = raw_data.decode(encoding)
                return content, encoding
            except UnicodeDecodeError:
                # 如果检测的编码失败，尝试 UTF-8
                content = raw_data.decode("utf-8", errors="replace")
                self.logger.warning(
                    f"使用 UTF-8 编码读取文件，可能存在字符替换"
                )
                return content, "utf-8"

        except Exception as e:
            self.logger.error(f"读取文件时发生错误: {e}")
            raise

    def _get_video_duration(self, video_path: str) -> Optional[float]:
        """获取视频时长（秒）。用于进度展示等功能。"""
        try:
            cmd = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                duration_str = result.stdout.strip()
                return float(duration_str) if duration_str else None
            return None
        except Exception as e:
            self.logger.warning(f"获取视频时长失败: {e}")
            return None

    
    def _scan_local_videos_recursive(self, directory: Path) -> List[Path]:
        """递归扫描本地视频文件 - 从 LocalMixin 迁移"""
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
        """智能处理单个本地视频文件 - 从 LocalMixin 迁移"""
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

        # 2. 分析视频内嵌字幕
        self.logger.info("分析视频内嵌字幕...")
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
                    # 保存为 .emb.srt 格式
                    emb_subtitle_path = self._generate_final_subtitle_path(
                        video_path_str, "emb"
                    )

                    try:
                        # 复制最佳字幕到标准位置
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

        # 3. 查找外置英文字幕文件
        english_subtitle = self._find_local_english_subtitle(video_path)
        if english_subtitle:
            self.logger.info(f"找到外置英文字幕: {english_subtitle}")
            return self._process_local_subtitle(english_subtitle, output_dir)

        # 4. 音轨转录
        self.logger.info(f"开始音轨转录: {video_path.name}")
        return self._extract_from_audio_with_asr_naming(
            video_path_str, output_dir
        )

    def _find_local_english_subtitle(self, video_path: Path) -> Optional[str]:
        """查找本地英文字幕文件，按优先级排序 - 从 LocalMixin 迁移"""
        base_name = video_path.stem
        parent_dir = video_path.parent

        # 按优先级排序的英文字幕文件名
        # 1. .emb.srt - 优先级最高（内嵌字幕）
        # 2. .srt - 优先级第二（通用字幕文件）
        # 3. .en.srt, .eng.srt, .english.srt - 优先级第三（外置英文字幕）
        # 4. .asr.srt - 优先级最低（音轨转录字幕）
        possible_names = [
            # 优先级1：内嵌字幕
            f"{base_name}.emb.srt",
            # 优先级2：通用字幕文件
            f"{base_name}.srt",
            # 优先级3：外置英文字幕
            f"{base_name}.en.srt",
            f"{base_name}.eng.srt",
            f"{base_name}.english.srt",
            # 优先级4：音轨转录字幕
            f"{base_name}.asr.srt",
        ]

        for name in possible_names:
            subtitle_path = parent_dir / name
            if subtitle_path.exists():
                # 对于 .srt 文件，需要检查是否为英文字幕
                # 对于 .emb.srt 和 .asr.srt，默认认为是英文字幕
                if name.endswith(".emb.srt") or name.endswith(".asr.srt"):
                    self.logger.info(
                        f"找到{name.split('.')[-2]}字幕: {subtitle_path}"
                    )
                    return str(subtitle_path)
                elif self._is_english_subtitle(str(subtitle_path)):
                    self.logger.info(f"找到外置英文字幕: {subtitle_path}")
                    return str(subtitle_path)

        return None

    def _is_english_subtitle(self, subtitle_path: str) -> bool:
        """检查字幕文件是否为英文 - 从 LocalMixin 迁移"""
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
        """处理本地字幕文件 - 从 LocalMixin 迁移"""
        return self.process_single_file(subtitle_path, output_dir)

    def _extract_embedded_subtitles(self, video_path: str) -> List[Dict[str, str]]:
        """提取视频内嵌字幕，返回字幕信息列表 - 从 FTPMixin 迁移（通用方法）"""
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
        """从多个字幕流中选择最佳的英文字幕 - 从 FTPMixin 迁移（通用方法）"""
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