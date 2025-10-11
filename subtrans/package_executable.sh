#!/bin/bash
# SubTrans 可执行文件打包脚本

set -e

echo "📦 开始打包 SubTrans 可执行文件..."

# 检查可执行文件是否存在
if [ ! -f "dist/subtrans" ]; then
    echo "❌ 错误: 可执行文件不存在，请先运行编译"
    echo "运行: pyinstaller subtrans.spec"
    exit 1
fi

# 创建打包目录
PACKAGE_DIR="subtrans-executable-$(date +%Y%m%d)"
echo "📁 创建打包目录: $PACKAGE_DIR"
rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

# 复制可执行文件
echo "📋 复制可执行文件..."
cp dist/subtrans "$PACKAGE_DIR/"

# 复制使用说明
echo "📄 复制使用说明..."
cp EXECUTABLE_USAGE.md "$PACKAGE_DIR/README.md"

# 创建启动脚本
echo "🚀 创建启动脚本..."
cat > "$PACKAGE_DIR/run_subtrans.sh" << 'EOF'
#!/bin/bash
# SubTrans 启动脚本

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 运行 SubTrans
"$SCRIPT_DIR/subtrans" "$@"
EOF

# 设置执行权限
chmod +x "$PACKAGE_DIR/run_subtrans.sh"
chmod +x "$PACKAGE_DIR/subtrans"

# 创建版本信息文件
echo "📋 创建版本信息..."
cat > "$PACKAGE_DIR/VERSION.txt" << EOF
SubTrans 可执行文件包
版本: 2.8.2
编译日期: $(date '+%Y-%m-%d %H:%M:%S')
编译环境: macOS ARM64
PyInstaller 版本: 6.15.0
Python 版本: 3.13.5

包含功能:
- 自动模型选择 (默认启用)
- 字幕翻译和处理
- 音频提取和ASR
- 批量处理
- FTP模式
- 多种输出格式

使用方法:
./subtrans --help
./run_subtrans.sh --help

详细说明请查看 README.md
EOF

# 显示包大小
echo "📊 计算包大小..."
PACKAGE_SIZE=$(du -sh "$PACKAGE_DIR" | cut -f1)
echo "包大小: $PACKAGE_SIZE"

# 创建压缩包
echo "🗜️  创建压缩包..."
ZIP_NAME="${PACKAGE_DIR}.zip"
zip -r "$ZIP_NAME" "$PACKAGE_DIR" > /dev/null
ZIP_SIZE=$(du -sh "$ZIP_NAME" | cut -f1)

echo "✅ 打包完成！"
echo ""
echo "📦 打包结果:"
echo "  目录: $PACKAGE_DIR ($PACKAGE_SIZE)"
echo "  压缩包: $ZIP_NAME ($ZIP_SIZE)"
echo ""
echo "📋 包含文件:"
ls -la "$PACKAGE_DIR"
echo ""
echo "🚀 使用方法:"
echo "  1. 解压: unzip $ZIP_NAME"
echo "  2. 运行: cd $PACKAGE_DIR && ./subtrans --help"
echo "  3. 或使用: ./run_subtrans.sh --help"
echo ""
echo "📄 详细说明请查看包内的 README.md 文件"