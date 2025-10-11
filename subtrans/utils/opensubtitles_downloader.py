#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

import requests

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class SubtitleSearchResult:
    """字幕搜索结果"""

    id: str
    language: str
    filename: str
    download_url: str
    rating: float = 0.0
    download_count: int = 0
    file_size: int = 0
    encoding: str = "utf-8"
    format: str = "srt"


class OpenSubtitlesDownloader:
    """OpenSubtitles字幕下载器"""

    def __init__(self, api_key: str = "", user_agent: str = "subtrans v2.0"):
        self.api_key = api_key
        self.user_agent = user_agent
        self.base_url = "https://api.opensubtitles.com/api/v1"

        # 配置HTTP会话
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": self.user_agent, "Accept": "application/json"}
        )

        if self.api_key:
            self.session.headers["Api-Key"] = self.api_key

        # 配置重试策略
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def calculate_file_hash(self, file_path: str) -> Optional[str]:
        """计算视频文件的OpenSubtitles哈希值"""
        try:
            longlongformat = "<q"  # little-endian long long
            bytesize = struct.calcsize(longlongformat)

            with open(file_path, "rb") as f:
                filesize = os.path.getsize(file_path)

                if filesize < 65536 * 2:
                    logger.warning(f"文件太小，无法计算哈希: {file_path}")
                    return None

                # 读取文件开头和结尾的64KB
                f.seek(0)
                head = f.read(65536)

                f.seek(-65536, 2)
                tail = f.read(65536)

                # 计算哈希
                hash_value = filesize

                for i in range(0, 65536, bytesize):
                    if i + bytesize <= len(head):
                        hash_value += struct.unpack(
                            longlongformat, head[i : i + bytesize]
                        )[0]
                    if i + bytesize <= len(tail):
                        hash_value += struct.unpack(
                            longlongformat, tail[i : i + bytesize]
                        )[0]

                # 确保哈希值为正数并转换为16进制
                hash_value = hash_value & 0xFFFFFFFFFFFFFFFF
                return f"{hash_value:016x}"

        except Exception as e:
            logger.error(f"计算文件哈希失败 {file_path}: {e}")
            return None

    def search_subtitles(
        self,
        video_path: Optional[str] = None,
        movie_hash: Optional[str] = None,
        file_size: Optional[int] = None,
        imdb_id: Optional[str] = None,
        query: Optional[str] = None,
        languages: Optional[List[str]] = None,
    ) -> List[SubtitleSearchResult]:
        """搜索字幕"""
        if languages is None:
            languages = ["en", "zh"]

        # 构建搜索参数
        params = {
            "languages": ",".join(languages),
            "order_by": "download_count",
            "order_direction": "desc",
        }

        # 添加搜索条件
        if video_path and not movie_hash:
            movie_hash = self.calculate_file_hash(video_path)
            if movie_hash and video_path:  # 确保 video_path 不为 None
                file_size = os.path.getsize(video_path)

        # 在使用 movie_hash 之前添加检查
        if movie_hash and file_size:
            params["moviehash"] = movie_hash
            params["moviebytesize"] = str(file_size)
            logger.info(f"使用文件哈希搜索: {movie_hash}")

        if imdb_id:
            params["imdb_id"] = imdb_id
            logger.info(f"使用IMDB ID搜索: {imdb_id}")

        if query:
            params["query"] = query
            logger.info(f"使用关键词搜索: {query}")

        try:
            response = self.session.get(
                f"{self.base_url}/subtitles", params=params, timeout=30
            )
            response.raise_for_status()

            data = response.json()
            results = []

            for item in data.get("data", []):
                attributes = item.get("attributes", {})
                files = attributes.get("files", [])

                if not files:
                    continue

                file_info = files[0]  # 取第一个文件

                result = SubtitleSearchResult(
                    id=str(item.get("id", "")),
                    language=attributes.get("language", "unknown"),
                    filename=file_info.get("file_name", ""),
                    download_url=attributes.get("url", ""),
                    rating=float(attributes.get("ratings", 0)),
                    download_count=int(attributes.get("download_count", 0)),
                    file_size=int(file_info.get("file_size", 0)),
                )

                results.append(result)

            logger.info(f"找到 {len(results)} 个字幕结果")
            return results

        except requests.exceptions.RequestException as e:
            logger.error(f"搜索字幕失败: {e}")
            return []
        except Exception as e:
            logger.error(f"解析搜索结果失败: {e}")
            return []

    def download_subtitle(
        self, result: SubtitleSearchResult, output_path: Union[str, Path]
    ) -> Optional[str]:
        """下载字幕文件"""
        try:
            # 获取下载链接
            download_url = self._get_download_url(result.id)
            if not download_url:
                logger.error(f"无法获取下载链接: {result.id}")
                return None

            # 下载文件
            response = self.session.get(download_url, timeout=60)
            response.raise_for_status()

            # 确保输出目录存在
            output_path_obj = Path(output_path)  # 转换为 Path 对象
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)

            # 检查是否为ZIP文件
            if response.headers.get("content-type", "").startswith(
                "application/zip"
            ) or result.filename.endswith(".zip"):
                return self._extract_subtitle_from_zip(
                    response.content, output_path_obj
                )
            else:
                # 直接保存字幕文件
                with open(output_path_obj, "wb") as f:
                    f.write(response.content)

                logger.info(f"字幕下载成功: {output_path_obj}")
                return str(output_path_obj)

        except Exception as e:
            logger.error(f"下载字幕失败 {result.filename}: {e}")
            return None

    def _get_download_url(self, subtitle_id: str) -> Optional[str]:
        """获取字幕下载链接"""
        try:
            response = self.session.post(
                f"{self.base_url}/download",
                json={"file_id": int(subtitle_id)},
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            return data.get("link")

        except Exception as e:
            logger.error(f"获取下载链接失败: {e}")
            return None

    def _extract_subtitle_from_zip(
        self, zip_content: bytes, output_path: Path
    ) -> Optional[str]:
        """从ZIP文件中提取字幕"""
        try:
            with tempfile.NamedTemporaryFile() as temp_zip:
                temp_zip.write(zip_content)
                temp_zip.flush()

                with zipfile.ZipFile(temp_zip.name, "r") as zip_file:
                    # 查找字幕文件
                    subtitle_files = [
                        name
                        for name in zip_file.namelist()
                        if name.lower().endswith(
                            (".srt", ".ass", ".vtt", ".sub")
                        )
                    ]

                    if not subtitle_files:
                        logger.warning("ZIP文件中未找到字幕文件")
                        return None

                    # 选择第一个字幕文件
                    subtitle_file = subtitle_files[0]

                    # 提取并保存
                    with zip_file.open(subtitle_file) as source:
                        content = source.read()

                        # 更新输出文件扩展名
                        subtitle_ext = Path(subtitle_file).suffix
                        final_output_path = output_path.with_suffix(
                            subtitle_ext
                        )

                        with open(final_output_path, "wb") as target:
                            target.write(content)

                        logger.info(f"从ZIP提取字幕成功: {final_output_path}")
                        return str(final_output_path)

        except Exception as e:
            logger.error(f"提取ZIP字幕失败: {e}")
            return None

    def search_and_download_best(
        self,
        video_path: str,
        output_dir: str,
        languages: Optional[List[str]] = None,
    ) -> Optional[str]:
        """搜索并下载最佳字幕"""
        if languages is None:
            languages = ["en", "zh"]  # 提供默认值

        # 搜索字幕
        results = self.search_subtitles(
            video_path=video_path, languages=languages
        )

        if not results:
            logger.warning(f"未找到字幕: {video_path}")
            return None

        # 选择最佳字幕（按下载次数排序）
        best_result = max(results, key=lambda x: x.download_count)

        # 生成输出文件名
        video_name = Path(video_path).stem
        output_filename = f"{video_name}.{best_result.language}.srt"
        output_path = Path(output_dir) / output_filename

        # 下载字幕
        downloaded_path = self.download_subtitle(best_result, str(output_path))

        if downloaded_path:
            logger.info(f"最佳字幕下载成功: {downloaded_path}")

        return downloaded_path
