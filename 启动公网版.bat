@echo off
cd /d D:\EduFlow
start "" /min cmd /c ".venv\Scripts\python.exe -m backend.cli serve --host 127.0.0.1 --port 8765 >> data\server.log 2>&1"
timeout /t 3 >nul
start "" /min cmd /c "tools\cloudflared.exe tunnel --url http://127.0.0.1:8765 --no-autoupdate >> data\tunnel.log 2>&1"