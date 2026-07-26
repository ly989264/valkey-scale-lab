from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
import tarfile
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from valkey_scale_lab.observer.failover_timeline import StableShardAccumulator
from valkey_scale_lab.runtime.setup_timeline import REQUIRED_SETUP_SEGMENTS


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "m2_performance_capture.py"
sys.path.insert(0, str(SCRIPT.parent))
import valkey_probe_lib  # noqa: E402

SPEC = importlib.util.spec_from_file_location("m2_performance_capture_fault_test", SCRIPT)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)


def _historical_source_bytes(
    run_id: str,
    group: str,
    source_name: str,
) -> bytes:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "m2_regressions"
    manifest = json.loads(
        (fixture_dir / "historical_gate_replays.json").read_text(encoding="utf-8")
    )
    case = next(row for row in manifest["runs"] if row["source_run_id"] == run_id)
    fixture = case["fixture"]
    archive_path = fixture_dir / fixture["file"]
    compressed = archive_path.read_bytes()
    assert len(compressed) == fixture["gzip_bytes"]
    assert hashlib.sha256(compressed).hexdigest() == fixture["sha256"]
    source = case[group][source_name]
    with tarfile.open(archive_path, mode="r:gz") as archive:
        member = archive.extractfile(source["path"])
        assert member is not None
        raw = member.read()
    assert hashlib.sha256(raw).hexdigest() == source["sha256"]
    return raw


def _state(*, cross_domain: bool = True) -> dict:
    nodes = []
    for ordinal in range(25):
        shard = f"shard-{ordinal:04d}"
        nodes.extend(
            [
                {
                    "logical_id": f"{shard}-primary",
                    "shard_id": shard,
                    "role": "primary",
                    "nodehost_id": f"primary-host-{ordinal % 2}",
                    "az_id": "az-a",
                    "pid": 1000 + ordinal,
                },
                {
                    "logical_id": f"{shard}-replica",
                    "shard_id": shard,
                    "role": "replica",
                    "nodehost_id": f"replica-host-{ordinal % 2}",
                    "az_id": "az-b" if cross_domain else "az-a",
                    "pid": 2000 + ordinal,
                },
            ]
        )
    return {"nodes": nodes}


def _view(target_flags: list[str], replacement_role: str) -> dict:
    nodes = {
        "p0": {
            "node_id": "p0",
            "flags": target_flags or ["master"],
            "role": "primary",
            "master_id": "-",
            "link_state": "disconnected" if "fail" in target_flags else "connected",
            "slots": ["0-8191"],
        },
        "r0": {
            "node_id": "r0",
            "flags": ["master"] if replacement_role == "primary" else ["replica"],
            "role": replacement_role,
            "master_id": "-" if replacement_role == "primary" else "p0",
            "link_state": "connected",
            "slots": ["0-8191"] if replacement_role == "primary" else [],
        },
        "p1": {
            "node_id": "p1",
            "flags": ["master"],
            "role": "primary",
            "master_id": "-",
            "link_state": "connected",
            "slots": ["8192-16383"],
        },
        "r1": {
            "node_id": "r1",
            "flags": ["replica"],
            "role": "replica",
            "master_id": "p1",
            "link_state": "connected",
            "slots": [],
        },
    }
    return {
        "logical_id": "observer",
        "status": "PASS",
        "cluster_state": "ok",
        "cluster_slots_assigned": 16384,
        "cluster_slots_ok": 16384,
        "cluster_known_nodes": 4,
        "cluster_nodes": nodes,
    }


def test_actual_resource_sources_round_trip_production_compaction(
    tmp_path: Path,
) -> None:
    for arm in ("baseline", "candidate"):
        raw = _historical_source_bytes(
            "29916936241",
            "capacity_sources",
            f"{arm}_resource",
        )
        source_path = tmp_path / f"{arm}-resource-window.json"
        source_path.write_bytes(raw)
        report = capture._load_resource_window(source_path)
        compact_bytes = source_path.read_bytes()
        assert json.loads(compact_bytes) == report

        second_path = tmp_path / f"{arm}-round-trip.json"
        capture._write_json(second_path, report)
        assert second_path.read_bytes() == compact_bytes
        assert len(compact_bytes) <= len(raw)


def test_run_29997723777_capacity_sources_use_production_serializers(
    tmp_path: Path,
) -> None:
    sources: dict[str, tuple[bytes, dict]] = {}
    for name in (
        "formation_resource",
        "failover_resource",
        "failover_topology",
        "failover_fault",
        "failover_workload",
    ):
        raw = _historical_source_bytes(
            "29997723777",
            "capacity_sources",
            name,
        )
        sources[name] = (raw, json.loads(raw))

    def directional_counts(document: dict) -> tuple[int, int, int]:
        refs = 0
        transitions = 0
        previous_by_logical: dict[str, str] = {}
        for sample in document["samples"]:
            for nodehost in sample["nodehosts"]:
                for process in nodehost["processes"]:
                    digest = process["directional_cluster_links_sha256"]
                    refs += 1
                    logical_id = process["logical_id"]
                    previous = previous_by_logical.get(logical_id)
                    if previous is not None and previous != digest:
                        transitions += 1
                    previous_by_logical[logical_id] = digest
        return (
            refs,
            len(document["directional_cluster_links_dictionary"]),
            transitions,
        )

    raw, _document = sources["formation_resource"]
    resource_path = tmp_path / "formation_resource.json"
    resource_path.write_bytes(raw)
    report = capture._load_resource_window(resource_path)
    compact_formation = resource_path.read_bytes()
    assert json.loads(compact_formation) == report
    assert directional_counts(report) == (1250, 190, 189)
    assert len(compact_formation) * 10 < len(raw)
    assert (
        len(gzip.compress(compact_formation, compresslevel=6, mtime=0)) * 8
        < len(gzip.compress(raw, compresslevel=6, mtime=0))
    )

    failover_raw, failover_resource = sources["failover_resource"]
    compact_failover_report = capture._intern_resource_directional_links(
        failover_resource
    )
    failover_resource_path = tmp_path / "failover_resource.json"
    capture._write_json(failover_resource_path, compact_failover_report)
    compact_failover = failover_resource_path.read_bytes()
    assert directional_counts(compact_failover_report) == (1263, 99, 49)
    assert len(compact_failover) * 15 < len(failover_raw)
    assert (
        len(gzip.compress(compact_failover, compresslevel=6, mtime=0)) * 8
        < len(gzip.compress(failover_raw, compresslevel=6, mtime=0))
    )

    for name in (
        "failover_topology",
        "failover_workload",
    ):
        _raw, document = sources[name]
        path = tmp_path / f"{name}.json"
        capture._write_json(path, document)
        assert json.loads(path.read_bytes()) == document

    fault_raw, fault = sources["failover_fault"]
    target_ids = set(fault["target_node_ids"])
    replacement_ids = set(fault["replacement_node_ids"])
    topology_view_entries: dict[str, dict] = {}
    compact_rounds = []
    for row in fault["observer_rounds"]:
        compact_rounds.append(
            {
                **{key: value for key, value in row.items() if key != "views"},
                "views_sha256": capture._intern_fault_topology_view(
                    topology_view_entries,
                    capture._compact_fault_views(
                        row["views"],
                        target_ids,
                        replacement_ids,
                    ),
                ),
            }
        )
    convergence_ref = capture._intern_fault_topology_view(
        topology_view_entries,
        capture._compact_fault_views(
            fault["every_node_convergence_views"],
            target_ids,
            replacement_ids,
        ),
    )
    compact_fault = {
        **{
            key: value
            for key, value in fault.items()
            if key not in {"observer_rounds", "every_node_convergence_views"}
        },
        "observer_rounds": compact_rounds,
        "topology_view_dictionary": [
            topology_view_entries[digest]
            for digest in sorted(topology_view_entries)
        ],
        "every_node_convergence_views_sha256": convergence_ref,
    }
    fault_path = tmp_path / "failover_fault.json"
    capture._write_json(fault_path, compact_fault)
    assert len(compact_rounds) == len(fault["observer_rounds"]) == 535
    assert len(topology_view_entries) == 6
    assert fault_path.stat().st_size * 20 < len(fault_raw)

    summary_path = tmp_path / "failover_fault_summary.json"
    summary = capture._compact_fault_summary(compact_fault)
    capture._write_json(summary_path, summary)
    assert json.loads(summary_path.read_bytes()) == summary


def test_steady_data_path_streams_bounded_histogram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import valkey_scale_lab.observer.failover_timeline as failover_timeline

    class Clock:
        value = 100.0

        def __call__(self) -> float:
            self.value += 0.000001
            return self.value

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        @staticmethod
        def execute(command: str, _key: str, value: str | None = None) -> SimpleNamespace:
            return SimpleNamespace(value="OK" if command == "SET" else value or "x" * 512)

    monkeypatch.setattr(
        failover_timeline.ObserverEndpoint,
        "from_node",
        staticmethod(lambda _node: object()),
    )
    monkeypatch.setattr(failover_timeline, "PersistentClusterClient", Client)
    monkeypatch.setattr(capture.time, "monotonic", Clock())
    report = capture._capture_data_path(
        tmp_path,
        {
            "runtime": {"run_id": "steady-capacity"},
            "nodes": [{"logical_id": "node-1"}],
        },
        duration_seconds=0.18,
    )

    assert report["operation_count"] > 50_000
    assert "latency_precision_ms" not in report
    bucket_index = capture._latency_histogram_bucket_index(0.001)
    assert report["latency_histogram"] == {
        "schema_version": capture.LATENCY_HISTOGRAM_SCHEMA_VERSION,
        "buckets": [
            {
                "index": bucket_index,
                "count": report["operation_count"],
            }
        ],
    }
    assert (
        sum(row["count"] for row in report["latency_histogram"]["buckets"])
        == report["operation_count"]
    )
    assert report["p99_latency_ms"] == capture._latency_histogram_bucket_upper_ms(
        bucket_index
    )
    assert "latencies" not in report


def test_latency_histogram_bucket_boundaries_and_overflow_are_conservative() -> None:
    maximum = capture.LATENCY_HISTOGRAM_MAX_MS

    assert capture._latency_histogram_bucket_index(0.0) == 0
    assert capture._latency_histogram_bucket_index(
        capture.LATENCY_HISTOGRAM_MIN_POSITIVE_MS / 2
    ) == 0
    assert capture._latency_histogram_bucket_upper_ms(0) > 0
    one_ms_index = capture._latency_histogram_bucket_index(1.0)
    assert capture._latency_histogram_bucket_upper_ms(one_ms_index) == 1.0
    lower = capture._latency_histogram_bucket_upper_ms(one_ms_index - 1)
    upper = capture._latency_histogram_bucket_upper_ms(one_ms_index)
    assert (upper - lower) / lower <= 0.01
    assert (
        capture._latency_histogram_bucket_index(maximum)
        == capture.LATENCY_HISTOGRAM_MAX_INDEX
    )
    assert (
        capture._latency_histogram_bucket_index(maximum + 0.000001)
        == capture.LATENCY_HISTOGRAM_OVERFLOW_INDEX
    )
    overflow = capture._latency_histogram_rows(
        Counter({capture.LATENCY_HISTOGRAM_OVERFLOW_INDEX: 7})
    )
    assert overflow == {
        "schema_version": capture.LATENCY_HISTOGRAM_SCHEMA_VERSION,
        "buckets": [
            {"index": capture.LATENCY_HISTOGRAM_OVERFLOW_INDEX, "count": 7}
        ],
    }


