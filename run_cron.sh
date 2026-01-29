#!/bin/bash

# ==============================================================================
# srt_translate 自动化任务脚本 (适用于 macOS/Linux crontab)
# ==============================================================================

# 1. 设置环境变量
# Crontab 运行时的环境非常精简，必须显式设置 PATH，确保能找到 python3, ffmpeg, ollama 等工具
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export LANG=en_US.UTF-8

# 2. 项目配置
# 获取脚本所在目录的绝对路径，确保从任何地方调用都能定位到项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$PROJECT_DIR/config.json"
LOG_DIR="$PROJECT_DIR/logs"

# 3. 创建日志目录
mkdir -p "$LOG_DIR"

# 获取当前日期，用于日志文件名
DATE=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/cron_$DATE.log"
LOCK_FILE="$LOG_DIR/run_cron.lock"

# 检查是否存在锁文件
if [ -f "$LOCK_FILE" ]; then
    # 检查锁文件中的 PID 是否还在运行
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 上次任务 (PID: $PID) 仍在运行，本次跳过" >> "$LOG_FILE"
        exit 0
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 发现陈旧的锁文件 (PID: $PID)，进程已不存在，继续执行" >> "$LOG_FILE"
    fi
fi

# 创建锁文件，记录当前 PID
echo $$ > "$LOCK_FILE"

# 确保脚本退出时删除锁文件
trap 'rm -f "$LOCK_FILE"' EXIT

echo "========================================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 任务开始" >> "$LOG_FILE"

# 4. 执行任务
# ------------------------------------------------------------------------------
# 切换到项目目录
# ------------------------------------------------------------------------------
cd "$PROJECT_DIR" || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 错误: 无法进入目录 $PROJECT_DIR" >> "$LOG_FILE"
    exit 1
}

# ------------------------------------------------------------------------------
# 任务 A: 字幕翻译 & 自动迁移 (srt_translate with unified orchestrator)
# ------------------------------------------------------------------------------
echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始执行: 字幕翻译与迁移 (srt_translate)" >> "$LOG_FILE"

# 说明: --once 表示运行一次扫描队列后退出
/opt/homebrew/bin/python3 run_srt_translate.py --config "$CONFIG_FILE" --once >> "$LOG_FILE" 2>&1
TRANSLATE_EXIT_CODE=$?

if [ $TRANSLATE_EXIT_CODE -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 任务完成" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 任务异常 (Exit Code: $TRANSLATE_EXIT_CODE)" >> "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 所有任务结束" >> "$LOG_FILE"
echo "========================================================" >> "$LOG_FILE"
