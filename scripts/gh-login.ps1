# GitHub CLI 登录助手（自动带着代理）
$ErrorActionPreference = 'Continue'
$gh = 'C:\Program Files\GitHub CLI\gh.exe'
$env:HTTPS_PROXY = 'http://127.0.0.1:7897'
$env:HTTP_PROXY  = 'http://127.0.0.1:7897'
$env:NO_PROXY    = 'localhost,127.0.0.1,::1'

try { $Host.UI.RawUI.WindowTitle = 'GitHub CLI 登录' } catch { }

Write-Host ''
Write-Host '  GitHub CLI 登录' -ForegroundColor White -BackgroundColor DarkGray
Write-Host ''
Write-Host '  1. 终端会显示 8 位一次性代码（同时已复制到剪贴板）' -ForegroundColor Cyan
Write-Host '  2. 按 Enter，浏览器自动打开'
Write-Host '  3. 粘贴代码 -> Authorize 授权'
Write-Host ''

& $gh auth login --hostname github.com --git-protocol https --web --clipboard

Write-Host ''
& $gh auth setup-git
& $gh auth status
if ($LASTEXITCODE -eq 0) {
    Write-Host ''
    Write-Host '  登录成功！可以关闭此窗口了，接下来直接 git push 即可。' -ForegroundColor Green
} else {
    Write-Host ''
    Write-Host '  未登录成功，可重新运行：gh auth login' -ForegroundColor Yellow
}
Write-Host ''
