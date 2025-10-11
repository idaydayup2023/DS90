#!/bin/bash

# 媒体库管理系统启动脚本
# Media Library Management System Startup Script

# 设置脚本目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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

# 检查Python环境
check_python() {
    if ! command -v python3 &> /dev/null; then
        log_error "Python3 未安装，请先安装 Python 3.7+"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    log_info "检测到 Python 版本: $PYTHON_VERSION"
    
    # 检查版本是否满足要求（3.7+）
    if python3 -c 'import sys; exit(0 if sys.version_info >= (3, 7) else 1)'; then
        log_info "Python 版本满足要求"
    else
        log_error "Python 版本过低，需要 3.7 或更高版本"
        exit 1
    fi
}

# 检查并安装依赖
install_dependencies() {
    log_info "检查依赖包..."
    
    if [ -f "requirements.txt" ]; then
        log_info "安装依赖包..."
        python3 -m pip install -r requirements.txt
        if [ $? -eq 0 ]; then
            log_info "依赖包安装完成"
        else
            log_error "依赖包安装失败"
            exit 1
        fi
    else
        log_warn "未找到 requirements.txt 文件"
    fi
}

# 检查配置文件
check_config() {
    if [ ! -f "config/config.yaml" ]; then
        log_error "配置文件不存在: config/config.yaml"
        log_info "请确保配置文件存在并正确配置"
        exit 1
    fi
    log_info "配置文件检查通过"
}

# 创建必要目录
create_directories() {
    log_info "创建必要目录..."
    mkdir -p logs
    mkdir -p database
    log_info "目录创建完成"
}

# 显示帮助信息
show_help() {
    echo -e "${BLUE}媒体库管理系统启动脚本${NC}"
    echo ""
    echo "用法: $0 [选项] [命令]"
    echo ""
    echo "选项:"
    echo "  -h, --help     显示此帮助信息"
    echo "  --no-deps      跳过依赖检查和安装"
    echo ""
    echo "命令:"
    echo "  init           初始化数据库"
    echo "  scan [路径]    扫描媒体文件"
    echo "  metadata       更新元数据"
    echo "  duplicates     检测重复文件"
    echo "  stats          显示统计信息"
    echo "  full           执行完整流程"
    echo ""
    echo "示例:"
    echo "  $0 init                    # 初始化数据库"
    echo "  $0 scan /volume1/video     # 扫描指定目录"
    echo "  $0 full                    # 执行完整流程"
}

# 主函数
main() {
    local skip_deps=false
    local command=""
    local scan_path=""
    
    # 解析参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            --no-deps)
                skip_deps=true
                shift
                ;;
            init|metadata|duplicates|stats|full)
                command="$1"
                shift
                ;;
            scan)
                command="scan"
                shift
                if [[ $# -gt 0 && ! $1 =~ ^- ]]; then
                    scan_path="$1"
                    shift
                fi
                ;;
            *)
                log_error "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 如果没有指定命令，显示帮助
    if [ -z "$command" ]; then
        show_help
        exit 0
    fi
    
    log_info "启动媒体库管理系统..."
    
    # 环境检查
    check_python
    create_directories
    check_config
    
    if [ "$skip_deps" = false ]; then
        install_dependencies
    fi
    
    # 执行命令
    case $command in
        init)
            log_info "初始化数据库..."
            python3 main.py init
            ;;
        scan)
            if [ -n "$scan_path" ]; then
                log_info "扫描目录: $scan_path"
                python3 main.py scan "$scan_path"
            else
                log_info "扫描默认目录..."
                python3 main.py scan
            fi
            ;;
        metadata)
            log_info "更新元数据..."
            python3 main.py metadata
            ;;
        duplicates)
            log_info "检测重复文件..."
            python3 main.py duplicates
            ;;
        stats)
            log_info "显示统计信息..."
            python3 main.py stats
            ;;
        full)
            log_info "执行完整流程..."
            python3 main.py full
            ;;
    esac
    
    if [ $? -eq 0 ]; then
        log_info "操作完成"
    else
        log_error "操作失败"
        exit 1
    fi
}

# 运行主函数
main "$@"