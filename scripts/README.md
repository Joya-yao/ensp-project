# eNSP 错误 40 修复脚本（通用版）

eNSP 里设备（路由器/交换机）启动失败、报错 40，多数情况是 VirtualBox 这一层出的问题。这组脚本把能自动修的几类问题一次处理掉，修不了的（虚拟化相关、大版本不兼容）给出明确结论，并在下面「手动处理」一节写清楚要改哪个开关。

通用版：脚本里**没有写死的盘符或安装目录**，换机器、换安装位置、换 eNSP 版本都能直接用。

## 三个入口

| 脚本 | 做什么 | 等价写法 |
| --- | --- | --- |
| `fix-ensp40.ps1` | 全量诊断 + 修复（默认） | — |
| `fix-vbox-drv.ps1` | 只修 VBoxDrv 驱动服务 | `fix-ensp40.ps1 -Task Drv` |
| `fix-vbox-logs.ps1` | 只修虚拟机目录的 Logs 子目录 | `fix-ensp40.ps1 -Task Logs` |

Host-Only 网卡单独处理：`fix-ensp40.ps1 -Task Net`。

## 双击启动（推荐给不熟命令行的人）

仓库根目录（或解压出来的文件夹根目录）有两个 `.bat`，**双击就能跑**，跑完窗口会停住等回车：

| 文件 | 作用 |
| --- | --- |
| `双击修复.bat` | 诊断 + 自动修复 |
| `双击诊断.bat` | 只看会改什么，不实际修改（`-WhatIf`） |

前提：`.bat` 必须和 `scripts` 文件夹放在同一层，别把 bat 单独拷走。

## 命令行用法

右键 `fix-ensp40.ps1` → **使用 PowerShell 运行**；或者：

```powershell
powershell -ExecutionPolicy Bypass -File .\fix-ensp40.ps1
```

- 需要管理员权限，脚本自己弹 UAC 提权。
- 先看结论再动手：加 `-WhatIf` 只诊断，不修改任何东西。
- 批量分发、不想交互：加 `-Yes`。
- 只修某一项：用 `-Task Drv` / `-Task Logs`，或者直接跑对应的单功能脚本。
- 每次实际修复（不加 `-WhatIf`）都会在 `%TEMP%\ensp40-fix-<时间>.log` 留日志，也可以用 `-LogPath` 指定位置。
- 退出码：`0` 正常或已修复，`1` 提权被拒绝，`2` 还有需要人工处理的问题。

## 自动修什么

| 问题 | 表现 | 处理 |
| --- | --- | --- |
| `VBoxDrv` 服务指向的驱动文件不存在 | 驱动状态 STOPPED，任何虚拟机都起不来 | 在安装目录里找到 `VBoxDrv.sys`，改服务路径并启动 |
| `VBoxDrv` 没启动 | 同上 | 启动服务并回读状态确认 |
| `VBoxNetAdp` / `VBoxNetLwf` / `VBoxUSBMon` 没运行 | 网卡创建失败、USB 设备异常 | 逐个启动并确认 RUNNING |
| 虚拟机目录缺 `Logs` 子目录 | VBox 报 `VERR_PATH_NOT_FOUND`，eNSP 只显示启动失败 | 补建目录；权限不足时先取所有权再授权 |
| Host-Only 网卡缺失 | eNSP 设备间无法互通 | `VBoxManage hostonlyif create` 创建，并配 `192.168.56.1/24` |
| Host-Only 网卡被禁用 | 同上 | `Enable-NetAdapter` 启用 |
| Host-Only 网卡没有 IPv4 | 同上 | 自动挑一个未占用的 `192.168.x.1/24` 配置 |
| Hyper-V 占用 VT-x | VirtualBox 报 VT-x 不可用 | 执行 `bcdedit /set hypervisorlaunchtype off`，结论里提示重启 |

> 关 Hyper-V 会连带影响 WSL2、Docker Desktop、部分安卓模拟器。想恢复：`bcdedit /set hypervisorlaunchtype auto` 后重启。

## 只诊断不修什么

