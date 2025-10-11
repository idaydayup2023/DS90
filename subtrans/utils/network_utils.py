#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import ftplib
import os
import socket
import threading
import time
import urllib.parse
from contextlib import contextmanager
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from .logger import get_logger

logger = get_logger(__name__)


def check_internet_connection(timeout: int = 5) -> bool:
    """检查网络连接"""
    try:
        # 尝试连接到Google DNS
        socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        return True
    except OSError:
        return False


def check_url_accessible(url: str, timeout: int = 10) -> bool:
    """检查URL是否可访问"""
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        return response.status_code < 400
    except Exception:
        return False


def download_with_progress(
    url: str,
    output_path: str,
    progress_callback: Optional[Callable] = None,
    chunk_size: int = 8192,
    timeout: int = 60,
) -> bool:
    """带进度的文件下载"""
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded_size = 0

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)

                    if progress_callback and total_size > 0:
                        progress = downloaded_size / total_size * 100
                        progress_callback(
                            progress, downloaded_size, total_size
                        )

        logger.info(f"下载完成: {output_path} ({downloaded_size} 字节)")
        return True

    except Exception as e:
        logger.error(f"下载失败 {url}: {e}")
        return False


def retry_on_failure(
    func: Callable,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
):
    """重试装饰器"""

    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:  # 使用Exception而不是裸露的except
                last_exception = e
                if attempt < max_retries - 1:
                    wait_time = delay * (backoff**attempt)
                    logger.warning(f"操作失败，{wait_time:.1f}秒后重试 (尝试 {attempt + 1}/{max_retries}): {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"操作最终失败 (尝试 {max_retries} 次): {e}")

        if last_exception is not None:  # 添加None检查
            raise last_exception
        else:
            raise RuntimeError("未知错误")

    return wrapper


def validate_ftp_url(url: str) -> bool:
    """验证FTP URL格式"""
    try:
        parsed = urlparse(url)
        return parsed.scheme == "ftp" and parsed.hostname is not None
    except Exception:
        return False


def parse_ftp_url(url: str) -> dict:
    """解析FTP URL"""
    parsed = urlparse(url)

    return {
        "host": parsed.hostname,
        "port": parsed.port or 21,
        "username": parsed.username or "anonymous",
        "password": parsed.password or "anonymous@example.com",
        "path": parsed.path or "/",
    }


class CompatibleFTP(ftplib.FTP):
    """兼容中文文件名的FTP类

    处理ftplib在处理中文文件名时的编码问题的临时解决方案。
    """

    def __init__(self, *args, **kwargs):
        """初始化兼容FTP连接"""
        # 使用UTF-8编码替代latin1
        import sys

        if sys.version_info >= (3, 9):
            kwargs["encoding"] = "utf-8"
        super().__init__(*args, **kwargs)
        if hasattr(self, "encoding"):
            self.encoding = "utf-8"

        self._compatibility_mode = True
        self._current_dir = "/"

    def _has_chinese_chars(self, text: str) -> bool:
        """检查文本是否包含中文字符"""
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _try_change_directory(
        self, remote_path: str
    ) -> Tuple[bool, Optional[str]]:
        """尝试切换到文件所在目录"""
        try:
            dirname = os.path.dirname(remote_path)
            if dirname and dirname != ".":
                original_dir = self.pwd()

                if self._has_chinese_chars(dirname):
                    logger.warning(f"跳过包含中文字符的目录切换: {dirname}")
                    return False, None

                self.cwd(dirname)
                self._current_dir = dirname
                return True, original_dir
        except Exception as e:
            logger.error(f"切换目录失败: {e}")
        return False, None

    def _restore_directory(self, original_dir: Optional[str]):
        """恢复到原始目录"""
        try:
            if original_dir:
                self.cwd(original_dir)
                self._current_dir = original_dir
        except Exception as e:
            logger.error(f"恢复目录失败: {e}")

    def safe_transfercmd(self, cmd: str, filename: str):
        """安全执行传输命令"""
        original_dir = None

        try:
            # 方法1: 尝试原始文件名
            return self.transfercmd(f"{cmd} {filename}")
        except UnicodeEncodeError:
            if self._has_chinese_chars(filename):
                try:
                    # 方法2: 尝试切换到目录后使用文件名
                    dirname = os.path.dirname(filename)
                    if dirname and not self._has_chinese_chars(dirname):
                        dir_changed, original_dir = self._try_change_directory(
                            filename
                        )
                        if dir_changed:
                            basename = os.path.basename(filename)
                            try:
                                result = self.transfercmd(f"{cmd} {basename}")
                                logger.info(
                                    f"使用目录切换方式下载: {basename}"
                                )
                                return result
                            except Exception as e:
                                logger.error(f"目录切换后仍然失败: {e}")
                            finally:
                                self._restore_directory(original_dir)

                    # 方法3: 尝试URL编码
                    encoded_filename = urllib.parse.quote(filename, safe="/")
                    return self.transfercmd(f"{cmd} {encoded_filename}")

                except Exception as e:
                    logger.error(f"中文文件名处理失败: {e}")
                    raise Exception(
                        f"跳过包含中文字符的文件: {os.path.basename(filename)}"
                    )
            else:
                try:
                    # 方法4: 对于非中文的编码问题，尝试URL编码
                    encoded_filename = urllib.parse.quote(filename, safe="/")
                    return self.transfercmd(f"{cmd} {encoded_filename}")
                except Exception:
                    # 方法5: 最后尝试只使用文件名
                    basename = os.path.basename(filename)
                    try:
                        return self.transfercmd(f"{cmd} {basename}")
                    except Exception:
                        raise Exception(f"无法处理文件名: {filename}")
        except Exception as e:
            if "550" in str(e):
                raise Exception(f"文件不存在或权限拒绝: {filename}")
            else:
                raise Exception(f"传输命令失败: {e}")
        finally:
            if original_dir:
                self._restore_directory(original_dir)

    def safe_command(self, cmd: str, filename: str):
        """安全执行包含文件名的FTP命令"""
        try:
            return self.voidcmd(f"{cmd} {filename}")
        except UnicodeEncodeError:
            if self._has_chinese_chars(filename):
                raise Exception(
                    f"跳过包含中文字符的文件: {os.path.basename(filename)}"
                )
            else:
                try:
                    encoded_filename = urllib.parse.quote(filename, safe="/")
                    return self.voidcmd(f"{cmd} {encoded_filename}")
                except Exception:
                    raise Exception(f"无法处理文件名: {filename}")


class FTPScanner:
    """FTP文件扫描器"""

    def __init__(self):
        self.dir_cache = {}  # 目录内容缓存
        self.file_type_cache = {}  # 文件类型缓存
        self.cache_lock = threading.Lock()  # 缓存锁
        self.scanned_dirs = 0
        self.found_files = 0

    def _get_directory_listing_with_types(
        self, ftp: CompatibleFTP, path: str
    ) -> Tuple[List[str], List[str]]:
        """获取目录列表并区分文件和目录类型"""
        with self.cache_lock:
            if path in self.dir_cache:
                return self.dir_cache[path]

        files = []
        directories = []

        try:
            ftp.cwd(path)

            try:
                # 获取所有项目的列表
                all_items = []
                ftp.retrlines("NLST", all_items.append)

                current_dir = ftp.pwd()

                # 逐个判断每个项目是文件还是目录
                for item in all_items:
                    if item in [".", ".."]:
                        continue

                    try:
                        ftp.cwd(item)
                        directories.append(item)
                        ftp.cwd(current_dir)
                    except ftplib.error_perm:
                        files.append(item)
                    except Exception:
                        files.append(item)

            except Exception as e:
                logger.warning(f"NLST命令失败: {e}")

                # 备选方案：使用LIST命令
                try:
                    listing = []

                    def safe_append(line):
                        try:
                            if isinstance(line, bytes):
                                decoded = line.decode(
                                    "latin1", errors="ignore"
                                )
                            else:
                                decoded = line
                            listing.append(decoded)
                        except BaseException:
                            pass

                    ftp.retrlines("LIST", safe_append)

                    for line in listing:
                        try:
                            parts = line.split()
                            if len(parts) >= 9:
                                permissions = parts[0]
                                name = " ".join(parts[8:])

                                if name in [".", ".."] or not name.strip():
                                    continue

                                if permissions.startswith("d"):
                                    directories.append(name)
                                else:
                                    files.append(name)

                        except Exception:
                            continue

                except Exception as final_e:
                    logger.error(f"所有方案都失败: {final_e}")
                    return [], []
        except Exception as e:
            logger.error(f"获取目录 {path} 列表时出错: {e}")
            return [], []

        # 缓存结果
        with self.cache_lock:
            self.dir_cache[path] = (files, directories)

        return files, directories

    def scan_directory_recursive(
        self,
        ftp: CompatibleFTP,
        path: str,
        extension: Optional[str] = None,
        max_depth: int = 5,
    ) -> List[str]:
        """递归扫描目录"""
        if max_depth <= 0:
            return []

        all_files = []

        try:
            files, directories = self._get_directory_listing_with_types(
                ftp, path
            )

            # 处理文件
            for file in files:
                if extension is None or file.lower().endswith(
                    extension.lower()
                ):
                    full_path = os.path.join(path, file).replace("\\", "/")
                    all_files.append(full_path)
                    self.found_files += 1

            # 递归处理子目录
            for directory in directories:
                subdir_path = os.path.join(path, directory).replace("\\", "/")
                self.scanned_dirs += 1
                subfiles = self.scan_directory_recursive(
                    ftp, subdir_path, extension, max_depth - 1
                )
                all_files.extend(subfiles)

        except Exception as e:
            logger.error(f"扫描目录 {path} 时出错: {e}")

        return all_files

    def find_subtitle_files(
        self, ftp: CompatibleFTP, video_path: str
    ) -> List[str]:
        """查找视频文件对应的字幕文件"""
        video_dir = os.path.dirname(video_path)
        video_name = os.path.splitext(os.path.basename(video_path))[0]

        # 可能的字幕文件名模式
        patterns = [
            f"{video_name}.en.srt",
            f"{video_name}.eng.srt",
            f"{video_name}.english.srt",
            f"{video_name}.srt",
            f"{video_name}.ass",
            f"{video_name}.ssa",
            f"{video_name}.vtt",
        ]

        found_subtitles = []

        try:
            files, _ = self._get_directory_listing_with_types(ftp, video_dir)

            for pattern in patterns:
                if pattern in files:
                    subtitle_path = os.path.join(video_dir, pattern).replace(
                        "\\", "/"
                    )
                    found_subtitles.append(subtitle_path)

        except Exception as e:
            logger.error(f"查找字幕文件时出错: {e}")

        return found_subtitles

    def clear_cache(self):
        """清除缓存"""
        with self.cache_lock:
            self.dir_cache.clear()
            self.file_type_cache.clear()


@contextmanager
def ftp_connection(
    host: str,
    port: int = 21,
    username: str = "anonymous",
    password: str = "anonymous@example.com",
    timeout: int = 30,
):
    """FTP连接上下文管理器"""
    ftp = None
    try:
        ftp = CompatibleFTP()
        ftp.connect(host, port, timeout)
        ftp.login(username, password)
        logger.info(f"FTP连接成功: {host}:{port}")
        yield ftp
    except Exception as e:
        logger.error(f"FTP连接失败: {e}")
        # 确保抛出的异常是 BaseException 的子类
        # 将 None 替换为适当的异常类，例如：
        raise ValueError("错误信息")  # 而不是 raise None
        raise
    finally:
        if ftp:
            try:
                ftp.quit()
            except BaseException:
                try:
                    ftp.close()
                except BaseException:
                    pass


def get_file_size_from_url(url: str, timeout: int = 10) -> Optional[int]:
    """获取URL文件大小"""
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            content_length = response.headers.get("content-length")
            if content_length:
                return int(content_length)
    except Exception as e:
        logger.error(f"获取文件大小失败 {url}: {e}")
    return None


def is_valid_subtitle_url(url: str) -> bool:
    """验证是否为有效的字幕文件URL"""
    subtitle_extensions = [".srt", ".ass", ".ssa", ".vtt", ".sub"]
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
        return any(path.endswith(ext) for ext in subtitle_extensions)
    except Exception:
        return False


def normalize_url(url: str) -> str:
    """标准化URL格式"""
    if not url.startswith(("http://", "https://", "ftp://")):
        url = "http://" + url
    return url.rstrip("/")


def extract_domain(url: str) -> Optional[str]:
    """提取URL的域名"""
    try:
        parsed = urlparse(url)
        return parsed.netloc
    except Exception:
        return None
