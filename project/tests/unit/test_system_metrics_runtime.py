from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.metrics.m2_resource import (
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
                "Id": "cid-a-full",
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
) -> str:
    gone = gone_pids or set()
    omitted = omitted_cluster_pids or set()
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
            f"\t{received_messages + direction * sample * 8 * scale}\t0\t2\t0"
        )
    rows.append(f"NET\t{1000 + sample * 100}\t{2000 + sample * 200}")
    return "\n".join(rows)


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
    assert all(args[-2:] == ["101:7101", "102:7102"] for args in exec_calls)
    assert all("/proc/$pid/stat" in args[4] and "/proc/$pid/statm" in args[4] for args in exec_calls)
    assert all("/proc/$pid/fd" in args[4] and "/proc/net/dev" in args[4] for args in exec_calls)
    assert all("valkey-cli --raw -p \"$port\" CLUSTER INFO" in args[4] for args in exec_calls)
    assert all("valkey-cli --raw -p \"$port\" CLUSTER NODES" in args[4] for args in exec_calls)
    assert report["diagnostics"] == {"cluster_bus_messages": 108, "namespace_network_bytes": 600}
    assert "exact Valkey 9.1 per-node CLUSTER INFO" in report["metric_provenance"]["cluster_bus_bytes"]
    assert "no namespace-traffic fallback" in report["metric_provenance"]["cluster_bus_bytes"]
    assert "diagnostic only" in report["diagnostic_provenance"]["namespace_network_bytes"]


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
    assert "not owned" in report["errors"][0]


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
    samples = {"owned-a": 0, "owned-b": 0}

    def command(args, *, timeout, check):
        container = args[1]
        suffix = container[-1]
        if args[0] == "inspect":
            inspected = json.loads(_owned_inspect())[0]
            inspected["Id"] = f"cid-{suffix}-full"
            return SimpleNamespace(returncode=0, stdout=json.dumps([inspected]), stderr="")
        sample = samples[container]
        samples[container] += 1
        port = 7101 if container == "owned-a" else 7201
        rows = ["META\t100\t4096"]
        if container == "owned-a" and sample > 0:
            rows.append(f"GONE\t101\t{port}")
        else:
            rows.extend(
                [
                    f"PID\t101\t{10 + sample}\t2\t5\t4\t2",
                    f"CLUSTER\t101\t{port}\t{1000 + sample * 100}\t{500 + sample * 50}"
                    f"\t{100 + sample * 10}\t{80 + sample * 8}\t0\t2\t0",
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
