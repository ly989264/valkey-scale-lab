from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from valkey_scale_lab.metrics import TelemetryRun, workload_metrics

CANONICAL_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]
BENCHMARK_PROFILES = ("smoke", "uniform", "hotspot", "mixed_rw", "write_heavy", "read_heavy")
SLOT_COUNT = 16384


@dataclass(frozen=True)
class WorkloadProfile:
    name: str
    read_ratio: float
    write_ratio: float
    target_qps: float
    keyspace: int
    value_size: int = 16
    hash_slot_distribution: str = "full_slot"
    connections: int = 1
    pipeline: int = 1
    timeout_ms: int = 1000


def build_workload_profile(name: str, config: dict[str, Any] | None = None) -> WorkloadProfile:
    workload = dict(config or {})
    if name not in BENCHMARK_PROFILES:
        raise ValueError(f"unsupported workload profile {name!r}")
    read_ratio = float(workload.get("read_ratio", _default_read_ratio(name)))
    write_ratio = float(workload.get("write_ratio", round(1.0 - read_ratio, 6)))
    if abs((read_ratio + write_ratio) - 1.0) > 0.000001:
        raise ValueError(f"workload ratios must sum to 1.0, got read={read_ratio} write={write_ratio}")
    target_qps = float(workload.get("target_qps", workload.get("uniform_qps", 0) or 12.0))
    distribution = str(workload.get("hash_slot_distribution", "single_tag" if name == "smoke" else "full_slot"))
    return WorkloadProfile(
        name=name,
        read_ratio=read_ratio,
        write_ratio=write_ratio,
        target_qps=max(target_qps, 0.0),
        keyspace=max(int(workload.get("keyspace", 256)), 1),
        value_size=max(int(workload.get("value_size", 16)), 1),
        hash_slot_distribution=distribution,
        connections=max(int(workload.get("connections", 1)), 1),
        pipeline=max(int(workload.get("pipeline", 1)), 1),
        timeout_ms=max(int(workload.get("timeout_ms", 1000)), 1),
    )


def _default_read_ratio(name: str) -> float:
    return {
        "smoke": 0.8,
        "uniform": 0.8,
        "hotspot": 0.8,
        "mixed_rw": 0.5,
        "write_heavy": 0.2,
        "read_heavy": 0.95,
    }[name]


def slot_for_key(key: str) -> int:
    hashtag = _hash_tag(key)
    crc = 0
    for byte in hashtag.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc % SLOT_COUNT


def _hash_tag(key: str) -> str:
    start = key.find("{")
    if start >= 0:
        end = key.find("}", start + 1)
        if end > start + 1:
            return key[start + 1 : end]
    return key


