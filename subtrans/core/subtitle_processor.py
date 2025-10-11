#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import subprocess
import tempfile
import time

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm  # 添加tqdm导入

# 添加FTP相关导入
from utils.ftp_handler import FTPFileInfo, FTPHandler
from utils.logger import get_logger
from utils.name_consistency_manager import NameConsistencyManager

# 导入ProcessingMode
from .config import ProcessingMode
from .types import ProcessingResult
from .mixins.transcription_mixin import TranscriptionMixin
from .mixins.local_mixin import LocalMixin
from .mixins.ftp_mixin import FTPMixin
from .mixins.utils_mixin import UtilsMixin
from .stats_manager import StatsManager
from .subtitle_detector import SubtitleDetector

# QualityAssessor导入
try:
    from utils.quality_assessor import (
        QualityAssessor,  # type: ignore[reportAttributeAccessIssue]
    )
except ImportError:
    QualityAssessor = None  # type: ignore[misc]

logger = get_logger(__name__)


# ProcessingResult 已迁移至 core/types.py 模块


class SubtitleProcessor(UtilsMixin, TranscriptionMixin, LocalMixin, FTPMixin):
    """字幕处理器"""

    def __init__(self, config):
        self.config = config
        self.logger = logger

        # 初始化组件
        self.opensubtitles_downloader = None
        self.audio_extractor = None
        self.context_analyzer = None
        self.translation_engine = None
        self.format_converter = None
        self.name_manager = NameConsistencyManager()

        # 统计信息（由 StatsManager 管理，引用同一dict以保持兼容）
        self.processing_stats = {
            "total_files": 0,
            "successful_files": 0,
            "failed_files": 0,
            "total_subtitles": 0,
            "processing_time": 0.0,
        }
        self.stats = StatsManager(existing_stats=self.processing_stats)

        # 媒体与字幕检测
        self.detector = SubtitleDetector(logger=self.logger)

    def initialize_components(
        self, mode: ProcessingMode, ftp_url: Optional[str] = None
    ) -> bool:
        """初始化组件"""
        try:
            # FTP模式特殊初始化
            if mode == ProcessingMode.FTP and ftp_url:
                # 修复：使用绝对导入
                from utils.ftp_handler import FTPHandler
                from utils.network_utils import validate_ftp_url

                # 验证FTP URL
                if not validate_ftp_url(ftp_url):
                    self.logger.error(f"无效的FTP URL: {ftp_url}")
                    return False

                # 测试FTP连接
                try:
                    ftp_handler = FTPHandler.from_url(ftp_url)
                    # 修复：使用上下文管理器进行连接测试
                    with ftp_handler.connect() as ftp:
                        self.logger.info("FTP连接测试成功")
                        # 连接会在with块结束时自动关闭
                except Exception as e:
                    self.logger.error(f"FTP连接测试异常: {e}")
                    return False

            # 根据配置初始化各个组件
            if not self.config.DISABLE_OPENSUBTITLES:
                # 初始化OpenSubtitles下载器
                pass

            if (
                self.config.FORCE_AUDIO_EXTRACTION
                or mode == ProcessingMode.LOCAL
            ):
                # 初始化音频提取器
                pass

            # FTP模式特殊初始化
            if mode == ProcessingMode.FTP and ftp_url:
                # 验证FTP URL
                from utils.network_utils import validate_ftp_url

                if not validate_ftp_url(ftp_url):
                    self.logger.error(f"无效的FTP URL: {ftp_url}")
                    return False

                # 测试FTP连接
                try:
                    from utils.ftp_handler import FTPHandler

                    ftp_handler = FTPHandler.from_url(ftp_url)
                    with ftp_handler.connect() as ftp:
                        self.logger.info("FTP连接测试成功")
                except Exception as e:
                    self.logger.error(f"FTP连接测试失败: {e}")
                    return False

            # 初始化其他组件
            from utils.context_analyzer import ContextAnalyzer

            self.context_analyzer = ContextAnalyzer(self.config)
            # 翻译引擎在处理单个文件时已初始化，这里不需要重复
            # self.format_converter = FormatConverter()

            return True
        except Exception as e:
            self.logger.error(f"组件初始化失败: {e}")
            return False

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
            self.processing_stats["total_files"] += 1

            # 检查文件是否存在
            if not Path(file_path).exists():
                self.logger.error(f"文件不存在: {file_path}")
                self.processing_stats["failed_files"] += 1
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
                extracted_subtitle_path = self._extract_subtitles_from_video(
                    file_path
                )
                if not extracted_subtitle_path:
                    self.processing_stats["failed_files"] += 1
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
                self.processing_stats["failed_files"] += 1
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message=f"不支持的文件格式: {file_extension}",
                )

            if not subtitle_content or not subtitle_content.strip():
                self.processing_stats["failed_files"] += 1
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
                self.processing_stats["failed_files"] += 1
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
                self.processing_stats["failed_files"] += 1
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
                self.processing_stats["failed_files"] += 1
                return ProcessingResult(
                    success=False,
                    input_file=file_path,
                    output_files=[],
                    error_message=f"文件写入失败: {write_error}",
                )

            # 更新成功统计
            processing_time = time.time() - start_time
            self.processing_stats["successful_files"] += 1
            self.processing_stats["processing_time"] += processing_time
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
            self.processing_stats["failed_files"] += 1
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

    def process_ftp_directory(
        self, ftp_url: str, output_dir: Optional[str] = None
    ) -> List[ProcessingResult]:
        """处理FTP目录 - 重新设计的智能处理逻辑"""
        results = []

        try:
            import tempfile

            from utils.file_handler import FileHandler
            from utils.ftp_handler import FTPHandler

            # 创建FTP处理器
            ftp_handler = FTPHandler.from_url(ftp_url)
            file_handler = FileHandler()

            # 解析FTP URL获取路径
            from urllib.parse import urlparse

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

        # 步骤2: 下载视频文件进行进一步处理
        self.logger.info(
            f"📥 步骤2/5: 下载视频文件进行分析: {video_file.name}"
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

        # 步骤3: 检查视频内嵌字幕（优先）
        self.logger.info(f"🎬 步骤3/5: 分析视频内嵌字幕...")
        embedded_subtitles = self._extract_embedded_subtitles(local_video_path)

        if embedded_subtitles:
            self.logger.info(f"✅ 发现 {len(embedded_subtitles)} 个内嵌字幕流")
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

        # 步骤4: 回退查找英文字幕文件（外置）
        self.logger.info(f"🔍 步骤4/5: 查找现有英文字幕文件...")
        english_subtitle = self._find_english_subtitle(
            ftp_handler, ftp_connection, video_file
        )

        if english_subtitle:
            self.logger.info(f"✅ 发现英文字幕: {english_subtitle}")
            return self._process_existing_subtitle(
                ftp_handler,
                ftp_connection,
                english_subtitle,
                temp_dir,
                output_dir,
            )

        # 步骤5: 从音轨提取字幕（ASR）
        self.logger.info(f"🎵 步骤5/5: 开始音轨转录识别字幕...")

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

        # 可能的英文字幕文件名模式（按优先级排序）
        subtitle_patterns = [
            # 优先级1：内嵌字幕
            f"{video_name}.emb.srt",
            # 优先级2：通用字幕文件
            f"{video_name}.srt",
            # 优先级3：外置英文字幕
            f"{video_name}.en.srt",
            f"{video_name}.eng.srt",
            f"{video_name}.english.srt",
            f"{video_name}.en.vtt",
            f"{video_name}.eng.vtt",
            # 优先级4：音轨转录字幕
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
            import json
            import subprocess

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

    def _select_best_subtitle(
        self, subtitle_streams: List[Dict[str, str]], prefer_english: bool = True
    ) -> Optional[str]:
        """从多个字幕流中选择最佳字幕，优先选择英文字幕但不限制"""
        if not subtitle_streams:
            return None

        # 如果优先英文字幕，先尝试找英文字幕
        if prefer_english:
            english_subtitles = []
            for stream in subtitle_streams:
                language = stream.get("language", "").lower()
                title = stream.get("title", "").lower()
                if self._is_english_subtitle_stream(language, title):
                    english_subtitles.append(stream)
            
            if english_subtitles:
                self.logger.info(f"找到 {len(english_subtitles)} 个英文字幕流")
                return self._select_from_subtitle_list(english_subtitles, "英文")
        
        # 如果没有英文字幕或不优先英文，选择任何可用字幕
        self.logger.info(f"选择任何可用字幕，共 {len(subtitle_streams)} 个字幕流")
        return self._select_from_subtitle_list(subtitle_streams, "可用")

    def _select_from_subtitle_list(
        self, subtitle_list: List[Dict[str, str]], subtitle_type: str
    ) -> Optional[str]:
        """从字幕列表中选择最佳字幕"""
        if not subtitle_list:
            return None
            
        if len(subtitle_list) == 1:
            self.logger.info(
                f"找到1个{subtitle_type}字幕流: {subtitle_list[0]['language']}"
            )
            return subtitle_list[0]["path"]

        # 多个字幕时，使用质量评估器选择最佳
        self.logger.info(
            f"🔍 发现 {len(subtitle_list)} 个{subtitle_type}字幕流，开始质量评估..."
        )

        # 尝试使用质量评估器
        try:
            from utils.quality_assessor import SubtitleQualityAssessor
            assessor = SubtitleQualityAssessor(self.config)
            
            # 构建字幕候选列表
            subtitle_candidates = []
            for stream in subtitle_list:
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
        for stream in subtitle_list:
            subtitle_path = stream.get('path')
            if subtitle_path and os.path.exists(subtitle_path):
                self.logger.info(f"🔄 使用降级策略，选择第一个字幕: {subtitle_path}")
                return subtitle_path
        
        self.logger.warning("未找到有效的字幕文件")
        return None

    def _select_best_english_subtitle(
        self, subtitle_streams: List[Dict[str, str]]
    ) -> Optional[str]:
        """从多个字幕流中选择最佳的英文字幕（保持向后兼容）"""
        return self._select_best_subtitle(subtitle_streams, prefer_english=True)

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

    def get_processing_stats(self) -> Dict[str, Any]:
        """获取处理统计信息"""
        return self.stats.get_processing_stats()

    def cleanup(self) -> None:
        """清理资源"""
        try:
            # 清理临时文件和资源
            pass
        except Exception as e:
            self.logger.error(f"清理资源时发生错误: {e}")

    def _download_from_opensubtitles(
        self, video_path: str, target_lang: str
    ) -> Optional[str]:
        """从OpenSubtitles下载字幕（委托）"""
        return self.detector.download_from_opensubtitles(video_path, target_lang)

    def _get_video_duration(self, video_path: str) -> Optional[float]:
        """获取视频总时长（秒）（委托）"""
        return self.detector.get_video_duration(video_path)

    def _extract_audio(self, video_path: str) -> Optional[str]:
        """从视频文件中提取音轨"""
        self.logger.info(f"正在从 {video_path} 中提取音轨...")
        try:
            # 获取视频总时长
            total_duration = self._get_video_duration(video_path)

            temp_dir = tempfile.gettempdir()
            audio_path = os.path.join(temp_dir, f"{Path(video_path).stem}.aac")

            command = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "16000",
                "-progress",
                "pipe:1",
                str(audio_path),
            ]

            # 创建进度条
            with tqdm(total=100, desc="音频提取", unit="%", ncols=80) as pbar:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                last_progress = 0
                while True:
                    output = (
                        process.stdout.readline() if process.stdout else ""
                    )
                    if output == "" and process.poll() is not None:
                        break
                    if output and "out_time_ms=" in output:
                        try:
                            time_ms = int(
                                output.split("out_time_ms=")[1].strip()
                            )
                            current_seconds = time_ms / 1000000

                            if total_duration and total_duration > 0:
                                # 计算真实进度百分比
                                progress = min(
                                    100,
                                    (current_seconds / total_duration) * 100,
                                )
                                progress_diff = progress - last_progress
                                if progress_diff > 0:
                                    pbar.update(progress_diff)
                                    last_progress = progress
                                pbar.set_description(
                                    f"音频提取: {current_seconds:.1f}s/{total_duration:.1f}s"
                                )
                            else:
                                # 如果无法获取总时长，显示当前处理时间
                                pbar.set_description(
                                    f"音频提取: {current_seconds:.1f}s"
                                )
                        except (ValueError, IndexError):
                            pass

                # 确保进度条达到100%
                pbar.update(100 - pbar.n)
                pbar.set_description("音频提取完成")

            self.logger.info("音轨提取成功")
            return audio_path
        except FileNotFoundError:
            self.logger.error(
                "错误: ffmpeg 未安装或不在系统PATH中。请安装ffmpeg。"
            )
            return None
        except subprocess.CalledProcessError as e:
            self.logger.error(f"使用ffmpeg提取音轨时出错: {e.stderr}")
            return None

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

        # 2. 优先分析视频内嵌字幕
        self.logger.info("分析视频内嵌字幕...")
        embedded_subtitles = self._extract_embedded_subtitles(video_path_str)

        if embedded_subtitles:
            self.logger.info(
                f"找到 {len(embedded_subtitles)} 个内嵌字幕流"
            )

            # 选择最佳字幕（优先英文，但不限制）
            best_subtitle_path = self._select_best_subtitle(
                embedded_subtitles, prefer_english=True
            )

            if best_subtitle_path:
                # 保存为 .emb.srt 格式
                emb_subtitle_path = self._generate_final_subtitle_path(
                    video_path_str, "emb"
                )

                try:
                    # 复制最佳字幕到标准位置
                    import shutil

                    shutil.copy2(best_subtitle_path, emb_subtitle_path)
                    self.logger.info(
                        f"内嵌字幕已保存: {emb_subtitle_path}"
                    )

                    # 处理字幕进行翻译
                    result = self._process_local_subtitle(
                        emb_subtitle_path, output_dir
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
                    self.logger.error(f"处理内嵌字幕失败: {e}")
            else:
                self.logger.info("内嵌字幕中未找到可用字幕")
        else:
            self.logger.info("未找到内嵌字幕")

        # 3. 回退查找外置英文字幕文件
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
        """查找本地英文字幕文件，按优先级排序"""
        base_name = video_path.stem
        parent_dir = video_path.parent

        # 按优先级排序的英文字幕文件名
        # 1. .emb.srt - 优先级最高（内嵌字幕）
        # 2. .srt - 优先级其次（通用字幕文件）
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

    def _extract_from_audio_smart(
        self, video_path: str, output_dir: Optional[str]
    ) -> ProcessingResult:
        """从音轨提取并识别字幕"""
        start_time = time.time()

        try:
            # 首先尝试使用af_whisper（如果支持）
            self.logger.info("=== 开始尝试 af_whisper 转录 ===")
            subtitle_file = self._transcribe_with_af_whisper(video_path)

            if subtitle_file:
                # af_whisper成功，直接处理字幕文件
                self.logger.info("✓ af_whisper 转录成功，直接处理字幕文件")
                # 在翻译前明确打印视频与字幕
                self.logger.warning(
                    f"开始翻译字幕文件: {Path(subtitle_file).name} (来自视频: {Path(video_path).name}, 路径: {subtitle_file})"
                )
                result = self.process_single_file(subtitle_file, output_dir)

                # 清理临时文件
                try:
                    os.remove(subtitle_file)
                except Exception:
                    pass

                return result

            # af_whisper失败，回退到传统方法
            self.logger.info(
                "✗ af_whisper 不可用，回退到传统音频提取+Whisper方法"
            )

            # 提取音频
            audio_path = self._extract_audio(video_path)
            if not audio_path:
                return ProcessingResult(
                    success=False,
                    input_file=video_path,
                    error_message="音频提取失败",
                    processing_time=time.time() - start_time,
                )

            # 使用Whisper识别字幕
            subtitle_content = self._transcribe_with_whisper(audio_path)
            if not subtitle_content:
                return ProcessingResult(
                    success=False,
                    input_file=video_path,
                    error_message="音轨识别失败",
                    processing_time=time.time() - start_time,
                )

            # 保存临时字幕文件 - 使用统一命名规则
            temp_subtitle = self._generate_temp_subtitle_path(
                video_path, "whisper.temp"
            )
            with open(temp_subtitle, "w", encoding="utf-8") as f:
                f.write(subtitle_content)

            # 翻译字幕
            self.logger.warning(
                f"开始翻译字幕文件: {Path(temp_subtitle).name} (来自视频: {Path(video_path).name}, 路径: {temp_subtitle})"
            )
            result = self.process_single_file(temp_subtitle, output_dir)

            # 清理临时文件
            try:
                os.remove(temp_subtitle)
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass

            return result

        except Exception as e:
            return ProcessingResult(
                success=False,
                input_file=video_path,
                error_message=f"音轨处理失败: {str(e)}",
                processing_time=time.time() - start_time,
            )

    def _extract_from_audio_with_asr_naming(
        self, video_path: str, output_dir: Optional[str]
    ) -> ProcessingResult:
        """从音轨提取并识别字幕，使用 .asr.srt 命名"""
        start_time = time.time()

        try:
            # 生成 ASR 字幕文件路径
            asr_subtitle_path = self._generate_final_subtitle_path(
                video_path, "asr"
            )

            # 检查是否已存在 ASR 字幕
            if os.path.exists(asr_subtitle_path):
                self.logger.info(f"ASR字幕已存在: {asr_subtitle_path}")
                # 在翻译前明确打印视频与字幕
                self.logger.warning(
                    f"开始翻译字幕文件: {Path(asr_subtitle_path).name} (来自视频: {Path(video_path).name}, 路径: {asr_subtitle_path})"
                )
                return self._process_local_subtitle(
                    asr_subtitle_path, output_dir
                )

            # 首先尝试使用af_whisper（如果支持）
            self.logger.info("=== 开始尝试 af_whisper 转录 ===")
            subtitle_file = self._transcribe_with_af_whisper(video_path)

            if subtitle_file:
                # af_whisper成功，重命名为 ASR 格式
                self.logger.info("✓ af_whisper 转录成功")
                try:
                    import shutil

                    shutil.move(subtitle_file, asr_subtitle_path)
                    self.logger.info(f"ASR字幕已保存: {asr_subtitle_path}")
                    # 在翻译前明确打印视频与字幕
                    self.logger.warning(
                        f"开始翻译字幕文件: {Path(asr_subtitle_path).name} (来自视频: {Path(video_path).name}, 路径: {asr_subtitle_path})"
                    )
                    # 处理字幕进行翻译
                    return self._process_local_subtitle(
                        asr_subtitle_path, output_dir
                    )
                except Exception as e:
                    self.logger.error(f"保存ASR字幕失败: {e}")

            # af_whisper失败，回退到传统方法
            self.logger.info(
                "✗ af_whisper 不可用，回退到传统音频提取+Whisper方法"
            )

            # 提取音频
            audio_path = self._extract_audio(video_path)
            if not audio_path:
                # 音频提取失败，但不应该导致程序退出
                self.logger.warning(f"音频提取失败: {video_path}，跳过此文件")
                return ProcessingResult(
                    success=False,
                    input_file=video_path,
                    error_message="音频提取失败 - 可能是视频文件损坏或格式不支持",
                    processing_time=time.time() - start_time,
                )

            # 使用Whisper识别字幕
            subtitle_content = self._transcribe_with_whisper(audio_path)
            if not subtitle_content:
                self.logger.warning(f"音轨识别失败: {video_path}，跳过此文件")
                return ProcessingResult(
                    success=False,
                    input_file=video_path,
                    error_message="音轨识别失败 - 可能是音频质量问题或语言不支持",
                    processing_time=time.time() - start_time,
                )

            # 保存ASR字幕文件
            with open(asr_subtitle_path, "w", encoding="utf-8") as f:
                f.write(subtitle_content)

            self.logger.info(f"ASR字幕已保存: {asr_subtitle_path}")

            # 处理字幕进行翻译
            result = self._process_local_subtitle(
                asr_subtitle_path, output_dir
            )

            # 清理临时文件
            try:
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass

            return result

        except Exception as e:
            self.logger.warning(f"音轨处理失败: {video_path} - {str(e)}，跳过此文件")
            return ProcessingResult(
                success=False,
                input_file=video_path,
                error_message=f"音轨处理失败: {str(e)}",
                processing_time=time.time() - start_time,
            )

    def _extract_from_audio_with_asr_naming_and_upload(
        self,
        video_path: str,
        video_dir: str,
        ftp_handler: "FTPHandler",
        output_dir: Optional[str],
    ) -> ProcessingResult:
        """从音轨提取字幕，使用ASR命名并上传到FTP"""
        start_time = time.time()
        video_name = Path(video_path).stem

        try:
            self.logger.info(f"🎵 开始音轨转录: {video_name}")

            # 提取音频
            self.logger.info(f"📢 提取音频轨道...")
            audio_path = self._extract_audio(video_path)
            if not audio_path:
                return ProcessingResult(
                    success=False,
                    input_file=video_path,
                    error_message="音频提取失败",
                    processing_time=time.time() - start_time,
                )

            # 使用Whisper识别字幕
            self.logger.info(f"🤖 使用Whisper进行语音识别...")
            subtitle_content = self._transcribe_with_whisper(audio_path)
            if not subtitle_content:
                return ProcessingResult(
                    success=False,
                    input_file=video_path,
                    error_message="音轨识别失败",
                    processing_time=time.time() - start_time,
                )

            # 生成ASR字幕文件
            asr_subtitle_name = f"{video_name}.asr.srt"
            temp_dir = os.path.dirname(video_path)
            asr_subtitle_local_path = os.path.join(temp_dir, asr_subtitle_name)
            asr_subtitle_remote_path = f"{video_dir}/{asr_subtitle_name}"

            # 保存ASR字幕文件
            with open(asr_subtitle_local_path, "w", encoding="utf-8") as f:
                f.write(subtitle_content)
            self.logger.info(f"📝 ASR字幕已保存: {asr_subtitle_local_path}")

            # 先上传ASR字幕到FTP
            self.logger.info(
                f"📤 上传ASR字幕到FTP: {asr_subtitle_remote_path}"
            )
            if ftp_handler.upload_file(
                asr_subtitle_local_path, asr_subtitle_remote_path
            ):
                self.logger.info(
                    f"✅ ASR字幕上传成功: {asr_subtitle_remote_path}"
                )
            else:
                self.logger.warning(
                    f"⚠️ ASR字幕上传失败: {asr_subtitle_remote_path}"
                )

            # 然后进行翻译
            self.logger.info(f"🌐 开始翻译ASR字幕...")
            # 在翻译前明确打印视频与字幕
            self.logger.warning(
                f"开始翻译字幕文件: {os.path.basename(asr_subtitle_local_path)} (来源视频: {video_name}, 路径: {asr_subtitle_local_path})"
            )
            result = self.process_single_file(
                asr_subtitle_local_path, output_dir
            )

            # 上传翻译结果到FTP
            if result.success:
                self.logger.info(f"📤 上传翻译结果到FTP...")
                self._upload_result_to_ftp(ftp_handler, result, video_dir)

            # 清理临时文件
            try:
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass

            return result

        except Exception as e:
            return ProcessingResult(
                success=False,
                input_file=video_path,
                error_message=f"音轨处理失败: {str(e)}",
                processing_time=time.time() - start_time,
            )

    def _transcribe_with_whisper(self, audio_path: str) -> Optional[str]:
        """使用Whisper转录音频"""
        try:
            import os
            import whisper
            import torch

            # 新增：输入校验（存在性与非零大小）
            try:
                if not os.path.isfile(audio_path):
                    self.logger.error(f"音频文件不存在: {audio_path}")
                    return None
                size_bytes = os.path.getsize(audio_path)
                if size_bytes <= 0:
                    self.logger.error(f"音频文件大小为0: {audio_path}")
                    return None
            except Exception as ve:
                self.logger.error(f"音频文件校验失败: {ve}")
                return None

            # 获取音频文件大小和时长信息
            audio_size = os.path.getsize(audio_path) / (1024 * 1024)  # MB

            print(f"\n🎵 音频文件大小: {audio_size:.1f} MB")
            print("🔄 开始 Whisper 转录...")

            # 设备检测和配置
            device = self._get_optimal_device()
            use_fp16 = getattr(self.config, "WHISPER_FP16", True) and device != "cpu"
            
            print(f"🖥️  使用设备: {device}")
            if use_fp16:
                print("⚡ 启用半精度计算 (FP16)")

            # 阶段1: 加载模型
            print("\n📥 阶段 1/2: 加载 Whisper 模型...")
            with tqdm(
                total=1, desc="加载模型", unit="model", ncols=80
            ) as pbar:
                model = whisper.load_model(getattr(self.config, "WHISPER_MODEL", "base"), device=device)
                pbar.update(1)
            print("✅ 模型加载完成")

            # 获取音频时长用于进度计算
            audio_duration = None
            try:
                cmd = [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    audio_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    audio_duration = float(result.stdout.strip())
                    print(
                        f"📊 音频时长: {audio_duration / 60:.1f} 分钟"
                    )
            except BaseException:
                audio_duration = None

            # 阶段2: 字幕转录（带实时进度）
            print("\n🎯 阶段 2/2: 字幕转录...")
            print("📊 转录进度:")

            # 启动转录（在后台线程中）
            import queue
            import threading

            result_queue = queue.Queue()
            error_queue = queue.Queue()
            progress_queue = queue.Queue()

            def transcribe_worker():
                try:
                    # 启用VAD和更精确的语音检测参数
                    result = model.transcribe(
                        audio_path,
                        language=(None if (getattr(self.config, "WHISPER_LANGUAGE", None) or "").lower() == "auto" else getattr(self.config, "WHISPER_LANGUAGE", None)),
                        # VAD相关参数
                        no_speech_threshold=0.6,
                        logprob_threshold=-1.0,
                        compression_ratio_threshold=2.4,
                        # 时间戳相关参数
                        word_timestamps=True,
                        # 其他优化参数
                        condition_on_previous_text=True,
                        temperature=0.0,
                        beam_size=5,
                        best_of=5,
                        patience=1.0,
                        # GPU优化参数
                        fp16=use_fp16,
                    )
                    result_queue.put(result)
                except Exception as e:
                    error_queue.put(e)

            # 启动转录线程
            thread = threading.Thread(target=transcribe_worker)
            thread.start()

            # 实时显示转录进度
            start_time = time.time()
            last_update = time.time()
            update_interval = 2.0  # 每2秒更新一次

            # 如果知道音频时长，显示基于时长的进度条
            if audio_duration:
                with tqdm(
                    total=100, desc="转录进度", unit="%", ncols=80
                ) as pbar:
                    while thread.is_alive():
                        elapsed = time.time() - start_time
                        current_time = time.time()
                        
                        # 估算进度 (假设转录速度约为实时的 0.3x)
                        estimated_progress = min(100, (elapsed * 0.3 / audio_duration) * 100)
                        
                        if current_time - last_update >= update_interval:
                            current_pos = min(elapsed * 0.3, audio_duration)
                            pbar.n = estimated_progress
                            pbar.set_description(
                                f"转录进度: {current_pos:.1f}s/{audio_duration:.1f}s"
                            )
                            pbar.refresh()
                            last_update = current_time
                        
                        time.sleep(0.5)
                    
                    # 转录完成
                    pbar.n = 100
                    pbar.set_description("转录完成")
                    pbar.refresh()
            else:
                # 没有时长信息时，显示时间进度
                print("   时间   | 状态")
                print("   -------|--------")
                while thread.is_alive():
                    elapsed = time.time() - start_time
                    current_time = time.time()

                    if current_time - last_update >= update_interval:
                        time_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
                        status = "🔄 转录中..."
                        print(f"\r   {time_str}   | {status}", end="", flush=True)
                        last_update = current_time
                    
                    time.sleep(1.0)

            # 等待线程完成
            thread.join()

            # 检查是否有错误
            if not error_queue.empty():
                raise error_queue.get()

            # 获取结果
            if result_queue.empty():
                raise Exception("转录未返回结果")

            result = result_queue.get()

            # 显示最终结果
            elapsed_total = time.time() - start_time
            segments = result.get("segments", [])

            print(f"\n📊 转录统计:")
            print(f"   ⏱️  总耗时: {elapsed_total:.1f} 秒")
            print(f"   📝 字幕段数: {len(segments)} 个")

            if segments:
                total_duration = segments[-1].get("end", 0) if segments else 0
                print(f"   🎵 音频时长: {total_duration / 60:.1f} 分钟")
                print(
                    f"   ⚡ 转录速度: {total_duration / elapsed_total:.1f}x 实时速度"
                )

            # 检查结果类型并转换为SRT格式
            segments = result.get("segments")
            if not segments or not isinstance(segments, list):
                self.logger.error("Whisper转录结果格式错误")
                return None

            # 确保segments是正确的类型
            if not all(isinstance(seg, dict) for seg in segments):
                self.logger.error("Whisper segments格式错误")
                return None

            # 将转录结果转换为SRT格式
            srt_content = self._convert_whisper_to_srt(segments)

            self.logger.info(
                f"Whisper转录完成，生成了 {len(segments)} 个字幕段"
            )

            # 新增：空SRT结果明确告警并返回None，避免静默空输出
            if not srt_content or not srt_content.strip():
                self.logger.warning("Whisper转录返回空结果（无有效字幕段）")
                return None

            return srt_content

        except Exception as e:
            self.logger.error(f"Whisper转录失败: {str(e)}")
            return None

    def _transcribe_with_af_whisper(self, video_path: str) -> Optional[str]:
        """使用ffmpeg的af_whisper直接从视频生成字幕"""
        try:
            self.logger.info(f"检查 af_whisper 支持...")

            # 首先检查ffmpeg是否支持af_whisper滤镜
            check_cmd = ["ffmpeg", "-filters"]
            check_result = subprocess.run(
                check_cmd, capture_output=True, text=True
            )

            if "whisper" not in check_result.stdout:
                self.logger.warning(
                    "✗ ffmpeg 不支持 af_whisper 滤镜或版本过低"
                )
                return None

            # 阶段1: 模型准备
            print("\n📥 阶段 1/2: 准备 af_whisper 模型...")
            with tqdm(
                total=1, desc="模型准备", unit="model", ncols=80
            ) as pbar:
                # af_whisper 模型准备（实际上是内置的，这里只是显示准备过程）
                time.sleep(0.5)  # 模拟准备时间
                pbar.update(1)
            print("✅ 模型准备完成")

            self.logger.info("✓ ffmpeg 支持 af_whisper 滤镜，开始转录...")

            # 生成临时字幕文件路径
            temp_subtitle = self._generate_temp_subtitle_path(
                video_path, "af_whisper.temp"
            )

            # 使用af_whisper滤镜直接生成字幕（尊重配置语言；auto/None 时不指定以启用自动检测）
            _w_model = getattr(self.config, "WHISPER_MODEL", "base")
            _w_lang = getattr(self.config, "WHISPER_LANGUAGE", None)
            if isinstance(_w_lang, str) and _w_lang.lower() == "auto":
                _w_lang = None
            _af_filter = f"whisper=model={_w_model}" + (f":language={_w_lang}" if _w_lang else "")
            command = [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-af",
                _af_filter,
                "-f",
                "srt",
                temp_subtitle,
            ]

            self.logger.info(f"执行 af_whisper 命令: {' '.join(command)}")

            # 阶段2: 字幕转录（显示真实进度）
            print("\n🎯 阶段 2/2: 字幕转录...")
            total_duration = self._get_video_duration(video_path)

            # 修复：确保这两个变量在所有分支后均已绑定
            stderr_output: List[str] = []
            process = None  # type: Optional[subprocess.Popen]
            
            if total_duration:
                with tqdm(
                    total=100, desc="转录进度", unit="%", ncols=80
                ) as pbar:
                    process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                    last_progress = 0
                    # 保持对stderr的收集
                    while True:
                        output = (
                            process.stderr.readline() if process.stderr else ""
                        )
                        if output == "" and process.poll() is not None:
                            break
                        if output:
                            stderr_output.append(output.strip())
                            if "time=" in output:
                                try:
                                    # 解析ffmpeg输出中的时间信息
                                    time_str = output.split("time=")[1].split()[0]
                                    current_seconds = self._parse_time_to_seconds(
                                        time_str
                                    )

                                    # 计算真实进度
                                    progress = min(
                                        100,
                                        (current_seconds / total_duration) * 100,
                                    )
                                    progress_diff = progress - last_progress
                                    if progress_diff > 0:
                                        pbar.update(progress_diff)
                                        last_progress = progress
                                    pbar.set_description(
                                        f"转录进度: {current_seconds:.1f}s/{total_duration:.1f}s"
                                    )
                                except (ValueError, IndexError):
                                    pass

                    pbar.update(100 - pbar.n)
                    pbar.set_description("转录完成")
            else:
                # 无法获取时长时的备用显示方式
                print("📊 转录进度 (无法获取时长信息):")
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                
                start_time = time.time()
                while True:
                    output = process.stderr.readline() if process.stderr else ""
                    if output == "" and process.poll() is not None:
                        break
                    if output:
                        stderr_output.append(output.strip())  # 修复：也收集stderr
                        if "time=" in output:
                            try:
                                time_str = output.split("time=")[1].split()[0]
                                current_seconds = self._parse_time_to_seconds(time_str)
                                elapsed = time.time() - start_time
                                print(
                                    f"\r   处理时长: {current_seconds:.1f}s | 耗时: {elapsed:.1f}s",
                                    end="", flush=True
                                )
                            except (ValueError, IndexError):
                                pass

            # 检查执行结果
            if process and process.returncode == 0 and os.path.exists(temp_subtitle):
                self.logger.info(f"✓ af_whisper转录成功: {temp_subtitle}")
                print("\n✅ af_whisper 转录完成")
                return temp_subtitle
            else:
                self.logger.warning(
                    f"✗ af_whisper转录失败，返回码: {process.returncode if process else 'N/A'}"
                )
                if stderr_output:
                    self.logger.warning(
                        f"错误输出: {' '.join(stderr_output[-5:])}"
                    )
                return None

        except FileNotFoundError:
            self.logger.warning("✗ ffmpeg 不支持 af_whisper 滤镜或版本过低")
            return None
        except Exception as e:
            self.logger.error(f"✗ af_whisper 转录异常: {str(e)}")
            return None
            
    def _parse_time_to_seconds(self, time_str: str) -> float:
        """将ffmpeg时间格式转换为秒数"""
        try:
            parts = time_str.split(":")
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return (
                    float(hours) * 3600 + float(minutes) * 60 + float(seconds)
                )
            return 0.0
        except BaseException:
            return 0.0

    def _extract_from_audio(self, video_path: str) -> Optional[str]:
        """从音频提取字幕"""
        try:
            # 新增：视频文件存在性与非零大小校验
            try:
                if not os.path.isfile(video_path):
                    self.logger.error(f"视频文件不存在: {video_path}")
                    return None
                vsize = os.path.getsize(video_path)
                if vsize <= 0:
                    self.logger.error(f"视频文件大小为0: {video_path}")
                    return None
            except Exception as ve:
                self.logger.error(f"视频文件校验失败: {ve}")
                return None

            # 提取音频
            audio_path = self._extract_audio(video_path)
            if not audio_path:
                self.logger.error("音频提取失败")
                return None

            # 新增：提取出的音频文件再次校验
            try:
                if not os.path.isfile(audio_path):
                    self.logger.error(f"提取的音频文件不存在: {audio_path}")
                    return None
                asize = os.path.getsize(audio_path)
                if asize <= 0:
                    self.logger.error(f"提取的音频文件大小为0: {audio_path}")
                    return None
            except Exception as ve:
                self.logger.error(f"提取音频文件校验失败: {ve}")
                return None

            print("\n🔄 开始加载Whisper模型...")
            self.logger.info("开始加载Whisper模型")

            # 加载Whisper模型
            try:
                import whisper

                model_name = self.config.WHISPER_MODEL

                # 使用tqdm显示模型加载进度
                with tqdm(
                    total=1, desc="加载Whisper模型", unit="model"
                ) as pbar:
                    model = whisper.load_model(model_name)
                    pbar.update(1)

                print("✅ Whisper模型加载完成")
                self.logger.info(f"Whisper模型加载完成: {model_name}")

            except Exception as model_error:
                self.logger.error(f"Whisper模型加载失败: {model_error}")
                return None

            # 音频转录
            try:
                print("\n🔄 开始音频转录...")
                self.logger.info("开始音频转录")

                # 使用tqdm显示转录进度
                with tqdm(total=1, desc="音频转录中", unit="file") as pbar:
                    # 尝试自动检测语言
                    try:
                        result = model.transcribe(
                            audio_path,
                            language=None,  # 自动检测
                            verbose=False,
                            fp16=False,
                        )
                    except Exception as transcribe_error:
                        self.logger.warning(
                            f"自动语言检测失败，使用中文: {transcribe_error}"
                        )
                        # 回退到中文
                        result = model.transcribe(
                            audio_path,
                            language="zh",
                            verbose=False,
                            fp16=False,
                        )
                    pbar.set_description("转录完成")
                    pbar.update(1)

                # 防御性归一化，确保返回值为 str
                text_field = result.get("text")
                if isinstance(text_field, str):
                    transcribed_text: str = text_field
                elif isinstance(text_field, list):
                    transcribed_text = " ".join(str(x) for x in text_field)
                else:
                    transcribed_text = (
                        "" if text_field is None else str(text_field)
                    )

                print("\n✅ 音频转录完成")
                self.logger.info("音频转录完成")

                # 创建临时字幕文件 - 直接使用最终文件名格式
                video_name = Path(video_path).stem
                temp_subtitle_path = self._generate_final_subtitle_path(
                    video_path, "ai"
                )

                # 新增：空结果短路（既无分段又无文本时，直接返回None）
                no_segments = not result.get("segments")
                if no_segments and not transcribed_text.strip():
                    self.logger.warning("转录结果为空（无segments且无文本），放弃生成SRT")
                    # 清理临时音频文件
                    if not self.config.PREVENT_CLEANUP:
                        try:
                            os.remove(audio_path)
                        except Exception as cleanup_error:
                            self.logger.warning(f"清理临时文件失败: {cleanup_error}")
                    return None

                # 将转录结果转换为SRT格式并保存
                if "segments" in result and result["segments"]:
                    # 类型检查：确保segments是列表类型
                    segments = result["segments"]
                    if isinstance(segments, list) and all(
                        isinstance(seg, dict) for seg in segments
                    ):
                        # 如果有分段信息，使用分段生成SRT
                        srt_content = self._convert_whisper_to_srt(segments)
                    else:
                        # 如果segments类型不正确，创建单个字幕条目
                        srt_content = f"1\n00:00:00,000 --> 99:59:59,999\n{transcribed_text}\n\n"
                else:
                    # 如果没有分段信息，创建单个字幕条目
                    srt_content = f"1\n00:00:00,000 --> 99:59:59,999\n{transcribed_text}\n\n"

                # 新增：空SRT防卫
                if not srt_content or not srt_content.strip():
                    self.logger.warning("生成的SRT内容为空，放弃写入文件")
                    # 清理临时音频文件
                    if not self.config.PREVENT_CLEANUP:
                        try:
                            os.remove(audio_path)
                        except Exception as cleanup_error:
                            self.logger.warning(f"清理临时文件失败: {cleanup_error}")
                    return None

                # 保存SRT文件
                with open(temp_subtitle_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)

                self.logger.info(f"转录字幕已保存到: {temp_subtitle_path}")

                # 新增：保存后校验SRT文件存在且非空
                try:
                    if not os.path.isfile(temp_subtitle_path):
                        self.logger.warning(f"SRT文件未生成: {temp_subtitle_path}")
                        return None
                    srt_size = os.path.getsize(temp_subtitle_path)
                    if srt_size <= 0:
                        self.logger.warning(f"SRT文件为空: {temp_subtitle_path}")
                        return None
                except Exception as ve:
                    self.logger.warning(f"SRT文件校验失败: {ve}")
                    return None

            except Exception as transcribe_error:
                self.logger.error(f"音频转录失败: {transcribe_error}")
                return None

            # 清理临时音频文件
            if not self.config.PREVENT_CLEANUP:
                try:
                    os.remove(audio_path)
                except Exception as cleanup_error:
                    self.logger.warning(f"清理临时文件失败: {cleanup_error}")

            return temp_subtitle_path  # 返回字幕文件路径而不是文本内容

        except Exception as e:
            self.logger.error(f"音频转录时发生错误: {e}")
            return None

    def _convert_whisper_to_srt(self, segments: List[Dict[str, Any]]) -> str:
        """将 Whisper 转录结果转换为 SRT 格式，优先使用词级时间轴按停顿/标点/长度进行断句"""
        if not segments or not isinstance(segments, list):
            return ""

        # 配置阈值
        max_chars = getattr(self.config, "SUBTITLE_MAX_CHARS", 20)
        max_duration = getattr(self.config, "SUBTITLE_MAX_DURATION", 1.5)
        pause_split = getattr(self.config, "WORD_PAUSE_SPLIT", 0.225)  # 词间停顿阈值（50%）

        strong_punct = set([".", "?", "!", "。", "？", "！", "…"])
        weak_punct = set([",", ";", "，", "、", "；"])
        speaker_hints = ["-", "—", ":", "：", "——"]

        def needs_space(prev: str, cur: str) -> bool:
            if not prev or not cur:
                return False
            return prev[-1].isalnum() and cur[0].isalnum()

        def finalize_chunk(chunks: List[Dict[str, Any]], c_start: float, c_end: float, c_text: str) -> None:
            t = (c_text or "").strip()
            if not t:
                return
            # 收紧两端空格
            chunks.append({"start": float(c_start), "end": float(c_end), "text": t})

        def split_by_words(seg: Dict[str, Any]) -> List[Dict[str, Any]]:
            words = seg.get("words") or []
            if not isinstance(words, list) or not words:
                return []

            chunks: List[Dict[str, Any]] = []
            chunk_text = ""
            chunk_start: Optional[float] = None
            last_end: Optional[float] = None

            for idx, w in enumerate(words):
                w_text = str(w.get("word") or w.get("text") or "")
                if not w_text:
                    continue
                # Whisper 的词时间戳
                w_start = w.get("start")
                w_end = w.get("end")
                if w_start is None or w_end is None:
                    continue
                w_start = float(w_start)
                w_end = float(w_end)

                # 若当前无块，初始化
                if chunk_start is None:
                    chunk_start = w_start
                    last_end = w_start

                # 若与上一个词间隔较大，先结束上一个块
                gap_before = max(0.0, w_start - (last_end or w_start))
                if chunk_text and gap_before >= pause_split and chunk_start is not None and last_end is not None:
                    finalize_chunk(chunks, chunk_start, last_end, chunk_text)
                    chunk_text = ""
                    chunk_start = w_start

                # 追加当前词
                if needs_space(chunk_text, w_text):
                    chunk_text += " "
                chunk_text += w_text
                last_end = w_end

                # 决定是否在此处收束
                ends_with = w_text.strip()[-1:] if w_text.strip() else ""
                duration_now = max(0.0, (last_end or chunk_start) - (chunk_start or w_start))
                too_long = len(chunk_text) >= max_chars or duration_now >= max_duration
                is_strong = ends_with in strong_punct
                is_weak = ends_with in weak_punct

                if is_strong or (too_long and (is_weak or idx == len(words) - 1)):
                    if chunk_start is not None and last_end is not None:
                        finalize_chunk(chunks, chunk_start, last_end, chunk_text)
                    chunk_text = ""
                    chunk_start = None  # 下一块由后续词初始化

            # 收尾
            if chunk_text and chunk_start is not None and last_end is not None:
                finalize_chunk(chunks, chunk_start, last_end, chunk_text)

            # 后处理：合并极短片段与相邻片段
            merged: List[Dict[str, Any]] = []
            buf = None
            for c in chunks:
                if buf is None:
                    buf = c
                    continue
                dur = max(0.0, c["end"] - c["start"])
                gap = max(0.0, c["start"] - buf["end"])
                combined_text = (buf["text"] + " " + c["text"]).strip()
                if dur < 0.4 and gap <= 0.2 and len(combined_text) <= max_chars:
                    buf = {"start": buf["start"], "end": c["end"], "text": combined_text}
                else:
                    merged.append(buf)
                    buf = c
            if buf is not None:
                merged.append(buf)
            return merged

        def split_text_proportional(seg: Dict[str, Any]) -> List[Dict[str, Any]]:
            # 无词级信息时，按标点/长度切分，并按长度比例分配时间
            text = (seg.get("text") or "").strip()
            s = float(seg.get("start", 0.0))
            e = float(seg.get("end", s))
            d = max(0.0, e - s)
            if not text:
                return []

            # 先强后弱
            parts: List[str] = []
            buf = ""
            for ch in text:
                buf += ch
                if ch in strong_punct:
                    if buf.strip():
                        parts.append(buf.strip())
                    buf = ""
            if buf.strip():
                parts.append(buf.strip())
            if len(parts) <= 1:
                tmp = []
                for p in parts or [text]:
                    b = ""
                    for ch in p:
                        b += ch
                        if ch in weak_punct:
                            if b.strip():
                                tmp.append(b.strip())
                            b = ""
                    if b.strip():
                        tmp.append(b.strip())
                parts = tmp
            if not parts:
                parts = [text]

            # 过长再硬切
            normalized: List[str] = []
            for p in parts:
                if len(p) <= max_chars:
                    normalized.append(p)
                else:
                    if " " in p:
                        words = p.split()
                        line = []
                        for w in words:
                            cand = (" ".join(line + [w])).strip()
                            if len(cand) <= max_chars:
                                line.append(w)
                            else:
                                if line:
                                    normalized.append(" ".join(line))
                                line = [w]
                        if line:
                            normalized.append(" ".join(line))
                    else:
                        for i in range(0, len(p), max_chars):
                            normalized.append(p[i:i+max_chars])

            total_chars = sum(len(p) for p in normalized)
            if total_chars <= 0:
                return []
            out: List[Dict[str, Any]] = []
            cursor = s
            for p in normalized:
                ratio = len(p) / total_chars
                span = d * ratio if d > 0 else 0.0
                out.append({"start": cursor, "end": cursor + span, "text": p})
                cursor += span
            if out:
                out[-1]["end"] = e
            return out

        # 1) 过滤静音段与无效段
        valid_segments: List[Dict[str, Any]] = []
        for segment in segments:
            if isinstance(segment, dict) and all(k in segment for k in ["start", "end", "text"]):
                no_speech_prob = segment.get("no_speech_prob", 0.0)
                avg_logprob = segment.get("avg_logprob", 0.0)
                if no_speech_prob < 0.6 and avg_logprob > -1.0:
                    t = str(segment.get("text", "")).strip()
                    if t:
                        valid_segments.append(segment)
            else:
                self.logger.debug(f"跳过无效segment: {segment}")

        if not valid_segments:
            return ""

        # 2) 基于词级时间与标点切分
        split_segments: List[Dict[str, Any]] = []
        for seg in valid_segments:
            word_chunks = split_by_words(seg)
            if word_chunks:
                split_segments.extend(word_chunks)
            else:
                split_segments.extend(split_text_proportional(seg))

        # 3) 轻度合并，避免碎片化
        optimized_segments = self._optimize_speech_segments(split_segments)

        # 4) 生成SRT内容
        srt_lines: List[str] = []
        for i, segment in enumerate(optimized_segments, 1):
            srt_lines.append(f"{i}")
            srt_lines.append(f"{self._seconds_to_srt_time(segment['start'])} --> {self._seconds_to_srt_time(segment['end'])}")
            srt_lines.append(segment.get("text", "").strip())
            srt_lines.append("")
        return "\n".join(srt_lines)

    def _optimize_speech_segments(
        self, segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """基于语音间隔优化字幕段落"""
        if not segments:
            return []

        optimized = []
        current_segment = None

        for segment in segments:
            text = str(segment["text"]).strip()
            start_time = float(segment["start"])
            end_time = float(segment["end"])

            if current_segment is None:
                current_segment = {
                    "start": start_time,
                    "end": end_time,
                    "text": text,
                }
            else:
                # 计算与前一段的间隔
                gap = start_time - current_segment["end"]

                # 如果间隔小于0.5秒且内容相关，则合并
                if gap < 0.5 and self._should_merge_segments(
                    current_segment["text"], text
                ):
                    current_segment["end"] = end_time
                    current_segment["text"] += " " + text
                else:
                    # 间隔较大或内容不相关，保存当前段并开始新段
                    optimized.append(current_segment)
                    current_segment = {
                        "start": start_time,
                        "end": end_time,
                        "text": text,
                    }

        # 添加最后一个段落
        if current_segment is not None:
            optimized.append(current_segment)

        return optimized

    def _should_merge_segments(self, text1: str, text2: str) -> bool:
        """判断两个文本段是否应该合并
        规则：
        - 避免跨越强断句（中英标点 .?!。？！…）合并；
        - 避免跨越说话人提示（-, —, :, ：, ——）合并（可配置）；
        - 在长度与时长允许的情况下才合并。
        """
        t1 = (text1 or "").strip()
        t2 = (text2 or "").strip()
        if not t1 or not t2:
            return False

        # 说话人分割提示（可配置）
        if getattr(self.config, "ASR_SPEAKER_SPLIT_HINT", True):
            speaker_hints = ["-", "—", ":", "：", "——"]
            if any(h in t1[-3:] for h in speaker_hints) or any(h in t2[:3] for h in speaker_hints):
                return False

        strong_punct = (".", "?", "!", "。", "？", "！", "…")
        # 若第一段以强断句结束，不合并
        if t1.endswith(strong_punct):
            return False

        # 合并后长度限制
        combined_len = len((t1 + " " + t2).strip())
        if combined_len > 75:
            return False

        return True


    def _extract_subtitles_from_video(self, video_path: str) -> Optional[str]:
        """从视频文件中提取字幕（委托 + 回退音频转录）"""
        try:
            path = self.detector.extract_subtitles_from_video(video_path)
            if path:
                return path
            # 如果没有找到字幕文件，尝试音频转录
            self.logger.info("开始从音频提取字幕...")
            return self._extract_from_audio(video_path)
        except Exception as e:
            self.logger.error(f"处理视频文件时发生错误: {e}")
            return None

    # 在_analyze_subtitle_content方法中添加IMDB信息提取
    def _analyze_subtitle_content(self, subtitles, context):
        # 现有代码...

        # 如果没有从文件名或NFO获取到IMDB信息，尝试从字幕内容提取
        if (
            not context.plot
            and hasattr(self, "context_analyzer")
            and self.context_analyzer
        ):
            subtitle_text = "\n".join(
                [
                    sub.content if hasattr(sub, "content") else str(sub)
                    for sub in subtitles[:50]
                ]
            )
            imdb_info = self.context_analyzer.imdb_fetcher.extract_imdb_info_from_subtitles(
                subtitle_text
            )
            if imdb_info:
                # 更新上下文信息
                # 类似于上面的代码...
                pass
