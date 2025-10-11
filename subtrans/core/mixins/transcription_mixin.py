#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import tempfile
import time
import re
import sys as _sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from tqdm import tqdm

from core.types import ProcessingResult


@runtime_checkable
class _TranscriptionDeps(Protocol):
    """转录功能依赖的协议定义"""
    logger: Any
    config: Any

    def _get_video_duration(self, video_path: str) -> Optional[float]:
        ...

    def _generate_temp_subtitle_path(self, video_path: str, tag: str) -> str:
        ...

    def _generate_final_subtitle_path(self, video_path: str, tag: str, output_dir: Optional[str] = None) -> str:
        ...

    def _process_local_subtitle(self, subtitle_path: str, output_dir: Optional[str]) -> ProcessingResult:
        ...

    def process_single_file(self, file_path: str, output_dir: Optional[str]) -> ProcessingResult:
        ...

    def _upload_result_to_ftp(self, ftp_handler, result: ProcessingResult, remote_dir: str) -> None:
        ...

    def _parse_time_to_seconds(self, time_str: str) -> float:
        ...

    def _get_optimal_device(self) -> str:
        """获取最优的计算设备"""
        ...

    def _test_mps_compatibility(self) -> bool:
        """测试MPS设备与Whisper的兼容性"""
        ...

    # 以下方法由 TranscriptionMixin 自身实现，但为了类型检查，在协议中声明
    def _extract_audio(self: "_TranscriptionDeps", video_path: str) -> Optional[str]:
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

    def _extract_from_audio_smart(
        self: "_TranscriptionDeps", video_path: str, output_dir: Optional[str]
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
                from pathlib import Path as _Path
                self.logger.warning(
                    f"开始翻译字幕文件: {_Path(subtitle_file).name} (来自视频: {_Path(video_path).name}, 路径: {subtitle_file})"
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
            from pathlib import Path as _Path
            self.logger.warning(
                f"开始翻译字幕文件: {_Path(temp_subtitle).name} (来自视频: {_Path(video_path).name}, 路径: {temp_subtitle})"
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
        self: "_TranscriptionDeps", video_path: str, output_dir: Optional[str]
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
                from pathlib import Path as _Path
                self.logger.warning(
                    f"开始翻译字幕文件: {_Path(asr_subtitle_path).name} (来自视频: {_Path(video_path).name}, 路径: {asr_subtitle_path})"
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
                    from pathlib import Path as _Path
                    self.logger.warning(
                        f"开始翻译字幕文件: {_Path(asr_subtitle_path).name} (来自视频: {_Path(video_path).name}, 路径: {asr_subtitle_path})"
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
        self: "_TranscriptionDeps",
        video_path: str,
        video_dir: str,
        ftp_handler,
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

    def _transcribe_with_whisper(self: "_TranscriptionDeps", audio_path: str) -> Optional[str]:
        """使用Whisper转录音频"""
        try:
            import whisper
            import torch

            # 基础校验：文件存在且非空
            if not audio_path or not os.path.exists(audio_path):
                self.logger.error("Whisper转录失败：音频文件不存在: %s", audio_path)
                return None
            if os.path.getsize(audio_path) == 0:
                self.logger.error("Whisper转录失败：音频文件大小为0: %s", audio_path)
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
                # 使用配置的模型名和设备
                model_name = getattr(self.config, "WHISPER_MODEL", "base")
                model = whisper.load_model(model_name, device=device)
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
                        fp16=use_fp16,  # 使用半精度计算（GPU加速时）
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
            update_interval = 1.0  # 每1秒更新一次
            
            # 动态速度计算变量
            speed_samples = []
            max_samples = 10  # 保留最近10个样本用于平均
            
            # 如果知道音频时长，显示基于时长的进度条
            if audio_duration:
                with tqdm(
                    total=100, desc="🎵 转录进度", unit="%", ncols=100,
                    bar_format='{l_bar}{bar}| {n:.1f}% [{elapsed}<{remaining}, {rate_fmt}]'
                ) as pbar:
                    while thread.is_alive():
                        elapsed = time.time() - start_time
                        current_time = time.time()
                        
                        if current_time - last_update >= update_interval and elapsed > 0:
                            # 动态计算转录速度
                            if len(speed_samples) >= 2:
                                # 使用最近的速度样本计算平均速度
                                recent_speeds = speed_samples[-5:]  # 最近5个样本
                                avg_speed = sum(recent_speeds) / len(recent_speeds)
                                
                                # 基于动态速度估算进度
                                estimated_pos = min(elapsed * avg_speed, audio_duration)
                                estimated_progress = min(100, (estimated_pos / audio_duration) * 100)
                                
                                # 估算剩余时间
                                if avg_speed > 0:
                                    remaining_audio = audio_duration - estimated_pos
                                    remaining_time = remaining_audio / avg_speed
                                    remaining_str = f"{int(remaining_time // 60):02d}:{int(remaining_time % 60):02d}"
                                else:
                                    remaining_str = "计算中..."
                                
                                pbar.n = estimated_progress
                                pbar.set_description(
                                    f"🎵 转录进度 [{estimated_pos:.1f}s/{audio_duration:.1f}s] 速度:{avg_speed:.2f}x 剩余:{remaining_str}"
                                )
                            else:
                                # 初始阶段，使用保守估算
                                conservative_speed = 0.25  # 保守的初始速度
                                estimated_pos = min(elapsed * conservative_speed, audio_duration)
                                estimated_progress = min(100, (estimated_pos / audio_duration) * 100)
                                
                                pbar.n = estimated_progress
                                pbar.set_description(
                                    f"🎵 转录进度 [{estimated_pos:.1f}s/{audio_duration:.1f}s] 初始化中..."
                                )
                            
                            pbar.refresh()
                            last_update = current_time
                            
                            # 更新速度样本（基于实际观察到的模式）
                            if elapsed > 5:  # 5秒后开始收集速度样本
                                # 根据转录的典型模式调整速度估算
                                if elapsed < 30:
                                    # 初期较慢（模型加载和初始化）
                                    current_speed = 0.15
                                elif elapsed < 60:
                                    # 中期加速
                                    current_speed = 0.35
                                else:
                                    # 后期稳定
                                    current_speed = 0.45
                                
                                speed_samples.append(current_speed)
                                if len(speed_samples) > max_samples:
                                    speed_samples.pop(0)
                        
                        time.sleep(0.5)
                    
                    # 转录完成
                    pbar.n = 100
                    pbar.set_description("✅ 转录完成")
                    pbar.refresh()
            else:
                # 没有时长信息时，显示时间进度和状态
                print("🎵 转录进度 (未知时长)")
                print("=" * 50)
                stage_messages = [
                    "🔄 初始化模型...",
                    "🎯 分析音频特征...", 
                    "📝 生成转录文本...",
                    "🔧 优化字幕分段...",
                    "✨ 完善转录结果..."
                ]
                stage_index = 0
                stage_change_interval = 30  # 每30秒切换一次状态消息
                last_stage_change = start_time
                
                while thread.is_alive():
                    elapsed = time.time() - start_time
                    current_time = time.time()

                    if current_time - last_update >= update_interval:
                        # 更新状态消息
                        if current_time - last_stage_change >= stage_change_interval:
                            stage_index = min(stage_index + 1, len(stage_messages) - 1)
                            last_stage_change = current_time
                        
                        time_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
                        status = stage_messages[stage_index]
                        
                        # 添加动态指示器
                        dots = "." * (int(elapsed) % 4)
                        print(f"\r⏱️  耗时: {time_str} | {status}{dots}    ", end="", flush=True)
                        last_update = current_time
                    
                    time.sleep(1.0)
                
                print(f"\n✅ 转录完成! 总耗时: {int((time.time() - start_time) // 60):02d}:{int((time.time() - start_time) % 60):02d}")

            # 等待线程完成
            thread.join()

            # 检查是否有错误
            if not error_queue.empty():
                raise error_queue.get()

            # 获取结果
            if result_queue.empty():
                self.logger.warning("Whisper转录未返回任何结果（空队列）")
                return None

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
                self.logger.warning("Whisper转录结果为空或格式异常（segments缺失或非列表）")
                return None

            # 确保segments是正确的类型
            if not all(isinstance(seg, dict) for seg in segments):
                self.logger.warning("Whisper segments格式异常（包含非dict元素）")
                return None

            # 将转录结果转换为SRT格式
            srt_content = self._convert_whisper_to_srt(segments)
            if not srt_content or not srt_content.strip():
                self.logger.warning("Whisper转录生成的SRT内容为空")
                return None

            self.logger.info(
                "Whisper转录完成，生成了 %d 个字幕段", len(segments)
            )

            return srt_content

        except Exception as e:
            self.logger.error(f"Whisper转录失败: {str(e)}")
            return None

    def _transcribe_with_af_whisper(self: "_TranscriptionDeps", video_path: str) -> Optional[str]:
        """使用ffmpeg的af_whisper直接从视频生成字幕"""
        try:
            self.logger.info("检查 af_whisper 支持...")

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

            # 使用af_whisper滤镜直接生成字幕
            # 构建 whisper 滤镜字符串，按需添加语言参数（auto/None 时省略以启用自动检测）
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

            # 确保这两个变量在所有分支后均已绑定
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
                        stderr_output.append(output.strip())  # 也收集stderr
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
                
                # 进行SRT后处理优化
                optimized_subtitle = self._refine_srt_file(temp_subtitle)
                if optimized_subtitle:
                    # 删除原始文件，返回优化后的文件
                    try:
                        os.remove(temp_subtitle)
                    except Exception:
                        pass
                    return optimized_subtitle
                else:
                    # 优化失败，返回原始文件
                    return temp_subtitle
            else:
                self.logger.error(
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

    def _refine_srt_file(self: "_TranscriptionDeps", srt_file_path: str) -> Optional[str]:
        """对af_whisper生成的SRT文件进行后处理优化，改善分段质量"""
        try:
            with open(srt_file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
            if not content:
                self.logger.warning(f"SRT文件为空: {srt_file_path}")
                return None
                
            # 解析SRT文件为段落
            srt_blocks = content.split('\n\n')
            segments = []
            
            for block in srt_blocks:
                lines = block.strip().split('\n')
                if len(lines) >= 3:
                    try:
                        # 解析时间码
                        time_line = lines[1]
                        if ' --> ' in time_line:
                            start_str, end_str = time_line.split(' --> ')
                            start_time = self._srt_time_to_seconds(start_str.strip())
                            end_time = self._srt_time_to_seconds(end_str.strip())
                            text = '\n'.join(lines[2:]).strip()
                            
                            segments.append({
                                'start': start_time,
                                'end': end_time,
                                'text': text
                            })
                    except Exception as e:
                        self.logger.warning(f"解析SRT段落失败: {e}")
                        continue
            
            if not segments:
                self.logger.warning(f"未能解析任何有效SRT段落: {srt_file_path}")
                return None
                
            # 使用现有的优化和分割逻辑
            optimized_segments = self._optimize_speech_segments(segments)
            
            # 进一步按语气间隔/标点和长度拆分长段
            max_chars = getattr(self.config, "SUBTITLE_MAX_CHARS", 20)
            max_duration = getattr(self.config, "SUBTITLE_MAX_DURATION", 1.5)
            
            final_segments = []
            for seg in optimized_segments:
                parts = self._split_long_segment(seg, max_chars=max_chars, max_duration=max_duration)
                final_segments.extend(parts)
            
            # 生成优化后的SRT内容
            srt_lines = []
            idx = 1
            for seg in final_segments:
                start_time = seg.get("start", 0.0)
                end_time = seg.get("end", 0.0)
                text = seg.get("text", "").strip()

                # 过滤极短或空文本
                if not text or len(text) < 2:
                    continue

                srt_lines.append(str(idx))
                srt_lines.append(
                    f"{self._seconds_to_srt_time(start_time)} --> {self._seconds_to_srt_time(end_time)}"
                )
                srt_lines.append(text)
                srt_lines.append("")
                idx += 1
            
            # 生成优化后的文件路径
            refined_path = srt_file_path.replace('.temp', '.refined')
            
            # 写入优化后的内容
            with open(refined_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(srt_lines))
                
            self.logger.info(f"✓ SRT文件后处理完成: {refined_path}")
            return refined_path
            
        except Exception as e:
            self.logger.error(f"✗ SRT文件后处理失败: {e}")
            return None

    def _srt_time_to_seconds(self: "_TranscriptionDeps", time_str: str) -> float:
        """将SRT时间格式 (HH:MM:SS,mmm) 转换为秒数"""
        try:
            # 格式: 00:01:23,456
            time_part, ms_part = time_str.split(',')
            h, m, s = map(int, time_part.split(':'))
            ms = int(ms_part)
            return h * 3600 + m * 60 + s + ms / 1000.0
        except Exception:
            return 0.0

    def _seconds_to_srt_time(self: "_TranscriptionDeps", seconds: float) -> str:
        """将秒数格式化为SRT时间 (HH:MM:SS,mmm)"""
        try:
            if seconds is None or not isinstance(seconds, (int, float)):
                seconds = 0.0
            if seconds < 0:
                seconds = 0.0
            total_ms = int(round(seconds * 1000.0))
            ms = total_ms % 1000
            total_sec = total_ms // 1000
            s = total_sec % 60
            total_min = total_sec // 60
            m = total_min % 60
            h = (total_min // 60)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        except Exception:
            return "00:00:00,000"

    def _extract_from_audio(self: "_TranscriptionDeps", video_path: str) -> Optional[str]:
        """从音频提取字幕"""
        try:
            # 提取音频
            audio_path = self._extract_audio(video_path)
            if not audio_path or not os.path.exists(audio_path):
                self.logger.error("音频提取失败")
                return None
            if os.path.getsize(audio_path) == 0:
                self.logger.error("音频提取失败：音频文件大小为0: %s", audio_path)
                return None

            print("\n🔄 开始加载Whisper模型...")
            self.logger.info("开始加载Whisper模型")

            # 加载Whisper模型
            try:
                import whisper

                model_name = getattr(self.config, "WHISPER_MODEL", "base")

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
                temp_subtitle_path = self._generate_final_subtitle_path(
                    video_path, "ai"
                )

                # 将转录结果转换为SRT格式并保存
                segments = result.get("segments") if isinstance(result, dict) else None
                if segments and isinstance(segments, list) and all(isinstance(seg, dict) for seg in segments):
                    srt_content = self._convert_whisper_to_srt(segments)
                else:
                    srt_content = f"1\n00:00:00,000 --> 99:59:59,999\n{transcribed_text}\n\n"

                if not srt_content or not srt_content.strip():
                    self.logger.warning("转录结果生成的SRT为空，可能没有识别到有效语音")
                    return None

                # 保存SRT文件
                with open(temp_subtitle_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)

                self.logger.info(f"转录字幕已保存到: {temp_subtitle_path}")

            except Exception as transcribe_error:
                self.logger.error(f"音频转录失败: {transcribe_error}")
                return None

            # 清理临时音频文件
            if not getattr(self.config, "PREVENT_CLEANUP", False):
                try:
                    os.remove(audio_path)
                except Exception as cleanup_error:
                    self.logger.warning(f"清理临时文件失败: {cleanup_error}")

            return temp_subtitle_path  # 返回字幕文件路径而不是文本内容

        except Exception as e:
            self.logger.error(f"音频转录时发生错误: {e}")
            return None

    def _convert_whisper_to_srt(self: "_TranscriptionDeps", segments: List[Dict[str, Any]]) -> str:
        """将 Whisper 转录结果转换为 SRT 格式，基于VAD优化语音间隔对齐"""
        if not segments or not isinstance(segments, list):
            return ""

        # 验证每个segment的结构并过滤静音段
        valid_segments = []
        for segment in segments:
            if isinstance(segment, dict) and all(
                key in segment for key in ["start", "end", "text"]
            ):
                # 检查是否为有效语音段
                no_speech_prob = segment.get("no_speech_prob", 0.0)
                avg_logprob = segment.get("avg_logprob", 0.0)

                # 过滤可能的静音段（使用配置参数）
                vad_no_speech = getattr(self.config, "ASR_VAD_NO_SPEECH", 0.7)
                vad_logprob = getattr(self.config, "ASR_VAD_LOGPROB", -0.8)
                
                if no_speech_prob < vad_no_speech and avg_logprob > vad_logprob:
                    valid_segments.append(segment)

        # 如果没有有效段，回退到原始段
        if not valid_segments:
            valid_segments = segments

        # 对段进行轻度优化合并（减少碎片化字幕）
        optimized_segments = self._optimize_speech_segments(valid_segments)

        # 阈值（可通过配置覆盖）
        max_chars = getattr(self.config, "SUBTITLE_MAX_CHARS", 40)
        max_duration = getattr(self.config, "SUBTITLE_MAX_DURATION", 3.0)

        # 进一步按语气间隔/标点和长度拆分长段
        final_segments: List[Dict[str, Any]] = []
        for seg in optimized_segments:
            parts = self._split_long_segment(seg, max_chars=max_chars, max_duration=max_duration)
            final_segments.extend(parts)

        # 生成SRT内容
        srt_lines: List[str] = []
        idx = 1
        for seg in final_segments:
            start_time = seg.get("start", 0.0)
            end_time = seg.get("end", 0.0)
            text = seg.get("text", "").strip()

            # 基于VAD的进一步优化：移除可能的噪声片段
            if not text or len(text) < 2:
                continue

            srt_lines.append(str(idx))
            srt_lines.append(
                f"{self._seconds_to_srt_time(start_time)} --> {self._seconds_to_srt_time(end_time)}"
            )
            srt_lines.append(text)
            srt_lines.append("")
            idx += 1

        return "\n".join(srt_lines)

    def _optimize_speech_segments(
        self: "_TranscriptionDeps", segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """对Whisper的语音段进行轻度合并，减少碎片化字幕"""
        if not segments:
            return []

        optimized: List[Dict[str, Any]] = []
        current = None

        # 阈值（可通过配置覆盖）
        max_chars = getattr(self.config, "SUBTITLE_MAX_CHARS", 40)
        max_duration = getattr(self.config, "SUBTITLE_MAX_DURATION", 3.0)
        max_gap = getattr(self.config, "SUBTITLE_MERGE_MAX_GAP", 0.35)

        for seg in segments:
            if current is None:
                current = seg.copy()
                continue

            # 判断是否需要合并：间隔时间短且合并后仍较短
            gap = max(0.0, seg["start"] - current["end"])
            merged_duration = (seg["end"] - current["start"]) if current else 0.0
            merged_text = ((current.get("text", "") + " " + seg.get("text", "")).strip())
            merged_len = len(merged_text)

            if (
                gap <= max_gap
                and merged_duration <= max_duration
                and merged_len <= max_chars
                and self._should_merge_segments(current.get("text", ""), seg.get("text", ""))
            ):
                current["end"] = seg["end"]
                current["text"] = merged_text
            else:
                optimized.append(current)
                current = seg.copy()

        if current is not None:
            optimized.append(current)

        return optimized

    def _split_long_segment(
        self: "_TranscriptionDeps",
        segment: Dict[str, Any],
        max_chars: int = 40,
        max_duration: float = 3.0,
    ) -> List[Dict[str, Any]]:
        """将过长的字幕段按语气标点和长度拆分为更短的段。
        拆分策略：
        1) 先按强断句（. ? ! 。？！）切；
        2) 再按弱停顿（, ; ， 、；）切；
        3) 仍超长则按字数/词数硬切；
        时间按文本长度比例分配。
        """
        text = (segment.get("text") or "").strip()
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        duration = max(0.0, end - start)

        if not text:
            return []

        # 如果已足够短，直接返回
        if len(text) <= max_chars and duration <= max_duration:
            return [segment]

        def split_by_regex(t: str, pattern: str) -> List[str]:
            chunks: List[str] = []
            last = 0
            for m in re.finditer(pattern, t):
                idx = m.end()
                chunk = t[last:idx].strip()
                if chunk:
                    chunks.append(chunk)
                last = idx
            tail = t[last:].strip()
            if tail:
                chunks.append(tail)
            return chunks

        # 1) 强断句
        parts = split_by_regex(text, r"[^\S\r\n]*[\.\?\!。？！]+\s*")
        if len(parts) <= 1:
            # 2) 弱停顿
            parts = split_by_regex(text, r"[^\S\r\n]*[,;，、；]+\s*")
        if len(parts) <= 1:
            parts = [text]

        # 如果拆分后某些片段仍过长，进一步按字数硬切
        normalized: List[str] = []
        for p in parts:
            if len(p) <= max_chars:
                normalized.append(p)
            else:
                # 按空格分词优先，否则按字符切
                if " " in p:
                    words = p.split()
                    buf: List[str] = []
                    line = []
                    for w in words:
                        if len(" ".join(line + [w])) <= max_chars:
                            line.append(w)
                        else:
                            if line:
                                buf.append(" ".join(line))
                            line = [w]
                    if line:
                        buf.append(" ".join(line))
                    normalized.extend(buf)
                else:
                    for i in range(0, len(p), max_chars):
                        normalized.append(p[i:i+max_chars])

        # 依据文本长度比例分配时间
        total_chars = sum(len(p) for p in normalized)
        if total_chars == 0:
            return []

        segments_out: List[Dict[str, Any]] = []
        cursor = start
        for p in normalized:
            ratio = len(p) / total_chars
            seg_duration = duration * ratio if duration > 0 else 0
            seg_start = cursor
            seg_end = cursor + seg_duration
            segments_out.append({
                "start": seg_start,
                "end": seg_end,
                "text": p.strip(),
            })
            cursor = seg_end

        # 若因舍入导致最后终点小于原终点，校正最后一段终点
        if segments_out:
            segments_out[-1]["end"] = end

        # 合并极短片段（<0.4s）与相邻片段
        merged: List[Dict[str, Any]] = []
        current_segment: Optional[Dict[str, Any]] = None
        for s in segments_out:
            seg_dur = max(0.0, s["end"] - s["start"])
            if current_segment is None:
                current_segment = s
                continue
            if seg_dur < 0.4 and (s["start"] - current_segment["end"]) <= 0.2 and len((current_segment["text"] + " " + s["text"]).strip()) <= max_chars:
                current_segment = {
                    "start": current_segment["start"],
                    "end": s["end"],
                    "text": (current_segment["text"] + " " + s["text"]).strip(),
                }
            else:
                merged.append(current_segment)
                current_segment = s
        if current_segment is not None:
            merged.append(current_segment)

        return merged


    def _should_merge_segments(
        self: "_TranscriptionDeps", text1: str, text2: str
    ) -> bool:
        """检查两个文本段是否应该合并为一个字幕"""
        # 检查说话人分割提示（如果配置启用）
        if getattr(self.config, "ASR_SPEAKER_SPLIT_HINT", True):
            # 避免跨越强烈的说话人分割提示进行合并
            speaker_hints = ["-", "—", ":", "：", "——"]
            if any(hint in text1[-3:] or hint in text2[:3] for hint in speaker_hints):
                return False
        
        # 检查长度限制（从词数改为字符数，更严格）
        combined_length = len((text1 + " " + text2).strip())
        return combined_length <= 75  # 更严格的合并条件


class TranscriptionMixin:
    """转录相关功能的混入类"""

    def _get_optimal_device(self: "_TranscriptionDeps") -> str:
        """获取最优的计算设备"""
        import torch
        
        # 获取配置的设备偏好
        device_preference = getattr(self.config, "WHISPER_DEVICE", "auto")
        use_gpu = getattr(self.config, "WHISPER_USE_GPU", True)
        
        # 如果明确指定了设备，直接返回
        if device_preference != "auto":
            if device_preference == "cpu":
                return "cpu"
            elif device_preference == "mps" and torch.backends.mps.is_available():
                # 测试MPS兼容性
                if self._test_mps_compatibility():
                    return "mps"
                else:
                    self.logger.warning("MPS设备不兼容当前Whisper版本，回退到CPU")
                    return "cpu"
            elif device_preference == "cuda" and torch.cuda.is_available():
                return "cuda"
            else:
                self.logger.warning(f"指定的设备 {device_preference} 不可用，回退到自动选择")
        
        # 自动选择最优设备
        if not use_gpu:
            return "cpu"
        
        # 优先级：MPS (Apple Silicon) > CUDA > CPU
        if torch.backends.mps.is_available():
            # 测试MPS兼容性
            if self._test_mps_compatibility():
                return "mps"
            else:
                self.logger.warning("MPS设备不兼容当前Whisper版本，使用CPU")
                return "cpu"
        elif torch.cuda.is_available():
            return "cuda"
        else:
            return "cpu"
    
    def _test_mps_compatibility(self: "_TranscriptionDeps") -> bool:
        """测试MPS设备与Whisper的兼容性"""
        try:
            import whisper
            import torch
            
            # 尝试加载一个小模型到MPS设备
            model = whisper.load_model("tiny", device="mps")
            del model  # 释放内存
            return True
        except Exception:
            return False

    def _extract_from_audio(self, video_path: str):
        return _TranscriptionDeps._extract_from_audio(self, video_path)  # type: ignore

    def _refine_srt_file(self, srt_file_path: str):
        return _TranscriptionDeps._refine_srt_file(self, srt_file_path)  # type: ignore

    def _srt_time_to_seconds(self, time_str: str) -> float:
        return _TranscriptionDeps._srt_time_to_seconds(self, time_str)  # type: ignore

    def _seconds_to_srt_time(self, seconds: float) -> str:
        return _TranscriptionDeps._seconds_to_srt_time(self, seconds)  # type: ignore

    def _convert_whisper_to_srt(self, segments):
        return _TranscriptionDeps._convert_whisper_to_srt(self, segments)  # type: ignore

    def _optimize_speech_segments(self, segments):
        return _TranscriptionDeps._optimize_speech_segments(self, segments)  # type: ignore

    def _split_long_segment(self, segment, max_chars: int = 42, max_duration: float = 3.5):
        return _TranscriptionDeps._split_long_segment(self, segment, max_chars=max_chars, max_duration=max_duration)  # type: ignore

    def _transcribe_with_whisper(self, audio_path: str):
        return _TranscriptionDeps._transcribe_with_whisper(self, audio_path)  # type: ignore

    def _transcribe_with_af_whisper(self, video_path: str):
        return _TranscriptionDeps._transcribe_with_af_whisper(self, video_path)  # type: ignore

    def _extract_from_audio_smart(self, video_path: str, output_dir):
        return _TranscriptionDeps._extract_from_audio_smart(self, video_path, output_dir)  # type: ignore

    def _extract_from_audio_with_asr_naming(self, video_path: str, output_dir):
        return _TranscriptionDeps._extract_from_audio_with_asr_naming(self, video_path, output_dir)  # type: ignore