def generate_benchmark_keys(
    *,
    profile: str = "uniform",
    keyspace: int = 256,
    hash_slot_distribution: str = "full_slot",
    prefix: str = "vslab",
) -> tuple[list[str], dict[str, Any]]:
    requested_full = hash_slot_distribution == "full_slot"
    if requested_full:
        keys = _keys_for_all_slots(prefix=prefix)
    elif hash_slot_distribution == "single_tag":
        keys = [f"{{{prefix}-{profile}}}:key:{idx}" for idx in range(max(keyspace, 1))]
    elif hash_slot_distribution == "hotspot" or profile == "hotspot":
        hot = [f"{prefix}:hotspot:{idx}:0" for idx in range(max(1, keyspace // 20))]
        keys = hot + [f"{prefix}:cold:{idx}" for idx in range(max(keyspace - len(hot), 1))]
    else:
        keys = [f"{prefix}:{profile}:{idx}" for idx in range(max(keyspace, 1))]
    return keys, key_slot_coverage(keys, distribution=hash_slot_distribution, full_slot_requested=requested_full)


def _keys_for_all_slots(*, prefix: str) -> list[str]:
    slots: dict[int, str] = {}
    idx = 0
    while len(slots) < SLOT_COUNT:
        key = f"{prefix}:slot:{idx}"
        slot = slot_for_key(key)
        slots.setdefault(slot, key)
        idx += 1
    return [slots[slot] for slot in range(SLOT_COUNT)]


def key_slot_coverage(keys: Iterable[str], *, distribution: str, full_slot_requested: bool) -> dict[str, Any]:
    slots = sorted({slot_for_key(key) for key in keys})
    return {
        "hash_slot_distribution": distribution,
        "slot_count_observed": len(slots),
        "slot_sample": slots[:16],
        "full_slot_requested": full_slot_requested,
        "full_slot_covered": len(slots) == SLOT_COUNT if full_slot_requested else False,
        "fixed_hash_tag_only": len(slots) == 1,
    }


def run_benchmark_workload(
    *,
    telemetry: TelemetryRun,
    command: Callable[..., str],
    profile_names: list[str] | None = None,
    workload_config: dict[str, Any] | None = None,
    operations_per_window: int = 6,
    sleep_seconds: float = 0.02,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    profile_names = profile_names or ["smoke"]
    workload_config = workload_config or {}
    coverage_by_profile: dict[str, Any] = {}
    for profile_name in profile_names:
        profile = build_workload_profile(profile_name, workload_config)
        keys, coverage = generate_benchmark_keys(
            profile=profile.name,
            keyspace=profile.keyspace,
            hash_slot_distribution=profile.hash_slot_distribution,
            prefix=f"vslab-{telemetry.run_id}-{profile.name}",
        )
        coverage_by_profile[profile.name] = coverage
        selected_keys = keys[: max(operations_per_window, 1)]
        row_events, row_metrics, row_windows = run_windowed_workload(
            telemetry=telemetry,
            command=command,
            requested_qps=profile.target_qps,
            operations_per_window=operations_per_window,
            sleep_seconds=sleep_seconds,
            keys=selected_keys,
            profile=profile,
            key_slot_coverage_obj=coverage,
        )
        events.extend(row_events)
        metric_rows.extend(row_metrics)
        windows.extend(row_windows)
    return {
        "events": events,
        "metric_rows": metric_rows,
        "windows": windows,
        "profiles_covered": profile_names,
        "hash_slot_coverage": coverage_by_profile,
        "workload_mode": "benchmark" if any(name != "smoke" for name in profile_names) else "smoke",
    }


def run_windowed_workload(
    *,
    telemetry: TelemetryRun,
    command: Callable[..., str],
    requested_qps: float,
    operations_per_window: int = 6,
    sleep_seconds: float = 0.02,
    keys: list[str] | None = None,
    profile: WorkloadProfile | None = None,
    key_slot_coverage_obj: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    measured_windows: list[dict[str, Any]] = []
    all_latencies: list[float] = []
    all_errors: list[str] = []
    all_started = time.monotonic()
    all_start_event = telemetry.event(
        "workload_window_started",
        subject_type="workload_window",
        subject_id="all_run",
        message="All-run workload window started.",
        metadata={"window_name": "all_run"},
    )
    events.append(all_start_event)

    for window_name in CANONICAL_WINDOWS[:-1]:
        start_event = telemetry.event(
            "workload_window_started",
            subject_type="workload_window",
            subject_id=window_name,
            message=f"{window_name} workload window started.",
            metadata={"window_name": window_name},
        )
        events.append(start_event)
        window_started = time.monotonic()
        latencies_ms: list[float] = []
        errors: list[str] = []
        selected_keys = keys or [f"{{vslab-p16}}:{window_name}:{idx}" for idx in range(max(operations_per_window, 1))]
        for op_index in range(operations_per_window):
            op_type = "SET" if op_index % 3 == 0 else "GET"
            if profile is not None:
                write_stride = max(int(round(1.0 / max(profile.write_ratio, 0.000001))), 1)
                op_type = "SET" if op_index % write_stride == 0 else "GET"
            key = selected_keys[op_index % len(selected_keys)]
            value = f"value-{window_name}-{op_index}"
            op_started = time.monotonic()
            try:
                if op_type == "SET":
                    result = command("SET", key, value, timeout=10)
                    if str(result).upper() != "OK":
                        errors.append(f"SET unexpected result {result!r}")
                    else:
                        latencies_ms.append((time.monotonic() - op_started) * 1000.0)
                else:
                    _ = command("GET", key, timeout=10)
                    latencies_ms.append((time.monotonic() - op_started) * 1000.0)
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        duration = max(time.monotonic() - window_started, 0.000001)
        metrics = workload_metrics(
            requested_qps=requested_qps,
            duration_seconds=duration,
            latencies_ms=latencies_ms,
            error_texts=errors,
        )
        end_event = telemetry.event(
            "workload_window_finished",
            subject_type="workload_window",
            subject_id=window_name,
            message=f"{window_name} workload window finished.",
            metadata={"window_name": window_name, "sample_count": metrics["sample_count"]},
        )
        events.append(end_event)
        metrics["window_start_event_id"] = start_event["event_id"]
        metrics["window_end_event_id"] = end_event["event_id"]
        measured_windows.append(
            _benchmark_window(
                {
                "window_name": window_name,
                "start_event_id": start_event["event_id"],
                "end_event_id": end_event["event_id"],
                "window_start_event_id": start_event["event_id"],
                "window_end_event_id": end_event["event_id"],
                "status": "PASS" if not errors else "FAIL",
                "metrics": metrics,
                },
                profile=profile,
                key_slot_coverage_obj=key_slot_coverage_obj,
            )
        )
        metric_rows.extend(_workload_metric_rows(telemetry, f"{profile.name}:{window_name}" if profile else window_name, metrics, profile=profile, window_name=window_name))
        all_latencies.extend(latencies_ms)
        all_errors.extend(errors)

    all_duration = max(time.monotonic() - all_started, 0.000001)
    all_metrics = workload_metrics(
        requested_qps=requested_qps,
        duration_seconds=all_duration,
        latencies_ms=all_latencies,
        error_texts=all_errors,
    )
    all_end_event = telemetry.event(
        "workload_window_finished",
        subject_type="workload_window",
        subject_id="all_run",
        message="All-run workload window finished.",
        metadata={"window_name": "all_run", "sample_count": all_metrics["sample_count"]},
    )
    events.append(all_end_event)
    all_metrics["window_start_event_id"] = all_start_event["event_id"]
    all_metrics["window_end_event_id"] = all_end_event["event_id"]
    measured_windows.append(
        _benchmark_window(
            {
            "window_name": "all_run",
            "start_event_id": all_start_event["event_id"],
            "end_event_id": all_end_event["event_id"],
            "window_start_event_id": all_start_event["event_id"],
            "window_end_event_id": all_end_event["event_id"],
            "status": "PASS" if not all_errors else "FAIL",
            "metrics": all_metrics,
            },
            profile=profile,
            key_slot_coverage_obj=key_slot_coverage_obj,
        )
    )
    metric_rows.extend(_workload_metric_rows(telemetry, f"{profile.name}:all_run" if profile else "all_run", all_metrics, profile=profile, window_name="all_run"))
    return events, metric_rows, measured_windows


def _benchmark_window(row: dict[str, Any], *, profile: WorkloadProfile | None, key_slot_coverage_obj: dict[str, Any] | None) -> dict[str, Any]:
    if profile is None:
        return row
    row.update(
        {
            "profile": profile.name,
            "workload_mode": "smoke" if profile.name == "smoke" else "benchmark",
            "hash_slot_distribution": profile.hash_slot_distribution,
            "key_slot_coverage": key_slot_coverage_obj or {},
            "config": {
                "target_qps": profile.target_qps,
                "read_ratio": profile.read_ratio,
                "write_ratio": profile.write_ratio,
                "connections": profile.connections,
                "pipeline": profile.pipeline,
                "keyspace": profile.keyspace,
                "value_size": profile.value_size,
                "timeout_ms": profile.timeout_ms,
            },
        }
    )
    return row


def _workload_metric_rows(telemetry: TelemetryRun, source_id: str, metrics: dict[str, Any], *, profile: WorkloadProfile | None = None, window_name: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    missing_reasons = metrics.get("missing_reasons", {})
    for name, value in metrics.items():
        if name == "missing_reasons":
            continue
        rows.append(
            telemetry.metric(
                source_type="workload",
                source_id=source_id,
                metric_name=name,
                metric_value=value,
                metric_unit="count" if name.endswith("_count") or name.endswith("_ops") or name == "sample_count" else "ms" if name.startswith("latency_") else "ratio" if name == "error_rate" else "ops_per_second" if name.endswith("qps") else "seconds" if name == "duration_seconds" else "value",
                labels={"window_name": window_name or source_id, "profile": profile.name if profile else "legacy"},
                missing_reason_text=str(missing_reasons.get(name, "")),
            )
        )
    return rows
