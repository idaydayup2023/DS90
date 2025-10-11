@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM 媒体库管理系统启动脚本 (Windows)
REM Media Library Management System Startup Script (Windows)

REM 设置脚本目录
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM 颜色定义（Windows 10+）
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "NC=[0m"

REM 日志函数
:log_info
echo %GREEN%[INFO]%NC% %~1
goto :eof

:log_warn
echo %YELLOW%[WARN]%NC% %~1
goto :eof

:log_error
echo %RED%[ERROR]%NC% %~1
goto :eof

REM 检查Python环境
:check_python
python --version >nul 2>&1
if errorlevel 1 (
    call :log_error "Python 未安装，请先安装 Python 3.7+"
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
call :log_info "检测到 Python 版本: !PYTHON_VERSION!"

REM 检查版本（简化检查）
python -c "import sys; exit(0 if sys.version_info >= (3, 7) else 1)" >nul 2>&1
if errorlevel 1 (
    call :log_error "Python 版本过低，需要 3.7 或更高版本"
    pause
    exit /b 1
)
call :log_info "Python 版本满足要求"
goto :eof

REM 检查并安装依赖
:install_dependencies
call :log_info "检查依赖包..."

if exist "requirements.txt" (
    call :log_info "安装依赖包..."
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        call :log_error "依赖包安装失败"
        pause
        exit /b 1
    )
    call :log_info "依赖包安装完成"
) else (
    call :log_warn "未找到 requirements.txt 文件"
)
goto :eof

REM 检查配置文件
:check_config
if not exist "config\config.yaml" (
    call :log_error "配置文件不存在: config\config.yaml"
    call :log_info "请确保配置文件存在并正确配置"
    pause
    exit /b 1
)
call :log_info "配置文件检查通过"
goto :eof

REM 创建必要目录
:create_directories
call :log_info "创建必要目录..."
if not exist "logs" mkdir logs
if not exist "database" mkdir database
call :log_info "目录创建完成"
goto :eof

REM 显示帮助信息
:show_help
echo %BLUE%媒体库管理系统启动脚本%NC%
echo.
echo 用法: %~nx0 [选项] [命令]
echo.
echo 选项:
echo   -h, --help     显示此帮助信息
echo   --no-deps      跳过依赖检查和安装
echo.
echo 命令:
echo   init           初始化数据库
echo   scan [路径]    扫描媒体文件
echo   metadata       更新元数据
echo   duplicates     检测重复文件
echo   stats          显示统计信息
echo   full           执行完整流程
echo.
echo 示例:
echo   %~nx0 init                    # 初始化数据库
echo   %~nx0 scan D:\Videos          # 扫描指定目录
echo   %~nx0 full                    # 执行完整流程
echo.
goto :eof

REM 主函数
:main
set "skip_deps=false"
set "command="
set "scan_path="

REM 解析参数
:parse_args
if "%~1"=="" goto :args_done
if "%~1"=="-h" goto :help
if "%~1"=="--help" goto :help
if "%~1"=="--no-deps" (
    set "skip_deps=true"
    shift
    goto :parse_args
)
if "%~1"=="init" (
    set "command=init"
    shift
    goto :parse_args
)
if "%~1"=="scan" (
    set "command=scan"
    shift
    if not "%~1"=="" if not "%~1:~0,1%"=="-" (
        set "scan_path=%~1"
        shift
    )
    goto :parse_args
)
if "%~1"=="metadata" (
    set "command=metadata"
    shift
    goto :parse_args
)
if "%~1"=="duplicates" (
    set "command=duplicates"
    shift
    goto :parse_args
)
if "%~1"=="stats" (
    set "command=stats"
    shift
    goto :parse_args
)
if "%~1"=="full" (
    set "command=full"
    shift
    goto :parse_args
)
call :log_error "未知参数: %~1"
goto :help

:help
call :show_help
pause
exit /b 0

:args_done
if "%command%"=="" (
    call :show_help
    pause
    exit /b 0
)

call :log_info "启动媒体库管理系统..."

REM 环境检查
call :check_python
call :create_directories
call :check_config

if "%skip_deps%"=="false" (
    call :install_dependencies
)

REM 执行命令
if "%command%"=="init" (
    call :log_info "初始化数据库..."
    python main.py init
) else if "%command%"=="scan" (
    if not "%scan_path%"=="" (
        call :log_info "扫描目录: !scan_path!"
        python main.py scan "!scan_path!"
    ) else (
        call :log_info "扫描默认目录..."
        python main.py scan
    )
) else if "%command%"=="metadata" (
    call :log_info "更新元数据..."
    python main.py metadata
) else if "%command%"=="duplicates" (
    call :log_info "检测重复文件..."
    python main.py duplicates
) else if "%command%"=="stats" (
    call :log_info "显示统计信息..."
    python main.py stats
) else if "%command%"=="full" (
    call :log_info "执行完整流程..."
    python main.py full
)

if errorlevel 1 (
    call :log_error "操作失败"
    pause
    exit /b 1
) else (
    call :log_info "操作完成"
)

pause
goto :eof

REM 调用主函数
call :main %*