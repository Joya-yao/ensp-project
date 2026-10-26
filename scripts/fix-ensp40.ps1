<#
.SYNOPSIS
    eNSP 设备启动失败（错误 40）诊断与修复，通用版：脚本内不写死任何盘符或安装路径。

.DESCRIPTION
    自动定位 VirtualBox 安装目录、驱动副本、虚拟机目录，检查并修复：
      1. VBoxDrv 内核驱动服务指向的文件不存在 → 改指向安装目录里的驱动副本并启动服务
      2. VBoxNetAdp / VBoxNetLwf / VBoxUSBMon 驱动未运行 → 逐个启动
      3. 虚拟机目录缺少 Logs 子目录 → 补建目录（权限不足时先取所有权再授权）
      4. Host-Only 网卡缺失 → 用 VBoxManage 创建并配上 192.168.56.1/24
      5. Host-Only 网卡被禁用或没有 IPv4 → 启用并补配地址
    只剩 VT-x 开关（BIOS 设置）和 VirtualBox 大版本不兼容无法自动处理，会如实报告。
    Hyper-V 会直接执行 bcdedit /set hypervisorlaunchtype off，并在结论里提示重启。

    定位顺序（依次尝试，命中即用）：
      VirtualBox 安装目录：
        注册表 Oracle\VirtualBox\InstallDir → 环境变量 VBOX_INSTALL_PATH /
        VBOX_MSI_INSTALL_PATH → 卸载项 InstallLocation → VBoxDrv 服务路径反推 →
        Program Files 常见目录 → 各磁盘常见相对路径 → PATH → 各磁盘限量搜索 VBoxManage.exe
      虚拟机目录：
        %USERPROFILE%\.VirtualBox\VirtualBox.xml 里的设备记录与 defaultMachineFolder →
        各磁盘限量搜索 VBoxServer 目录下的 .vbox 文件

.PARAMETER Task
    All（默认）：全部检查与修复。
    Drv：只处理 VBoxDrv 驱动服务。
    Logs：只处理虚拟机目录缺少 Logs 的问题。
    Net：只处理 Host-Only 网卡（创建、启用、配 IP）。

.PARAMETER WhatIf
    只诊断，不做任何修改。

.PARAMETER Yes
    不做交互确认，直接修复（适合分发给别人批量跑）。

.PARAMETER LogPath
    自定义日志文件路径；默认写到 %TEMP%\ensp40-fix-<时间>.log。

.PARAMETER Pause
    结束后停住等回车，双击 .bat 启动时用，避免窗口一闪而过。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\fix-ensp40.ps1
    powershell -ExecutionPolicy Bypass -File .\fix-ensp40.ps1 -WhatIf
    powershell -ExecutionPolicy Bypass -File .\fix-ensp40.ps1 -Task Drv -Yes

.NOTES
    需要 Windows + 管理员权限（脚本会自行提权）。
    适用 VirtualBox 5.2 / 6.0 / 6.1；VirtualBox 7.x 与 eNSP 不兼容，只能提示不能修。
    脚本不含写死的盘符或安装目录，换机器、换安装位置都能直接用。
#>
[CmdletBinding()]
param(
    [ValidateSet('All', 'Drv', 'Logs', 'Net')]
    [string]$Task = 'All',
    [switch]$WhatIf,
    [switch]$Yes,
    [string]$LogPath,
    [switch]$Pause
)

$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------- 输出与统计
$script:Fixed = New-Object System.Collections.ArrayList
$script:Problems = New-Object System.Collections.ArrayList
$script:Notes = New-Object System.Collections.ArrayList
$script:Skipped = 0
$script:NeedReboot = $false
$script:VBox = $null
$script:VBoxDir = $null
$script:VBoxManage = $null
$script:LogFile = $null

function Write-Section([string]$Text) {
    Write-Host ""
    Write-Host "== $Text ==" -ForegroundColor Cyan
}
function Write-Ok([string]$Text)   { Write-Host "  [正常] $Text" -ForegroundColor Green }
function Write-Fix([string]$Text)  { Write-Host "  [已修] $Text" -ForegroundColor Yellow; [void]$script:Fixed.Add($Text) }
function Write-Bad([string]$Text)  { Write-Host "  [问题] $Text" -ForegroundColor Red; [void]$script:Problems.Add($Text) }
function Write-Note([string]$Text) { Write-Host "  [说明] $Text" -ForegroundColor Gray; [void]$script:Notes.Add($Text) }

