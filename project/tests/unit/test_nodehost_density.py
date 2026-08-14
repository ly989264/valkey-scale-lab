from __future__ import annotations

from pathlib import Path

import pytest

from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import load_effective_config, normalize_config
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan
from valkey_scale_lab.planner.plan import build_cluster_plan, create_plan_file
from valkey_scale_lab import resource


def test_global_config_supplies_density_defaults() -> None:
    config = load_effective_config("templates/configs/scale_100.yaml")
    runtime = config["runtime"]

    assert runtime["nodehost_strategy"] == "density_limited"
    assert runtime["max_nodehosts"] == 64
    assert runtime["nodehosts_per_az"] == 2
    assert runtime["max_logical_nodes_per_nodehost"] == 25
    assert runtime["nodehost_distribution"] == "round_robin_by_az"
    assert config["_config_sources"]["merge_order"] == ["built-in defaults", "global config", "scenario config", "CLI override"]


def test_scenario_and_cli_override_global_density(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    text = Path("templates/configs/scale_30.yaml").read_text(encoding="utf-8")
    scenario.write_text(
        text.replace(
            "  sandbox_mode: container_namespace",
            "  sandbox_mode: container_namespace\n  max_logical_nodes_per_nodehost: 10",
        ),
        encoding="utf-8",
    )

    config = load_effective_config(
        scenario,
        cli_overrides={"runtime": {"max_logical_nodes_per_nodehost": 5}},
    )

    assert config["runtime"]["max_logical_nodes_per_nodehost"] == 5
    assert config["_config_sources"]["cli_override_applied"] is True


def test_density_planner_splits_100_and_200_nodes(tmp_path: Path) -> None:
    plan100 = create_plan_file("templates/configs/scale_100.yaml", tmp_path / "scale_100.json")
    assert plan100["nodehost_density"]["actual_nodehost_count"] == 4
    assert max(plan100["nodehost_density"]["logical_nodes_per_nodehost"].values()) == 25

    config200 = load_effective_config("templates/configs/scale_200.yaml")
    plan200 = build_cluster_plan(
        config200,
        config_path=Path("templates/configs/scale_200.yaml"),
        capability_id="management_matrix",
        scenario="management_matrix",
    )
    assert plan200["nodehost_density"]["actual_nodehost_count"] == 8
    assert max(plan200["nodehost_density"]["logical_nodes_per_nodehost"].values()) == 25


def test_density_planner_fails_closed_when_max_nodehosts_too_low() -> None:
    config = load_effective_config("templates/configs/scale_200.yaml")
    config["runtime"]["max_nodehosts"] = 2

    with pytest.raises(NodehostDensityError, match="exceeds max_nodehosts"):
        build_nodehost_density_plan(
            config=config,
            nodes=_nodes_from_config(config),
            run_id="test-low-nodehost-cap",
            assign=True,
        )


def test_resource_preflight_records_density_checks(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_details", lambda: {"available": True, "server_version": "test"})
    monkeypatch.setattr(resource, "_cleanup_state_check", lambda capability_id, scenario, node_count: resource._check("previous_cleanup_state", True, {"node_count": node_count}))
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))

    report = resource.run_resource_preflight("templates/configs/scale_100.yaml", tmp_path / "preflight.json")

    assert report["status"] == "PASS"
    assert report["nodehost_density"]["actual_nodehost_count"] == 4
    names = {check["name"]: check["status"] for check in report["checks"]}
    assert names["nodehost_density_plan"] == "PASS"
    assert names["nodehost_count_limit"] == "PASS"
    assert names["nodehost_process_density"] == "PASS"
    assert names["total_port_count"] == "PASS"


def test_resource_preflight_fails_when_density_over_max(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_details", lambda: {"available": True, "server_version": "test"})
    monkeypatch.setattr(resource, "_cleanup_state_check", lambda capability_id, scenario, node_count: resource._check("previous_cleanup_state", True, {"node_count": node_count}))
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))

    report = resource.run_resource_preflight(
        "templates/configs/scale_100.yaml",
        tmp_path / "preflight.json",
        cli_overrides={"runtime": {"max_nodehosts": 2}},
    )

    assert report["status"] == "FAIL"
    assert any(check["name"] == "nodehost_density_plan" and check["status"] == "FAIL" for check in report["checks"])


def _nodes_from_config(config: dict) -> list[dict]:
    cluster = config["cluster"]
    azs = list(config["network"]["azs"])
    nodes = []
    ordinal = 0
    for shard in range(int(cluster["shards"])):
        shard_id = f"shard-{shard:04d}"
        nodes.append(_node(cluster, shard_id, "primary", azs[shard % len(azs)], ordinal))
        ordinal += 1
    for shard in range(int(cluster["shards"])):
        shard_id = f"shard-{shard:04d}"
        nodes.append(_node(cluster, shard_id, "replica", azs[(shard + 1) % len(azs)], ordinal))
        ordinal += 1
    return nodes


