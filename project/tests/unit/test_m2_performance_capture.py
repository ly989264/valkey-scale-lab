from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from valkey_scale_lab.observer.failover_timeline import StableShardAccumulator
from valkey_scale_lab.runtime.setup_timeline import REQUIRED_SETUP_SEGMENTS


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "m2_performance_capture.py"
SPEC = importlib.util.spec_from_file_location("m2_performance_capture_fault_test", SCRIPT)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = capture
SPEC.loader.exec_module(capture)


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
            "master_id": None,
            "link_state": "disconnected" if "fail" in target_flags else "connected",
            "slots": ["0-8191"],
        },
        "r0": {
            "node_id": "r0",
            "flags": ["master"] if replacement_role == "primary" else ["replica"],
            "role": replacement_role,
            "master_id": None if replacement_role == "primary" else "p0",
            "link_state": "connected",
            "slots": ["0-8191"] if replacement_role == "primary" else [],
        },
        "p1": {
            "node_id": "p1",
            "flags": ["master"],
            "role": "primary",
            "master_id": None,
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
        },
        {
            "logical_id": "node-b",
            "container_name": "host-a",
            "container_id": "container-a",
            "pid": 102,
        },
        {
            "logical_id": "node-c",
            "container_name": "host-b",
            "container_id": "container-b",
            "pid": 201,
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
                    + '","Config":{"Labels":'
                    + json.dumps(labels)
                    + "}}]"
                )
            )
        return SimpleNamespace(stdout="", returncode=0)

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
        ["exec", "container-a", "kill", "-KILL", "101", "102"],
        ["exec", "container-b", "kill", "-KILL", "201"],
    ]
    assert [batch["status"] for batch in command_batches] == ["PASS", "PASS"]


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


def test_fault_client_series_keeps_only_operations_started_after_sigkill() -> None:
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
    ]

    series = capture._fault_client_series(
        [probe],
        {"sigkill_barrier": 10.0},
        [{"shard_id": "s0", "endpoint_monotonic": 10.1}],
    )[0]

    assert series["attempt_started_monotonic"] == [10.09]
    assert len(series["samples_through_stable_endpoint"]) == 1
    assert series["samples_through_stable_endpoint"][0]["set_completed_at_monotonic"] == 10.095
    assert series["samples_through_stable_endpoint"][0]["get_completed_at_monotonic"] == 10.1


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
    probe.samples = [
        {"started_at_monotonic": round(10.01 + (index * 0.09), 6)}
        for index in range(12)
    ]
    cadence = capture._fault_cadence([probe], 10.0, 1.0)
    markers = dict(zip(capture._fault_marker_names(), [10.0, 10.01, 10.1, 10.2, 10.3, 10.4, 11.4, 11.5]))
    convergence = {
        "converged": True,
        "unexpected_pfail": 0,
        "unexpected_fail": 0,
        "unexpected_promotions": 0,
        "split_brain": False,
        "slot_loss": False,
    }

    assert cadence["status"] == "PASS"
    assert capture._missing_fault_facts(
        markers,
        {"first_affected_write": 10.4, "first_affected_read": 10.5},
        {"status": "PASS", "required_shards": ["s0"]},
        [{"shard_id": "s0", "window_seconds": 1, "consecutive_pairs": 10, "errors": 0, "timeouts": 0, "earliest_qualifying": True}],
        cadence,
        convergence,
        {"unexpected_pfail": 0, "unexpected_fail": 0, "unexpected_promotions": 0, "split_brain": False},
    ) == []

    probe.samples.pop(5)
    broken = capture._fault_cadence([probe], 10.0, 1.0)
    errors = capture._missing_fault_facts(
        markers,
        {"first_affected_write": 10.4, "first_affected_read": 10.5},
        {"status": "PASS", "required_shards": ["s0"]},
        [{"shard_id": "s0", "window_seconds": 1, "consecutive_pairs": 10, "errors": 0, "timeouts": 0, "earliest_qualifying": True}],
        broken,
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
    monkeypatch.setattr(docker_runtime, "run_docker", fake_run_docker)

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


def test_owned_pid_observation_distinguishes_gone_from_probe_failure() -> None:
    target = SimpleNamespace(logical_id="node-1", pid=123)

    def result(returncode: int, stdout: str, stderr: str = "") -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    assert capture._owned_pid_is_alive(
        {"container_id": "owned-container"},
        target,
        command=lambda *_args, **_kwargs: result(0, "VSLAB_ALIVE"),
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
                },
                {
                    "trial_id": candidate_id,
                    "derived_intervals": {"formation_seconds": duration},
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

    assert len(calls) == 4
    assert all(
        call["scale"] == 50
        and call["sequence"] == 1
        and call["scenario"] == "cluster_timeout"
        for call in calls
    )
    assert [call["candidate"] for call in calls] == capture._formation_candidates()
    assert all(cell["required_pairs"] == 1 for cell in context.cells)
    assert [candidate["bounded_parallelism"] for candidate, _ in survivors] == [8]


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
