#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import ftplib
import os
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class FTPConfig:
    """FTP配置信息"""

    host: str
    port: int = 21
    username: str = "anonymous"
    password: str = "anonymous@example.com"
    timeout: int = 300
    passive_mode: bool = True
    encoding: str = "utf-8"
    max_retries: int = 3
    chunk_size: int = 8192


@dataclass
class FTPFileInfo:
    """FTP文件信息"""

    name: str
    path: str
    size: int
    is_directory: bool
    modified_time: Optional[str] = None


@dataclass
class FTPHandler:
    """统一FTP处理器"""

    def __init__(self, config: FTPConfig):
        self.config = config
        self._connection = None
        self._keepalive_thread = None
        self._keepalive_stop = threading.Event()
        self.ftp: Optional[ftplib.FTP] = None  # 添加ftp属性

    @classmethod
    def from_url(cls, ftp_url: str) -> "FTPHandler":
        """从FTP URL创建处理器"""
        parsed = urlparse(ftp_url)

        if parsed.scheme != "ftp":
            raise ValueError(f"不支持的协议: {parsed.scheme}")

        config = FTPConfig(
            host=parsed.hostname or "localhost",
            port=parsed.port or 21,
            username=parsed.username or "anonymous",
            password=parsed.password or "anonymous@example.com",
        )

        return cls(config)

    @contextmanager
    def connect(self):
        """FTP连接上下文管理器"""
        ftp = None
        try:
            # 创建FTP连接
            ftp = ftplib.FTP()
            ftp.encoding = self.config.encoding

            # 连接到服务器
            logger.info(
                f"连接到FTP服务器: {self.config.host}:{self.config.port}"
            )
            ftp.connect(
                self.config.host, self.config.port, timeout=self.config.timeout
            )

            # 登录
            ftp.login(self.config.username, self.config.password)

            # 设置被动模式
            if self.config.passive_mode:
                ftp.set_pasv(True)

            logger.info("FTP连接成功")
            yield ftp

        except socket.timeout:
            logger.error("FTP连接超时")
            raise
        except ftplib.error_perm as e:
            logger.error(f"FTP权限错误: {e}")
            raise
        except Exception as e:
            logger.error(f"FTP连接失败: {e}")
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

    def list_directory(self, remote_path: str = "/") -> List[FTPFileInfo]:
        """列出目录内容"""
        files = []

        with self.connect() as ftp:
            try:
                ftp.cwd(remote_path)

                # 获取详细列表
                lines = []
                ftp.retrlines("LIST", lines.append)

                for line in lines:
                    file_info = self._parse_list_line(line, remote_path)
                    if file_info:
                        files.append(file_info)

                logger.debug(f"列出目录 {remote_path}: {len(files)} 个项目")

            except ftplib.error_perm as e:
                logger.error(f"无法访问目录 {remote_path}: {e}")
                raise

        return files

    def _parse_list_line(
        self, line: str, base_path: str
    ) -> Optional[FTPFileInfo]:
        """解析LIST命令的输出行"""
        try:
            parts = line.split()
            if len(parts) < 9:
                return None

            permissions = parts[0]
            size_str = parts[4]
            name = " ".join(parts[8:])

            # 跳过当前目录和父目录
            if name in [".", ".."]:
                return None

            is_directory = permissions.startswith("d")
            size = 0 if is_directory else int(size_str)

            file_path = f"{base_path.rstrip('/')}/{name}"

            return FTPFileInfo(
                name=name, path=file_path, size=size, is_directory=is_directory
            )

        except (ValueError, IndexError) as e:
            logger.warning(f"解析FTP列表行失败: {line} - {e}")
            return None

    # 删除第一个download_file方法定义（第170-234行）

    def upload_file(
        self, local_path: str, remote_path: str, progress_callback=None
    ) -> bool:
        """上传文件"""
        local_path_obj = Path(local_path)  # 转换为Path对象

        if not local_path_obj.exists():
            logger.error(f"本地文件不存在: {local_path}")
            return False

        file_size = local_path_obj.stat().st_size
        uploaded_size = 0

        try:
            with self.connect() as ftp:
                # 确保远程目录存在
                remote_dir = os.path.dirname(remote_path)
                if remote_dir and remote_dir != "/":
                    self._ensure_remote_directory(ftp, remote_dir)

                logger.info(f"上传文件: {local_path} -> {remote_path}")

                def read_callback(data):
                    nonlocal uploaded_size
                    uploaded_size += len(data)

                    if progress_callback:
                        progress = uploaded_size / file_size * 100
                        progress_callback(progress, uploaded_size, file_size)

                    return data

                # 设置二进制模式并上传
                ftp.voidcmd("TYPE I")
                with open(local_path, "rb") as f:
                    ftp.storbinary(
                        f"STOR {remote_path}",
                        f,
                        self.config.chunk_size,
                        read_callback,
                    )

                logger.info(f"上传成功: {remote_path} ({uploaded_size} 字节)")
                return True

        except Exception as e:
            logger.error(f"上传文件失败: {e}")
            return False

    def _ensure_remote_directory(self, ftp, remote_dir: str) -> None:
        """确保远程目录存在"""
        dirs = remote_dir.strip("/").split("/")
        current_dir = "/"

        for dir_name in dirs:
            if not dir_name:
                continue

            current_dir = f"{current_dir.rstrip('/')}/{dir_name}"

            try:
                ftp.cwd(current_dir)
            except ftplib.error_perm:
                # 目录不存在，创建它
                try:
                    ftp.mkd(current_dir)
                    logger.debug(f"创建远程目录: {current_dir}")
                except ftplib.error_perm as e:
                    logger.warning(f"无法创建远程目录 {current_dir}: {e}")

    def delete_file(self, remote_path: str) -> bool:
        """删除远程文件"""
        try:
            with self.connect() as ftp:
                ftp.delete(remote_path)
                logger.info(f"删除文件成功: {remote_path}")
                return True
        except Exception as e:
            logger.error(f"删除文件失败 {remote_path}: {e}")
            return False

    def _create_connection(self) -> ftplib.FTP:
        """创建新的FTP连接"""
        try:
            ftp = ftplib.FTP()
            ftp.encoding = self.config.encoding

            # 连接到服务器
            logger.info(
                f"连接到FTP服务器: {self.config.host}:{self.config.port}"
            )
            ftp.connect(
                self.config.host, self.config.port, timeout=self.config.timeout
            )

            # 登录
            ftp.login(self.config.username, self.config.password)

            # 设置被动模式
            if self.config.passive_mode:
                ftp.set_pasv(True)

            self.ftp = ftp
            logger.info("FTP连接创建成功")
            return ftp

        except Exception as e:
            logger.error(f"创建FTP连接失败: {e}")
            raise

    def _ensure_connection(
        self, ftp_connection: Optional[ftplib.FTP] = None
    ) -> ftplib.FTP:
        """确保FTP连接有效，如果断开则重新连接"""
        if ftp_connection is None:
            ftp_connection = self.ftp

        try:
            # 发送NOOP命令检查连接状态
            if ftp_connection:
                ftp_connection.voidcmd("NOOP")
                return ftp_connection
        except Exception as e:
            logger.warning(f"FTP连接已断开，尝试重新连接: {e}")
            try:
                if ftp_connection:
                    ftp_connection.quit()
            except BaseException:
                pass

        # 重新建立连接
        return self._create_connection()

    # 删除重复的file_exists方法定义（保留第二个版本）
    # 删除重复的download_file方法定义（保留第二个版本）

    def file_exists(
        self, remote_path: str, ftp_connection: Optional[ftplib.FTP] = None
    ) -> bool:
        """检查远程文件是否存在"""
        try:
            # 确保连接有效
            ftp_connection = self._ensure_connection(ftp_connection)

            # 尝试获取文件大小来检查文件是否存在
            ftp_connection.size(remote_path)
            return True
        except Exception as e:
            if "550" in str(e) or "No such file" in str(e):
                return False
            logger.warning(f"检查文件存在性失败 {remote_path}: {e}")
            return False

    def download_file(
        self,
        remote_path: str,
        local_path: str,
        ftp_connection: Optional[ftplib.FTP] = None,
    ) -> bool:
        """下载文件，带重试机制"""
        max_retries = 3
        retry_delay = 5

        for attempt in range(max_retries):
            try:
                # 确保连接有效
                ftp_connection = self._ensure_connection(ftp_connection)

                with open(local_path, "wb") as local_file:
                    ftp_connection.retrbinary(
                        f"RETR {remote_path}", local_file.write
                    )

                logger.info(f"文件下载成功: {remote_path} -> {local_path}")
                return True

            except Exception as e:
                logger.warning(
                    f"下载文件失败 (尝试 {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    logger.info(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    logger.error(f"下载文件失败: {e}")
                    return False

        return False

    def start_keepalive(self, interval=300):  # 每5分钟发送一次保活
        """启动FTP连接保活线程"""

        def keepalive_worker():
            while not self._keepalive_stop.wait(interval):
                try:
                    if self.ftp:
                        self.ftp.voidcmd("NOOP")
                        logger.debug("FTP保活信号发送成功")
                except Exception as e:
                    logger.warning(f"FTP保活失败: {e}")

        self._keepalive_thread = threading.Thread(
            target=keepalive_worker, daemon=True
        )
        self._keepalive_thread.start()
        logger.info("FTP连接保活已启动")

    def stop_keepalive(self):
        """停止FTP连接保活"""
        if self._keepalive_thread:
            self._keepalive_stop.set()
            self._keepalive_thread.join(timeout=5)
            logger.info("FTP连接保活已停止")
