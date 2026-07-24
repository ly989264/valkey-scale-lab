from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from valkey_scale_lab.metrics import m2_resource
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.metrics.m2_resource import (
    M2ResourceMeasurementError,
    _cluster_link_errors_from_raw,
    _complete_owned_peer_sets,
    collect_m2_resource_window,
    validate_and_aggregate_m2_resource_samples,
    validate_equal_m2_resource_windows,
)


def test_size_to_bytes_parses_docker_units() -> None:
    assert docker_runtime._size_to_bytes("1kB") == 1000
    assert docker_runtime._size_to_bytes("1MiB") == 1024 * 1024
    assert docker_runtime._size_to_bytes("2.5MB") == 2_500_000


def test_system_metric_windows_follow_available_artifacts(tmp_path) -> None:
    (tmp_path / "management_ops_matrix.json").write_text("{}", encoding="utf-8")
    (tmp_path / "workload_windows.json").write_text("{}", encoding="utf-8")
    (tmp_path / "fault_timeline_report.json").write_text("{}", encoding="utf-8")
    assert docker_runtime._system_metric_windows_for_artifacts(tmp_path) == [
        "setup",
        "cleanup",
        "management",
        "workload",
        "fault",
    ]


class _FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def monotonic(self) -> float:
        return self.value

    def wall(self) -> float:
        return 1_700_000_000.0 + self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _FirstSampleEvent:
    def __init__(self) -> None:
        self.was_set = False

    def set(self) -> None:
        self.was_set = True


class _WindowStartEvent:
    def __init__(self, first_sample: _FirstSampleEvent, clock: _FakeClock) -> None:
        self.first_sample = first_sample
        self.clock = clock
        self.wait_timeouts: list[float] = []

    def wait(self, timeout: float) -> bool:
        assert self.first_sample.was_set is True
        self.wait_timeouts.append(timeout)
        self.clock.value += 7.0
        return True


class _FormationCompleteEvent:
    def __init__(self, sample_phases: tuple[str, ...]) -> None:
        phase_states = {
            "formation_bootstrap": (False, False),
            "formation_boundary": (False, True),
            "post_formation": (True, True),
        }
        self.states = [
            state
            for marker in sample_phases
            for state in phase_states[marker]
        ]
        self.position = 0

    def is_set(self) -> bool:
        state = self.states[self.position]
        self.position += 1
        return state


def _directional_cluster_link(
    node_id: str,
    direction: str,
    *,
    create_time: int = 1000,
    events: str = "r",
) -> dict:
    return {
        "direction": direction,
        "node_id": node_id,
        "create_time": create_time,
        "events": events,
        "send_buffer_allocated": 0,
        "send_buffer_used": 0,
    }


def _bidirectional_cluster_links(node_id: str, *, create_time: int = 1000) -> list[dict]:
    return [
        _directional_cluster_link(node_id, "to", create_time=create_time),
        _directional_cluster_link(node_id, "from", create_time=create_time),
    ]


def _m2_runtime_state() -> dict:
    return {
        "capability_id": "m2_performance",
        "runtime": {"run_id": "m2-run-1"},
        "nodehosts": [
            {
                "nodehost_id": "nodehost-a",
                "container_id": "cid-a",
                "container_name": "owned-a",
            }
        ],
        "nodes": [
            {
                "logical_id": "node-1",
                "nodehost_id": "nodehost-a",
                "container_id": "cid-a",
                "nodehost_container_name": "owned-a",
                "pid": 101,
                "client_port": 7101,
            },
            {
                "logical_id": "node-2",
                "nodehost_id": "nodehost-a",
                "container_id": "cid-a",
                "nodehost_container_name": "owned-a",
                "pid": 102,
                "client_port": 7102,
            },
        ],
    }


def _owned_inspect(*, run_id: str = "m2-run-1") -> str:
    return json.dumps(
        [
            {
                "Id": "cid-a",
                "Name": "/owned-a",
                "Config": {
                    "Labels": {
                        "org.valkey-scale-lab.project": "valkey-scale-lab",
                        "org.valkey-scale-lab.capability_id": "m2_performance",
                        "org.valkey-scale-lab.run_id": run_id,
                    }
                },
            }
        ]
    )


def _gone_process(pid: int = 101) -> list[dict]:
    return [{"nodehost_id": "nodehost-a", "container_id": "cid-a", "pid": pid}]


def _m2_batch_output(
    sample: int,
    *,
    gone_pids: set[int] | None = None,
    omitted_cluster_pids: set[int] | None = None,
    rollback_pid: int | None = None,
    non_connected_links: dict[int, list[tuple[str, str, str, str, str]]] | None = None,
    cluster_link_errors: dict[int, int] | None = None,
    cluster_link_counts: dict[int, int] | None = None,
    directional_cluster_links: dict[int, list[dict]] | None = None,
) -> str:
    gone = gone_pids or set()
    omitted = omitted_cluster_pids or set()
    link_rows = non_connected_links or {}
    error_claims = cluster_link_errors or {}
    link_counts = cluster_link_counts or {}
    directional_links = directional_cluster_links
    rows = ["META\t100\t4096"]
    process_values = {
        101: (7101, 10, 2, 5, 4, 2, 1000, 500, 100, 80),
        102: (7102, 20, 3, 6, 5, 3, 2000, 1000, 200, 160),
    }
    for pid, values in process_values.items():
        port, utime, stime, rss, fds, connections, sent_bytes, received_bytes, sent_messages, received_messages = values
        if pid in gone:
            rows.append(f"GONE\t{pid}\t{port}")
            continue
        rows.append(
            f"PID\t{pid}\t{utime + sample * 10}\t{stime}\t{rss + sample}\t{fds + sample}\t{connections}"
        )
        if pid in omitted:
            continue
        direction = -1 if pid == rollback_pid else 1
        scale = 1 if pid == 101 else 2
        rows.append(
            f"CLUSTER\t{pid}\t{port}\t{sent_bytes + direction * sample * 100 * scale}"
            f"\t{received_bytes + direction * sample * 50 * scale}"
            f"\t{sent_messages + direction * sample * 10 * scale}"
            f"\t{received_messages + direction * sample * 8 * scale}\t0\t{link_counts.get(pid, 2)}"
            f"\t{error_claims.get(pid, 0)}"
            f"\t{len(link_rows.get(pid, []))}"
        )
        rows.extend(
            f"LINK\t{pid}\t{node_id}\t{address}\t{flags}\t{master_id}\t{link_state}"
            for node_id, address, flags, master_id, link_state in link_rows.get(pid, [])
        )
        if directional_links is None or pid in directional_links:
            process_directional_links = (
                [] if directional_links is None else directional_links[pid]
            )
            raw_links = [
                {
                    "direction": link["direction"],
                    "node": link["node_id"],
                    "create-time": link["create_time"],
                    "events": link["events"],
                    "send-buffer-allocated": link["send_buffer_allocated"],
                    "send-buffer-used": link["send_buffer_used"],
                }
                for link in process_directional_links
            ]
            rows.append(f"CLINKS\t{pid}\t{json.dumps(raw_links, separators=(',', ':'))}")
    rows.append(f"NET\t{1000 + sample * 100}\t{2000 + sample * 200}")
    return "\n".join(rows)


def _inline_resource_report(report: dict) -> dict:
    errors: list[str] = []
    samples = m2_resource._resource_samples_with_directional_links(report, errors)
    assert errors == []
    return {
        **{
            key: value
            for key, value in report.items()
            if key != "directional_cluster_links_dictionary"
        },
        "samples": [copy.deepcopy(sample) for sample in samples],
    }


def _m2_resource_report_with_link(
    link: tuple[str, str, str, str, str],
    *,
    claimed_errors: int,
    window_name: str = "cluster-link-semantics",
    link_samples: set[int] | None = None,
    cluster_link_counts: tuple[int, ...] = (2, 2),
    allow_initial_membership_transitions: bool = False,
    sample_phases: tuple[str, ...] | None = None,
    directional_links_by_sample: tuple[dict[int, list[dict]], ...] | None = None,
) -> dict:
    clock = _FakeClock()
    sample = 0
    active_samples = set(range(len(cluster_link_counts))) if link_samples is None else link_samples
    formation_complete_event = (
        _FormationCompleteEvent(sample_phases) if sample_phases is not None else None
    )
    if sample_phases is not None:
        assert len(sample_phases) == len(cluster_link_counts)
    if directional_links_by_sample is not None:
        assert len(directional_links_by_sample) == len(cluster_link_counts)

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        assert args[6] == ""
        links = {101: [link]} if sample in active_samples else {}
        output = _m2_batch_output(
            sample,
            non_connected_links=links,
            cluster_link_errors={101: claimed_errors} if links else {},
            cluster_link_counts={
                101: cluster_link_counts[sample],
                102: cluster_link_counts[sample],
            },
            directional_cluster_links=(
                directional_links_by_sample[sample]
                if directional_links_by_sample is not None
                else None
            ),
        )
        sample += 1
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    return collect_m2_resource_window(
        _m2_runtime_state(),
        window_name=window_name,
        duration_seconds=len(cluster_link_counts) - 1,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
        formation_complete_event=formation_complete_event,
        allow_initial_membership_transitions=allow_initial_membership_transitions,
    )


