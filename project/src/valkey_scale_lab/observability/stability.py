from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping, Sequence

from valkey_scale_lab.observability.cluster import LightClusterProbe
from valkey_scale_lab.observability.contracts import (
    CheckResult,
    CheckStatus,
    CollectionError,
    SemanticFailure,
    final_verdict,
    run_check,
)
from valkey_scale_lab.observability.load import MemtierLoadLane
from valkey_scale_lab.observability.resources import (
    ResourceSamplerRunner,
    analyze_resource_samples,
)
from valkey_scale_lab.observability.sentinel import SentinelLane


class StabilityWindow:
    """The fixed 120-second no-fault window from the accepted design."""

    def __init__(
        self,
        *,
        light_probe: LightClusterProbe,
        sentinel: SentinelLane,
        load: MemtierLoadLane,
        resource_runners: Sequence[ResourceSamplerRunner] = (),
        validation_options: Mapping[str, Any] | None = None,
    ) -> None:
        self.light_probe = light_probe
        self.sentinel = sentinel
        self.load = load
        self.resource_runners = list(resource_runners)
        # Applied to every boundary and per-round probe, so the window observes
        # the cluster under the same contract throughout.
        self.validation_options = dict(validation_options or {})

    def run(self) -> dict[str, Any]:
        checks: list[CheckResult] = []
        if not self.resource_runners:
            checks.append(
                CheckResult(
                    name="resource_sampler_configured",
                    status=CheckStatus.ERROR,
                    reason="formal stability window requires at least one resource sampler",
                )
            )
            return {
                **final_verdict(checks),
                "formal_window_started": False,
            }
        preflight = run_check("load_preflight", self.load.preflight)
        checks.append(preflight)
        if preflight.status is not CheckStatus.OK:
            return {
                **final_verdict(checks),
                "formal_window_started": False,
            }
        sentinel_prepare = run_check("sentinel_prepare", self.sentinel.prepare)
        checks.append(sentinel_prepare)
        if sentinel_prepare.status is not CheckStatus.OK:
            return {
                **final_verdict(checks),
                "formal_window_started": False,
            }
        start_boundary = run_check(
            "light_start_boundary",
            lambda: self.light_probe.validate(
                self.light_probe.collect(), **self.validation_options
            ),
        )
        checks.append(start_boundary)
        if start_boundary.status is not CheckStatus.OK:
            return {
                **final_verdict(checks),
                "formal_window_started": False,
            }

        load_process = None
        resource_documents: list[dict[str, Any]] = []
        resource_analyses: list[dict[str, Any]] = []
        expected_processes = {
            runner.sampler.sampler_id: {
                process.logical_id for process in runner.sampler.processes
            }
            for runner in self.resource_runners
        }
        rounds: list[dict[str, Any]] = []
        load_result: dict[str, Any] | None = None
        try:
            for runner in self.resource_runners:
                runner.start()
            load_process = self.load.start(duration_seconds=120.0)
            for round_index in range(2):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    light_future = executor.submit(
                        self.light_probe.collect_rolling, duration_seconds=60.0
                    )
                    sentinel_future = executor.submit(
                        self.sentinel.rolling_sweep, duration_seconds=60.0
                    )
                    light_rows = light_future.result()
                    sentinel_result = sentinel_future.result()
                light_result = self.light_probe.validate(
                    light_rows, **self.validation_options
                )
                rounds.append(
                    {
                        "round": round_index + 1,
                        "light": light_result,
                        "sentinel": sentinel_result,
                    }
                )
            load_result = self.load.finish(load_process)
            load_process = None
            checks.append(
                CheckResult(
                    name="load_formal_window",
                    status=CheckStatus.OK,
                    evidence=load_result,
                    warnings=tuple(load_result.get("warnings", [])),
                )
            )
            checks.append(
                CheckResult(
                    name="stability_light_rounds",
                    status=CheckStatus.OK,
                    evidence=[round_result["light"] for round_result in rounds],
                )
            )
            checks.append(
                CheckResult(
                    name="stability_sentinel_rounds",
                    status=CheckStatus.OK,
                    evidence=[round_result["sentinel"] for round_result in rounds],
                )
            )
        except SemanticFailure as exc:
            checks.append(
                CheckResult(
                    name="stability_formal_window",
                    status=CheckStatus.FAIL,
                    reason=str(exc),
                )
            )
        except Exception as exc:  # collector/process implementation failure
            checks.append(
                CheckResult(
                    name="stability_formal_window",
                    status=CheckStatus.ERROR,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
        finally:
            if load_process is not None:
                load_process.stop()
            for runner in self.resource_runners:
                try:
                    resource_documents.append(runner.stop())
                except Exception as exc:
                    checks.append(
                        CheckResult(
                            name=f"resource_sampler:{runner.sampler.sampler_id}",
                            status=CheckStatus.ERROR,
                            reason=f"{type(exc).__name__}: {exc}",
                        )
                    )
            self.sentinel.close()

        for document in resource_documents:
            sampler_id = str(document.get("static", {}).get("sampler_id", "MISSING"))
            if document.get("errors"):
                checks.append(
                    CheckResult(
                        name=f"resource_sampler:{sampler_id}",
                        status=CheckStatus.ERROR,
                        reason="; ".join(document["errors"]),
                    )
                )
                continue
            samples = list(document.get("samples", []))
            if (
                not samples
                or not any(sample.get("kind") == "host" for sample in samples)
                or not any(sample.get("kind") == "process" for sample in samples)
            ):
                checks.append(
                    CheckResult(
                        name=f"resource_sampler:{sampler_id}",
                        status=CheckStatus.ERROR,
                        reason="resource sampler produced no host/process evidence",
                    )
                )
                continue
            missing_live = _missing_live_processes(
                document, expected_processes.get(sampler_id, set())
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
                    timeline_events=_resource_timeline_events(
                        start_boundary.evidence,
                        rounds,
                        load_result,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - analyzer failure is a tool error
                checks.append(
                    CheckResult(
                        name=f"resource_analysis:{sampler_id}",
                        status=CheckStatus.ERROR,
                        reason=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            resource_analyses.append({"sampler_id": sampler_id, "analysis": analysis})
            checks.append(
                CheckResult(
                    name=f"resource_analysis:{sampler_id}",
                    status=CheckStatus.OK,
                    evidence=analysis,
                    warnings=tuple(analysis.get("warnings", [])),
                )
            )
        warnings = _epoch_warnings(
            start_boundary.evidence,
            rounds[-1]["light"] if rounds else None,
        )
        if warnings:
            checks.append(
                CheckResult(
                    name="epoch_change",
                    status=CheckStatus.OK,
                    warnings=tuple(warnings),
                )
            )
        result = final_verdict(checks)
        result.update(
            {
                "formal_window_started": True,
                "duration_seconds": 120,
                "start_boundary": start_boundary.evidence,
                "rounds": rounds,
                "end_boundary": rounds[-1]["light"] if rounds else None,
                "resource_documents": resource_documents,
                "resource_analyses": resource_analyses,
                "claim": "未观察到异常" if result["status"] == "PASS" else "",
            }
        )
        return result


def _epoch_warnings(
    start: dict[str, Any] | None, end: dict[str, Any] | None
) -> list[str]:
    if not start or not end:
        return []
    start_by_node = {row["logical_id"]: row for row in start.get("nodes", [])}
    warnings: list[str] = []
    for row in end.get("nodes", []):
        before = start_by_node.get(row["logical_id"])
        if before is None:
            continue
        for field in ("cluster_current_epoch", "cluster_my_epoch"):
            try:
                old = int(before["cluster_info"].get(field, 0))
                new = int(row["cluster_info"].get(field, 0))
            except (TypeError, ValueError):
                continue
            if new > old:
                warnings.append(
                    f"{row['logical_id']} {field} increased from {old} to {new}"
                )
    return warnings


def _missing_live_processes(
    document: dict[str, Any], expected_logical_ids: set[str]
) -> list[dict[str, Any]]:
    process_samples = [
        sample for sample in document.get("samples", []) if sample.get("kind") == "process"
    ]
    if not process_samples:
        return [{"reason": "no process samples"}]
    latest = process_samples[-1]
    observed = {
        str(row.get("logical_id"))
        for row in latest.get("processes", [])
        if isinstance(row, dict) and row.get("status", "OK") == "OK"
    }
    missing = [
        {"logical_id": logical_id, "reason": "missing latest sample"}
        for logical_id in sorted(expected_logical_ids - observed)
    ]
    for row in latest.get("processes", []):
        if isinstance(row, dict) and row.get("status", "OK") != "OK":
            missing.append(
                {
                    "logical_id": row.get("logical_id"),
                    "pid": row.get("pid"),
                    "status": row.get("status"),
                }
            )
    return missing


def _resource_timeline_events(
    start_boundary: dict[str, Any] | None,
    rounds: list[dict[str, Any]],
    load_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if start_boundary:
        events.append({"event_type": "topology_start_boundary", "monotonic": _first_monotonic(start_boundary)})
    if load_result:
        events.append({"event_type": "load_formal_window", "monotonic": None})
    for round_result in rounds:
        for row in round_result.get("sentinel", {}).get("rows", []):
            if isinstance(row, dict):
                events.append({"event_type": "sentinel_get", "event_id": row.get("logical_id"), "monotonic": row.get("monotonic")})
        for row in round_result.get("light", {}).get("nodes", []):
            if isinstance(row, dict):
                events.append({"event_type": "topology_light_probe", "event_id": row.get("logical_id"), "monotonic": row.get("monotonic")})
    return events


def _first_monotonic(document: dict[str, Any]) -> float | None:
    values = [
        row.get("monotonic")
        for row in document.get("nodes", [])
        if isinstance(row, dict) and isinstance(row.get("monotonic"), (int, float))
    ]
    return float(min(values)) if values else None
