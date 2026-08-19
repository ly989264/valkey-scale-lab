from __future__ import annotations

import ast
import time
from pathlib import Path

import pytest

from valkey_scale_lab.config.simple_yaml import parse_config_file
from valkey_scale_lab.config.validation import load_effective_config, normalize_config
from valkey_scale_lab.observability.cluster import MySlots
from valkey_scale_lab.nodehost_density import NodehostDensityError, build_nodehost_density_plan
from valkey_scale_lab.planner.plan import build_cluster_plan, create_plan_file
from valkey_scale_lab import resource
from valkey_scale_lab.runtime import docker_runtime


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


def test_bounded_parallel_does_not_report_a_worker_socket_timeout_as_its_own_budget() -> None:
    """A worker's `TimeoutError` is not this pool's timeout, and on 3.11+ they are
    the same class.

    `concurrent.futures.TimeoutError is TimeoutError is socket.timeout`, so the
    old `except FutureTimeoutError` around `future.result()` caught a plain RESP
    read timeout and reported it as the parallelism budget being exceeded.
    Measured on a real 1280-node run: it died at 448s claiming a 10225.7s budget
    was blown, while 1023 of 1024 workers had finished in 98s.

    On Python 3.9 (this workstation) those classes are distinct, so this test
    passes trivially there and is only a live regression guard on 3.11+ - which
    is the controllers, and is precisely why the workstation suite never caught
    it. Mutation-check it on the controller, not here.
    """

    def worker(item: int) -> int:
        if item == 3:
            raise TimeoutError("timed out reading from 127.0.0.1:7801")
        return item

    with pytest.raises(TimeoutError, match="timed out reading from"):
        docker_runtime._bounded_parallel(
            range(8), worker, parallelism=4, timeout=600.0, label="probe"
        )

    # And the pool's own budget still reports as itself.
    def slow(item: int) -> int:
        time.sleep(5)
        return item

    with pytest.raises(docker_runtime.DockerRuntimeError, match="exceeded .* with parallelism"):
        docker_runtime._bounded_parallel(
            range(4), slow, parallelism=1, timeout=1.0, label="slow probe"
        )


def test_bounded_parallel_returns_every_result_when_nothing_fails() -> None:
    got = docker_runtime._bounded_parallel(
        range(20), lambda i: i * 2, parallelism=4, timeout=60.0, label="ok"
    )
    assert sorted(got) == [i * 2 for i in range(20)]


def test_convergence_no_progress_bound_scales_with_node_count() -> None:
    """The 240s constant said in its own comment that it was not scale-free.

    Re-measured at 1280 nodes: replicas leave `CLUSTER SHARDS`' `loading` set
    steadily but with a lengthening tail, and three real runs were failed with a
    single replica still loading. The dwell is close to linear in node count
    (14.3s at 30, 83.1s at 200), so the same 2.9x margin the constant already
    used gives 1.25s per node.
    """
    from valkey_scale_lab.observability.cluster import (
        CONVERGENCE_NO_PROGRESS_SECONDS,
        convergence_no_progress_seconds,
    )

    # The floor holds where the baselines were taken.
    assert convergence_no_progress_seconds(30) == CONVERGENCE_NO_PROGRESS_SECONDS
    assert convergence_no_progress_seconds(50) == CONVERGENCE_NO_PROGRESS_SECONDS
    assert convergence_no_progress_seconds(192) == CONVERGENCE_NO_PROGRESS_SECONDS
    # And it really does scale above it, which is the whole point.
    assert convergence_no_progress_seconds(200) == 250.0
    assert convergence_no_progress_seconds(1280) == 1600.0
    # A bound below the 240s floor is never produced.
    assert convergence_no_progress_seconds(0) == CONVERGENCE_NO_PROGRESS_SECONDS


def test_a_failing_reclaim_does_not_replace_the_failure_that_caused_it() -> None:
    """`m4_first_1280_run_map.md` §5.2, which cost two of four 1280-node runs.

    The failure handler called `reclaim_run` and then `raise`; when the reclaim
    raised, the bare `raise` never ran and its exception became the reported
    cause. Both times the real failure survived only in the command audit, and
    one of them was a convergence stall that took two further runs to name.

    Asserted on the parsed tree rather than the text: every `except` handler that
    reclaims must guard the reclaim and must end by re-raising the original.
    """
    import ast

    tree = ast.parse(Path("src/valkey_scale_lab/runtime/lifecycle.py").read_text())
    handlers = [
        h
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for h in node.handlers
        if any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "reclaim_run"
            for c in ast.walk(h)
        )
    ]
    assert handlers, "no failure handler reclaims; this test is guarding nothing"
    for h in handlers:
        # the reclaim is wrapped
        guarded = [n for n in h.body if isinstance(n, ast.Try)]
        assert guarded, "reclaim_run in a failure handler must be guarded"
        assert any(g.handlers for g in guarded), "the guard must catch"
        # and the original still propagates, as the last thing the handler does
        last = h.body[-1]
        assert isinstance(last, ast.Raise) and last.exc is None, (
            "the failure handler must end in a bare `raise` so the original "
            "exception is what propagates"
        )


