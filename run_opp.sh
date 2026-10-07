#!/bin/bash
# 海外机会雷达运行包装
# 用法: ./run_opp.sh [--dry-run]
cd /home/erp/opportunity-monitor || exit 1
exec venv/bin/python monitor.py "$@"
