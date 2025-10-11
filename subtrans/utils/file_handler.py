#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import mimetypes
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

import chardet

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class FileInfo:
    """文件信息"""

    path: str
    name: str
    size: int
    extension: str
    mime_type: str
    encoding: Optional[str] = None
    created_time: float = 0.0
    modified_time: float = 0.0
    checksum: Optional[str] = None


class FileHandler:
    """统一文件处理器"""

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = Path(temp_dir) if temp_dir else Path.cwd() / "temp"
        self.temp_files = []  # 跟踪临时文件
        self.encoding_priority = [
            "utf-8",
            "utf-8-sig",
            "gbk",
            "gb2312",
            "big5",
            "latin1",
            "cp1252",
        ]

        # 支持的文件类型
        self.video_extensions = {
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".m4v",
        }
        self.subtitle_extensions = {
            ".srt",
            ".ass",
            ".ssa",
            ".vtt",
            ".sub",
            ".idx",
            ".sup",
        }
        self.audio_extensions = {
            ".mp3",
            ".wav",
            ".flac",
            ".aac",
            ".ogg",
            ".m4a",
        }
        self.archive_extensions = {
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".gz",
            ".bz2",
        }

        # 确保临时目录存在
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def __del__(self):
        """清理临时文件"""
        self.cleanup_temp_files()

    # ==================== 文件信息获取 ====================

    def get_file_info(self, file_path: Union[str, Path]) -> Optional[FileInfo]:
        """获取文件详细信息"""
        file_path = Path(file_path)

        if not file_path.exists():
            logger.error(f"文件不存在: {file_path}")
            return None

        try:
            stat = file_path.stat()
            mime_type, _ = mimetypes.guess_type(str(file_path))

            # 检测文本文件编码
            encoding = None
            if self.is_text_file(file_path):
                encoding = self.detect_encoding(file_path)

            return FileInfo(
                path=str(file_path.absolute()),
                name=file_path.name,
                size=stat.st_size,
                extension=file_path.suffix.lower(),
                mime_type=mime_type or "application/octet-stream",
                encoding=encoding,
                created_time=stat.st_ctime,
                modified_time=stat.st_mtime,
            )

        except Exception as e:
            logger.error(f"获取文件信息失败 {file_path}: {e}")
            return None

    def detect_encoding(
        self, file_path: Union[str, Path], sample_size: int = 8192
    ) -> Optional[str]:
        """检测文件编码"""
        file_path = Path(file_path)

        try:
            # 读取文件样本
            with open(file_path, "rb") as f:
                sample = f.read(sample_size)

            # 使用chardet检测
            result = chardet.detect(sample)
            detected_encoding = result.get("encoding")
            confidence = result.get("confidence", 0)

            logger.debug(
                f"编码检测结果: {detected_encoding} (置信度: {confidence:.2f})"
            )

            # 如果置信度太低，尝试常见编码
            if confidence < 0.7:
                for encoding in self.encoding_priority:
                    try:
                        with open(file_path, "r", encoding=encoding) as f:
                            f.read(1024)  # 尝试读取一部分
                        logger.debug(f"使用编码: {encoding}")
                        return encoding
                    except UnicodeDecodeError:
                        continue

            return detected_encoding

        except Exception as e:
            logger.warning(f"编码检测失败 {file_path}: {e}")
            return "utf-8"  # 默认编码

    def calculate_checksum(
        self, file_path: Union[str, Path], algorithm: str = "md5"
    ) -> Optional[str]:
        """计算文件校验和"""
        file_path = Path(file_path)

        if not file_path.exists():
            return None

        try:
            hash_obj = hashlib.new(algorithm)

            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hash_obj.update(chunk)

            return hash_obj.hexdigest()

        except Exception as e:
            logger.error(f"计算校验和失败 {file_path}: {e}")
            return None

    # ==================== 文件类型判断 ====================

    def is_video_file(self, file_path: Union[str, Path]) -> bool:
        """判断是否为视频文件"""
        return Path(file_path).suffix.lower() in self.video_extensions

    def is_subtitle_file(self, file_path: Union[str, Path]) -> bool:
        """判断是否为字幕文件"""
        return Path(file_path).suffix.lower() in self.subtitle_extensions

    def is_audio_file(self, file_path: Union[str, Path]) -> bool:
        """判断是否为音频文件"""
        return Path(file_path).suffix.lower() in self.audio_extensions

    def is_archive_file(self, file_path: Union[str, Path]) -> bool:
        """判断是否为压缩文件"""
        return Path(file_path).suffix.lower() in self.archive_extensions

    def is_text_file(self, file_path: Union[str, Path]) -> bool:
        """判断是否为文本文件"""
        file_path = Path(file_path)

        # 基于扩展名判断
        text_extensions = {
            ".txt",
            ".srt",
            ".ass",
            ".ssa",
            ".vtt",
            ".sub",
            ".log",
            ".cfg",
            ".ini",
        }
        if file_path.suffix.lower() in text_extensions:
            return True

        # 基于MIME类型判断
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type and mime_type.startswith("text/"):
            return True

        return False

    # ==================== 文件读写操作 ====================

    def read_text_file(
        self, file_path: Union[str, Path], encoding: Optional[str] = None
    ) -> Optional[str]:
        """读取文本文件"""
        file_path = Path(file_path)

        if not file_path.exists():
            logger.error(f"文件不存在: {file_path}")
            return None

        # 自动检测编码
        if encoding is None:
            encoding = self.detect_encoding(file_path)

        try:
            with open(
                file_path, "r", encoding=encoding, errors="replace"
            ) as f:
                content = f.read()
            logger.debug(f"读取文件成功: {file_path} (编码: {encoding})")
            return content

        except Exception as e:
            logger.error(f"读取文件失败 {file_path}: {e}")
            return None

    def write_text_file(
        self,
        file_path: Union[str, Path],
        content: str,
        encoding: str = "utf-8",
        backup: bool = True,
    ) -> bool:
        """写入文本文件"""
        file_path = Path(file_path)

        # 创建目录
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # 备份原文件
        if backup and file_path.exists():
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            try:
                shutil.copy2(file_path, backup_path)
                logger.debug(f"已备份原文件: {backup_path}")
            except Exception as e:
                logger.warning(f"备份文件失败: {e}")

        try:
            with open(file_path, "w", encoding=encoding, newline="\n") as f:
                f.write(content)
            logger.debug(f"写入文件成功: {file_path} (编码: {encoding})")
            return True

        except Exception as e:
            logger.error(f"写入文件失败 {file_path}: {e}")
            return False

    def copy_file(
        self,
        src_path: Union[str, Path],
        dst_path: Union[str, Path],
        preserve_metadata: bool = True,
    ) -> bool:
        """复制文件"""
        src_path = Path(src_path)
        dst_path = Path(dst_path)

        if not src_path.exists():
            logger.error(f"源文件不存在: {src_path}")
            return False

        # 创建目标目录
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if preserve_metadata:
                shutil.copy2(src_path, dst_path)
            else:
                shutil.copy(src_path, dst_path)

            logger.debug(f"复制文件成功: {src_path} -> {dst_path}")
            return True

        except Exception as e:
            logger.error(f"复制文件失败: {e}")
            return False

    def move_file(
        self, src_path: Union[str, Path], dst_path: Union[str, Path]
    ) -> bool:
        """移动文件"""
        src_path = Path(src_path)
        dst_path = Path(dst_path)

        if not src_path.exists():
            logger.error(f"源文件不存在: {src_path}")
            return False

        # 创建目标目录
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.move(str(src_path), str(dst_path))
            logger.debug(f"移动文件成功: {src_path} -> {dst_path}")
            return True

        except Exception as e:
            logger.error(f"移动文件失败: {e}")
            return False

    def delete_file(
        self, file_path: Union[str, Path], safe_delete: bool = True
    ) -> bool:
        """删除文件"""
        file_path = Path(file_path)

        if not file_path.exists():
            logger.warning(f"文件不存在: {file_path}")
            return True

        try:
            if safe_delete:
                # 安全删除：移动到回收站目录
                trash_dir = self.temp_dir / "trash"
                trash_dir.mkdir(exist_ok=True)

                timestamp = int(time.time())
                trash_path = (
                    trash_dir
                    / f"{file_path.stem}_{timestamp}{file_path.suffix}"
                )

                shutil.move(str(file_path), str(trash_path))
                logger.debug(f"安全删除文件: {file_path} -> {trash_path}")
            else:
                # 直接删除
                file_path.unlink()
                logger.debug(f"删除文件: {file_path}")

            return True

        except Exception as e:
            logger.error(f"删除文件失败 {file_path}: {e}")
            return False

    # ==================== 临时文件管理 ====================

    def create_temp_file(
        self,
        suffix: str = "",
        prefix: str = "subtrans_",
        content: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> Optional[str]:
        """创建临时文件"""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w" if content else "w+",
                suffix=suffix,
                prefix=prefix,
                dir=self.temp_dir,
                delete=False,
                encoding=encoding if content else None,
            ) as temp_file:
                temp_path = temp_file.name

                if content:
                    temp_file.write(content)

                self.temp_files.append(temp_path)
                logger.debug(f"创建临时文件: {temp_path}")
                return temp_path

        except Exception as e:
            logger.error(f"创建临时文件失败: {e}")
            return None

    def create_temp_dir(self, prefix: str = "subtrans_") -> Optional[str]:
        """创建临时目录"""
        try:
            temp_dir = tempfile.mkdtemp(prefix=prefix, dir=self.temp_dir)
            self.temp_files.append(temp_dir)  # 也跟踪临时目录
            logger.debug(f"创建临时目录: {temp_dir}")
            return temp_dir

        except Exception as e:
            logger.error(f"创建临时目录失败: {e}")
            return None

    def cleanup_temp_files(self):
        """清理临时文件"""
        for temp_path in self.temp_files:
            try:
                temp_path_obj = Path(temp_path)
                if temp_path_obj.exists():
                    if temp_path_obj.is_file():
                        temp_path_obj.unlink()
                        logger.debug(f"已删除临时文件: {temp_path}")
                    elif temp_path_obj.is_dir():
                        shutil.rmtree(temp_path)
                        logger.debug(f"已删除临时目录: {temp_path}")
            except Exception as e:
                logger.warning(f"删除临时文件失败 {temp_path}: {e}")

        self.temp_files.clear()

    # ==================== 目录操作 ====================

    def scan_directory(
        self,
        directory: Union[str, Path],
        extensions: Optional[List[str]] = None,
        recursive: bool = True,
        max_depth: int = 10,
    ) -> List[FileInfo]:
        """扫描目录中的文件"""
        directory = Path(directory)

        if not directory.exists() or not directory.is_dir():
            logger.error(f"目录不存在或不是目录: {directory}")
            return []

        files = []

        def scan_recursive(current_dir: Path, current_depth: int = 0):
            if current_depth >= max_depth:
                return

            try:
                for item in current_dir.iterdir():
                    if item.is_file():
                        # 检查扩展名过滤
                        if extensions is None or item.suffix.lower() in [
                            ext.lower() for ext in extensions
                        ]:
                            file_info = self.get_file_info(item)
                            if file_info:
                                files.append(file_info)

                    elif item.is_dir() and recursive:
                        scan_recursive(item, current_depth + 1)

            except PermissionError:
                logger.warning(f"无权限访问目录: {current_dir}")
            except Exception as e:
                logger.error(f"扫描目录失败 {current_dir}: {e}")

        logger.info(f"开始扫描目录: {directory}")
        scan_recursive(directory)

        logger.info(f"扫描完成，发现 {len(files)} 个文件")
        return files

    def find_video_files(self, directory: Union[str, Path]) -> List[str]:
        """查找目录中的视频文件"""
        directory = Path(directory)

        if not directory.exists() or not directory.is_dir():
            logger.error(f"目录不存在或不是目录: {directory}")
            return []

        video_files = []

        try:
            for file_path in directory.iterdir():
                if file_path.is_file() and self.is_video_file(file_path):
                    video_files.append(str(file_path.absolute()))

            logger.info(
                f"在目录 {directory} 中找到 {len(video_files)} 个视频文件"
            )
            return video_files

        except Exception as e:
            logger.error(f"查找视频文件失败 {directory}: {e}")
            return []

    def find_related_files(
        self, video_path: Union[str, Path]
    ) -> Dict[str, List[str]]:
        """查找视频文件的相关文件（字幕、音频等）"""
        video_path = Path(video_path)
        video_dir = video_path.parent
        video_stem = video_path.stem

        related_files = {"subtitles": [], "audio": [], "other": []}

        try:
            for file_path in video_dir.iterdir():
                if file_path.is_file() and file_path.stem.startswith(
                    video_stem
                ):
                    if self.is_subtitle_file(file_path):
                        related_files["subtitles"].append(str(file_path))
                    elif self.is_audio_file(file_path):
                        related_files["audio"].append(str(file_path))
                    elif file_path != video_path:
                        related_files["other"].append(str(file_path))

        except Exception as e:
            logger.error(f"查找相关文件失败: {e}")

        return related_files

    def ensure_directory(self, directory: Union[str, Path]) -> bool:
        """确保目录存在"""
        directory = Path(directory)

        try:
            directory.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"创建目录失败 {directory}: {e}")
            return False

    # ==================== 文件名处理 ====================

    def sanitize_filename(self, filename: str, replacement: str = "_") -> str:
        """清理文件名，移除非法字符"""
        # Windows和Unix系统的非法字符
        illegal_chars = '<>:"/\\|?*'

        sanitized = filename
        for char in illegal_chars:
            sanitized = sanitized.replace(char, replacement)

        # 移除控制字符
        sanitized = "".join(char for char in sanitized if ord(char) >= 32)

        # 限制长度
        if len(sanitized) > 255:
            name, ext = os.path.splitext(sanitized)
            max_name_len = 255 - len(ext)
            sanitized = name[:max_name_len] + ext

        return sanitized.strip()

    def generate_unique_filename(
        self, directory: Union[str, Path], filename: str
    ) -> str:
        """生成唯一文件名"""
        directory = Path(directory)
        base_path = directory / filename

        if not base_path.exists():
            return filename

        name, ext = os.path.splitext(filename)
        counter = 1

        while True:
            new_filename = f"{name}_{counter}{ext}"
            new_path = directory / new_filename

            if not new_path.exists():
                return new_filename

            counter += 1

            # 防止无限循环
            if counter > 9999:
                timestamp = int(time.time())
                return f"{name}_{timestamp}{ext}"

    def get_safe_path(
        self, base_dir: Union[str, Path], relative_path: str
    ) -> Optional[Path]:
        """获取安全的路径，防止目录遍历攻击"""
        base_dir = Path(base_dir).resolve()

        try:
            # 解析相对路径
            full_path = (base_dir / relative_path).resolve()

            # 检查是否在基础目录内
            if base_dir in full_path.parents or full_path == base_dir:
                return full_path
            else:
                logger.warning(f"路径遍历攻击尝试: {relative_path}")
                return None

        except Exception as e:
            logger.error(f"路径解析失败: {e}")
            return None