def test_steady_data_path_counts_overflow_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import valkey_scale_lab.observer.failover_timeline as failover_timeline

    clock_values = iter((100.0, 100.0, 110.001, 110.001, 110.001))

    class Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        @staticmethod
        def execute(
            command: str,
            _key: str,
            value: str | None = None,
        ) -> SimpleNamespace:
            return SimpleNamespace(value="OK" if command == "SET" else value or "x" * 512)

    monkeypatch.setattr(
        failover_timeline.ObserverEndpoint,
        "from_node",
        staticmethod(lambda _node: object()),
    )
    monkeypatch.setattr(failover_timeline, "PersistentClusterClient", Client)
    monkeypatch.setattr(capture.time, "monotonic", lambda: next(clock_values))

    with pytest.raises(capture.CaptureError, match="data-path observation failed"):
        capture._capture_data_path(
            tmp_path,
            {
                "runtime": {"run_id": "steady-overflow"},
                "nodes": [{"logical_id": "node-1"}],
            },
            duration_seconds=1.0,
        )

    report = json.loads(
        (tmp_path / "workload_observation.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "FAIL"
    assert report["operation_count"] == 1
    assert (
        sum(row["count"] for row in report["latency_histogram"]["buckets"]) == 1
    )
    assert report["latency_histogram"] == {
        "schema_version": capture.LATENCY_HISTOGRAM_SCHEMA_VERSION,
        "buckets": [
            {"index": capture.LATENCY_HISTOGRAM_OVERFLOW_INDEX, "count": 1}
        ],
    }
    assert "histogram overflowed" in report["errors"][0]


def test_latency_histogram_is_bounded_for_repeated_and_unique_latencies() -> None:
    repeated_count = capture.LATENCY_HISTOGRAM_MAX_BUCKETS * 2
    repeated = Counter(
        {
            capture._latency_histogram_bucket_index(1.234567): repeated_count,
        }
    )
    repeated_rows = capture._latency_histogram_rows(repeated)
    assert repeated_rows["buckets"] == [
        {
            "index": capture._latency_histogram_bucket_index(1.234567),
            "count": repeated_count,
        }
    ]

    unique_count = capture.LATENCY_HISTOGRAM_MAX_BUCKETS * 2
    unique_bins: Counter[int] = Counter()
    for ordinal in range(unique_count):
        fraction = ordinal / max(unique_count - 1, 1)
        unique_bins[
            capture._latency_histogram_bucket_index(
                capture.LATENCY_HISTOGRAM_MIN_POSITIVE_MS
                * (
                    capture.LATENCY_HISTOGRAM_MAX_MS
                    / capture.LATENCY_HISTOGRAM_MIN_POSITIVE_MS
                )
                ** fraction
            )
        ] += 1
    unique_rows = capture._latency_histogram_rows(unique_bins)

    assert len(unique_rows["buckets"]) <= capture.LATENCY_HISTOGRAM_MAX_BUCKETS
    assert sum(row["count"] for row in unique_rows["buckets"]) == unique_count


def test_latency_histogram_nearest_rank_and_serialized_size_are_bounded() -> None:
    all_bins = Counter(
        {
            bucket_index: 1
            for bucket_index in range(capture.LATENCY_HISTOGRAM_MAX_INDEX + 1)
        }
    )
    rows = capture._latency_histogram_rows(all_bins)

    assert capture.LATENCY_HISTOGRAM_MAX_BUCKETS <= 4_096
    assert len(rows["buckets"]) == capture.LATENCY_HISTOGRAM_MAX_INDEX + 1
    assert capture._histogram_nearest_rank(rows, 0.50) is not None
    assert capture._histogram_nearest_rank(rows, 0.99) is not None
    assert len(json.dumps(rows, separators=(",", ":")).encode("ascii")) < 100_000


def test_capture_owned_valkey_logs_before_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = "m2-discovery-test"
    nodes = [
        {
            "logical_id": "shard-0000-primary",
            "container_name": "owned-nodehost-0",
            "log_file": f"/tmp/valkey-scale-lab/{run_id}/shard-0000-primary/valkey.log",
        },
        {
            "logical_id": "shard-0001-primary",
            "container_name": "owned-nodehost-1",
            "log_file": f"/tmp/valkey-scale-lab/{run_id}/shard-0001-primary/valkey.log",
        },
    ]

    def fake_run(command: list[str], *, env: object, timeout: int) -> dict:
        assert command[:2] == ["docker", "exec"]
        assert timeout == 5
        if command[2] == "owned-nodehost-0":
            return {"returncode": 0, "stdout": "cluster link connected\n", "stderr": ""}
        return {"returncode": 1, "stdout": "", "stderr": "missing"}

    monkeypatch.setattr(capture, "_run_command", fake_run)
    manifest_path = capture._capture_owned_valkey_logs(
        tmp_path,
        {"runtime": {"run_id": run_id}, "nodes": nodes},
        expected_run_id=run_id,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "PARTIAL"
    assert manifest["expected_log_count"] == 2
    assert manifest["captured_log_count"] == 1
    assert manifest["logs"][0]["status"] == "PASS"
    assert manifest["logs"][1] == {
        "logical_id": "shard-0001-primary",
        "reason": "owned Valkey log was unavailable before cleanup",
        "status": "MISSING",
    }
    assert (tmp_path / "server_logs" / "shard-0000-primary.log").read_text(encoding="utf-8") == (
        "cluster link connected\n"
    )


def test_capture_arm_preserves_failure_diagnostics_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial_id = "m2-discovery-test"
    trials_dir = tmp_path / capture.TRIALS_DIR
    trials_dir.mkdir()
    state_path = trials_dir / trial_id / "state.json"
    context = capture.CaptureContext(
        args=SimpleNamespace(),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "report.json",
    )
    spec = capture.ArmSpec(
        trial_id=trial_id,
        pair_id="pair-01",
        cell_id="formation-discovery-1",
        arm="baseline",
        order=1,
        scale=50,
        scenario="formation_50",
        treatment={"kind": "cluster_create_strategy", "value": "baseline"},
        resource_seconds=1.0,
        workload_seconds=1.0,
    )
    calls: list[str] = []

    def fake_run(command: list[str], *, env: object, timeout: int) -> dict:
        calls.append(command[0])
        if command[0] == "setup":
            capture._write_json(state_path, {"runtime": {"run_id": trial_id}, "nodes": []})
            return {"returncode": 0, "stdout": "", "stderr": ""}
        return {"returncode": 0, "stdout": "", "stderr": ""}

    def fail_data_path(*args: object, **kwargs: object) -> dict:
        primary = capture.CaptureError("capture failure")
        shutdown_note = (
            "persistent fault client shutdown also failed: CaptureError: shutdown failure"
        )
        if hasattr(primary, "add_note"):
            primary.add_note(shutdown_note)
        else:
            setattr(primary, "sampler_shutdown_error", shutdown_note)
        raise primary

    def fail_log_capture(*args: object, **kwargs: object) -> None:
        calls.append("logs")
        raise RuntimeError("log collection failure")

    monkeypatch.setattr(capture, "_ensure_preflight", lambda *args: (tmp_path / "preflight.json", {}))
    monkeypatch.setattr(capture, "_treatment_environment", lambda spec: {})
    monkeypatch.setattr(capture, "_setup_command", lambda *args: ["setup"])
    monkeypatch.setattr(capture, "_cleanup_command", lambda *args: ["cleanup"])
    monkeypatch.setattr(capture, "_run_command", fake_run)
    monkeypatch.setattr(capture, "_validate_state", lambda *args: None)
    monkeypatch.setattr(capture, "_capture_topology", lambda *args, **kwargs: {})
    monkeypatch.setattr(capture, "_attach_setup_wrapper_timing", lambda *args, **kwargs: None)
    monkeypatch.setattr(capture, "_uses_setup_resource_window", lambda spec: False)
    monkeypatch.setattr(capture, "_needs_stability_observation", lambda spec: False)
    monkeypatch.setattr(capture, "_capture_data_path", fail_data_path)
    monkeypatch.setattr(capture, "_capture_resource_window", lambda *args, **kwargs: {})
    monkeypatch.setattr(capture, "_capture_owned_valkey_logs", fail_log_capture)
    monkeypatch.setattr(capture, "_cleanup_state_for_attempt", lambda *args, **kwargs: state_path)
    monkeypatch.setattr(capture, "_cleanup_error", lambda *args, **kwargs: "")
    monkeypatch.setattr(capture, "_collect_partial_refs", lambda *args, **kwargs: None)

    with pytest.raises(capture.CaptureError) as caught:
        capture._capture_arm(context, spec)

    message = str(caught.value)
    assert "capture failure" in message
    assert "persistent fault client shutdown also failed: CaptureError: shutdown failure" in message
    assert "owned Valkey log diagnostics also failed: RuntimeError: log collection failure" in message
    assert calls == ["setup", "logs", "cleanup"]


def test_capture_arm_does_not_collect_diagnostic_logs_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial_id = "m2-discovery-success"
    trials_dir = tmp_path / capture.TRIALS_DIR
    trials_dir.mkdir()
    state_path = trials_dir / trial_id / "state.json"
    context = capture.CaptureContext(
        args=SimpleNamespace(),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "report.json",
    )
    spec = capture.ArmSpec(
        trial_id=trial_id,
        pair_id="pair-01",
        cell_id="formation-discovery-1",
        arm="baseline",
        order=1,
        scale=50,
        scenario="formation_50",
        treatment={"kind": "cluster_create_strategy", "value": "baseline"},
        resource_seconds=1.0,
        workload_seconds=1.0,
    )
    calls: list[str] = []

    def fake_run(command: list[str], *, env: object, timeout: int) -> dict:
        calls.append(command[0])
        if command[0] == "setup":
            capture._write_json(state_path, {"runtime": {"run_id": trial_id}, "nodes": []})
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(capture, "_ensure_preflight", lambda *args: (tmp_path / "preflight.json", {}))
    monkeypatch.setattr(capture, "_treatment_environment", lambda spec: {})
    monkeypatch.setattr(capture, "_setup_command", lambda *args: ["setup"])
    monkeypatch.setattr(capture, "_cleanup_command", lambda *args: ["cleanup"])
    monkeypatch.setattr(capture, "_run_command", fake_run)
    monkeypatch.setattr(capture, "_validate_state", lambda *args: None)
    monkeypatch.setattr(capture, "_capture_topology", lambda *args, **kwargs: {})
    monkeypatch.setattr(capture, "_attach_setup_wrapper_timing", lambda *args, **kwargs: None)
    monkeypatch.setattr(capture, "_uses_setup_resource_window", lambda spec: False)
    monkeypatch.setattr(capture, "_needs_stability_observation", lambda spec: False)
    monkeypatch.setattr(capture, "_capture_data_path", lambda *args, **kwargs: {})
    monkeypatch.setattr(capture, "_capture_resource_window", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        capture,
        "_capture_owned_valkey_logs",
        lambda *args, **kwargs: calls.append("logs"),
    )
    monkeypatch.setattr(capture, "_cleanup_state_for_attempt", lambda *args, **kwargs: state_path)
    monkeypatch.setattr(capture, "_cleanup_error", lambda *args, **kwargs: "")
    monkeypatch.setattr(capture, "_build_trial", lambda *args, **kwargs: {"status": "PASS"})

    assert capture._capture_arm(context, spec) == {"status": "PASS"}
    assert calls == ["setup", "cleanup"]


def test_capture_arm_binds_compressed_partial_sources_when_trial_build_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trial_id = "m2-discovery-build-failure"
    trials_dir = tmp_path / capture.TRIALS_DIR
    trials_dir.mkdir()
    trial_dir = trials_dir / trial_id
    state_path = trial_dir / "state.json"
    context = capture.CaptureContext(
        args=SimpleNamespace(),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "report.json",
    )
    spec = capture.ArmSpec(
        trial_id=trial_id,
        pair_id="pair-01",
        cell_id="formation-discovery-1",
        arm="baseline",
        order=1,
        scale=50,
        scenario="formation_50",
        treatment={"kind": "cluster_create_strategy", "value": "baseline"},
        resource_seconds=1.0,
        workload_seconds=1.0,
    )

    def fake_run(command: list[str], *, env: object, timeout: int) -> dict:
        if command[0] == "setup":
            capture._write_json(state_path, {"runtime": {"run_id": trial_id}, "nodes": []})
        return {"returncode": 0, "stdout": "", "stderr": ""}

    def fail_build(*args: object, **kwargs: object) -> dict:
        source = trial_dir / "resource_window.json"
        capture._write_json(source, {"status": "PASS"})
        capture._gzip_trial_json_source(source)
        capture._write_json(
            trial_dir / "evidence_provenance.json",
            {"status": "PASS", "current_invocation": True},
        )
        raise OSError("archive write failed")

    monkeypatch.setattr(capture, "_ensure_preflight", lambda *args: (tmp_path / "preflight.json", {}))
    monkeypatch.setattr(capture, "_treatment_environment", lambda spec: {})
    monkeypatch.setattr(capture, "_setup_command", lambda *args: ["setup"])
    monkeypatch.setattr(capture, "_cleanup_command", lambda *args: ["cleanup"])
    monkeypatch.setattr(capture, "_run_command", fake_run)
    monkeypatch.setattr(capture, "_validate_state", lambda *args: None)
    monkeypatch.setattr(capture, "_capture_topology", lambda *args, **kwargs: {})
    monkeypatch.setattr(capture, "_attach_setup_wrapper_timing", lambda *args, **kwargs: None)
    monkeypatch.setattr(capture, "_uses_setup_resource_window", lambda spec: False)
    monkeypatch.setattr(capture, "_needs_stability_observation", lambda spec: False)
    monkeypatch.setattr(capture, "_capture_data_path", lambda *args, **kwargs: {})
    monkeypatch.setattr(capture, "_capture_resource_window", lambda *args, **kwargs: {})
    monkeypatch.setattr(capture, "_cleanup_state_for_attempt", lambda *args, **kwargs: state_path)
    monkeypatch.setattr(capture, "_cleanup_error", lambda *args, **kwargs: "")
    monkeypatch.setattr(capture, "_build_trial", fail_build)

    with pytest.raises(capture.CaptureError, match="archive write failed"):
        capture._capture_arm(context, spec)

    resource_ref = next(row for row in context.source_refs if row["category"] == "resource")
    assert resource_ref["path"].endswith("/resource_window.json.gz")
    assert any(row["category"] == "provenance" for row in context.source_refs)
    assert not (trial_dir / "resource_window.json").exists()


def test_partial_refs_reject_ambiguous_plain_and_compressed_sources(tmp_path: Path) -> None:
    trial_dir = tmp_path / "trials" / "trial-a"
    trial_dir.mkdir(parents=True)
    plain = trial_dir / "workload_observation.json"
    plain.write_text('{"status":"PASS"}\n', encoding="utf-8")
    plain.with_suffix(".json.gz").write_bytes(gzip.compress(plain.read_bytes(), mtime=0))
    context = capture.CaptureContext(
        args=SimpleNamespace(),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "report.json",
    )

    with pytest.raises(capture.CaptureError, match="ambiguous plain and compressed"):
        capture._collect_partial_refs(
            context,
            trial_dir,
            SimpleNamespace(scenario="formation_50"),
        )


def test_partial_ref_failure_is_secondary_to_the_capture_root_cause(tmp_path: Path) -> None:
    trial_dir = tmp_path / "trials" / "trial-a"
    trial_dir.mkdir(parents=True)
    plain = trial_dir / "fault_observation.json"
    plain.write_text('{"status":"FAIL"}\n', encoding="utf-8")
    plain.with_suffix(".json.gz").write_bytes(gzip.compress(plain.read_bytes(), mtime=0))
    context = capture.CaptureContext(
        args=SimpleNamespace(),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "report.json",
    )
    root_cause = OSError("archive write failed")

    capture._collect_partial_refs_after_error(
        context,
        trial_dir,
        SimpleNamespace(scenario="failover_timeline"),
        root_cause,
    )

    text = capture._capture_error_text(root_cause)
    assert text.startswith("archive write failed")
    assert "partial evidence binding also failed" in text
    assert "ambiguous plain and compressed" in text


def test_fault_targets_are_half_up_deterministic_and_cross_domain() -> None:
    selected = capture._select_fault_target_nodes(_state(), 50, "10_percent")

    assert [row["logical_id"] for row in selected] == [
        "shard-0000-primary",
        "shard-0001-primary",
        "shard-0002-primary",
    ]
    with pytest.raises(capture.CaptureError, match="different nodehost and failure domain"):
        capture._select_fault_target_nodes(_state(cross_domain=False), 50, "one")


def test_owned_sigkill_prevalidates_and_batches_each_unique_container() -> None:
    for script in (
        capture.OWNED_PROCESS_IDENTITY_PROBE_SCRIPT,
        capture.OWNED_PROCESS_STATE_PROBE_SCRIPT,
    ):
        parsed = subprocess.run(
            ["sh", "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert parsed.returncode == 0, parsed.stderr
    labels = {
        "org.valkey-scale-lab.project": "valkey-scale-lab",
        "org.valkey-scale-lab.capability_id": "failover_timeline",
        "org.valkey-scale-lab.run_id": "trial-1",
    }
    selected = [
        {
            "logical_id": "node-a",
            "container_name": "host-a",
            "container_id": "container-a",
            "pid": 101,
            "pid_file": "/tmp/node-a/valkey.pid",
            "config_file": "/tmp/node-a/valkey.conf",
            "client_port": 7001,
        },
        {
            "logical_id": "node-b",
            "container_name": "host-a",
            "container_id": "container-a",
            "pid": 102,
            "pid_file": "/tmp/node-b/valkey.pid",
            "config_file": "/tmp/node-b/valkey.conf",
            "client_port": 7002,
        },
        {
            "logical_id": "node-c",
            "container_name": "host-b",
            "container_id": "container-b",
            "pid": 201,
            "pid_file": "/tmp/node-c/valkey.pid",
            "config_file": "/tmp/node-c/valkey.conf",
            "client_port": 7003,
        },
    ]
    calls: list[list[str]] = []

    def command(argv, **_kwargs):
        calls.append(list(argv))
        if argv[0] == "inspect":
            suffix = argv[1][-1]
            return SimpleNamespace(
                stdout=(
                    '[{"Id":"container-'
                    + suffix
                    + '","Name":"/host-'
                    + suffix
                    + '","Config":{"Labels":'
                    + json.dumps(labels)
                    + "}}]"
                )
            )
        if argv[4] == capture.OWNED_PROCESS_IDENTITY_PROBE_SCRIPT:
            return SimpleNamespace(
                stdout="VSLAB_IDENTITY_VERIFIED\n",
                stderr="",
                returncode=0,
            )
        return SimpleNamespace(
            stdout="",
            stderr="",
            returncode=0,
        )

    sender, command_batches = capture._owned_sigkill_sender(
        {
            "capability_id": "failover_timeline",
            "runtime": {"run_id": "trial-1"},
        },
        selected,
        command=command,
    )
    with pytest.raises(capture.CaptureError, match="was not pre-authorized"):
        sender(SimpleNamespace(logical_id="node-a", pid=102), 9)
    for node in selected:
        sender(SimpleNamespace(logical_id=node["logical_id"], pid=node["pid"]), 9)

    assert [call for call in calls if call[0] == "inspect"] == [
        ["inspect", "container-a"],
        ["inspect", "container-b"],
    ]
    assert [call for call in calls if call[0] == "exec"] == [
        [
            "exec",
            "container-a",
            "sh",
            "-c",
            capture.OWNED_PROCESS_IDENTITY_PROBE_SCRIPT,
            "sh",
            "101",
            "/tmp/node-a/valkey.pid",
            "/tmp/node-a/valkey.conf",
            "7001",
            "102",
            "/tmp/node-b/valkey.pid",
            "/tmp/node-b/valkey.conf",
            "7002",
        ],
        ["exec", "container-a", "sh", "-c", "kill -KILL 101 102"],
        [
            "exec",
            "container-b",
            "sh",
            "-c",
            capture.OWNED_PROCESS_IDENTITY_PROBE_SCRIPT,
            "sh",
            "201",
            "/tmp/node-c/valkey.pid",
            "/tmp/node-c/valkey.conf",
            "7003",
        ],
        ["exec", "container-b", "sh", "-c", "kill -KILL 201"],
    ]
    assert [batch["status"] for batch in command_batches] == ["PASS", "PASS"]
    assert [batch["stdout"] for batch in command_batches] == ["", ""]


def test_owned_sigkill_script_fails_closed_before_signaling_without_identity(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            "sh",
            "-c",
            capture.OWNED_PROCESS_IDENTITY_PROBE_SCRIPT,
            "sh",
            "2",
            str(tmp_path / "missing.pid"),
            str(tmp_path / "valkey.conf"),
            "7001",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 65
    assert result.stdout == "VSLAB_IDENTITY_MISMATCH pidfile_unreadable\n"


def test_owned_sigkill_does_not_accept_a_failed_shell_command() -> None:
    labels = {
        "org.valkey-scale-lab.project": "valkey-scale-lab",
        "org.valkey-scale-lab.capability_id": "failover_timeline",
        "org.valkey-scale-lab.run_id": "trial-1",
    }

    def command(argv, **_kwargs):
        if argv[0] == "inspect":
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "Id": "container-a",
                            "Name": "/host-a",
                            "Config": {"Labels": labels},
                        }
                    ]
                ),
                returncode=0,
                stderr="",
            )
        if argv[4] == capture.OWNED_PROCESS_IDENTITY_PROBE_SCRIPT:
            return SimpleNamespace(
                stdout="VSLAB_IDENTITY_VERIFIED\n",
                stderr="",
                returncode=0,
            )
        return SimpleNamespace(stdout="", stderr="shell failure", returncode=127)

    sender, command_batches = capture._owned_sigkill_sender(
        {
            "capability_id": "failover_timeline",
            "runtime": {"run_id": "trial-1"},
        },
        [
            {
                "logical_id": "node-a",
                "container_name": "host-a",
                "container_id": "container-a",
                "pid": 101,
                "pid_file": "/tmp/node-a/valkey.pid",
                "config_file": "/tmp/node-a/valkey.conf",
                "client_port": 7001,
            }
        ],
        command=command,
    )

    with pytest.raises(capture.CaptureError, match="SIGKILL batch failed"):
        sender(SimpleNamespace(logical_id="node-a", pid=101), 9)

    assert command_batches[0]["status"] == "FAIL"
    assert command_batches[0]["returncode"] == 127


def test_owned_sigkill_requires_exact_identity_confirmation() -> None:
    labels = {
        "org.valkey-scale-lab.project": "valkey-scale-lab",
        "org.valkey-scale-lab.capability_id": "failover_timeline",
        "org.valkey-scale-lab.run_id": "trial-1",
    }

    def command(argv, **_kwargs):
        if argv[0] == "inspect":
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "Id": "container-a",
                            "Name": "/host-a",
                            "Config": {"Labels": labels},
                        }
                    ]
                ),
                returncode=0,
                stderr="",
            )
        return SimpleNamespace(
            stdout="VSLAB_IDENTITY_MISMATCH process_id\n",
            stderr="",
            returncode=0,
        )

    sender, command_batches = capture._owned_sigkill_sender(
        {
            "capability_id": "failover_timeline",
            "runtime": {"run_id": "trial-1"},
        },
        [
            {
                "logical_id": "node-a",
                "container_name": "host-a",
                "container_id": "container-a",
                "pid": 101,
                "pid_file": "/tmp/node-a/valkey.pid",
                "config_file": "/tmp/node-a/valkey.conf",
                "client_port": 7001,
            }
        ],
        command=command,
    )

    with pytest.raises(capture.CaptureError, match="SIGKILL batch failed"):
        sender(SimpleNamespace(logical_id="node-a", pid=101), 9)

    assert command_batches[0]["status"] == "FAIL"
    assert command_batches[0]["returncode"] == "MISSING"
    assert command_batches[0]["stdout"] == "MISSING"


