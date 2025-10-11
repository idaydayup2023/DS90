#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 - 主程序入口
智能字幕提取与翻译工具
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

# 导入核心模块
from core.config import ProcessingMode, SubTransConfig
from core.subtitle_processor import SubtitleProcessor
from utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


def create_parser():
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="subtrans",
        description="SubTrans 2.0 - 智能字幕提取与翻译工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例用法:
  subtrans video.mkv                    # 处理单个视频文件
  subtrans /path/to/videos/             # 批量处理目录
  subtrans --ftp ftp://user:pass@host/  # FTP模式
  subtrans video.mkv --force-audio     # 强制音轨提取
        """,
    )

    # 基本参数
    parser.add_argument("input", nargs="?", help="输入文件或目录路径")
    parser.add_argument(
        "--version",
        action="version",
        version=f"subtrans {SubTransConfig.VERSION}",
    )

    # 翻译配置
    translation_group = parser.add_argument_group("翻译配置")
    translation_group.add_argument(
        "--ollama-url",
        help=f"Ollama服务器地址 (默认: {SubTransConfig.OLLAMA_URL})",
    )
    translation_group.add_argument(
        "--model", help=f"使用的翻译模型 (默认: {SubTransConfig.OLLAMA_MODEL})"
    )
    translation_group.add_argument(
        "--auto-select-model",
        action="store_true",
        help="自动选择参数量最大的模型进行翻译（默认已启用）"
    )
    translation_group.add_argument(
        "--no-auto-select-model",
        action="store_true",
        help="禁用自动模型选择功能"
    )
    translation_group.add_argument(
        "--preferred-model-family",
        help="首选模型家族 (如: gemma3, llama3, qwen2等)，与--auto-select-model配合使用"
    )
    translation_group.add_argument(
        "--batch-size",
        type=int,
        help=f"批处理大小 (默认: {SubTransConfig.BATCH_SIZE})",
    )
    translation_group.add_argument(
        "--timeout",
        type=int,
        help=f"翻译超时时间(秒) (默认: {SubTransConfig.TRANSLATION_TIMEOUT})",
    )
    # 新增：英文保真控制
    translation_group.add_argument(
        "--preserve-original-english",
        action="store_true",
        help="当检测到原始字幕为英文时，严格保留英文原文在双语字幕中（默认启用）",
    )
    translation_group.add_argument(
        "--no-preserve-original-english",
        action="store_true",
        help="禁用英文保真（允许对英文进行改写或清洗）",
    )

    # 音频处理配置
    audio_group = parser.add_argument_group("音频处理配置")
    audio_group.add_argument(
        "--whisper-model",
        choices=["tiny", "base", "small", "medium", "large"],
        help=f"Whisper模型大小 (默认: {SubTransConfig.WHISPER_MODEL})",
    )
    audio_group.add_argument(
        "--source-language",
        choices=["auto", "en", "zh", "yue", "ja", "ko", "fr", "de", "es"],
        help="""指定音频源语言，用于Whisper音频转录 (默认: auto)
                           支持的语言选项:
                           • auto - 自动检测语言 (推荐)
                           • en   - 英语 (English)
                           • zh   - 中文普通话 (Mandarin Chinese)
                           • yue  - 粤语 (Cantonese)
                           • ja   - 日语 (Japanese)
                           • ko   - 韩语 (Korean)
                           • fr   - 法语 (French)
                           • de   - 德语 (German)
                           • es   - 西班牙语 (Spanish)

                           注意: 指定正确的源语言可以提高转录准确性，
                           特别是对于粤语等方言。如果不确定，建议使用 auto""",
    )
    audio_group.add_argument(
        "--force-audio",
        action="store_true",
        help="强制从音轨提取字幕，跳过其他字幕源",
    )
    audio_group.add_argument(
        "--whisper-device",
        choices=["auto", "cpu", "mps", "cuda"],
        help="指定Whisper使用的计算设备 (默认: auto)",
    )
    audio_group.add_argument(
        "--no-gpu",
        action="store_true",
        help="禁用GPU加速，强制使用CPU",
    )
    audio_group.add_argument(
        "--no-fp16",
        action="store_true",
        help="禁用半精度计算(FP16)，使用全精度(FP32)",
    )

    # ASR/分段参数（新增）
    asr_group = parser.add_argument_group("ASR/分段参数")
    asr_group.add_argument(
        "--asr-max-chars",
        type=int,
        help=f"每条字幕最大字符数 (默认: {SubTransConfig.SUBTITLE_MAX_CHARS})",
    )
    asr_group.add_argument(
        "--asr-max-duration",
        type=float,
        help=f"每条字幕最大时长(秒) (默认: {SubTransConfig.SUBTITLE_MAX_DURATION})",
    )
    asr_group.add_argument(
        "--asr-min-duration",
        type=float,
        help=f"每条字幕最小时长(秒) (默认: {SubTransConfig.SUBTITLE_MIN_DURATION})",
    )
    asr_group.add_argument(
        "--asr-merge-max-gap",
        type=float,
        help=f"相邻段合并的最大间隔(秒) (默认: {SubTransConfig.SUBTITLE_MERGE_MAX_GAP})",
    )
    asr_group.add_argument(
        "--asr-vad-no-speech",
        type=float,
        help=f"Whisper VAD no_speech 阈值 (默认: {SubTransConfig.ASR_VAD_NO_SPEECH})",
    )
    asr_group.add_argument(
        "--asr-vad-logprob",
        type=float,
        help=f"Whisper VAD avg_logprob 阈值 (默认: {SubTransConfig.ASR_VAD_LOGPROB})",
    )
    asr_group.add_argument(
        "--asr-speaker-split-hint",
        action="store_true",
        help="启用基于文本提示的说话人分割（如破折号/冒号）",
    )
    asr_group.add_argument(
        "--no-speaker-split-hint",
        action="store_true",
        help="禁用基于文本提示的说话人分割",
    )

    # 处理选项
    process_group = parser.add_argument_group("处理选项")
    process_group.add_argument(
        "--no-opensubtitles", action="store_true", help="禁用OpenSubtitles下载"
    )
    process_group.add_argument(
        "--temp-dir", help=f"临时文件目录 (默认: {SubTransConfig.TEMP_DIR})"
    )
    process_group.add_argument(
        "--no-cleanup", action="store_true", help="不清理临时文件"
    )
    process_group.add_argument(
        "--output-dir", "-o", help="输出目录 (默认: 与输入文件同目录)"
    )
    process_group.add_argument(
        "--output-ass", action="store_true", help="同时输出ASS格式字幕"
    )

    # FTP模式
    ftp_group = parser.add_argument_group("FTP模式")
    ftp_group.add_argument(
        "--ftp",
        help="FTP服务器地址 (格式: ftp://user:pass@host[:port]/path/, 默认端口21)",
    )

    # 调试选项
    debug_group = parser.add_argument_group("调试选项")
    debug_group.add_argument(
        "--debug", action="store_true", help="启用调试模式"
    )
    debug_group.add_argument(
        "--limit", type=int, help="调试模式下限制处理的字幕条数"
    )
    debug_group.add_argument(
        "--verbose", "-v", action="store_true", help="详细输出"
    )
    debug_group.add_argument(
        "--config-info", action="store_true", help="显示当前配置信息"
    )

    # 在参数解析部分添加
    parser.add_argument(
        "--omdb-api-key", help="OMDB API密钥，用于获取电影信息"
    )
    return parser


def main():
    """主函数"""
    parser = create_parser()
    args = parser.parse_args()

    # 设置日志
    if args.debug:
        log_level = "DEBUG"
    elif args.verbose:
        log_level = "INFO"
    else:
        log_level = "WARNING"

    setup_logging(log_level=log_level)

    # 更新配置
    SubTransConfig.update_from_args(args)

    # 显示配置信息
    if args.config_info:
        SubTransConfig.print_config()
        return

    # 验证配置
    config_errors = SubTransConfig.validate_config()
    if config_errors:
        logger.error("配置错误:")
        for error in config_errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    # 确定处理模式
    if args.ftp:
        mode = ProcessingMode.FTP
        input_path = args.ftp
    elif args.input:
        input_path = args.input
        if Path(input_path).is_dir():
            mode = ProcessingMode.BATCH
        else:
            mode = ProcessingMode.LOCAL
    else:
        mode = ProcessingMode.BATCH
        input_path = "."

    logger.info(f"SubTrans {SubTransConfig.VERSION} 启动")
    logger.info(f"处理模式: {mode.value}")
    logger.info(f"输入路径: {input_path}")

    # 创建处理器
    processor = SubtitleProcessor(SubTransConfig)

    try:
        # 初始化组件
        if not processor.initialize_components(mode, args.ftp):
            logger.error("组件初始化失败")
            sys.exit(1)

        # 执行处理
        results = []

        if mode == ProcessingMode.LOCAL:
            result = processor.process_single_file(input_path, args.output_dir)
            results = [result]

        elif mode == ProcessingMode.BATCH:
            results = processor.process_directory(input_path, args.output_dir)

        elif mode == ProcessingMode.FTP:
            results = processor.process_ftp_directory(
                input_path, args.output_dir
            )

        # 输出结果统计
        successful = sum(1 for r in results if r.success)
        total = len(results)
        failed = total - successful

        logger.info(f"\n处理完成: {successful}/{total} 个文件成功")
        
        if failed > 0:
            logger.warning(f"失败文件数: {failed}")
            logger.info("失败原因:")
            for result in results:
                if not result.success:
                    logger.warning(f"  - {result.input_file}: {result.error_message}")

        if successful > 0:
            logger.info("输出文件:")
            for result in results:
                if result.success:
                    for output_file in result.output_files:
                        logger.info(f"  - {output_file}")

        # 显示统计信息
        if args.verbose:
            stats = processor.get_processing_stats()
            logger.info("\n处理统计:")
            for key, value in stats.items():
                logger.info(f"  {key}: {value}")

        # 修改退出逻辑 - 只有在所有文件都失败时才退出
        if successful == 0 and total > 0:
            logger.error("所有文件处理都失败")
            sys.exit(1)
        elif failed > 0:
            logger.warning(f"部分文件处理失败 ({failed}/{total})，但程序继续运行")
            # 部分失败时返回退出码2，表示部分成功
            sys.exit(2)
        else:
            logger.info("所有文件处理成功")
            sys.exit(0)

    except KeyboardInterrupt:
        logger.info("\n用户中断处理")
        sys.exit(1)

    except Exception as e:
        logger.error(f"处理过程中发生错误: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    finally:
        # 清理资源
        if not args.no_cleanup:
            processor.cleanup()


if __name__ == "__main__":
    main()
