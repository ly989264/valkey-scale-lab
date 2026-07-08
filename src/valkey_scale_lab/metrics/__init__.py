from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MISSING = "MISSING"
SKIPPED_WITH_REASON = "SKIPPED_WITH_REASON"
UNSUPPORTED_WITH_REASON = "UNSUPPORTED_WITH_REASON"


def missing_reason(status: str, reason: str) -> dict[str, str]:
    if status not in {MISSING, SKIPPED_WITH_REASON, UNSUPPORTED_WITH_REASON}:
        raise ValueError(f"{status} is not a missing-data status")
    if not reason:
        raise ValueError(f"{status} requires a reason")
    return {"status": status, "reason": reason}


def metric_missing(reason: str) -> str:
    if not reason:
        raise ValueError("MISSING metric requires a reason")
    return MISSING


@dataclass
class TelemetryRun:
    phase_id: str
    scenario_name: str
    run_id: str
    sample_id: str = "sample-0001"
    stage_id: str | None = None
    coverage_id: str = "telemetry.collector_smoke"
    scale: int | None = None
    node_count: int | None = None
    clock_source: str = "wall_time_unix_ms_and_python_monotonic"
    start_wall_unix_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    start_monotonic: float = field(default_factory=time.monotonic)
    _event_counter: int = 0

    def __post_init__(self) -> None:
        if self.stage_id is None:
            self.stage_id = self.phase_id

    def now_unix_ms(self) -> int:
        return int(time.time() * 1000)

    def monotonic_ms(self) -> float:
        return round((time.monotonic() - self.start_monotonic) * 1000.0, 6)

    def event(
        self,
        event_type: str,
        *,
        severity: str = "INFO",
        subject_type: str = "harness",
        subject_id: str = "P16_QUANT_TELEMETRY_UNIFICATION",
        operation_id: str = SKIPPED_WITH_REASON,
        fault_id: str = SKIPPED_WITH_REASON,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._event_counter += 1
        return {
            "schema_version": "v1",
            "run_id": self.run_id,
            "phase_id": self.phase_id,
            "stage_id": self.stage_id,
            "coverage_id": self.coverage_id,
            "scale": self.scale if self.scale is not None else MISSING,
            "node_count": self.node_count if self.node_count is not None else MISSING,
            "scenario_name": self.scenario_name,
            "sample_id": self.sample_id,
            "event_id": f"evt-{self._event_counter:04d}-{event_type}",
            "event_type": event_type,
            "timestamp_unix_ms": self.now_unix_ms(),
            "monotonic_ms": self.monotonic_ms(),
            "clock_source": self.clock_source,
            "severity": severity,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "operation_id": operation_id,
            "fault_id": fault_id,
            "message": message,
            "metadata": metadata or {},
        }

    def metric(
        self,
        *,
        source_type: str,
        source_id: str,
        metric_name: str,
        metric_value: int | float | str | bool,
        metric_unit: str,
        labels: dict[str, Any] | None = None,
        missing_reason_text: str = "",
    ) -> dict[str, Any]:
        if metric_value == MISSING and not missing_reason_text:
            raise ValueError(f"{metric_name} MISSING metric requires missing_reason")
        return {
            "schema_version": "v1",
            "run_id": self.run_id,
            "phase_id": self.phase_id,
            "stage_id": self.stage_id,
            "coverage_id": self.coverage_id,
            "scale": self.scale if self.scale is not None else MISSING,
            "node_count": self.node_count if self.node_count is not None else MISSING,
            "scenario_name": self.scenario_name,
            "sample_id": self.sample_id,
            "timestamp_unix_ms": self.now_unix_ms(),
            "monotonic_ms": self.monotonic_ms(),
            "clock_source": self.clock_source,
            "source_type": source_type,
            "source_id": source_id,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "metric_unit": metric_unit,
            "labels": labels or {},
            "missing_reason": missing_reason_text,
        }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty JSONL artifact {path}")
    for index, row in enumerate(rows, start=1):
        _reject_unsafe_json_values(row, f"{path}:line {index}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True, allow_nan=False) for row in rows) + "\n", encoding="utf-8")


def _reject_unsafe_json_values(value: Any, path: str) -> None:
    if value is None:
        raise ValueError(f"{path}: null is not an allowed telemetry value")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path}: non-finite telemetry number is not allowed")
    if isinstance(value, str) and value.lower() in {"nan", "infinity", "-infinity", "undefined", "null"}:
        raise ValueError(f"{path}: forbidden placeholder value {value!r}")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_unsafe_json_values(item, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _reject_unsafe_json_values(item, f"{path}[{idx}]")


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def workload_metrics(
    *,
    requested_qps: float,
    duration_seconds: float,
    latencies_ms: list[float],
    error_texts: list[str],
) -> dict[str, Any]:
    sample_count = len(latencies_ms)
    error_count = len(error_texts)
    total_ops = sample_count + error_count
    duration = max(duration_seconds, 0.000001)
    missing_reasons: dict[str, str] = {}

    def latency_value(field: str, pct: float) -> float | str:
        if not latencies_ms:
            missing_reasons[field] = "no successful workload latency samples were collected for this window"
            return MISSING
        return round(percentile(latencies_ms, pct), 6)

    counts = classify_errors(error_texts)
    achieved_qps: float | str
    if total_ops == 0:
        achieved_qps = MISSING
        missing_reasons["achieved_qps"] = "no workload operations were attempted for this window"
    else:
        achieved_qps = round(sample_count / duration, 6)

    achieved_value = achieved_qps
    throughput_ratio: float | str = MISSING
    if isinstance(achieved_value, (int, float)) and requested_qps > 0:
        throughput_ratio = round(float(achieved_value) / float(requested_qps), 6)
    elif requested_qps <= 0:
        missing_reasons["throughput_ratio"] = "requested_qps was zero, so throughput ratio is undefined"
    else:
        missing_reasons["throughput_ratio"] = missing_reasons.get("achieved_qps", "achieved_qps was unavailable")

    moved_count = counts["moved_redirection_count"]
    ask_count = counts["ask_redirection_count"]
    cluster_down_count = counts["cluster_down_error_count"]
    readonly_count = counts["readonly_error_count"]
    tryagain_count = counts["tryagain_error_count"]

    return {
        "requested_qps": round(float(requested_qps), 6),
        "achieved_qps": achieved_qps,
        "throughput_ratio": throughput_ratio,
        "ok_ops": sample_count,
        "error_ops": error_count,
        "error_rate": round(error_count / max(total_ops, 1), 6) if total_ops else MISSING,
        "latency_p50_ms": latency_value("latency_p50_ms", 50),
        "latency_p90_ms": latency_value("latency_p90_ms", 90),
        "latency_p95_ms": latency_value("latency_p95_ms", 95),
        "latency_p99_ms": latency_value("latency_p99_ms", 99),
        "latency_p999_ms": latency_value("latency_p999_ms", 99.9),
        "timeout_count": counts["timeout_count"],
        "connection_error_count": counts["connection_error_count"],
        "moved_count": moved_count,
        "ask_count": ask_count,
        "cluster_down_count": cluster_down_count,
        "readonly_count": readonly_count,
        "tryagain_count": tryagain_count,
        "moved_redirection_count": counts["moved_redirection_count"],
        "ask_redirection_count": counts["ask_redirection_count"],
        "cluster_down_error_count": counts["cluster_down_error_count"],
        "readonly_error_count": counts["readonly_error_count"],
        "tryagain_error_count": counts["tryagain_error_count"],
        "unknown_error_count": counts["unknown_error_count"],
        "sample_count": sample_count,
        "duration_seconds": round(duration_seconds, 6),
        "missing_reasons": missing_reasons,
    }


def classify_errors(error_texts: list[str]) -> dict[str, int]:
    counts = {
        "timeout_count": 0,
        "connection_error_count": 0,
        "moved_redirection_count": 0,
        "ask_redirection_count": 0,
        "cluster_down_error_count": 0,
        "readonly_error_count": 0,
        "tryagain_error_count": 0,
        "unknown_error_count": 0,
    }
    for text in error_texts:
        lowered = text.lower()
        if "timeout" in lowered:
            counts["timeout_count"] += 1
        elif "connection" in lowered or "refused" in lowered or "reset" in lowered:
            counts["connection_error_count"] += 1
        elif "moved" in lowered:
            counts["moved_redirection_count"] += 1
        elif "ask" in lowered:
            counts["ask_redirection_count"] += 1
        elif "clusterdown" in lowered or "cluster down" in lowered:
            counts["cluster_down_error_count"] += 1
        elif "readonly" in lowered:
            counts["readonly_error_count"] += 1
        elif "tryagain" in lowered:
            counts["tryagain_error_count"] += 1
        else:
            counts["unknown_error_count"] += 1
    return counts
