# 一键打包：构建前端 -> 收集后端 -> 生成可分发目录
# 用法：powershell -ExecutionPolicy Bypass -File scripts/package.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root 'dist\EduFlow'
$nodeDir = 'D:\deepseek\Node'

Write-Host '==> 1/4 构建前端' -ForegroundColor Cyan
Push-Location (Join-Path $root 'frontend')
$env:Path = "$nodeDir;$env:Path"

if (-not (Test-Path (Join-Path $root 'frontend\node_modules'))) {
    Write-Host '   安装前端依赖...'
    & "$nodeDir\npm.cmd" install --no-audit --no-fund
}
& "$nodeDir\npm.cmd" run build
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
Pop-Location

Write-Host '==> 2/4 准备输出目录' -ForegroundColor Cyan
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force -Path $out | Out-Null

Write-Host '==> 3/4 复制后端与产物' -ForegroundColor Cyan
Copy-Item (Join-Path $root 'backend') $out -Recurse
Copy-Item (Join-Path $root 'run.py') $out
Copy-Item (Join-Path $root 'requirements.txt') $out
Copy-Item (Join-Path $root 'README.md') $out

$dist = Join-Path $root 'frontend\dist'
if (-not (Test-Path $dist)) { throw '未找到前端构建产物' }
New-Item -ItemType Directory -Force -Path (Join-Path $out 'frontend') | Out-Null
Copy-Item $dist (Join-Path $out 'frontend') -Recurse

# 清掉缓存文件
Get-ChildItem $out -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem $out -Recurse -File -Filter '*.pyc' | Remove-Item -Force

Write-Host '==> 4/4 生成启动脚本' -ForegroundColor Cyan
$launcher = @'
@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" run.py
) else (
    echo 首次运行请先执行：python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
)
'@
Set-Content -Path (Join-Path $out '启动.bat') -Value $launcher -Encoding OEM

$size = [math]::Round((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "打包完成：$out  ($size MB)" -ForegroundColor Green
