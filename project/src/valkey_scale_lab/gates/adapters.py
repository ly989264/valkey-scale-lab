from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

from valkey_scale_lab.scenarios import ArtifactSpec, ReportSurface, ScenarioSpec
from valkey_scale_lab.scenarios.contracts import freeze_json
from valkey_scale_lab.runtime.docker_runtime import (
    cleanup_scenario,
    create_scenario,
)
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline

from .contracts import (
    AdapterBundle,
    ExecutionContext,
    OwnedFaultScope,
    StepResult,
    StepStatus,
)


# These aliases are intentionally direct references. The adapter delegates to the
# established runtime instead of copying any Valkey or Docker lifecycle behavior.
LEGACY_CREATE_SCENARIO = create_scenario
LEGACY_CLEANUP_SCENARIO = cleanup_scenario


class GateAdapterError(RuntimeError):
    pass


class AdapterPathError(GateAdapterError):
    pass


class AdapterCollisionError(GateAdapterError):
    pass


class AdapterOwnershipError(GateAdapterError):
    pass


@dataclass(frozen=True)
class LegacyRuntimeEntrypoints:
    create: Callable[..., dict[str, Any]] = LEGACY_CREATE_SCENARIO
    cleanup: Callable[..., dict[str, Any]] = LEGACY_CLEANUP_SCENARIO
    preflight: Optional[Callable[..., dict[str, Any]]] = None
    live_probe: Optional[Callable[..., dict[str, Any]]] = None


@dataclass(frozen=True)
class LegacyRuntimePaths:
    artifact_root: Path
    runtime_dir: Path
    state_path: Path
    cleanup_path: Path

    @classmethod
    def under(cls, artifact_root: Union[str, Path]) -> "LegacyRuntimePaths":
        root = Path(artifact_root).resolve()
        runtime_dir = _confined(root, root / "runtime", allow_root=False)
        return cls(
            artifact_root=root,
            runtime_dir=runtime_dir,
            state_path=_confined(root, runtime_dir / "state.json", allow_root=False),
            cleanup_path=_confined(
                root,
                runtime_dir / "cleanup_report.json",
                allow_root=False,
            ),
        )


@dataclass(frozen=True)
class LegacyExecutionSnapshot:
    """Read-only observations retained by a completed legacy projection."""

    run_id: str
    ownership_id: str
    provenance_id: str
    state: Optional[Mapping[str, Any]]
    preflight_result: Optional[Mapping[str, Any]]
    live_probe_result: Optional[Mapping[str, Any]]
    cleanup_result: Optional[Mapping[str, Any]]
    setup_segments: tuple[Mapping[str, Any], ...]


@dataclass
class _LegacyRun:
    ownership_id: str
    provenance_id: str
    paths: LegacyRuntimePaths
    setup_timeline: SetupTimeline = field(default_factory=SetupTimeline)
    state: Optional[dict[str, Any]] = None
    preflight_result: Optional[dict[str, Any]] = None
    live_probe_result: Optional[dict[str, Any]] = None
    runtime_started: bool = False
    cleanup_attempted: bool = False
    cleanup_result: Optional[dict[str, Any]] = None


def _confined(root: Path, candidate: Path, *, allow_root: bool) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise AdapterPathError(
            f"adapter path escapes artifact_root: {candidate}"
        ) from exc
    if not allow_root and relative == Path("."):
        raise AdapterPathError("adapter output path must be below artifact_root")
    return resolved


