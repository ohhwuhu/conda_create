@echo off
rem 打包为单个 exe（产物位于 dist\CondaEnvManager.exe）
cd /d "%~dp0"
python -m PyInstaller --onefile --windowed --noconfirm --name CondaEnvManager main.py
echo.
echo 构建完成：dist\CondaEnvManager.exe
pause
