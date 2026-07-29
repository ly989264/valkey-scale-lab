from __future__ import annotations

import time
from pathlib import Path
from threading import Event
from typing import Any, Mapping, Sequence

from valkey_scale_lab import __version__
from valkey_scale_lab.observability.contracts import (
    CheckResult,
    CheckStatus,
    final_verdict,
)
from valkey_scale_lab.observability.resources import (
    ExpectedGoneProcess,
    ResourceSamplerRunner,
    analyze_resource_samples,
)


def run_resource_observation(
    *,
    runners: Sequence[ResourceSamplerRunner],
    duration_seconds: float,
    expected_gone_processes: Sequence[ExpectedGoneProcess] = (),
    first_complete_sample_event: Event | None = None,
    window_start_event: Event | None = None,
    timeline_events: Sequence[Mapping[str, Any]] = (),
    sleep_interval_seconds: float = 0.05,
    monotonic: Any = time.monotonic,
) -> dict[str, Any]:
    checks: list[CheckResult] = []
    expected = {
        (process.logical_id, process.pid) for process in expected_gone_processes
    }
    configured_processes = {
        runner.sampler.sampler_id: {
            (process.logical_id, process.pid) for process in runner.sampler.processes
        }
        for runner in runners
    }
    if not runners:
        checks.append(
            CheckResult(
                name="resource_sampler_configured",
                status=CheckStatus.ERROR,
                reason="resource observation requires at least one sampler runner",
            )
        )
        return {
            **final_verdict(checks),
            "resource_documents": [],
            "resource_analyses": [],
        }

    documents: list[dict[str, Any]] = []
    first_sample_marked = False
    started = monotonic()
    try:
        for runner in runners:
            runner.start()
        deadline = started + duration_seconds
        while monotonic() <= deadline:
            if not first_sample_marked and _initial_process_samples_complete(
                runners, expected
            ):
                if first_complete_sample_event is not None:
                    first_complete_sample_event.set()
                first_sample_marked = True
            time.sleep(sleep_interval_seconds)
        if not first_sample_marked:
            checks.append(
                CheckResult(
                    name="resource_expected_gone_prefault_sample",
                    status=CheckStatus.ERROR,
                    reason="planned-kill target processes were not sampled before the fault barrier",
                )
            )
    finally:
        for runner in runners:
            try:
                documents.append(runner.stop())
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    CheckResult(
                        name=f"resource_sampler:{runner.sampler.sampler_id}",
                        status=CheckStatus.ERROR,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                )

    analyses: list[dict[str, Any]] = []
    for document in documents:
        sampler_id = str(document.get("static", {}).get("sampler_id", "MISSING"))
        samples = list(document.get("samples", []))
        if document.get("errors"):
            checks.append(
                CheckResult(
                    name=f"resource_sampler:{sampler_id}",
                    status=CheckStatus.ERROR,
                    reason="; ".join(str(error) for error in document["errors"]),
                )
            )
            continue
        if not any(sample.get("kind") == "host" for sample in samples):
            checks.append(
                CheckResult(
                    name=f"resource_sampler:{sampler_id}",
                    status=CheckStatus.ERROR,
                    reason="resource sampler produced no host evidence",
                )
            )
            continue
        if not any(sample.get("kind") == "process" for sample in samples):
            checks.append(
                CheckResult(
                    name=f"resource_sampler:{sampler_id}",
                    status=CheckStatus.ERROR,
                    reason="resource sampler produced no process evidence",
                )
            )
            continue
        missing_live = _missing_live_processes(
            document,
            expected,
            configured_processes.get(sampler_id, set()),
        )
        if missing_live:
            checks.append(
                CheckResult(
                    name=f"resource_sampler:{sampler_id}",
                    status=CheckStatus.ERROR,
                    reason=f"live process samples are missing: {missing_live}",
                )
            )
            continue
        try:
            analysis = analyze_resource_samples(
                document["static"],
                samples,
                timeline_events=timeline_events,
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                CheckResult(
                    name=f"resource_analysis:{sampler_id}",
                    status=CheckStatus.ERROR,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        analyses.append({"sampler_id": sampler_id, "analysis": analysis})
        checks.append(
            CheckResult(
                name=f"resource_analysis:{sampler_id}",
                status=CheckStatus.OK,
                evidence=analysis,
                warnings=tuple(analysis.get("warnings", [])),
            )
        )

    result = final_verdict(checks)
    return {
        **result,
        "duration_seconds": duration_seconds,
        "expected_gone_processes": [
            {"logical_id": process.logical_id, "pid": process.pid}
            for process in expected_gone_processes
        ],
        "planned_kill_prefault_sample_complete": first_sample_marked,
        "planned_kill_barrier_observed": (
            window_start_event.is_set() if window_start_event is not None else False
        ),
        "resource_documents": documents,
        "resource_analyses": analyses,
    }


def write_resource_observation(
    path: Path,
    *,
    capability_id: str,
    scenario_name: str,
    run_id: str,
    runners: Sequence[ResourceSamplerRunner],
    duration_seconds: float,
    expected_gone_processes: Sequence[ExpectedGoneProcess] = (),
    first_complete_sample_event: Event | None = None,
    window_start_event: Event | None = None,
    timeline_events: Sequence[Mapping[str, Any]] = (),
    monotonic: Any = time.monotonic,
) -> dict[str, Any]:
    import json

    observation = run_resource_observation(
        runners=runners,
        duration_seconds=duration_seconds,
        expected_gone_processes=expected_gone_processes,
        first_complete_sample_event=first_complete_sample_event,
        window_start_event=window_start_event,
        timeline_events=timeline_events,
        monotonic=monotonic,
    )
    artifact = {
        "schema_version": "v1",
        "artifact_type": "resource_observation",
        "capability_id": capability_id,
        "scenario_name": scenario_name,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        **observation,
    }
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


def _expected_processes_sampled(
    runners: Sequence[ResourceSamplerRunner], expected: set[tuple[str, int]]
) -> bool:
    observed: set[tuple[str, int]] = set()
    for runner in runners:
        for sample in runner.samples:
            if sample.get("kind") != "process":
                continue
            for row in sample.get("processes", []):
                if row.get("status", "OK") == "EXPECTED_GONE":
                    continue
                try:
                    observed.add((str(row["logical_id"]), int(row["pid"])))
                except (KeyError, TypeError, ValueError):
                    continue
    return expected <= observed


def _initial_process_samples_complete(
    runners: Sequence[ResourceSamplerRunner], expected: set[tuple[str, int]]
) -> bool:
    if expected:
        return _expected_processes_sampled(runners, expected)
    return all(any(sample.get("kind") == "process" for sample in runner.samples) for runner in runners)


def _missing_live_processes(
    document: Mapping[str, Any],
    expected: set[tuple[str, int]],
    configured: set[tuple[str, int]],
) -> list[dict[str, Any]]:
    static = document.get("static", {})
    sampler_id = str(static.get("sampler_id", "MISSING")) if isinstance(static, Mapping) else "MISSING"
    process_samples = [
        sample for sample in document.get("samples", []) if sample.get("kind") == "process"
    ]
    if not process_samples:
        return [{"sampler_id": sampler_id, "reason": "no process samples"}]
    latest = process_samples[-1]
    missing: list[dict[str, Any]] = []
    observed: set[tuple[str, int]] = set()
    for row in latest.get("processes", []):
        try:
            key = (str(row["logical_id"]), int(row["pid"]))
        except (KeyError, TypeError, ValueError):
            missing.append({"sampler_id": sampler_id, "row": row, "reason": "invalid process row"})
            continue
        if key in expected and row.get("status") == "EXPECTED_GONE":
            continue
        if row.get("status", "OK") != "OK":
            missing.append({"sampler_id": sampler_id, "logical_id": key[0], "pid": key[1], "status": row.get("status")})
            continue
        observed.add(key)
    for logical_id, pid in sorted(configured - expected - observed):
        missing.append(
            {
                "sampler_id": sampler_id,
                "logical_id": logical_id,
                "pid": pid,
                "reason": "missing latest sample",
            }
        )
    return missing