def test_m2_resource_window_batches_owned_pids_and_aggregates_proc_counters() -> None:
    clock = _FakeClock()
    calls: list[list[str]] = []
    exec_count = 0

    def command(args, *, timeout, check):
        nonlocal exec_count
        calls.append(args)
        assert timeout == 30
        assert check is False
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        sample = exec_count
        exec_count += 1
        return SimpleNamespace(returncode=0, stdout=_m2_batch_output(sample), stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="candidate-soak",
        duration_seconds=2,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )

    assert report["status"] == "PASS"
    assert report["coverage"] == {
        "complete": True,
        "expected_sample_count": 3,
        "observed_sample_count": 3,
        "nodehost_count": 1,
        "process_count": 2,
        "sample_timestamps_unix_ms": [1700000100000, 1700000101000, 1700000102000],
        "sample_monotonic_seconds": [100.0, 101.0, 102.0],
        "scheduled_offsets_seconds": [0.0, 1.0, 2.0],
        "actual_window_start_monotonic_seconds": 100.0,
        "actual_window_end_monotonic_seconds": 102.0,
        "actual_window_span_seconds": 2.0,
        "sampling_envelope_end_monotonic_seconds": 102.0,
        "sampling_envelope_span_seconds": 2.0,
        "max_schedule_lag_seconds": 0.0,
        "max_sample_collection_seconds": 0.0,
    }
    assert report["metrics"] == {
        "peak_rss_bytes": 15 * 4096,
        "cpu_time_seconds": 0.4,
        "fd_count": 13,
        "connection_count": 5,
        "cluster_bus_bytes": 900,
        "cluster_link_errors": 0,
        "buffer_overflows": 0,
    }
    exec_calls = [args for args in calls if args[0] == "exec"]
    assert len(exec_calls) == 3
    assert all(args[1] == "cid-a" for args in exec_calls)
    assert all(args[6] == "" for args in exec_calls)
    assert all(args[-2:] == ["101:7101", "102:7102"] for args in exec_calls)
    assert all("/proc/$pid/stat" in args[4] and "/proc/$pid/statm" in args[4] for args in exec_calls)
    assert all("/proc/$pid/fd" in args[4] and "/proc/net/dev" in args[4] for args in exec_calls)
    assert all("valkey-cli --raw -p \"$port\" CLUSTER INFO" in args[4] for args in exec_calls)
    assert all("valkey-cli --raw -p \"$port\" CLUSTER NODES" in args[4] for args in exec_calls)
    assert all("valkey-cli -3 --json -p \"$port\" CLUSTER LINKS" in args[4] for args in exec_calls)
    assert all('printf "LINK\\t%s' in args[4] and "pending_handshake" in args[4] for args in exec_calls)
    assert report["diagnostics"] == {"cluster_bus_messages": 108, "namespace_network_bytes": 600}
    assert "exact Valkey 9.1 per-node CLUSTER INFO" in report["metric_provenance"]["cluster_bus_bytes"]
    assert "no namespace-traffic fallback" in report["metric_provenance"]["cluster_bus_bytes"]
    assert "diagnostic only" in report["diagnostic_provenance"]["namespace_network_bytes"]
    entries = report["directional_cluster_links_dictionary"]
    assert len(entries) == 1
    assert entries[0]["directional_cluster_links"] == []
    assert all(
        process["directional_cluster_links_sha256"] == entries[0]["sha256"]
        and "directional_cluster_links" not in process
        for sample in report["samples"]
        for nodehost in sample["nodehosts"]
        for process in nodehost["processes"]
    )
    assert validate_and_aggregate_m2_resource_samples(report)["status"] == "PASS"


def test_m2_resource_window_interns_directional_links_before_report_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock()
    sample = 0
    original_resource_report = m2_resource._resource_report
    observed_compact_samples = False

    def recording_resource_report(**kwargs):
        nonlocal observed_compact_samples
        samples = kwargs["samples"]
        entries = kwargs["directional_cluster_links"]
        observed_compact_samples = bool(samples) and bool(entries) and all(
            "directional_cluster_links_sha256" in process
            and "directional_cluster_links" not in process
            for row in samples
            for nodehost in row["nodehosts"]
            for process in nodehost["processes"]
        )
        return original_resource_report(**kwargs)

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        output = _m2_batch_output(sample)
        sample += 1
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(m2_resource, "_resource_report", recording_resource_report)
    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="collection-time-interning",
        duration_seconds=1,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )

    assert report["status"] == "PASS"
    assert observed_compact_samples is True


def test_m2_resource_probe_does_not_classify_unreadable_proc_stat_as_gone() -> None:
    script = m2_resource._PROC_BATCH_SCRIPT
    missing = 'if [ ! -e "$stat_path" ]; then'
    unreadable = 'if [ ! -r "$stat_path" ]; then'

    assert missing in script
    assert unreadable in script
    assert script.index(missing) < script.index(unreadable)
    assert "stat_unreadable" in script
    assert "stat_malformed" in script
    assert 'if [ ! -r "$stat_path" ] ||' not in script
    assert 'case "$stat_line" in' in script
    assert "stat_tail=${stat_line##*) }" in script
    assert "R|S|D|T|t|W|K|P|I)" in script


def test_m2_resource_probe_rechecks_stat_after_secondary_proc_exit_race() -> None:
    script = m2_resource._PROC_BATCH_SCRIPT

    helper = script.split("emit_process_failure() {", 1)[1].split(
        "for owned_process", 1
    )[0]
    assert '[ "$expected_gone" -eq 1 ]' in helper
    assert '[ ! -e "$stat_path" ]' in helper
    assert "gone_stat_tail=${gone_stat_line##*) }" in helper
    assert 'case "$gone_state" in' in helper
    assert "Z|X|x)" in helper
    assert "printf 'GONE\\t%s\\t%s\\n'" in helper
    assert "printf 'GONE\\t%s\\t%s\\n'" not in script.split(
        "for owned_process", 1
    )[1]
    for reason in (
        "statm_unreadable",
        "fd_unreadable",
        "cluster_info_unreadable",
        "cluster_nodes_unreadable",
        "cluster_links_unreadable",
        "process_stat_reread",
    ):
        assert f"emit_process_failure {reason}" in script


def test_m2_resource_probe_buffers_complete_process_rows_across_fault_race() -> None:
    script = m2_resource._PROC_BATCH_SCRIPT

    pid_buffer = script.index("pid_row=$(printf 'PID")
    first_cluster_probe = script.index("cluster_info=$(valkey-cli")
    final_identity_probe = script.index("final_stat_line=$(cat")
    row_flush = script.index("printf '%s\\n%s\\n' \"$pid_row\" \"$cluster_row\"")

    assert pid_buffer < first_cluster_probe < final_identity_probe < row_flush
    assert "start_time=${20}" in script
    assert script.count("Z|X|x)") >= 3
    assert "emit_process_failure process_not_live_at_reread" in script
    assert 'if [ "${20}" != "$start_time" ]; then' in script
    assert "emit_process_failure process_identity_changed" in script