def _node(cluster: dict, shard_id: str, role: str, az_id: str, ordinal: int) -> dict:
    return {
        "logical_id": f"{shard_id}-{role}",
        "shard_id": shard_id,
        "role": role,
        "az_id": az_id,
        "host_id": "local",
        "ordinal": ordinal,
        "client_port": int(cluster["port_base"]) + ordinal,
        "cluster_bus_port": int(cluster["cluster_bus_port_base"]) + ordinal,
    }


def _shape_nodes(
    shards: int, replicas_per_shard: int, azs: list[str], *, primaries_first: bool = True
) -> list[dict[str, object]]:
    """A run's logical nodes at an arbitrary shard shape, in the runtime's order.

    `primaries_first` is the ordering `_node_specs`, the semantic validator and
    the resource preflight all use - every primary, then every replica. The
    planner interleaves instead, which is why both orders are exercised here.
    """

    from valkey_scale_lab import placement

    primaries: list[dict[str, object]] = []
    replicas: list[dict[str, object]] = []
    for shard in range(shards):
        shard_id = f"shard-{shard:04d}"
        primaries.append(
            {
                "logical_id": f"{shard_id}-primary",
                "shard_id": shard_id,
                "role": "primary",
                "az_id": placement.primary_az(azs, shard),
            }
        )
        for replica in range(replicas_per_shard):
            replicas.append(
                {
                    "logical_id": f"{shard_id}-replica-{replica:02d}",
                    "shard_id": shard_id,
                    "role": "replica",
                    "az_id": placement.replica_az(azs, shard, replica),
                }
            )
    if primaries_first:
        ordered = primaries + replicas
    else:
        by_shard: list[dict[str, object]] = []
        for shard in range(shards):
            shard_id = f"shard-{shard:04d}"
            by_shard.extend(
                node for node in primaries + replicas if node["shard_id"] == shard_id
            )
        ordered = by_shard
    for ordinal, node in enumerate(ordered):
        node["ordinal"] = ordinal
        node["client_port"] = 7000 + ordinal
        node["cluster_bus_port"] = 17000 + ordinal
    return ordered


def _density_config(replicas_per_shard: int, nodehosts_per_az: int, azs: list[str]) -> dict:
    return {
        "runtime": {"nodehosts_per_az": nodehosts_per_az},
        "cluster": {"replicas_per_shard": replicas_per_shard},
        "network": {"azs": azs},
    }


def _nodehost_of(nodes: list[dict[str, object]]) -> dict[str, str]:
    return {str(node["logical_id"]): str(node["nodehost_id"]) for node in nodes}


