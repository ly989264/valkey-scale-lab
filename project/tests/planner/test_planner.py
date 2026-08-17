from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pytest

from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import normalize_config
from valkey_scale_lab.planner.plan import PlannerError, build_cluster_plan, create_plan_file


def test_multi_az_plan_places_replicas_apart(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan.json")
    assert plan["node_count"] == 6
    assert plan["azs"] == ["az-a", "az-b"]
    assert plan["constraints"]["shard_az_balanced"] is True
    assert plan["constraints"]["two_virtual_azs"] is True
    assert plan["constraints"]["primary_replica_opposite_az_pair"] is True
    by_shard: dict[str, list[dict]] = defaultdict(list)
    for node in plan["nodes"]:
        by_shard[node["shard_id"]].append(node)
    for nodes in by_shard.values():
        primary = [node for node in nodes if node["role"] == "primary"][0]
        replica = [node for node in nodes if node["role"] == "replica"][0]
        assert primary["az_id"] != replica["az_id"]


def test_plan_has_unique_names_dirs_and_ports(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan.json")
    for key in ["logical_id", "container_name", "data_dir", "log_dir"]:
        values = [node[key] for node in plan["nodes"]]
        assert len(values) == len(set(values))
    assert [nodehost["az_id"] for nodehost in plan["nodehosts"]] == ["az-a", "az-a", "az-b", "az-b"]
    assert {node["nodehost_id"] for node in plan["nodes"]} == {
        "nodehost-az-a-00",
        "nodehost-az-a-01",
        "nodehost-az-b-00",
        "nodehost-az-b-01",
    }
    assert all(node["nodehost_container_name"] for node in plan["nodes"])
    ports_by_host: dict[str, list[int]] = defaultdict(list)
    for node in plan["nodes"]:
        ports_by_host[node["host_id"]].extend([node["client_port"], node["cluster_bus_port"]])
    for ports in ports_by_host.values():
        assert len(ports) == len(set(ports))


def test_az_balancing_is_deterministic(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan.json")
    counts = Counter(node["az_id"] for node in plan["nodes"])
    assert max(counts.values()) - min(counts.values()) <= 1
    plan2 = create_plan_file("templates/configs/local_az_3x2.yaml", tmp_path / "cluster_plan2.json")
    assert plan["nodes"] == plan2["nodes"]


def test_multi_replica_plan_balances_each_shard_across_the_azs(tmp_path: Path) -> None:
    """P1 and P2 at three members per shard.

    This test used to assert that every replica sits outside its primary's AZ,
    which is the placement the planner alone produced and the runtime never did.
    Under the unified policy a three-member shard over two AZs is 2/1, so the
    old assertion describes a topology no run would start. What survives, and is
    the property the operator asked for, is that the split is even within the
    shard and that at least one replica is still in the other AZ.
    """

    config = tmp_path / "multi_replica.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("replicas_per_shard: 1", "replicas_per_shard: 2"), encoding="utf-8")
    plan = create_plan_file(config, tmp_path / "cluster_plan.json")
    assert plan["node_count"] == 9
    assert plan["constraints"]["shard_az_balanced"] is True
    by_shard: dict[str, list[dict]] = defaultdict(list)
    for node in plan["nodes"]:
        by_shard[node["shard_id"]].append(node)
    for nodes in by_shard.values():
        primary = [node for node in nodes if node["role"] == "primary"][0]
        replicas = [node for node in nodes if node["role"] == "replica"]
        assert len(replicas) == 2
        counts = Counter(node["az_id"] for node in nodes)
        assert sorted(counts.values()) == [1, 2]
        assert any(replica["az_id"] != primary["az_id"] for replica in replicas)
    # P2: the fleet's own per-AZ totals stay even at an odd shard count.
    totals = Counter(node["az_id"] for node in plan["nodes"])
    assert max(totals.values()) - min(totals.values()) <= 1


def test_1000_node_plan_is_opt_in_dry_run(tmp_path: Path) -> None:
    plan = create_plan_file("templates/configs/scale_1000_dryrun_optin.yaml", tmp_path / "scale_1000.json", dry_run=True)
    assert plan["node_count"] == 1000
    assert plan["azs"] == ["az-a", "az-b"]
    assert len(plan["nodehosts"]) == 40
    assert plan["constraints"]["opt_in_1000"] is True
    assert plan["constraints"]["dry_run"] is True
    assert plan["constraints"]["two_virtual_azs"] is True
    assert all(node["dry_run"] is True for node in plan["nodes"])


def test_scale_projection_250_node_plan_is_dry_run_only(tmp_path: Path) -> None:
    config = tmp_path / "scale_250_scale_projection.yaml"
    config.write_text(scale_projection_config_text(250, dry_run=True), encoding="utf-8")

    plan = create_plan_file(config, tmp_path / "scale_250.json", dry_run=True)

    assert plan["node_count"] == 250
    assert plan["runtime"]["dry_run"] is True
    assert plan["constraints"]["scale_projection_200_plus"] is True
    assert plan["constraints"]["above_200_dry_run_only"] is True
    assert plan["constraints"]["no_execution"] is True
    assert all(node["dry_run"] is True for node in plan["nodes"])


def test_scale_projection_planner_rejects_real_above_200(tmp_path: Path) -> None:
    config = tmp_path / "scale_250_real.yaml"
    config.write_text(scale_projection_config_text(250, dry_run=False), encoding="utf-8")

    with pytest.raises(PlannerError, match="REAL_EXECUTION_ABOVE_200_FORBIDDEN"):
        create_plan_file(config, tmp_path / "scale_250_real.json")


def test_management_matrix_200_exact_200_plan_uses_bounded_exception_without_raising_cap() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))

    plan = build_cluster_plan(
        config,
        config_path=Path("templates/configs/scale_200.yaml"),
        capability_id="management_matrix",
        scenario="management_matrix",
    )

    assert plan["node_count"] == 200
    assert plan["constraints"]["default_node_cap"] == 100
    assert plan["constraints"]["opt_in_1000"] is False
    assert plan["constraints"]["exact_200_bounded_exception"] is True
    assert plan["constraints"]["selected_capability_id"] == "management_matrix"
    assert plan["constraints"]["selected_scenario_id"] == "management_matrix"
    assert plan["runtime"]["dry_run"] is False
    assert plan["nodehost_density"]["actual_nodehost_count"] == 8


def test_local_full_flow_exact_200_plan_uses_bounded_exception_without_raising_cap() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))

    plan = build_cluster_plan(
        config,
        config_path=Path("templates/configs/scale_200.yaml"),
        capability_id="local_full_flow",
        scenario="local_full_flow",
    )

    assert plan["node_count"] == 200
    assert plan["constraints"]["default_node_cap"] == 100
    assert plan["constraints"]["opt_in_1000"] is False
    assert plan["constraints"]["exact_200_bounded_exception"] is True
    assert plan["constraints"]["selected_capability_id"] == "local_full_flow"
    assert plan["constraints"]["selected_scenario_id"] == "local_full_flow"
    assert plan["runtime"]["dry_run"] is False


