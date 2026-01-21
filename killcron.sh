#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FILE="$PROJECT_DIR/logs/run_cron.lock"

kill_tree() {
  local pid="$1"
  local sig="$2"
  local children
  children="$(pgrep -P "$pid" 2>/dev/null || true)"
  if [ -n "$children" ]; then
    while IFS= read -r cpid; do
      [ -n "$cpid" ] || continue
      kill_tree "$cpid" "$sig"
    done <<< "$children"
  fi
  kill "-$sig" "$pid" 2>/dev/null || true
}

is_running() {
  local pid="$1"
  ps -p "$pid" >/dev/null 2>&1
}

if [ ! -f "$LOCK_FILE" ]; then
  echo "lock file not found: $LOCK_FILE"
  exit 1
fi

PID="$(cat "$LOCK_FILE" 2>/dev/null || true)"
if [ -z "$PID" ]; then
  echo "lock file is empty: $LOCK_FILE"
  rm -f "$LOCK_FILE"
  exit 1
fi

if ! is_running "$PID"; then
  echo "process not running: $PID"
  rm -f "$LOCK_FILE"
  exit 0
fi

echo "killing cron job pid=$PID"
ps -o pid,ppid,pgid,command -p "$PID" || true

kill_tree "$PID" TERM
sleep 2

if is_running "$PID"; then
  echo "still running, force kill pid=$PID"
  kill_tree "$PID" KILL
  sleep 1
fi

if ! is_running "$PID"; then
  rm -f "$LOCK_FILE"
  echo "killed and removed lock: $LOCK_FILE"
else
  echo "failed to kill pid=$PID (still running)"
  exit 2
fi

