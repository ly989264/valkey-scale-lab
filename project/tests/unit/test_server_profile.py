from __future__ import annotations

from pathlib import Path

import pytest

from valkey_scale_lab import resource
from valkey_scale_lab.config.validation import load_effective_config, validate_config_file
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.server_profile import compute_effective_server_profile


def test_global_server_profile_defaults_to_one_b_dev_and_64mb() -> None:
    config = load_effective_config("templates/configs/scale_100.yaml")

    assert config["runtime"]["server_profile"] == "one_b_dev"
    assert config["runtime"]["valkey"]["io_threads"] == 1
    assert config["cluster"]["node_memory_limit_mb"] == 64
    assert config["_effective_server_profile"]["effective_io_threads"] == 1
    assert config["_effective_server_profile"]["effective_node_memory_limit_mb"] == 64


def test_cli_override_wins_for_io_threads_2(tmp_path: Path) -> None:
    report = validate_config_file(
        "templates/configs/scale_10.yaml",
        tmp_path / "config_validation_report.json",
        cli_overrides={"runtime": {"valkey": {"io_threads": 2, "io_threads_max_total": 64}}},
    )

    assert report["status"] == "PASS"
    assert report["requested_io_threads"] == 2
    assert report["effective_io_threads"] == 2
    assert report["requested_node_memory_limit_mb"] == 64
    assert report["effective_node_memory_limit_mb"] == 64
    assert report["io_thread_budget_status"] == "PASS"


def test_excessive_io_threads_degrades_with_reason() -> None:
    config = load_effective_config(
        "templates/configs/scale_30.yaml",
        cli_overrides={"runtime": {"valkey": {"io_threads": 99, "io_threads_max_per_node": 2, "io_threads_max_total": 60}}},
    )

    profile = compute_effective_server_profile(config, host_cpu_count=16, nodehost_count=2)

    assert profile["requested_io_threads"] == 99
    assert profile["effective_io_threads"] == 2
    assert profile["total_valkey_threads"] == 60
    assert profile["io_thread_budget_status"] == "DEGRADED_WITH_REASON"
    assert any("exceeds io_threads_max_per_node" in reason for reason in profile["io_thread_budget_reason"])