def test_one_replica_placement_is_unchanged_by_the_shard_aware_assignment() -> None:
    """The property the whole multi-replica program is measured against.

    Round-robin by position and the shard-a-time walk agree exactly whenever no
    shard has two members in one AZ, which is every one-replica multi-AZ shape.
    Asserted here against the two shapes the frozen baselines were taken at, by
    reproducing the positional assignment directly rather than trusting it.
    """

    azs = ["az-a", "az-b"]
    for shards, nodehosts_per_az in [(25, 2), (100, 2), (3, 2), (15, 2)]:
        nodes = _shape_nodes(shards, 1, azs)
        build_nodehost_density_plan(
            config=_density_config(1, nodehosts_per_az, azs),
            nodes=nodes,
            run_id="density-r1",
            assign=True,
        )
        by_az: dict[str, list[dict[str, object]]] = {}
        for node in sorted(nodes, key=lambda item: int(item["ordinal"])):
            by_az.setdefault(str(node["az_id"]), []).append(node)
        expected: dict[str, str] = {}
        for az, hosted in by_az.items():
            count = max(nodehosts_per_az, -(-len(hosted) // 25))
            for offset, node in enumerate(hosted):
                expected[str(node["logical_id"])] = f"nodehost-{az}-{offset % count:02d}"
        assert _nodehost_of(nodes) == expected

    # A single-AZ non-HA plan puts both members of a shard in the one AZ, so it
    # is a shape where the two assignments genuinely differ - the shard-a-time
    # walk would gather all three primaries onto one nodehost. The positional
    # assignment already separates every shard here, so it is the one kept, and
    # this is what the "only where the positional one fails" rule is protecting.
    single = ["az-local"]
    nodes = _shape_nodes(3, 1, single)
    build_nodehost_density_plan(
        config=_density_config(1, 2, single), nodes=nodes, run_id="density-single", assign=True
    )
    assert _nodehost_of(nodes) == {
        "shard-0000-primary": "nodehost-az-local-00",
        "shard-0001-primary": "nodehost-az-local-01",
        "shard-0002-primary": "nodehost-az-local-00",
        "shard-0000-replica-00": "nodehost-az-local-01",
        "shard-0001-replica-00": "nodehost-az-local-00",
        "shard-0002-replica-00": "nodehost-az-local-01",
    }


def test_multi_replica_shards_never_share_a_nodehost() -> None:
    """Measured, not predicted: the positional assignment could not do this.

    At ten shards of four replicas the primary and one of its replicas landed on
    one nodehost at every `nodehosts_per_az` from 1 to 16, because the runtime
    orders every primary before every replica, so where the stride lands - not
    the number of fault domains - decides whether the two blocks collide.
    """

    azs = ["az-a", "az-b"]
    for shards, replicas, nodehosts_per_az in [(10, 4, 3), (10, 4, 4), (40, 4, 2), (3, 2, 2), (6, 4, 3)]:
        for primaries_first in (True, False):
            nodes = _shape_nodes(shards, replicas, azs, primaries_first=primaries_first)
            build_nodehost_density_plan(
                config=_density_config(replicas, nodehosts_per_az, azs),
                nodes=nodes,
                run_id="density-mr",
                assign=True,
            )
            per_shard: dict[str, list[str]] = {}
            for node in nodes:
                per_shard.setdefault(str(node["shard_id"]), []).append(str(node["nodehost_id"]))
            for shard_id, hosts in per_shard.items():
                assert len(set(hosts)) == len(hosts), (
                    f"{shards}x{replicas} per_az={nodehosts_per_az} "
                    f"primaries_first={primaries_first} {shard_id} -> {hosts}"
                )
            # The walk never rewinds, so the load stays as even as before.
            counts: dict[str, int] = {}
            for node in nodes:
                counts[str(node["nodehost_id"])] = counts.get(str(node["nodehost_id"]), 0) + 1
            assert max(counts.values()) - min(counts.values()) <= 1


def test_the_per_az_fault_domain_minimum_covers_every_shard_shape() -> None:
    """One expression where there used to be a single-AZ special case.

    `ceil((replicas + 1) / AZs)` is `replicas + 1` at one AZ, which is exactly
    what the single-AZ branch computed, and 1 at one replica over two AZs, which
    is what multi-AZ was hardcoded to. It is 3 at four replicas over two AZs, and
    that is the value nothing stated before.
    """

    from valkey_scale_lab.nodehost_density import _min_fault_domains_per_az

    assert _min_fault_domains_per_az(0, 1) == 1
    assert _min_fault_domains_per_az(0, 2) == 1
    for replicas in (1, 2, 3, 4):
        assert _min_fault_domains_per_az(replicas, 1) == replicas + 1
    assert _min_fault_domains_per_az(1, 2) == 1
    assert _min_fault_domains_per_az(2, 2) == 2
    assert _min_fault_domains_per_az(3, 2) == 2
    assert _min_fault_domains_per_az(4, 2) == 3
    assert _min_fault_domains_per_az(4, 3) == 2

    # And it reaches the plan: ten shards of four replicas over two AZs get
    # three nodehosts per AZ at the shipped `nodehosts_per_az: 2`, because two
    # cannot hold a shard's three same-AZ members. At one replica the same knob
    # is untouched, which is what keeps every existing plan where it was.
    azs = ["az-a", "az-b"]
    nodes = _shape_nodes(10, 4, azs)
    plan = build_nodehost_density_plan(
        config=_density_config(4, 2, azs), nodes=nodes, run_id="density-min", assign=True
    )
    assert plan["actual_nodehost_count"] == 6
    assert plan["nodehost_count_by_az"] == {"az-a": 3, "az-b": 3}

    nodes = _shape_nodes(25, 1, azs)
    plan = build_nodehost_density_plan(
        config=_density_config(1, 2, azs), nodes=nodes, run_id="density-min-r1", assign=True
    )
    assert plan["actual_nodehost_count"] == 4


def test_a_shard_shape_that_cannot_be_separated_is_refused_by_name() -> None:
    """The refusal names the shard, the nodehost, the shape and the knob.

    It used to say only "primary and replica for at least one shard share a
    nodehost fault domain", which names none of them - and at more than one
    replica per shard the knob is the whole content of the answer.

    Reached with an AZ layout the placement policy would not produce, all five
    members of one shard in one AZ, because with the minimum above hoisted into
    the per-AZ nodehost count the policy's own layouts are always separable.
    That makes this a fail-closed backstop rather than a step a supported shape
    walks through, and it is asserted as one.
    """

    azs = ["az-a", "az-b"]
    nodes = _shape_nodes(4, 4, azs)
    for node in nodes:
        if node["shard_id"] == "shard-0000":
            node["az_id"] = "az-a"

    with pytest.raises(NodehostDensityError) as excinfo:
        build_nodehost_density_plan(
            config=_density_config(4, 2, azs), nodes=nodes, run_id="density-refusal", assign=True
        )

    message = str(excinfo.value)
    assert "shard-0000" in message
    assert "runtime.nodehosts_per_az is 2" in message
    assert "needs at least 3 nodehost(s) in each AZ" in message
    assert "a shard of 5 members over 2 AZ(s)" in message
