@echo off
chcp 65001 >nul
echo ============================================
echo   EduFlow 当前访问地址
echo ============================================
echo.
echo [局域网]
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=1" %%b in ("%%a") do echo   http://%%b:8765
)
echo.
echo [公网]
if exist "D:\EduFlow\data\tunnel.log" (
  powershell -NoProfile -Command "$t = Get-Content 'D:\EduFlow\data\tunnel.log' -Raw; $m = [regex]::Matches($t, 'https://[a-z0-9-]+\.trycloudflare\.com') | ForEach-Object { $_.Value } | Where-Object { $_ -notmatch '://api\.' } | Select-Object -Unique; if ($m) { $m | ForEach-Object { '   ' + $_ } } else { '   （还没有生成隧道地址）' }"
) else (
  echo   （还没有生成隧道地址）
)
echo.
echo [服务状态]
powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:8765/api/health' -UseBasicParsing -TimeoutSec 5; '   后端运行中 ' + $r.StatusCode } catch { '   后端未运行，请双击 启动公网版.bat' }"
echo.
pause