def test_local_full_flow_exact_2000_plan_uses_controlled_opt_in_path() -> None:
    config = normalize_config(
        parse_config_file("templates/configs/scale_2000_local_full_flow_optin.yaml")
    )

    plan = build_cluster_plan(
        config,
        config_path=Path("templates/configs/scale_2000_local_full_flow_optin.yaml"),
        capability_id="local_full_flow",
        scenario="local_full_flow",
        operator_opt_in=True,
        cost_acknowledged=True,
    )

    assert plan["node_count"] == 2000
    assert plan["runtime"]["dry_run"] is False
    assert plan["constraints"]["exact_2000_local_full_flow_opt_in"] is True
    assert plan["constraints"]["selected_capability_id"] == "local_full_flow"
    assert plan["constraints"]["selected_scenario_id"] == "local_full_flow"
    assert plan["constraints"]["operator_opt_in"] is True
    assert plan["constraints"]["cost_acknowledged"] is True
    assert plan["scalable_observability"]["cluster_nodes_command_count"] == 0
    assert plan["scalable_observability"]["light_command_count"] == 2000 * 6
    assert plan["nodehost_density"]["actual_nodehost_count"] == 80


def test_local_full_flow_exact_2000_plan_requires_explicit_opt_in() -> None:
    config = normalize_config(
        parse_config_file("templates/configs/scale_2000_local_full_flow_optin.yaml")
    )

    with pytest.raises(PlannerError, match="plans above 200 nodes"):
        build_cluster_plan(
            config,
            config_path=Path("templates/configs/scale_2000_local_full_flow_optin.yaml"),
            capability_id="local_full_flow",
            scenario="local_full_flow",
        )


