#!/bin/bash
# SubTrans 2.0 发布脚本

set -e

VERSION="2.0.0"
TAG="v${VERSION}"

echo "🚀 开始发布 SubTrans ${VERSION}..."

# 检查是否在主分支
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ] && [ "$CURRENT_BRANCH" != "master" ]; then
    echo "❌ 错误: 请在主分支上发布"
    exit 1
fi

# 检查工作目录是否干净
if [ -n "$(git status --porcelain)" ]; then
    echo "❌ 错误: 工作目录不干净，请先提交所有更改"
    exit 1
fi

# 运行构建
echo "🔨 运行构建..."
./build.sh

# 创建 Git 标签
echo "🏷️ 创建 Git 标签 ${TAG}..."
git tag -a "$TAG" -m "Release version $VERSION"

# 推送标签
echo "📤 推送标签到远程仓库..."
git push origin "$TAG"

# 发布到 PyPI (测试)
echo "🧪 发布到 PyPI 测试环境..."
twine upload --repository testpypi dist/*

echo "✅ 测试发布完成！"
echo "🔗 测试链接: https://test.pypi.org/project/subtrans/"

read -p "是否发布到正式 PyPI? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "📦 发布到正式 PyPI..."
    twine upload dist/*
    echo "🎉 发布完成！"
    echo "🔗 正式链接: https://pypi.org/project/subtrans/"
else
    echo "⏸️ 跳过正式发布"
fi

echo "✨ 发布流程完成！"