def test_cluster_meet_retries_a_transient_failure() -> None:
    """One MEET of 1024 timing out ended a real 1280-node run.

    Every sibling in formation retries; this one issued a single command. MEET is
    safe to repeat, so the retry belongs here rather than in a wider timeout.
    """
    calls = {"n": 0}

    def flaky(node, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("timed out")
        return "OK"

    src = {"logical_id": "shard-0000-primary", "nodehost_container_ip": "10.0.0.1", "client_port": 7800}
    tgt = {"logical_id": "shard-0001-primary", "nodehost_container_ip": "10.0.0.2", "client_port": 7801}

    saved = docker_runtime._node_command
    try:
        docker_runtime._node_command = flaky
        docker_runtime._meet_node_pair(src, tgt)          # succeeds on the third try
        assert calls["n"] == 3

        calls["n"] = 0

        def always(node, *args, **kwargs):
            calls["n"] += 1
            raise TimeoutError("timed out")

        docker_runtime._node_command = always
        with pytest.raises(docker_runtime.DockerRuntimeError, match="CLUSTER MEET .* failed after"):
            docker_runtime._meet_node_pair(src, tgt)
        assert calls["n"] == docker_runtime.MEET_ATTEMPTS   # bounded, not infinite
    finally:
        docker_runtime._node_command = saved


def test_replica_of_wait_tolerates_an_unanswered_probe() -> None:
    """The next stage of the pipeline whose previous stage had this same defect.

    `_process_node_is_replica_of` is a 5s probe; calling it unguarded made one
    slow answer end the wait, and it is fanned over all 1024 replicas each
    polling once a second. An unanswered probe is "not yet confirmed".
    """
    calls = {"n": 0}

    def flaky(node, master_id):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("timed out")
        return True

    saved = docker_runtime._process_node_is_replica_of
    try:
        docker_runtime._process_node_is_replica_of = flaky
        docker_runtime._wait_process_replica_of({"logical_id": "r"}, "mid", timeout=30)
        assert calls["n"] == 3

        # and a probe that never answers still fails on the deadline, not early
        calls["n"] = 0

        def never(node, master_id):
            calls["n"] += 1
            raise TimeoutError("timed out")

        docker_runtime._process_node_is_replica_of = never
        with pytest.raises(docker_runtime.DockerRuntimeError, match="did not become replica"):
            docker_runtime._wait_process_replica_of({"logical_id": "r"}, "mid", timeout=2)
        assert calls["n"] >= 1
    finally:
        docker_runtime._process_node_is_replica_of = saved


def _cluster_myid_reads() -> tuple[dict[int, str], set[int]]:
    """Every `CLUSTER MYID` read in the runtime, and which are retried.

    Structural rather than textual on purpose. The first version of a sibling
    regression test searched a function's source for `"OSError"` and passed with
    the fix reverted, because the explanatory comment above it said "OSError";
    an AST walk cannot be satisfied by a comment.
    """

    tree = ast.parse(Path(docker_runtime.__file__).read_text(encoding="utf-8"))

    def is_myid(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_node_command"):
            return False
        literals = [a.value for a in node.args if isinstance(a, ast.Constant)]
        return "CLUSTER" in literals and "MYID" in literals

    # The reads that sit inside a lambda handed to `_retry_read`.
    retried: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_retry_read"
        ):
            for argument in list(node.args) + [kw.value for kw in node.keywords]:
                if isinstance(argument, ast.Lambda):
                    retried.update(
                        id(inner) for inner in ast.walk(argument) if is_myid(inner)
                    )

    # Each read, attributed to the module-level function that contains it -
    # not the innermost, which for a fan-out is an anonymous nested worker whose
    # name says nothing about which lane the read is on.
    owner: dict[int, str] = {}
    for scope in tree.body:
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(scope):
            if is_myid(inner):
                owner[id(inner)] = scope.name

    return owner, retried


def test_every_cluster_myid_read_in_the_management_and_fault_lanes_is_retried() -> None:
    """The seventh instance of one shape, and the guard against an eighth.

    A single un-retried RESP command inside a fan-out was found four times on
    the formation path, each costing a real 1280-node run. These are the same
    shape in the management and fault lanes: `CLUSTER MYID` read once, with the
    answer then addressing every `SETSLOT`, `MIGRATE`, `FORGET` or `REPLICATE`
    that follows - so a transient ends the operation before any of it runs.

    Asserted as a *set of exceptions* rather than a count, so that a newly added
    un-retried read fails here by name wherever it is written.
    """

    owner, retried = _cluster_myid_reads()
    unretried = {name for node_id, name in owner.items() if node_id not in retried}

    assert unretried == {"_cluster_node_ids_by_shard"}, unretried

    # And the retried ones are the seven converted here plus the one `5082e4e8`
    # already did, so removing a wrapper is caught rather than merely tolerated.
    assert len(retried) == 8


def test_the_one_unretried_cluster_myid_read_is_reached_only_from_formation() -> None:
    """Why `_cluster_node_ids_by_shard` is exempted above, checked rather than asserted.

    It is a genuine un-retried read inside a `_bounded_parallel` fan-out over
    every primary - 256 of them at 1280 nodes - so the exemption is a statement
    about *which lane it is on*, not about it being safe. It is reached only
    from cluster formation and setup, which is a separately audited path, and
    converting it would change a path every frozen baseline was taken on. This
    test exists so the exemption stops holding the moment a management or fault
    caller appears.
    """

    tree = ast.parse(Path(docker_runtime.__file__).read_text(encoding="utf-8"))
    callers: set[str] = set()
    for scope in ast.walk(tree):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if scope.name == "_cluster_node_ids_by_shard":
            continue
        for inner in ast.walk(scope):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "_cluster_node_ids_by_shard"
            ):
                callers.add(scope.name)

    assert callers and all(
        "management" not in name and "fault" not in name for name in callers
    ), callers


def _topology_nodes(count: int = 3) -> list[dict[str, object]]:
    return [
        {
            "logical_id": f"shard-{i:04d}-primary",
            "shard_id": f"shard-{i:04d}",
            "host": "127.0.0.1",
            "client_port": 7400 + i,
            "role": "primary",
        }
        for i in range(count)
    ]


