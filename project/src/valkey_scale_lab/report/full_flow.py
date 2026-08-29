"""Make a full-flow run's evidence renderable by the offline report renderer.

The gate run and the renderer were built against different vocabularies and were
never connected. Measured 2026-08-19 on a real passing exact-50: the run's
`analysis_summary.json` emits `bottlenecks, failover, recovery, topology_summary,
lifecycle_durations, workload_impact, resources...` and `report/render.py` reads
`command_audit, management_ops, fault_timeline, setup_telemetry,
workload_benchmark, resource_analysis, findings, metrics...`. **They share three
keys** - `run_id`, `created_at` and `status` - so rendering a correct 50-node run
produced a report whose every section said `MISSING` or `SKIPPED_WITH_REASON`
and whose command audit said `total_commands: 0`, from a run that had issued
4,528 commands.

This is the adapter, and it is deliberately a *reader* rather than a second
analyzer. Every number below is lifted from an artifact the run already wrote and
validated; nothing here recomputes a measurement, because a report that derived
its own numbers could disagree with the evidence it claims to summarise.

Where a source is absent the section says so with a reason and the renderer
prints that reason. Nothing is estimated and no absence is filled in - the same
rule the rest of this product follows, and the reason a reader can trust the
sections that *are* populated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from valkey_scale_lab.report.messages import DEFAULT_LANGUAGE, messages

MISSING = "MISSING"
_SKIPPED = "SKIPPED_WITH_REASON"


def _load(runtime: Path, name: str) -> Any:
    try:
        return json.loads((runtime / name).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _load_lines(runtime: Path, name: str) -> list[dict[str, Any]]:
    path = runtime / name
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _skipped(reason: str) -> dict[str, Any]:
    return {"status": _SKIPPED, "reason": reason}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _setup_aggregates(runtime: Path, msg: Mapping[str, str]) -> dict[str, Any]:
    """Stage durations, from the run's own timing breakdown."""

    breakdown = _load(runtime, "runtime_timing_breakdown_local_full_flow.json")
    timings = (breakdown or {}).get("timings")
    if not isinstance(timings, list) or not timings:
        return _skipped(msg["reason.no_timings"])
    rows: list[dict[str, Any]] = []
    for row in timings:
        if not isinstance(row, dict):
            continue
        seconds = _number(row.get("duration_seconds"))
        rows.append(
            {
                "metric": str(row.get("name", MISSING)),
                # The breakdown records seconds; the renderer's whole vocabulary
                # is milliseconds, so the unit is converted here rather than
                # letting a reader compare two scales in one table. A stage the
                # run recorded as MISSING stays MISSING - it is not a zero.
                "value_ms": round(seconds * 1000.0, 3) if seconds is not None else MISSING,
                "status": str(row.get("status", MISSING)),
            }
        )
    ranking = sorted(rows, key=lambda item: _number(item["value_ms"]) or 0.0, reverse=True)
    return {
        "status": "PASS",
        "stage_duration_ranking": ranking,
        # Per-node readiness is not recorded by the full-flow lifecycle - it has
        # no per-node ready timestamp - so this is stated absent rather than
        # approximated from a stage total.
        "slowest_nodes_topN": [
            {
                "status": _SKIPPED,
                "reason": msg["reason.no_per_node_ready"],
            }
        ],
    }


def _command_audit(runtime: Path, msg: Mapping[str, str]) -> dict[str, Any]:
    """The command audit, which already answers most of this question itself."""

    summary = _load(runtime, "command_audit/command_audit_summary.json")
    rows = _load_lines(runtime, "command_audit/command_log.jsonl")
    if summary is None and not rows:
        return _skipped(msg["reason.no_command_audit"])

    timed = [row for row in rows if _number(row.get("duration_ms")) is not None]
    slowest = sorted(timed, key=lambda row: float(row["duration_ms"]), reverse=True)[:20]
    return {
        "status": "PASS",
        "total_commands": len(rows),
        "by_command_kind": (summary or {}).get("by_command_kind", {}),
        "slowest_commands_topN": [
            {
                "command_id": row.get("command_id", MISSING),
                "command_kind": row.get("command_kind", MISSING),
                "duration_ms": row.get("duration_ms", MISSING),
                "status": row.get("status", MISSING),
            }
            for row in slowest
        ],
        "failed_commands": (summary or {}).get("failed_commands", []),
        "retry_commands": (summary or {}).get("retry_commands", []),
        "pass_count": (summary or {}).get("pass_count", MISSING),
        "failure_count": (summary or {}).get("failure_count", MISSING),
        "retry_count": (summary or {}).get("retry_count", MISSING),
    }


