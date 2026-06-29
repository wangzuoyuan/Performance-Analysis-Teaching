#!/bin/bash
set -u
cd "$(dirname "$0")" || exit 1
python3 run.py start
status=$?

echo ""
if [ "$status" -eq 0 ]; then
  echo "可以关闭这个窗口，成绩分析应用会继续在后台运行。"
else
  echo "启动失败，退出码: $status"
  echo "可查看日志:"
  echo "  $HOME/.exam-tracker/backend.log"
  echo "  $HOME/.exam-tracker/frontend.log"
fi
echo ""
read -n 1 -s -r -p "按任意键关闭窗口..."
echo ""
exit "$status"
