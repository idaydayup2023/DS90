#!/bin/bash
# 群晖NAS磁力链接转换器安装脚本
# 
# 使用方法:
# 1. 上传此脚本到群晖NAS
# 2. SSH登录群晖: ssh admin@your-nas-ip
# 3. 运行脚本: bash synology_setup.sh
#
# 作者: AI Assistant
# 版本: 1.0

set -e  # 遇到错误立即退出

echo "🚀 群晖NAS磁力链接转换器安装脚本"
echo "版本: 2.0.0"
echo "适用于: 群晖 DSM 7.x"
echo "支持: libtorrent 1.x 和 2.x 版本"
echo "========================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 检查是否为root用户
check_permissions() {
    if [[ $EUID -ne 0 ]]; then
        log_warn "建议使用root权限运行此脚本"
        log_info "如果遇到权限问题，请使用: sudo bash synology_setup.sh"
    fi
}

# 检查Python环境
check_python() {
    log_step "检查Python环境..."
    
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1)
        log_info "Python版本: $PYTHON_VERSION"
    else
        log_error "Python3未安装，请先安装Python3"
        exit 1
    fi
}

# 安装pip
install_pip() {
    log_step "检查并安装pip..."
    
    # 检查pip是否可用
    if python3 -m pip --version &> /dev/null; then
        log_info "pip已可用"
        return 0
    fi
    
    if command -v pip3 &> /dev/null; then
        log_info "pip3已安装"
        return 0
    fi
    
    log_info "正在安装pip..."
    
    # 下载get-pip.py
    if command -v curl &> /dev/null; then
        curl -s https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
    elif command -v wget &> /dev/null; then
        wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py
    else
        log_error "需要curl或wget来下载pip安装脚本"
        log_info "请手动下载 https://bootstrap.pypa.io/get-pip.py 并上传到群晖"
        exit 1
    fi
    
    # 安装pip
    python3 /tmp/get-pip.py --user
    
    # 添加到PATH
    export PATH="$HOME/.local/bin:$PATH"
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    
    log_info "pip安装完成"
}

# 安装依赖库
install_dependencies() {
    log_step "安装Python依赖库..."
    
    # 安装libtorrent
    log_info "正在安装libtorrent..."
    python3 -m pip install --user libtorrent
    
    # 验证安装
    if python3 -c "import libtorrent; print('libtorrent版本:', libtorrent.version)" 2>/dev/null; then
        log_info "libtorrent安装成功"
    else
        log_error "libtorrent安装失败"
        exit 1
    fi
}

# 创建目录结构
create_directories() {
    log_step "创建目录结构..."
    
    DIRS=(
        "/volume1/Downloads/magnet.files"
        "/volume1/Downloads/torrent.files"
        "/volume1/Downloads/logs"
        "/volume1/Downloads/scripts"
    )
    
    for dir in "${DIRS[@]}"; do
        if mkdir -p "$dir" 2>/dev/null; then
            log_info "创建目录: $dir"
        else
            log_warn "无法创建目录: $dir (可能需要管理员权限)"
        fi
    done
}

# 复制脚本文件
copy_scripts() {
    log_step "复制脚本文件..."
    
    SCRIPT_DIR="/volume1/Downloads/scripts"
    
    # 检查源脚本是否存在
    if [[ -f "synology_magnet_converter.py" ]]; then
        cp synology_magnet_converter.py "$SCRIPT_DIR/"
        chmod +x "$SCRIPT_DIR/synology_magnet_converter.py"
        log_info "已复制: synology_magnet_converter.py"
    else
        log_warn "未找到 synology_magnet_converter.py，请手动上传"
    fi
    
    # 检查简化版脚本是否存在
    if [[ -f "synology_magnet_converter_simple.py" ]]; then
        cp synology_magnet_converter_simple.py "$SCRIPT_DIR/"
        chmod +x "$SCRIPT_DIR/synology_magnet_converter_simple.py"
        log_info "已复制: synology_magnet_converter_simple.py"
    else
        log_warn "未找到 synology_magnet_converter_simple.py，请手动上传"
    fi
    
    # 检查并复制libtorrent 2.x版本脚本
    if [[ -f "synology_magnet_converter_v2.py" ]]; then
        cp synology_magnet_converter_v2.py "$SCRIPT_DIR/"
        chmod +x "$SCRIPT_DIR/synology_magnet_converter_v2.py"
        log_info "已复制: synology_magnet_converter_v2.py"
    else
        log_warn "未找到 synology_magnet_converter_v2.py，请手动上传"
    fi
}

