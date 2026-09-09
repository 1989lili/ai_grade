# 一键出包：PyInstaller(onedir) + Inno Setup 安装包
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1 -SkipPyInstaller
param(
    [string]$Python = 'D:\miniconda3\envs\python12\python.exe',
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not $SkipPyInstaller) {
    Write-Host '==> PyInstaller (onedir) ...' -ForegroundColor Cyan
    & $Python -m PyInstaller build.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出码 $LASTEXITCODE" }
}

$outDir = Join-Path $root 'dist\AI_Grader'
if (-not (Test-Path (Join-Path $outDir 'AI_Grader.exe'))) {
    throw "找不到 $outDir\AI_Grader.exe，请先执行 PyInstaller 构建"
}

# 定位 ISCC.exe（Inno Setup 6 编译器）
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host '未找到 Inno Setup 6，请先安装：' -ForegroundColor Yellow
    Write-Host '    winget install JRSoftware.InnoSetup' -ForegroundColor Yellow
    Write-Host '或到 https://jrsoftware.org/isdl.php 下载（安装后可重跑本脚本的第三步）' -ForegroundColor Yellow
    exit 2
}

Write-Host "==> Inno Setup: $iscc" -ForegroundColor Cyan
& $iscc (Join-Path $root 'installer.iss')
if ($LASTEXITCODE -ne 0) { throw "ISCC 失败，退出码 $LASTEXITCODE" }

Get-ChildItem (Join-Path $root 'Output\*.exe') |
    Select-Object Name, @{ n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } }, LastWriteTime |
    Format-Table -AutoSize