def test_m2_resource_probe_is_valid_posix_shell_fixture() -> None:
    completed = subprocess.run(
        ["sh", "-n"],
        input=m2_resource._PROC_BATCH_SCRIPT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_m2_resource_window_excludes_only_well_formed_pending_handshake() -> None:
    link = (
        "a" * 40,
        "127.0.0.1:7201@17201",
        "handshake",
        "-",
        "disconnected",
    )

    report = _m2_resource_report_with_link(link, claimed_errors=0)

    assert report["status"] == "PASS"
    assert report["metrics"]["cluster_link_errors"] == 0
    process = report["samples"][0]["nodehosts"][0]["processes"][0]
    assert process["non_connected_cluster_links"] == [
        {
            "node_id": "a" * 40,
            "address": "127.0.0.1:7201@17201",
            "flags": ["handshake"],
            "master_id": "-",
            "link_state": "disconnected",
        }
    ]
    assert process["non_connected_cluster_link_count"] == 1
    assert validate_and_aggregate_m2_resource_samples(report)["status"] == "PASS"


def test_m2_resource_window_counts_established_disconnected_link() -> None:
    report = _m2_resource_report_with_link(
        ("b" * 40, "127.0.0.1:7201@17201", "master", "-", "disconnected"),
        claimed_errors=1,
    )

    assert report["status"] == "PASS"
    assert report["metrics"]["cluster_link_errors"] == 1
    verdict = validate_equal_m2_resource_windows(report, copy.deepcopy(report))
    assert verdict["status"] == "FAIL"
    assert any("metric cluster_link_errors must be zero" in error for error in verdict["errors"])


def test_m2_resource_comparison_can_preserve_candidate_safety_rejection() -> None:
    baseline = _m2_resource_report_with_link(
        ("a" * 40, "127.0.0.1:7201@17201", "handshake", "-", "disconnected"),
        claimed_errors=0,
    )
    candidate = _m2_resource_report_with_link(
        ("b" * 40, "127.0.0.1:7201@17201", "master", "-", "disconnected"),
        claimed_errors=1,
    )

    assert validate_equal_m2_resource_windows(baseline, candidate)["status"] == "FAIL"
    assert validate_equal_m2_resource_windows(
        baseline,
        candidate,
        allow_candidate_safety_failure=True,
    )["status"] == "PASS"
    assert validate_equal_m2_resource_windows(
        candidate,
        baseline,
        allow_candidate_safety_failure=True,
    )["status"] == "FAIL"


_FORMATION_PEER_ID = "b" * 40
_FORMATION_OTHER_PEER_ID = "c" * 40
_FORMATION_KNOWN_PRIMARY_ID = f"{1:040x}"
_FORMATION_ROLE_ROW = {
    "node_id": _FORMATION_PEER_ID,
    "address": "127.0.0.1:7201@17201",
    "flags": ["master"],
    "master_id": "-",
    "link_state": "disconnected",
}
_FORMATION_HANDSHAKE_ROW = {
    "node_id": _FORMATION_OTHER_PEER_ID,
    "address": "127.0.0.1:7202@17202",
    "flags": ["handshake"],
    "master_id": "-",
    "link_state": "disconnected",
}


def _semantic_cluster_process(
    *,
    cluster_link_count: int,
    observations: list[dict] | None = None,
    directional_links: list[dict] | None = None,
    pid: int = 101,
    logical_id: str = "observer",
    claimed_errors: int = 0,
) -> dict:
    raw_observations = copy.deepcopy(observations or [])
    return {
        "logical_id": logical_id,
        "pid": pid,
        "cluster_link_count": cluster_link_count,
        "cluster_link_errors": claimed_errors,
        "non_connected_cluster_link_count": len(raw_observations),
        "non_connected_cluster_links": raw_observations,
        "directional_cluster_links": copy.deepcopy(directional_links or []),
    }


def _directional_history(spec: tuple[tuple[str, int], ...]) -> list[dict]:
    return [
        _directional_cluster_link(_FORMATION_PEER_ID, direction, create_time=create_time)
        for direction, create_time in spec
    ]


def _complete_boundary_links(link_count: int) -> list[dict]:
    peer_ids = [
        _FORMATION_PEER_ID,
        *(f"{index + 1:040x}" for index in range(link_count - 2)),
    ]
    return [
        _directional_cluster_link(node_id, direction)
        for node_id in peer_ids
        for direction in ("to", "from")
    ]


def test_m2_complete_owned_peer_sets_require_one_consistent_peer_universe() -> None:
    node_ids = ("a" * 40, "b" * 40, "c" * 40)
    processes = [
        _semantic_cluster_process(
            cluster_link_count=3,
            logical_id=f"node-{index}",
            directional_links=[
                link
                for peer_id in node_ids
                if peer_id != node_ids[index]
                for link in _bidirectional_cluster_links(peer_id)
            ],
        )
        for index in range(3)
    ]

    assert _complete_owned_peer_sets(processes) == {
        f"node-{index}": frozenset(
            peer_id for peer_id in node_ids if peer_id != node_ids[index]
        )
        for index in range(3)
    }

    inconsistent = copy.deepcopy(processes)
    for link in inconsistent[1]["directional_cluster_links"]:
        if link["node_id"] == node_ids[0]:
            link["node_id"] = "d" * 40
    assert _complete_owned_peer_sets(inconsistent) is None


def test_m2_complete_owned_peer_sets_support_single_process_formation() -> None:
    process = _semantic_cluster_process(
        cluster_link_count=1,
        logical_id="node-0",
    )

    assert _complete_owned_peer_sets([process]) == {
        "node-0": frozenset(),
    }


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            {
                "counts": (1, 2, 2, 2),
                "directions": ((), (), (("to", 1000), ("from", 1000))),
            },
            id="pr25-initial-membership-expansion",
        ),
        pytest.param(
            {
                "counts": (20, 23, 23, 25),
                "directions": ((), (), (("to", 1000), ("from", 1000))),
            },
            id="pr26-progressive-expansion",
        ),
        pytest.param(
            {
                "counts": (2, 2, 2, 2),
                "previous_observations": [_FORMATION_HANDSHAKE_ROW],
                "directions": ((), (), (("to", 1000), ("from", 1000))),
            },
            id="pr31-unrelated-prior-handshake",
        ),
        pytest.param(
            {
                "counts": (2, 2, 2, 2),
                "directions": (
                    (("to", 1000),),
                    (("from", 1000),),
                    (("to", 1000), ("from", 1000)),
                ),
            },
            id="pr34-direction-correction",
        ),
        pytest.param(
            {
                "counts": (2, 2, 2, 2),
                "directions": (
                    (("to", 1000), ("from", 1000)),
                    (("to", 2000), ("from", 1000)),
                    (("to", 2000), ("from", 1000)),
                ),
            },
            id="pr37-same-sample-reconnect-next-confirmed",
        ),
    ],
)
def test_m2_bootstrap_historical_shapes_share_phase_invariants(case: dict) -> None:
    previous_count, current_count, next_count, boundary_count = case["counts"]
    previous_directions, current_directions, recovered_directions = case["directions"]
    previous = _semantic_cluster_process(
        cluster_link_count=previous_count,
        observations=case.get("previous_observations"),
        directional_links=_directional_history(previous_directions),
    )
    current = _semantic_cluster_process(
        cluster_link_count=current_count,
        observations=[_FORMATION_ROLE_ROW],
        directional_links=_directional_history(current_directions),
        claimed_errors=1,
    )
    recovered = _semantic_cluster_process(
        cluster_link_count=next_count,
        directional_links=_directional_history(recovered_directions),
    )
    boundary = _semantic_cluster_process(
        cluster_link_count=boundary_count,
        directional_links=_complete_boundary_links(boundary_count),
    )
    raw_current = copy.deepcopy(current)

    assert (
        _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=previous,
            next_process=recovered,
            formation_boundary_process=boundary,
            allow_initial_membership_transition=True,
            sample_phase="formation_bootstrap",
        )
        == 0
    )
    assert current == raw_current


@pytest.mark.parametrize(
    ("flags", "master_id"),
    [
        pytest.param(["master"], "-", id="primary"),
        pytest.param(["slave"], "-", id="replica-primary-unknown"),
        pytest.param(
            ["slave"],
            _FORMATION_KNOWN_PRIMARY_ID,
            id="replica-primary-known",
        ),
        pytest.param(["master", "nofailover"], "-", id="primary-no-failover"),
        pytest.param(
            ["slave", "nofailover"],
            "-",
            id="replica-primary-unknown-no-failover",
        ),
        pytest.param(
            ["slave", "nofailover"],
            _FORMATION_KNOWN_PRIMARY_ID,
            id="replica-primary-known-no-failover",
        ),
        pytest.param(
            ["nofailover", "master"],
            "-",
            id="primary-no-failover-reordered",
        ),
        pytest.param(
            ["nofailover", "slave"],
            _FORMATION_KNOWN_PRIMARY_ID,
            id="replica-primary-known-no-failover-reordered",
        ),
    ],
)
@pytest.mark.parametrize(
    ("current_directions", "recovered_directions"),
    [
        pytest.param((), (("to", 1000),), id="next-outbound"),
        pytest.param((), (("from", 1000),), id="next-inbound"),
        pytest.param(
            (("to", 1000),),
            (("to", 1000), ("from", 1000)),
            id="current-outbound",
        ),
        pytest.param(
            (("from", 1000),),
            (("to", 1000), ("from", 1000)),
            id="current-inbound",
        ),
        pytest.param(
            (("to", 1000), ("from", 1000)),
            (("to", 1000), ("from", 1000)),
            id="current-bidirectional",
        ),
    ],
)
@pytest.mark.parametrize(
    "sample_phase",
    ["formation_bootstrap", "formation_boundary"],
)
def test_m2_formation_transition_is_invariant_to_documented_role_and_direction_state(
    flags: list[str],
    master_id: str,
    current_directions: tuple[tuple[str, int], ...],
    recovered_directions: tuple[tuple[str, int], ...],
    sample_phase: str,
) -> None:
    previous = _semantic_cluster_process(cluster_link_count=1)
    current = _semantic_cluster_process(
        cluster_link_count=3,
        observations=[
            {
                **_FORMATION_ROLE_ROW,
                "flags": flags,
                "master_id": master_id,
            }
        ],
        directional_links=_directional_history(current_directions),
        claimed_errors=1,
    )
    recovered = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=_directional_history(recovered_directions),
    )
    boundary = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=_complete_boundary_links(3),
    )

    assert (
        _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=previous,
            next_process=recovered,
            formation_boundary_process=boundary,
            allow_initial_membership_transition=True,
            sample_phase=sample_phase,
        )
        == 0
    )


