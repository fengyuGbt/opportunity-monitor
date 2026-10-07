#!/bin/bash
# 海外机会雷达运行包装：自动带上 Telegram 代理（远程台式机 Clash 在宿主机 7890 端口）
# 用法: ./run_opp.sh [--dry-run]
cd /home/erp/opportunity-monitor || exit 1
export TELEGRAM_PROXY="${TELEGRAM_PROXY:-http://172.29.224.1:7890}"
exec venv/bin/python monitor.py "$@"
