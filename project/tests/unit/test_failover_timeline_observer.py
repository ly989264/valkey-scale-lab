from __future__ import annotations

import signal

import pytest

from valkey_scale_lab.metrics import nearest_rank
from valkey_scale_lab.observer import failover_timeline
from valkey_scale_lab.observer.failover_timeline import (
    ClientRecoveryAccumulator,
    FailoverTimelineError,
    FailoverTimelineObserver,
    ObserverEndpoint,
    OwnedProcessTarget,
    PersistentClusterClient,
    RespError,
    StableShardAccumulator,
    apply_owned_sigkill,
    build_rto_summary,
    derive_rto_metrics,
    percentile,
)


def complete_sample(**overrides):
    row = {
        "schema_version": "v1",
        "capability_id": "failover_timeline",
        "run_id": "run",
        "scenario_name": "scenario",
        "sample_id": "sample",
        "status": "PASS",
        "execution_mode": "real_valkey",
        "real_valkey": True,
        "node_count": 30,
        "scale": "30",
        "fault_apply_at_ms": 1000,
        "target_process_gone_at_ms": 1100,
        "first_pfail_seen_at_ms": 1200,
        "first_fail_seen_at_ms": 1300,
        "first_promotion_seen_at_ms": 1400,
        "first_slots_covered_at_ms": 1500,
        "first_cluster_ok_at_ms": 1600,
        "first_client_success_at_ms": 1700,
        "clean_snapshot_passed_at_ms": 2100,
    }
    row.update(derive_rto_metrics(row))
    row.update(overrides)
    return row


def test_derive_rto_metrics_separates_cluster_client_and_clean_tail() -> None:
    metrics = derive_rto_metrics(complete_sample())

    assert metrics["kill_to_pfail_ms"] == 200
    assert metrics["pfail_to_cluster_ok_ms"] == 400
    assert metrics["kill_to_client_recovered_ms"] == 700
    assert metrics["cluster_ok_to_client_success_ms"] == 100
    assert metrics["cluster_ok_to_clean_snapshot_ms"] == 500
    assert metrics["kill_to_clean_snapshot_ms"] == 1100


def test_derive_rto_metrics_fails_closed_on_missing_pfail() -> None:
    sample = complete_sample(first_pfail_seen_at_ms="MISSING")

    with pytest.raises(FailoverTimelineError, match="first_pfail_seen_at_ms"):
        derive_rto_metrics(sample)


def test_derive_rto_metrics_rejects_non_monotonic_client_recovery() -> None:
    sample = complete_sample(first_client_success_at_ms=1500)

    with pytest.raises(FailoverTimelineError, match="timestamps must be monotonic"):
        derive_rto_metrics(sample)


def test_derive_rto_metrics_rejects_clean_gate_substitution() -> None:
    sample = complete_sample()
    sample["first_cluster_ok_at_ms"] = sample["first_pfail_seen_at_ms"] + (
        sample["clean_snapshot_passed_at_ms"] - sample["fault_apply_at_ms"]
    )

    with pytest.raises(FailoverTimelineError, match="substituted|timestamps must be monotonic"):
        derive_rto_metrics(sample)


def test_percentile_nearest_rank_round_index() -> None:
    assert percentile([3], 0.95) == 3
    assert percentile([10, 20, 30], 0.50) == 20
    assert percentile([10, 20, 30], 0.95) == 30
    assert percentile([10, 20, 30, 40], 0.50) == 30


def test_m2_nearest_rank_uses_ceil_rank_without_changing_legacy_percentile() -> None:
    assert nearest_rank(list(range(1, 8)), 0.95) == 7
    assert nearest_rank(list(range(1, 11)), 0.50) == 5
    assert nearest_rank(list(range(1, 11)), 0.95) == 10
    assert percentile([10, 20, 30, 40], 0.50) == 30


def test_owned_multi_pid_sigkill_requires_ownership_and_observes_each_process_gone() -> None:
    targets = [
        OwnedProcessTarget("node-1", "nodehost-a", 101, "run-1"),
        OwnedProcessTarget("node-2", "nodehost-b", 101, "run-1"),
    ]
    alive = {target.logical_id: True for target in targets}
    sent: list[tuple[str, int]] = []
    lifecycle: list[str] = []

    def signal_sender(target: OwnedProcessTarget, signal_number: int) -> None:
        lifecycle.append("signal")
        sent.append((target.logical_id, signal_number))
        alive[target.logical_id] = False

    result = apply_owned_sigkill(
        targets,
        expected_ownership_id="run-1",
        signal_sender=signal_sender,
        process_alive=lambda target: alive[target.logical_id],
        wait_timeout_seconds=1.0,
        monotonic_clock=lambda: 10.0,
        wall_clock=lambda: 20.0,
        sleep=lambda _seconds: None,
        barrier_callback=lambda: lifecycle.append("barrier"),
    )

    assert result["status"] == "PASS"
    assert sorted(sent) == [("node-1", signal.SIGKILL), ("node-2", signal.SIGKILL)]
    assert lifecycle[0] == "barrier"
    assert all(row["status"] == "PASS" for row in result["targets"])
    assert all(isinstance(row["process_gone_at_monotonic_ms"], float) for row in result["targets"])

    with pytest.raises(FailoverTimelineError, match="not owned"):
        apply_owned_sigkill(
            [OwnedProcessTarget("node-3", "nodehost-c", 103, "other-run")],
            expected_ownership_id="run-1",
            signal_sender=signal_sender,
            process_alive=lambda _target: True,
            wait_timeout_seconds=1.0,
        )