| 问题 | 结论 |
| --- | --- |
| VT-x 没开 | BIOS/UEFI 设置，脚本无法代劳 |
| VirtualBox 7.x | 大版本不兼容，需要卸载后装 5.2.44 或 6.0.24 |
| 内存完整性（内核隔离）开着 | 脚本**不检测**这一项；表现是 `VBoxDrv` 启动失败、错误码 577，需要在 Windows 安全中心手动关（见下面第 4 条） |
| 提权被拒（退出码 1） | UAC 弹窗点了「否」，需要手动以管理员身份重跑 |

## 手动处理（脚本修不了的部分）

下面几项都要动系统设置或重装软件，脚本只报告结论，不代为执行。按报错对症往下翻。

### 1. VT-x / AMD-V 没开（BIOS/UEFI）

症状：脚本结论里出现「VT-x 未开启」；VirtualBox 报 `VT-x is not available (VERR_VMX_NO_VMX)`。

1. 重启电脑，开机按进 BIOS 的键（常见 `Del`、`F2`、`F10`、`Esc`，笔记本多为 `F2` 或 `Fn+F2`）。
2. 打开虚拟化选项：
   - Intel 平台：`Intel Virtualization Technology`（VT-x）、`Intel VT-d`（开 VT-d 更稳）
   - AMD 平台：`SVM Mode` 或 `AMD-V`
   - 位置一般在 `Advanced` / `CPU Configuration` / `Security` 下，有的机器叫 `Virtualization Technology`。
3. 保存退出（`F10` → Save & Exit）。
4. 进系统后验证：任务管理器 → 性能 → CPU → 右下角「虚拟化：已启用」。这一步没到「已启用」，脚本怎么跑都没用。

### 2. VirtualBox 7.x（大版本不兼容）

症状：脚本报「VirtualBox 7.x 与 eNSP 不兼容」；装的是 7.0/7.1。

eNSP 只认 5.2.x / 6.0.x。改法二选一：

1. 控制面板 → 程序和功能 → 卸载 `Oracle VM VirtualBox`（7.x），顺手把 eNSP 也卸了。
2. 重启，然后二选一：
   - 重装 eNSP 安装包（安装时会自带配套 VirtualBox 5.2.x）；
   - 或先单独装 `VirtualBox 5.2.44`，再装 eNSP，安装时跳过自带 VirtualBox。
3. 装完验证版本：`"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" --version`，应显示 `5.2.44` 或 `6.0.x`。
4. 不要用 7.x 的「升级」按钮，也不要点软件内的更新提示。

### 3. 关 Hyper-V 需要重启（脚本已改开关，重启才算完）

症状：脚本已执行 `bcdedit /set hypervisorlaunchtype off`，但设备仍然起不来。

1. 重启电脑（这一步不能省，设置只在开机时生效）。
2. 重启后确认开关：管理员 PowerShell 里 `bcdedit /enum | findstr hypervisor`，应看到 `hypervisorlaunchtype    Off`。
3. 还要检查「Windows 功能」里这三项是否已取消勾选：`Hyper-V`、`虚拟机平台`、`Windows 虚拟机监控程序平台`。取消后重启。
4. 需要恢复 WSL2 / Docker Desktop：`bcdedit /set hypervisorlaunchtype auto`，再把上面三项勾回来，重启。

### 4. 内存完整性（内核隔离）拦住 VBoxDrv

症状：`VBoxDrv` 明明存在也启动不了，服务状态反复回到 STOPPED；`VBox.log` 里有签名或驱动加载失败。

1. Windows 安全中心 → 设备安全性 → 内核隔离详细信息。
2. 把「内存完整性」关掉，重启。
3. 验证：`sc query VBoxDrv`，应显示 `RUNNING`。
4. 想再打开内存完整性，得先确认 VirtualBox 版本与驱动签名都正常。

### 5. bcdedit 执行失败 / 被拒绝访问

症状：脚本报「设置 hypervisorlaunchtype 失败」或 `无法打开启动配置数据存储`。

1. 开始菜单搜 `PowerShell` → 右键 → **以管理员身份运行**（脚本提权失败时最常见的坑）。
2. 手动执行：`bcdedit /set hypervisorlaunchtype off`。
3. 回读确认：`bcdedit /enum {current} | findstr hypervisor`。
4. 被安全软件拦时，先退出安全软件或把 `bcdedit.exe` 加白名单再执行。

