#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SubTrans 2.0 - 智能字幕处理和翻译系统
安装配置文件
"""

try:
    from setuptools import setup, find_packages
except ImportError:
    print("错误: 需要安装 setuptools")
    print("请运行: pip install setuptools")
    exit(1)

from pathlib import Path
import re

# 读取版本号
def get_version():
    """从 core/config.py 读取版本号"""
    try:
        config_file = Path(__file__).parent / "core" / "config.py"
        content = config_file.read_text(encoding='utf-8')
        # 分别匹配双引号和单引号
        version_match = re.search(r'VERSION\s*:\s*str\s*=\s*"([^"]*)"', content)
        if not version_match:
            version_match = re.search(r"VERSION\s*:\s*str\s*=\s*'([^']*)'", content)
        if version_match:
            return version_match.group(1)
    except FileNotFoundError:
        pass
    return "2.0.0"

# 读取README文件
this_directory = Path(__file__).parent
try:
    long_description = (this_directory / "README.md").read_text(encoding='utf-8')
except FileNotFoundError:
    long_description = "SubTrans 2.0 - 智能字幕处理和翻译系统"

# 读取依赖项
def get_requirements():
    """从 requirements.txt 读取依赖项"""
    requirements_file = this_directory / "requirements.txt"
    if requirements_file.exists():
        with open(requirements_file, 'r', encoding='utf-8') as f:
            requirements = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    requirements.append(line)
            return requirements
    return []

setup(
    name="subtrans",
    version=get_version(),
    description="智能字幕处理和翻译系统",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="SubTrans Team",
    author_email="subtrans@example.com",
    url="https://github.com/username/subtrans",
    project_urls={
        "Bug Reports": "https://github.com/username/subtrans/issues",
        "Source": "https://github.com/username/subtrans",
        "Documentation": "https://github.com/username/subtrans/blob/main/README.md",
        "Changelog": "https://github.com/username/subtrans/blob/main/CHANGELOG.md",
    },
    packages=find_packages(exclude=["tests", "tests.*", "temp", "runtime-test"]),
    include_package_data=True,
    package_data={
        "subtrans": ["*.md", "*.txt", "*.json"],
    },
    entry_points={
        'console_scripts': [
            'subtrans=main:main',
        ],
    },
    install_requires=get_requirements(),
    extras_require={
        'dev': [
            'pytest>=7.0.0',
            'pytest-cov>=4.0.0',
            'black>=22.0.0',
            'flake8>=5.0.0',
            'mypy>=1.0.0',
        ],
        'test': [
            'pytest>=7.0.0',
            'pytest-cov>=4.0.0',
            'pytest-mock>=3.10.0',
        ],
    },
    python_requires='>=3.8',
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: End Users/Desktop",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Multimedia :: Video",
        "Topic :: Text Processing :: Linguistic",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Environment :: Console",
    ],
    keywords="subtitle translation video audio whisper ollama ai nlp",
    zip_safe=False,
)