def test_run_29992169655_kill127_replay_uses_shell_bound_pid_argv() -> None:
    recorded_fault = json.loads(
        _historical_source_bytes(
            "29992169655",
            "failure_sources",
            "fault",
        )
    )
    recorded = recorded_fault["command_batches"][0]
    target_pid = recorded["pids"][0]
    assert "exit=127" in recorded["error"]
    assert recorded["argv"][2] == "kill"

    labels = {
        "org.valkey-scale-lab.project": "valkey-scale-lab",
        "org.valkey-scale-lab.capability_id": "failover_timeline",
        "org.valkey-scale-lab.run_id": "trial-1",
    }
    calls: list[list[str]] = []

    def command(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        if argv[0] == "inspect":
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "Id": "owned-container-id",
                            "Name": "/owned-container",
                            "Config": {"Labels": labels},
                        }
                    ]
                ),
                returncode=0,
                stderr="",
            )
        if argv[4] == capture.OWNED_PROCESS_IDENTITY_PROBE_SCRIPT:
            return SimpleNamespace(
                stdout="VSLAB_IDENTITY_VERIFIED\n",
                stderr="",
                returncode=0,
            )
        return SimpleNamespace(stdout="", stderr="", returncode=0)

    sender, command_batches = capture._owned_sigkill_sender(
        {
            "capability_id": "failover_timeline",
            "runtime": {"run_id": "trial-1"},
        },
        [
            {
                "logical_id": "node-a",
                "container_name": "owned-container",
                "container_id": "owned-container-id",
                "pid": target_pid,
                "pid_file": "/tmp/node-a/valkey.pid",
                "config_file": "/tmp/node-a/valkey.conf",
                "client_port": 7001,
            }
        ],
        command=command,
    )
    repaired = command_batches[0]["argv"]
    assert repaired[:4] == [
        "exec",
        "owned-container-id",
        "sh",
        "-c",
    ]
    assert repaired[2] != recorded["argv"][2]
    assert repaired[4] == f"kill -KILL {target_pid}"

    sender(SimpleNamespace(logical_id="node-a", pid=target_pid), 9)
    assert calls[-1] == repaired
    assert command_batches[0]["status"] == "PASS"
    assert command_batches[0]["stdout"] == ""