# ---------------------------------------------------------------- 定位工具函数
function Get-RegValue([string]$Path, [string]$Name) {
    if (-not (Test-Path $Path)) { return $null }
    try {
        $value = (Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop).$Name
        if ($value) { return ([string]$value).Trim() }
    } catch { }
    return $null
}

function Get-FixedDrives {
    try {
        $disks = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction Stop
        $roots = @($disks | ForEach-Object { $_.DeviceID + '\' })
        if ($roots.Count -gt 0) { return $roots }
    } catch { }
    return @(($env:SystemDrive) + '\')
}

# 在卸载列表里按显示名找安装位置：任何机器、任何安装盘都适用
function Get-UninstallLocation([string]$Pattern) {
    $roots = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($item in Get-ChildItem $root -ErrorAction SilentlyContinue) {
            $props = Get-ItemProperty -Path $item.PSPath -ErrorAction SilentlyContinue
            if (-not $props -or -not $props.DisplayName) { continue }
            if ($props.DisplayName -notlike $Pattern) { continue }
            $location = $props.InstallLocation
            if (-not $location -and $props.DisplayIcon) {
                $icon = ($props.DisplayIcon -split ',')[0].Trim().Trim('"')
                if ($icon) { $location = Split-Path -Path $icon -Parent }
            }
            if ($location -and (Test-Path $location)) { return $location.TrimEnd('\') }
        }
    }
    return $null
}

# 各磁盘限量搜索，只在前面所有办法都失败时用，比较慢
function Find-UnderDrives {
    param(
        [string]$Filter,
        [int]$Depth = 3,
        [switch]$Directory,
        [switch]$File
    )
    $result = New-Object System.Collections.ArrayList
    foreach ($root in Get-FixedDrives) {
        $items = $null
        try {
            $items = Get-ChildItem -Path $root -Filter $Filter -Recurse -Depth $Depth -Force -ErrorAction SilentlyContinue
        } catch { continue }
        foreach ($item in $items) {
            if ($Directory -and -not $item.PSIsContainer) { continue }
            if ($File -and $item.PSIsContainer) { continue }
            [void]$result.Add($item)
        }
    }
    return $result
}

function New-VBoxInfo([string]$Dir, [string]$Manage) {
    $version = $null
    try {
        $version = (& $Manage --version 2>$null | Select-Object -First 1)
    } catch { }
    if (-not $version) {
        $svc = Join-Path $Dir 'VBoxSVC.exe'
        if (Test-Path $svc) { $version = (Get-Item $svc).VersionInfo.FileVersion }
    }
    $major = 0
    if ($version -and $version -match '^(\d+)\.') { $major = [int]$Matches[1] }
    return [pscustomobject]@{
        Dir     = $Dir
        Manage  = $Manage
        Version = $version
        Major   = $major
    }
}

function Get-VBoxInfo {
    $candidates = New-Object System.Collections.ArrayList

    foreach ($key in @('HKLM:\SOFTWARE\Oracle\VirtualBox', 'HKLM:\SOFTWARE\WOW6432Node\Oracle\VirtualBox')) {
        $dir = Get-RegValue -Path $key -Name 'InstallDir'
        if ($dir) { [void]$candidates.Add($dir.TrimEnd('\')) }
    }

    foreach ($name in @('VBOX_INSTALL_PATH', 'VBOX_MSI_INSTALL_PATH')) {
        $dir = [Environment]::GetEnvironmentVariable($name)
        if ($dir) { [void]$candidates.Add($dir.TrimEnd('\')) }
    }

    $dir = Get-UninstallLocation -Pattern '*VirtualBox*'
    if ($dir) { [void]$candidates.Add($dir) }

    # 服务当前指向的驱动通常就在安装目录的 drivers\vboxdrv 下，往上推三级就是安装目录
    $qc = & sc.exe qc VBoxDrv 2>$null
    $binLine = ($qc | Where-Object { $_ -match 'BINARY_PATH_NAME' } | Select-Object -First 1)
    if ($binLine) {
        $bin = ($binLine -split ':', 2)[1].Trim().Trim('"') -replace '^\\\?\?\\', ''
        $dir = Split-Path -Path $bin -Parent
        if ($dir) { $dir = Split-Path -Path $dir -Parent }
        if ($dir) { $dir = Split-Path -Path $dir -Parent }
        if ($dir) { [void]$candidates.Add($dir) }
    }

    foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432)) {
        if ($pf) { [void]$candidates.Add((Join-Path $pf 'Oracle\VirtualBox')) }
    }

    foreach ($drive in Get-FixedDrives) {
        foreach ($rel in @('Oracle\VirtualBox', 'Program Files\Oracle\VirtualBox', 'Program Files (x86)\Oracle\VirtualBox')) {
            [void]$candidates.Add((Join-Path $drive $rel))
        }
    }

    foreach ($dir in $candidates) {
        if (-not $dir) { continue }
        $manage = Join-Path $dir 'VBoxManage.exe'
        if (Test-Path $manage) { return New-VBoxInfo -Dir $dir -Manage $manage }
    }

    $cmd = Get-Command 'VBoxManage.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return New-VBoxInfo -Dir (Split-Path -Path $cmd.Source -Parent) -Manage $cmd.Source }

    Write-Note '注册表、环境变量和常见目录都没找到 VirtualBox，正在各磁盘限量搜索（可能较慢）……'
    $hit = Find-UnderDrives -Filter 'VBoxManage.exe' -Depth 3 -File | Select-Object -First 1
    if ($hit) { return New-VBoxInfo -Dir (Split-Path -Path $hit.FullName -Parent) -Manage $hit.FullName }

    return $null
}

function Find-VBoxDrvSys([string]$VBoxDir) {
    if ($VBoxDir -and (Test-Path $VBoxDir)) {
        foreach ($rel in @('drivers\vboxdrv\VBoxDrv.sys', 'drivers\VBoxDrv.sys', 'VBoxDrv.sys')) {
            $path = Join-Path $VBoxDir $rel
            if (Test-Path $path) { return (Get-Item $path).FullName }
        }
        $found = Get-ChildItem $VBoxDir -Filter 'VBoxDrv.sys' -Recurse -File -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) { return $found.FullName }
    }

    Write-Note '安装目录里没有 VBoxDrv.sys，正在各磁盘限量搜索（可能较慢）……'
    $hit = Find-UnderDrives -Filter 'VBoxDrv.sys' -Depth 4 -File | Select-Object -First 1
    if ($hit) { return $hit.FullName }

    return $null
}

function Get-VBoxMachineFolders {
    $folders = New-Object System.Collections.ArrayList
    $xmlPath = Join-Path $env:USERPROFILE '.VirtualBox\VirtualBox.xml'

    if (Test-Path $xmlPath) {
        try {
            [xml]$doc = Get-Content -Path $xmlPath -Raw -ErrorAction Stop
            foreach ($node in $doc.SelectNodes('//*[@src]')) {
                $dir = Split-Path -Path $node.src -Parent
                if ($dir -and -not $folders.Contains($dir)) { [void]$folders.Add($dir) }
            }
            foreach ($node in $doc.SelectNodes('//*[@defaultMachineFolder]')) {
                $dir = $node.defaultMachineFolder
                if ($dir -and -not $folders.Contains($dir)) { [void]$folders.Add($dir) }
            }
        } catch {
            Write-Note '读 VirtualBox.xml 失败，改用磁盘搜索。'
        }
    }

    if ($folders.Count -eq 0) {
        Write-Note '虚拟机记录里没有设备，正在各磁盘限量搜索 VBoxServer 目录（可能较慢）……'
        foreach ($root in (Find-UnderDrives -Filter 'VBoxServer' -Depth 3 -Directory)) {
            $files = Get-ChildItem $root.FullName -Filter '*.vbox' -Recurse -Depth 1 -File -ErrorAction SilentlyContinue
            foreach ($file in $files) {
                $dir = Split-Path -Path $file.FullName -Parent
                if ($dir -and -not $folders.Contains($dir)) { [void]$folders.Add($dir) }
            }
        }
    }

    return $folders
}

# ---------------------------------------------------------------- 权限与日志
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Host 'eNSP 错误 40 诊断修复（通用版）' -ForegroundColor White
Write-Host "时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray

if (-not $isAdmin) {
    if ($WhatIf) {
        Write-Note '当前不是管理员，-WhatIf 只读取状态，能看到的检查项会跳过写入类验证。'
    } else {
        Write-Host '需要管理员权限，正在提权……' -ForegroundColor Yellow
        $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Task', $Task)
        if ($Yes) { $argList += '-Yes' }
        if ($LogPath) { $argList += @('-LogPath', "`"$LogPath`"") }
        if ($Pause) { $argList += '-Pause' }
        try {
            Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $argList | Out-Null
        } catch {
            Write-Host '提权被拒绝，退出。' -ForegroundColor Red
            exit 1
        }
        exit 0
    }
}

if (-not $WhatIf) {
    if (-not $LogPath) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $LogPath = Join-Path $env:TEMP "ensp40-fix-$stamp.log"
    }
    try {
        Start-Transcript -Path $LogPath -Force | Out-Null
        $script:LogFile = $LogPath
    } catch { }
}

$running = @(Get-Process -Name 'eNSP', 'VirtualBox' -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    Write-Note '检测到 eNSP 或 VirtualBox 正在运行，修驱动前建议先完全退出再运行本脚本。'
}

# ---------------------------------------------------------------- 检查 0：VirtualBox 安装
if ($Task -ne 'Logs') {
    Write-Section 'VirtualBox'
    $script:VBox = Get-VBoxInfo
    if (-not $script:VBox) {
        Write-Bad '没有找到 VirtualBox。请先安装 eNSP 配套的 VirtualBox 5.2.x 或 6.0.x（不要装 7.x）。'
    } else {
        $script:VBoxDir = $script:VBox.Dir
        $script:VBoxManage = $script:VBox.Manage
        Write-Ok "安装目录：$($script:VBox.Dir)"
        if ($script:VBox.Version) {
            Write-Ok "版本：$($script:VBox.Version)"
            if ($script:VBox.Major -ge 7) {
                Write-Bad "VirtualBox $($script:VBox.Major).x 与 eNSP 不兼容，需降级到 5.2.44 或 6.0.24。"
            }
        } else {
            Write-Bad 'VBoxManage 无法读取版本，可能是驱动未启动。'
        }
    }
}

# ---------------------------------------------------------------- 检查 1：VBoxDrv 驱动
function Repair-VBoxDrv {
    Write-Section '内核驱动 VBoxDrv'

    $qc = & sc.exe qc VBoxDrv 2>&1
    if ($LASTEXITCODE -ne 0 -or -not ($qc -match 'BINARY_PATH_NAME')) {
        Write-Bad '系统里没有 VBoxDrv 服务，VirtualBox 安装不完整，需重装 VirtualBox。'
        return
    }

    $binLine = ($qc | Where-Object { $_ -match 'BINARY_PATH_NAME' } | Select-Object -First 1)
    $binPath = (($binLine -split ':', 2)[1]).Trim().Trim('"')
    $drvPath = $binPath -replace '^\\\?\?\\', ''

    if (Test-Path $drvPath) {
        Write-Ok "驱动文件存在：$drvPath"
    } else {
        Write-Bad "驱动文件不存在：$drvPath"
        $found = Find-VBoxDrvSys -VBoxDir $script:VBoxDir
        if (-not $found) {
            Write-Bad '安装目录和磁盘里都找不到 VBoxDrv.sys，需重装 VirtualBox。'
        } elseif ($WhatIf) {
            Write-Note "将把服务指向：$found"
        } else {
            & sc.exe config VBoxDrv binPath= "\??\$found" | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Fix "VBoxDrv 服务已指向 $found"
            } else {
                Write-Bad "修改服务路径失败（sc exit=$LASTEXITCODE），可能被驱动签名策略或安全软件拦截。"
            }
        }
    }

    $status = (& sc.exe query VBoxDrv) -join "`n"
    if ($status -match 'RUNNING') {
        Write-Ok '驱动服务运行中。'
        return
    }

    if ($WhatIf) {
        Write-Note '驱动服务未运行，正式运行会尝试启动。'
        return
    }

    & sc.exe start VBoxDrv | Out-Null
    $status = (& sc.exe query VBoxDrv) -join "`n"
    if ($status -match 'RUNNING') {
        Write-Fix 'VBoxDrv 已启动。'
    } else {
        Write-Bad 'VBoxDrv 启动失败，错误码见上方输出（常见为 577 签名被拦，或安全软件阻止驱动加载）。'
    }
}

# ---------------------------------------------------------------- 检查 1b：其它 VirtualBox 驱动
function Repair-DriverServices {
    Write-Section 'VirtualBox 其它驱动'

    $handled = 0
    foreach ($name in @('VBoxNetAdp', 'VBoxNetLwf', 'VBoxUSBMon')) {
        $qc = & sc.exe query $name 2>&1
        if ($LASTEXITCODE -ne 0 -or -not ($qc -match 'SERVICE_NAME')) {
            Write-Note "系统里没有 $name 服务（部分安装方式不带），跳过。"
            continue
        }
        $handled++

        if ((($qc) -join "`n") -match 'RUNNING') {
            Write-Ok "$name 运行中。"
            continue
        }

        if ($WhatIf) {
            Write-Note "$name 未运行，正式运行会尝试启动。"
            continue
        }

        & sc.exe start $name | Out-Null
        $after = ((& sc.exe query $name) -join "`n")
        if ($after -match 'RUNNING') {
            Write-Fix "$name 已启动。"
        } else {
            Write-Bad "$name 启动失败，错误码见上方输出。"
        }
    }

    if ($handled -eq 0) { Write-Note '没有可处理的 VirtualBox 网络/USB 驱动。' }
}

# ---------------------------------------------------------------- 检查 2：虚拟机日志目录
function Repair-VmLogs {
    Write-Section '虚拟机日志目录'

    $folders = Get-VBoxMachineFolders
    if ($folders.Count -eq 0) {
        Write-Bad '没找到任何虚拟机目录，eNSP 可能未初始化。先打开 eNSP 让它建一次 Base 虚拟机。'
        return
    }
    Write-Ok "找到 $($folders.Count) 个虚拟机目录"

    $missing = @($folders | Where-Object { (Test-Path $_) -and -not (Test-Path (Join-Path $_ 'Logs')) })
    if ($missing.Count -eq 0) {
        Write-Ok '所有虚拟机目录都有 Logs。'
        return
    }

    Write-Bad "$($missing.Count) 个目录缺少 Logs：" + (($missing | ForEach-Object { Split-Path $_ -Leaf }) -join '、')
    if ($WhatIf) {
        Write-Note '正式运行会补建这些 Logs 目录。'
        return
    }

    $failed = @()
    foreach ($folder in $missing) {
        $logs = Join-Path $folder 'Logs'
        try {
            New-Item -ItemType Directory -Path $logs -Force -ErrorAction Stop | Out-Null
        } catch {
            & takeown.exe /f $folder /a /r /d Y | Out-Null
            & icacls.exe $folder /grant "$($env:USERNAME):(OI)(CI)M" /T /C | Out-Null
            try {
                New-Item -ItemType Directory -Path $logs -Force -ErrorAction Stop | Out-Null
            } catch {
                $failed += $folder
            }
        }
    }

    if ($failed.Count -eq 0) {
        Write-Fix "已补建 $($missing.Count) 个 Logs 目录。"
    } else {
        Write-Bad '仍有目录建不了：' + (($failed | ForEach-Object { Split-Path $_ -Leaf }) -join '、')
    }
}

# ---------------------------------------------------------------- 检查 3：CPU 虚拟化
function Test-Virtualization {
    Write-Section 'CPU 虚拟化'
    $cpu = $null
    try {
        $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    } catch {
        Write-Note '读不到 CPU 信息（需要管理员权限），跳过 VT-x 检查。'
        $script:Skipped++
    }
    if ($cpu) {
        if ($cpu.VirtualizationFirmwareEnabled) {
            Write-Ok 'VT-x 已在 BIOS/UEFI 开启。'
        } else {
            Write-Bad 'VT-x 未开启，需进 BIOS 打开 Intel Virtualization Technology（无法用脚本修）。'
        }
    }
}

# ---------------------------------------------------------------- 检查 4：Hyper-V 冲突
function Test-HyperV {
    Write-Section 'Hyper-V 冲突'
    $hypervisor = $null
    try {
        $hypervisor = (Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).HypervisorPresent
    } catch {
        Write-Note '读不到 Hyper-V 状态（需要管理员权限）。'
        $script:Skipped++
    }

    if ($hypervisor -eq $false) {
        Write-Ok 'Hyper-V 未占用 VT-x。'
        return
    }
    if ($hypervisor -ne $true) { return }

    Write-Bad 'Hyper-V 正在运行，VirtualBox 5.2/6.0 会启动失败。'
    Write-Note '关闭 Hyper-V 后 WSL2、Docker Desktop、部分安卓模拟器会不可用；需要恢复时执行 bcdedit /set hypervisorlaunchtype auto。'

    if ($WhatIf) {
        Write-Note '正式运行会执行：bcdedit /set hypervisorlaunchtype off，然后提示重启。'
        return
    }

    & bcdedit.exe /set hypervisorlaunchtype off | Out-Null
    $after = ((& bcdedit.exe /enum '{current}' 2>&1) -join "`n")
    if ($after -match 'hypervisorlaunchtype\s+Off') {
        Write-Fix '已设置 hypervisorlaunchtype = Off，重启后生效。'
        $script:NeedReboot = $true
    } else {
        Write-Bad '设置 hypervisorlaunchtype 失败，请以管理员身份手动执行 bcdedit /set hypervisorlaunchtype off。'
    }
}

# ---------------------------------------------------------------- 检查 5：Host-Only 网卡
function Get-HostOnlyAdapters {
    try {
        return @(Get-NetAdapter -ErrorAction Stop | Where-Object {
            $_.InterfaceDescription -like '*VirtualBox*Host*Only*'
        })
    } catch {
        return $null
    }
}

function Get-FreeHostOnlyIp {
    $used = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
              ForEach-Object { $_.IPAddress })
    foreach ($candidate in @('192.168.56.1', '192.168.57.1', '192.168.58.1')) {
        if ($used -notcontains $candidate) { return $candidate }
    }
    return $null
}

function Repair-HostOnly {
    Write-Section 'Host-Only 网卡'

    $adapters = Get-HostOnlyAdapters
    if ($null -eq $adapters) {
        Write-Note '无法枚举网卡（需要管理员权限），跳过 Host-Only 检查。'
        $script:Skipped++
        return
    }

    if ($adapters.Count -eq 0) {
        Write-Bad '没有 VirtualBox Host-Only 网卡。'
        if (-not $script:VBoxManage) {
            Write-Bad '找不到 VBoxManage，无法自动创建，请重装 VirtualBox。'
            return
        }
        if ($WhatIf) {
            Write-Note '正式运行会用 VBoxManage hostonlyif create 创建网卡并配置 IP。'
            return
        }
        & $script:VBoxManage hostonlyif create 2>&1 | Out-Null
        Start-Sleep -Seconds 3
        $adapters = Get-HostOnlyAdapters
        if (-not $adapters -or $adapters.Count -eq 0) {
            Write-Bad 'Host-Only 网卡创建失败，请重装 VirtualBox 后重试。'
            return
        }
        Write-Fix "已创建 Host-Only 网卡：$($adapters[0].Name)"
    }

    foreach ($adapter in $adapters) {
        if ($adapter.Status -eq 'Disabled') {
            if ($WhatIf) {
                Write-Note "$($adapter.Name) 被禁用，正式运行会启用。"
            } else {
                try {
                    Enable-NetAdapter -Name $adapter.Name -Confirm:$false -ErrorAction Stop
                    Start-Sleep -Seconds 2
                    Write-Fix "已启用网卡 $($adapter.Name)。"
                    $adapter = Get-NetAdapter -Name $adapter.Name -ErrorAction SilentlyContinue
                } catch {
                    Write-Bad "启用网卡 $($adapter.Name) 失败：$($_.Exception.Message)"
                    continue
                }
            }
        }

        if (-not $adapter) { continue }

        $ip = (Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue |
               Select-Object -First 1).IPAddress

        if ($ip) {
            Write-Ok "$($adapter.Name)（$($adapter.InterfaceDescription)）IP=$ip 状态=$($adapter.Status)"
            continue
        }

        $address = Get-FreeHostOnlyIp
        if ($WhatIf) {
            Write-Note "$($adapter.Name) 没有 IPv4，正式运行会配置 $address/24。"
            continue
        }
        if (-not $address) {
            Write-Bad "找不到可用的 192.168.x.1 地址给 $($adapter.Name)，请手动配置。"
            continue
        }
        try {
            New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress $address -PrefixLength 24 -ErrorAction Stop | Out-Null
            Write-Fix "已给 $($adapter.Name) 配置 $address/24。"
        } catch {
            Write-Bad "给 $($adapter.Name) 配置 IP 失败：$($_.Exception.Message)"
        }
    }
}

# ---------------------------------------------------------------- 按任务执行
if ($Task -eq 'All' -or $Task -eq 'Drv') {
    Repair-VBoxDrv
    if ($Task -eq 'All') { Repair-DriverServices }
}
if ($Task -eq 'All' -or $Task -eq 'Logs') { Repair-VmLogs }
if ($Task -eq 'All') {
    Test-Virtualization
    Test-HyperV
}
if ($Task -eq 'All' -or $Task -eq 'Net') { Repair-HostOnly }

# ---------------------------------------------------------------- 汇总
Write-Section '结论'
if ($script:Fixed.Count -gt 0) {
    Write-Host '  本次修复：' -ForegroundColor Yellow
    $script:Fixed | ForEach-Object { Write-Host "   - $_" }
}
if ($script:Problems.Count -gt 0) {
    Write-Host '  仍存在的问题：' -ForegroundColor Red
    $script:Problems | ForEach-Object { Write-Host "   - $_" }
}

if ($script:NeedReboot) {
    Write-Host ''
    Write-Host '  需要重启：Hyper-V 已关闭，重启电脑后才会生效。' -ForegroundColor Yellow
    Write-Host '  重启后直接打开 eNSP 启动设备；要恢复 WSL2/Docker，执行 bcdedit /set hypervisorlaunchtype auto 再重启。' -ForegroundColor DarkGray
}

if ($script:Problems.Count -eq 0 -and $script:Fixed.Count -eq 0 -and $script:Skipped -eq 0) {
    Write-Host '  所有检查项正常。若 eNSP 仍报 40，请重启 eNSP 后再试，并查看虚拟机目录下的 Logs\VBox.log。' -ForegroundColor Green
    $code = 0
} elseif ($script:Problems.Count -eq 0 -and $script:Fixed.Count -eq 0) {
    Write-Host "  已完成的检查项正常，另有 $($script:Skipped) 项因权限跳过；带管理员权限运行可补全检查。" -ForegroundColor Green
    $code = 0
} elseif ($script:Problems.Count -eq 0) {
    if ($script:NeedReboot) {
        Write-Host '  已修复可自动处理的问题；其中 Hyper-V 关闭需要重启后生效，请先重启电脑再启动设备。' -ForegroundColor Yellow
    } else {
        Write-Host '  已修复可自动处理的问题，请重启 eNSP 后重新启动设备。' -ForegroundColor Green
    }
    $code = 0
} else {
    Write-Host '  存在需要人工处理的问题，见上方红色项。' -ForegroundColor Red
    $code = 2
}

if ($script:LogFile) {
    try { Stop-Transcript | Out-Null } catch { }
    Write-Host ''
    Write-Host "日志：$($script:LogFile)" -ForegroundColor DarkGray
}

if ($Pause) {
    Write-Host ''
    Read-Host '按回车键关闭窗口' | Out-Null
}

exit $code
