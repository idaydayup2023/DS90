#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMDB信息获取器
获取电影或电视剧的IMDB信息，用于增强翻译上下文
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from utils.logger import get_logger

logger = get_logger(__name__)


class IMDBInfoFetcher:
    """IMDB信息获取器"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.omdb_api_url = "http://www.omdbapi.com/"

    def get_imdb_info_from_nfo(
        self, video_path: str
    ) -> Optional[Dict[str, Any]]:
        """从NFO文件中获取IMDB信息"""
        # 1. 查找同名NFO文件
        nfo_path = self._find_nfo_file(video_path)
        if not nfo_path:
            logger.debug(f"未找到NFO文件: {video_path}")
            return None

        # 2. 从NFO文件中提取IMDB ID
        imdb_id = self._extract_imdb_id_from_nfo(nfo_path)
        if not imdb_id:
            logger.debug(f"未在NFO文件中找到IMDB ID: {nfo_path}")
            return None

        # 3. 获取IMDB信息
        return self.get_imdb_info_by_id(imdb_id)

    def get_imdb_info_by_title(
        self, title: str, year: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """通过标题获取IMDB信息"""
        if not self.api_key:
            logger.warning("未配置OMDB API密钥，无法通过标题获取IMDB信息")
            return None

        params = {
            "apikey": self.api_key,
            "t": title,
            "plot": "full",
            "r": "json",
        }

        if year:
            params["y"] = year

        try:
            response = requests.get(
                self.omdb_api_url, params=params, timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if data.get("Response") == "True":
                logger.info(f"通过标题获取IMDB信息成功: {title}")
                return data
            else:
                logger.warning(
                    f"通过标题获取IMDB信息失败: {data.get('Error', '未知错误')}"
                )
                return None

        except Exception as e:
            logger.error(f"获取IMDB信息失败: {e}")
            return None

    def get_imdb_info_by_id(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        """通过IMDB ID获取信息"""
        if not self.api_key:
            logger.warning("未配置OMDB API密钥，无法通过ID获取IMDB信息")
            return None

        # 确保ID格式正确
        if not imdb_id.startswith("tt"):
            imdb_id = f"tt{imdb_id}"

        params = {
            "apikey": self.api_key,
            "i": imdb_id,
            "plot": "full",
            "r": "json",
        }

        try:
            response = requests.get(
                self.omdb_api_url, params=params, timeout=10
            )
            response.raise_for_status()
            data = response.json()

            if data.get("Response") == "True":
                logger.info(f"通过ID获取IMDB信息成功: {imdb_id}")
                return data
            else:
                logger.warning(
                    f"通过ID获取IMDB信息失败: {data.get('Error', '未知错误')}"
                )
                return None

        except Exception as e:
            logger.error(f"获取IMDB信息失败: {e}")
            return None

    def extract_imdb_info_from_subtitles(
        self, subtitle_content: str
    ) -> Optional[Dict[str, Any]]:
        """从字幕内容中提取可能的IMDB信息"""
        # 这个方法需要更复杂的NLP处理，这里只是一个简单的实现
        # 可以使用AI模型来分析字幕内容，提取电影信息

        # 尝试从字幕中提取可能的电影名称和年份
        title_match = re.search(
            r"(?:presents|presents:)\s+([\w\s]+)", subtitle_content
        )
        year_match = re.search(r"(19|20)\d{2}", subtitle_content)

        title = title_match.group(1).strip() if title_match else None
        year = year_match.group(0) if year_match else None

        if title:
            return self.get_imdb_info_by_title(title, year)

        return None

    def _find_nfo_file(self, file_path: str) -> Optional[str]:
        """查找与视频文件同名的NFO文件"""
        file_path_obj = Path(file_path)
        file_dir = file_path_obj.parent
        file_stem = file_path_obj.stem

        # 处理字幕文件路径，提取可能的视频文件名
        base_name = file_stem

        # 如果是字幕文件，处理可能的语言代码
        if file_path.endswith((".srt", ".ass", ".ssa")):
            # 处理常见的语言代码模式，如 .en.srt, .zh.srt 等
            lang_patterns = [
                ".en.",
                ".zh.",
                ".ja.",
                ".ko.",
                ".fr.",
                ".de.",
                ".es.",
                ".ru.",
            ]

            for pattern in lang_patterns:
                if pattern in file_path:
                    # 移除语言代码部分，获取基本文件名
                    base_name = file_path_obj.name.split(pattern)[0]
                    break

            # 如果文件名包含多个点，可能是使用了其他格式的语言代码
            if "." in file_stem and base_name == file_stem:
                # 尝试移除最后一个扩展名部分（可能是语言代码）
                base_name = file_stem.rsplit(".", 1)[0]

        # 只查找与处理后的视频文件名完全匹配的NFO文件
        nfo_path = file_dir / f"{base_name}.nfo"
        if nfo_path.exists():
            logger.debug(f"找到NFO文件(完全匹配): {nfo_path}")
            return str(nfo_path)

        # 修改日志输出，显示尝试查找的NFO文件路径
        logger.debug(f"未找到NFO文件: {nfo_path}")
        return None

    def _extract_imdb_id_from_nfo(self, nfo_path: str) -> Optional[str]:
        """从NFO文件中提取IMDB ID"""
        try:
            with open(nfo_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # 查找IMDB链接或ID
            imdb_patterns = [
                r"imdb\.com/title/(tt\d+)",  # IMDB链接
                r"<id>(tt\d+)</id>",  # XML格式
                r'imdb id="?(tt\d+)"?',  # 其他可能的格式
                r'imdb[\s:=]+"?(tt\d+)"?',  # 其他可能的格式
            ]

            for pattern in imdb_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    return match.group(1)

            return None

        except Exception as e:
            logger.error(f"读取NFO文件失败: {e}")
            return None

    def extract_imdb_id_from_remote_nfo(
        self, ftp_handler, remote_nfo_path: str
    ) -> Optional[str]:
        """从远程NFO文件中提取IMDB ID"""
        try:
            # 读取远程NFO文件内容
            content = ftp_handler.read_file_content(remote_nfo_path)
            if not content:
                logger.debug(f"无法读取远程NFO文件内容: {remote_nfo_path}")
                return None

            # 查找IMDB链接或ID
            imdb_patterns = [
                r"imdb\.com/title/(tt\d+)",  # IMDB链接
                r"<id>(tt\d+)</id>",  # XML格式
                r'imdb id="?(tt\d+)"?',  # 其他可能的格式
                r'imdb[\s:=]+"?(tt\d+)"?',  # 其他可能的格式
            ]

            for pattern in imdb_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    logger.info(
                        f"从远程NFO文件中提取到IMDB ID: {match.group(1)}"
                    )
                    return match.group(1)

            logger.debug(f"未在远程NFO文件中找到IMDB ID: {remote_nfo_path}")
            return None

        except Exception as e:
            logger.error(f"从远程NFO文件提取IMDB ID失败: {e}")
            return None