@pytest.mark.parametrize(
    "state",
    [
        {"runtime": {"run_id": "trial-1"}},
        {"capability_id": "failover_timeline", "runtime": {"run_id": ""}},
    ],
)
def test_owned_sigkill_requires_nonempty_runtime_ownership(
    state: dict[str, object],
) -> None:
    with pytest.raises(capture.CaptureError, match="requires runtime ownership"):
        capture._owned_sigkill_sender(
            state,
            [],
            command=lambda *_args, **_kwargs: None,
        )


def test_owned_sigkill_rejects_out_of_range_pid_before_docker() -> None:
    with pytest.raises(capture.CaptureError, match="complete container/process identity"):
        capture._owned_sigkill_sender(
            {
                "capability_id": "failover_timeline",
                "runtime": {"run_id": "trial-1"},
            },
            [
                {
                    "logical_id": "node-a",
                    "container_name": "host-a",
                    "container_id": "container-a",
                    "pid": 2_147_483_648,
                    "pid_file": "/tmp/node-a/valkey.pid",
                    "config_file": "/tmp/node-a/valkey.conf",
                    "client_port": 7001,
                }
            ],
            command=lambda *_args, **_kwargs: pytest.fail("Docker must not run"),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("container_name", "--help"),
        ("container_name", "owned/container"),
        ("container_id", "-owned-container-id"),
        ("container_id", "owned\ncontainer"),
        ("pid_file", "--help"),
        ("config_file", "relative/valkey.conf"),
    ],
)
def test_owned_sigkill_rejects_option_like_container_identity(
    field: str,
    value: str,
) -> None:
    target = {
        "logical_id": "node-a",
        "container_name": "owned-container",
        "container_id": "owned-container-id",
        "pid": 49,
        "pid_file": "/tmp/node-a/valkey.pid",
        "config_file": "/tmp/node-a/valkey.conf",
        "client_port": 7001,
    }
    target[field] = value
    with pytest.raises(capture.CaptureError, match="complete container/process identity"):
        capture._owned_sigkill_sender(
            {
                "capability_id": "failover_timeline",
                "runtime": {"run_id": "trial-1"},
            },
            [target],
            command=lambda *_args, **_kwargs: pytest.fail("Docker must not run"),
        )


def test_owned_sigkill_rejects_one_container_id_with_multiple_names() -> None:
    selected = [
        {
            "logical_id": f"node-{suffix}",
            "container_name": f"host-{suffix}",
            "container_id": "container-a",
            "pid": pid,
            "pid_file": f"/tmp/node-{suffix}/valkey.pid",
            "config_file": f"/tmp/node-{suffix}/valkey.conf",
            "client_port": port,
        }
        for suffix, pid, port in (("a", 101, 7001), ("b", 102, 7002))
    ]

    with pytest.raises(capture.CaptureError, match="container id maps to multiple container names"):
        capture._owned_sigkill_sender(
            {
                "capability_id": "failover_timeline",
                "runtime": {"run_id": "trial-1"},
            },
            selected,
            command=lambda *_args, **_kwargs: pytest.fail("Docker must not run"),
        )


def test_owned_sigkill_rejects_runtime_container_rename() -> None:
    labels = {
        "org.valkey-scale-lab.project": "valkey-scale-lab",
        "org.valkey-scale-lab.capability_id": "failover_timeline",
        "org.valkey-scale-lab.run_id": "trial-1",
    }
    selected = [
        {
            "logical_id": "node-a",
            "container_name": "host-a",
            "container_id": "container-a",
            "pid": 101,
            "pid_file": "/tmp/node-a/valkey.pid",
            "config_file": "/tmp/node-a/valkey.conf",
            "client_port": 7001,
        }
    ]

    with pytest.raises(capture.CaptureError, match="identity/ownership verification"):
        capture._owned_sigkill_sender(
            {
                "capability_id": "failover_timeline",
                "runtime": {"run_id": "trial-1"},
            },
            selected,
            command=lambda *_args, **_kwargs: SimpleNamespace(
                stdout=json.dumps(
                    [
                        {
                            "Id": "container-a",
                            "Name": "/renamed-host-a",
                            "Config": {"Labels": labels},
                        }
                    ]
                )
            ),
        )


def test_owned_sigkill_rejects_duplicate_physical_process_identity() -> None:
    selected = [
        {
            "logical_id": f"node-{suffix}",
            "container_name": "host-a",
            "container_id": "container-a",
            "pid": 101,
            "pid_file": f"/tmp/node-{suffix}/valkey.pid",
            "config_file": f"/tmp/node-{suffix}/valkey.conf",
            "client_port": port,
        }
        for suffix, port in (("a", 7001), ("b", 7002))
    ]

    with pytest.raises(capture.CaptureError, match="process identities are duplicated"):
        capture._owned_sigkill_sender(
            {
                "capability_id": "failover_timeline",
                "runtime": {"run_id": "trial-1"},
            },
            selected,
            command=lambda *_args, **_kwargs: pytest.fail("Docker must not run"),
        )


def test_fault_topology_facts_require_expected_fail_and_promotion_only() -> None:
    facts = capture._fault_topology_facts(
        [_view(["master", "fail"], "primary")],
        initial_roles={"p0": "primary", "r0": "replica", "p1": "primary", "r1": "replica"},
        node_shards={"p0": "s0", "r0": "s0", "p1": "s1", "r1": "s1"},
        target_node_ids={"p0"},
        replacement_node_ids={"r0"},
        expected_nodes=4,
    )

    assert facts["converged"] is True
    assert facts["replacement_promotions_complete"] is True
    assert facts["unexpected_pfail"] == 0
    assert facts["unexpected_fail"] == 0
    assert facts["unexpected_promotions"] == 0
    assert facts["split_brain"] is False
    assert facts["slot_loss"] is False

    bad = _view(["master", "fail"], "primary")
    bad["cluster_nodes"]["r1"]["role"] = "primary"
    bad["cluster_nodes"]["r1"]["flags"] = ["master"]
    bad["cluster_nodes"]["r1"]["master_id"] = None
    bad["cluster_nodes"]["r1"]["slots"] = ["8192-16383"]
    bad_facts = capture._fault_topology_facts(
        [bad],
        initial_roles={"p0": "primary", "r0": "replica", "p1": "primary", "r1": "replica"},
        node_shards={"p0": "s0", "r0": "s0", "p1": "s1", "r1": "s1"},
        target_node_ids={"p0"},
        replacement_node_ids={"r0"},
        expected_nodes=4,
    )
    assert bad_facts["converged"] is False
    assert bad_facts["unexpected_promotions"] == 1
    assert bad_facts["split_brain"] is True


def test_fault_topology_facts_accept_production_primary_master_null() -> None:
    nodes = valkey_probe_lib.parse_cluster_nodes(
        "\n".join(
            [
                "p0 127.0.0.1:7000@17000 fail,master - 0 0 1 disconnected",
                "r0 127.0.0.1:7001@17001 master - 0 0 2 connected 0-8191",
                "p1 127.0.0.1:7002@17002 master - 0 0 3 connected 8192-16383",
                "r1 127.0.0.1:7003@17003 slave p1 0 0 4 connected",
            ]
        )
    )
    assert nodes["p0"]["master_id"] is None
    assert nodes["r0"]["master_id"] is None

    facts = capture._fault_topology_facts(
        [
            {
                "logical_id": "observer",
                "status": "PASS",
                "cluster_state": "ok",
                "cluster_slots_assigned": 16384,
                "cluster_slots_ok": 16384,
                "cluster_known_nodes": 4,
                "cluster_nodes": nodes,
            }
        ],
        initial_roles={
            "p0": "primary",
            "r0": "replica",
            "p1": "primary",
            "r1": "replica",
        },
        node_shards={"p0": "s0", "r0": "s0", "p1": "s1", "r1": "s1"},
        target_node_ids={"p0"},
        replacement_node_ids={"r0"},
        expected_nodes=4,
    )

    assert facts["clean_topology"] is True
    assert facts["converged"] is True


