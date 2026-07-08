from __future__ import annotations

from valkey_scale_lab.metrics import TelemetryRun
from valkey_scale_lab.workload import BENCHMARK_PROFILES, build_workload_profile, run_benchmark_workload


def test_profiles_normalize_ratios() -> None:
    for profile in BENCHMARK_PROFILES:
        normalized = build_workload_profile(profile, {"target_qps": 5})
        assert round(normalized.read_ratio + normalized.write_ratio, 6) == 1.0


def test_invalid_ratio_rejected() -> None:
    try:
        build_workload_profile("uniform", {"read_ratio": 0.7, "write_ratio": 0.7})
    except ValueError as exc:
        assert "sum to 1.0" in str(exc)
    else:
        raise AssertionError("invalid workload ratio should be rejected")


def test_benchmark_runner_emits_metrics_and_windows_for_every_profile() -> None:
    telemetry = TelemetryRun(phase_id="M1-S05", scenario_name="unit", run_id="unit-run")

    def command(*args: object, timeout: int = 10) -> str:
        return "OK" if args and args[0] == "SET" else "value"

    result = run_benchmark_workload(
        telemetry=telemetry,
        command=command,
        profile_names=list(BENCHMARK_PROFILES),
        workload_config={"target_qps": 6, "keyspace": 32, "hash_slot_distribution": "multi_slot"},
        operations_per_window=2,
        sleep_seconds=0,
    )

    assert result["profiles_covered"] == list(BENCHMARK_PROFILES)
    assert result["events"]
    assert result["metric_rows"]
    assert len(result["windows"]) == len(BENCHMARK_PROFILES) * 6
    for row in result["windows"]:
        metrics = row["metrics"]
        assert "throughput_ratio" in metrics
        assert "moved_count" in metrics
        assert "tryagain_count" in metrics
        assert row["key_slot_coverage"]["fixed_hash_tag_only"] is False


def test_benchmark_runner_classifies_failure_counts() -> None:
    telemetry = TelemetryRun(phase_id="M1-S05", scenario_name="unit", run_id="unit-run-failure")

    def command(*args: object, timeout: int = 10) -> str:
        raise RuntimeError("MOVED 1234 127.0.0.1:7000")

    result = run_benchmark_workload(
        telemetry=telemetry,
        command=command,
        profile_names=["uniform"],
        workload_config={"target_qps": 3, "hash_slot_distribution": "multi_slot"},
        operations_per_window=1,
        sleep_seconds=0,
    )

    assert any(row["status"] == "FAIL" for row in result["windows"])
    assert any(row["metrics"]["moved_count"] > 0 for row in result["windows"])
