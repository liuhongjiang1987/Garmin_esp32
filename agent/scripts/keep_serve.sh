#!/usr/bin/env bash
# 模块说明：保活教练 HTTP API（8765），挂掉自动重启，避免表盘「无法加载场次/趋势」。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${COACH_LOG:-/tmp/coach_api.log}"
PIDFILE="${COACH_PIDFILE:-/tmp/coach_api.pid}"
export COACH_BIND="${COACH_BIND:-0.0.0.0}"
export COACH_PORT="${COACH_PORT:-8765}"

cd "$ROOT"
while true; do
  echo "$(date '+%F %T') starting serve bind=${COACH_BIND}:${COACH_PORT}" >>"$LOG"
  # shellcheck disable=SC2094
  uv run python -m src.cli serve >>"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
  wait $! || true
  echo "$(date '+%F %T') serve exited, restart in 2s" >>"$LOG"
  sleep 2
done