def _install_probe_rows(monkeypatch, sequence) -> list[list[str]]:
    """Serve `_light_probe_rows` from a scripted sequence, recording each scope."""

    scopes: list[list[str]] = []
    calls = {"n": 0}

    def fake(nodes):
        scopes.append([str(n["logical_id"]) for n in nodes])
        rows = sequence[min(calls["n"], len(sequence) - 1)]
        calls["n"] += 1
        wanted = {str(n["logical_id"]) for n in nodes}
        return [r for r in rows if r["logical_id"] in wanted]

    monkeypatch.setattr(docker_runtime, "_light_probe_rows", fake)
    monkeypatch.setattr(docker_runtime, "TOPOLOGY_GAP_PAUSE_SECONDS", 0.0)
    return scopes


def _ok_row(logical_id: str) -> dict[str, object]:
    shard = logical_id.rsplit("-", 1)[0]
    return {
        "logical_id": logical_id,
        "status": "OK",
        # `role` here is the parsed ROLE reply the topology reader consults for
        # link state, not a bare string.
        "role": {"role": "primary", "replication_state": "connected"},
        "cluster_info": {
            "cluster_state": "ok",
            "cluster_known_nodes": "3",
            "cluster_slots_assigned": "16384",
            "cluster_slots_ok": "16384",
            "cluster_slots_fail": "0",
        },
        "myslots": MySlots(
            node_id=f"id-{logical_id}",
            shard_id=shard,
            role="primary",
            slot_owner_id=f"id-{logical_id}",
            slot_count=0,
            bitmap_encoding="raw",
            bitmap=b"\x00" * 2048,
        ),
    }


def _gap_row(logical_id: str, *, transient: bool) -> dict[str, object]:
    return {
        "logical_id": logical_id,
        "status": "FAIL",
        "error": "TimeoutError: timed out" if transient else "SemanticFailure: wrong role",
        # Both render as `semantic` on the verdict axis, which is exactly why the
        # retry layer cannot key on `failure_kind` and needs its own field.
        "failure_kind": "semantic",
        "transport_transient": transient,
    }


def test_a_transient_topology_gap_is_asked_again_before_it_ends_an_operation(monkeypatch) -> None:
    """The highest-count instance of the shape that cost five paid runs.

    Eleven management operations take this reading before and after themselves,
    so at 1280 nodes a run makes tens of thousands of single node observations
    through here, any one of which used to be fatal. A node servicing gossip
    from 1279 peers occasionally answers slowly.
    """

    nodes = _topology_nodes(3)
    ids = [str(n["logical_id"]) for n in nodes]
    scopes = _install_probe_rows(
        monkeypatch,
        [
            # First round: one node times out.
            [_ok_row(ids[0]), _gap_row(ids[1], transient=True), _ok_row(ids[2])],
            # Re-ask: it answers.
            [_ok_row(ids[0]), _ok_row(ids[1]), _ok_row(ids[2])],
        ],
    )

    topology = docker_runtime._management_require_live_topology(nodes, "probe")

    assert set(topology) == set(ids)
    # Only the gapped node was re-probed - at 1280 nodes re-reading the fleet
    # would make the retry itself the O(N) round this must not become.
    assert scopes == [ids, [ids[1]]]


def test_a_topology_gap_that_never_clears_still_ends_the_operation(monkeypatch) -> None:
    """The accept condition is unchanged: this re-asks, it does not tolerate."""

    nodes = _topology_nodes(3)
    ids = [str(n["logical_id"]) for n in nodes]
    scopes = _install_probe_rows(
        monkeypatch,
        [[_ok_row(ids[0]), _gap_row(ids[1], transient=True), _ok_row(ids[2])]],
    )

    with pytest.raises(docker_runtime.DockerRuntimeError, match="probe"):
        docker_runtime._management_require_live_topology(nodes, "probe")

    # Bounded, and every attempt after the first re-probes only the gap.
    assert len(scopes) == docker_runtime.TOPOLOGY_GAP_ATTEMPTS
    assert scopes[1:] == [[ids[1]]] * (docker_runtime.TOPOLOGY_GAP_ATTEMPTS - 1)


def test_a_non_transient_topology_gap_is_not_retried_at_all(monkeypatch) -> None:
    """A node that answered and disagreed is a confirmed failure.

    Retrying it is the fail-open direction: it spends the budget reaching the
    same verdict and makes a real failure look intermittent. This is the
    property that keeps the re-ask safe, so it is asserted rather than assumed.
    """

    nodes = _topology_nodes(3)
    ids = [str(n["logical_id"]) for n in nodes]
    scopes = _install_probe_rows(
        monkeypatch,
        [[_ok_row(ids[0]), _gap_row(ids[1], transient=False), _ok_row(ids[2])]],
    )

    with pytest.raises(docker_runtime.DockerRuntimeError):
        docker_runtime._management_require_live_topology(nodes, "probe")

    assert scopes == [ids]


def test_a_mixed_gap_set_is_not_retried_because_one_is_confirmed(monkeypatch) -> None:
    """§12.2's precedence: a confirmed failure outranks any number of transports."""

    nodes = _topology_nodes(3)
    ids = [str(n["logical_id"]) for n in nodes]
    scopes = _install_probe_rows(
        monkeypatch,
        [[_ok_row(ids[0]), _gap_row(ids[1], transient=True), _gap_row(ids[2], transient=False)]],
    )

    with pytest.raises(docker_runtime.DockerRuntimeError):
        docker_runtime._management_require_live_topology(nodes, "probe")

    assert scopes == [ids]


def _forget_row(monkeypatch, exc):
    """One `CLUSTER FORGET` attempt whose transport raises `exc`."""

    log: list[dict[str, object]] = []

    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(docker_runtime, "_node_command", boom)
    docker_runtime._management_log_forget_removed_node(
        log,
        telemetry=docker_runtime.TelemetryRun(
            capability_id="c", scenario_name="s", run_id="r"
        ),
        capability_id="c",
        parent_run_id="r",
        operation_id="op",
        target={"logical_id": "shard-0000-primary", "client_port": 7400},
        removed_id="deadbeef",
    )
    return log