def _management_ops(runtime: Path, msg: Mapping[str, str]) -> dict[str, Any]:
    """The management matrix, whose records already use the renderer's vocabulary."""

    sequence = _load(runtime, "management_sequence.json")
    operations = ((sequence or {}).get("result") or {}).get("operations")
    if not isinstance(operations, list) or not operations:
        return _skipped(msg["reason.no_management_ops"])

    ranking = sorted(
        (
            {
                "operation_name": row.get("operation_name", MISSING),
                "operation_id": row.get("operation_id", MISSING),
                "operation_duration_ms": row.get("operation_duration_ms", MISSING),
                "operation_status": row.get("operation_status", MISSING),
                "command_count": row.get("command_count", 0),
                "error_count": row.get("error_count", 0),
                "retry_count": row.get("retry_count", 0),
            }
            for row in operations
            if isinstance(row, dict)
        ),
        key=lambda item: _number(item["operation_duration_ms"]) or 0.0,
        reverse=True,
    )
    diffs: list[dict[str, Any]] = []
    for row in operations:
        diff = row.get("topology_diff")
        if not isinstance(diff, dict):
            continue
        before = _number(row.get("cluster_known_nodes_before"))
        after = _number(row.get("cluster_known_nodes_after"))
        diffs.append(
            {
                "operation_id": row.get("operation_id", MISSING),
                "known_nodes_delta": (
                    int(after - before) if before is not None and after is not None else MISSING
                ),
                "moved_slot_range_count": row.get("slots_moved", MISSING),
                "keys_moved": row.get("keys_moved", MISSING),
            }
        )
    return {
        "status": ((sequence or {}).get("result") or {}).get("operation_status", MISSING),
        "duration_ranking_topN": ranking,
        "topology_diff_summary": diffs,
        "rolling_restart_summary": _load_lines(runtime, "rolling_restart_results.jsonl"),
        "reshard_rebalance_summary": [
            row for row in ranking if "reshard" in str(row["operation_name"]) or "rebalance" in str(row["operation_name"])
        ],
    }


def _workload_benchmark(runtime: Path, msg: Mapping[str, str]) -> dict[str, Any]:
    windows = (_load(runtime, "workload_windows.json") or {}).get("windows")
    if not isinstance(windows, list) or not windows:
        return _skipped(msg["reason.no_workload_windows"])
    rows = [
        {
            "profile": row.get("profile", row.get("coverage_id", MISSING)),
            "window_name": row.get("window_name", row.get("event_id", MISSING)),
            "achieved_qps": row.get("achieved_qps", MISSING),
            "latency_p99_ms": row.get("latency_p99_ms", MISSING),
            "error_rate": row.get("error_rate", MISSING),
            "status": row.get("status", MISSING),
        }
        for row in windows
        if isinstance(row, dict)
    ]
    profiles = sorted({str(row["profile"]) for row in rows if row["profile"] != MISSING})
    # `key_slot_coverage` is an object; the report line asks the one question
    # it exists to answer - was the benchmark confined to a fixed hash tag -
    # so the boolean is lifted out rather than the whole record printed.
    covered = {
        str(row["key_slot_coverage"].get("full_slot_covered", MISSING))
        for row in windows
        if isinstance(row, dict) and isinstance(row.get("key_slot_coverage"), dict)
    }
    return {
        "status": "PASS",
        "windows": rows,
        "profiles_covered": profiles,
        "full_slot_covered": sorted(covered)[0] if len(covered) == 1 else (sorted(covered) or MISSING),
    }