def test_exact_2000_plan_rejects_non_local_full_flow_scenario() -> None:
    config = normalize_config(
        parse_config_file("templates/configs/scale_2000_local_full_flow_optin.yaml")
    )

    with pytest.raises(PlannerError, match="plans above 200 nodes"):
        build_cluster_plan(
            config,
            config_path=Path("templates/configs/scale_2000_local_full_flow_optin.yaml"),
            capability_id="management_matrix",
            scenario="management_matrix",
            operator_opt_in=True,
            cost_acknowledged=True,
        )


def test_management_matrix_200_exact_200_plan_rejects_wrong_scenario() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))

    with pytest.raises(PlannerError, match="node count exceeds default cap"):
        build_cluster_plan(
            config,
            config_path=Path("templates/configs/scale_200.yaml"),
            capability_id="management_matrix",
            scenario="management_matrix_typo",
        )


def test_management_matrix_200_bounded_exception_rejects_non_200_node_count() -> None:
    config = normalize_config(parse_config_file("templates/configs/scale_200.yaml"))
    config["cluster"]["shards"] = 99

    with pytest.raises(PlannerError, match="node count exceeds default cap"):
        build_cluster_plan(
            config,
            config_path=Path("templates/configs/scale_200.yaml"),
            capability_id="management_matrix",
            scenario="management_matrix",
        )


def test_plain_scale_200_plan_still_requires_existing_opt_in(tmp_path: Path) -> None:
    with pytest.raises(PlannerError, match="NODE_CAP_EXCEEDED"):
        create_plan_file("templates/configs/scale_200.yaml", tmp_path / "plain_scale_200_plan.json")


def test_single_az_replicas_rejected_without_non_ha_marker(tmp_path: Path) -> None:
    with pytest.raises(PlannerError, match="single-AZ replica"):
        create_plan_file("templates/configs/single_mac_6node.yaml", tmp_path / "single.json")


def test_single_az_replicas_allowed_with_non_ha_marker(tmp_path: Path) -> None:
    config = tmp_path / "single_non_ha.yaml"
    text = Path("templates/configs/single_mac_6node.yaml").read_text(encoding="utf-8")
    text = text.replace("  node_memory_limit_mb: 128", "  node_memory_limit_mb: 128\n  non_ha_allowed: true")
    config.write_text(text, encoding="utf-8")
    plan = create_plan_file(config, tmp_path / "single_non_ha.json")
    assert plan["node_count"] == 6
    assert plan["constraints"]["non_ha_single_az"] is True
    assert plan["constraints"]["shard_az_balanced"] is True


def test_numeric_host_capacity_is_enforced(tmp_path: Path) -> None:
    config = tmp_path / "zero_memory.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("memory_gb: auto", "memory_gb: 0"), encoding="utf-8")
    with pytest.raises(PlannerError, match="planner constraints failed"):
        create_plan_file(config, tmp_path / "zero_memory.json")


def test_numeric_host_capacity_can_pass(tmp_path: Path) -> None:
    config = tmp_path / "numeric_memory.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("memory_gb: auto", "memory_gb: 2"), encoding="utf-8")
    plan = create_plan_file(config, tmp_path / "numeric_memory.json")
    assert plan["constraints"]["host_capacity_checked"] is True
    assert plan["constraints"]["host_capacity"][0]["status"] == "PASS"