@pytest.mark.parametrize(
    "next_links",
    [
        pytest.param([], id="missing-peer"),
        pytest.param(
            [_directional_cluster_link(_FORMATION_OTHER_PEER_ID, "to")],
            id="different-peer",
        ),
        pytest.param(
            [_directional_cluster_link(_FORMATION_PEER_ID, "to", events="w")],
            id="target-not-readable",
        ),
        pytest.param(
            [
                _directional_cluster_link(_FORMATION_PEER_ID, "to"),
                _directional_cluster_link(
                    _FORMATION_PEER_ID,
                    "to",
                    create_time=2000,
                ),
            ],
            id="duplicate-target-direction",
        ),
    ],
)
@pytest.mark.parametrize(
    "sample_phase",
    ["formation_bootstrap", "formation_boundary"],
)
def test_m2_formation_transition_rejects_unproven_next_sample_recovery(
    next_links: list[dict],
    sample_phase: str,
) -> None:
    previous = _semantic_cluster_process(cluster_link_count=1)
    current = _semantic_cluster_process(
        cluster_link_count=3,
        observations=[
            {
                **_FORMATION_ROLE_ROW,
                "flags": ["slave", "nofailover"],
                "master_id": "-",
            }
        ],
        claimed_errors=1,
    )
    recovered = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=next_links,
    )
    boundary = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=_complete_boundary_links(3),
    )

    assert (
        _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=previous,
            next_process=recovered,
            formation_boundary_process=boundary,
            allow_initial_membership_transition=True,
            sample_phase=sample_phase,
        )
        == 1
    )


@pytest.mark.parametrize(
    "sample_phase",
    [None, "pre_barrier", "window", "post_formation"],
)
def test_m2_formation_transition_does_not_relax_other_sample_phases(
    sample_phase: str | None,
) -> None:
    previous = _semantic_cluster_process(cluster_link_count=1)
    current = _semantic_cluster_process(
        cluster_link_count=3,
        observations=[
            {
                **_FORMATION_ROLE_ROW,
                "flags": ["slave"],
                "master_id": "-",
            }
        ],
        claimed_errors=1,
    )
    recovered = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=_directional_history((("to", 1000),)),
    )
    boundary = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=_complete_boundary_links(3),
    )

    assert (
        _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=previous,
            next_process=recovered,
            formation_boundary_process=boundary,
            allow_initial_membership_transition=True,
            sample_phase=sample_phase,
        )
        == 1
    )


@pytest.mark.parametrize(
    ("flags", "master_id"),
    [
        pytest.param(
            ["master"],
            _FORMATION_KNOWN_PRIMARY_ID,
            id="primary-with-primary-id",
        ),
        pytest.param(["slave", "fail?"], "-", id="replica-failure-flag"),
        pytest.param(
            ["slave", "nofailover", "fail?"],
            "-",
            id="safe-modifier-does-not-mask-failure",
        ),
        pytest.param(["master", "slave"], "-", id="conflicting-roles"),
        pytest.param(
            ["nofailover"],
            "-",
            id="modifier-without-role",
        ),
    ],
)
@pytest.mark.parametrize(
    "sample_phase",
    ["formation_bootstrap", "formation_boundary"],
)
def test_m2_formation_transition_rejects_adversarial_role_rows(
    flags: list[str],
    master_id: str,
    sample_phase: str,
) -> None:
    previous = _semantic_cluster_process(cluster_link_count=1)
    current = _semantic_cluster_process(
        cluster_link_count=3,
        observations=[
            {
                **_FORMATION_ROLE_ROW,
                "flags": flags,
                "master_id": master_id,
            }
        ],
        claimed_errors=1,
    )
    recovered = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=_directional_history((("to", 1000),)),
    )
    boundary = _semantic_cluster_process(
        cluster_link_count=3,
        directional_links=_complete_boundary_links(3),
    )

    assert (
        _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=previous,
            next_process=recovered,
            formation_boundary_process=boundary,
            allow_initial_membership_transition=True,
            sample_phase=sample_phase,
        )
        == 1
    )


def _formation_directional_samples(sample_count: int) -> tuple[dict[int, list[dict]], ...]:
    return tuple(
        {
            101: _bidirectional_cluster_links("b" * 40),
            102: _bidirectional_cluster_links("a" * 40),
        }
        for _ in range(sample_count)
    )


def _trusted_formation_report(
    *,
    sample_phases: tuple[str, ...] = (
        "formation_bootstrap",
        "formation_bootstrap",
        "post_formation",
    ),
    link_samples: set[int] | None = None,
    link: tuple[str, str, str, str, str] = (
        "b" * 40,
        "127.0.0.1:7201@17201",
        "master",
        "-",
        "disconnected",
    ),
    claimed_errors: int = 1,
    directional_links_by_sample: tuple[dict[int, list[dict]], ...] | None = None,
) -> dict:
    return _inline_resource_report(
        _m2_resource_report_with_link(
            link,
            claimed_errors=claimed_errors,
            window_name="m2-formation-bootstrap",
            link_samples={1} if link_samples is None else link_samples,
            cluster_link_counts=tuple(2 for _ in sample_phases),
            allow_initial_membership_transitions=True,
            sample_phases=sample_phases,
            directional_links_by_sample=(
                directional_links_by_sample
                if directional_links_by_sample is not None
                else _formation_directional_samples(len(sample_phases))
            ),
        ),
    )


@pytest.mark.parametrize(
    "sample_phases",
    [
        pytest.param(
            (
                "formation_bootstrap",
                "formation_bootstrap",
                "post_formation",
                "post_formation",
            ),
            id="event-between-samples",
        ),
        pytest.param(
            (
                "formation_bootstrap",
                "formation_boundary",
                "post_formation",
                "post_formation",
            ),
            id="event-during-transition-sample",
        ),
    ],
)
def test_m2_formation_report_is_invariant_to_formation_event_timing(
    sample_phases: tuple[str, ...],
) -> None:
    directional_samples = list(_formation_directional_samples(4))
    directional_samples[1][101] = directional_samples[1][101][:1]
    directional_samples[2][101] = directional_samples[2][101][:1]
    report = _trusted_formation_report(
        sample_phases=sample_phases,
        directional_links_by_sample=tuple(directional_samples),
    )

    assert report["status"] == "PASS"
    assert report["metrics"]["cluster_link_errors"] == 0
    assert [sample["sample_phase"] for sample in report["samples"]] == list(sample_phases)
    process = report["samples"][1]["nodehosts"][0]["processes"][0]
    assert process["cluster_link_errors"] == 1
    assert process["non_connected_cluster_link_count"] == 1
    assert process["non_connected_cluster_links"] == [_FORMATION_ROLE_ROW]
    assert process["directional_cluster_links"] == directional_samples[1][101]
    first_post_process = report["samples"][2]["nodehosts"][0]["processes"][0]
    assert first_post_process["non_connected_cluster_links"] == []
    assert first_post_process["directional_cluster_links"] == directional_samples[2][101]
    trusted = validate_and_aggregate_m2_resource_samples(
        report,
        allow_initial_membership_transitions=True,
    )
    assert trusted["status"] == "PASS"
    assert trusted["metrics"]["cluster_link_errors"] == 0


def test_m2_formation_report_is_invariant_to_nonfailure_role_modifier() -> None:
    report = _trusted_formation_report(
        link=(
            _FORMATION_PEER_ID,
            "127.0.0.1:7201@17201",
            "slave,nofailover",
            "-",
            "disconnected",
        ),
    )

    trusted = validate_and_aggregate_m2_resource_samples(
        report,
        allow_initial_membership_transitions=True,
    )
    assert trusted["status"] == "PASS"
    assert trusted["metrics"]["cluster_link_errors"] == 0


@pytest.mark.parametrize(
    ("next_links", "expected_status", "expected_errors"),
    [
        pytest.param([], "PASS", 1, id="missing-peer"),
        pytest.param(
            [_directional_cluster_link(_FORMATION_OTHER_PEER_ID, "to")],
            "PASS",
            1,
            id="different-peer",
        ),
        pytest.param(
            [_directional_cluster_link(_FORMATION_PEER_ID, "to", events="w")],
            "PASS",
            1,
            id="target-not-readable",
        ),
        pytest.param(
            [
                _directional_cluster_link(_FORMATION_PEER_ID, "to"),
                _directional_cluster_link(
                    _FORMATION_PEER_ID,
                    "to",
                    create_time=2000,
                ),
            ],
            "PASS",
            1,
            id="duplicate-target-direction",
        ),
    ],
)
def test_m2_formation_report_rejects_unproven_next_sample_recovery(
    next_links: list[dict],
    expected_status: str,
    expected_errors: int | None,
) -> None:
    report = _trusted_formation_report(
        sample_phases=(
            "formation_bootstrap",
            "formation_bootstrap",
            "post_formation",
            "post_formation",
        ),
    )
    report["samples"][2]["nodehosts"][0]["processes"][0][
        "directional_cluster_links"
    ] = copy.deepcopy(next_links)

    trusted = validate_and_aggregate_m2_resource_samples(
        report,
        allow_initial_membership_transitions=True,
    )
    assert trusted["status"] == expected_status
    if expected_errors is not None:
        assert trusted["metrics"]["cluster_link_errors"] == expected_errors
    else:
        assert trusted["coverage"]["complete"] is False


