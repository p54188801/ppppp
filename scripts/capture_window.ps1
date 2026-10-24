# Capture a window by title (ASCII only: PS 5.1 may read BOM-less UTF-8 as ANSI)
param(
    [string]$TitleLike = 'EduFlow*',
    [string]$OutFile = 'D:\deepseek\projects\eduflow\docs\screenshots\00-window.png'
)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PW {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$proc = Get-Process | Where-Object { $_.MainWindowTitle -like $TitleLike } | Select-Object -First 1
if (-not $proc) { Write-Output 'NO_WINDOW'; exit 1 }

$h = $proc.MainWindowHandle
[PW]::ShowWindow($h, 9) | Out-Null
[PW]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 1500

$r = New-Object PW+RECT
[PW]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left
$hh = $r.Bottom - $r.Top
if ($w -lt 400 -or $hh -lt 300) {
    Write-Output "TOO_SMALL ${w}x${hh}"
    exit 2
}

$bmp = New-Object System.Drawing.Bitmap($w, $hh)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [PW]::PrintWindow($h, $hdc, 2)
$g.ReleaseHdc($hdc)
$g.Dispose()
$bmp.Save($OutFile, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output "PRINTED $ok ${w}x${hh}"
