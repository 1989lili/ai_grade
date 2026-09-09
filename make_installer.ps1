# 一键出包：PyInstaller(onedir) + Inno Setup 安装包
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1           # 快速模式(默认)：增量 PyInstaller + lzma2/normal
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1 -Release  # 发布模式：lzma2/ultra64 极限压缩（最小体积，最慢）
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1 -SkipPyInstaller   # 只重打安装包（PyInstaller 产物已最新时）
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1 -FastCompile       # 秒级出包（zip/1，产物 ~234MB，仅供本地快速验证）
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1 -QuickAssets       # 只改前端(html/css/js)时：直接拷入产物，跳过 PyInstaller(41s)
#   powershell -ExecutionPolicy Bypass -File .\make_installer.ps1 -Version 1.0.1     # 指定版本号出包（用户侧会走覆盖升级，无需先卸载）
#
# 提速提示：改的只是前端(index.html/css/js)或 Python 代码但没动依赖时，
#   PyInstaller 增量构建会自动跳过大部分工作；真正的大头是安装包压缩，
#   日常迭代用默认档即可，正式发布再 -Release。
param(
    [string]$Python = 'D:\miniconda3\envs\python12\python.exe',
    [string]$Version = '',
    [switch]$SkipPyInstaller,
    [switch]$QuickAssets,
    [switch]$Release,
    [switch]$FastCompile
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Show-Elapsed([double]$Sec, [string]$Msg) {
    Write-Host ("{0}  →  {1:N0} 秒" -f $Msg, $Sec) -ForegroundColor Green
}

if ($QuickAssets) {
    # 只更新前端资源，跳过整个 PyInstaller（41s 的分析/打包开销）
    $target = Join-Path $root 'dist\AI_Grader\_internal'
    if (-not (Test-Path (Join-Path $target 'base_library.zip'))) {
        throw "dist\AI_Grader\_internal 不存在或不是完整产物，请先不带 -QuickAssets 完整出包一次"
    }
    foreach ($rel in @('index.html', 'css\style.css', 'js\main.js')) {
        $dst = Join-Path $target $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item (Join-Path $root $rel) $dst -Force
    }
    Write-Host '==> 前端资源已直接拷入产物（跳过 PyInstaller）' -ForegroundColor Green
    $SkipPyInstaller = $true
}

if (-not $SkipPyInstaller) {
    Write-Host '==> PyInstaller (onedir, 增量) ...' -ForegroundColor Cyan
    $t = Measure-Command { & $Python -m PyInstaller build.spec --noconfirm }
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败，退出码 $LASTEXITCODE" }
    Show-Elapsed $t.TotalSeconds 'PyInstaller 完成'
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
    exit 2
}

$isccArgs = @()
if ($Version)      { $isccArgs += '/DMyAppVersion=' + $Version }
if ($Release)      { $isccArgs += '/DRelease' }
if ($FastCompile)  { $isccArgs += '/DFastCompile' }

Write-Host '==> Inno Setup ...' -ForegroundColor Cyan
$t = Measure-Command { & $iscc @isccArgs (Join-Path $root 'installer.iss') }
if ($LASTEXITCODE -ne 0) { throw "ISCC 失败，退出码 $LASTEXITCODE" }
Show-Elapsed $t.TotalSeconds ('Inno Setup 完成(' + $(if ($Release) { '极限压缩' } elseif ($FastCompile) { '快速模式' } else { '标准压缩' }) + ')')

Get-ChildItem (Join-Path $root 'Output\*.exe') |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 Name, @{ n = 'MB'; e = { [math]::Round($_.Length / 1MB, 1) } }, LastWriteTime |
    Format-Table -AutoSize