# 创建启动脚本
create_startup_script() {
    log_step "创建启动脚本..."
    
    cat > /volume1/Downloads/scripts/start_converter.sh << 'EOF'
#!/bin/bash
# 磁力链接转换器启动脚本

cd /volume1/Downloads/scripts

# 设置Python路径
export PATH="$HOME/.local/bin:$PATH"

# 启动转换器
python3 synology_magnet_converter.py --once

# 记录执行时间
echo "$(date): 磁力链接转换任务执行完成" >> /volume1/Downloads/logs/task_execution.log
EOF

    chmod +x /volume1/Downloads/scripts/start_converter.sh
    log_info "启动脚本已创建: /volume1/Downloads/scripts/start_converter.sh"
}

# 创建监控脚本
create_monitor_script() {
    log_step "创建监控脚本..."
    
    cat > /volume1/Downloads/scripts/start_monitor.sh << 'EOF'
#!/bin/bash
# 磁力链接转换器监控脚本

cd /volume1/Downloads/scripts

# 设置Python路径
export PATH="$HOME/.local/bin:$PATH"

# 启动监控模式
nohup python3 synology_magnet_converter.py --monitor --interval 300 > /volume1/Downloads/logs/monitor.log 2>&1 &

echo "监控进程已启动，PID: $!"
echo "日志文件: /volume1/Downloads/logs/monitor.log"
EOF

    chmod +x /volume1/Downloads/scripts/start_monitor.sh
    log_info "监控脚本已创建: /volume1/Downloads/scripts/start_monitor.sh"
}

# 创建测试文件
create_test_files() {
    log_step "创建测试文件..."
    
    # 创建示例.magnet文件
    cat > /volume1/Downloads/magnet.files/test_magnet.magnet << 'EOF'
magnet:?xt=urn:btih:c12fe1c06bba254a9dc9f519b335aa7c1367a88a&dn=Test+File
EOF
    
    log_info "测试文件已创建: /volume1/Downloads/magnet.files/test_magnet.magnet"
}

# 显示使用说明
show_usage() {
    log_step "安装完成！使用说明："
    
    echo ""
    echo "📁 目录结构："
    echo "   /volume1/Downloads/magnet.files/  - 放置.magnet文件"
    echo "   /volume1/Downloads/torrent.files/ - 输出.torrent文件"
    echo "   /volume1/Downloads/logs/          - 日志文件"
    echo "   /volume1/Downloads/scripts/       - 脚本文件"
    echo ""
    echo "🚀 运行方式："
    echo "   1. libtorrent 2.x版本（推荐，适用于新版本libtorrent 2.0+）: python3 /volume1/Downloads/scripts/synology_magnet_converter_v2.py --once"
    echo "   2. 简化版本（适用于旧版本libtorrent 1.x）: python3 /volume1/Downloads/scripts/synology_magnet_converter_simple.py --once"
    echo "   3. 标准版本: python3 /volume1/Downloads/scripts/synology_magnet_converter.py --once"
    echo "   4. 单次运行: bash /volume1/Downloads/scripts/start_converter.sh"
    echo "   5. 监控模式: bash /volume1/Downloads/scripts/start_monitor.sh"
    echo ""
    echo "💡 版本选择建议："
    echo "   - 如果遇到 'settings_pack' 错误，请使用简化版本"
    echo "   - 简化版本兼容性更好，适合旧版本libtorrent"
    echo ""
    echo "⚙️ 群晖任务计划配置："
    echo "   1. 打开DSM控制面板 > 任务计划"
    echo "   2. 新增 > 计划的任务 > 用户定义的脚本"
    echo "   3. 任务名称: 磁力链接转换"
    echo "   4. 用户账号: root"
    echo "   5. 计划: 每5分钟执行一次"
    echo "   6. 任务设置 > 运行命令: python3 /volume1/Downloads/scripts/synology_magnet_converter_v2.py --once"
    echo ""
    echo "📝 使用方法："
    echo "   1. 将.magnet文件放入 /volume1/Downloads/magnet.files/"
    echo "   2. 脚本会自动转换为.torrent文件"
    echo "   3. 转换后的文件保存在 /volume1/Downloads/torrent.files/"
    echo ""
    echo "🔍 查看日志："
    echo "   tail -f /volume1/Downloads/logs/magnet_converter.log"
    echo ""
}

# 主函数
main() {
    log_info "开始安装群晖磁力链接转换器..."
    
    check_permissions
    check_python
    install_pip
    install_dependencies
    create_directories
    copy_scripts
    create_startup_script
    create_monitor_script
    create_test_files
    show_usage
    
    log_info "安装完成！🎉"
}

# 运行主函数
main "$@"