def test_m2_resource_window_does_not_self_authorize_bootstrap_transition() -> None:
    report = _trusted_formation_report()

    recomputed = validate_and_aggregate_m2_resource_samples(report)
    assert recomputed["status"] == "PASS"
    assert recomputed["metrics"]["cluster_link_errors"] == 1
    assert validate_equal_m2_resource_windows(report, copy.deepcopy(report))["status"] == "FAIL"


@pytest.mark.parametrize(
    ("sample_phases", "link_samples", "link", "claimed_errors"),
    [
        pytest.param(
            ("formation_bootstrap", "formation_boundary", "post_formation"),
            {1, 2},
            ("b" * 40, "127.0.0.1:7201@17201", "master", "-", "disconnected"),
            1,
            id="boundary-role-disconnect-persists-into-post",
        ),
        pytest.param(
            ("formation_bootstrap", "formation_boundary", "post_formation"),
            {1, 2},
            ("c" * 40, "127.0.0.1:7202@17202", "handshake", "-", "disconnected"),
            0,
            id="boundary-handshake-persists-into-post",
        ),
        pytest.param(
            (
                "formation_bootstrap",
                "formation_boundary",
                "post_formation",
                "post_formation",
            ),
            {3},
            ("b" * 40, "127.0.0.1:7201@17201", "master", "-", "disconnected"),
            1,
            id="post-formation-role-disconnect",
        ),
        pytest.param(
            (
                "formation_bootstrap",
                "formation_boundary",
                "post_formation",
                "post_formation",
            ),
            {3},
            ("c" * 40, "127.0.0.1:7202@17202", "handshake", "-", "disconnected"),
            0,
            id="post-formation-handshake",
        ),
    ],
)
def test_m2_formation_report_fails_closed_for_boundary_or_post_disconnect(
    sample_phases: tuple[str, ...],
    link_samples: set[int],
    link: tuple[str, str, str, str, str],
    claimed_errors: int,
) -> None:
    report = _trusted_formation_report(
        sample_phases=sample_phases,
        link_samples=link_samples,
        link=link,
        claimed_errors=claimed_errors,
    )

    assert report["status"] == "FAIL"
    assert report["coverage"]["complete"] is False


def test_m2_formation_report_requires_complete_post_formation_boundary() -> None:
    report = _trusted_formation_report(
        sample_phases=(
            "formation_bootstrap",
            "formation_bootstrap",
            "formation_boundary",
        ),
        link_samples=set(),
    )

    assert report["status"] == "FAIL"
    assert report["coverage"]["complete"] is False
    assert any(
        "never reached a complete post-formation boundary" in error
        for error in report["errors"]
    )


def _complete_bootstrap_transition() -> tuple[dict, dict, dict, dict]:
    previous = _semantic_cluster_process(
        cluster_link_count=2,
        directional_links=_bidirectional_cluster_links(_FORMATION_PEER_ID),
    )
    current = _semantic_cluster_process(
        cluster_link_count=2,
        observations=[_FORMATION_ROLE_ROW],
        directional_links=_bidirectional_cluster_links(_FORMATION_PEER_ID),
        claimed_errors=1,
    )
    recovered = _semantic_cluster_process(
        cluster_link_count=2,
        directional_links=_bidirectional_cluster_links(_FORMATION_PEER_ID),
    )
    boundary = copy.deepcopy(recovered)
    return previous, current, recovered, boundary


def test_m2_bootstrap_transition_counts_disconnect_when_next_sample_is_still_disconnected() -> None:
    previous, current, recovered, boundary = _complete_bootstrap_transition()
    replica_without_known_primary = {
        **_FORMATION_ROLE_ROW,
        "flags": ["slave"],
        "master_id": "-",
    }
    current["non_connected_cluster_links"] = [
        copy.deepcopy(replica_without_known_primary)
    ]
    recovered["non_connected_cluster_links"] = [
        copy.deepcopy(replica_without_known_primary)
    ]
    recovered["non_connected_cluster_link_count"] = 1
    recovered["cluster_link_errors"] = 1

    assert (
        _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=previous,
            next_process=recovered,
            formation_boundary_process=boundary,
            allow_initial_membership_transition=True,
            sample_phase="formation_bootstrap",
        )
        == 1
    )


@pytest.mark.parametrize("missing", ["previous", "next", "boundary"])
def test_m2_bootstrap_transition_raises_for_missing_surrounding_evidence(missing: str) -> None:
    previous, current, recovered, boundary = _complete_bootstrap_transition()
    current["non_connected_cluster_links"][0].update(
        {"flags": ["slave"], "master_id": "-"}
    )
    evidence = {
        "previous": previous,
        "next": recovered,
        "boundary": boundary,
    }
    evidence[missing] = None

    with pytest.raises(
        M2ResourceMeasurementError,
        match="formation transition lacks complete surrounding evidence",
    ):
        _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=evidence["previous"],
            next_process=evidence["next"],
            formation_boundary_process=evidence["boundary"],
            allow_initial_membership_transition=True,
            sample_phase="formation_bootstrap",
        )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param("missing-clinks", id="missing-cluster-links"),
        pytest.param("incomplete-clinks", id="incomplete-cluster-links"),
        pytest.param("one-direction", id="no-bidirectional-boundary"),
    ],
)
def test_m2_formation_report_fails_closed_for_incomplete_directional_evidence(
    mutate: str,
) -> None:
    directional_samples = list(_formation_directional_samples(3))
    boundary_links = copy.deepcopy(directional_samples[2])
    if mutate == "missing-clinks":
        del boundary_links[101]
    elif mutate == "incomplete-clinks":
        boundary_links[101][0] = {
            **boundary_links[101][0],
            "events": "x",
        }
    else:
        boundary_links[101] = boundary_links[101][:1]
    directional_samples[2] = boundary_links

    report = _trusted_formation_report(
        directional_links_by_sample=tuple(directional_samples),
    )

    assert report["status"] == "FAIL"
    assert report["coverage"]["complete"] is False


def test_m2_formation_validator_rejects_inconsistent_owned_peer_topology() -> None:
    report = _trusted_formation_report(
        sample_phases=(
            "formation_bootstrap",
            "formation_bootstrap",
            "post_formation",
            "post_formation",
        ),
    )
    process = report["samples"][2]["nodehosts"][0]["processes"][1]
    for link in process["directional_cluster_links"]:
        link["node_id"] = _FORMATION_PEER_ID

    trusted = validate_and_aggregate_m2_resource_samples(
        report,
        allow_initial_membership_transitions=True,
    )
    assert trusted["status"] == "FAIL"
    assert trusted["coverage"]["complete"] is False
    assert any("inconsistent owned peer topology" in error for error in trusted["errors"])


def test_m2_formation_validator_rejects_peer_identity_change_after_strict_boundary() -> None:
    report = _trusted_formation_report(
        sample_phases=(
            "formation_bootstrap",
            "formation_bootstrap",
            "post_formation",
            "post_formation",
        ),
    )
    process = report["samples"][3]["nodehosts"][0]["processes"][1]
    for link in process["directional_cluster_links"]:
        link["node_id"] = _FORMATION_OTHER_PEER_ID

    trusted = validate_and_aggregate_m2_resource_samples(
        report,
        allow_initial_membership_transitions=True,
    )
    assert trusted["status"] == "FAIL"
    assert trusted["coverage"]["complete"] is False
    assert any("changed owned peer identity" in error for error in trusted["errors"])


