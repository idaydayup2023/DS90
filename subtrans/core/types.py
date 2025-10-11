#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据类型定义模块

定义了字幕处理系统中使用的基础数据类型。
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProcessingResult:
    """处理结果数据类"""

    success: bool
    input_file: str
    output_files: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    processing_time: float = 0.0
    original_encoding: Optional[str] = None