def test_a_transient_forget_failure_stays_inside_the_convergence_loop(monkeypatch) -> None:
    """It is issued to every survivor on every round of a 120s loop.

    At 1280 nodes that is 1,279 survivors per removal operation times four
    operations times a round every two seconds - over five thousand commands per
    run - and a single transport failure used to raise straight out of the loop
    that exists to re-issue exactly this command. The error *reply* case was
    already tolerated for the same reason.
    """

    log = _forget_row(monkeypatch, TimeoutError("timed out"))

    assert len(log) == 1
    assert log[0]["status"] == "FAIL"
    # The row says why it did not end the run, so a reader can see the loop
    # absorbed it rather than that nothing happened.
    assert log[0]["retry_eligible"] is True


def test_a_non_transient_forget_failure_still_ends_the_operation(monkeypatch) -> None:
    """Only transport is absorbed; a real refusal is still the cluster's answer."""

    with pytest.raises(docker_runtime.DockerRuntimeError, match="cluster_forget_removed_node"):
        _forget_row(monkeypatch, RuntimeError("ERR something the server means"))


def test_a_forget_row_that_never_waited_is_unchanged(monkeypatch) -> None:
    """The new key appears only on the branch that needs it.

    `management_command_log` is a diffed artifact and every frozen baseline was
    taken before this field existed, so a run with no transient must produce
    byte-identical rows.
    """

    log: list[dict[str, object]] = []
    monkeypatch.setattr(docker_runtime, "_node_command", lambda *a, **k: "OK")
    docker_runtime._management_log_forget_removed_node(
        log,
        telemetry=docker_runtime.TelemetryRun(capability_id="c", scenario_name="s", run_id="r"),
        capability_id="c",
        parent_run_id="r",
        operation_id="op",
        target={"logical_id": "shard-0000-primary", "client_port": 7400},
        removed_id="deadbeef",
    )
    assert log[0]["status"] == "PASS"
    assert "retry_eligible" not in log[0]


def _unguarded_reads(*, management_scopes_only: bool = True) -> set[str]:
    """Management/fault reads that still issue a single un-retried RESP command.

    Structural, and asserted as a *set* so a newly added one fails by name. The
    four transports these cover are the ones the audit found: a bare
    `RespConnection`, `_node_response`, `_host_command_binary`, and
    `_node_command`. `_node_command`'s own reads are pinned separately by the
    `CLUSTER MYID` test above.
    """

    tree = ast.parse(Path(docker_runtime.__file__).read_text(encoding="utf-8"))
    transports = {"_node_response", "_host_command_binary", "RespConnection"}

    def transport_calls(node: ast.AST) -> set[int]:
        return {
            id(inner)
            for inner in ast.walk(node)
            if isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Name)
            and inner.func.id in transports
        }

    # A nested `def` handed to `_retry_read` by name is as guarded as a lambda
    # written inline; a multi-statement body cannot be a lambda, so both shapes
    # occur and the guard has to see through both.
    nested: dict[str, ast.AST] = {
        inner.name: inner
        for inner in ast.walk(tree)
        if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    retried: set[int] = set()
    for node in ast.walk(tree):
        # Guarded by `_retry_read`.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_retry_read"
        ):
            for argument in list(node.args) + [kw.value for kw in node.keywords]:
                retried |= transport_calls(argument)
                if isinstance(argument, ast.Name) and argument.id in nested:
                    retried |= transport_calls(nested[argument.id])
        # Or guarded by an enclosing `try` that handles the failure itself -
        # `_management_wait_node_role` polls inside one, which is a different
        # shape of the same protection and must not be reported as a defect.
        if isinstance(node, ast.Try) and node.handlers:
            for statement in node.body:
                retried |= transport_calls(statement)

    bare: set[str] = set()
    for scope in tree.body:
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if management_scopes_only and not scope.name.startswith(
            ("_management", "_run_scalable")
        ):
            continue
        for inner in ast.walk(scope):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id in transports
                and id(inner) not in retried
            ):
                bare.add(scope.name)
    return bare


def test_the_management_lane_has_no_unretried_single_shot_reads_left(
) -> None:
    """F4, F7 and F8 of the audit, and the guard against a fourth.

    Each was one RESP command with no retry at any level, inside a lane that
    issues it thousands of times per 1280-node run: `CLUSTER SHARDS` asking
    whether a removed node is gone, `CLUSTER GETKEYSINSLOT` driving a slot
    drain, and two `CLUSTER MYSLOTS` verifying slot ownership. The drain one
    died *mid slot move*, leaving the slot IMPORTING on one node and MIGRATING
    on the other.
    """

    assert _unguarded_reads() == set(), _unguarded_reads()


def test_a_transient_makes_cluster_health_unknown_and_is_asked_again(monkeypatch) -> None:
    """`cluster_state` is `ok` only when every node answered.

    So one transport failure out of 1280 turned the whole summary `unknown`.
    That is fatal where a caller gates on it - the reshard's clean-cluster
    precondition and the recovery verification both raise - and worse where one
    does not: an `after` reading feeds `pass_status`, so a transient wrote a
    **FAIL for an operation that had succeeded**, which is a wrong claim left in
    the evidence rather than a stopped run.
    """

    nodes = _topology_nodes(3)
    ids = [str(n["logical_id"]) for n in nodes]
    scopes = _install_probe_rows(
        monkeypatch,
        [
            [_ok_row(ids[0]), _gap_row(ids[1], transient=True), _ok_row(ids[2])],
            [_ok_row(ids[0]), _ok_row(ids[1]), _ok_row(ids[2])],
        ],
    )

    health = docker_runtime._management_cluster_health_settled(nodes)

    assert health["cluster_state"] == "ok"
    assert scopes == [ids, [ids[1]]]


