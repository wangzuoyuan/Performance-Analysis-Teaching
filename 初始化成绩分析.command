#!/bin/bash
set -u
cd "$(dirname "$0")" || exit 1
python3 run.py init
status=$?
echo ""
read -n 1 -s -r -p "按任意键关闭窗口..."
echo ""
exit "$status"