def _latency_point(value: Any, msg: Mapping[str, str]) -> dict[str, Any]:
    """One measured latency as the renderer's distribution shape.

    A single run measures one failover, so p50, p95 and max are that one value.
    They are stated rather than left MISSING because they are the same
    observation, and `sample_count` says how many observations stand behind
    them so nobody reads a percentile that had one sample as a distribution.
    """

    number = _number(value)
    if number is None:
        return {"status": MISSING, "reason": msg["reason.latency_not_observed"], "sample_count": 0}
    return {
        "p50_ms": number,
        "p95_ms": number,
        "max_ms": number,
        "status": "PASS",
        "sample_count": 1,
    }


def _fault_timeline(runtime: Path, msg: Mapping[str, str]) -> dict[str, Any]:
    sequence = _load(runtime, "fault_sequence.json")
    if sequence is None:
        return _skipped(msg["reason.no_fault_sequence"])
    results = sequence.get("fault_results") or []
    failover = sequence.get("failover_details") or {}
    # Each scenario reports its *own* duration and nothing else. The failover
    # numbers below are one measurement, taken by the primary-kill lane, and are
    # not a property of `replica_stop` or `network_delay`. An earlier draft of
    # this adapter copied them onto all nine rows, which read as nine measured
    # outages that were never measured - the fabrication this product forbids
    # everywhere else. Where a scenario did not measure a client outage the
    # field says so with a reason.
    unmeasured = {
        "status": MISSING,
        "reason": msg["reason.no_client_outage_measure"],
    }
    rows = [
        {
            "fault_type": row.get("id", MISSING),
            "sample_id": row.get("operation_id", MISSING),
            "status": row.get("status", MISSING),
            "metrics": {
                "duration_ms": row.get("duration_ms", MISSING),
                "client_unavailability_ms": unmeasured,
                "workload_recovery_ms": unmeasured,
            },
        }
        for row in results
        if isinstance(row, dict)
    ]
    return {
        "status": "PASS" if results else _SKIPPED,
        "reason": "" if results else msg["reason.no_fault_scenarios"],
        "scenario_count": len(results),
        "rows": rows,
        "failover_latency": _latency_point(failover.get("cluster_recovery_latency_ms"), msg),
        "promotion_latency": _latency_point(failover.get("pfail_to_promotion_ms"), msg),
        "client_unavailability": _latency_point(failover.get("client_unavailable_to_recovered_ms"), msg),
        "workload_recovery": _latency_point(failover.get("read_unavailability_ms"), msg),
        # The full-flow fault lane observes no split brain and no cluster-down
        # window; §7.3 forbids the writes that would measure the second. Stated
        # absent with the reason rather than reported as zero, which would be a
        # claim nobody made.
        "split_brain_window": {
            "status": MISSING,
            "reason": msg["reason.no_split_brain"],
        },
        "cluster_down_window": {
            "status": MISSING,
            "reason": msg["reason.no_cluster_down"],
        },
        "detection_ms": failover.get("process_gone_to_pfail_ms", MISSING),
        "failover_success": failover.get("failover_success", MISSING),
        "replacement_logical_id": failover.get("replacement_logical_id", MISSING),
        "missing_fields": failover.get("missing_fields", []),
    }


def _resource_analysis(runtime: Path, msg: Mapping[str, str]) -> dict[str, Any]:
    observation = _load(runtime, "scalable_stability_observation.json")
    analyses = (observation or {}).get("resource_analyses")
    if not isinstance(analyses, list) or not analyses:
        return _skipped(msg["reason.no_resource_analyses"])
    per_window: list[dict[str, Any]] = []
    for entry in analyses:
        if not isinstance(entry, dict):
            continue
        analysis = entry.get("analysis") or {}
        totals = analysis.get("process_totals") or {}
        per_window.append(
            {
                "window": entry.get("sampler_id", MISSING),
                "status": analysis.get("status", MISSING),
                "metrics": totals,
                "missing_count": len(analysis.get("warnings") or []),
            }
        )
    return {
        "status": "PASS",
        "per_window": per_window,
        # Ranking nodes by resource use needs a per-node series the stability
        # observation aggregates per sampler, not per node.
        "abnormal_nodes_topN": [
            {
                "status": _SKIPPED,
                "reason": msg["reason.no_per_node_resource"],
            }
        ],
    }


