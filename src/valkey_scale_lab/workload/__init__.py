from __future__ import annotations

import time
from typing import Any, Callable

from valkey_scale_lab.metrics import TelemetryRun, workload_metrics

CANONICAL_WINDOWS = ["baseline", "pre_event", "event", "recovery", "post_recovery", "all_run"]


def run_windowed_workload(
    *,
    telemetry: TelemetryRun,
    command: Callable[..., str],
    requested_qps: float,
    operations_per_window: int = 6,
    sleep_seconds: float = 0.02,
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
        for op_index in range(operations_per_window):
            op_type = "SET" if op_index % 3 == 0 else "GET"
            key = f"{{vslab-p16}}:{window_name}:{op_index % 3}"
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
        measured_windows.append(
            {
                "window_name": window_name,
                "start_event_id": start_event["event_id"],
                "end_event_id": end_event["event_id"],
                "status": "PASS" if not errors else "FAIL",
                "metrics": metrics,
            }
        )
        metric_rows.extend(_workload_metric_rows(telemetry, window_name, metrics))
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
    measured_windows.append(
        {
            "window_name": "all_run",
            "start_event_id": all_start_event["event_id"],
            "end_event_id": all_end_event["event_id"],
            "status": "PASS" if not all_errors else "FAIL",
            "metrics": all_metrics,
        }
    )
    metric_rows.extend(_workload_metric_rows(telemetry, "all_run", all_metrics))
    return events, metric_rows, measured_windows


def _workload_metric_rows(telemetry: TelemetryRun, window_name: str, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    missing_reasons = metrics.get("missing_reasons", {})
    for name, value in metrics.items():
        if name == "missing_reasons":
            continue
        rows.append(
            telemetry.metric(
                source_type="workload",
                source_id=window_name,
                metric_name=name,
                metric_value=value,
                metric_unit="count" if name.endswith("_count") or name.endswith("_ops") or name == "sample_count" else "ms" if name.startswith("latency_") else "ratio" if name == "error_rate" else "ops_per_second" if name.endswith("qps") else "seconds" if name == "duration_seconds" else "value",
                labels={"window_name": window_name},
                missing_reason_text=str(missing_reasons.get(name, "")),
            )
        )
    return rows
