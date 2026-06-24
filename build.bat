@echo off
echo === 安装 PyInstaller ===
pip install pyinstaller -q

echo === 开始打包 ===
pyinstaller --onefile --windowed --name "环境检测" main.py

echo === 打包完成 ===
echo exe 文件在 dist\ 目录下
pause
