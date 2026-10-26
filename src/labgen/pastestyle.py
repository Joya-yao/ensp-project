"""把命令块转成「粘贴安全」样式。

eNSP 命令行有一个坏习惯：粘贴时多出来一个换行，控制台可能把上一条命令再执行一次。
如果上一条正好是收尾的 ``quit``，视图就从 ``[LSW1]`` 掉到 ``<LSW1>``，后面全报
``Error: Unrecognized command found at '^' position``，整段粘贴作废。

安全样式把每个顶层块结尾的 ``quit`` 换成 ``return`` + ``system-view``：

- ``return`` 一定回到用户视图，不依赖当前在第几层
- ``system-view`` 一定回到系统视图
- 两个命令在系统视图下执行都没有副作用，即使多执行一次也只是绕一圈

嵌套块（例如 ``ospf`` 下面的 ``area``）仍然用 ``quit``，退早了会中断后续配置。
"""

from __future__ import annotations

__all__ = ["to_safe_paste", "VIEW_STARTS"]

# 这些命令会进入一个新的子视图
VIEW_STARTS = (
    "interface ",
    "vlan ",
    "acl number ",
    "ospf ",
    "area ",
    "stp region-configuration",
    "dhcp",
)


def _opens_view(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "return", "system-view", "quit")):
        return False
    if stripped.startswith("stp mode"):
        return False
    return stripped.startswith(VIEW_STARTS)


def to_safe_paste(commands: list[str]) -> list[str]:
    """顶层 ``quit`` → ``return`` + ``system-view``，嵌套 ``quit`` 保留。"""

    out: list[str] = []
    depth = 0

    for line in commands:
        stripped = line.strip()

        if stripped == "quit":
            depth = max(depth - 1, 0)
            if depth == 0:
                out.append("return")
                out.append("system-view")
            else:
                out.append(line)
            continue

        out.append(line)
        if _opens_view(line):
            depth += 1

    return out