@pytest.mark.parametrize(
    "convergence_case",
    [
        pytest.param("early-formation", id="early-formation-temporary-id"),
        pytest.param("last-formation", id="last-formation-temporary-id"),
        pytest.param("first-post", id="first-post-one-way-temporary-id"),
        pytest.param(
            "complete-then-incomplete",
            id="complete-formation-then-incomplete-convergence",
        ),
    ],
)
def test_m2_formation_validator_locks_peer_identity_only_at_strict_boundary(
    convergence_case: str,
) -> None:
    report = _trusted_formation_report(
        sample_phases=(
            "formation_bootstrap",
            "formation_bootstrap",
            "post_formation",
            "post_formation",
        ),
        link_samples=set(),
        claimed_errors=0,
    )
    changed_sample_index = {
        "early-formation": 0,
        "last-formation": 1,
        "first-post": 2,
        "complete-then-incomplete": 0,
    }[convergence_case]
    process = report["samples"][changed_sample_index]["nodehosts"][0]["processes"][0]
    for link in process["directional_cluster_links"]:
        link["node_id"] = _FORMATION_OTHER_PEER_ID
    if convergence_case == "first-post":
        process["directional_cluster_links"] = process["directional_cluster_links"][:1]
    elif convergence_case == "complete-then-incomplete":
        report["samples"][1]["nodehosts"][0]["processes"][0][
            "directional_cluster_links"
        ] = []

    trusted = validate_and_aggregate_m2_resource_samples(
        report,
        allow_initial_membership_transitions=True,
    )
    assert trusted["status"] == "PASS"
    assert trusted["metrics"]["cluster_link_errors"] == 0


def test_m2_formation_report_accepts_boundary_as_first_complete_peer_topology() -> None:
    directional_samples = list(_formation_directional_samples(3))
    directional_samples[0][102] = []
    directional_samples[1][102] = []

    report = _trusted_formation_report(
        directional_links_by_sample=tuple(directional_samples),
    )

    assert report["status"] == "PASS"
    assert report["metrics"]["cluster_link_errors"] == 0


@pytest.mark.parametrize("missing_sample", ["previous", "next"])
def test_m2_formation_validator_fails_when_surrounding_sample_is_missing(
    missing_sample: str,
) -> None:
    report = _trusted_formation_report()
    missing_index = 0 if missing_sample == "previous" else 2
    del report["samples"][missing_index]

    assert (
        validate_and_aggregate_m2_resource_samples(
            report,
            allow_initial_membership_transitions=True,
        )["status"]
        == "FAIL"
    )


@pytest.mark.parametrize("mutation", ["pid", "link-count"])
def test_m2_formation_validator_fails_for_owned_pid_change_or_topology_rollback(
    mutation: str,
) -> None:
    report = _trusted_formation_report()
    if mutation == "pid":
        report["samples"][2]["nodehosts"][0]["processes"][0]["pid"] = 202
    else:
        report["samples"][1]["nodehosts"][0]["processes"][0][
            "cluster_link_count"
        ] = 3

    assert (
        validate_and_aggregate_m2_resource_samples(
            report,
            allow_initial_membership_transitions=True,
        )["status"]
        == "FAIL"
    )


def test_m2_resource_window_fails_closed_for_unsafe_or_unknown_link_states() -> None:
    unsafe_links = [
        ("c" * 40, "127.0.0.1:7201@17201", "master,fail?", "-", "disconnected"),
        ("d" * 40, "127.0.0.1:7201@17201", "master,fail", "-", "disconnected"),
        ("e" * 40, ":0@0", "master,noaddr", "-", "disconnected"),
        ("f" * 40, "127.0.0.1:7201@17201", "master", "-", "unknown"),
        ("1" * 40, "127.0.0.1:7201@17201", "handshake,master", "-", "disconnected"),
        ("2" * 40, "127.0.0.1:7201@17201", "mystery", "-", "disconnected"),
        ("3" * 40, ":7201@17201", "handshake", "-", "disconnected"),
        ("4" * 40, "999.999.999.999:7201@17201", "handshake", "-", "disconnected"),
        ("5" * 40, "127.0.0.1:99999@99999", "handshake", "-", "disconnected"),
        ("6" * 40, "[2001:db8::1]:7201@17201", "handshake", "-", "disconnected"),
    ]

    for link in unsafe_links:
        report = _m2_resource_report_with_link(link, claimed_errors=1)
        recomputed = validate_and_aggregate_m2_resource_samples(report)
        assert recomputed["status"] == "PASS"
        assert recomputed["metrics"]["cluster_link_errors"] == 1
        assert validate_equal_m2_resource_windows(report, copy.deepcopy(report))["status"] == "FAIL"

        previous, current, recovered, boundary = _complete_bootstrap_transition()
        node_id, address, flags, master_id, link_state = link
        current["non_connected_cluster_links"] = [
            {
                "node_id": node_id,
                "address": address,
                "flags": flags.split(","),
                "master_id": master_id,
                "link_state": link_state,
            }
        ]
        assert _cluster_link_errors_from_raw(
            current,
            expected_gone_client_ports=set(),
            previous_process=previous,
            next_process=recovered,
            formation_boundary_process=boundary,
            allow_initial_membership_transition=True,
            sample_phase="formation_bootstrap",
        ) == 1


def test_m2_expected_gone_link_exclusion_requires_known_disconnected_target() -> None:
    expected_link = {
        "node_id": "a" * 40,
        "address": "127.0.0.1:7101@17101",
        "flags": ["master", "fail?"],
        "master_id": "-",
        "link_state": "disconnected",
    }
    expected_replica_link = {
        **expected_link,
        "flags": ["slave", "fail", "nofailover"],
        "master_id": "b" * 40,
    }
    for link in (expected_link, expected_replica_link):
        assert _cluster_link_errors_from_raw(
            {
                "logical_id": "observer",
                "cluster_link_errors": 0,
                "non_connected_cluster_link_count": 1,
                "non_connected_cluster_links": [link],
            },
            expected_gone_client_ports={7101},
        ) == 0

    unsafe_expected_links = [
        {**expected_link, "link_state": "unknown"},
        {**expected_link, "flags": ["master", "mystery"]},
        {**expected_link, "flags": ["master", "noaddr"]},
        {**expected_link, "flags": ["myself", "master"]},
        {**expected_link, "master_id": "b" * 40},
        {**expected_link, "flags": ["slave"], "master_id": "-"},
        {**expected_link, "flags": ["master", "fail?", "fail"]},
        {**expected_link, "flags": ["master", "nofailover"]},
        {**expected_link, "address": "127.0.0.1:7102@17102", "flags": ["master"]},
    ]
    for link in unsafe_expected_links:
        assert _cluster_link_errors_from_raw(
            {
                "logical_id": "observer",
                "cluster_link_errors": 1,
                "non_connected_cluster_link_count": 1,
                "non_connected_cluster_links": [link],
            },
            expected_gone_client_ports={7101},
        ) == 1


def test_m2_resource_window_rejects_missing_raw_links_and_process_summary_mismatch() -> None:
    report = _m2_resource_report_with_link(
        ("b" * 40, "127.0.0.1:7201@17201", "master", "-", "disconnected"),
        claimed_errors=1,
    )

    missing_raw = copy.deepcopy(report)
    del missing_raw["samples"][0]["nodehosts"][0]["processes"][0]["non_connected_cluster_links"]
    assert validate_and_aggregate_m2_resource_samples(missing_raw)["status"] == "FAIL"

    omitted_row = copy.deepcopy(report)
    process = omitted_row["samples"][0]["nodehosts"][0]["processes"][0]
    process["non_connected_cluster_links"] = []
    process["cluster_link_errors"] = 0
    verdict = validate_and_aggregate_m2_resource_samples(omitted_row)
    assert verdict["status"] == "FAIL"
    assert any("non-connected link count does not match raw links" in error for error in verdict["errors"])

    mismatched = copy.deepcopy(report)
    mismatched["samples"][0]["nodehosts"][0]["processes"][0]["cluster_link_errors"] = 0
    verdict = validate_and_aggregate_m2_resource_samples(mismatched)
    assert verdict["status"] == "FAIL"
    assert any("does not match raw links" in error for error in verdict["errors"])


def test_m2_raw_resource_validator_recomputes_and_rejects_coverage_tampering() -> None:
    clock = _FakeClock()
    sample = 0

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        output = _m2_batch_output(sample)
        sample += 1
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="raw-validation",
        duration_seconds=2,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )
    report["metrics"]["cluster_bus_bytes"] = 999_999
    recomputed = validate_and_aggregate_m2_resource_samples(report)
    assert recomputed["status"] == "PASS"
    assert recomputed["metrics"]["cluster_bus_bytes"] == 900
    assert recomputed["diagnostics"] == {"cluster_bus_messages": 108, "namespace_network_bytes": 600}

    invalid = copy.deepcopy(report)
    invalid["samples"].pop()
    verdict = validate_and_aggregate_m2_resource_samples(invalid)
    assert verdict["status"] == "FAIL"
    assert any("sample count is not exact" in error for error in verdict["errors"])

    invalid = copy.deepcopy(report)
    invalid["samples"][1]["sample_index"] = 0
    assert validate_and_aggregate_m2_resource_samples(invalid)["status"] == "FAIL"

    invalid = copy.deepcopy(report)
    invalid["samples"][1]["status"] = "FAIL"
    assert validate_and_aggregate_m2_resource_samples(invalid)["status"] == "FAIL"

    invalid = copy.deepcopy(report)
    invalid["samples"][1]["nodehosts"].append(copy.deepcopy(invalid["samples"][1]["nodehosts"][0]))
    verdict = validate_and_aggregate_m2_resource_samples(invalid)
    assert verdict["status"] == "FAIL"
    assert any("duplicate nodehost" in error for error in verdict["errors"])

    invalid = copy.deepcopy(report)
    invalid["samples"][1]["nodehosts"][0]["processes"].pop()
    verdict = validate_and_aggregate_m2_resource_samples(invalid)
    assert verdict["status"] == "FAIL"
    assert any("exact owned PID union" in error for error in verdict["errors"])

    invalid = copy.deepcopy(report)
    invalid["samples"][1]["started_at_monotonic_seconds"] += 0.2
    invalid["samples"][1]["ended_at_monotonic_seconds"] += 0.2
    invalid["samples"][1]["schedule_lag_seconds"] = 0.2
    invalid["coverage"]["sample_monotonic_seconds"][1] += 0.2
    verdict = validate_and_aggregate_m2_resource_samples(invalid)
    assert verdict["status"] == "FAIL"
    assert any("schedule lag exceeds" in error for error in verdict["errors"])


