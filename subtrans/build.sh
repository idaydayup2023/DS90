#!/bin/bash
# SubTrans 2.0 构建脚本

set -e

echo "🚀 开始构建 SubTrans 2.0..."

# 清理旧的构建文件
echo "🧹 清理旧的构建文件..."
rm -rf build/
rm -rf dist/
rm -rf *.egg-info/
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# 检查 Python 版本
echo "🐍 检查 Python 版本..."
python3 --version

# 升级构建工具
echo "🔧 升级构建工具..."
pip3 install --upgrade setuptools wheel build twine

# 安装依赖
echo "📦 安装依赖..."
pip3 install -r requirements.txt

# 运行测试
echo "🧪 运行测试..."
python3 -m pytest tests/ -v --tb=short

# 构建源码包和轮子包
echo "📦 构建包..."
python3 -m build

# 检查包
echo "✅ 检查包..."
twine check dist/*

echo "🎉 构建完成！"
echo "📁 构建文件位于 dist/ 目录"
ls -la dist/