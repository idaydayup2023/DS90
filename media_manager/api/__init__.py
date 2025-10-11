#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API模块
包含TMDB客户端和其他外部API集成
"""

from .tmdb_client import TMDBClient

__all__ = ['TMDBClient']