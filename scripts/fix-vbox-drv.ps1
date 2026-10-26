<#
.SYNOPSIS
    修复 VirtualBox 驱动服务 VBoxDrv 指向的驱动文件缺失（通用版，自动定位安装目录）。

.DESCRIPTION
    只处理驱动这一项，等价于：.\fix-ensp40.ps1 -Task Drv。
    VirtualBox 安装目录、VBoxDrv.sys 副本的位置都由主脚本自动定位，
    脚本内不写死任何盘符或安装路径。日志写 %TEMP%\ensp40-fix-<时间>.log。

.PARAMETER WhatIf
    只诊断，不做任何修改。

.PARAMETER Yes
    不做交互确认，直接修复。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\fix-vbox-drv.ps1
    powershell -ExecutionPolicy Bypass -File .\fix-vbox-drv.ps1 -WhatIf

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

& $main -Task Drv -WhatIf:$WhatIf -Yes:$Yes
exit $LASTEXITCODE