def _load_owned_state(
    path: Path,
    *,
    phase: str,
    scenario: str,
    expected_run_id: Optional[str] = None,
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterOwnershipError(
            f"cleanup requires readable runtime ownership state: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise AdapterOwnershipError("runtime ownership state must be a JSON object")
    runtime = value.get("runtime")
    run_id = runtime.get("run_id") if isinstance(runtime, dict) else None
    if not isinstance(run_id, str) or not run_id:
        raise AdapterOwnershipError(
            "cleanup requires runtime ownership with an explicit run_id"
        )
    if value.get("phase_id") != phase or value.get("scenario") != scenario:
        raise AdapterOwnershipError(
            "runtime ownership state does not match the configured phase/scenario"
        )
    if expected_run_id is not None and run_id != expected_run_id:
        raise AdapterOwnershipError(
            f"runtime ownership run_id mismatch: expected {expected_run_id!r}, got {run_id!r}"
        )
    return value


def _optional_path(value: Any) -> Optional[Path]:
    if value is None:
        return None
    if not isinstance(value, (str, Path)):
        raise GateAdapterError("configured path must be a string or Path")
    return Path(value)


def _optional_mapping(value: Any, *, field_name: str) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise GateAdapterError(f"{field_name} must be a mapping")
    return dict(value)


class LegacyGateAdapter:
    """Project the monolithic P36 runtime through the narrow Gate protocols.

    ``create_scenario`` remains the single owner of Valkey, workload,
    management, fault, analysis, and report behavior. The other methods record
    the canonical orchestration boundary and expose only paths produced by that
    call; they do not recreate or relabel the underlying observations.
    """

    _PROJECTION_MODE = "legacy_monolith_projection"

    def __init__(
        self,
        entrypoints: Optional[LegacyRuntimeEntrypoints] = None,
    ) -> None:
        self.entrypoints = entrypoints or LegacyRuntimeEntrypoints()
        self._runs: dict[str, _LegacyRun] = {}
        self._lock = threading.Lock()

    def resource_preflight(self, context: ExecutionContext) -> StepResult:
        phase, scenario, config_template = self._require_profile(context)
        record = self._record(context)
        path = record.paths.runtime_dir / "resource_preflight.json"
        if self.entrypoints.preflight is not None:
            record.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
            try:
                with record.setup_timeline.span(
                    "resource_preflight",
                    "resource_preflight",
                    {"node_count": context.requested_nodes},
                ):
                    report = self.entrypoints.preflight(
                        phase=phase,
                        scenario=scenario,
                        config_path=config_template,
                        out_path=path,
                        requested_nodes=context.requested_nodes,
                    )
            except Exception as exc:  # noqa: BLE001 - inability to prove safety blocks execution
                return StepResult(
                    step_id="resource_preflight",
                    status=StepStatus.BLOCKED,
                    run_id=context.run_id,
                    ownership_id=context.ownership_id,
                    provenance_id=context.provenance_id,
                    reason=f"resource preflight could not establish safe execution: {exc}",
                    details={
                        "adapter_mode": self._PROJECTION_MODE,
                        "admission_evidence": False,
                        "exception_type": exc.__class__.__name__,
                    },
                )
            if not isinstance(report, dict):
                return StepResult(
                    step_id="resource_preflight",
                    status=StepStatus.BLOCKED,
                    run_id=context.run_id,
                    ownership_id=context.ownership_id,
                    provenance_id=context.provenance_id,
                    reason="resource preflight did not return a verifiable report",
                    details={
                        "adapter_mode": self._PROJECTION_MODE,
                        "admission_evidence": False,
                    },
                )
            record.preflight_result = dict(report)
            observed = report.get("nodes_requested", report.get("node_count"))
            if observed != context.requested_nodes:
                return StepResult(
                    step_id="resource_preflight",
                    status=StepStatus.BLOCKED,
                    run_id=context.run_id,
                    ownership_id=context.ownership_id,
                    provenance_id=context.provenance_id,
                    reason=(
                        "resource preflight did not preserve the exact requested node count: "
                        f"requested={context.requested_nodes}, observed={observed}"
                    ),
                    artifact_paths=(path,) if path.exists() else (),
                    details={
                        "adapter_mode": self._PROJECTION_MODE,
                        "admission_evidence": False,
                    },
                )
            details = {
                "adapter_mode": self._PROJECTION_MODE,
                "delegated_entrypoint": "resource_preflight",
                "requested_nodes": context.requested_nodes,
                "observed_nodes": observed,
                "admission_evidence": False,
            }
            if report.get("can_run") is not True or report.get("status") != "PASS":
                return StepResult(
                    step_id="resource_preflight",
                    status=StepStatus.BLOCKED,
                    run_id=context.run_id,
                    ownership_id=context.ownership_id,
                    provenance_id=context.provenance_id,
                    reason="resource preflight blocked exact-scale execution",
                    artifact_paths=(path,) if path.exists() else (),
                    details=details,
                )
            return StepResult.passed(
                context,
                "resource_preflight",
                artifact_paths=(path,) if path.exists() else (),
                details=details,
            )
        return StepResult.passed(
            context,
            "resource_preflight",
            artifact_paths=(path,) if path.exists() else (),
            details={
                "adapter_mode": self._PROJECTION_MODE,
                "delegated_entrypoint": "create_scenario",
                "delegated_to": "runtime_start",
                "projected_artifact_names": ("resource_preflight.json",),
                "admission_evidence": False,
            },
        )

    def runtime_start(self, context: ExecutionContext) -> StepResult:
        phase, scenario, config_template = self._require_profile(context)
        record = self._record(context)
        with self._lock:
            if record.runtime_started:
                raise AdapterCollisionError(
                    f"runtime_start already attempted for run_id {context.run_id!r}"
                )
            if record.paths.state_path.exists():
                raise AdapterCollisionError(
                    f"runtime state output already exists: {record.paths.state_path}"
                )
            record.runtime_started = True
        record.paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {
            "phase": phase,
            "scenario": scenario,
            "config_path": config_template,
            "artifacts_dir": record.paths.runtime_dir,
            "state_out": record.paths.state_path,
            "setup_timeline": record.setup_timeline,
        }
        global_config_path = _optional_path(
            context.configuration.get("global_config_path")
        )
        if global_config_path is not None:
            kwargs["global_config_path"] = global_config_path
        cli_overrides = _optional_mapping(
            context.configuration.get("cli_overrides"),
            field_name="cli_overrides",
        )
        if cli_overrides is not None:
            kwargs["cli_overrides"] = cli_overrides

        state = self.entrypoints.create(**kwargs)
        if not isinstance(state, dict):
            raise GateAdapterError("legacy create_scenario must return a state object")
        nodes = state.get("nodes")
        if not isinstance(nodes, list) or len(nodes) != context.requested_nodes:
            observed = len(nodes) if isinstance(nodes, list) else "MISSING"
            raise GateAdapterError(
                "legacy runtime did not preserve the exact requested node count: "
                f"requested={context.requested_nodes}, observed={observed}"
            )
        runtime = state.get("runtime")
        runtime_run_id = runtime.get("run_id") if isinstance(runtime, dict) else None
        if not isinstance(runtime_run_id, str) or not runtime_run_id:
            raise AdapterOwnershipError(
                "legacy runtime state requires an explicit runtime.run_id"
            )
        if state.get("phase_id") != phase or state.get("scenario") != scenario:
            raise AdapterOwnershipError(
                "legacy runtime returned cross-profile ownership state"
            )
        persisted = _load_owned_state(
            record.paths.state_path,
            phase=phase,
            scenario=scenario,
            expected_run_id=runtime_run_id,
        )
        persisted_nodes = persisted.get("nodes")
        if (
            not isinstance(persisted_nodes, list)
            or len(persisted_nodes) != context.requested_nodes
        ):
            raise GateAdapterError(
                "persisted legacy state did not preserve the exact requested node count"
            )
        record.state = state
        return StepResult.passed(
            context,
            "runtime_start",
            artifact_paths=(record.paths.state_path,),
            details={
                "adapter_mode": self._PROJECTION_MODE,
                "delegated_entrypoint": "create_scenario",
                "runtime_run_id": runtime_run_id,
                "requested_nodes": context.requested_nodes,
                "observed_nodes": len(nodes),
                "admission_evidence": False,
            },
        )

    def cluster_form(self, context: ExecutionContext) -> StepResult:
        return self._projected(
            context,
            "cluster_form",
            (
                f"cluster_snapshots_{context.runtime_scenario}.json",
                "run_state.json",
            ),
        )

    def stabilize(self, context: ExecutionContext) -> StepResult:
        return self._projected(context, "stabilize", ("run_state.json",))

    def run_baseline(self, context: ExecutionContext) -> StepResult:
        return self._projected(
            context,
            "baseline_workload",
            ("workload_windows.json", "events.jsonl"),
        )

    def run_matrix(
        self,
        context: ExecutionContext,
        scenarios: tuple[ScenarioSpec, ...],
        execution_order_or_scope: Union[tuple[str, ...], OwnedFaultScope],
    ) -> StepResult:
        if isinstance(execution_order_or_scope, OwnedFaultScope):
            return self._run_fault_matrix(
                context,
                scenarios,
                execution_order_or_scope,
            )
        return self._run_management_matrix(
            context,
            scenarios,
            execution_order_or_scope,
        )

    def _run_management_matrix(
        self,
        context: ExecutionContext,
        scenarios: tuple[ScenarioSpec, ...],
        execution_order: tuple[str, ...],
    ) -> StepResult:
        scenario_ids = tuple(scenario.id for scenario in scenarios)
        configured_operations = tuple(
            operation for scenario in scenarios for operation in scenario.operations
        )
        if (
            len(set(execution_order)) != len(execution_order)
            or set(execution_order) != set(configured_operations)
        ):
            raise GateAdapterError(
                "management execution order must name every configured operation "
                "exactly once"
            )
        return self._projected(
            context,
            "management_matrix",
            ("management_sequence.json", "management_command_log.jsonl"),
            scenario_ids=scenario_ids,
            execution_order=execution_order,
        )

    def _run_fault_matrix(
        self,
        context: ExecutionContext,
        scenarios: tuple[ScenarioSpec, ...],
        scope: OwnedFaultScope,
    ) -> StepResult:
        if (
            scope.run_id != context.run_id
            or scope.ownership_id != context.ownership_id
            or not scope.project_owned
            or scope.host_networking_allowed
        ):
            raise AdapterOwnershipError(
                "fault adapter requires the context's project-owned sandbox scope"
            )
        return self._projected(
            context,
            "fault_matrix",
            ("fault_sequence.json", "fault_command_log.jsonl"),
            scenario_ids=tuple(scenario.id for scenario in scenarios),
            fault_target_kind=scope.kind.value,
            owned_resource_ids=scope.resource_ids,
            host_networking_allowed=False,
        )

    def recovery(self, context: ExecutionContext) -> StepResult:
        projected = self._projected(context, "recovery", ("fault_sequence.json",))
        if self.entrypoints.live_probe is None:
            return projected
        record = self._require_started(context)
        assert record.state is not None
        probe = self.entrypoints.live_probe(
            state=dict(record.state),
            requested_nodes=context.requested_nodes,
        )
        if not isinstance(probe, dict):
            raise GateAdapterError("legacy live probe must return an observation object")
        if probe.get("observed_nodes") != context.requested_nodes:
            raise GateAdapterError(
                "legacy live probe did not preserve the exact requested node count: "
                f"requested={context.requested_nodes}, observed={probe.get('observed_nodes')}"
            )
        record.live_probe_result = dict(probe)
        return StepResult.passed(
            context,
            "recovery",
            artifact_paths=projected.artifact_paths,
            details={
                **dict(projected.details),
                "live_probe": probe,
                "probe_before_cleanup": True,
            },
        )

    def validate(
        self,
        context: ExecutionContext,
        artifacts: tuple[ArtifactSpec, ...],
    ) -> StepResult:
        raw_names = tuple(artifact.raw_name for artifact in artifacts)
        if len(set(raw_names)) != len(raw_names):
            raise AdapterCollisionError("compiled raw artifact names must be unique")
        paths = tuple(
            _confined(
                self._record(context).paths.runtime_dir,
                self._record(context).paths.runtime_dir / raw_name,
                allow_root=False,
            )
            for raw_name in raw_names
        )
        return StepResult.passed(
            context,
            "artifact_validation",
            artifact_paths=tuple(path for path in paths if path.exists()),
            details={
                "adapter_mode": self._PROJECTION_MODE,
                "raw_artifact_names": raw_names,
                "observed_artifact_count": sum(path.exists() for path in paths),
                "admission_evidence": False,
                "reason": (
                    "Legacy artifact paths are characterized here; independent "
                    "evidence admission remains a separate boundary."
                ),
            },
        )

    def analyze(self, context: ExecutionContext) -> StepResult:
        return self._projected(context, "analysis", ("analysis_summary.json",))

    def render(
        self,
        context: ExecutionContext,
        surfaces: tuple[ReportSurface, ...],
    ) -> StepResult:
        return self._projected(
            context,
            "report",
            ("report_index.json",),
            report_surfaces=tuple(surface.id for surface in surfaces),
        )

    def cleanup(self, context: ExecutionContext) -> StepResult:
        record = self._get_record(context)
        if record is None:
            return StepResult.passed(
                context,
                "cleanup",
                details={
                    "adapter_mode": self._PROJECTION_MODE,
                    "cleanup_delegated": False,
                    "reason": "no owned legacy runtime was started",
                    "admission_evidence": False,
                },
            )
        with self._lock:
            if record.cleanup_attempted:
                raise AdapterCollisionError(
                    f"cleanup already attempted for run_id {context.run_id!r}"
                )
            record.cleanup_attempted = True
        if not record.runtime_started or not record.paths.state_path.exists():
            return StepResult.passed(
                context,
                "cleanup",
                details={
                    "adapter_mode": self._PROJECTION_MODE,
                    "cleanup_delegated": False,
                    "reason": "no owned legacy runtime state exists",
                    "admission_evidence": False,
                },
            )

        phase, scenario, _ = self._require_profile(context)
        runtime_run_id: Optional[str] = None
        if isinstance(record.state, dict):
            runtime = record.state.get("runtime")
            if isinstance(runtime, dict) and isinstance(runtime.get("run_id"), str):
                runtime_run_id = runtime["run_id"]
        _load_owned_state(
            record.paths.state_path,
            phase=phase,
            scenario=scenario,
            expected_run_id=runtime_run_id,
        )
        with record.setup_timeline.span(
            "cleanup",
            "cleanup",
            {"node_count": context.requested_nodes},
        ):
            result = self.entrypoints.cleanup(
                state_path=record.paths.state_path,
                artifacts_dir=record.paths.runtime_dir,
                out_path=record.paths.cleanup_path,
            )
        if not isinstance(result, dict):
            raise GateAdapterError("legacy cleanup_scenario must return a report object")
        record.cleanup_result = result
        details = {
            "adapter_mode": self._PROJECTION_MODE,
            "delegated_entrypoint": "cleanup_scenario",
            "cleanup_delegated": True,
            "legacy_cleanup_status": result.get("status", "MISSING"),
            "admission_evidence": False,
        }
        if result.get("status") != "PASS":
            return StepResult.failed(
                context,
                "cleanup",
                "legacy cleanup did not PASS",
                details=details,
            )
        artifact_paths = (
            (record.paths.cleanup_path,) if record.paths.cleanup_path.exists() else ()
        )
        return StepResult.passed(
            context,
            "cleanup",
            artifact_paths=artifact_paths,
            details=details,
        )

    def _projected(
        self,
        context: ExecutionContext,
        step_id: str,
        artifact_names: tuple[str, ...],
        **details: Any,
    ) -> StepResult:
        record = self._require_started(context)
        paths = tuple(
            _confined(
                record.paths.runtime_dir,
                record.paths.runtime_dir / name,
                allow_root=False,
            )
            for name in artifact_names
        )
        return StepResult.passed(
            context,
            step_id,
            artifact_paths=tuple(path for path in paths if path.exists()),
            details={
                "adapter_mode": self._PROJECTION_MODE,
                "delegated_entrypoint": "create_scenario",
                "projected_artifact_names": artifact_names,
                "admission_evidence": False,
                **details,
            },
        )

    def _record(self, context: ExecutionContext) -> _LegacyRun:
        paths = LegacyRuntimePaths.under(context.artifact_root)
        with self._lock:
            existing = self._runs.get(context.run_id)
            if existing is not None:
                if (
                    existing.ownership_id != context.ownership_id
                    or existing.provenance_id != context.provenance_id
                    or existing.paths != paths
                ):
                    raise AdapterCollisionError(
                        f"run_id {context.run_id!r} is already bound to another owner"
                    )
                return existing
            record = _LegacyRun(
                ownership_id=context.ownership_id,
                provenance_id=context.provenance_id,
                paths=paths,
            )
            self._runs[context.run_id] = record
            return record

    def _get_record(self, context: ExecutionContext) -> Optional[_LegacyRun]:
        with self._lock:
            record = self._runs.get(context.run_id)
            if record is None:
                return None
            if (
                record.ownership_id != context.ownership_id
                or record.provenance_id != context.provenance_id
            ):
                raise AdapterOwnershipError(
                    f"run_id {context.run_id!r} is owned by another execution"
                )
            return record

    def _require_started(self, context: ExecutionContext) -> _LegacyRun:
        record = self._get_record(context)
        if record is None or not record.runtime_started or record.state is None:
            raise GateAdapterError(
                f"legacy runtime has not started for run_id {context.run_id!r}"
            )
        return record

    def execution_snapshot(
        self,
        *,
        run_id: str,
        ownership_id: str,
        provenance_id: str,
    ) -> LegacyExecutionSnapshot:
        """Return immutable execution observations without exposing adapter state."""

        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                raise AdapterOwnershipError(f"run_id {run_id!r} has no adapter execution")
            if (
                record.ownership_id != ownership_id
                or record.provenance_id != provenance_id
            ):
                raise AdapterOwnershipError(
                    f"run_id {run_id!r} is owned by another execution"
                )
            return LegacyExecutionSnapshot(
                run_id=run_id,
                ownership_id=ownership_id,
                provenance_id=provenance_id,
                state=freeze_json(record.state) if record.state is not None else None,
                preflight_result=(
                    freeze_json(record.preflight_result)
                    if record.preflight_result is not None
                    else None
                ),
                live_probe_result=(
                    freeze_json(record.live_probe_result)
                    if record.live_probe_result is not None
                    else None
                ),
                cleanup_result=(
                    freeze_json(record.cleanup_result)
                    if record.cleanup_result is not None
                    else None
                ),
                setup_segments=tuple(
                    freeze_json(segment) for segment in record.setup_timeline.segments
                ),
            )

    def adapter_bundle(self) -> AdapterBundle:
        return AdapterBundle(
            runtime=self,
            workload=self,
            management=self,
            fault=self,
            artifact_validation=self,
            analysis=self,
            report=self,
        )

    @staticmethod
    def _require_profile(
        context: ExecutionContext,
    ) -> tuple[str, str, str]:
        if (
            not context.runtime_phase
            or not context.runtime_scenario
            or not context.config_template
        ):
            raise GateAdapterError(
                "compiled Gate plan has no compatible legacy runtime profile; "
                "the adapter will not silently downscale"
            )
        return (
            context.runtime_phase,
            context.runtime_scenario,
            context.config_template,
        )


def build_legacy_adapter_bundle(
    entrypoints: Optional[LegacyRuntimeEntrypoints] = None,
) -> AdapterBundle:
    adapter = LegacyGateAdapter(entrypoints=entrypoints)
    return adapter.adapter_bundle()


# Compatibility spelling for callers that think in terms of the whole bundle.
build_legacy_adapters = build_legacy_adapter_bundle
