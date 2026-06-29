@echo off
chcp 65001 >nul
cd /d "%~dp0"
python run.py start
echo.
if errorlevel 1 (
  echo 启动失败，可查看日志：
  echo   %USERPROFILE%\.exam-tracker\backend.log
  echo   %USERPROFILE%\.exam-tracker\frontend.log
) else (
  echo 可以关闭这个窗口，成绩分析应用会继续在后台运行。
)
echo.
pause