@pytest.mark.parametrize("master_id", ["MISSING", "r0"])
def test_fault_topology_facts_reject_missing_or_cross_shard_replica_master(
    master_id: str,
) -> None:
    view = _view(["master", "fail"], "primary")
    if master_id == "MISSING":
        del view["cluster_nodes"]["r1"]["master_id"]
    else:
        view["cluster_nodes"]["r1"]["master_id"] = master_id

    facts = capture._fault_topology_facts(
        [view],
        initial_roles={"p0": "primary", "r0": "replica", "p1": "primary", "r1": "replica"},
        node_shards={"p0": "s0", "r0": "s0", "p1": "s1", "r1": "s1"},
        target_node_ids={"p0"},
        replacement_node_ids={"r0"},
        expected_nodes=4,
    )

    assert facts["clean_topology"] is False
    assert facts["converged"] is False


def test_fault_client_series_retains_raw_attempts_but_summarizes_closed_fault_window() -> None:
    probe = capture.FaultClientProbe("s0", "key", "value", None, True)
    probe.samples = [
        {
            "started_at_monotonic": 9.99,
            "completed_at_monotonic": 10.01,
            "set_completed_at_monotonic": 10.0,
            "get_completed_at_monotonic": 10.01,
            "set_succeeded": True,
            "get_succeeded": True,
            "value_matches": True,
            "timed_out": False,
            "error": "",
            "latency_ms": 20.0,
            "status": "PASS",
            "moved_count": 0,
            "ask_count": 0,
        },
        {
            "started_at_monotonic": 10.09,
            "completed_at_monotonic": 10.1,
            "set_completed_at_monotonic": 10.095,
            "get_completed_at_monotonic": 10.1,
            "set_succeeded": True,
            "get_succeeded": True,
            "value_matches": True,
            "timed_out": False,
            "error": "",
            "latency_ms": 10.0,
            "status": "PASS",
            "moved_count": 0,
            "ask_count": 0,
        },
        {
            "started_at_monotonic": 10.21,
            "completed_at_monotonic": 10.22,
            "set_completed_at_monotonic": 10.215,
            "get_completed_at_monotonic": 10.22,
            "set_succeeded": True,
            "get_succeeded": True,
            "value_matches": True,
            "timed_out": False,
            "error": "",
            "latency_ms": 10.0,
            "status": "PASS",
            "moved_count": 0,
            "ask_count": 0,
        },
    ]

    series = capture._fault_client_series(
        [probe],
        {"sigkill_barrier": 10.0},
        0.2,
    )[0]

    assert [row["started_at_monotonic"] for row in series["attempts"]] == [
        9.99,
        10.09,
        10.21,
    ]
    assert series["attempt_count"] == 1
    assert series["set_success_count"] == 1
    assert {
        "attempt_started_monotonic",
        "successful_pair_latencies_ms",
        "samples_through_stable_endpoint",
    }.isdisjoint(series)


def test_fault_trial_summary_stays_bounded_at_full_matrix_cardinality() -> None:
    targets = [
        {
            "logical_id": f"node-{index:03d}",
            "shard_id": f"shard-{index:03d}",
            "pid": 1000 + index,
            "ownership_id": "capacity-run",
            "process_gone": True,
            "physical_fault_id": f"capacity-run:{index}",
            "process_gone_at_monotonic_ms": 100000.0 + index,
            "valkey_node_id": f"valkey-{index:03d}",
        }
        for index in range(33)
    ]
    raw_fault = {
        "status": "PASS",
        "errors": [],
        "mode": "owned-process-sigkill",
        "signal": "SIGKILL",
        "commands": [
            f"docker exec container-{index} sh -c 'kill -KILL {1000 + index}'"
            for index in range(4)
        ],
        "barrier_monotonic": 100.0,
        "primary_count": 100,
        "failed_primary_count": 33,
        "injection_skew_ms": 1.0,
        "signal_barrier_span_ms": 1.0,
        "targets": targets,
    }
    summary_without_rounds = capture._compact_fault_summary(raw_fault)
    raw_fault.update(
        {
            "observer_rounds": [
                {
                    "at_monotonic": 100.0 + index / 10.0,
                    "views": [{"cluster_nodes": {"raw": "x" * 4096}}],
                }
                for index in range(1201)
            ],
            "every_node_convergence_views": [
                {"cluster_nodes": {"raw": "x" * 4096}}
                for _index in range(199)
            ],
            "initial_roles": {f"node-{index:03d}": "primary" for index in range(200)},
            "node_shards": {f"node-{index:03d}": f"shard-{index // 2:03d}" for index in range(200)},
        }
    )

    summary_with_rounds = capture._compact_fault_summary(raw_fault)

    assert summary_with_rounds == summary_without_rounds
    assert {
        "observer_rounds",
        "every_node_convergence_views",
        "initial_roles",
        "node_shards",
    }.isdisjoint(summary_with_rounds)
    retained_report = json.dumps(
        {"trials": [{"fault": summary_with_rounds} for _index in range(366)]},
        sort_keys=True,
        allow_nan=False,
    )
    assert len(retained_report.encode("utf-8")) < 32 * 1024 * 1024


def test_fault_views_keep_only_gate_consumed_cluster_node_fields() -> None:
    node_id = "a" * 40
    compact = capture._compact_fault_views(
        [
            {
                "logical_id": "node-1",
                "status": "PASS",
                "cluster_state": "ok",
                "cluster_slots_assigned": 16384,
                "cluster_slots_ok": 16384,
                "cluster_known_nodes": 1,
                "cluster_nodes": {
                    node_id: {
                        "node_id": node_id,
                        "flags": ["myself", "master"],
                        "role": "primary",
                        "slots": ["0-16383"],
                        "link_state": "connected",
                        "addr": "127.0.0.1:7000@17000",
                        "master_id": "-",
                    }
                },
            }
        ],
        {node_id},
        {node_id},
    )[0]

    assert compact["cluster_nodes"][node_id] == {
        "node_id": node_id,
        "addr": "127.0.0.1:7000@17000",
        "flags": ["myself", "master"],
        "role": "primary",
        "master_id": "-",
        "slots": ["0-16383"],
        "link_state": "connected",
    }
    assert compact["target_flags"] == {node_id: ["myself", "master"]}
    assert compact["replacement_roles"] == {node_id: "primary"}


def test_fault_topology_view_interning_preserves_rounds_and_transition() -> None:
    stable_views = [
        {
            "logical_id": f"node-{observer:03d}",
            "status": "PASS",
            "cluster_nodes": {
                f"node-{node:03d}": {
                    "node_id": f"node-{node:03d}",
                    "flags": ["master"],
                    "role": "primary",
                    "master_id": "-",
                    "slots": [f"{node}-{node}"],
                    "link_state": "connected",
                }
                for node in range(50)
            },
        }
        for observer in range(3)
    ]
    transitioned_views = json.loads(json.dumps(stable_views))
    transitioned_views[0]["cluster_nodes"]["node-000"]["flags"].append("fail")
    rounds = [
        {
            "at_monotonic": float(index),
            "facts": {"converged": index >= 64},
            "views": stable_views if index < 64 else transitioned_views,
        }
        for index in range(128)
    ]

    topology_view_entries: dict[str, dict] = {}
    encoded_rounds = [
        {
            **{key: value for key, value in round_row.items() if key != "views"},
            "views_sha256": capture._intern_fault_topology_view(
                topology_view_entries,
                round_row["views"],
            ),
        }
        for round_row in rounds
    ]
    convergence_ref = capture._intern_fault_topology_view(
        topology_view_entries,
        transitioned_views,
    )
    interned = {
        "observer_rounds": encoded_rounds,
        "topology_view_dictionary": [
            topology_view_entries[digest]
            for digest in sorted(topology_view_entries)
        ],
        "every_node_convergence_views_sha256": convergence_ref,
    }
    dictionary = {
        entry["sha256"]: entry["views"]
        for entry in interned["topology_view_dictionary"]
    }
    expanded = [
        dictionary[round_row["views_sha256"]]
        for round_row in interned["observer_rounds"]
    ]
    inline_size = len(
        json.dumps(
            {
                "observer_rounds": rounds,
                "every_node_convergence_views": transitioned_views,
            },
            sort_keys=True,
        )
    )
    interned_size = len(json.dumps(interned, sort_keys=True))

    assert len(interned["observer_rounds"]) == len(rounds)
    assert len(dictionary) == 2
    assert all(
        entry["sha256"] == capture._digest(entry["views"])
        for entry in interned["topology_view_dictionary"]
    )
    assert all("views" not in round_row for round_row in encoded_rounds)
    assert expanded == [round_row["views"] for round_row in rounds]
    assert expanded[63] != expanded[64]
    assert (
        dictionary[interned["every_node_convergence_views_sha256"]]
        == transitioned_views
    )
    assert interned_size < inline_size // 10


