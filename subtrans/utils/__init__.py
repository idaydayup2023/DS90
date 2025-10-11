#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 工具模块
"""

__version__ = "2.0.0"

# 导入并导出常用函数
from .logger import get_logger, setup_logging

__all__ = [
    "get_logger",
    "setup_logging",
]
