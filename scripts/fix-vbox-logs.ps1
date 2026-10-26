<#
.SYNOPSIS
    补建 eNSP 虚拟机目录缺失的 Logs 子目录并授权（通用版，自动定位虚拟机目录）。

.DESCRIPTION
    只处理 Logs 目录这一项，等价于：.\fix-ensp40.ps1 -Task Logs。
    虚拟机目录从 %USERPROFILE%\.VirtualBox\VirtualBox.xml 读取，读不到才限量搜索磁盘，
    脚本内不写死任何盘符或安装路径。日志写 %TEMP%\ensp40-fix-<时间>.log。

.PARAMETER WhatIf
    只诊断，不做任何修改。

.PARAMETER Yes
    不做交互确认，直接修复。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\fix-vbox-logs.ps1
    powershell -ExecutionPolicy Bypass -File .\fix-vbox-logs.ps1 -WhatIf

.NOTES
    需要管理员权限（主脚本会自行提权）。
#>
[CmdletBinding()]
param(
    [switch]$WhatIf,
    [switch]$Yes
)

$main = Join-Path $PSScriptRoot 'fix-ensp40.ps1'
if (-not (Test-Path $main)) {
    Write-Host "找不到主脚本：$main" -ForegroundColor Red
    exit 1
}

& $main -Task Logs -WhatIf:$WhatIf -Yes:$Yes
exit $LASTEXITCODE
