import tempfile
from pathlib import Path

import pytest

from labgen.generators import build_configs
from labgen.requirements import RequirementError, load_requirements

ROOT = Path(__file__).resolve().parents[1]

ROUTING = """
experiment:
  name: 路由与出口实验

departments:
  lan: {name: 内网, subnet: 192.168.1.0/24}

devices:
  AR1:
    role: router
    interfaces:
      - {name: GigabitEthernet0/0/0, ip: 10.0.1.1/24, description: to-AR2}
      - {name: GigabitEthernet0/0/1, ip: 192.168.1.1/24, description: to-LAN}
  AR2:
    role: router
    interfaces:
      - {name: GigabitEthernet0/0/0, ip: 10.0.1.2/24, description: to-AR1}

protocols:
  rip:
    process: 1
    version: 2
    devices: [AR2]
  bgp:
    as: 65001
    router_id: 1.1.1.1
    devices: [AR1]
    neighbors:
      - {ip: 10.0.1.2, remote_as: 65002, description: peer-ar2}
  prefix_list:
    - name: PL-24
      device: AR1
      rules:
        - {seq: 10, action: permit, prefix: 192.168.0.0/16, greater_equal: 24, less_equal: 24}
        - {seq: 20, action: deny, prefix: 0.0.0.0/0, less_equal: 32}
  route_policy:
    - name: RP-IN
      device: AR1
      apply_peer: 10.0.1.2
      apply_direction: import
      nodes:
        - {seq: 10, action: permit, match_prefix_list: PL-24, apply_local_preference: 200}
        - {seq: 20, action: deny}
  nat:
    - name: egress
      device: AR1
      acl_number: 2000
      interface: GigabitEthernet0/0/1
      source: lan
"""


def load_yaml(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    try:
        return load_requirements(path)
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.fixture(scope="module")
def req():
    return load_yaml(ROUTING)


def test_rip_uses_classful_network(topo, req):
    lines = build_configs(topo, req)["AR2"]
    assert "rip 1" in lines
    assert " version 2" in lines
    assert " undo summary" in lines
    assert " network 10.0.0.0" in lines


def test_rip_only_on_declared_devices(topo, req):
    assert "rip 1" not in build_configs(topo, req)["AR1"]


def test_bgp_neighbors_and_networks(topo, req):
    lines = build_configs(topo, req)["AR1"]
    assert "bgp 65001" in lines
    assert " router-id 1.1.1.1" in lines
    assert " peer 10.0.1.2 as-number 65002" in lines
    assert " peer 10.0.1.2 description peer-ar2" in lines
    assert " network 10.0.1.0 255.255.255.0" in lines
    assert " network 192.168.1.0 255.255.255.0" in lines
    assert " peer 10.0.1.2 route-policy RP-IN import" in lines


def test_bgp_not_on_other_devices(topo, req):
    lines = build_configs(topo, req)["AR2"]
    assert not any(line.startswith("bgp ") for line in lines)


def test_prefix_list_commands(topo, req):
    lines = build_configs(topo, req)["AR1"]
    assert "ip ip-prefix PL-24 index 10 permit 192.168.0.0 16 greater-equal 24 less-equal 24" in lines
    assert "ip ip-prefix PL-24 index 20 deny 0.0.0.0 0 less-equal 32" in lines


def test_route_policy_nodes(topo, req):
    lines = build_configs(topo, req)["AR1"]
    assert "route-policy RP-IN permit node 10" in lines
    assert " if-match ip-prefix PL-24" in lines
    assert " apply local-preference 200" in lines
    assert "route-policy RP-IN deny node 20" in lines


def test_nat_acl_and_interface(topo, req):
    lines = build_configs(topo, req)["AR1"]
    assert "acl number 2000" in lines
    assert " rule 5 permit source 192.168.1.0 0.0.0.255" in lines
    assert "interface GigabitEthernet0/0/1" in lines
    assert " nat outbound 2000" in lines
    # nat 行必须落在接口视图里
    index = lines.index("interface GigabitEthernet0/0/1")
    nat_index = lines.index(" nat outbound 2000")
    assert nat_index > index
    assert lines[lines.index(" ip address 192.168.1.1 255.255.255.0")] == " ip address 192.168.1.1 255.255.255.0"


def test_route_policy_rejects_unknown_prefix_list():
    broken = ROUTING.replace("match_prefix_list: PL-24", "match_prefix_list: PL-不存在")
    with pytest.raises(RequirementError):
        load_yaml(broken)


def test_route_policy_rejects_unknown_acl():
    broken = ROUTING.replace("match_prefix_list: PL-24", "match_acl: 3999")
    with pytest.raises(RequirementError):
        load_yaml(broken)


def test_nat_rejects_unsupported_type():
    broken = ROUTING.replace("source: lan", "source: lan\n      type: static")
    with pytest.raises(RequirementError):
        load_yaml(broken)


def test_prefix_list_rejects_bad_range():
    broken = ROUTING.replace("greater_equal: 24", "greater_equal: 8")
    with pytest.raises(RequirementError):
        load_yaml(broken)


def test_unknown_device_in_bgp_rejected_by_topo(topo):
    req = load_yaml(ROUTING.replace("devices: [AR1]", "devices: [AR9]"))
    with pytest.raises(RequirementError):
        build_configs(topo, req)