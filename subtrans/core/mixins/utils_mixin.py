#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具方法 Mixin - 包含文件路径生成、编码检测等通用工具方法
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple, Protocol, runtime_checkable, Any

import chardet


@runtime_checkable
class _UtilsDeps(Protocol):
    """Protocol: 声明 UtilsMixin 运行时依赖的属性与方法"""
    logger: Any


class UtilsMixin:
    """工具方法模块 - 文件路径生成、编码检测等通用功能"""

    # 由主类提供的依赖（用于类型检查）
    logger: Any

    def _read_subtitle_file_with_encoding_detection(
        self: "_UtilsDeps", file_path: str
    ) -> Tuple[str, str]:
        """使用编码检测读取字幕文件

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

    def _generate_base_name(self, file_path: str) -> str:
        """生成统一的基础文件名，确保与视频文件名一致"""
        path_obj = Path(file_path)
        base_name = path_obj.stem

        # 清理各种不规整的文件名模式
        # 1. 去掉语言代码（如 .en, .zh, .fr 等）
        language_codes = [
            ".en",
            ".zh",
            ".fr",
            ".de",
            ".es",
            ".it",
            ".ja",
            ".ko",
            ".pt",
            ".ru",
            ".eng",
            ".english",
        ]
        for lang_code in language_codes:
            if base_name.endswith(lang_code):
                base_name = base_name[: -len(lang_code)]
                break

        # 2. 去掉字幕类型标识符（如 .emb, .asr, .ai 等）
        subtitle_type_codes = [".emb", ".asr", ".ai", ".temp"]
        for type_code in subtitle_type_codes:
            if base_name.endswith(type_code):
                base_name = base_name[: -len(type_code)]
                break

        # 3. 去掉字幕提取时产生的标识符
        base_name = re.sub(r"_subtitle_\d+$", "", base_name)

        # 4. 去掉临时文件标识符
        base_name = re.sub(r"\.temp$", "", base_name)
        base_name = re.sub(r"_whisper_.*$", "", base_name)

        # 5. 去掉其他可能的字幕标识符
        base_name = re.sub(r"_sub\d*$", "", base_name)
        base_name = re.sub(r"_track\d*$", "", base_name)

        # 6. 新增：去掉随机字符串（如 _pld9uigv, _4qh0fooe 等）
        # 匹配下划线后跟8个字母数字字符的模式
        base_name = re.sub(r"_[a-zA-Z0-9]{8}$", "", base_name)

        # 7. 去掉音频文件后缀
        base_name = base_name.replace("_audio", "")

        return base_name

    def _generate_temp_subtitle_path(
        self, video_path: str, tag: str
    ) -> str:
        """生成临时字幕文件路径，确保与最终文件名一致"""
        base_name = self._generate_base_name(video_path)
        video_dir = Path(video_path).parent
        return str(video_dir / f"{base_name}.{tag}.srt")

    def _generate_final_subtitle_path(
        self,
        video_path: str,
        tag: str = "ai",
        output_dir: Optional[str] = None,
    ) -> str:
        """生成最终字幕文件路径

        Args:
            video_path: 视频文件路径
            tag: 字幕类型 ('ai' 为翻译字幕, 'emb' 为内嵌字幕, 'asr' 为音轨转录)
            output_dir: 输出目录
        """
        base_name = self._generate_base_name(video_path)

        if output_dir:
            output_dir_obj = Path(output_dir)
            output_dir_obj.mkdir(parents=True, exist_ok=True)
            output_file = output_dir_obj / f"{base_name}.{tag}.srt"
        else:
            video_dir = Path(video_path).parent
            output_file = video_dir / f"{base_name}.{tag}.srt"

        return str(output_file)

    def _generate_output_path(
        self, input_path: str, output_dir: Optional[str] = None
    ) -> str:
        """生成输出文件路径，使用 .ai.srt 扩展名"""
        return self._generate_final_subtitle_path(input_path, "ai", output_dir)