def scale_projection_config_text(target: int, *, dry_run: bool) -> str:
    return f"""
schema_version: v1
profile_name: scale_{target}_scale_projection
safety:
  default_max_nodes: 100
  allow_1000_nodes: false
  require_sandbox_network: true
  forbid_host_network_mutation: true
  cleanup_on_error: true
runtime:
  provider: docker
  valkey_image: valkey/valkey:9.1.0
  sandbox_mode: container_namespace
  dry_run: {str(dry_run).lower()}
hosts:
  - host_id: local
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [controller]
network:
  virtual_az_mode: multi
  azs: [az-a, az-b]
cluster:
  shards: {target}
  replicas_per_shard: 0
  port_base: 12000
  cluster_bus_port_base: 22000
  node_memory_limit_mb: 32
scale_profile:
  dry_run_only: true
  scale_projection_target: true
  target_nodes: {target}
  execution_mode: dry_run
workload:
  enabled: false
faults: []
""".strip() + "\n"


def _shard_shape_config(shards: int, replicas_per_shard: int, azs: list[str]) -> dict:
    from copy import deepcopy

    from valkey_scale_lab.config.validation import load_effective_config

    config = deepcopy(load_effective_config("templates/configs/scale_50.yaml"))
    config["cluster"]["shards"] = shards
    config["cluster"]["replicas_per_shard"] = replicas_per_shard
    config["network"]["azs"] = list(azs)
    config["network"]["virtual_az_mode"] = "single" if len(azs) == 1 else "multi"
    return config


def _az_by_logical_id(nodes: list[dict]) -> dict[str, str]:
    return {str(node["logical_id"]): str(node["az_id"]) for node in nodes}


def test_every_module_places_a_shard_in_the_same_azs() -> None:
    """The four node models this repository builds must agree about placement.

    They did not. The planner, the semantic validator and the resource preflight
    put every replica in an AZ other than its primary's; the runtime - which is
    what actually starts the fleet - walked the AZ list from the shard's own
    index and did not exclude the primary's AZ. All four agree at one replica per
    shard, which is every run ever taken, so nothing disagreed out loud; at two
    or more the started topology contradicted the plan the constraints were
    asserted against.
    """

    from valkey_scale_lab.config.validation import _semantic_density_nodes
    from valkey_scale_lab.resource import _preflight_density_nodes
    from valkey_scale_lab.runtime.docker_runtime import _node_specs

    for azs in (["az-a"], ["az-a", "az-b"], ["az-a", "az-b", "az-c"]):
        for shards in (3, 4, 5, 6, 7):
            for replicas in (0, 1, 2, 3, 4):
                config = _shard_shape_config(shards, replicas, azs)
                models = {
                    "semantic": _az_by_logical_id(_semantic_density_nodes(config)),
                    "preflight": _az_by_logical_id(_preflight_density_nodes(config)),
                    "runtime": _az_by_logical_id(
                        _node_specs(config, "local_full_flow", "local_full_flow", "agreement")
                    ),
                    "planner": _az_by_logical_id(
                        _planner_placement(shards, replicas, azs)
                    ),
                }
                reference = models["semantic"]
                for name, model in models.items():
                    assert model == reference, (
                        f"{name} disagrees at {shards}x{replicas} over {len(azs)} AZs"
                    )


def _planner_placement(shards: int, replicas: int, azs: list[str]) -> list[dict]:
    """The AZ the planner's own loop assigns, without its refusals."""

    from valkey_scale_lab import placement

    nodes = []
    for shard in range(shards):
        shard_id = f"shard-{shard:04d}"
        nodes.append({"logical_id": f"{shard_id}-primary", "az_id": placement.primary_az(azs, shard)})
        for replica in range(replicas):
            nodes.append(
                {
                    "logical_id": f"{shard_id}-replica-{replica:02d}",
                    "az_id": placement.replica_az(azs, shard, replica),
                }
            )
    return nodes