def test_persistent_cluster_client_reuses_owned_redirect_connection(monkeypatch) -> None:
    endpoints = [
        ObserverEndpoint("node-1", "127.0.0.1", 7000, container_ip="10.0.0.1"),
        ObserverEndpoint("node-2", "127.0.0.1", 7001, container_ip="10.0.0.2"),
    ]
    created: list[str] = []

    class FakePersistentConnection:
        def __init__(self, endpoint, _timeout_seconds):
            self.endpoint = endpoint
            self.calls = 0
            created.append(endpoint.logical_id)

        def execute(self, *args):
            self.calls += 1
            if self.endpoint.logical_id == "node-1":
                raise RespError("MOVED 1 10.0.0.2:7001")
            return "OK" if args[0] == "SET" else "value"

        def close(self):
            return None

    monkeypatch.setattr(failover_timeline, "_PersistentRespConnection", FakePersistentConnection)

    with PersistentClusterClient(endpoints) as client:
        write = client.execute("SET", "key", "value")
        read = client.execute("GET", "key")

    assert write.value == "OK"
    assert write.moved_count == 1
    assert write.endpoint_logical_id == "node-2"
    assert read.value == "value"
    assert created == ["node-1", "node-2"]


def test_stable_shard_accumulator_requires_full_cadenced_window_for_every_shard() -> None:
    accumulator = StableShardAccumulator()
    for index in range(11):
        for shard_id, offset in [("shard-a", 0.0), ("shard-b", 50.0)]:
            accumulator.record(
                shard_id=shard_id,
                monotonic_ms_value=index * 100.0 + offset,
                set_succeeded=True,
                get_succeeded=True,
                value_matches=True,
            )

    summary = accumulator.summary(["shard-a", "shard-b"])

    assert summary["status"] == "PASS"
    assert summary["stable_endpoint_monotonic_ms"] == 1050.0
    assert summary["stable_window_skew_ms"] == 50.0

    incomplete = StableShardAccumulator()
    for index in range(10):
        incomplete.record(
            shard_id="shard-a",
            monotonic_ms_value=index * 100.0,
            set_succeeded=True,
            get_succeeded=True,
            value_matches=True,
        )
    assert incomplete.summary(["shard-a"])["status"] == "FAIL"


def test_client_recovery_accumulator_counts_before_first_success_only() -> None:
    acc = ClientRecoveryAccumulator("sample", fault_apply_at_ms=1000, probe_interval_ms=250)
    acc.record({"timestamp_unix_ms": 900, "status": "FAIL", "timeout": True, "moved_count": 1, "ask_count": 0})
    acc.record({"timestamp_unix_ms": 1100, "status": "FAIL", "timeout": True, "moved_count": 2, "ask_count": 1})
    acc.record({"timestamp_unix_ms": 1300, "status": "PASS", "timeout": False, "moved_count": 1, "ask_count": 1})
    acc.record({"timestamp_unix_ms": 1500, "status": "FAIL", "timeout": True, "moved_count": 9, "ask_count": 9})

    summary = acc.summary()

    assert summary["first_success_after_fault_ms"] == 1300
    assert summary["error_count_before_recovery"] == 1
    assert summary["timeout_count_before_recovery"] == 1
    assert summary["moved_count"] == 2
    assert summary["ask_count"] == 1


def test_client_recovery_can_select_success_after_cluster_ok_marker() -> None:
    acc = ClientRecoveryAccumulator("sample", fault_apply_at_ms=1000, probe_interval_ms=250)
    acc.record({"timestamp_unix_ms": 1100, "status": "FAIL"})
    acc.record({"timestamp_unix_ms": 1600, "status": "PASS"})
    acc.record({"timestamp_unix_ms": 1800, "status": "PASS"})

    assert acc.summary()["first_success_after_fault_ms"] == 1600
    assert acc.first_success_at_or_after(1700) == 1800


def test_build_rto_summary_uses_only_real_pass_samples() -> None:
    samples = [complete_sample(sample_id="s30", node_count=30), complete_sample(sample_id="s50", node_count=50)]
    samples.append(complete_sample(sample_id="fake", node_count=100, real_valkey=False, execution_mode="fake_schema"))

    summary = build_rto_summary(
        samples,
        capability_id="failover_timeline",
        run_id="summary",
        timeout_config_ms=30000,
        server_profile="global_default",
        nodehost_strategy="configured_plan",
        scale="30,50",
    )

    assert summary["sample_count"] == 2
    assert summary["observed_real_scales"] == [30, 50]
    assert summary["derived_series"]["kill_to_pfail_ms"]["p50_ms"] == 200


def test_observer_endpoint_selection_always_includes_target_at_large_scale() -> None:
    endpoints = [
        ObserverEndpoint(logical_id=f"node-{idx:04d}", host="127.0.0.1", port=7000 + idx)
        for idx in range(200)
    ]

    observer = FailoverTimelineObserver(
        capability_id="failover_timeline",
        run_id="run",
        scenario_name="scenario",
        sample_id="sample",
        node_count=200,
        endpoints=endpoints,
        target_primary_logical_id="node-0199",
        target_primary_node_id="node-id-199",
        expected_replica_node_id="node-id-198",
        max_observer_endpoints=32,
    )

    assert any(endpoint.logical_id == "node-0199" for endpoint in observer._sample_endpoints)
    assert len(observer._sample_endpoints) == 32