def test_a_confirmed_bad_node_still_makes_cluster_health_unknown(monkeypatch) -> None:
    """The re-ask must not turn a real failure into a clean cluster."""

    nodes = _topology_nodes(3)
    ids = [str(n["logical_id"]) for n in nodes]
    scopes = _install_probe_rows(
        monkeypatch,
        [[_ok_row(ids[0]), _gap_row(ids[1], transient=False), _ok_row(ids[2])]],
    )

    health = docker_runtime._management_cluster_health_settled(nodes)

    assert health["cluster_state"] == "unknown"
    # Not retried at all: a node that answered and disagreed is confirmed.
    assert scopes == [ids]


def test_the_topology_snapshot_still_records_a_gap_rather_than_re_asking(monkeypatch) -> None:
    """A snapshot is evidence, not a gate, and says so in its own comment.

    Re-asking there would hide the per-node gap the snapshot exists to keep, so
    the settled reading is deliberately not wired into it.
    """

    nodes = _topology_nodes(3)
    ids = [str(n["logical_id"]) for n in nodes]
    scopes = _install_probe_rows(
        monkeypatch,
        [[_ok_row(ids[0]), _gap_row(ids[1], transient=True), _ok_row(ids[2])]],
    )

    health = docker_runtime._management_cluster_health(nodes)

    assert health["cluster_state"] == "unknown"
    assert scopes == [ids]