def test_the_unified_policy_keeps_both_balance_properties() -> None:
    """P1 per-shard and P2 global, over the shapes the ladder and M4 will use.

    The all-opposite policy this replaced satisfies P1 only at one replica: five
    members over two AZs land 1/4, not 3/2. It also skews the fleet's own totals
    by `replicas - 1` at an odd shard count, which is why odd shard counts at
    three or more replicas used to be refused outright with a message naming
    neither balance nor replicas.
    """

    from collections import Counter

    from valkey_scale_lab import placement

    for azs in (["az-a", "az-b"], ["az-a", "az-b", "az-c"]):
        for shards in (3, 5, 6, 7, 10, 40, 256):
            for replicas in (1, 2, 3, 4):
                nodes = _planner_placement(shards, replicas, azs)
                for shard in range(shards):
                    shard_id = f"shard-{shard:04d}"
                    members = [placement.primary_az(azs, shard)] + [
                        placement.replica_az(azs, shard, replica) for replica in range(replicas)
                    ]
                    counts = [members.count(az) for az in azs]
                    # P1: the shard's members are spread evenly over the AZs.
                    assert max(counts) - min(counts) <= 1, (shard_id, shards, replicas, len(azs), counts)
                    # At more than one AZ, at least one replica is outside the
                    # primary's AZ - the property the old constraint name meant.
                    if len(azs) > 1 and replicas:
                        assert any(az != members[0] for az in members[1:])
                # P2: the fleet's own per-AZ totals stay within one of each other.
                totals = Counter(node["az_id"] for node in nodes)
                for az in azs:
                    totals.setdefault(az, 0)
                assert max(totals.values()) - min(totals.values()) <= 1, (shards, replicas, dict(totals))
                # Exact at an even split, which is the operator's 6x5 example.
                if shards % len(azs) == 0:
                    assert len(set(totals.values())) == 1


def _old_replica_az(azs: list[str], primary_az: str, shard: int, replica: int) -> str:
    """The planner's `_replica_az` as it stood before the unification."""

    if len(azs) == 1:
        return azs[0]
    candidates = [az for az in azs if az != primary_az]
    return candidates[(shard + replica) % len(candidates)]


def test_one_replica_placement_is_byte_identical_to_the_old_formula() -> None:
    """The regression the whole program is judged on, at every reachable AZ count.

    `_validate_network` admits exactly one AZ in single mode and exactly two in
    multi, so one and two are the AZ counts a configuration can have. At both,
    the unified function returns the same string as the old one for every shard
    of every one-replica shape, which is what keeps the existing runs' placement
    unmoved.
    """

    from valkey_scale_lab import placement

    for azs in (["az-a"], ["az-a", "az-b"]):
        for shard in range(500):
            primary = placement.primary_az(azs, shard)
            assert primary == azs[shard % len(azs)]
            assert placement.replica_az(azs, shard, 0) == _old_replica_az(azs, primary, shard, 0)


def test_three_azs_are_the_one_place_the_two_formulas_differ_at_one_replica() -> None:
    """Reported rather than reconciled, because it is measured and unreachable.

    multi_replica_support_map.md §7.1 says the unified formula was "spot-checked
    to agree with the planner's formula at r=1 for both 2 and 3 AZs". At three
    AZs that is false: from shard 3 onward the two pick different AZs, because
    the old formula indexes the two *candidates* left after excluding the
    primary's while this one indexes all three. Both satisfy P1 there - a
    two-member shard occupies two of three AZs either way - so nothing is wrong
    with the placement, only with the claim.

    It moves nothing, because no configuration can declare three AZs:
    `virtual_az_mode: multi` requires exactly two and `single` exactly one.
    Pinned here so that a later session which widens the AZ count meets the
    divergence as a decision rather than as a surprise.
    """

    from valkey_scale_lab import placement

    azs = ["az-a", "az-b", "az-c"]
    differing = [
        shard
        for shard in range(12)
        if placement.replica_az(azs, shard, 0)
        != _old_replica_az(azs, placement.primary_az(azs, shard), shard, 0)
    ]
    assert differing == [3, 4, 5, 9, 10, 11]
    for shard in range(12):
        members = [placement.primary_az(azs, shard), placement.replica_az(azs, shard, 0)]
        assert len(set(members)) == 2


