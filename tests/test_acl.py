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