def test_a_fault_probe_survivor_read_is_retried_without_ending_the_run(monkeypatch) -> None:
    """Every exception on a fault probe is run-fatal, so this was too.

    The read is of the *survivor's* own view while a different node is paused -
    idempotent, and nothing to do with the fault's answer. The pause is shorter
    than `_retry_read`'s default because this runs inside the applied fault.
    """

    calls = {"n": 0}

    def flaky(node, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("timed out")
        return "cluster_state:ok\r\n"

    class _Backend:
        def pause_node(self, _target): return [{"action": "pause"}]
        def resume_node(self, _target): return [{"action": "resume"}]

    monkeypatch.setattr(docker_runtime, "_node_command", flaky)
    monkeypatch.setattr(docker_runtime, "_management_wait_clean_cluster", lambda *a, **k: None)
    monkeypatch.setattr(docker_runtime.time, "sleep", lambda _s: None)

    result = docker_runtime._local_full_flow_process_pause_probe(
        {"logical_id": "shard-0000-replica-00"},
        {"logical_id": "shard-0000-primary", "client_port": 7400},
        _topology_nodes(2),
        backend=_Backend(),
    )

    assert "cluster_state:" in result["observed_cluster_info"]
    assert calls["n"] == 2


def test_retry_read_is_bounded_and_reads_only() -> None:
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("timed out")
        return "ok"

    assert docker_runtime._retry_read(flaky, what="probe", pause=0.0) == "ok"

    calls["n"] = 0

    def never():
        calls["n"] += 1
        raise TimeoutError("timed out")

    with pytest.raises(docker_runtime.DockerRuntimeError, match="probe failed after 3 attempts"):
        docker_runtime._retry_read(never, what="probe", pause=0.0)
    assert calls["n"] == 3


def test_replica_sync_wait_retries_transport_not_only_error_replies() -> None:
    """`TimeoutError` subclasses `OSError`, which the loop's except omitted.

    So error *replies* were retried (ValkeyErrorReply subclasses
    DockerRuntimeError) and transport failures were not - in a loop whose whole
    purpose is to retry.

    Asserted on the parsed handler, not on the source text: the first version of
    this test searched the function source for "OSError" and passed even with the
    except narrowed, because the explanatory comment above it says "OSError".
    The mutation check is what caught that.
    """
    import ast
    import inspect
    import textwrap

    assert issubclass(TimeoutError, OSError)  # the premise, on every version

    fn = docker_runtime._management_matrix_wait_replica_sync_ready
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    caught: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            names = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
            caught |= {n.id for n in names if isinstance(n, ast.Name)}
    assert "OSError" in caught, (
        "the retry loop must catch OSError; without it a socket timeout escapes "
        f"a loop that exists to retry. caught={sorted(caught)}"
    )


def _reread_probe(outcomes_by_node, *, attempts, nodes=None, **kwargs):
    """A light probe whose transport yields per-node outcomes in order."""

    from valkey_scale_lab.observability.cluster import LightClusterProbe, NodeEndpoint

    endpoints = nodes or [
        NodeEndpoint(
            logical_id=f"n{index}",
            host="127.0.0.1",
            port=7400 + index,
            expected_role="primary",
            expected_shard=f"shard-{index}",
            az_id="az-a",
            placement_id=f"p{index}",
        )
        for index in range(len(outcomes_by_node))
    ]
    calls: dict[str, int] = {}

    probe = LightClusterProbe(
        endpoints,
        transport_reread_attempts=attempts,
        transport_reread_pause=0.0,
        **kwargs,
    )

    def observe(node):
        index = calls.get(node.logical_id, 0)
        calls[node.logical_id] = index + 1
        outcomes = outcomes_by_node[node.logical_id]
        outcome = outcomes[min(index, len(outcomes) - 1)]
        if isinstance(outcome, BaseException):
            return LightClusterProbe._failed_row(node, outcome, 0.0, 0.0)
        return {"logical_id": node.logical_id, "status": "OK", "answer": outcome}

    probe.observe_node = observe  # type: ignore[method-assign]
    return probe, calls


def test_a_transport_gap_is_reread_and_the_row_is_replaced() -> None:
    """The F6 defect: one unanswered node of 1,279 ended a paid run.

    The down-window validation runs while the primary is dead and the fleet is
    gossiping the failure, which is when a 5s read is least likely to answer.
    """

    probe, calls = _reread_probe(
        {"n0": [TimeoutError("timed out"), "second"], "n1": ["first"]},
        attempts=3,
    )
    rows = probe._reread_transport_gaps(probe.collect(), ())
    assert [row["status"] for row in rows] == ["OK", "OK"]
    assert calls == {"n0": 2, "n1": 1}, "only the gapped node is asked again"


def test_a_semantic_answer_is_never_reread() -> None:
    """The gate that makes this a transport re-read and not a convergence wait.

    A node answering with the wrong role is an observation - re-asking would only
    delay the report by the whole budget - and `is_transient_transport_error` is
    an allowlist that excludes `SemanticFailure`, so it is not eligible.
    """

    from valkey_scale_lab.observability.contracts import SemanticFailure

    probe, calls = _reread_probe(
        {"n0": [SemanticFailure("ROLE disagrees with CLUSTER MYSLOTS role")]},
        attempts=3,
    )
    rows = probe._reread_transport_gaps(probe.collect(), ())
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["transport_transient"] is False
    assert calls == {"n0": 1}, "a semantic disagreement must not be re-read"


def test_a_planned_down_node_is_never_reread() -> None:
    """Load-bearing rather than tidy.

    At the primary-kill down-window the killed node is in `self.nodes` and
    refuses every connection. Without this exclusion every run would pay the
    whole pause budget re-reading a node it deliberately stopped - measured
    across 91 retained runs, the re-read otherwise never fires at all.
    """

    probe, calls = _reread_probe(
        {"n0": [ConnectionRefusedError("refused")], "n1": ["fine"]},
        attempts=3,
    )
    rows = probe._reread_transport_gaps(probe.collect(), {"n0"})
    assert calls == {"n0": 1, "n1": 1}
    assert rows[0]["status"] == "FAIL"


def test_a_node_that_never_answers_still_fails_the_validation() -> None:
    """The accept condition is unchanged: the budget is bounded and fails closed."""

    probe, calls = _reread_probe({"n0": [TimeoutError("timed out")]}, attempts=3)
    rows = probe._reread_transport_gaps(probe.collect(), ())
    assert calls == {"n0": 3}
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["transport_reread_attempt"] == 2


def test_the_default_probe_never_rereads() -> None:
    """Every existing caller keeps a single observation.

    Only the one site that owns a one-shot raises this, so no frozen baseline's
    path changes.
    """

    from valkey_scale_lab.observability.cluster import (
        FullClusterValidator,
        LightClusterProbe,
        NodeEndpoint,
    )

    node = NodeEndpoint(
        logical_id="n0",
        host="127.0.0.1",
        port=7400,
        expected_role="primary",
        expected_shard="s",
        az_id="az-a",
        placement_id="p",
    )
    assert LightClusterProbe([node]).transport_reread_attempts == 1
    assert FullClusterValidator([node]).light.transport_reread_attempts == 1


def test_run_applies_the_reread_before_validating() -> None:
    """The wiring, so enabling the knob is not silently inert.

    `run` is `validate(collect())`; the re-read sits between them, so a gap that
    clears on a second ask must reach `validate` as an answer.
    """

    probe, calls = _reread_probe(
        {"n0": [TimeoutError("timed out"), "second"]}, attempts=3
    )
    seen: list[list[dict[str, object]]] = []
    probe.validate = lambda rows, **_k: seen.append(rows) or {"status": "OK"}  # type: ignore[method-assign]
    probe.run()
    assert calls == {"n0": 2}
    assert seen[0][0]["status"] == "OK"


def test_the_down_window_validation_enables_the_reread() -> None:
    """The one enabled site, asserted structurally.

    A transport re-read that is present but not switched on at the site the audit
    named would pass every test above and change nothing on a real run.
    """

    source = Path(docker_runtime.__file__).read_text(encoding="utf-8")
    marker = "def full_validation_while_target_down()"
    assert marker in source
    body = source[source.index(marker) : source.index(marker) + 2000]
    assert "convergence_timeout=0.0" in body
    assert "transport_reread_attempts=3" in body
def _mutation_row(monkeypatch, kind, outcomes, *, pause=None):
    """One chokepoint mutation whose transport yields `outcomes` in order.

    `outcomes` members are either an exception to raise or a string to return,
    so a test can express "fails once then answers" as well as "always fails".
    """

    log: list[dict[str, object]] = []
    calls: list[int] = []
    remaining = list(outcomes)

    def transport(*_a, **_k):
        calls.append(1)
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(docker_runtime, "_node_command", transport)
    # Real pauses would make the suite sleep for the reissue budget.
    monkeypatch.setattr(
        docker_runtime, "MANAGEMENT_MUTATION_REISSUE_PAUSE_SECONDS", pause or 0.0
    )
    docker_runtime._management_log_node_command(
        log,
        telemetry=docker_runtime.TelemetryRun(
            capability_id="c", scenario_name="s", run_id="r"
        ),
        capability_id="c",
        parent_run_id="r",
        operation_id="op",
        command_kind=kind,
        target={"logical_id": "shard-0000-primary", "client_port": 7400},
        args=["CLUSTER", "SETSLOT", 0, "NODE", "deadbeef"],
        timeout=30,
    )
    return log, len(calls)


def test_setslot_transient_is_reissued_until_it_answers(monkeypatch) -> None:
    """SETSLOT is three quarters of a 1280-node run's ~34,500 mutations.

    Re-issuing `SETSLOT <slot> NODE <id>` with the same owner is a no-op, so an
    unknown outcome can simply be repeated. It is issued to *every* primary in a
    loop, so one slow node of 256 used to end the operation.
    """

    log, calls = _mutation_row(
        monkeypatch, "cluster_setslot_node", [TimeoutError("timed out"), "OK"]
    )
    assert calls == 2
    assert len(log) == 1, "a re-issue must not add a row"
    assert log[0]["status"] == "PASS"
    assert log[0]["attempt_count"] == 2


def test_setslot_that_never_answers_still_ends_the_run(monkeypatch) -> None:
    """`reissue` is bounded and fails closed.

    Nothing downstream would notice that one primary never learned the new slot
    owner - `_management_reshard_node_owns_slot` asks the *target* - so an
    exhausted re-issue must still raise.
    """

    with pytest.raises(docker_runtime.DockerRuntimeError, match="cluster_setslot_node"):
        _mutation_row(
            monkeypatch,
            "cluster_setslot_node",
            [TimeoutError("timed out")] * docker_runtime.MANAGEMENT_MUTATION_REISSUE_ATTEMPTS,
        )


def test_a_failover_is_never_reissued(monkeypatch) -> None:
    """The trap this item exists for.

    A second `CLUSTER FAILOVER` can start a second election, so a transport
    failure must not be repeated. `_management_wait_node_role` follows all three
    call sites and is the arbiter, so the chokepoint records the attempt and
    returns.
    """

    log, calls = _mutation_row(
        monkeypatch,
        "cluster_failover_before_primary_restart",
        [TimeoutError("timed out")],
    )
    assert calls == 1, "FAILOVER must be issued exactly once"
    assert log[0]["status"] == "FAIL"
    assert log[0]["retry_eligible"] is True
    assert "attempt_count" not in log[0]


def test_every_suppress_family_is_issued_exactly_once(monkeypatch) -> None:
    """Verify-only applies to each family whose arbiter already follows it."""

    for kind in (
        "cluster_failover_takeover_before_primary_remove",
        "cluster_failover_restore_primary_placement",
        "cluster_replicate_restored_primary",
        "cluster_replicate_restored_node",
        "cluster_migrate_keys",
    ):
        log, calls = _mutation_row(monkeypatch, kind, [TimeoutError("timed out")])
        assert calls == 1, kind
        assert log[0]["retry_eligible"] is True, kind


def test_an_error_reply_is_never_retried_or_suppressed(monkeypatch) -> None:
    """A node that answered `-ERR` was reached and will say it again.

    This is the axis `is_transient_transport_error` exists to separate: it is an
    allowlist, so `ValkeyErrorReply` is excluded by default rather than by a
    branch.
    """

    for kind in ("cluster_setslot_node", "cluster_failover_before_primary_restart"):
        calls: list[int] = []

        def transport(*_a, **_k):
            calls.append(1)
            raise docker_runtime.ValkeyErrorReply("ERR nope")

        monkeypatch.setattr(docker_runtime, "_node_command", transport)
        monkeypatch.setattr(
            docker_runtime, "MANAGEMENT_MUTATION_REISSUE_PAUSE_SECONDS", 0.0
        )
        log: list[dict[str, object]] = []
        with pytest.raises(docker_runtime.DockerRuntimeError):
            docker_runtime._management_log_node_command(
                log,
                telemetry=docker_runtime.TelemetryRun(
                    capability_id="c", scenario_name="s", run_id="r"
                ),
                capability_id="c",
                parent_run_id="r",
                operation_id="op",
                command_kind=kind,
                target={"logical_id": "shard-0000-primary", "client_port": 7400},
                args=["CLUSTER", "SETSLOT", 0, "NODE", "deadbeef"],
                timeout=30,
            )
        # The raise alone does not prove the doctrine: a re-issued error reply
        # would still end up raising, so the count is what says the answer was
        # believed the first time.
        assert calls == [1], f"{kind} re-issued a command the node had answered"
        assert "retry_eligible" not in log[0]


def test_an_unnamed_mutation_kind_still_fails_closed(monkeypatch) -> None:
    """Default is raise, so an eleventh kind inherits no policy."""

    with pytest.raises(docker_runtime.DockerRuntimeError, match="something_new"):
        _mutation_row(monkeypatch, "something_new", [TimeoutError("timed out")])


def test_a_mutation_row_that_never_failed_is_unchanged(monkeypatch) -> None:
    """`management_command_log` is diffed and `fault_command_log`'s 12 is pinned.

    A command that answered first time must write exactly the row it always
    wrote, so neither new key may appear.
    """

    log, calls = _mutation_row(monkeypatch, "cluster_setslot_node", ["OK"])
    assert calls == 1
    assert log[0]["status"] == "PASS"
    assert "attempt_count" not in log[0]
    assert "retry_eligible" not in log[0]


def test_the_mutation_policy_table_covers_every_kind_that_reaches_it() -> None:
    """Structural, asserted as a set so an eleventh kind fails by name.

    The chokepoint also serves the fault lane, so a kind added without a decided
    policy would silently inherit `raise` at a site where that ends a paid run.
    """

    source = Path(docker_runtime.__file__).read_text(encoding="utf-8")
    wrappers = {
        "_management_log_node_command",
        "_management_reshard_log_slot_command",
    }
    kinds: set[str] = set()
    non_literal: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else getattr(func, "attr", None)
        )
        if name not in wrappers:
            continue
        literals = [
            kw.value.value
            for kw in node.keywords
            if kw.arg == "command_kind" and isinstance(kw.value, ast.Constant)
        ]
        literals += [
            arg.value
            for arg in node.args
            if isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and arg.value.startswith("cluster_")
        ]
        if literals:
            kinds.update(literals)
        else:
            non_literal.append(node.lineno)

    assert kinds == set(docker_runtime._MANAGEMENT_MUTATION_TRANSPORT_POLICY), (
        "a command_kind reaching the mutation chokepoint has no decided policy"
    )
    # The single non-literal call is the pass-through wrapper forwarding its own
    # parameter. A second one would mean a kind computed at runtime, which this
    # table cannot cover.
    assert len(non_literal) == 1, non_literal