def test_capture_json_writer_uses_compact_encoding(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    capture._write_json(path, {"b": [2, 3], "a": 1})

    assert path.read_text(encoding="utf-8") == '{"a":1,"b":[2,3]}\n'


def test_success_source_gzip_is_deterministic_and_lossless(tmp_path: Path) -> None:
    payload = b'{"attempts":[{"started_at_monotonic":1.0}],"status":"PASS"}\n'
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_bytes(payload)
    second.write_bytes(payload)

    first_gzip = capture._gzip_trial_json_source(first)
    second_gzip = capture._gzip_trial_json_source(second)

    assert not first.exists()
    assert not second.exists()
    assert first_gzip.read_bytes() == second_gzip.read_bytes()
    with gzip.open(first_gzip, "rb") as handle:
        assert handle.read() == payload


def _write_supporting_archive_case(root: Path) -> tuple[capture.CaptureContext, Path, list[Path]]:
    trial_dir = root / "trials" / "trial-a"
    sidecar_dir = root / "trials" / "logs" / "commands"
    (trial_dir / "node_configs").mkdir(parents=True)
    sidecar_dir.mkdir(parents=True)
    state = trial_dir / "state.json"
    state.write_text('{"status":"PASS"}\n', encoding="utf-8")
    wrapper = trial_dir / "capture_wrapper_commands.json"
    wrapper.write_bytes(b'{"setup":{"stdout":"exact"}}\n')
    config = trial_dir / "node_configs" / "node.conf"
    config.write_bytes(b"port 7000\n")
    config.chmod(0o640)
    stdout = sidecar_dir / "cmd-000001.stdout.log"
    stderr = sidecar_dir / "cmd-000001.stderr.log"
    stdout.write_bytes(b"command output\n")
    stderr.write_bytes(b"")
    command = trial_dir / "command_log.jsonl"
    command.write_text(
        json.dumps(
            {
                "stdout_path": str(stdout),
                "stdout_sha256": hashlib.sha256(stdout.read_bytes()).hexdigest(),
                "stderr_path": str(stderr),
                "stderr_sha256": hashlib.sha256(stderr.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    context = capture.CaptureContext(
        args=SimpleNamespace(run_id="archive-test"),
        artifacts_dir=root,
        report_path=root / capture.REPORT_NAME,
    )
    return context, trial_dir, [state, command]


def test_success_supporting_archive_is_deterministic_and_preserves_sources(
    tmp_path: Path,
) -> None:
    outputs = []
    for name in ("one", "two"):
        context, trial_dir, sources = _write_supporting_archive_case(tmp_path / name)
        source_bytes = {path.name: path.read_bytes() for path in sources}
        archive_path = capture._archive_success_supporting_artifacts(
            context,
            trial_dir,
            gate_source_paths=sources,
            command_path=sources[1],
        )
        outputs.append(archive_path.read_bytes())

        assert {path.name: path.read_bytes() for path in sources} == source_bytes
        assert not (trial_dir / "capture_wrapper_commands.json").exists()
        assert not (trial_dir / "node_configs" / "node.conf").exists()
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            assert [member.name for member in members] == sorted(
                [
                    "trials/logs/commands/cmd-000001.stderr.log",
                    "trials/logs/commands/cmd-000001.stdout.log",
                    "trials/trial-a/capture_wrapper_commands.json",
                    "trials/trial-a/node_configs/node.conf",
                ]
            )
            extracted = {
                member.name: archive.extractfile(member).read()
                for member in members
            }
            assert extracted["trials/logs/commands/cmd-000001.stdout.log"] == (
                b"command output\n"
            )
            assert extracted["trials/trial-a/node_configs/node.conf"] == b"port 7000\n"
            assert next(
                member
                for member in members
                if member.name == "trials/trial-a/node_configs/node.conf"
            ).mode == 0o640

    assert outputs[0] == outputs[1]


def test_artifact_binding_accepts_product_rooted_command_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product_root = tmp_path / "product"
    artifacts_dir = product_root / "artifacts" / "gate-runs" / "run-a" / "check-a"
    sidecar = artifacts_dir / "trials" / "logs" / "commands" / "cmd-000001.stdout.log"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("output\n", encoding="utf-8")
    monkeypatch.setattr(capture, "ROOT", product_root)

    record = capture._artifact_regular_file(
        artifacts_dir,
        sidecar.relative_to(product_root),
    )

    assert record[0] == sidecar.resolve()
    assert record[1] == "trials/logs/commands/cmd-000001.stdout.log"


@pytest.mark.parametrize("failure", ["digest", "duplicate", "missing", "escape", "symlink"])
def test_supporting_sidecars_fail_closed(
    tmp_path: Path,
    failure: str,
) -> None:
    context, trial_dir, sources = _write_supporting_archive_case(tmp_path)
    command_path = sources[1]
    row = json.loads(command_path.read_text(encoding="utf-8"))
    if failure == "digest":
        row["stdout_sha256"] = "0" * 64
    elif failure == "duplicate":
        row["stderr_path"] = row["stdout_path"]
        row["stderr_sha256"] = row["stdout_sha256"]
    elif failure == "missing":
        row["stdout_path"] = str(tmp_path / "missing.log")
    elif failure == "escape":
        outside = tmp_path.parent / "outside.log"
        outside.write_bytes(b"outside")
        row["stdout_path"] = str(outside)
        row["stdout_sha256"] = hashlib.sha256(b"outside").hexdigest()
    else:
        target = Path(row["stdout_path"])
        replacement = target.with_name("symlink-target.log")
        replacement.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(replacement)
    command_path.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(capture.CaptureError):
        capture._archive_success_supporting_artifacts(
            context,
            trial_dir,
            gate_source_paths=sources,
            command_path=command_path,
        )

    assert not (trial_dir / "supporting_artifacts.tar.gz").exists()
    assert (trial_dir / "capture_wrapper_commands.json").is_file()


def test_fixed_complete_matrix_file_count_stays_below_seal_limit() -> None:
    formation_trials = 4 * 2 + 4 * 3 * 7 * 2
    failover_trials = 3 * 2 + 3 * 2 * 3 * 10 * 2
    stability_trials = 3 * 2
    maximum_source_and_archive_files_per_trial = 11
    bounded_top_level_files = 32

    largest_single_gate_run = max(
        formation_trials,
        failover_trials,
        stability_trials,
    )
    projected_files = (
        largest_single_gate_run * maximum_source_and_archive_files_per_trial
        + bounded_top_level_files
    )

    assert (formation_trials, failover_trials, stability_trials) == (176, 366, 6)
    assert largest_single_gate_run == failover_trials
    assert projected_files == 4058
    assert projected_files < 10_000


def test_valid_setup_resource_window_is_compacted_before_digesting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "resource_window.json"
    report = {"status": "PASS", "samples": [{"sample_index": 0}]}
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    validated = False

    def validate(value: dict, **kwargs: object) -> dict:
        nonlocal validated
        validated = True
        assert kwargs == {
            "allow_initial_membership_transitions": True,
            "allow_safety_failure_evidence": False,
        }
        return value

    monkeypatch.setattr(capture, "_validate_resource_report", validate)
    monkeypatch.setattr(
        capture,
        "_intern_resource_directional_links",
        lambda value: value,
    )

    assert capture._load_resource_window(path) == report
    assert validated is True
    assert path.read_text(encoding="utf-8") == (
        '{"samples":[{"sample_index":0}],"status":"PASS"}\n'
    )


def test_resource_writer_streams_json_without_materializing_encoded_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "resource_window.json"
    report = {
        "status": "PASS",
        "samples": [{"sample_index": 0}],
        "directional_cluster_links_dictionary": [
            {
                "sha256": "a" * 64,
                "directional_cluster_links": [],
            }
        ],
    }

    def fail_dumps(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("resource writer must use JSONEncoder.iterencode")

    monkeypatch.setattr(capture.json, "dumps", fail_dumps)
    capture._write_resource_json(path, report)

    assert json.loads(path.read_text(encoding="utf-8")) == report


def test_first_fault_success_ignores_operation_started_before_sigkill() -> None:
    probe = capture.FaultClientProbe("s0", "key", "value", None, True)
    probe.samples = [
        {
            "started_at_monotonic": 9.99,
            "completed_at_monotonic": 10.01,
            "set_completed_at_monotonic": 10.0,
            "get_completed_at_monotonic": 10.01,
            "set_succeeded": True,
            "get_succeeded": True,
            "value_matches": True,
            "timed_out": False,
            "error": "",
        },
        {
            "started_at_monotonic": 10.09,
            "completed_at_monotonic": 10.1,
            "set_completed_at_monotonic": 10.095,
            "get_completed_at_monotonic": 10.1,
            "set_succeeded": True,
            "get_succeeded": True,
            "value_matches": True,
            "timed_out": False,
            "error": "",
        },
    ]
    accumulator = StableShardAccumulator(
        window_ms=1000.0,
        min_pairs=10,
        max_pair_interval_ms=100.0,
    )
    first_success: dict[str, float] = {}

    capture._consume_fault_samples(
        [probe],
        threading.Lock(),
        {"s0": 0},
        accumulator,
        {"sigkill_barrier": 10.0, "all_slots_covered_cluster_ok": 10.0},
        first_success,
    )

    assert first_success == {
        "first_affected_write": 10.095,
        "first_affected_read": 10.1,
    }


def test_fault_recovery_ignores_operation_started_after_closed_window() -> None:
    probe = capture.FaultClientProbe("s0", "key", "value", None, True)
    probe.samples = [
        {
            "started_at_monotonic": 10.21,
            "completed_at_monotonic": 10.22,
            "set_completed_at_monotonic": 10.215,
            "get_completed_at_monotonic": 10.22,
            "set_succeeded": True,
            "get_succeeded": True,
            "value_matches": True,
            "timed_out": False,
            "error": "",
        }
    ]
    accumulator = StableShardAccumulator(
        window_ms=1000.0,
        min_pairs=10,
        max_pair_interval_ms=100.0,
    )
    first_success: dict[str, float] = {}

    capture._consume_fault_samples(
        [probe],
        threading.Lock(),
        {"s0": 0},
        accumulator,
        {"sigkill_barrier": 10.0, "all_slots_covered_cluster_ok": 10.0},
        first_success,
        window_end=10.2,
    )

    assert first_success == {}
    assert accumulator.samples == {}


def test_fault_markers_and_intervals_are_observed_and_ordered() -> None:
    markers = {"sigkill_barrier": 10.0, "all_processes_gone": 10.1}
    capture._advance_fault_markers(
        markers,
        11.0,
        {"target_pfail_node_ids": ["p0"], "target_fail_node_ids": [], "promoted_replacement_node_ids": [], "cluster_ok_all_slots": False},
    )
    capture._advance_fault_markers(
        markers,
        12.0,
        {"target_pfail_node_ids": [], "target_fail_node_ids": ["p0"], "promoted_replacement_node_ids": [], "cluster_ok_all_slots": False},
    )
    capture._advance_fault_markers(
        markers,
        13.0,
        {"target_pfail_node_ids": [], "target_fail_node_ids": ["p0"], "promoted_replacement_node_ids": ["r0"], "cluster_ok_all_slots": False},
    )
    capture._advance_fault_markers(
        markers,
        14.0,
        {"target_pfail_node_ids": [], "target_fail_node_ids": ["p0"], "promoted_replacement_node_ids": ["r0"], "cluster_ok_all_slots": True},
    )
    markers.update({"stable_client_recovery": 15.0, "every_node_converged": 15.2})

    intervals = capture._fault_intervals(
        markers,
        {"first_affected_write": 14.1, "first_affected_read": 14.2},
    )

    assert list(markers) == list(capture._fault_marker_names())
    assert intervals["kill_to_stable_seconds"] == 5.0
    assert intervals["pfail_to_cluster_ok_seconds"] == 3.0
    assert intervals["process_gone_to_pfail_seconds"] == 0.9
    assert intervals["cluster_ok_to_stable_seconds"] == 1.0


def test_stable_shard_evidence_is_earliest_one_second_consecutive_window() -> None:
    accumulator = StableShardAccumulator(window_ms=1000.0, min_pairs=10, max_pair_interval_ms=100.0)
    for timestamp in range(2000, 3100, 100):
        accumulator.record(
            shard_id="s0",
            monotonic_ms_value=float(timestamp),
            set_succeeded=True,
            get_succeeded=True,
            value_matches=True,
        )
    summary = accumulator.summary(["s0"])

    rows = capture._stable_shard_rows(accumulator, summary)

    assert summary["status"] == "PASS"
    assert rows == [
        {
            "shard_id": "s0",
            "window_start_monotonic": 2.0,
            "window_seconds": 1,
            "consecutive_pairs": 11,
            "errors": 0,
            "timeouts": 0,
            "endpoint_monotonic": 3.0,
            "earliest_qualifying": True,
        }
    ]


def test_fault_cadence_and_missing_facts_fail_closed() -> None:
    probe = capture.FaultClientProbe("s0", "{s0}:value", "value", object(), True)
    control = capture.FaultClientProbe("s1", "{s1}:value", "value", object(), False)
    probe.samples = [
        {"started_at_monotonic": round(10.01 + (index * 0.09), 6)}
        for index in range(12)
    ]
    control.samples = [
        {"started_at_monotonic": round(10.01 + (index * 0.09), 6)}
        for index in range(12)
    ]
    cadence = capture._fault_cadence([probe, control], 10.0, 1.0)
    markers = dict(zip(capture._fault_marker_names(), [10.0, 10.01, 10.1, 10.2, 10.3, 10.4, 11.4, 11.5]))
    convergence = {
        "converged": True,
        "unexpected_pfail": 0,
        "unexpected_fail": 0,
        "unexpected_promotions": 0,
        "split_brain": False,
        "slot_loss": False,
    }
    post_convergence_rounds = [
        {
            "at_monotonic": 11.6,
            "facts": dict(convergence),
        }
    ]

    assert cadence["status"] == "PASS"
    assert capture._missing_fault_facts(
        markers,
        {"first_affected_write": 10.4, "first_affected_read": 10.5},
        {"status": "PASS", "required_shards": ["s0"]},
        [{"shard_id": "s0", "window_seconds": 1, "consecutive_pairs": 10, "errors": 0, "timeouts": 0, "earliest_qualifying": True}],
        cadence,
        post_convergence_rounds,
        convergence,
        {"unexpected_pfail": 0, "unexpected_fail": 0, "unexpected_promotions": 0, "split_brain": False},
    ) == []

    no_post_convergence = capture._missing_fault_facts(
        markers,
        {"first_affected_write": 10.4, "first_affected_read": 10.5},
        {"status": "PASS", "required_shards": ["s0"]},
        [{"shard_id": "s0", "window_seconds": 1, "consecutive_pairs": 10, "errors": 0, "timeouts": 0, "earliest_qualifying": True}],
        cadence,
        [{"at_monotonic": 11.5, "facts": dict(convergence)}],
        convergence,
        {"unexpected_pfail": 0, "unexpected_fail": 0, "unexpected_promotions": 0, "split_brain": False},
    )
    assert "no fixed observation round followed every-node convergence" in no_post_convergence

    regressed = dict(convergence, slot_loss=True, converged=False)
    post_convergence_regression = capture._missing_fault_facts(
        markers,
        {"first_affected_write": 10.4, "first_affected_read": 10.5},
        {"status": "PASS", "required_shards": ["s0"]},
        [{"shard_id": "s0", "window_seconds": 1, "consecutive_pairs": 10, "errors": 0, "timeouts": 0, "earliest_qualifying": True}],
        cadence,
        [{"at_monotonic": 11.6, "facts": regressed}],
        convergence,
        {"unexpected_pfail": 0, "unexpected_fail": 0, "unexpected_promotions": 0, "split_brain": False},
    )
    assert "post-convergence topology observation regressed" in post_convergence_regression

    probe.samples.pop(5)
    broken = capture._fault_cadence([probe, control], 10.0, 1.0)
    errors = capture._missing_fault_facts(
        markers,
        {"first_affected_write": 10.4, "first_affected_read": 10.5},
        {"status": "PASS", "required_shards": ["s0"]},
        [{"shard_id": "s0", "window_seconds": 1, "consecutive_pairs": 10, "errors": 0, "timeouts": 0, "earliest_qualifying": True}],
        broken,
        post_convergence_rounds,
        convergence,
        {"unexpected_pfail": 0, "unexpected_fail": 0, "unexpected_promotions": 0, "split_brain": False},
    )
    assert any("cadence exceeded 100 ms" in error for error in errors)


def test_fault_resource_window_samples_all_owned_processes_before_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_sample = threading.Event()
    observed_expected_gone: list[list[dict[str, object]] | None] = []

    def fake_run_docker(_command: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="sample", stderr="")

    def fake_collect(
        _state: dict,
        *,
        command: object,
        expected_gone_processes: list[dict[str, object]] | None,
        first_complete_sample_event: threading.Event | None,
        **_kwargs: object,
    ) -> dict:
        observed_expected_gone.append(expected_gone_processes)
        command(["exec", "host-a", "sh", "-c", "sample"], timeout=1, check=False)
        assert first_sample.is_set() is False
        command(["exec", "host-b", "sh", "-c", "sample"], timeout=1, check=False)
        assert first_complete_sample_event is first_sample
        first_complete_sample_event.set()
        assert first_sample.is_set() is True
        return {
            "status": "PASS",
            "duration_seconds": 5.0,
            "coverage": {"complete": True},
            "metrics": {
                "peak_rss_bytes": 1,
                "cpu_time_seconds": 1,
                "fd_count": 1,
                "connection_count": 1,
                "cluster_bus_bytes": 1,
                "cluster_link_errors": 0,
                "buffer_overflows": 0,
            },
        }

    import valkey_scale_lab.metrics.m2_resource as resource_module
    import valkey_scale_lab.runtime.docker_runtime as docker_runtime

    monkeypatch.setattr(resource_module, "collect_m2_resource_window", fake_collect)
    monkeypatch.setattr(
        resource_module,
        "validate_and_aggregate_m2_resource_samples",
        lambda report, **_kwargs: {"status": "PASS", "errors": [], "metrics": report["metrics"]},
    )
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)
    monkeypatch.setattr(
        capture,
        "_intern_resource_directional_links",
        lambda value: value,
    )

    report = capture._capture_resource_window(
        tmp_path,
        {"nodehosts": [{"nodehost_id": "a"}, {"nodehost_id": "b"}]},
        5.0,
        expected_gone_processes=[
            {"nodehost_id": "a", "container_id": "container-a", "pid": 101}
        ],
        first_sample_event=first_sample,
    )

    assert report["status"] == "PASS"
    assert observed_expected_gone == [
        [{"nodehost_id": "a", "container_id": "container-a", "pid": 101}]
    ]


def test_resource_report_validation_uses_raw_derived_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import valkey_scale_lab.metrics.m2_resource as resource_module

    report = {
        "status": "PASS",
        "coverage": {"complete": True},
        "metrics": {
            "peak_rss_bytes": 1,
            "cpu_time_seconds": 1,
            "fd_count": 1,
            "connection_count": 1,
            "cluster_bus_bytes": 1,
            "cluster_link_errors": 0,
            "buffer_overflows": 0,
        },
    }
    recomputed_metrics = dict(report["metrics"])
    monkeypatch.setattr(
        resource_module,
        "validate_and_aggregate_m2_resource_samples",
        lambda _report, **_kwargs: {"status": "PASS", "errors": [], "metrics": recomputed_metrics},
    )

    assert capture._validate_resource_report(report) is report

    report["metrics"]["cluster_link_errors"] = 1
    with pytest.raises(capture.CaptureError, match="does not match raw samples"):
        capture._validate_resource_report(report)

    recomputed_metrics["cluster_link_errors"] = 1
    with pytest.raises(capture.CaptureError, match="unavailable or nonzero"):
        capture._validate_resource_report(report)
    assert capture._validate_resource_report(
        report,
        allow_safety_failure_evidence=True,
    ) is report

    report["metrics"]["cluster_link_errors"] = 0
    monkeypatch.setattr(
        resource_module,
        "validate_and_aggregate_m2_resource_samples",
        lambda _report, **_kwargs: {"status": "FAIL", "errors": ["raw links missing"], "metrics": {}},
    )
    with pytest.raises(capture.CaptureError, match="raw samples are incomplete or invalid"):
        capture._validate_resource_report(report)


def test_owned_pid_observation_distinguishes_gone_from_probe_failure() -> None:
    target = SimpleNamespace(logical_id="node-1", pid=123)
    calls: list[list[str]] = []

    def result(returncode: int, stdout: str, stderr: str = "") -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    def alive_command(args: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        return result(0, "VSLAB_PRESENT")

    assert capture._owned_pid_is_alive(
        {"container_id": "owned-container"},
        target,
        command=alive_command,
    ) is True
    assert capture._owned_pid_is_alive(
        {"container_id": "owned-container"},
        target,
        command=lambda *_args, **_kwargs: result(0, "VSLAB_GONE"),
    ) is False
    with pytest.raises(capture.CaptureError, match="PID observation failed"):
        capture._owned_pid_is_alive(
            {"container_id": "owned-container"},
            target,
            command=lambda *_args, **_kwargs: result(125, "", "docker unavailable"),
        )
    assert calls[0][:4] == ["exec", "owned-container", "sh", "-c"]
    assert calls[0][-2:] == ["sh", "123"]
    assert "stat_tail=${stat_line##*) }" in calls[0][4]
    assert "awk" not in calls[0][4]
    assert '[ ! -e "$stat_path" ]' in calls[0][4]
    assert "VSLAB_UNREADABLE" in calls[0][4]


@pytest.mark.parametrize("pid", [True, 0, 1, -1, "123; touch /tmp/unsafe"])
def test_owned_pid_observation_rejects_unsafe_pid_before_docker(pid: object) -> None:
    with pytest.raises(capture.CaptureError, match="identity is unsafe"):
        capture._owned_pid_is_alive(
            {"container_id": "owned-container"},
            SimpleNamespace(logical_id="node-1", pid=pid),
            command=lambda *_args, **_kwargs: pytest.fail("Docker must not run"),
        )


def test_cleanup_uses_label_recovery_state_when_setup_state_is_absent(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"

    cleanup_state = capture._cleanup_state_for_attempt(
        tmp_path,
        state_path,
        capability_id="failover_timeline",
        run_id="trial-1",
    )

    assert cleanup_state.name == "cleanup_recovery_state.json"
    recovered = json.loads(cleanup_state.read_text(encoding="utf-8"))
    assert recovered["capability_id"] == "failover_timeline"
    assert recovered["runtime"] == {
        "type": "m2_label_recovery",
        "run_id": "trial-1",
        "recovery_scope": "exact product-owned Docker labels",
    }


def test_cleanup_reuses_only_complete_matching_process_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "capability_id": "cluster_timeout",
                "runtime": {"type": "docker_process", "run_id": "trial-1"},
                "nodehosts": [{"nodehost_id": "host-1"}],
                "nodes": [{"logical_id": "node-1"}],
            }
        ),
        encoding="utf-8",
    )

    assert capture._cleanup_state_for_attempt(
        tmp_path,
        state_path,
        capability_id="cluster_timeout",
        run_id="trial-1",
    ) == state_path


def test_setup_wrapper_uses_shared_clock_across_real_python_process(
    tmp_path: Path,
) -> None:
    timeline_path = tmp_path / "setup_timeline.json"
    child = (
        "import sys, time\n"
        "from valkey_scale_lab.runtime.setup_timeline import REQUIRED_SETUP_SEGMENTS, SetupTimeline\n"
        "timeline = SetupTimeline()\n"
        "for name in REQUIRED_SETUP_SEGMENTS:\n"
        "    if name == 'scale_ladder_artifact_write':\n"
        "        continue\n"
        "    if name == 'cluster_snapshot_write':\n"
        "        with timeline.span('cluster_final_full_snapshot', 'setup', {}):\n"
        "            time.sleep(0.001)\n"
        "    with timeline.span(name, 'setup', {}):\n"
        "        time.sleep(0.001)\n"
        "timeline.mark_event('data_path_probe', 'm2_measurement', {})\n"
        "timeline.write_artifact(\n"
        "    sys.argv[1], capability_id='cluster_timeout', run_id='trial-1',\n"
        "    scenario='cluster_timeout', profile_id='exact-50', node_count=1, status='PASS',\n"
        ")\n"
    )
    result = capture._run_command(
        [sys.executable, "-c", child, str(timeline_path)],
        env=capture._base_environment(),
        timeout=10,
    )

    assert result["returncode"] == 0, result["stderr"]
    raw = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert result["started_at_monotonic"] <= raw["segments"][0]["start_monotonic"]
    assert raw["segments"][-1]["end_monotonic"] <= result["ended_at_monotonic"]

    missing_end = dict(result)
    missing_end.pop("ended_at_monotonic")
    with pytest.raises(capture.CaptureError, match="monotonic evidence is missing"):
        capture._attach_setup_wrapper_timing(
            timeline_path,
            missing_end,
            state={"nodes": [{"role": "primary"}]},
            topology={"status": "PASS", "versions": ["9.1.0"]},
        )

    capture._attach_setup_wrapper_timing(
        timeline_path,
        result,
        state={"nodes": [{"role": "primary"}]},
        topology={"status": "PASS", "versions": ["9.1.0"]},
    )

    rebuilt = json.loads(timeline_path.read_text(encoding="utf-8"))
    assert rebuilt["segments"][0]["start_monotonic"] == result["started_at_monotonic"]
    assert rebuilt["segments"][-1]["end_monotonic"] == result["ended_at_monotonic"]
    assert rebuilt["status"] == "PASS"
    assert rebuilt["required_stage_coverage"]["status"] == "PASS"
    assert rebuilt["setup_timeline_unexplained_seconds"] == 0.0
    assert rebuilt["setup_timeline_total_seconds"] == rebuilt["setup_command_wall_seconds"]


def test_setup_wrapper_accounts_for_sub_millisecond_cli_gaps(tmp_path: Path) -> None:
    outer_start = 100.0
    cursor = 100.0002
    segments = []
    required_names = [
        name
        for name in REQUIRED_SETUP_SEGMENTS
        if name != "scale_ladder_artifact_write"
    ]
    required_names.insert(
        required_names.index("cluster_snapshot_write"),
        "cluster_final_full_snapshot",
    )
    for index, name in enumerate(required_names):
        if index == 1:
            cursor = round(cursor + 0.0005, 6)
        segment_end = round(cursor + 0.001, 6)
        segments.append(
            {
                "name": name,
                "kind": "span",
                "category": "setup",
                "start_monotonic": cursor,
                "end_monotonic": segment_end,
                "status": "PASS",
                "details": {},
            }
        )
        cursor = segment_end
    outer_end = round(cursor + 0.0003, 6)
    timeline_path = tmp_path / "setup_timeline.json"
    timeline_path.write_text(
        json.dumps(
            {
                "capability_id": "cluster_timeout",
                "run_id": "trial-1",
                "scenario": "cluster_timeout",
                "profile_id": "exact-50",
                "node_count": 1,
                "status": "PASS",
                "segments": segments,
                "events": [],
                "source_artifacts": [],
            }
        ),
        encoding="utf-8",
    )

    capture._attach_setup_wrapper_timing(
        timeline_path,
        {
            "started_at_monotonic": outer_start,
            "ended_at_monotonic": outer_end,
        },
        state={"nodes": [{"role": "primary"}]},
        topology={"status": "PASS", "versions": ["9.1.0"]},
    )

    rebuilt = json.loads(timeline_path.read_text(encoding="utf-8"))
    internal_gaps = [
        segment
        for segment in rebuilt["segments"]
        if segment["name"].startswith("setup_wrapper_between_cli_segments_")
    ]
    assert [segment["duration_seconds"] for segment in internal_gaps] == [0.0005]
    assert rebuilt["setup_timeline_unexplained_seconds"] == 0.0
    assert rebuilt["setup_timeline_total_seconds"] == rebuilt["setup_command_wall_seconds"]
    assert all(
        current["start_monotonic"] == previous["end_monotonic"]
        for previous, current in zip(rebuilt["segments"], rebuilt["segments"][1:])
    )


def test_setup_wrapper_strictly_rejects_overlap_and_out_of_bounds() -> None:
    with pytest.raises(capture.CaptureError, match="overlaps"):
        capture._exhaustive_setup_wrapper_segments(
            [
                {"name": "first", "start_monotonic": 10.0, "end_monotonic": 10.5},
                {"name": "second", "start_monotonic": 10.499999, "end_monotonic": 10.8},
            ],
            outer_start=10.0,
            outer_end=11.0,
        )
    with pytest.raises(capture.CaptureError, match="outside"):
        capture._exhaustive_setup_wrapper_segments(
            [{"name": "first", "start_monotonic": 9.999999, "end_monotonic": 10.5}],
            outer_start=10.0,
            outer_end=11.0,
        )
    with pytest.raises(capture.CaptureError, match="invalid monotonic bounds"):
        capture._exhaustive_setup_wrapper_segments(
            [{"name": "first", "end_monotonic": 10.5}],
            outer_start=10.0,
            outer_end=11.0,
        )


def test_stability_facts_are_derived_from_full_slots_and_roles() -> None:
    probe = _view([], "replica")
    probe["cluster_nodes"]["p0"]["slots"] = ["0-8191"]
    probe["cluster_nodes"]["p1"]["slots"] = ["8192-16383"]
    for row in probe["cluster_nodes"].values():
        row["link_state"] = "connected"
        row.setdefault("slots", [])
    baseline_roles = {
        node_id: row["role"]
        for node_id, row in probe["cluster_nodes"].items()
    }

    good = capture._stability_probe_facts(
        [probe],
        expected_nodes=4,
        baseline_roles=baseline_roles,
    )
    assert good["status"] == "PASS"

    probe["cluster_nodes"]["r1"]["role"] = "primary"
    probe["cluster_nodes"]["r1"]["slots"] = ["8192-16383"]
    bad = capture._stability_probe_facts(
        [probe],
        expected_nodes=4,
        baseline_roles=baseline_roles,
    )
    assert bad["status"] == "FAIL"
    assert bad["unexpected_promotion_node_ids"] == ["r1"]
    assert bad["split_brain"] is True


def _discovery_resources(**overrides: float) -> dict[str, float]:
    resources = {
        "peak_rss_bytes": 100.0,
        "cpu_time_seconds": 100.0,
        "fd_count": 100.0,
        "connection_count": 100.0,
        "cluster_bus_bytes": 100.0,
        "cluster_link_errors": 0.0,
        "buffer_overflows": 0.0,
    }
    resources.update(overrides)
    return resources


def test_formation_discovery_helper_runs_only_fixed_exact_50_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = capture.CaptureContext(
        args=SimpleNamespace(run_id="discovery", mode="formation"),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "m2_candidate_discovery.json",
    )
    calls: list[dict] = []

    def fake_pair(ctx, **kwargs):
        calls.append(kwargs)
        pair_id = f"{kwargs['cell_id']}-pair-01"
        baseline_id = f"{pair_id}-baseline"
        candidate_id = f"{pair_id}-candidate"
        duration = (
            80.0
            if kwargs["candidate"].get("bounded_parallelism") == 8
            else 110.0
        )
        ctx.trials.extend(
            [
                {
                    "trial_id": baseline_id,
                    "derived_intervals": {"formation_seconds": 100.0},
                    "resource_window": _discovery_resources(),
                },
                {
                    "trial_id": candidate_id,
                    "derived_intervals": {"formation_seconds": duration},
                    "resource_window": _discovery_resources(),
                },
            ]
        )
        return {
            "pair_id": pair_id,
            "cell_id": kwargs["cell_id"],
            "baseline_trial_id": baseline_id,
            "candidate_trial_id": candidate_id,
        }

    monkeypatch.setattr(capture, "_capture_pair", fake_pair)

    survivors = capture.capture_formation_discovery(context)

    assert len(calls) == 5
    assert all(
        call["scale"] == 50
        and call["sequence"] == 1
        and call["scenario"] == "cluster_timeout"
        for call in calls
    )
    assert [call["candidate"] for call in calls] == capture._formation_candidates()
    assert [candidate["bounded_parallelism"] for candidate in capture._formation_candidates()[1:]] == [
        2,
        4,
        8,
        16,
    ]
    assert all(cell["required_pairs"] == 1 for cell in context.cells)
    assert [candidate["bounded_parallelism"] for candidate, _ in survivors] == [8]


def test_formation_discovery_rejects_unsafe_candidate_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = capture.CaptureContext(
        args=SimpleNamespace(run_id="discovery", mode="formation"),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "m2_candidate_discovery.json",
    )
    candidates = capture._formation_candidates()[:2]
    calls: list[str] = []

    def fake_pair(ctx, **kwargs):
        calls.append(kwargs["cell_id"])
        pair_id = f"{kwargs['cell_id']}-pair-01"
        baseline_id = f"{pair_id}-baseline"
        candidate_id = f"{pair_id}-candidate"
        unsafe = len(calls) == 1
        ctx.trials.extend(
            [
                {
                    "trial_id": baseline_id,
                    "derived_intervals": {"formation_seconds": 100.0},
                    "resource_window": _discovery_resources(),
                },
                {
                    "trial_id": candidate_id,
                    "derived_intervals": {"formation_seconds": 80.0},
                    "resource_window": _discovery_resources(
                        cluster_link_errors=1.0 if unsafe else 0.0
                    ),
                },
            ]
        )
        return {
            "pair_id": pair_id,
            "cell_id": kwargs["cell_id"],
            "baseline_trial_id": baseline_id,
            "candidate_trial_id": candidate_id,
        }

    monkeypatch.setattr(capture, "_capture_pair", fake_pair)

    survivors = capture.capture_formation_discovery(context, candidates=candidates)

    assert calls == ["formation-discovery-1", "formation-discovery-2"]
    assert [cell["status"] for cell in context.cells] == ["FAIL", "PASS"]
    assert [candidate for candidate, _duration in survivors] == [candidates[1]]


def test_formation_discovery_rejects_resource_regression_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = capture.CaptureContext(
        args=SimpleNamespace(run_id="discovery", mode="formation"),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "m2_candidate_discovery.json",
    )
    candidates = capture._formation_candidates()[:2]
    calls: list[str] = []

    def fake_pair(ctx, **kwargs):
        calls.append(kwargs["cell_id"])
        pair_id = f"{kwargs['cell_id']}-pair-01"
        baseline_id = f"{pair_id}-baseline"
        candidate_id = f"{pair_id}-candidate"
        regressed = len(calls) == 1
        ctx.trials.extend(
            [
                {
                    "trial_id": baseline_id,
                    "derived_intervals": {"formation_seconds": 100.0},
                    "resource_window": _discovery_resources(),
                },
                {
                    "trial_id": candidate_id,
                    "derived_intervals": {"formation_seconds": 80.0},
                    "resource_window": _discovery_resources(
                        peak_rss_bytes=111.0 if regressed else 100.0
                    ),
                },
            ]
        )
        return {
            "pair_id": pair_id,
            "cell_id": kwargs["cell_id"],
            "baseline_trial_id": baseline_id,
            "candidate_trial_id": candidate_id,
        }

    monkeypatch.setattr(capture, "_capture_pair", fake_pair)

    survivors = capture.capture_formation_discovery(context, candidates=candidates)

    assert calls == ["formation-discovery-1", "formation-discovery-2"]
    assert [cell["status"] for cell in context.cells] == ["FAIL", "PASS"]
    assert [candidate for candidate, _duration in survivors] == [candidates[1]]


def test_failover_discovery_helper_runs_only_fixed_single_primary_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = capture.CaptureContext(
        args=SimpleNamespace(run_id="discovery", mode="failover"),
        artifacts_dir=tmp_path,
        report_path=tmp_path / "m2_candidate_discovery.json",
    )
    calls: list[dict] = []
    strategy = "current-formation-strategy"
    monkeypatch.setattr(capture, "_current_strategy_default", lambda: strategy)

    def fake_pair(_ctx, **kwargs):
        calls.append(kwargs)
        return {
            "pair_id": f"{kwargs['cell_id']}-pair-01",
            "cell_id": kwargs["cell_id"],
        }

    monkeypatch.setattr(capture, "_capture_pair", fake_pair)
    monkeypatch.setattr(
        capture,
        "_failover_discovery_passed",
        lambda _ctx, pair: pair["cell_id"].endswith("10000"),
    )

    survivors = capture.capture_failover_discovery(context)

    assert len(calls) == 3
    assert all(
        call["scale"] == 50
        and call["sequence"] == 1
        and call["scenario"] == "failover_timeline"
        and call["fault_rate"] == "one"
        for call in calls
    )
    assert [call["candidate"]["value"] for call in calls] == [5000, 10000, 15000]
    assert all(
        call["candidate"]["cluster_create_strategy"] == strategy for call in calls
    )
    assert all(cell["required_pairs"] == 1 for cell in context.cells)
    assert [candidate["value"] for candidate in survivors] == [10000]