def test_resource_preflight_records_64mb_memory_and_blocks_when_insufficient(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(resource, "_docker_details", lambda: {"available": True, "server_version": "test"})
    monkeypatch.setattr(resource, "_cleanup_state_check", lambda capability_id, scenario, node_count: resource._check("previous_cleanup_state", True, {"node_count": node_count}))
    monkeypatch.setattr(resource, "_port_check", lambda base, count, name: resource._check(name, True, {"base": base, "count": count}))
    monkeypatch.setattr(resource, "_host_available_memory_mb", lambda: 1000)

    report = resource.run_resource_preflight("templates/configs/scale_30.yaml", tmp_path / "preflight.json")

    assert report["status"] == "FAIL"
    assert report["can_run"] is False
    assert report["node_memory_limit_mb"] == 64
    assert report["projected_node_memory_mb"] == 30 * 64
    assert report["host_available_memory_mb"] == 1000
    assert report["memory_budget_status"] == "FAIL"


def test_process_config_omits_io_threads_for_one_and_writes_two_with_maxmemory() -> None:
    base_node = {
        "run_id": "SERVER_PROFILE-test",
        "logical_id": "shard-0000-primary",
        "client_port": 7000,
        "cluster_bus_port": 17000,
        "requested_cluster_node_timeout_ms": 30000,
        "effective_cluster_node_timeout_ms": 30000,
        "cluster_node_timeout_source": "global",
        "cluster_node_timeout_profile": "MISSING",
        "effective_node_memory_limit_mb": 64,
    }
    nodehost = {"container_ip": "172.18.0.2"}

    text_one = docker_runtime._process_config_text({**base_node, "effective_io_threads": 1}, nodehost, replicas_per_shard=1)
    text_two = docker_runtime._process_config_text({**base_node, "effective_io_threads": 2}, nodehost, replicas_per_shard=1)

    assert "io-threads" not in text_one
    assert "maxmemory 64mb" in text_one
    assert "cluster-node-timeout 30000" in text_one
    assert "vslab cluster-node-timeout-source source=global" in text_one
    assert "io-threads 2" in text_two
    assert "maxmemory 64mb" in text_two


def test_the_topology_pin_appears_only_above_one_replica_per_shard() -> None:
    """§2.4's fix, and the byte-identity that keeps it off every existing run.

    Valkey's defaults are `cluster-migration-barrier 1` with replica migration
    allowed, so a shard holding spare replicas above the barrier may have one
    taken by another shard. At one replica a shard has no spare, which is why
    this has never mattered; at two or more the formation validator would see a
    replica under a different primary and raise a permanent `SemanticFailure`
    that nothing could attribute.

    The generated config is a diffed view of the `runtime_start` stage, so the
    one-replica text is compared line for line against the text produced when
    the shape is one replica - and to a frozen baseline's own file, below.
    """

    node = {
        "run_id": "pin-run",
        "logical_id": "shard-0000-primary",
        "client_port": 7400,
        "cluster_bus_port": 17400,
        "effective_io_threads": 1,
        "effective_node_memory_limit_mb": 64,
        "effective_cluster_node_timeout_ms": 30000,
        "requested_cluster_node_timeout_ms": 30000,
        "cluster_node_timeout_source": "global",
    }
    nodehost = {"container_ip": "172.18.0.2"}

    pin = "cluster-allow-replica-migration no"
    for replicas in (0, 1):
        text = docker_runtime._process_config_text(node, nodehost, replicas_per_shard=replicas)
        assert pin not in text
    baseline = docker_runtime._process_config_text(node, nodehost, replicas_per_shard=1)
    for replicas in (2, 3, 4):
        text = docker_runtime._process_config_text(node, nodehost, replicas_per_shard=replicas)
        assert text.count(pin) == 1
        # The pin is the only difference, and it sits directly after
        # `appendonly no` where the shape-independent lines resume.
        assert [line for line in text.splitlines() if line != pin] == baseline.splitlines()


def test_one_replica_node_config_differs_from_the_frozen_baseline_by_the_sendbuf_line_alone() -> None:
    """The `runtime_start` diff view compares this file, so it is compared here.

    `cluster-link-sendbuf-limit` is the only directive added to every node's
    config since those baselines were frozen, so byte identity is false *by
    declaration*: the declared `runtime_start` delta is one added line in every
    `node_configs/*.conf` and nothing else. Asserting the shape of the delta,
    rather than dropping the test, keeps every other byte of the generated
    config pinned to a real run's own file - which is what makes MR-1's r=1
    no-op proof checkable.
    """

    frozen = Path(
        "artifacts/baselines/exact-50-6b6f57fd/run-1/001-real.local.full-flow/runtime/node_configs"
    )
    if not frozen.is_dir():
        pytest.skip("the frozen exact-50 baseline is not present in this checkout")
    expected = (frozen / "shard-0000-primary.conf").read_text(encoding="utf-8")
    node = {
        "run_id": "local_full_flow-local_full_flow-20260628",
        "logical_id": "shard-0000-primary",
        "client_port": 7400,
        "cluster_bus_port": 17400,
        "effective_io_threads": 1,
        "effective_node_memory_limit_mb": 64,
        "effective_cluster_node_timeout_ms": 30000,
        "requested_cluster_node_timeout_ms": 30000,
        "cluster_node_timeout_source": "global",
        "cluster_node_timeout_profile": "MISSING",
    }
    produced = docker_runtime._process_config_text(
        node, {"container_ip": "172.18.0.2"}, replicas_per_shard=1
    )
    added = f"cluster-link-sendbuf-limit {docker_runtime.CLUSTER_LINK_SENDBUF_LIMIT_BYTES}"
    assert produced.count(added) == 1
    assert [line for line in produced.splitlines() if line != added] == expected.splitlines()


def test_the_sendbuf_cap_exceeds_one_whole_cluster_bus_message_at_every_admitted_scale() -> None:
    """The cap's floor is one message, not a memory budget, and this pins it.

    `freeClusterLinkOnBufferLimitReached` frees the link when the send queue
    exceeds the limit, so a cap below one message frees the link on the first
    ping that ever queues - during formation, which is exactly the scale the cap
    exists for. 39d44012's 32 KiB held two messages at N=1280 and a real run
    measured 33,000 link frees; `m4_first_1280_run_map.md` §7.1 recommended
    8 KiB, which is *half* a message there. This test is what would have caught
    both.

    The message size is the pinned build's own (valkey 9.1.0, `cluster_legacy.h`):
    a PING carries `floor(N * cluster-message-gossip-perc / 100)` gossip entries
    of `sizeof(clusterMsgDataGossip)` on a 2256-byte header. Both struct sizes
    are compiled facts and are stated as literals, because a test that recomputed
    them from the same assumption would assert nothing.

    There is deliberately **no** `sizeof(clusterMsg)` floor here. An earlier
    version of this test applied one at 4352 bytes; that floor is on the
    *allocation* and `totlen` is trimmed, which the measured byte-per-message
    figures in `m4_gossip_cost_and_stage_plan.md` §5.1 confirm to 1-2%. Applying
    it would overstate the smallest message and so understate the headroom this
    test is checking.
    """

    header_bytes = 2256
    gossip_entry_bytes = 104
    gossip_perc = 10  # cluster-message-gossip-perc, hidden config, default 10

    def ping_bytes(nodes: int) -> int:
        # `m4_gossip_cost_and_stage_plan.md` §5.1 measures a further ~33 bytes of
        # ping extensions on top of this. They are left out deliberately: this is
        # a *floor* on the message, and a floor that included an optional term
        # would be checking a larger message than the build is guaranteed to
        # send. At these margins it moves nothing - 33 bytes against 67x of
        # headroom - and the measured-against-modelled agreement §5.1 reports is
        # 1-2% with the extensions included.
        wanted = max(3, nodes * gossip_perc // 100)
        return header_bytes + gossip_entry_bytes * wanted

    # 1280 is the largest node count any bounded exception admits
    # (`scale_1280_native_ecs_optin`); 2000 is the scenario's own ceiling.
    for nodes in (6, 30, 50, 100, 200, 1280, 2000):
        message = ping_bytes(nodes)
        assert docker_runtime.CLUSTER_LINK_SENDBUF_LIMIT_BYTES > message, (
            f"the cap frees a link holding one {nodes}-node ping"
        )

    # A cap that merely clears one message would still free a link on the second,
    # which is a reconnect during formation rather than a runaway peer. The
    # measured average occupancy on a real 1280-node run was 12.6 KB, so require
    # real headroom over a whole message at the largest admitted scale.
    assert docker_runtime.CLUSTER_LINK_SENDBUF_LIMIT_BYTES >= 32 * ping_bytes(1280)


