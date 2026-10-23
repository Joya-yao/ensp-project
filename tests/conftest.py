"""测试用的合成拓扑。

仓库里不放真实的 eNSP 工程文件；测试用的 `.topo` 由这里现写现用。
结构（设备、接口、连线）与 eNSP 导出的格式一致，仅用于验证解析与生成。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from labgen.topo import parse_topo

TOPO_XML = """<?xml version="1.0" encoding="UNICODE" ?>
<topo version="1.3.00.100">
    <devices>
        <dev id="SYN-AR1" name="AR1" poe="0" model="AR2220" settings="" system_mac="00-E0-FC-00-00-01" com_port="2000" bootmode="1" cx="348.000000" cy="210.000000" edit_left="375" edit_top="264">
            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="1" />
                <interface sztype="Ethernet" interfacename="GE" count="2" />
            </slot>
        </dev>
        <dev id="SYN-AR2" name="AR2" poe="0" model="AR2220" settings="" system_mac="00-E0-FC-00-00-02" com_port="2001" bootmode="1" cx="569.000000" cy="205.000000" edit_left="596" edit_top="259">
            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="1" />
                <interface sztype="Ethernet" interfacename="GE" count="2" />
            </slot>
        </dev>
        <dev id="SYN-LSW1" name="LSW1" poe="0" model="S5700" settings="" system_mac="00-E0-FC-00-00-03" com_port="2002" bootmode="1" cx="448.000000" cy="355.000000" edit_left="475" edit_top="409">
            <slot number="slot17" isMainBoard="1">
                <interface sztype="Ethernet" interfacename="GE" count="24" />
            </slot>
        </dev>
    </devices>
    <lines>
        <line srcDeviceID="SYN-LSW1" destDeviceID="SYN-AR1">
            <interfacePair lineName="Copper" srcIndex="0" srcBoundRectIsMoved="0" srcBoundRect_X="450.0" srcBoundRect_Y="346.0" srcOffset_X="0" srcOffset_Y="0" tarIndex="0" tarBoundRectIsMoved="0" tarBoundRect_X="399.0" tarBoundRect_Y="272.0" tarOffset_X="0" tarOffset_Y="0" />
        </line>
        <line srcDeviceID="SYN-LSW1" destDeviceID="SYN-AR2">
            <interfacePair lineName="Copper" srcIndex="1" srcBoundRectIsMoved="0" srcBoundRect_X="502.0" srcBoundRect_Y="348.0" srcOffset_X="0" srcOffset_Y="0" tarIndex="0" tarBoundRectIsMoved="0" tarBoundRect_X="568.0" tarBoundRect_Y="265.0" tarOffset_X="0" tarOffset_Y="0" />
        </line>
    </lines>
    <shapes />
    <txttips />
</topo>
"""


@pytest.fixture(scope="session")
def topo_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("topo") / "synthetic.topo"
    path.write_text(TOPO_XML, encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def topo(topo_path):
    return parse_topo(topo_path)
