import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import requests
import srt
from tqdm import tqdm

from utils.context_analyzer import MovieContext  # 使用已有的MovieContext类
from utils.logger import get_logger
from utils.model_selector import ModelSelector
from utils.model_service_client import ModelServiceManager

from .config import SubTransConfig
from .prompts import PromptTemplates

# 添加项目根目录到 Python 路径以解决导入问题
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入 TerminologyManager
try:
    import sys
    import os
    
    # 确保项目根目录在 Python 路径中
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    from utils.terminology_manager import TerminologyManager
    TERMINOLOGY_MANAGER_AVAILABLE = True
    print("✅ TerminologyManager 导入成功")
except ImportError as e:
    print(f"⚠️ 警告: 无法导入 TerminologyManager: {e}")
    import traceback
    print(f"详细错误信息: {traceback.format_exc()}")
    TerminologyManager = None
    TERMINOLOGY_MANAGER_AVAILABLE = False
except Exception as e:
    print(f"⚠️ TerminologyManager 初始化异常: {e}")
    import traceback
    print(f"详细错误信息: {traceback.format_exc()}")
    TerminologyManager = None
    TERMINOLOGY_MANAGER_AVAILABLE = False


class TranslationEngine:
    def __init__(self, config: SubTransConfig):
        self.config = config
        self.logger = get_logger(__name__)
        # 更简洁的方式：使用默认值初始化
        self.movie_context = MovieContext()
        
        # 初始化模型服务管理器
        self.service_manager = ModelServiceManager(config)
        
        # 自动模型选择
        if self.config.AUTO_SELECT_MODEL:
            self._auto_select_model()

        # 初始化 terminology_manager
        if TERMINOLOGY_MANAGER_AVAILABLE and TerminologyManager:
            try:
                self.terminology_manager = TerminologyManager(config)
                if hasattr(self.terminology_manager, "load_terminology"):
                    self.terminology_manager.load_terminology()
                self.logger.info("TerminologyManager 初始化成功")
            except Exception as e:
                self.logger.warning(f"初始化 TerminologyManager 失败: {e}")
                self.terminology_manager = None
        else:
            self.logger.warning("TerminologyManager 不可用，跳过初始化")
            self.terminology_manager = None

        # 添加调试模式配置
        if hasattr(self.config, "DEBUG_MODE") and self.config.DEBUG_MODE:
            import logging

            logging.getLogger("utils.terminology_manager").setLevel(
                logging.DEBUG
            )
            self.logger.debug("已启用 TerminologyManager 调试模式")
        
        # 验证配置
        self._validate_configuration()
        
        # 执行服务健康检查
        self._perform_health_check()
    
    def _validate_configuration(self) -> None:
        """验证配置有效性"""
        print("🔍 正在验证配置...")
        try:
            validation_errors = self.config.validate_config()
            
            if validation_errors:
                print("⚠️ 配置验证发现以下问题:")
                for i, error in enumerate(validation_errors, 1):
                    print(f"  {i}. {error}")
                    self.logger.warning(f"配置问题: {error}")
                
                # 如果有严重错误，抛出异常
                critical_errors = [
                    error for error in validation_errors 
                    if any(keyword in error for keyword in ["不能为空", "格式无效", "无法创建"])
                ]
                
                if critical_errors:
                    raise Exception(f"发现 {len(critical_errors)} 个严重配置错误，请修复后重试")
                else:
                    print("⚠️ 发现配置警告，但可以继续运行")
            else:
                print("✅ 配置验证通过")
                self.logger.info("配置验证通过")
                
        except Exception as e:
            self.logger.error(f"配置验证失败: {e}")
            raise
    
    def _perform_health_check(self) -> None:
        """执行模型服务健康检查"""
        print("🔍 正在检查模型服务状态...")
        try:
            health_status = self.service_manager.health_check()
            
            available_count = sum(1 for status in health_status.values() if status.get("available", False))
            total_count = len(health_status)
            
            print(f"📊 服务状态总览: {available_count}/{total_count} 个服务可用")
            
            for service_name, status in health_status.items():
                service_display_name = status.get("service_name", service_name)
                if status.get("available", False):
                    model_count = status.get("model_count", 0)
                    print(f"  ✅ {service_display_name}: {model_count} 个模型可用")
                else:
                    error_msg = status.get("error", "服务不可用")
                    print(f"  ❌ {service_display_name}: {error_msg}")
            
            if available_count == 0:
                self.logger.warning("⚠️ 没有可用的模型服务，请检查配置和服务状态")
            else:
                self.logger.info(f"✅ 健康检查完成，{available_count} 个服务可用")
                
        except Exception as e:
            self.logger.error(f"健康检查失败: {e}")
    
    def _auto_select_model(self) -> None:
        """自动选择最佳模型和服务"""
        print("🔍 正在自动选择最佳模型和服务...")
        try:
            model_selector = ModelSelector(self.config)
            selected_model, selected_service, reason = model_selector.suggest_best_model(self.config.PREFERRED_MODEL_FAMILY)
            
            if selected_model and selected_service:
                # 根据选择的服务更新配置
                if selected_service == "lm_studio":
                    original_model = self.config.LM_STUDIO_MODEL
                    self.config.LM_STUDIO_MODEL = selected_model
                    self.service_manager.set_preferred_service("lm_studio")
                    print(f"✅ 自动选择 LM Studio 模型: {original_model} -> {selected_model}")
                    self.logger.info(f"自动选择 LM Studio 模型: {original_model} -> {selected_model}")
                else:  # ollama
                    original_model = self.config.OLLAMA_MODEL
                    self.config.OLLAMA_MODEL = selected_model
                    self.service_manager.set_preferred_service("ollama")
                    print(f"✅ 自动选择 Ollama 模型: {original_model} -> {selected_model}")
                    self.logger.info(f"自动选择 Ollama 模型: {original_model} -> {selected_model}")
                
                print(f"📋 选择原因: {reason}")
                self.logger.info(f"模型选择原因: {reason}")
            else:
                print(f"⚠️ 自动模型选择失败，继续使用配置的模型")
                self.logger.warning(f"自动模型选择失败: {reason}")
                
        except Exception as e:
            print(f"❌ 自动模型选择过程中发生错误: {e}")
            print(f"⚠️ 继续使用配置的模型")
            self.logger.error(f"自动模型选择过程中发生错误: {e}")
            self.logger.warning(f"继续使用配置的模型")

    def _detect_language(self, text: str) -> str:
        """检测文本语言，使用大模型进行判定"""
        # 提交全文给大模型进行语言检测
        detected_language = self._submit_to_llm_for_language_detection(text)
        self.logger.debug(f"语言检测结果: '{detected_language}' for text: '{text[:100]}...'")
        return detected_language

    def _submit_to_llm_for_language_detection(self, text: str) -> str:
        """提交全文给大模型进行语言检测"""
        import re
        
        # 清理文本，移除时间戳和特殊字符
        clean_text = re.sub(r'\d{2}:\d{2}:\d{2}[,.]\d{3}', '', text)
        clean_text = re.sub(r'[\[\](){}]', '', clean_text)
        clean_text = clean_text.strip()
        
        if not clean_text:
            return "unknown"
        
        # 基于字符特征的语言检测
        # 中文检测
        if re.search(r'[\u4e00-\u9fff]', clean_text):
            return "chinese"
        
        # 西里尔文（俄语等）
        if re.search(r'[\u0400-\u04ff]', clean_text):
            return "russian"
        
        # 阿拉伯文
        if re.search(r'[\u0600-\u06ff]', clean_text):
            return "arabic"
        
        # 日文（平假名、片假名）
        if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', clean_text):
            return "japanese"
        
        # 韩文
        if re.search(r'[\uac00-\ud7af]', clean_text):
            return "korean"
        
        # 基于常见词汇的语言检测
        text_lower = clean_text.lower()
        
        # 西班牙语常见词汇和特征
        spanish_indicators = [
            r'\b(el|la|los|las|un|una|de|del|en|con|por|para|que|es|son|está|están)\b',
            r'\b(chicos|chicas|señor|señora|gracias|por favor|sí|no|muy|bien|mal)\b',
            r'\b(guarden|silencio|síntense|universidad|español|habla|dice|hacer)\b',
            r'ñ',  # 西班牙语特有字符
            r'[áéíóúü]',  # 西班牙语重音符号
        ]
        
        spanish_count = sum(1 for pattern in spanish_indicators if re.search(pattern, text_lower))
        
        # 法语常见词汇
        french_indicators = [
            r'\b(le|la|les|un|une|de|du|des|dans|avec|pour|que|est|sont|être|avoir)\b',
            r'\b(bonjour|merci|oui|non|très|bien|mal|français|parle|dit|faire)\b',
            r'[àâäéèêëïîôöùûüÿç]',  # 法语特殊字符
        ]
        
        french_count = sum(1 for pattern in french_indicators if re.search(pattern, text_lower))
        
        # 德语常见词汇
        german_indicators = [
            r'\b(der|die|das|ein|eine|und|oder|mit|für|von|zu|ist|sind|haben|sein)\b',
            r'\b(hallo|danke|ja|nein|sehr|gut|schlecht|deutsch|spricht|sagt|machen)\b',
            r'[äöüß]',  # 德语特殊字符
        ]
        
        german_count = sum(1 for pattern in german_indicators if re.search(pattern, text_lower))
        
        # 意大利语常见词汇
        italian_indicators = [
            r'\b(il|la|lo|gli|le|un|una|di|da|in|con|per|che|è|sono|essere|avere)\b',
            r'\b(ciao|grazie|sì|no|molto|bene|male|italiano|parla|dice|fare)\b',
            r'[àèéìíîòóù]',  # 意大利语重音符号
        ]
        
        italian_count = sum(1 for pattern in italian_indicators if re.search(pattern, text_lower))
        
        # 葡萄牙语常见词汇
        portuguese_indicators = [
            r'\b(o|a|os|as|um|uma|de|da|do|em|com|por|para|que|é|são|ser|ter)\b',
            r'\b(olá|obrigado|sim|não|muito|bem|mal|português|fala|diz|fazer)\b',
            r'[ãâáàçéêíóôõú]',  # 葡萄牙语特殊字符
        ]
        
        portuguese_count = sum(1 for pattern in portuguese_indicators if re.search(pattern, text_lower))
        
        # 土耳其语常见词汇
        turkish_indicators = [
            r'\b(bir|bu|şu|o|ve|ile|için|den|dan|da|de|ki|mi|mı|mu|mü)\b',
            r'\b(merhaba|teşekkür|evet|hayır|çok|iyi|kötü|türkçe|konuş|söyle|yap)\b',
            r'\b(ben|sen|o|biz|siz|onlar|var|yok|gel|git|gör|bil|ol|et)\b',
            r'[çğıöşüÇĞIİÖŞÜ]',  # 土耳其语特殊字符
        ]
        
        turkish_count = sum(1 for pattern in turkish_indicators if re.search(pattern, text_lower))
        
        # 英语常见词汇（作为最后检测）
        english_indicators = [
            r'\b(the|a|an|and|or|but|in|on|at|to|for|of|with|by|from|is|are|was|were|be|have|has|had|do|does|did)\b',
            r'\b(hello|thank|yes|no|very|good|bad|english|speak|say|make|get|go|come)\b',
        ]
        
        english_count = sum(1 for pattern in english_indicators if re.search(pattern, text_lower))
        
        # 根据匹配数量判断语言
        language_scores = {
            'spanish': spanish_count,
            'french': french_count,
            'german': german_count,
            'italian': italian_count,
            'portuguese': portuguese_count,
            'turkish': turkish_count,
            'english': english_count,
        }
        
        # 找到得分最高的语言
        max_score = max(language_scores.values())
        if max_score > 0:
            detected_language = max(language_scores, key=lambda x: language_scores.get(x, 0))
            self.logger.debug(f"语言检测结果: {detected_language} (得分: {max_score})")
            return detected_language
        
        # 如果没有匹配到任何语言特征，默认返回英语
        self.logger.debug("未能识别语言，默认为英语")
        return "english"

    def _build_translation_prompt(self, preprocessed_text: str, movie_context: Optional[MovieContext] = None, scene_types: Optional[List[str]] = None, abbreviation_rules: Optional[str] = None, extra_rules: Optional[List[str]] = None, batch_mode: bool = False) -> str:
        """
        分层模块化生成翻译提示词：
        - 基础通用提示词
        - 类型适配模块（根据影片类型和场景类型动态调整）
        - 缩写/术语处理规则
        - 内容长度与批量优化（短字幕或批量翻译自动简化）
        - 特殊内容处理（如音乐、歌词、台词等）
        - 支持配置化扩展
        """
        return PromptTemplates.build_translation_prompt(
            preprocessed_text=preprocessed_text,
            movie_context=movie_context,
            scene_types=scene_types,
            abbreviation_rules=abbreviation_rules,
            extra_rules=extra_rules,
            batch_mode=batch_mode
        )

    def _detect_scene_groups(self, subtitles: list) -> list:
        """将字幕分组为不同的场景
        
        场景分组规则：
        1. 基于时间间隔：如果两条字幕之间的时间间隔超过阈值，可以认为是不同场景
        2. 基于内容相似度：连续字幕内容的相似度高，可能属于同一场景
        
        返回场景分组列表，每个元素为 (start_index, end_index, scene_types)
        """
        if not subtitles:
            return []
            
        # 场景分组参数
        SCENE_TIME_THRESHOLD = 5  # 场景切换的时间阈值（秒）
        MIN_SCENE_SIZE = 3  # 最小场景大小（字幕条数）
        
        scene_groups = []
        current_scene_start = 0
        
        # 遍历字幕，根据时间间隔分组
        for i in range(1, len(subtitles)):
            prev_subtitle = subtitles[i-1]
            curr_subtitle = subtitles[i]
            
            # 计算时间间隔（秒）
            time_gap = (curr_subtitle.start - prev_subtitle.end).total_seconds()
            
            # 如果时间间隔超过阈值，认为是新场景
            if time_gap > SCENE_TIME_THRESHOLD:
                # 如果当前场景足够大，添加到场景列表
                if i - current_scene_start >= MIN_SCENE_SIZE:
                    scene_groups.append((current_scene_start, i-1, []))
                current_scene_start = i
        
        # 添加最后一个场景
        if len(subtitles) - current_scene_start >= MIN_SCENE_SIZE:
            scene_groups.append((current_scene_start, len(subtitles)-1, []))
        
        # 对每个场景进行类型检测
        for i, (start_idx, end_idx, _) in enumerate(scene_groups):
            # 合并场景内所有字幕文本
            scene_text = " ".join([self._clean_subtitle_text(subtitles[j].content.strip()) 
                                for j in range(start_idx, end_idx+1)])
            
            # 检测场景类型
            scene_types = self._detect_scene_type(scene_text)
            
            # 更新场景类型
            scene_groups[i] = (start_idx, end_idx, scene_types)
            
            # 记录场景信息
            subtitle_count = end_idx - start_idx + 1
            scene_start_time = subtitles[start_idx].start
            scene_end_time = subtitles[end_idx].end
            duration = (scene_end_time - scene_start_time).total_seconds()
            
            if scene_types:
                self.logger.info(f"🎬 场景 #{i+1}: 字幕 {start_idx+1}-{end_idx+1} ({subtitle_count}条, {duration:.1f}秒) 类型: {', '.join(scene_types)}")
            else:
                self.logger.debug(f"🎬 场景 #{i+1}: 字幕 {start_idx+1}-{end_idx+1} ({subtitle_count}条, {duration:.1f}秒) 未检测到明确类型")
        
        return scene_groups
    
    def translate_subtitle_content(
        self,
        content: str,
        target_language: str = "中文",
        progress_callback=None,
    ) -> str:
        """翻译字幕内容，生成中英文双语字幕"""
        try:
            # 解析SRT内容
            subtitles = list(srt.parse(content))
            self.logger.debug(f"解析到 {len(subtitles)} 个字幕条目")

            # 添加人名预分析
            if self.terminology_manager is not None:
                self.logger.debug("🔍 开始进行人名预分析...")
                # 直接传递字幕列表而不是合并的文本
                if hasattr(
                    self.terminology_manager, "build_name_consistency_map"
                ):
                    self.terminology_manager.build_name_consistency_map(
                        subtitles
                    )
                    self.logger.debug("✅ 人名预分析完成")
            else:
                self.logger.warning(
                    "⚠️ TerminologyManager 未初始化，跳过人名分析"
                )
            
            # 场景分组检测
            self.logger.info("🎬 开始场景分组检测...")
            scene_groups = self._detect_scene_groups(subtitles)
            self.logger.info(f"🎬 场景分组检测完成，共检测到 {len(scene_groups)} 个场景")
            
            # 创建字幕索引到场景类型的映射
            subtitle_to_scene_types = {}
            for start_idx, end_idx, scene_types in scene_groups:
                for i in range(start_idx, end_idx + 1):
                    subtitle_to_scene_types[i] = scene_types

            translated_subtitles = []

            # 使用批量翻译优化性能
            translated_subtitles = self._translate_subtitles_batch(
                subtitles, target_language, subtitle_to_scene_types, progress_callback
            )

            print("✅ 字幕翻译完成")

            # 重新组合为SRT格式
            result = srt.compose(translated_subtitles)
            self.logger.info(
                f"字幕翻译完成，共处理 {len(translated_subtitles)} 个条目"
            )
            return result

        except ImportError as e:
            self.logger.error(f"srt库导入失败: {e}")
            self.logger.error("请确保已安装srt库: pip install srt")
            return content
        except Exception as e:
            self.logger.error(f"翻译字幕内容失败: {e}")
            import traceback

            self.logger.error(f"详细错误信息: {traceback.format_exc()}")
            return content

    def _fallback_translate_text(self, text: str, target_language: str) -> str:
        """备用翻译逻辑：简单替换或返回提示"""
        self.logger.warning(f"使用备用翻译逻辑处理文本: {text[:50]}...")
        # 简单逻辑：直接返回原文并附加提示
        return f"{text}  # 翻译失败，建议人工校对"

    def _get_abbreviation_guide(self, types: List[str]) -> str:
        """根据类型（影片类型或场景类型）获取缩写处理指导"""
        if not types:
            return ""
            
        return "准确识别专业缩写，注意区分同形缩写的不同含义，避免与人名混淆"


    def _detect_scene_type(self, text: str) -> List[str]:
        """根据文本内容自动检测场景类型"""
        # 使用统一的场景类型关键词映射
        scene_type_keywords = PromptTemplates.SCENE_TYPE_KEYWORDS
        
        # 将文本转换为小写以进行不区分大小写的匹配
        text_lower = text.lower()
        
        # 计算每种场景类型的匹配分数
        scene_scores = {}
        for scene_type, keywords in scene_type_keywords.items():
            score = 0
            for keyword in keywords:
                if keyword in text_lower:
                    # 如果关键词出现在文本中，增加分数
                    # 可以根据关键词的重要性或出现频率调整分数
                    score += text_lower.count(keyword)
            if score > 0:
                scene_scores[scene_type] = score
        
        # 如果没有检测到任何场景类型，返回空列表
        if not scene_scores:
            return []
        
        # 按分数降序排序场景类型
        sorted_scenes = sorted(scene_scores.items(), key=lambda x: x[1], reverse=True)
        
        # 返回得分最高的场景类型（可以返回多个）
        # 对于超能力场景，降低阈值以确保TK/TP等关键缩写能被检测到
        top_scenes = []
        for scene, score in sorted_scenes[:2]:
            if scene == 'superhero' and score >= 1:  # 超能力场景阈值为1
                top_scenes.append(scene)
            elif score >= 2:  # 其他场景阈值为2
                top_scenes.append(scene)
        
        return top_scenes
        
    def _translate_text_dual(self, text: str, detected_lang: str) -> Optional[dict]:
        """对于非英文文本，同时翻译成中文和英文"""
        try:
            # 预处理特殊内容
            preprocessed_text = self._preprocess_special_content(text)

            # 如果是仅符号/音乐标签行，直接保留原文
            if self._is_symbolic_line(preprocessed_text):
                self.logger.debug("检测到符号/音乐标签行，直接保留原文")
                return {'chinese': preprocessed_text, 'english': preprocessed_text}

            # 构建双语翻译提示词
            prompt = PromptTemplates.get_dual_language_prompt(detected_lang, preprocessed_text)

            # 调用API进行翻译
            response = self._call_model_api(prompt)
            if not response:
                return None

            # 解析双语翻译结果
            import re
            chinese_match = re.search(r'中文[：:]\s*(.+)', response, re.MULTILINE)
            english_match = re.search(r'英文[：:]\s*(.+)', response, re.MULTILINE)
            
            if chinese_match and english_match:
                chinese_translation = chinese_match.group(1).strip()
                english_translation = english_match.group(1).strip()
                
                # 清理翻译结果
                chinese_translation = self._clean_subtitle_text(chinese_translation)
                english_translation = self._clean_subtitle_text(english_translation)
                
                return {
                    'chinese': chinese_translation,
                    'english': english_translation
                }
            else:
                self.logger.warning(f"无法解析双语翻译结果: {response}")
                return None
                
        except Exception as e:
            self.logger.error(f"双语翻译失败: {e}")
            return None

    def _translate_text(self, text: str, target_language: str = "中文") -> Optional[str]:
        """简化的文本翻译方法，主要用于特殊内容处理和测试"""
        try:
            # 预处理特殊内容
            preprocessed_text = self._preprocess_special_content(text)

            # 如果是仅符号/音乐标签行，直接保留原文
            if self._is_symbolic_line(preprocessed_text):
                self.logger.debug("检测到符号/音乐标签行，直接保留原文")
                return preprocessed_text

            # 如果是音乐/歌词行，使用精简提示词
            if self._is_music_line(preprocessed_text):
                music_prompt = PromptTemplates.get_music_translation_prompt(preprocessed_text)
                response = self._call_model_api(music_prompt)
                if response:
                    cleaned = self._post_process_translation(response.strip(), preprocessed_text)
                    final = self._postprocess_special_content(cleaned)
                    final = self._sanitize_music_translation(preprocessed_text, final)
                    if not final or self._is_invalid_translation(final, text):
                        self.logger.warning("音乐行翻译质量不合格，返回原文")
                        return text
                    self.logger.debug(f"音乐行翻译成功: '{text}' -> '{final}'")
                    return final
                else:
                    self.logger.debug("音乐行调用API返回空，返回原文")
                    return preprocessed_text

            # 对于普通文本，使用简单翻译提示词
            simple_prompt = PromptTemplates.get_simple_translation_prompt(preprocessed_text)
            response = self._call_model_api(simple_prompt)
            
            if response:
                cleaned_response = self._post_process_translation(response.strip(), preprocessed_text)
                final_response = self._postprocess_special_content(cleaned_response)
                
                if self._is_invalid_translation(final_response, text):
                    self.logger.warning(f"翻译质量不合格，返回原文: {text}")
                    return text
                    
                self.logger.debug(f"文本翻译成功: '{text}' -> '{final_response}'")
                return final_response
            else:
                self.logger.warning(f"文本翻译失败，API 返回空结果")
                return text

        except Exception as e:
            self.logger.error(f"翻译文本失败: {e}")
            return text

    def _post_process_translation(
        self, translation: str, original: str, is_english_original: bool = False
    ) -> str:
        """后处理翻译结果
        
        Args:
            translation: 翻译结果
            original: 原文
            is_english_original: 是否为英文原文
        """
        import re

        # 首先清理HTML标签和格式
        translation = self._clean_subtitle_text(translation)

        # 增强英文词汇检测和替换
        english_terms = {
            "namely": "即",
            "everything": "一切",
            "flora": "植物群",
            "fauna": "动物群",
            "craft": "技艺",
            "watershed": "分水岭",
        }

        for en, zh in english_terms.items():
            translation = re.sub(
                rf"\b{en}\b", zh, translation, flags=re.IGNORECASE
            )

        # 修复标点符号问题
        translation = re.sub(r"……+", "...", translation)
        translation = re.sub(r"，\s*以及", "以及", translation)

        # 简化翻译内容提取逻辑
        # 移除常见的前缀标记
        translation = re.sub(r'^.*?双语字幕[：:]?\s*', '', translation)
        translation = re.sub(r'^.*?翻译[：:]?\s*', '', translation)
        translation = re.sub(r'^\*\*[^\*]*\*\*\s*', '', translation)
        
        # 提取引号内的内容（如果存在）
        quote_match = re.search(r'[""'']([^""'']+)[""'']', translation)
        if quote_match:
            translation = quote_match.group(1).strip()
        
        # 移除开头和结尾的引号
        translation = re.sub(r'^[""''] *', '', translation)
        translation = re.sub(r' *[""'']$', '', translation)

        # 移除常见的翻译标记
        translation = re.sub(r"^(翻译结果?[:：]?\s*)", "", translation)
        translation = re.sub(r"^(中文[:：]?\s*)", "", translation)
        translation = re.sub(r'^["""](.*)["""]$', r"\1", translation)

        # 最终清理
        translation = re.sub(r"\s+", " ", translation)  # 合并多余空格

        # 移除中英文混杂
        translation = self._fix_language_mixing(translation, is_english_original)

        # 修复人名一致性
        translation = self._fix_name_consistency(translation)

        # 验证翻译质量
        if self._is_invalid_translation(translation, original):
            self.logger.warning(
                f"检测到无效翻译，返回原文: {translation[:50]}..."
            )
            return original

        return translation.strip()

    def _sanitize_music_translation(self, original: str, translated: str) -> str:
        """针对音乐/歌词行的严格清理，确保不产生额外说明性内容。
        - 保留音乐符号和括号包裹的音乐标签
        - 移除任何解释性前后缀（如“歌词：”“中文翻译：”等）
        - 合并多余空白，去除多余标点
        - 如果结果为空，则回退到 original
        """
        import re
        if not translated:
            return original

        t = translated.strip()
        # 去除常见提示/说明残留
        t = re.sub(r"^(?:翻译结果|翻译|中文翻译|歌词|结果)[:：\s-]*", "", t)
        t = re.sub(r"^(?:\*\*|—|--|——)+\s*", "", t)
        t = re.sub(r"^（注：.*?）$", "", t)
        t = re.sub(r"^注：.*$", "", t)

        # 移除成段的英文句子（避免解释/注释）
        t = re.sub(r"[A-Za-z]{3,}(?:[\w\s,.'\-:;!?])*", "", t)

        # 合并空白
        t = re.sub(r"\s+", " ", t).strip()

        # 去除开头/结尾多余的标点
        t = re.sub(r"^[，。！？、:：;；\-—~·]+", "", t)
        t = re.sub(r"[，。！？、:：;；\-—~·]+$", "", t)

        # 若清理后为空，回退到原文以避免噪声
        return t if t else original

    def _fix_language_mixing(self, translation: str, is_english_original: bool = False) -> str:
        """修复中英文混杂问题
        
        Args:
            translation: 要处理的文本
            is_english_original: 是否为英文原文，如果是则跳过处理
        """
        # 如果是英文原文，直接返回，不进行任何处理
        if is_english_original:
            return translation
        # 语气词和感叹词替换
        interjection_replacements = {
            "oh": "哦",
            "ah": "啊",
            "wow": "哇",
            "hmm": "嗯",
            "huh": "嗯",
            "yeah": "是的",
            "yep": "对",
            "nope": "不",
            "uh": "呃",
            "oops": "哎呀",
            "whoa": "哇哦",
            "hey": "嘿",
            "hi": "嗨",
            "bye": "再见",
            "okay": "好的",
            "ok": "好",
            "well": "嗯",
            "so": "所以",
            "but": "但是",
            "however": "然而",
            "actually": "实际上",
            "basically": "基本上",
            "literally": "简直",
            "seriously": "说真的",
            "honestly": "老实说",
            "frankly": "坦率地说",
        }

        # 常见英文词汇替换
        replacements = {
            "and": "和",
            "or": "或",
            "the": "",
            "a": "",
            "an": "",
            "is": "是",
            "are": "是",
            "was": "是",
            "were": "是",
            "will": "将",
            "would": "会",
            "can": "能",
            "could": "能够",
            "should": "应该",
            "must": "必须",
            "may": "可能",
            "might": "可能",
            "have": "有",
            "has": "有",
            "had": "有",
            "do": "做",
            "does": "做",
            "did": "做",
            "get": "得到",
            "got": "得到",
            "go": "去",
            "went": "去了",
            "come": "来",
            "came": "来了",
            "see": "看",
            "saw": "看到",
        }

        # 应用替换
        for en_word, zh_word in replacements.items():
            # 使用单词边界确保完整匹配
            pattern = r"\b" + re.escape(en_word) + r"\b"
            translation = re.sub(
                pattern, zh_word, translation, flags=re.IGNORECASE
            )

        # 移除孤立的英文单词（保留已知人名）
        if hasattr(self, "movie_context") and self.movie_context.characters:
            known_names = set(self.movie_context.characters.keys())
            words = translation.split()
            filtered_words = []
            for word in words:
                # 如果是英文单词且不是已知人名，则移除
                if re.match(r"^[a-zA-Z]+$", word) and word not in known_names:
                    continue
                filtered_words.append(word)
            translation = " ".join(filtered_words)

        return translation

    def _fix_name_consistency(self, translation: str) -> str:
        """修复人名一致性 - 增强版"""
        # 应用术语管理器的人名一致性
        if (
            hasattr(self, "terminology_manager")
            and self.terminology_manager is not None
        ):
            if hasattr(self.terminology_manager, "apply_name_consistency"):
                translation = self.terminology_manager.apply_name_consistency(
                    translation
                )

        # 处理中英文混合的人名标签
        mixed_pattern = r"\[([^\]]*[\u4e00-\u9fff][^\]]*[a-zA-Z][^\]]*)\]|\[([^\]]*[a-zA-Z][^\]]*[\u4e00-\u9fff][^\]]*)\]"

        def fix_mixed_name(match):
            name = match.group(1) or match.group(2)
            # 修复：增加更严格的属性检查和初始化检查
            if (
                hasattr(self, "terminology_manager")
                and self.terminology_manager is not None
                and hasattr(self.terminology_manager, "name_consistency_map")
            ):

                # 确保name_consistency_map已初始化
                if (
                    not hasattr(
                        self.terminology_manager, "name_consistency_map"
                    )
                    or self.terminology_manager.name_consistency_map is None
                ):
                    self.terminology_manager.name_consistency_map = {}

                try:
                    for (
                        en_name,
                        zh_name,
                    ) in self.terminology_manager.name_consistency_map.items():
                        if en_name in name:
                            return f"[{zh_name}]"
                except (AttributeError, TypeError) as e:
                    self.logger.warning(f"访问name_consistency_map时出错: {e}")
                    # 重新初始化映射
                    self.terminology_manager.name_consistency_map = {}

            # 修复：确保函数总是返回一个值
            return match.group(0)

        translation = re.sub(mixed_pattern, fix_mixed_name, translation)

        return translation

    def preprocess_for_translation(self, text: str) -> Tuple[str, Dict]:
        protected_terms = {}
        processed_text = text

        # 修复：初始化names变量
        names = []

        # 提取并保护人名
        if (
            hasattr(self, "terminology_manager")
            and self.terminology_manager is not None
            and hasattr(
                self.terminology_manager, "extract_names_from_subtitle"
            )
            and callable(
                getattr(
                    self.terminology_manager, "extract_names_from_subtitle"
                )
            )
        ):
            try:
                names = self.terminology_manager.extract_names_from_subtitle(
                    text
                )
                # 确保names是列表格式
                if not isinstance(names, list):
                    names = []
            except Exception as e:
                self.logger.warning(f"提取名称时出错: {e}")
                names = []  # 确保在异常情况下names有默认值

        # 处理提取的名称
        for i, name_info in enumerate(names):
            try:
                # 处理不同的返回格式
                if isinstance(name_info, tuple) and len(name_info) >= 2:
                    name, name_type = name_info[0], name_info[1]
                elif isinstance(name_info, str):
                    name, name_type = name_info, "unknown"
                else:
                    continue

                placeholder = f"__NAME_{i}__"
                protected_terms[placeholder] = name
                processed_text = processed_text.replace(name, placeholder)
            except (ValueError, IndexError) as e:
                self.logger.warning(f"处理名称信息时出错: {e}")
                continue

        return processed_text, protected_terms

    def postprocess_translation(
        self, translation: str, protected_terms: Dict
    ) -> str:
        """翻译后处理，恢复人名和专有名称"""
        result = translation

        # 恢复保护的术语
        for placeholder, original_term in protected_terms.items():
            # 检查是否有已知翻译
            if (
                hasattr(self, "terminology_manager")
                and self.terminology_manager is not None
                and hasattr(self.terminology_manager, "get_term_translation")
                and callable(
                    getattr(self.terminology_manager, "get_term_translation")
                )
            ):
                try:
                    translated_term = (
                        self.terminology_manager.get_term_translation(
                            original_term
                        )
                    )
                    if translated_term:
                        result = result.replace(placeholder, translated_term)
                    else:
                        result = result.replace(placeholder, original_term)
                except Exception as e:
                    self.logger.warning(f"获取术语翻译时出错: {e}")
                    result = result.replace(placeholder, original_term)
            else:
                result = result.replace(placeholder, original_term)

        # 应用名称一致性修复
        if (
            hasattr(self, "terminology_manager")
            and self.terminology_manager is not None
            and hasattr(self.terminology_manager, "apply_name_consistency")
            and callable(
                getattr(self.terminology_manager, "apply_name_consistency")
            )
        ):
            try:
                result = self.terminology_manager.apply_name_consistency(
                    result
                )
            except Exception as e:
                self.logger.warning(f"应用名称一致性时出错: {e}")

        return result

        # 安全地调用 terminology_manager 方法
        if (
            hasattr(self, "terminology_manager")
            and self.terminology_manager is not None
            and hasattr(self.terminology_manager, "apply_name_consistency")
            and callable(
                getattr(self.terminology_manager, "apply_name_consistency")
            )
        ):
            try:
                translation = self.terminology_manager.apply_name_consistency(
                    translation
                )
            except Exception as e:
                self.logger.warning(f"应用名称一致性时出错: {e}")

    def _is_simple_invalid(self, translation: str, original: str) -> bool:
        """简化的质量检测"""
        if not translation or not translation.strip():
            return True

        # 基本检查：是否与原文相同
        if translation.strip() == original.strip():
            return True

        # 检查是否包含过多英文（超过50%）
        import re

        english_chars = len(re.findall(r"[a-zA-Z]", translation))
        total_chars = len(translation.replace(" ", ""))

        if total_chars > 0 and english_chars / total_chars > 0.5:
            return True

        return False

    def _is_symbolic_line(self, text: str) -> bool:
        """
        判断一行是否仅为音乐符号/声效标签/标点符号等，不包含实际词语。
        """
        import re
        if text is None:
            return True
        t = str(text).strip()
        if not t:
            return True

        # 去掉常见的斜体标签
        t = re.sub(r'</?i>', '', t, flags=re.IGNORECASE).strip()

        # 仅音乐符号/标点符号
        if re.fullmatch(r'[♪♩♫♬\s\.\,\-\—\·\…\!\?\:\;\(\)\[\]\{\}<>～~·、，。！？：；“”"\'—-]+', t):
            return True

        # [music]/[音乐]/(music)/(音乐) 等声效标签
        if re.fullmatch(r'[\[\(\{<]\s*[^>\]\)\}]{0,32}?(music|musical|song|applause|laugh|bgm|sfx|sound|音乐|歌声|掌声|笑声|背景音乐|音效)\s*[\]\)\}>]', t, flags=re.IGNORECASE):
            return True

        # 不包含任何字母/汉字/数字，也视为符号行
        if not re.search(r'[A-Za-z0-9\u4e00-\u9fff]', t):
            return True

        return False

    def _is_music_line(self, text: str) -> bool:
        """
        判断一行是否为音乐/歌词内容
        """
        import re
        if not text:
            return False
            
        t = str(text).strip()
        # 去掉斜体标签
        t = re.sub(r'</?i>', '', t, flags=re.IGNORECASE).strip()
        
        # 检查是否包含音乐符号
        if re.search(r'[♪♩♫♬]', t):
            return True
            
        # 检查是否为音乐相关标签
        if re.search(r'[\[\(\{<]\s*(music|musical|song|singing|bgm|音乐|歌声|歌曲|演唱)\s*[\]\)\}>]', t, flags=re.IGNORECASE):
            return True
            
        # 检查是否为重复的歌词模式（常见于歌曲中）
        if re.search(r'\b(\w+)\s+\1\b', t, flags=re.IGNORECASE):  # 重复词汇
            return True
            
        # 检查是否包含韵律模式（如 "la la la", "oh oh oh"）
        if re.search(r'\b(la|ah|oh|na|da|hey|yo)\s+(la|ah|oh|na|da|hey|yo)', t, flags=re.IGNORECASE):
            return True
            
        return False

    def _is_invalid_translation(self, translation: str, original: str) -> bool:
        """检测无效翻译"""
        if not translation or not translation.strip():
            self.logger.debug(f"翻译无效: 空翻译结果")
            return True

        # 音乐符号不应被视为无效翻译
        music_symbols = ["♪", "♫", "♬", "♩", "♭", "♯"]
        if any(symbol in original for symbol in music_symbols):
            return False

        # 括号内的人名或声音描述不应被视为无效
        if re.match(r"^\[.*?\]$", original.strip()):
            return False

        # 检查是否只包含标点符号和空格（排除音乐符号）
        clean_translation = translation
        for symbol in music_symbols:
            clean_translation = clean_translation.replace(symbol, "")

        # 修复：正确转义方括号
        if re.match(
            r'^[\s!"#$%&\'()*+,-./:;<=>?@\[\\\]^_`{|}~，。！？；：""'
            "（）【】《》、]*$",
            clean_translation,
        ):
            return True

        # 检查是否与原文完全相同（可能翻译失败）
        if translation.strip() == original.strip():
            # 对于非常短的文本（如单词、感叹词），允许保持原文
            if len(original.strip()) <= 3 or original.strip().lower() in ['no', 'ok', 'yes', 'ah', 'oh', 'eh', 'mm', 'hmm']:
                return False
            # 对于可能是专有名词或外语的内容，也允许保持原文
            if re.match(r'^[A-Z][a-z]*$', original.strip()) or len(original.strip().split()) == 1:
                return False
            # 对于短的外语短语（少于15个字符且少于4个单词），允许保持原文
            if len(original.strip()) <= 15 and len(original.strip().split()) <= 3:
                return False
            self.logger.debug(f"翻译无效: 译文与原文相同 - '{translation.strip()}'")
            return True

        # 严格检查中英文混杂问题
        # 移除：删除重复的import re语句

        # 检查是否包含明显的英文单词（排除专有名词）
        english_words = re.findall(r"\b[a-zA-Z]{2,}\b", translation)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", translation)

        # 如果同时包含英文单词和中文字符，且英文单词超过5个，则认为是混杂翻译
        if len(english_words) > 5 and len(chinese_chars) > 0:
            # 检查是否包含常见的混杂模式
            mixed_patterns = [
                r"[a-zA-Z]+\s*[\u4e00-\u9fff]+\s*[a-zA-Z]+\s*[\u4e00-\u9fff]+",  # 复杂混杂模式
                # 只检查明显的错误模式
                r"\b(I\'m|we\'re|let\'s|what\'s)\b.*[\u4e00-\u9fff].*\b(begin|plan|status|control)\b",
            ]

            for pattern in mixed_patterns:
                if re.search(pattern, translation, re.IGNORECASE):
                    return True

        # 检查是否包含过多英文（超过70%），但排除专有名词和短句
        english_chars = len(re.findall(r"[a-zA-Z]", translation))
        total_chars = len(translation.replace(" ", ""))
        if total_chars > 0 and english_chars / total_chars > 0.7:  # 提高阈值到70%
            # 如果是括号内容、包含人名、短句子，或者原文本身就是外语，则不判定为无效
            original_english_ratio = len(re.findall(r"[a-zA-Z]", original)) / max(1, len(original.replace(" ", "")))
            if not (
                re.search(r"\[.*?\]", translation)
                or len(translation.split()) <= 5
                or len(translation) <= 30  # 短句子更宽松
                or original_english_ratio > 0.5  # 原文本身就是外语
            ):
                self.logger.debug(f"翻译包含过多英文被判定为无效: '{translation}' (英文字符: {english_chars}/{total_chars} = {english_chars/total_chars:.1%})")
                return True

        # 检查是否包含明显的翻译错误标记
        error_patterns = [
            r"提供.*?translate",
            r"I\'m begin",
            r"想要.*?translate",
            r"begin.*?here",
            r"following.*?status",
        ]

        for pattern in error_patterns:
            if re.search(pattern, translation, re.IGNORECASE):
                return True

        return False

    def _call_model_api(
        self, prompt: str, retries: Optional[int] = None
    ) -> Optional[str]:
        """调用模型API进行翻译（支持多个服务）"""
        if retries is None:
            retries = self.config.TRANSLATION_RETRIES

        for attempt in range(retries):
            try:
                self.logger.debug(
                    f"正在调用模型API (尝试 {attempt + 1}/{retries})..."
                )

                self.logger.debug(f"发送到API的提示词: {prompt[:200]}...")
                
                # 使用模型服务管理器生成文本
                result, service_used = self.service_manager.generate_text(prompt)
                
                self.logger.debug(
                    f"API 响应成功，使用服务: {service_used}, 返回内容长度: {len(result)}, 内容: '{result[:100]}...'"
                )

                if not result.strip():
                    self.logger.warning("API 返回了空的翻译结果")
                    return None

                return result

            except Exception as e:
                self.logger.warning(
                    f"调用模型API失败 (尝试 {attempt + 1}/{retries}): {e}"
                )

            if attempt == retries - 1:
                self.logger.error("所有重试都失败了")

        return None

    def set_movie_context(self, context_data: dict) -> bool:
        """设置电影上下文信息"""
        try:
            self.movie_context.title = context_data.get("title", "")
            self.movie_context.year = context_data.get("year", "")
            self.movie_context.genre = context_data.get("genre", [])
            self.movie_context.plot = context_data.get("plot", "")
            self.movie_context.characters = context_data.get("characters", {})
            self.movie_context.terminology = context_data.get(
                "terminology", {}
            )
            return True
        except Exception as e:
            self.logger.error(f"设置电影上下文失败: {e}")
            return False

    def _get_type_specific_guide(self, types: List[str]) -> str:
        """根据类型（影片类型或场景类型）获取特定的翻译指导"""
        return PromptTemplates.get_type_specific_guide(types)

    def _preprocess_special_content(self, text: str) -> str:
        """预处理特殊内容"""

        return text

    def _postprocess_special_content(self, translation: str) -> str:
        """后处理特殊内容"""
        result = translation
        # 额外清理：移除可能残留的中文音乐标签
        result = re.sub(r"\[音乐相关.*?\]", "[music]", result)
        result = re.sub(r"\[音乐.*?\]", "[music]", result)

        return result

    def _clean_subtitle_text(self, text: str) -> str:
        """清理字幕文本，移除HTML标签和多余空格"""
        # 使用format_converter的清理方法
        from utils.format_converter import FormatConverter

        converter = FormatConverter()

        # 使用ASS文本清理方法（它包含了HTML标签清理）
        cleaned_text = converter._clean_ass_text(text)

        # 更智能的清理逻辑
        import re

        # 只移除特定的无用标签，保留需要翻译的内容
        patterns_to_remove = [
            r"\[\s*\]",  # 空方括号
        ]

        for pattern in patterns_to_remove:
            cleaned_text = re.sub(
                pattern, "", cleaned_text, flags=re.IGNORECASE
            )

        # 清理零宽字符
        cleaned_text = re.sub(r"[\u200b-\u200d\ufeff]", "", cleaned_text)

        cleaned_text = re.sub(r"[.,]\s*$", "", cleaned_text)

        return cleaned_text.strip()
    
    def _translate_subtitles_batch(self, subtitles, target_language, subtitle_to_scene_types, progress_callback=None):
        """批量翻译字幕以提升性能"""
        translated_subtitles = []
        batch_size = self.config.BATCH_SIZE  # 使用配置中的批量大小
        
        # 预处理所有字幕，分离空字幕和有效字幕
        processed_subtitles = []
        for i, subtitle in enumerate(subtitles):
            raw_text = subtitle.content.strip()
            original_text = self._clean_subtitle_text(raw_text)
            if not original_text or original_text.isspace():
                processed_subtitles.append({
                    'index': i,
                    'subtitle': subtitle,
                    'raw_text': raw_text,
                    'original_text': '',
                    'is_empty': True
                })
            else:
                processed_subtitles.append({
                    'index': i,
                    'subtitle': subtitle,
                    'raw_text': raw_text,
                    'original_text': original_text,
                    'is_empty': False,
                    'scene_types': subtitle_to_scene_types.get(i, [])
                })
        
        # 检测整体语言（只检测一次）
        all_text = ' '.join([item['original_text'] for item in processed_subtitles if not item['is_empty']])
        detected_lang = self._detect_language(all_text) if all_text else 'english'
        self.logger.info(f"🌐 检测到整体语言: {detected_lang}")
        
        print("\n🔄 开始批量翻译字幕...")
        
        with tqdm(total=len(subtitles), desc="翻译字幕", unit="条", ncols=80) as pbar:
            i = 0
            while i < len(processed_subtitles):
                # 收集当前批次的有效字幕
                batch_items = []
                batch_start = i
                
                while i < len(processed_subtitles) and len(batch_items) < batch_size:
                    item = processed_subtitles[i]
                    if item['is_empty']:
                        # 空字幕直接处理
                        item['subtitle'].content = ''
                        translated_subtitles.append(item['subtitle'])
                        pbar.update(1)
                        if progress_callback:
                            progress = (i + 1) / len(processed_subtitles) * 100
                            progress_callback(progress, i + 1, len(processed_subtitles))
                    else:
                        batch_items.append(item)
                    i += 1
                
                if not batch_items:
                    continue
                
                # 批量翻译当前批次
                if len(batch_items) == 1:
                    # 单条字幕也使用批量翻译逻辑，保持一致性
                    item = batch_items[0]
                    
                    # 根据检测到的语言选择翻译方法
                    if detected_lang == 'english':
                        # 对于英文字幕，直接使用原文，不进行翻译
                        self._handle_translation_result(item, None, detected_lang, target_language)
                    elif detected_lang == 'chinese':
                        # 对于中文字幕，使用批量翻译逻辑
                        batch_translations = self._translate_batch([item], target_language)
                        translation = batch_translations[0] if batch_translations and batch_translations[0] else None
                        self._handle_translation_result(item, translation, detected_lang, target_language)
                    else:
                        # 对于非英文非中文语言，使用双语翻译
                        dual_translation = self._translate_text_dual(item['original_text'], detected_lang)
                        self._handle_translation_result(item, dual_translation, detected_lang, target_language)
                    
                    translated_subtitles.append(item['subtitle'])
                else:
                    # 多条字幕使用批量翻译
                    if detected_lang == 'english':
                        # 对于英文字幕，直接使用原文，不进行翻译
                        for item in batch_items:
                            self._handle_translation_result(item, None, detected_lang, target_language)
                            translated_subtitles.append(item['subtitle'])
                    elif detected_lang == 'chinese':
                        # 对于中文字幕，使用原有批量翻译逻辑
                        batch_translations = self._translate_batch(batch_items, target_language)
                        
                        for j, item in enumerate(batch_items):
                            translation = batch_translations[j] if j < len(batch_translations) and batch_translations[j] else None
                            self._handle_translation_result(item, translation, detected_lang, target_language)
                            translated_subtitles.append(item['subtitle'])
                    else:
                        # 对于非英文非中文语言，逐条进行双语翻译（批量双语翻译较复杂，暂时逐条处理）
                        for item in batch_items:
                            dual_translation = self._translate_text_dual(item['original_text'], detected_lang)
                            self._handle_translation_result(item, dual_translation, detected_lang, target_language)
                            translated_subtitles.append(item['subtitle'])
                
                # 更新进度条
                pbar.update(len(batch_items))
                if progress_callback:
                    progress = min(i, len(processed_subtitles)) / len(processed_subtitles) * 100
                    progress_callback(progress, min(i, len(processed_subtitles)), len(processed_subtitles))
        
        return translated_subtitles
    
    def _create_bilingual_content(self, translation, original, detected_lang):
        """创建双语字幕内容"""
        if detected_lang == "english":
            # 对于英文原文，如果有翻译则显示翻译+原文，如果没有翻译则只显示原文
            if translation and translation.strip():
                return f"{translation}\n{original}"
            else:
                return original
        elif detected_lang == "chinese":
            return f"{original}\n{translation}"
        else:
            # 对于其他语言，需要同时翻译成中文和英文
            # translation参数现在应该包含中文和英文两个翻译
            if isinstance(translation, dict) and 'chinese' in translation and 'english' in translation:
                return f"{translation['chinese']}\n{translation['english']}"
            else:
                # 兼容旧格式，如果只有中文翻译，则中文在上，原文在下
                return f"{translation}\n{original}"
    
    def _handle_translation_result(self, item, translation, detected_lang, target_language):
        """统一处理翻译结果，包括成功和失败的情况"""
        use_original_raw = (detected_lang == 'english' and getattr(self.config, 'PRESERVE_ORIGINAL_ENGLISH', True))
        original_for_output = item.get('raw_text', item.get('original_text', '')) if use_original_raw else item.get('original_text', '')
        if translation:
            if isinstance(translation, dict):
                # 双语翻译结果
                bilingual_content = self._create_bilingual_content(translation, original_for_output, detected_lang)
            else:
                # 单语翻译结果
                cleaned_translation = self._clean_subtitle_text(translation.strip())
                bilingual_content = self._create_bilingual_content(cleaned_translation, original_for_output, detected_lang)
            item['subtitle'].content = bilingual_content
        else:
            # 翻译失败或英文原文，使用原文
            fallback_original = original_for_output or item.get('original_text', '')
            if detected_lang == 'english':
                # 对于英文原文，直接创建双语内容，不添加翻译失败提示
                bilingual_content = self._create_bilingual_content("", fallback_original, detected_lang)
                item['subtitle'].content = bilingual_content
            else:
                # 对于其他语言翻译失败，添加提示
                item['subtitle'].content = f"{fallback_original}  # 翻译失败，可能需要人工校对"
    
    def _translate_batch(self, batch_items, target_language):
        """批量翻译多条字幕"""
        # 构建批量翻译提示词
        batch_text = "\n".join([f"{i+1}. {item['original_text']}" for i, item in enumerate(batch_items)])
        
        # 收集批次中的场景类型
        all_scene_types = set()
        for item in batch_items:
            if item.get('scene_types'):
                all_scene_types.update(item['scene_types'])
        
        scene_types_list = list(all_scene_types) if all_scene_types else None
        
        # 使用包含场景信息的提示词构建方法
        if scene_types_list:
            # 获取缩写处理指导
            abbreviation_guide = self._get_abbreviation_guide(scene_types_list)
            prompt = self._build_translation_prompt(
                batch_text,
                scene_types=scene_types_list,
                abbreviation_rules=abbreviation_guide,
                batch_mode=True
            )
        else:
            prompt = PromptTemplates.get_batch_translation_prompt(target_language, batch_text)
        
        try:
            response = self._call_model_api(prompt)
            if response:
                # 解析批量翻译结果
                lines = response.strip().split('\n')
                translations = []
                
                for line in lines:
                    # 移除编号前缀
                    import re
                    match = re.match(r'^\d+\.\s*(.+)$', line.strip())
                    if match:
                        translations.append(match.group(1))
                    elif line.strip() and not re.match(r'^\d+\.$', line.strip()):
                        translations.append(line.strip())
                
                # 确保翻译数量匹配
                while len(translations) < len(batch_items):
                    translations.append(None)
                
                return translations[:len(batch_items)]
        except Exception as e:
            self.logger.warning(f"批量翻译失败: {e}，回退到单条翻译")
        
        # 批量翻译失败，回退到简单单条翻译
        translations = []
        for item in batch_items:
            try:
                # 使用简单翻译提示词进行单条翻译
                simple_prompt = PromptTemplates.get_simple_translation_prompt(item['original_text'])
                response = self._call_model_api(simple_prompt)
                if response:
                    cleaned = self._post_process_translation(response.strip(), item['original_text'])
                    translations.append(cleaned)
                else:
                    translations.append(None)
            except Exception as e:
                self.logger.warning(f"单条翻译失败: {e}")
                translations.append(None)
        
        return translations
