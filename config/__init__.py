#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模块
包含配置管理器和配置文件
"""

from .config_manager import ConfigManager, get_config_manager

__all__ = ['ConfigManager', 'get_config_manager']