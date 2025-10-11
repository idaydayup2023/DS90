#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import tempfile
from enum import Enum
from typing import List, Optional


class ProcessingMode(Enum):
    """处理模式枚举"""

    LOCAL = "local"  # 本地文件处理
    BATCH = "batch"  # 批量处理
    FTP = "ftp"  # FTP模式


class SubTransConfig:
    """SubTrans配置类"""

    # 版本信息
    VERSION: str = "2.10.0"

    # 模型服务配置
    # 服务优先级：Ollama > LM Studio (基于测试结果，Ollama 在翻译质量上表现更优)
    MODEL_SERVICE_PRIORITY: List[str] = ["ollama", "lm_studio"]
    
    # Ollama配置
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_API_URL: str = "http://localhost:11434/api/generate"  # 添加API URL
    OLLAMA_MODEL: str = "gemma3"
    OLLAMA_TIMEOUT: int = 120  # 从30秒增加到120秒
    AUTO_SELECT_MODEL: bool = True  # 是否自动选择参数量最大的模型
    PREFERRED_MODEL_FAMILY: Optional[str] = "gemma3"  # 首选模型家族，默认为gemma3
    
    # LM Studio配置
    LM_STUDIO_URL: str = "http://localhost:1234"
    LM_STUDIO_API_URL: str = "http://localhost:1234/v1/chat/completions"  # OpenAI兼容API
    LM_STUDIO_MODEL: str = "google/gemma-3-4b"  # 默认模型，使用实际可用的Gemma模型
    LM_STUDIO_TIMEOUT: int = 120
    LM_STUDIO_MAX_TOKENS: int = 2048  # 最大输出token数
    LM_STUDIO_TEMPERATURE: float = 0.1  # 温度参数，较低值保证翻译一致性

    # 翻译配置
    TRANSLATION_TIMEOUT: int = 30  # 减少超时时间从60秒到30秒
    TRANSLATION_RETRIES: int = 2   # 减少重试次数从3次到2次
    BATCH_SIZE: int = 20  # 增加批量大小以提升性能

    # Whisper配置
    WHISPER_MODEL: str = "base"  # 使用base模型作为默认选择，平衡性能和精度
    WHISPER_SOURCE_LANGUAGE: Optional[str] = None  # None表示自动检测
    # GPU加速配置
    WHISPER_DEVICE: str = "auto"  # 设备选择: "auto", "cpu", "mps", "cuda"
    WHISPER_USE_GPU: bool = True  # 是否启用GPU加速（当可用时）
    WHISPER_FP16: bool = True     # 是否使用半精度计算（GPU加速时）

    # ASR/分段参数（优化后的参数，改善时间同步性）
    SUBTITLE_MAX_CHARS: int = 40              # 每条字幕最大字符数（从20增加到40）
    SUBTITLE_MAX_DURATION: float = 3.0        # 每条字幕最大时长（秒）（从1.5增加到3.0）
    SUBTITLE_MIN_DURATION: float = 0.8        # 每条字幕最小时长（秒）（从0.4增加到0.8）
    SUBTITLE_MERGE_MAX_GAP: float = 0.35      # 合并段落的最大间隔（秒）（从0.175增加到0.35）
    WORD_PAUSE_SPLIT: float = 0.45            # 词间停顿阈值（秒）（从0.225增加到0.45）
    ASR_VAD_NO_SPEECH: float = 0.7            # Whisper VAD: no_speech 阈值（从0.6放宽到0.7）
    ASR_VAD_LOGPROB: float = -0.8             # Whisper VAD: avg_logprob 阈值（从-1.0放宽到-0.8）
    ASR_SPLIT_STRONG_PUNCT: str = ".!?。？！"   # 强断句标点
    ASR_SPLIT_WEAK_PUNCT: str = ",;，、；"       # 弱停顿标点
    ASR_SPEAKER_SPLIT_HINT: bool = True       # 根据文本提示（如破折号/冒号）做说话人分割

    # 目录配置
    TEMP_DIR: str = tempfile.gettempdir()

    # 功能开关
    DISABLE_OPENSUBTITLES: bool = False
    FORCE_AUDIO_EXTRACTION: bool = False
    PREVENT_CLEANUP: bool = False
    # 新增：英文保真（当原始字幕为英文时，严格保留英文原文，不做任何清洗/改写）
    PRESERVE_ORIGINAL_ENGLISH: bool = True

    # 调试模式
    DEBUG_MODE: bool = False

    # OMDB API配置
    OMDB_API_KEY: Optional[str] = "ca27cde9"  # 设置默认的API密钥

    def __init__(self):
        self.config_dir = "/Users/daibo/subtrans/config"  # 默认配置目录

    def get_config_dir(self) -> str:
        """获取配置目录路径"""
        return self.config_dir

    def set_config_dir(self, config_dir: str) -> None:
        """设置配置目录路径"""
        self.config_dir = config_dir

    @classmethod
    def update_from_args(cls, args) -> None:
        """从命令行参数更新配置"""
        if hasattr(args, "ollama_url") and args.ollama_url:
            cls.OLLAMA_URL = args.ollama_url
            cls.OLLAMA_API_URL = f"{args.ollama_url.rstrip('/')}/api/generate"  # 自动构建API URL

        if hasattr(args, "lm_studio_url") and args.lm_studio_url:
            cls.LM_STUDIO_URL = args.lm_studio_url
            cls.LM_STUDIO_API_URL = f"{args.lm_studio_url.rstrip('/')}/v1/chat/completions"

        if hasattr(args, "model") and args.model:
            cls.OLLAMA_MODEL = args.model
            cls.LM_STUDIO_MODEL = args.model  # 同时设置LM Studio模型

        if hasattr(args, "batch_size") and args.batch_size:
            cls.BATCH_SIZE = args.batch_size

        if hasattr(args, "timeout") and args.timeout:
            cls.TRANSLATION_TIMEOUT = args.timeout

        # 添加重试次数配置支持
        if hasattr(args, "retries") and args.retries:
            cls.TRANSLATION_RETRIES = args.retries

        if hasattr(args, "whisper_model") and args.whisper_model:
            cls.WHISPER_MODEL = args.whisper_model

        if hasattr(args, "source_language") and args.source_language:
            cls.WHISPER_SOURCE_LANGUAGE = (
                args.source_language if args.source_language != "auto" else None
            )

        # GPU加速配置
        if hasattr(args, "whisper_device") and args.whisper_device:
            cls.WHISPER_DEVICE = args.whisper_device
        if hasattr(args, "no_gpu") and args.no_gpu:
            cls.WHISPER_USE_GPU = False
        if hasattr(args, "no_fp16") and args.no_fp16:
            cls.WHISPER_FP16 = False

        # 新增：ASR/分段参数覆盖
        if hasattr(args, "asr_max_chars") and args.asr_max_chars:
            cls.SUBTITLE_MAX_CHARS = int(args.asr_max_chars)
        if hasattr(args, "asr_max_duration") and args.asr_max_duration:
            cls.SUBTITLE_MAX_DURATION = float(args.asr_max_duration)
        if hasattr(args, "asr_min_duration") and args.asr_min_duration:
            cls.SUBTITLE_MIN_DURATION = float(args.asr_min_duration)
        if hasattr(args, "asr_merge_max_gap") and args.asr_merge_max_gap:
            cls.SUBTITLE_MERGE_MAX_GAP = float(args.asr_merge_max_gap)
        if hasattr(args, "asr_vad_no_speech") and args.asr_vad_no_speech is not None:
            cls.ASR_VAD_NO_SPEECH = float(args.asr_vad_no_speech)
        if hasattr(args, "asr_vad_logprob") and args.asr_vad_logprob is not None:
            cls.ASR_VAD_LOGPROB = float(args.asr_vad_logprob)
        if hasattr(args, "asr_speaker_split_hint") and args.asr_speaker_split_hint:
            cls.ASR_SPEAKER_SPLIT_HINT = True
        if hasattr(args, "no_speaker_split_hint") and args.no_speaker_split_hint:
            cls.ASR_SPEAKER_SPLIT_HINT = False

        if hasattr(args, "temp_dir") and args.temp_dir:
            cls.TEMP_DIR = args.temp_dir

        if hasattr(args, "no_opensubtitles") and args.no_opensubtitles:
            cls.DISABLE_OPENSUBTITLES = True

        if hasattr(args, "force_audio") and args.force_audio:
            cls.FORCE_AUDIO_EXTRACTION = True

        if hasattr(args, "no_cleanup") and args.no_cleanup:
            cls.PREVENT_CLEANUP = True

        # 新增：英文保真 CLI 开关
        if hasattr(args, "preserve_original_english") and args.preserve_original_english:
            cls.PRESERVE_ORIGINAL_ENGLISH = True
        if hasattr(args, "no_preserve_original_english") and args.no_preserve_original_english:
            cls.PRESERVE_ORIGINAL_ENGLISH = False

        # 添加OMDB API密钥处理
        if hasattr(args, "omdb_api_key") and args.omdb_api_key:
            cls.OMDB_API_KEY = args.omdb_api_key

        # 添加自动模型选择处理
        if hasattr(args, "auto_select_model") and args.auto_select_model:
            cls.AUTO_SELECT_MODEL = True
            
        if hasattr(args, "no_auto_select_model") and args.no_auto_select_model:
            cls.AUTO_SELECT_MODEL = False
            
        if hasattr(args, "preferred_model_family") and args.preferred_model_family:
            cls.PREFERRED_MODEL_FAMILY = args.preferred_model_family

    @classmethod
    def print_config(cls) -> None:
        """打印当前配置信息"""
        print(f"SubTrans {cls.VERSION} 配置信息:")
        print(f"  服务优先级: {' > '.join(cls.MODEL_SERVICE_PRIORITY)}")
        print(f"  Auto Select Model: {cls.AUTO_SELECT_MODEL}")
        if cls.PREFERRED_MODEL_FAMILY:
            print(f"  Preferred Model Family: {cls.PREFERRED_MODEL_FAMILY}")
        
        print(f"\n  === Ollama 配置 ===")
        print(f"  Ollama URL: {cls.OLLAMA_URL}")
        print(f"  Ollama API URL: {cls.OLLAMA_API_URL}")
        print(f"  Ollama Model: {cls.OLLAMA_MODEL}")
        print(f"  Ollama Timeout: {cls.OLLAMA_TIMEOUT}s")
        
        print(f"\n  === LM Studio 配置 ===")
        print(f"  LM Studio URL: {cls.LM_STUDIO_URL}")
        print(f"  LM Studio API URL: {cls.LM_STUDIO_API_URL}")
        print(f"  LM Studio Model: {cls.LM_STUDIO_MODEL}")
        print(f"  LM Studio Timeout: {cls.LM_STUDIO_TIMEOUT}s")
        print(f"  LM Studio Max Tokens: {cls.LM_STUDIO_MAX_TOKENS}")
        print(f"  LM Studio Temperature: {cls.LM_STUDIO_TEMPERATURE}")
        print(f"  Translation Timeout: {cls.TRANSLATION_TIMEOUT}s")
        print(f"  Translation Retries: {cls.TRANSLATION_RETRIES}")
        print(f"  Batch Size: {cls.BATCH_SIZE}")
        print(f"  Whisper Model: {cls.WHISPER_MODEL}")
        print(
            f"  Whisper Source Language: {cls.WHISPER_SOURCE_LANGUAGE or 'auto'}"
        )
        # GPU加速配置显示
        print(f"  Whisper Device: {cls.WHISPER_DEVICE}")
        print(f"  Whisper Use GPU: {cls.WHISPER_USE_GPU}")
        print(f"  Whisper FP16: {cls.WHISPER_FP16}")
        # 新增：打印ASR/分段参数
        print(f"  ASR Max Chars Per Cue: {cls.SUBTITLE_MAX_CHARS}")
        print(f"  ASR Max Duration: {cls.SUBTITLE_MAX_DURATION}s")
        print(f"  ASR Min Duration: {cls.SUBTITLE_MIN_DURATION}s")
        print(f"  ASR Merge Max Gap: {cls.SUBTITLE_MERGE_MAX_GAP}s")
        print(f"  ASR Word Pause Split: {cls.WORD_PAUSE_SPLIT}s")
        print(f"  ASR VAD no_speech_threshold: {cls.ASR_VAD_NO_SPEECH}")
        print(f"  ASR VAD logprob_threshold: {cls.ASR_VAD_LOGPROB}")
        print(f"  ASR Speaker Split Hint: {cls.ASR_SPEAKER_SPLIT_HINT}")
        print(f"  Temp Directory: {cls.TEMP_DIR}")
        print(f"  Debug Mode: {cls.DEBUG_MODE}")
        # 添加OMDB API密钥显示（隐藏部分字符）
        if cls.OMDB_API_KEY:
            masked_key = (
                cls.OMDB_API_KEY[:4]
                + "*" * (len(cls.OMDB_API_KEY) - 8)
                + cls.OMDB_API_KEY[-4:]
                if len(cls.OMDB_API_KEY) > 8
                else "*" * len(cls.OMDB_API_KEY)
            )
            print(f"  OMDB API Key: {masked_key}")
        else:
            print(f"  OMDB API Key: Not configured")
        print(f"  Disable OpenSubtitles: {cls.DISABLE_OPENSUBTITLES}")
        print(f"  Force Audio Extraction: {cls.FORCE_AUDIO_EXTRACTION}")
        print(f"  Prevent Cleanup: {cls.PREVENT_CLEANUP}")
        # 新增：打印英文保真开关
        print(f"  Preserve Original English: {cls.PRESERVE_ORIGINAL_ENGLISH}")
        print(f"  OMDB API Key: {'已配置' if cls.OMDB_API_KEY else '未配置'}")

    @classmethod
    def validate_config(cls) -> List[str]:
        """验证配置"""
        errors = []

        # 验证服务优先级配置
        if not cls.MODEL_SERVICE_PRIORITY:
            errors.append("MODEL_SERVICE_PRIORITY 不能为空")
        else:
            valid_services = {"ollama", "lm_studio"}
            for service in cls.MODEL_SERVICE_PRIORITY:
                if service not in valid_services:
                    errors.append(f"无效的服务名称: {service}，有效值为: {', '.join(valid_services)}")

        # 验证Ollama配置
        if not cls.OLLAMA_URL or not cls.OLLAMA_URL.startswith("http"):
            errors.append("Ollama URL格式无效，必须以http://或https://开头")
        
        if not cls.OLLAMA_API_URL or not cls.OLLAMA_API_URL.startswith("http"):
            errors.append("Ollama API URL格式无效，必须以http://或https://开头")
        
        if not cls.OLLAMA_MODEL or not cls.OLLAMA_MODEL.strip():
            errors.append("Ollama模型名称不能为空")

        # 验证LM Studio配置
        if not cls.LM_STUDIO_URL or not cls.LM_STUDIO_URL.startswith("http"):
            errors.append("LM Studio URL格式无效，必须以http://或https://开头")
        
        if not cls.LM_STUDIO_API_URL or not cls.LM_STUDIO_API_URL.startswith("http"):
            errors.append("LM Studio API URL格式无效，必须以http://或https://开头")
        
        if not cls.LM_STUDIO_MODEL or not cls.LM_STUDIO_MODEL.strip():
            errors.append("LM Studio模型名称不能为空")

        # 验证超时时间
        if cls.OLLAMA_TIMEOUT <= 0:
            errors.append("Ollama超时时间必须大于0秒")
        elif cls.OLLAMA_TIMEOUT > 600:
            errors.append("Ollama超时时间不应超过600秒")
            
        if cls.LM_STUDIO_TIMEOUT <= 0:
            errors.append("LM Studio超时时间必须大于0秒")
        elif cls.LM_STUDIO_TIMEOUT > 600:
            errors.append("LM Studio超时时间不应超过600秒")

        if cls.TRANSLATION_TIMEOUT <= 0:
            errors.append("翻译超时时间必须大于0秒")
        elif cls.TRANSLATION_TIMEOUT > 300:
            errors.append("翻译超时时间不应超过300秒")

        # 验证LM Studio特定参数
        if cls.LM_STUDIO_MAX_TOKENS <= 0:
            errors.append("LM Studio最大token数必须大于0")
        elif cls.LM_STUDIO_MAX_TOKENS > 8192:
            errors.append("LM Studio最大token数不应超过8192")
        
        if not (0.0 <= cls.LM_STUDIO_TEMPERATURE <= 2.0):
            errors.append("LM Studio温度参数必须在0.0到2.0之间")

        # 验证批处理大小
        if cls.BATCH_SIZE <= 0:
            errors.append("批处理大小必须大于0")
        elif cls.BATCH_SIZE > 100:
            errors.append("批处理大小不应超过100，以避免内存问题")

        # 验证重试次数
        if cls.TRANSLATION_RETRIES < 0:
            errors.append("翻译重试次数不能为负数")
        elif cls.TRANSLATION_RETRIES > 10:
            errors.append("翻译重试次数不应超过10次")

        # 验证首选模型家族
        if cls.PREFERRED_MODEL_FAMILY:
            valid_families = {"gemma", "gemma2", "gemma3", "llama", "llama2", "llama3", "qwen", "mistral", "phi"}
            if not any(cls.PREFERRED_MODEL_FAMILY.lower().startswith(family) for family in valid_families):
                errors.append(f"首选模型家族 '{cls.PREFERRED_MODEL_FAMILY}' 可能不被支持")

        # 验证临时目录
        if not cls.TEMP_DIR or not cls.TEMP_DIR.strip():
            errors.append("临时目录路径不能为空")
        elif not os.path.exists(cls.TEMP_DIR):
            try:
                os.makedirs(cls.TEMP_DIR, exist_ok=True)
            except Exception as e:
                errors.append(f"无法创建临时目录 {cls.TEMP_DIR}: {e}")

        # 验证字幕参数
        if cls.SUBTITLE_MAX_CHARS <= 0:
            errors.append("字幕最大字符数必须大于0")
        elif cls.SUBTITLE_MAX_CHARS > 200:
            errors.append("字幕最大字符数不应超过200")
        
        if cls.SUBTITLE_MAX_DURATION <= 0:
            errors.append("字幕最大时长必须大于0秒")
        elif cls.SUBTITLE_MAX_DURATION > 10:
            errors.append("字幕最大时长不应超过10秒")
        
        if cls.SUBTITLE_MIN_DURATION < 0:
            errors.append("字幕最小时长不能为负数")
        elif cls.SUBTITLE_MIN_DURATION >= cls.SUBTITLE_MAX_DURATION:
            errors.append("字幕最小时长不能大于等于最大时长")

        return errors
