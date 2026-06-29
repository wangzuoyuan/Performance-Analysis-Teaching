@echo off
chcp 65001 >nul
cd /d "%~dp0"
python run.py init
echo.
pause