# The three module-wide exemptions, each for a *different* structural reason, so
# the list is a judgement recorded once rather than one that grows per finding.
MODULE_WIDE_UNRETRIED_READ_EXEMPTIONS = {
    # The transport primitive itself. Retrying inside it would blind-retry every
    # mutation that goes through it, which is the exact thing
    # `_management_log_node_command`'s policy table exists to prevent.
    "_node_command",
    # A leaf read whose safety is positional, not intrinsic: all three callers
    # wrap it in a bounded deadline loop that treats an unanswered probe as
    # "not yet confirmed" rather than as a failure.
    "_process_node_is_replica_of",
    # M2 measurement only - gated by `_m2_measurement_enabled()` at its single
    # call site and never reached on the full-flow path.
    "_natural_probe_key_for_primary",
}


def test_every_unretried_read_in_the_module_is_a_named_exemption() -> None:
    """The audit ledger, made executable beyond the management lane.

    The narrower guard above only inspects `_management*` and `_run_scalable*`
    scopes, so every other function in the module was exempt *by naming
    convention* - which is not a decision anyone took. Widened, exactly three
    remain, and each is listed with the reason it is safe. A fourth fails here by
    name wherever it is written, which is what makes the §7 ledger a check rather
    than prose.

    Deliberately not widened to every read verb: `_wait_process_*` predicates are
    un-retried by design because their enclosing loop is the retry, so an
    AST-only rule that could not see that would produce an exemption list that
    grows with every wait and stops meaning anything.
    """

    assert _unguarded_reads(management_scopes_only=False) == (
        MODULE_WIDE_UNRETRIED_READ_EXEMPTIONS
    ), _unguarded_reads(management_scopes_only=False)


