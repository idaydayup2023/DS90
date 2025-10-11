from setuptools import setup, find_packages
import os

# 读取README文件
readme_path = os.path.join(os.path.dirname(__file__), "README.md")
if os.path.exists(readme_path):
    with open(readme_path, "r", encoding="utf-8") as fh:
        long_description = fh.read()
else:
    long_description = "磁力链接转种子文件工具集 - 提供多种可靠的转换解决方案"

setup(
    name="magnet2torrent",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.25.0",
        "bencodepy>=0.9.5",
    ],
    extras_require={
        "aria2": ["aria2p>=0.11.0"],
        "qbittorrent": ["qbittorrent-api>=2022.8.34"],
        "libtorrent": ["libtorrent>=2.0.0"],
    },
    entry_points={
        "console_scripts": [
            "magnet2torrent=magnet2torrent:main",
        ],
    },
    author="Magnet2Torrent Team",
    author_email="team@magnet2torrent.com",
    description="磁力链接转种子文件工具集 - 提供多种可靠的转换解决方案",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/magnet2torrent/magnet2torrent",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Archiving",
    ],
    keywords="magnet, torrent, bittorrent, aria2, qbittorrent, dht",
    python_requires=">=3.7",
    include_package_data=True,
    zip_safe=False,
)