def _findings(runtime: Path, analysis: dict[str, Any]) -> list[dict[str, Any]]:
    cleanup = _load(runtime, "cleanup_report.json") or {}
    verdict = _load(runtime, "run_verdict.json") or {}
    findings = [
        {"name": "run_verdict", "status": verdict.get("status", MISSING)},
        {"name": "management", "status": analysis.get("management_status", MISSING)},
        {"name": "fault", "status": analysis.get("fault_status", MISSING)},
        {
            "name": "cleanup",
            "status": cleanup.get("status", MISSING),
            "resources_remaining": cleanup.get("resources_remaining", MISSING),
        },
    ]
    recovery = analysis.get("recovery") or {}
    if recovery:
        findings.append(
            {
                "name": "recovery",
                "status": recovery.get("cluster_state", MISSING),
                "known_nodes": recovery.get("known_nodes", MISSING),
            }
        )
    return findings


def build_renderable_analysis(
    runtime_dir: str | Path, *, lang: str = DEFAULT_LANGUAGE
) -> dict[str, Any]:
    """The run's evidence in the vocabulary `report/render.py` consumes.

    `lang` reaches this layer and not only the renderer, because the reasons an
    absence carries are written here and are prose a person reads. Storing a key
    and resolving it later would leave `renderable_analysis.json` - an artifact a
    run keeps - unreadable to anyone opening it, which is the opposite of what
    every absence-with-a-reason in this product is for.

    Nothing else moves with the language: the same run yields the same numbers,
    the same field names and the same statuses in either.
    """

    msg = messages(lang)
    runtime = Path(runtime_dir)
    analysis = _load(runtime, "analysis_summary.json") or {}
    verdict = _load(runtime, "run_verdict.json") or {}
    cleanup = _load(runtime, "cleanup_report.json") or {}
    metrics = _load_lines(runtime, "metrics_timeseries.jsonl")

    return {
        "schema_version": "v1",
        "artifact_type": "local_full_flow_renderable_analysis",
        # Recorded so the renderer can refuse a mismatch. The reasons below are
        # prose in one language, and a report rendered in the other would come
        # out half translated - which reads as a rendering defect rather than as
        # what it is.
        "language": lang,
        "status": verdict.get("status") or analysis.get("status", MISSING),
        "run_id": analysis.get("run_id", MISSING),
        "created_at": analysis.get("created_at", MISSING),
        "source": {
            "capability_id": analysis.get("capability_id", MISSING),
            "scenario_name": analysis.get("scenario_name", MISSING),
            "node_count": analysis.get("node_count", MISSING),
        },
        "run_metadata": {
            "run_id": analysis.get("run_id", MISSING),
            "created_at": analysis.get("created_at", MISSING),
            "node_count": analysis.get("node_count", MISSING),
            "artifact_root": str(runtime),
            # Neither is recorded by a full-flow run today. Named with the reason
            # rather than omitted, so the gap is visible in the report instead of
            # looking like a renderer fault.
            "git_sha": {"status": MISSING, "reason": msg["reason.no_git_sha"]},
            "valkey_version": {
                "status": MISSING,
                "reason": msg["reason.no_valkey_version"],
            },
        },
        "findings": _findings(runtime, analysis),
        "setup_aggregates": _setup_aggregates(runtime, msg),
        "command_audit": _command_audit(runtime, msg),
        "management_ops": _management_ops(runtime, msg),
        "workload_benchmark": _workload_benchmark(runtime, msg),
        "fault_timeline": _fault_timeline(runtime, msg),
        "resource_analysis": _resource_analysis(runtime, msg),
        "metrics": [
            {
                "name": row.get("metric_name", MISSING),
                "value": row.get("metric_value", MISSING),
                "unit": row.get("metric_unit", ""),
                "source": row.get("source_type", ""),
            }
            for row in metrics
        ],
        "missing_metrics": analysis.get("missing_evidence", []),
        "baseline_comparison": {
            "status": _SKIPPED,
            "reason": msg["reason.no_baseline"],
        },
        "cleanup": {
            "status": cleanup.get("status", MISSING),
            "resources_remaining": cleanup.get("resources_remaining", MISSING),
            "action_count": len(cleanup.get("cleanup_actions", [])),
        },
    }