def test_exact_1280_needs_the_operator_not_only_the_file() -> None:
    """What makes a named exception an operator act rather than a configuration.

    `operator_opt_in` and `cost_acknowledged` are arguments threaded from
    `runtime/lifecycle.py`; no file can assert them about itself. The same is
    true of the capability/scenario pair, so a configuration that is admissible
    still cannot be planned from a scenario the exception does not name.
    """

    from valkey_scale_lab.config.validation import load_effective_config
    from valkey_scale_lab.planner.plan import PlannerError, build_cluster_plan

    config = load_effective_config("templates/configs/scale_1280_native_ecs_optin.yaml")

    plan = build_cluster_plan(
        config,
        capability_id="local_full_flow",
        scenario="local_full_flow",
        operator_opt_in=True,
        cost_acknowledged=True,
    )
    assert len(plan["nodes"]) == 1280
    assert plan["constraints"]["exact_1280_native_ecs_opt_in"] is True
    assert plan["constraints"]["exact_2000_local_full_flow_opt_in"] is False
    assert plan["constraints"]["operator_opt_in"] is True
    assert plan["constraints"]["cost_acknowledged"] is True

    for missing in ("operator_opt_in", "cost_acknowledged"):
        kwargs = {"operator_opt_in": True, "cost_acknowledged": True, missing: False}
        with pytest.raises(PlannerError, match="dry-run only"):
            build_cluster_plan(
                config,
                capability_id="local_full_flow",
                scenario="local_full_flow",
                **kwargs,
            )

    # A scenario the exception does not name cannot reach it either.
    with pytest.raises(PlannerError, match="dry-run only"):
        build_cluster_plan(
            config,
            capability_id="fault_matrix",
            scenario="fault_matrix",
            operator_opt_in=True,
            cost_acknowledged=True,
        )


def test_exact_1280_plans_twelve_nodehosts_with_no_shard_colliding() -> None:
    """The shape the fleet was rebuilt for, now pinned.

    One nodehost per host is what a native run places and refuses otherwise, so
    twelve nodehosts is twelve hosts. The fleet was rebuilt from eight to twelve
    `c4a-standard-2` on 2026-08-17 to buy two things this shape then has: 107
    nodes per host is **53.5 valkey-servers per vCPU**, inside the 50 per vCPU
    `m4_density_calibration.md` §4 measured clean rather than the 80 that eight
    hosts forced; and 107 x 64 MiB fits in 7911, so `node_memory_limit_mb` stays
    at the 64 every prior measurement was taken under instead of dropping to 32.
    """

    import collections

    from valkey_scale_lab.config.validation import load_effective_config
    from valkey_scale_lab.planner.plan import build_cluster_plan

    config = load_effective_config("templates/configs/scale_1280_native_ecs_optin.yaml")
    nodes = build_cluster_plan(
        config,
        capability_id="local_full_flow",
        scenario="local_full_flow",
        operator_opt_in=True,
        cost_acknowledged=True,
    )["nodes"]

    per_nodehost = collections.Counter(node["nodehost_id"] for node in nodes)
    assert len(per_nodehost) == 12
    # 1280 does not divide by 12, so the tail is one node lighter rather than
    # the plan refusing or silently rounding the node count.
    assert set(per_nodehost.values()) == {106, 107}
    assert sum(per_nodehost.values()) == 1280
    assert collections.Counter(node["az_id"] for node in nodes) == {
        "az-a": 640,
        "az-b": 640,
    }
    shards: dict[str, set[str]] = collections.defaultdict(set)
    for node in nodes:
        shards[node["shard_id"]].add(node["nodehost_id"])
    assert len(shards) == 256
    assert all(len(hosts) == 5 for hosts in shards.values()), "a shard shares a nodehost"
