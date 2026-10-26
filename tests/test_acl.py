import tempfile
from pathlib import Path

import pytest

from labgen.docx_writer import build_document
from labgen.generators import build_configs
from labgen.requirements import RequirementError, load_requirements
from labgen.topo import parse_topo

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "samples" / "requirements-acl.yaml"


@pytest.fixture(scope="module")
def req():
    return load_requirements(REQ)


def load_yaml(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    try:
        return load_requirements(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_parses_departments(req):
    assert set(req.departments) == {"finance", "server"}
    assert req.departments["finance"].subnet == "10.0.20.0/24"
    assert req.departments["finance"].name == "财务部"


def test_device_annotation(req):
    assert req.devices["LSW1"].department == "财务部"
    assert req.devices["LSW1"].layer == "access"
    assert req.devices["AR1"].layer == "core"


def test_acl_commands(topo, req):
    text = "\n".join(build_configs(topo, req)["AR1"])
    assert "acl number 3000" in text
    assert " rule 5 permit ip source 10.0.20.0 0.0.0.255 destination 10.0.30.0 0.0.0.255" in text
    assert " rule 10 deny ip destination 10.0.20.0 0.0.0.255" in text
    assert " rule 15 permit ip" in text
    assert " traffic-filter inbound acl 3000" in text


def test_acl_interface_not_duplicated(topo, req):
    lines = build_configs(topo, req)["AR1"]
    assert lines.count("interface GigabitEthernet0/0/0") == 1


def test_other_device_has_no_acl(topo, req):
    assert "acl number" not in "\n".join(build_configs(topo, req)["AR2"])


FINANCE_GUARD = """
departments:
  sales: {name: 销售部, subnet: 10.0.10.0/24}
  finance: {name: 财务部, subnet: 10.0.20.0/24}
devices:
  AR1:
    role: router
    interfaces:
      - {name: GigabitEthernet0/0/0, ip: 10.0.10.1/24}
      - {name: GigabitEthernet0/0/1, ip: 10.0.20.1/24}
      - {name: GigabitEthernet0/0/2, ip: 10.0.30.1/24}
  AR2:
    role: router
    interfaces:
      - {name: GigabitEthernet0/0/0, ip: 10.0.10.2/24}
protocols:
  acl:
    - name: finance-guard
      device: AR1
      acl_number: 3000
      apply:
        interfaces: [GigabitEthernet0/0/0, GigabitEthernet0/0/2]
        direction: inbound
      rules:
        - {action: deny, protocol: icmp, icmp_type: echo, destination: finance}
        - {action: deny, protocol: tcp, tcp_flag: syn, destination: finance}
        - {action: permit, source: any, destination: any}
"""


def test_single_acl_with_icmp_type_and_tcp_flag(topo):
    req = load_yaml(FINANCE_GUARD)
    lines = build_configs(topo, req)["AR1"]
    # icmp-type 名字各版本支持不一，统一输出数字类型/代码
    assert " rule 5 deny icmp destination 10.0.20.0 0.0.0.255 icmp-type 8 0" in lines
    assert " rule 10 deny tcp destination 10.0.20.0 0.0.0.255 tcp-flag syn" in lines
    assert " rule 15 permit ip" in lines
    assert lines.count("acl number 3000") == 1


def test_numeric_icmp_type_passthrough(topo):
    req = load_yaml(FINANCE_GUARD.replace("icmp_type: echo", 'icmp_type: "8 0"'))
    lines = build_configs(topo, req)["AR1"]
    assert " rule 5 deny icmp destination 10.0.20.0 0.0.0.255 icmp-type 8 0" in lines


def test_one_acl_applied_to_several_interfaces(topo):
    req = load_yaml(FINANCE_GUARD)
    lines = build_configs(topo, req)["AR1"]
    assert lines.count(" traffic-filter inbound acl 3000") == 2
    assert lines.count("interface GigabitEthernet0/0/0") == 1
    assert lines.count("interface GigabitEthernet0/0/2") == 1


def test_icmp_type_requires_icmp_protocol():
    with pytest.raises(RequirementError):
        load_yaml(FINANCE_GUARD.replace("protocol: icmp", "protocol: ip"))


def test_tcp_flag_requires_tcp_protocol():
    with pytest.raises(RequirementError):
        load_yaml(FINANCE_GUARD.replace("protocol: tcp", "protocol: udp"))


def test_unknown_tcp_flag_rejected():
    with pytest.raises(RequirementError):
        load_yaml(FINANCE_GUARD.replace("tcp_flag: syn", "tcp_flag: hello"))


def test_apply_interfaces_must_exist_in_topology(topo):
    req = load_yaml(FINANCE_GUARD.replace("GigabitEthernet0/0/2]", "GigabitEthernet0/0/9]"))
    with pytest.raises(RequirementError):
        build_configs(topo, req)


EXPANDED = FINANCE_GUARD.replace(
    "        interfaces: [GigabitEthernet0/0/0, GigabitEthernet0/0/2]\n        direction: inbound",
    "        interfaces: [GigabitEthernet0/0/0, GigabitEthernet0/0/2]\n"
    "        direction: inbound\n        expand: true",
)


def test_expand_clones_acl_per_interface(topo):
    """交换机同一个 ACL 不能挂多个 Vlanif，展开后每个接口一条独立 ACL。"""

    req = load_yaml(EXPANDED)
    numbers = [acl.acl_number for acl in req.acls]
    assert numbers == [3000, 3001]
    assert [acl.interface for acl in req.acls] == [
        "GigabitEthernet0/0/0",
        "GigabitEthernet0/0/2",
    ]

    lines = build_configs(topo, req)["AR1"]
    assert "acl number 3000" in lines
    assert "acl number 3001" in lines
    assert " traffic-filter inbound acl 3000" in lines
    assert " traffic-filter inbound acl 3001" in lines
    # 每个 ACL 只出现一次编号定义
    assert lines.count("acl number 3000") == 1


def test_expand_rejects_number_overflow():
    with pytest.raises(RequirementError):
        load_yaml(EXPANDED.replace("acl_number: 3000", "acl_number: 3999"))


def test_doc_marks_department_and_layer(topo, req):
    configs = build_configs(topo, req)
    texts = [p.text for p in build_document(topo, req, configs).paragraphs]
    assert "LSW1（财务部）　S5700" in texts
    assert "AR1　AR2220" in texts
    assert any("层级：接入层" in t for t in texts)


def test_doc_table_has_department_column(topo, req):
    configs = build_configs(topo, req)
    table = build_document(topo, req, configs).tables[0]
    headers = [c.text for c in table.rows[0].cells]
    assert headers == ["设备", "型号", "类型", "部门", "层级", "可连接口数"]
    rows = {r.cells[0].text: [c.text for c in r.cells] for r in table.rows[1:]}
    assert rows["LSW1"][3] == "财务部"
    assert rows["LSW1"][4] == "接入层"


def test_unknown_department_rejected():
    with pytest.raises(RequirementError) as excinfo:
        load_yaml(
            """
protocols:
  acl:
    - name: a
      device: AR1
      rules:
        - {action: deny, source: hr, destination: finance}
"""
        )
    assert "hr" in str(excinfo.value)


def test_department_without_subnet_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
departments:
  finance: {name: 财务部}
protocols:
  acl:
    - name: a
      device: AR1
      rules:
        - {action: deny, source: finance}
"""
        )


def test_bad_action_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  acl:
    - name: a
      device: AR1
      rules:
        - {action: drop, source: any, destination: any}
"""
        )


def test_port_on_ip_rule_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  acl:
    - name: a
      device: AR1
      rules:
        - {action: permit, protocol: ip, destination_port: 80}
"""
        )


def test_acl_number_range_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  acl:
    - name: a
      device: AR1
      acl_number: 2000
      rules:
        - {action: permit}
"""
        )


def test_duplicate_acl_name_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
protocols:
  acl:
    - {name: a, device: AR1, rules: [{action: permit}]}
    - {name: a, device: AR1, rules: [{action: permit}]}
"""
        )


def test_unknown_acl_device_rejected(topo):
    requirements = load_yaml(
        """
protocols:
  acl:
    - {name: a, device: R99, rules: [{action: permit}]}
"""
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, requirements)
    assert "R99" in str(excinfo.value)


def test_missing_acl_interface_rejected(topo):
    requirements = load_yaml(
        """
protocols:
  acl:
    - name: a
      device: AR1
      apply: {interface: GigabitEthernet0/0/9, direction: inbound}
      rules: [{action: permit}]
"""
    )
    with pytest.raises(RequirementError) as excinfo:
        build_configs(topo, requirements)
    assert "GigabitEthernet0/0/9" in str(excinfo.value)


def test_department_layer_enum_rejected():
    with pytest.raises(RequirementError):
        load_yaml(
            """
devices:
  AR1:
    layer: dmz
"""
        )