### 6. 提权被拒（退出码 1）

症状：脚本一启动就退出，退出码 `1`，什么都没改。

1. 找到 `双击修复.bat`，右键 → **以管理员身份运行**。
2. 或在管理员 PowerShell 里：`powershell -ExecutionPolicy Bypass -File .\scripts\fix-ensp40.ps1 -Yes`。
3. UAC 弹窗要点「是」；点了「否」等于没跑。

### 7. Host-Only 网卡要手工配（IP 冲突 / 没有可用地址）

症状：脚本报「找不到可用的 `192.168.x.1` 地址」或设备之间 ping 不通。

1. `Win + R` → 输入 `ncpa.cpl` → 回车。
2. 找到 `VirtualBox Host-Only Ethernet Adapter`（可能带 `#2` 后缀），右键 → 属性。
3. 双击「Internet 协议版本 4 (TCP/IPv4)」→ 使用下面的 IP 地址：
   - IP：`192.168.56.1`（被占用就换 `192.168.57.1`）
   - 子网掩码：`255.255.255.0`
   - 网关和 DNS 留空
4. 网卡列表里没有这张卡：打开 VirtualBox 管理器 → 文件 → 主机网络管理器（Host Network Manager）→ 创建，再回来配 IP。
5. 配完在 eNSP 里重启设备；同一台机器上所有 Host-Only 网卡只能有一张配 `192.168.56.1`。

### 8. 脚本找不到 VirtualBox

症状：脚本报「没有找到 VirtualBox」，或磁盘扫描很慢。

1. 先确认装的是 5.2.x / 6.0.x，不是 7.x。
2. 手动给脚本一个路径提示：设置用户环境变量 `VBOX_INSTALL_PATH`，值填安装目录，例如 `C:\Program Files\Oracle\VirtualBox`。
3. 确认注册表 `HKLM\SOFTWARE\Oracle\VirtualBox` 下的 `InstallDir` 正确（32 位 eNSP 可能落在 `WOW6432Node` 下）。
4. 都正常还找不到，说明 VirtualBox 装坏了：卸载重装。

### 9. 修完还报 40

1. 完全退出 eNSP（任务管理器里确认没有 `eNSP.exe`），再重新打开，重新拖一台设备启动。
2. 在 VirtualBox 管理器里直接启动那台虚拟机，看 VirtualBox 自己的报错——那里比 eNSP 的「错误 40」详细得多。
3. 打开虚拟机目录下的 `Logs\VBox.log`，搜 `VERR_` 或 `error`，最后 20 行通常能直接定位。
4. 确认 eNSP 安装目录里的设备镜像完整；设备镜像缺失时，脚本层面怎么修都不会好，需要重装 eNSP。
5. 都不行就回退到 VirtualBox `5.2.44`，这是与 eNSP 兼容性最好的版本。

## 脚本怎么找路径

依次尝试，命中即用；都不命中才扫描磁盘（会提示较慢）。

VirtualBox 安装目录：

1. 注册表 `HKLM\SOFTWARE\Oracle\VirtualBox`（含 `WOW6432Node`）的 `InstallDir`
2. 环境变量 `VBOX_INSTALL_PATH` / `VBOX_MSI_INSTALL_PATH`
3. 卸载列表里显示名含 `VirtualBox` 的 `InstallLocation`
4. `VBoxDrv` 服务当前驱动路径往上三级反推
5. `Program Files` / `Program Files (x86)` 下的 `Oracle\VirtualBox`
6. 各固定磁盘的常见相对路径
7. `PATH` 里的 `VBoxManage.exe`
8. 各固定磁盘限量搜索 `VBoxManage.exe`

虚拟机目录：

1. `%USERPROFILE%\.VirtualBox\VirtualBox.xml` 里的设备记录（`src`）和 `defaultMachineFolder`
2. 各固定磁盘限量搜索 `VBoxServer` 目录下的 `*.vbox`

## 适用范围

- Windows 10 / 11，PowerShell 5.1 及以上。
- VirtualBox 5.2 / 6.0 / 6.1（eNSP 常见配套版本）。
- eNSP 任意安装位置；不依赖某个盘符下的固定目录（如 `D:\...`）。
