#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import sys
from pathlib import Path
from typing import Optional


class SafeStreamHandler(logging.StreamHandler):
    """A StreamHandler that ignores BrokenPipeError to avoid noisy tracebacks
    when stdout is piped (e.g., through `head`).
    """

    def handleError(self, record) -> None:  # type: ignore[override]
        exc_type, exc_value, _ = sys.exc_info()
        if isinstance(exc_value, BrokenPipeError):
            try:
                self.flush()
                self.close()
            except Exception:
                pass
            return
        super().handleError(record)


def get_logger(
    name: str, level: Optional[int] = None, log_file: Optional[str] = None
) -> logging.Logger:
    """
    获取配置好的logger实例

    Args:
        name: logger名称，通常使用 __name__
        level: 日志级别，如果为None则使用root logger的级别
        log_file: 可选的日志文件路径

    Returns:
        配置好的logger实例
    """
    logger = logging.getLogger(name)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 如果没有指定级别，使用root logger的级别
    if level is None:
        level = logging.getLogger().level
        if level == logging.NOTSET:
            level = logging.INFO

    logger.setLevel(level)

    # 创建格式化器
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台处理器：改用 stderr，并在管道关闭时忽略 BrokenPipeError
    console_handler = SafeStreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 防止重复向 root 传播，避免重复日志
    logger.propagate = False

    # 文件处理器（如果指定了日志文件）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def setup_logging(
    log_level: str = "INFO", log_file: Optional[str] = None
) -> None:
    """
    设置全局日志配置

    Args:
        log_level: 日志级别字符串 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 可选的日志文件路径
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)


def setup_logger(
    name: str, level: int = logging.INFO, log_file: Optional[str] = None
) -> logging.Logger:
    """设置日志记录器"""
    logger = logging.getLogger(name)

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 创建格式化器
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # 控制台处理器：改用 stderr，并在管道关闭时忽略 BrokenPipeError
    console_handler = SafeStreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 防止重复向 root 传播，避免重复日志
    logger.propagate = False

    # 文件处理器（如果指定了日志文件）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