def test_m2_fault_resource_window_captures_before_barrier_then_runs_full_window() -> None:
    clock = _FakeClock()
    first_sample = _FirstSampleEvent()
    window_start = _WindowStartEvent(first_sample, clock)
    sample = 0

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        output = _m2_batch_output(sample, gone_pids={101} if sample > 0 else set())
        sample += 1
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="fault-barrier-window",
        duration_seconds=2,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
        expected_gone_processes=_gone_process(),
        first_complete_sample_event=first_sample,
        window_start_event=window_start,
    )

    assert report["status"] == "PASS"
    assert first_sample.was_set is True
    assert window_start.wait_timeouts == [30]
    assert report["coverage"]["expected_sample_count"] == 4
    assert report["coverage"]["observed_sample_count"] == 4
    assert [sample["sample_index"] for sample in report["samples"]] == [0, 1, 2, 3]
    assert [sample["sample_phase"] for sample in report["samples"]] == [
        "pre_barrier",
        "window",
        "window",
        "window",
    ]
    assert report["samples"][0]["scheduled_offset_seconds"] == -7.0
    assert report["samples"][-1]["started_at_monotonic_seconds"] == 109.0
    recomputed = validate_and_aggregate_m2_resource_samples(report)
    assert recomputed["status"] == "PASS"
    assert recomputed["fault_target_capture"] == {
        "expected_gone_processes": _gone_process(),
        "observed_gone_processes": _gone_process(),
        "captured_before_gone_processes": _gone_process(),
        "binding_status": "PASS",
    }

    invalid = copy.deepcopy(report)
    invalid["fault_target_capture"]["bindings"][0]["nodehost_id"] = "unowned-nodehost"
    verdict = validate_and_aggregate_m2_resource_samples(invalid)
    assert verdict["status"] == "FAIL"
    assert any("does not match raw process identity" in error for error in verdict["errors"])


def test_m2_resource_window_fails_closed_when_pid_sample_is_missing() -> None:
    clock = _FakeClock()

    def command(args, *, timeout, check):
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout="META\t100\t4096\nPID\t101\t10\t2\t5\t4\t2\nNET\t1000\t2000\n",
            stderr="",
        )

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="incomplete",
        duration_seconds=1,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )

    assert report["status"] == "FAIL"
    assert report["coverage"]["complete"] is False
    assert report["metrics"]["peak_rss_bytes"] == "MISSING"
    assert any("pids do not match explicit target" in error for error in report["errors"])


def test_m2_resource_window_rejects_container_with_wrong_ownership() -> None:
    calls: list[list[str]] = []

    def command(args, *, timeout, check):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=_owned_inspect(run_id="another-run"), stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="ownership",
        duration_seconds=1,
        interval_seconds=1,
        command=command,
    )

    assert report["status"] == "FAIL"
    assert report["coverage"]["expected_sample_count"] == 2
    assert all(args[0] == "inspect" for args in calls)
    assert all(args[1] == "cid-a" for args in calls)
    assert "not owned" in report["errors"][0]


def test_m2_resource_window_rejects_prefix_matching_replacement_container() -> None:
    inspected = json.loads(_owned_inspect())[0]
    inspected["Id"] = "cid-a-replacement"

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="container-identity",
        duration_seconds=1,
        interval_seconds=1,
        command=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([inspected]),
            stderr="",
        ),
    )

    assert report["status"] == "FAIL"
    assert "container id ownership mismatch" in report["errors"][0]


def test_m2_resource_window_rejects_runtime_container_rename() -> None:
    inspected = json.loads(_owned_inspect())[0]
    inspected["Name"] = "/renamed-owned-a"

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="container-identity",
        duration_seconds=1,
        interval_seconds=1,
        command=lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps([inspected]),
            stderr="",
        ),
    )

    assert report["status"] == "FAIL"
    assert "container name ownership mismatch" in report["errors"][0]


def test_m2_resource_window_rejects_one_container_id_with_multiple_names() -> None:
    state = copy.deepcopy(_m2_runtime_state())
    state["nodehosts"].append(
        {
            "nodehost_id": "nodehost-b",
            "container_id": "cid-a",
            "container_name": "owned-b",
        }
    )
    state["nodes"].append(
        {
            "logical_id": "node-3",
            "nodehost_id": "nodehost-b",
            "container_id": "cid-a",
            "nodehost_container_name": "owned-b",
            "pid": 103,
            "client_port": 7103,
        }
    )

    report = collect_m2_resource_window(
        state,
        window_name="duplicate-container-id",
        duration_seconds=1,
        interval_seconds=1,
        command=lambda *_args, **_kwargs: pytest.fail("Docker must not run"),
    )

    assert report["status"] == "FAIL"
    assert "duplicate nodehost ownership target" in report["errors"][0]


def test_m2_resource_window_rejects_duplicate_logical_process_identity() -> None:
    state = copy.deepcopy(_m2_runtime_state())
    state["nodes"][1]["logical_id"] = state["nodes"][0]["logical_id"]

    report = collect_m2_resource_window(
        state,
        window_name="duplicate-logical-id",
        duration_seconds=1,
        interval_seconds=1,
        command=lambda *_args, **_kwargs: pytest.fail("Docker must not run"),
    )

    assert report["status"] == "FAIL"
    assert "duplicate owned logical_id" in report["errors"][0]


def test_m2_resource_window_requires_fixed_interval_contract() -> None:
    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="bad-window",
        duration_seconds=2,
        interval_seconds=0.75,
        command=lambda *args, **kwargs: None,
    )

    assert report["status"] == "FAIL"
    assert "exact multiple" in report["errors"][0]


def test_m2_resource_window_fails_closed_when_cluster_counter_is_missing() -> None:
    clock = _FakeClock()

    def command(args, *, timeout, check):
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        return SimpleNamespace(returncode=0, stdout=_m2_batch_output(0, omitted_cluster_pids={102}), stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="missing-cluster-counter",
        duration_seconds=1,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )

    assert report["status"] == "FAIL"
    assert any("cluster samples do not match live proc targets" in error for error in report["errors"])


def test_m2_resource_window_fails_closed_when_cluster_counter_decreases() -> None:
    clock = _FakeClock()
    sample = 0

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        output = _m2_batch_output(sample, rollback_pid=102)
        sample += 1
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="counter-rollback",
        duration_seconds=1,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )

    assert report["status"] == "FAIL"
    assert report["metrics"]["cluster_bus_bytes"] == "MISSING"
    assert any("cluster_stats_bytes_sent decreased" in error for error in report["errors"])


def test_m2_resource_window_requires_directional_links_for_every_live_process() -> None:
    clock = _FakeClock()

    def command(args, *, timeout, check):
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        return SimpleNamespace(
            returncode=0,
            stdout=_m2_batch_output(
                0,
                directional_cluster_links={101: []},
            ),
            stderr="",
        )

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="missing-directional-links",
        duration_seconds=1,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )

    assert report["status"] == "FAIL"
    assert any(
        "directional cluster link observations do not match live proc targets"
        in error
        for error in report["errors"]
    )


def test_m2_resource_window_allows_only_captured_bound_expected_gone_process() -> None:
    clock = _FakeClock()
    sample = 0

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        output = _m2_batch_output(sample, gone_pids={101} if sample > 0 else set())
        sample += 1
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="fault-window",
        duration_seconds=2,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
        expected_gone_processes=_gone_process(),
    )

    assert report["status"] == "PASS"
    assert report["metrics"]["cluster_bus_bytes"] == 600
    assert report["metrics"]["cpu_time_seconds"] == 0.2
    assert report["metrics"]["peak_rss_bytes"] == 11 * 4096
    assert report["fault_target_capture"] == {
        "expected_gone_processes": _gone_process(),
        "observed_gone_processes": _gone_process(),
        "captured_before_gone_processes": _gone_process(),
        "binding_status": "PASS",
        "bindings": [
            {
                "pid": 101,
                "logical_id": "node-1",
                "client_port": 7101,
                "nodehost_id": "nodehost-a",
                "container_id": "cid-a",
                "ownership_id": "m2-run-1",
            }
        ],
    }


