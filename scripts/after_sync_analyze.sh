#!/usr/bin/env bash
# Garmin 同步 + swim_evidence 算完后调用：入队并处理单次/趋势分析。
# 用法（本机已配置 agent/.env，且能读到证据库）：
#   ./scripts/after_sync_analyze.sh
# 或在 NAS 计划任务里，garmindb 增量命令成功后再跑本脚本（需有 SiliconFlow 网络）。

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/agent"
exec python -m src.cli after-sync "$@"