def _parse_failure(payload: bytes) -> Exception:
    """What this module's own RESP parser raises for a broken stream."""

    import io

    try:
        docker_runtime._read_resp(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("stream did not fail")


def test_every_parse_failure_on_this_transport_is_classified_transient() -> None:
    """The gap that silently narrowed two landed fixes.

    `docker_runtime` has its own RESP parser, separate from `valkey/resp.py`, and
    it raised plain `DockerRuntimeError` where the predicate matches
    `RespProtocolError`/`EOFError`. So a node closing the connection mid-reply
    classified non-transient - and the management matrix restarts nodes as a
    matter of course, which is exactly when a peer closes mid-reply.

    The garbled-length case is the one a reading of the predicate would miss:
    `int()` on a desynced line raised a bare `ValueError`, which was not even a
    `DockerRuntimeError` and so escaped every handler on this transport.
    """

    from valkey_scale_lab.observability.contracts import is_transient_transport_error

    cases = {
        "closed connection": b"",
        "truncated line": b":12",
        "garbled length": b"$abc\r\n",
        "truncated bulk": b"$2\r\nabXX",
    }
    for label, payload in cases.items():
        exc = _parse_failure(payload)
        assert isinstance(exc, docker_runtime.RespTransportError), label
        assert is_transient_transport_error(exc) is True, label


def test_the_new_class_moves_no_verdict_and_no_existing_handler() -> None:
    """It inherits both on purpose, and both halves are load-bearing.

    `DockerRuntimeError` keeps every existing `except` on this transport catching
    what it caught before, so there is no blast radius. `RespProtocolError` is
    what the retry predicate matches. And `is_collection_failure` must still
    answer False, because a changed answer there would be a §12.1 verdict change
    rather than a retry-eligibility one.
    """

    from valkey_scale_lab.observability.contracts import is_collection_failure

    exc = _parse_failure(b"")
    assert isinstance(exc, docker_runtime.DockerRuntimeError)
    assert is_collection_failure(exc) is False


def test_an_error_reply_is_not_a_transport_failure() -> None:
    """The one stream failure that is an answer rather than a broken socket."""

    from valkey_scale_lab.observability.contracts import is_transient_transport_error

    exc = _parse_failure(b"-ERR no such key\r\n")
    assert isinstance(exc, docker_runtime.ValkeyErrorReply)
    assert not isinstance(exc, docker_runtime.RespTransportError)
    assert is_transient_transport_error(exc) is False


def test_every_full_cluster_validator_rereads_transport_gaps() -> None:
    """All seven sites, not just the down-window one.

    `FullClusterValidator.run` retries only `ConvergenceFailure`, so an
    unanswered node raises `SemanticFailure` straight out of *every* site
    regardless of its convergence timeout - the down-window was the worst
    instance, not the only one. Measured across 140 retained runs and 1,360 light
    validations, no site has ever seen an unexplained gap, so this costs nothing
    on a passing run.
    """

    source = Path(docker_runtime.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    sites = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "FullClusterValidator"
    ]
    assert len(sites) == 7, len(sites)
    without = [
        site.lineno
        for site in sites
        if not any(kw.arg == "transport_reread_attempts" for kw in site.keywords)
    ]
    assert without == [], without


def test_the_slot_drain_migrates_with_replace() -> None:
    """Without it the loop-continue dies on its second attempt.

    MIGRATE restores to the target then deletes locally, so a transport failure
    between those leaves the key on both nodes. The drain's next iteration
    re-reads `GETKEYSINSLOT`, still sees it on the source, and re-issues - which
    without REPLACE is `-BUSYKEY`, an error *reply*, which the chokepoint policy
    correctly refuses to retry. So the retry path would fail at exactly the
    failure it exists to absorb.

    Position matters: REPLACE is an option of MIGRATE and must precede KEYS.
    """

    source = Path(docker_runtime.__file__).read_text(encoding="utf-8")
    marker = '"MIGRATE", _cluster_meet_address(target)'
    assert marker in source
    argv_line = next(
        line for line in source.splitlines() if marker in line
    )
    assert '"REPLACE", "KEYS"' in argv_line, argv_line