def test_m2_resource_window_rejects_unexpected_or_uncaptured_gone_process() -> None:
    for expected_gone_processes, first_sample_gone in (([], False), (_gone_process(), True)):
        clock = _FakeClock()
        sample = 0

        def command(args, *, timeout, check):
            nonlocal sample
            if args[0] == "inspect":
                return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
            gone = {101} if first_sample_gone or sample > 0 else set()
            output = _m2_batch_output(sample, gone_pids=gone)
            sample += 1
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        report = collect_m2_resource_window(
            _m2_runtime_state(),
            window_name="invalid-gone",
            duration_seconds=1,
            interval_seconds=1,
            command=command,
            monotonic_clock=clock.monotonic,
            wall_clock=clock.wall,
            sleep=clock.sleep,
            expected_gone_processes=expected_gone_processes,
        )

        assert report["status"] == "FAIL"
        assert any("disappeared" in error for error in report["errors"])


def test_m2_resource_window_declared_gone_process_must_disappear() -> None:
    clock = _FakeClock()

    def command(args, *, timeout, check):
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        return SimpleNamespace(returncode=0, stdout=_m2_batch_output(0), stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="missing-fault-effect",
        duration_seconds=1,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
        expected_gone_processes=_gone_process(),
    )

    assert report["status"] == "FAIL"
    assert any("expected-gone process identity set" in error for error in report["errors"])


def test_m2_resource_window_rejects_unowned_expected_gone_process() -> None:
    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="unbound-fault-target",
        duration_seconds=1,
        interval_seconds=1,
        command=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must fail before Docker")),
        expected_gone_processes=[
            {"nodehost_id": "nodehost-a", "container_id": "cid-a", "pid": 999}
        ],
    )

    assert report["status"] == "FAIL"
    assert any("not bound to an owned fault target" in error for error in report["errors"])


def test_m2_resource_window_rejects_pid_only_fault_identity() -> None:
    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="unsafe-fault-target",
        duration_seconds=1,
        interval_seconds=1,
        command=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must fail before Docker")),
        expected_gone_pids={101},
    )

    assert report["status"] == "FAIL"
    assert any("unsafe across PID namespaces" in error for error in report["errors"])


def test_m2_resource_window_binds_same_pid_in_different_containers() -> None:
    state = {
        "capability_id": "m2_performance",
        "runtime": {"run_id": "m2-run-1"},
        "nodehosts": [
            {"nodehost_id": "nodehost-a", "container_id": "cid-a", "container_name": "owned-a"},
            {"nodehost_id": "nodehost-b", "container_id": "cid-b", "container_name": "owned-b"},
        ],
        "nodes": [
            {
                "logical_id": "node-a",
                "nodehost_id": "nodehost-a",
                "container_id": "cid-a",
                "nodehost_container_name": "owned-a",
                "pid": 101,
                "client_port": 7101,
            },
            {
                "logical_id": "node-b",
                "nodehost_id": "nodehost-b",
                "container_id": "cid-b",
                "nodehost_container_name": "owned-b",
                "pid": 101,
                "client_port": 7201,
            },
        ],
    }
    clock = _FakeClock()
    samples = {"cid-a": 0, "cid-b": 0}

    def command(args, *, timeout, check):
        container = args[1]
        suffix = container[-1]
        if args[0] == "inspect":
            inspected = json.loads(_owned_inspect())[0]
            inspected["Id"] = f"cid-{suffix}"
            inspected["Name"] = f"/owned-{suffix}"
            return SimpleNamespace(returncode=0, stdout=json.dumps([inspected]), stderr="")
        sample = samples[container]
        samples[container] += 1
        port = 7101 if container == "cid-a" else 7201
        rows = ["META\t100\t4096"]
        if container == "cid-a" and sample > 0:
            rows.append(f"GONE\t101\t{port}")
        else:
            rows.extend(
                [
                    f"PID\t101\t{10 + sample}\t2\t5\t4\t2",
                    f"CLUSTER\t101\t{port}\t{1000 + sample * 100}\t{500 + sample * 50}"
                    f"\t{100 + sample * 10}\t{80 + sample * 8}\t0\t2\t0\t0",
                    "CLINKS\t101\t[]",
                ]
            )
        rows.append(f"NET\t{1000 + sample * 100}\t{2000 + sample * 200}")
        return SimpleNamespace(returncode=0, stdout="\n".join(rows), stderr="")

    expected = [{"nodehost_id": "nodehost-a", "container_id": "cid-a", "pid": 101}]
    report = collect_m2_resource_window(
        state,
        window_name="pid-namespace-binding",
        duration_seconds=2,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
        expected_gone_processes=expected,
    )

    assert report["status"] == "PASS"
    assert report["fault_target_capture"]["expected_gone_processes"] == expected
    assert report["fault_target_capture"]["observed_gone_processes"] == expected
    assert validate_and_aggregate_m2_resource_samples(report)["status"] == "PASS"


def _complete_m2_resource_report(*, final_sample_delay: float = 0.0) -> dict:
    clock = _FakeClock()
    sample = 0

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        output = _m2_batch_output(sample)
        if sample == 2:
            clock.value += final_sample_delay
        sample += 1
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    return collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="comparison",
        duration_seconds=2,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )


def test_m2_resource_window_comparison_requires_equal_complete_windows() -> None:
    baseline = _complete_m2_resource_report()
    candidate = copy.deepcopy(baseline)
    assert validate_equal_m2_resource_windows(baseline, candidate)["status"] == "PASS"

    candidate["duration_seconds"] = 1.0
    assert validate_equal_m2_resource_windows(baseline, candidate)["status"] == "FAIL"

    candidate = copy.deepcopy(baseline)
    candidate["metrics"]["fd_count"] = "MISSING"
    verdict = validate_equal_m2_resource_windows(baseline, candidate)
    assert verdict["status"] == "FAIL"
    assert any("candidate metric fd_count" in error for error in verdict["errors"])

    candidate = copy.deepcopy(baseline)
    candidate["metrics"]["cluster_link_errors"] = 1
    verdict = validate_equal_m2_resource_windows(baseline, candidate)
    assert verdict["status"] == "FAIL"
    assert any("candidate metric cluster_link_errors must be zero" in error for error in verdict["errors"])

    candidate = _complete_m2_resource_report(final_sample_delay=0.2)
    verdict = validate_equal_m2_resource_windows(baseline, candidate)
    assert verdict["status"] == "FAIL"
    assert any("sampling_envelope_span_seconds" in error for error in verdict["errors"])


def test_m2_resource_window_comparison_allows_unequal_bounded_collection_time() -> None:
    baseline = _complete_m2_resource_report()
    candidate = copy.deepcopy(baseline)
    candidate["samples"][1]["ended_at_monotonic_seconds"] += 0.8
    candidate["coverage"]["max_sample_collection_seconds"] = 0.8

    verdict = validate_equal_m2_resource_windows(baseline, candidate)

    assert verdict["status"] == "PASS"


def test_m2_resource_window_comparison_allows_unequal_bounded_schedule_lag() -> None:
    baseline = _complete_m2_resource_report()
    candidate = copy.deepcopy(baseline)
    candidate["samples"][1]["started_at_monotonic_seconds"] += 0.05
    candidate["samples"][1]["ended_at_monotonic_seconds"] += 0.05
    candidate["samples"][1]["schedule_lag_seconds"] = 0.05
    candidate["coverage"]["sample_monotonic_seconds"][1] += 0.05
    candidate["coverage"]["max_schedule_lag_seconds"] = 0.05

    verdict = validate_equal_m2_resource_windows(baseline, candidate)

    assert verdict["status"] == "PASS"


def test_m2_resource_window_rejects_sampling_overrun_and_schedule_lag() -> None:
    clock = _FakeClock()
    sample = 0

    def command(args, *, timeout, check):
        nonlocal sample
        if args[0] == "inspect":
            return SimpleNamespace(returncode=0, stdout=_owned_inspect(), stderr="")
        output = _m2_batch_output(sample)
        sample += 1
        clock.value += 1.2
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    report = collect_m2_resource_window(
        _m2_runtime_state(),
        window_name="overrun",
        duration_seconds=2,
        interval_seconds=1,
        command=command,
        monotonic_clock=clock.monotonic,
        wall_clock=clock.wall,
        sleep=clock.sleep,
    )

    assert report["status"] == "FAIL"
    assert report["coverage"]["complete"] is False
    assert any("schedule lag exceeds" in error for error in report["errors"])
    assert any("overran its fixed interval" in error for error in report["errors"])
