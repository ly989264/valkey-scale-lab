#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402


STAGE_ID = "L06_SMALL_REAL_SCENARIO_AUDIT_PARITY"
RUN_ID = "L06_SMALL_REAL_SCENARIO_AUDIT_PARITY-small-real-parity-v1"
CREATED_AT = "2026-06-30T00:00:00Z"
RENDERED_SUFFIXES = {".html", ".csv", ".svg", ".md"}
COMMAND_FORBIDDEN_TOKENS = {"P14_SCALE_1000_OPTIN_DRYRUN", "VSLAB_ALLOW_1000_DRYRUN"}


@dataclass(frozen=True)
class SurfaceSpec:
    surface: str
    phase_id: str
    scenario: str
    evidence_path: str
    cleanup_path: str
    metric_paths: tuple[str, ...] = ()
    expected_nodes: int | None = 6
    min_nodes_observed: int | None = None
    expected_data_path: str | None = "PASS"
    producer: str = "scripts/valkey_e2e_gate.py"
    evidence_class: str = "real_valkey"


SURFACES = [
    SurfaceSpec(
        "cluster_smoke",
        "P03_LOCAL_DOCKER_VALKEY",
        "cluster_smoke",
        "artifacts/phases/P03_LOCAL_DOCKER_VALKEY/valkey_e2e_evidence.json",
        "artifacts/phases/P03_LOCAL_DOCKER_VALKEY/cleanup_report.json",
    ),
    SurfaceSpec(
        "management_ops",
        "P04_CLUSTER_MANAGEMENT_OPS",
        "management_ops",
        "artifacts/phases/P04_CLUSTER_MANAGEMENT_OPS/valkey_e2e_evidence.json",
        "artifacts/phases/P04_CLUSTER_MANAGEMENT_OPS/cleanup_report.json",
        ("artifacts/phases/P04_CLUSTER_MANAGEMENT_OPS/management_ops_report.json",),
    ),
    SurfaceSpec(
        "workload_smoke",
        "P05_WORKLOAD_ENGINE",
        "workload_smoke",
        "artifacts/phases/P05_WORKLOAD_ENGINE/valkey_e2e_evidence.json",
        "artifacts/phases/P05_WORKLOAD_ENGINE/cleanup_report.json",
        ("artifacts/phases/P05_WORKLOAD_ENGINE/workload_report.json",),
    ),
    SurfaceSpec(
        "observability_smoke",
        "P06_OBSERVABILITY_METRICS",
        "observability_smoke",
        "artifacts/phases/P06_OBSERVABILITY_METRICS/valkey_e2e_evidence.json",
        "artifacts/phases/P06_OBSERVABILITY_METRICS/cleanup_report.json",
        (
            "artifacts/phases/P06_OBSERVABILITY_METRICS/metrics_timeseries.jsonl",
            "artifacts/phases/P06_OBSERVABILITY_METRICS/events.jsonl",
        ),
    ),
    SurfaceSpec(
        "fault_sandbox",
        "P07_FAULT_INJECTION_SANDBOX",
        "fault_sandbox",
        "artifacts/phases/P07_FAULT_INJECTION_SANDBOX/valkey_e2e_evidence.json",
        "artifacts/phases/P07_FAULT_INJECTION_SANDBOX/cleanup_report.json",
        ("artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json",),
        expected_data_path="SKIPPED_WITH_REASON",
        producer="scripts/fault_safety_gate.py",
    ),
    SurfaceSpec(
        "failover_primary_stop",
        "P08_FAILOVER_SPLIT_BRAIN",
        "primary_stop_failover",
        "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/valkey_e2e_evidence.json",
        "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/cleanup_report.json",
        (
            "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json",
            "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/fault_report.json",
            "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/state_failover.json",
        ),
        expected_nodes=None,
        min_nodes_observed=5,
        expected_data_path="PASS",
        producer="scripts/fault_failover_gate.py",
    ),
    SurfaceSpec(
        "stability_soak",
        "P11_STABILITY_SOAK",
        "stability_soak_smoke",
        "artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json",
        "artifacts/phases/P11_STABILITY_SOAK/cleanup_report.json",
        (
            "artifacts/phases/P11_STABILITY_SOAK/stability_report.json",
            "artifacts/phases/P11_STABILITY_SOAK/stability_metrics.jsonl",
            "artifacts/phases/P11_STABILITY_SOAK/stability_baseline_comparison.json",
        ),
    ),
    SurfaceSpec(
        "cleanup",
        "P03_P11_SMALL_REAL_CLEANUP",
        "cleanup",
        "artifacts/phases/P03_LOCAL_DOCKER_VALKEY/cleanup_report.json",
        "artifacts/phases/P03_LOCAL_DOCKER_VALKEY/cleanup_report.json",
        (
            "artifacts/phases/P04_CLUSTER_MANAGEMENT_OPS/cleanup_report.json",
            "artifacts/phases/P05_WORKLOAD_ENGINE/cleanup_report.json",
            "artifacts/phases/P06_OBSERVABILITY_METRICS/cleanup_report.json",
            "artifacts/phases/P07_FAULT_INJECTION_SANDBOX/cleanup_report.json",
            "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/cleanup_report.json",
            "artifacts/phases/P09_ANALYSIS_REPORTING/cleanup_report.json",
            "artifacts/phases/P10_MULTI_HOST_ORCHESTRATION/cleanup_report.json",
            "artifacts/phases/P11_STABILITY_SOAK/cleanup_report.json",
        ),
        expected_nodes=None,
        expected_data_path=None,
        producer="valkey-scale-lab",
        evidence_class="source_artifact",
    ),
]

SCHEMA_BY_ARTIFACT_TYPE = {
    "valkey_e2e_evidence": "schemas/artifact/valkey_e2e_evidence.schema.json",
    "cleanup_report": "schemas/artifact/cleanup_report.schema.json",
    "management_ops_report": "schemas/artifact/management_ops_report.schema.json",
    "workload_report": "schemas/artifact/workload_report.schema.json",
    "metric_sample": "schemas/artifact/metric_sample.schema.json",
    "event": "schemas/artifact/event.schema.json",
    "fault_report": "schemas/artifact/fault_report.schema.json",
    "failover_report": "schemas/artifact/failover_report.schema.json",
    "analysis_summary": "schemas/artifact/analysis_summary.schema.json",
    "report_index": "schemas/artifact/report_index.schema.json",
    "stability_report": "schemas/artifact/stability_report.schema.json",
    "small_real_parity_audit": "schemas/artifact/small_real_parity_audit.schema.json",
    "metric_catalog": "schemas/artifact/metric_catalog.schema.json",
    "coverage_matrix": "schemas/artifact/coverage_matrix.schema.json",
    "loop_report_index": "schemas/artifact/loop_report_index.schema.json",
}

FAKE_METRICS = {
    "cluster_smoke": ["cluster_smoke.real_evidence.nodes_observed", "cluster_smoke.real_evidence.data_path_result"],
    "management_ops": ["management_ops.operation.meet.duration_seconds", "management_ops.operation.remove_node.status"],
    "workload_smoke": ["workload_smoke.achieved_qps", "workload_smoke.latency.p95_ms"],
    "observability_smoke": ["observability_smoke.metrics.sample_count", "observability_smoke.events.count"],
    "fault_sandbox": ["fault_sandbox.safety.host_network_mutated", "fault_sandbox.observed_impact"],
    "failover_primary_stop": ["failover_primary_stop.failover_latency_ms", "failover_primary_stop.split_brain_duration_ms"],
    "stability_soak": ["stability_soak.duration_seconds", "stability_soak.baseline.max_memory_growth_bytes"],
    "cleanup": ["cleanup.resources_remaining", "cleanup.action_count"],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path | str) -> str:
    path = Path(path)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def read_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def nested_get(payload: Any, pointer: str) -> Any:
    current = payload
    for part in pointer.strip("$").strip(".").split("."):
        if not part:
            continue
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current


class SmallRealParityAudit:
    def __init__(self, root: Path, *, require_fake: bool, require_real: bool, validate_report_views: bool) -> None:
        self.root = root
        self.require_fake = require_fake
        self.require_real = require_real
        self.validate_report_views = validate_report_views
        self.findings: list[dict[str, Any]] = []
        self.finding_seq = 0
        self.sources: dict[str, dict[str, Any]] = {}
        self.metrics: list[dict[str, Any]] = []

    def finding(self, *, severity: str, category: str, blocking: bool, description: str, evidence: list[str]) -> None:
        self.finding_seq += 1
        self.findings.append(
            {
                "id": f"SRP-{self.finding_seq:04d}",
                "severity": severity,
                "category": category,
                "blocking": blocking,
                "description": description,
                "evidence": evidence,
            }
        )

    def source_meta(self, path_text: str) -> dict[str, Any]:
        path_text = rel(self.root, path_text)
        if path_text in self.sources:
            return self.sources[path_text]
        path = self.root / path_text
        exists = path.exists()
        payload: Any = {}
        json_valid = False
        artifact_type = "missing"
        schema_path = ""
        schema_valid = False
        schema_errors: list[str] = []
        status: str | None = None
        producer: str | None = None
        run_id: str | None = None
        if exists:
            try:
                if path.suffix == ".jsonl":
                    rows = read_jsonl(path)
                    payload = rows[0] if rows else {}
                    json_valid = bool(rows)
                else:
                    payload = load_json(path)
                    json_valid = True
            except Exception as exc:  # noqa: BLE001 - reported as an audit finding.
                self.finding(
                    severity="high",
                    category="invalid_json",
                    blocking=True,
                    description="Source artifact is not valid JSON/JSONL",
                    evidence=[path_text, repr(exc)],
                )
        if isinstance(payload, dict):
            artifact_type = str(payload.get("artifact_type") or ("jsonl" if path.suffix == ".jsonl" else "json"))
            status = payload.get("status")
            producer_payload = payload.get("producer")
            if isinstance(producer_payload, dict):
                producer = str(producer_payload.get("name") or "")
            run_id = payload.get("run_id")
            schema_path = SCHEMA_BY_ARTIFACT_TYPE.get(artifact_type, "")
            if schema_path and json_valid:
                schema = load_json(self.root / schema_path)
                if path.suffix == ".jsonl":
                    rows = read_jsonl(path)
                    schema_errors = [
                        error
                        for idx, row in enumerate(rows, start=1)
                        for error in validate(row, schema, f"$[line {idx}]")
                    ]
                else:
                    schema_errors = validate(payload, schema)
                schema_valid = not schema_errors
                if schema_errors:
                    self.finding(
                        severity="high",
                        category="schema_invalid",
                        blocking=True,
                        description="Source artifact failed schema validation",
                        evidence=[path_text, *schema_errors[:5]],
                    )
            elif schema_path == "":
                schema_valid = json_valid
        meta = {
            "path": path_text,
            "exists": exists,
            "sha256": sha256_file(path) if exists else "MISSING",
            "artifact_type": artifact_type,
            "schema_path": schema_path,
            "schema_valid": schema_valid,
            "schema_errors": schema_errors,
            "status": status,
            "producer": producer,
            "run_id": run_id,
            "source_of_truth": path.suffix.lower() not in RENDERED_SUFFIXES,
        }
        if not exists:
            self.finding(
                severity="high",
                category="missing_source_artifact",
                blocking=True,
                description="Required source artifact is missing",
                evidence=[path_text],
            )
        self.sources[path_text] = meta
        return meta

    def load_json(self, path_text: str) -> dict[str, Any]:
        self.source_meta(path_text)
        path = self.root / path_text
        if not path.exists():
            return {}
        payload = load_json(path)
        return payload if isinstance(payload, dict) else {}

    def read_jsonl(self, path_text: str) -> list[Any]:
        self.source_meta(path_text)
        path = self.root / path_text
        if not path.exists():
            return []
        return read_jsonl(path)

    def missing_semantics(self, status: str, reason: str = "") -> dict[str, str]:
        if status in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"}:
            if not reason:
                self.finding(
                    severity="high",
                    category="missing_reason_absent",
                    blocking=True,
                    description="Missing, skipped, or no-baseline metric lacks a reason",
                    evidence=[status],
                )
            return {"status": status, "reason": reason}
        return {"status": "PRESENT", "reason": ""}

    def add_metric(
        self,
        *,
        name: str,
        surface: str,
        unit: str,
        source_artifact: str,
        source_pointer: str,
        value: Any,
        value_status: str = "MEASURED",
        reason: str = "",
        scenario: str | None = None,
        node_count_scope: str = "6",
        evidence_layer: str = "small-real",
        evidence_class: str = "source_artifact",
        real_valkey_coverage: bool = False,
    ) -> None:
        meta = self.source_meta(source_artifact)
        measured = value_status in {"MEASURED", "PASS"} and value is not None
        if measured and Path(source_artifact).suffix.lower() in RENDERED_SUFFIXES:
            self.finding(
                severity="high",
                category="rendered_view_metric_source",
                blocking=True,
                description="Rendered report view cannot be a measured metric source",
                evidence=[name, source_artifact],
            )
        self.metrics.append(
            {
                "name": name,
                "surface": surface,
                "unit": unit,
                "source_artifact": rel(self.root, source_artifact),
                "source_sha256": meta["sha256"],
                "source_pointer": source_pointer,
                "scenario": scenario,
                "node_count_scope": node_count_scope,
                "evidence_layer": evidence_layer,
                "evidence_class": evidence_class,
                "real_valkey_coverage": real_valkey_coverage,
                "value_status": value_status,
                "value": value,
                "missing_semantics": self.missing_semantics(value_status, reason),
            }
        )

    def validate_real_evidence(self, spec: SurfaceSpec) -> dict[str, Any]:
        if spec.evidence_class == "source_artifact":
            return {
                "present": True,
                "evidence_class": "source_artifact",
                "real_valkey_coverage": False,
                "source_artifacts": [spec.evidence_path, *spec.metric_paths],
                "checks": [{"name": "cleanup_source_artifact_surface", "status": "PASS"}],
            }
        evidence = self.load_json(spec.evidence_path)
        checks: list[dict[str, Any]] = []

        def check(name: str, ok: bool, actual: Any) -> None:
            checks.append({"name": name, "status": "PASS" if ok else "FAIL", "actual": actual})
            if not ok:
                self.finding(
                    severity="high",
                    category="invalid_real_evidence",
                    blocking=True,
                    description=f"Real evidence check failed: {name}",
                    evidence=[spec.surface, spec.evidence_path, repr(actual)],
                )

        producer = evidence.get("producer") if isinstance(evidence.get("producer"), dict) else {}
        versions = evidence.get("valkey_versions") if isinstance(evidence.get("valkey_versions"), list) else []
        nodes_observed = evidence.get("nodes_observed")
        check("producer", producer.get("name") == spec.producer, producer.get("name"))
        check("status", evidence.get("status") == "PASS", evidence.get("status"))
        check("real_valkey", evidence.get("real_valkey") is True, evidence.get("real_valkey"))
        check("version_prefix", bool(versions) and all(str(version).startswith("9.1.") for version in versions), versions)
        if spec.expected_nodes is not None:
            check("nodes_observed", nodes_observed == spec.expected_nodes, nodes_observed)
        if spec.min_nodes_observed is not None:
            check("nodes_observed_minimum", isinstance(nodes_observed, int) and nodes_observed >= spec.min_nodes_observed, nodes_observed)
        check("cluster_state_observed", evidence.get("cluster_state_observed") == "ok", evidence.get("cluster_state_observed"))
        if spec.expected_data_path is not None:
            check("data_path_result", evidence.get("data_path_result") == spec.expected_data_path, evidence.get("data_path_result"))
        cleanup = evidence.get("cleanup") if isinstance(evidence.get("cleanup"), dict) else {}
        check("evidence_cleanup_status", cleanup.get("status") == "PASS", cleanup)

        self.add_metric(
            name=f"{spec.surface}.real_evidence.nodes_observed",
            surface=spec.surface,
            unit="nodes",
            source_artifact=spec.evidence_path,
            source_pointer="$.nodes_observed",
            value=nodes_observed,
            scenario=evidence.get("scenario") or spec.scenario,
            node_count_scope=str(nodes_observed or spec.expected_nodes or "unknown"),
            evidence_class="real_valkey",
            real_valkey_coverage=True,
        )
        data_path = evidence.get("data_path_result")
        data_status = "PASS" if data_path == "PASS" else "SKIPPED_WITH_REASON" if data_path == "SKIPPED_WITH_REASON" else "FAIL"
        reason = "Fault/failover wrapper records liveness and cluster-state proof while data-path is intentionally skipped." if data_status == "SKIPPED_WITH_REASON" else ""
        self.add_metric(
            name=f"{spec.surface}.real_evidence.data_path_result",
            surface=spec.surface,
            unit="status",
            source_artifact=spec.evidence_path,
            source_pointer="$.data_path_result",
            value=None if data_status == "SKIPPED_WITH_REASON" else data_path,
            value_status=data_status,
            reason=reason,
            scenario=evidence.get("scenario") or spec.scenario,
            node_count_scope=str(nodes_observed or spec.expected_nodes or "unknown"),
            evidence_class="real_valkey",
            real_valkey_coverage=True,
        )
        return {
            "present": all(item["status"] == "PASS" for item in checks),
            "evidence_class": "real_valkey",
            "real_valkey_coverage": True,
            "source_artifacts": [spec.evidence_path],
            "checks": checks,
        }

    def validate_cleanup(self, spec: SurfaceSpec) -> dict[str, Any]:
        cleanup = self.load_json(spec.cleanup_path)
        resources = cleanup.get("resources_remaining")
        remaining_count = len(resources) if isinstance(resources, list) else -1
        ok = cleanup.get("status") == "PASS" and remaining_count == 0
        if not ok:
            self.finding(
                severity="high",
                category="cleanup_invalid",
                blocking=True,
                description="Cleanup report is not PASS with zero residual resources",
                evidence=[spec.surface, spec.cleanup_path, repr(cleanup.get("status")), repr(resources)],
            )
        self.add_metric(
            name=f"{spec.surface}.cleanup.resources_remaining",
            surface=spec.surface,
            unit="count",
            source_artifact=spec.cleanup_path,
            source_pointer="$.resources_remaining",
            value=remaining_count if remaining_count >= 0 else None,
            value_status="MEASURED" if remaining_count >= 0 else "MISSING",
            reason="" if remaining_count >= 0 else "cleanup_report lacks resources_remaining",
            scenario=spec.scenario,
            evidence_class="source_artifact",
            real_valkey_coverage=False,
        )
        return {
            "status": "PASS" if ok else "FAIL",
            "resources_remaining": remaining_count if remaining_count >= 0 else 999999,
            "source_artifact": spec.cleanup_path,
        }

    def add_fake_metrics(self, spec: SurfaceSpec) -> dict[str, Any]:
        metric_names = FAKE_METRICS[spec.surface]
        source = f"artifacts/loop_engineering/stages/{STAGE_ID}/current_harness_plan.json"
        for idx, name in enumerate(metric_names):
            self.add_metric(
                name=name,
                surface=spec.surface,
                unit="fixture",
                source_artifact=source,
                source_pointer=f"$.new_tests.{idx}",
                value=None,
                value_status="SKIPPED_WITH_REASON",
                reason="Deterministic fake fixture exercises extraction shape but cannot satisfy real Valkey coverage.",
                scenario="fake",
                node_count_scope="fake",
                evidence_layer="fake",
                evidence_class="fake",
                real_valkey_coverage=False,
            )
        return {
            "present": bool(metric_names),
            "evidence_class": "fake",
            "real_valkey_coverage": False,
            "metric_names": metric_names,
            "source_artifact": source,
        }

    def add_surface_specific_metrics(self, spec: SurfaceSpec) -> None:
        for metric_path in spec.metric_paths:
            self.source_meta(metric_path)
        if spec.surface == "management_ops":
            payload = self.load_json(spec.metric_paths[0])
            for idx, op in enumerate(payload.get("operations", [])):
                status = op.get("status")
                skipped = status == "SKIPPED_WITH_REASON"
                self.add_metric(
                    name=f"management_ops.operation.{op.get('operation')}.duration_seconds",
                    surface=spec.surface,
                    unit="seconds",
                    source_artifact=spec.metric_paths[0],
                    source_pointer=f"$.operations.{idx}.duration_seconds",
                    value=None if skipped else op.get("duration_seconds"),
                    value_status="SKIPPED_WITH_REASON" if skipped else "MEASURED",
                    reason=op.get("reason", ""),
                    scenario=spec.scenario,
                )
        elif spec.surface == "workload_smoke":
            payload = self.load_json(spec.metric_paths[0])
            for name, unit, pointer in [
                ("workload_smoke.achieved_qps", "qps", "$.achieved_qps"),
                ("workload_smoke.latency.p95_ms", "ms", "$.latency.p95"),
                ("workload_smoke.errors.total", "count", "$.errors.total"),
            ]:
                self.add_metric(
                    name=name,
                    surface=spec.surface,
                    unit=unit,
                    source_artifact=spec.metric_paths[0],
                    source_pointer=pointer,
                    value=nested_get(payload, pointer),
                    scenario=spec.scenario,
                )
            for idx, window in enumerate(payload.get("timing_windows", [])):
                if window.get("status") == "SKIPPED_WITH_REASON":
                    self.add_metric(
                        name=f"workload_smoke.timing_window.{window.get('name')}.duration_seconds",
                        surface=spec.surface,
                        unit="seconds",
                        source_artifact=spec.metric_paths[0],
                        source_pointer=f"$.timing_windows.{idx}.duration_seconds",
                        value=None,
                        value_status="SKIPPED_WITH_REASON",
                        reason=window.get("reason", ""),
                        scenario=spec.scenario,
                    )
        elif spec.surface == "observability_smoke":
            samples = self.read_jsonl(spec.metric_paths[0])
            events = self.read_jsonl(spec.metric_paths[1])
            self.add_metric(
                name="observability_smoke.metrics.sample_count",
                surface=spec.surface,
                unit="count",
                source_artifact=spec.metric_paths[0],
                source_pointer="$",
                value=len(samples),
                scenario=spec.scenario,
            )
            self.add_metric(
                name="observability_smoke.events.count",
                surface=spec.surface,
                unit="count",
                source_artifact=spec.metric_paths[1],
                source_pointer="$",
                value=len(events),
                scenario=spec.scenario,
            )
        elif spec.surface == "fault_sandbox":
            payload = self.load_json(spec.metric_paths[0])
            safety = payload.get("safety_checks", {})
            for key in ["sandbox_only", "host_network_mutated", "global_firewall_mutated", "fault_state_cleared"]:
                expected = True if key in {"sandbox_only", "fault_state_cleared"} else False
                actual = safety.get(key)
                if actual is not expected:
                    self.finding(
                        severity="high",
                        category="fault_safety_invalid",
                        blocking=True,
                        description="Fault safety check has unsafe value",
                        evidence=[key, repr(actual)],
                    )
                self.add_metric(
                    name=f"fault_sandbox.safety.{key}",
                    surface=spec.surface,
                    unit="boolean",
                    source_artifact=spec.metric_paths[0],
                    source_pointer=f"$.safety_checks.{key}",
                    value=actual,
                    scenario=spec.scenario,
                )
            impact = payload.get("faults", [{}])[0].get("observed_impact", {})
            status = impact.get("status", "MISSING")
            self.add_metric(
                name="fault_sandbox.observed_impact",
                surface=spec.surface,
                unit="status",
                source_artifact=spec.metric_paths[0],
                source_pointer="$.faults.0.observed_impact",
                value=None if status == "SKIPPED_WITH_REASON" else status,
                value_status=status,
                reason=impact.get("reason", ""),
                scenario=spec.scenario,
            )
        elif spec.surface == "failover_primary_stop":
            report = self.load_json(spec.metric_paths[0])
            fault_report = self.load_json(spec.metric_paths[1])
            state = self.load_json(spec.metric_paths[2])
            state_nodes = state.get("nodes") if isinstance(state.get("nodes"), list) else []
            if len(state_nodes) != 6:
                self.finding(
                    severity="high",
                    category="failover_initial_state_invalid",
                    blocking=True,
                    description="Failover initial state does not record six nodes",
                    evidence=[spec.metric_paths[2], str(len(state_nodes))],
                )
            summary = report.get("summary", {})
            self.add_metric(
                name="failover_primary_stop.initial_nodes",
                surface=spec.surface,
                unit="nodes",
                source_artifact=spec.metric_paths[2],
                source_pointer="$.nodes",
                value=len(state_nodes),
                scenario=spec.scenario,
            )
            self.add_metric(
                name="failover_primary_stop.promotion_observed",
                surface=spec.surface,
                unit="boolean",
                source_artifact=spec.metric_paths[0],
                source_pointer="$.summary.promotion_observed",
                value=summary.get("promotion_observed"),
                scenario=spec.scenario,
            )
            latency = (report.get("failovers") or [{}])[0].get("failover_latency_ms")
            self.add_metric(
                name="failover_primary_stop.failover_latency_ms",
                surface=spec.surface,
                unit="ms",
                source_artifact=spec.metric_paths[0],
                source_pointer="$.failovers.0.failover_latency_ms",
                value=latency,
                scenario=spec.scenario,
            )
            split = summary.get("split_brain_duration_ms", {})
            self.add_metric(
                name="failover_primary_stop.split_brain_duration_ms",
                surface=spec.surface,
                unit="ms",
                source_artifact=spec.metric_paths[0],
                source_pointer="$.summary.split_brain_duration_ms",
                value=split.get("value"),
                value_status=split.get("status", "MISSING"),
                reason=split.get("reason", "missing split-brain duration"),
                scenario=spec.scenario,
            )
            safety = fault_report.get("safety_checks", {})
            for key in ["sandbox_only", "host_network_mutated", "global_firewall_mutated", "fault_state_cleared"]:
                expected = True if key in {"sandbox_only", "fault_state_cleared"} else False
                actual = safety.get(key)
                if actual is not expected:
                    self.finding(
                        severity="high",
                        category="failover_fault_safety_invalid",
                        blocking=True,
                        description="Failover fault safety check has unsafe value",
                        evidence=[key, repr(actual)],
                    )
        elif spec.surface == "stability_soak":
            report = self.load_json(spec.metric_paths[0])
            self.read_jsonl(spec.metric_paths[1])
            self.load_json(spec.metric_paths[2])
            for name, unit, pointer in [
                ("stability_soak.duration_seconds", "seconds", "$.duration_seconds"),
                ("stability_soak.leaks.max_growth_bytes", "bytes", "$.summary.leaks.max_growth_bytes"),
                ("stability_soak.restart_delta_total", "count", "$.summary.restarts.total_restart_delta"),
                ("stability_soak.workload.error_count", "count", "$.summary.workload.error_count"),
            ]:
                self.add_metric(
                    name=name,
                    surface=spec.surface,
                    unit=unit,
                    source_artifact=spec.metric_paths[0],
                    source_pointer=pointer,
                    value=nested_get(report, pointer),
                    scenario=spec.scenario,
                )
            for idx, comparison in enumerate(report.get("summary", {}).get("baseline", {}).get("comparisons", [])):
                status = comparison.get("status", "MEASURED")
                self.add_metric(
                    name=f"stability_soak.baseline.{comparison.get('metric')}",
                    surface=spec.surface,
                    unit="count",
                    source_artifact=spec.metric_paths[0],
                    source_pointer=f"$.summary.baseline.comparisons.{idx}",
                    value=comparison.get("current_value") if status != "NO_BASELINE_YET" else None,
                    value_status=status,
                    reason="No previous stability baseline artifact exists." if status == "NO_BASELINE_YET" else "",
                    scenario=spec.scenario,
                )
        elif spec.surface == "cleanup":
            cleanup_paths = (spec.evidence_path, *spec.metric_paths)
            for path_text in cleanup_paths:
                cleanup = self.load_json(path_text)
                resources = cleanup.get("resources_remaining")
                actions = cleanup.get("cleanup_actions") or []
                remaining = len(resources) if isinstance(resources, list) else None
                self.add_metric(
                    name="cleanup.resources_remaining",
                    surface=spec.surface,
                    unit="count",
                    source_artifact=path_text,
                    source_pointer="$.resources_remaining",
                    value=remaining,
                    value_status="MEASURED" if remaining is not None else "MISSING",
                    reason="" if remaining is not None else "cleanup_report lacks resources_remaining",
                    scenario="cleanup",
                    evidence_class="source_artifact",
                )
                self.add_metric(
                    name="cleanup.action_count",
                    surface=spec.surface,
                    unit="count",
                    source_artifact=path_text,
                    source_pointer="$.cleanup_actions",
                    value=len(actions),
                    scenario="cleanup",
                    evidence_class="source_artifact",
                )

    def build_surfaces(self) -> list[dict[str, Any]]:
        surfaces: list[dict[str, Any]] = []
        for spec in SURFACES:
            fake = self.add_fake_metrics(spec)
            real = self.validate_real_evidence(spec)
            cleanup = self.validate_cleanup(spec)
            self.add_surface_specific_metrics(spec)
            surface_metrics = [metric["name"] for metric in self.metrics if metric["surface"] == spec.surface]
            if self.require_fake and not fake["present"]:
                self.finding(
                    severity="high",
                    category="fake_coverage_missing",
                    blocking=True,
                    description="Required fake surface coverage is absent",
                    evidence=[spec.surface],
                )
            if self.require_real and not real["present"]:
                self.finding(
                    severity="high",
                    category="real_coverage_missing",
                    blocking=True,
                    description="Required real surface coverage is absent",
                    evidence=[spec.surface],
                )
            surface_status = "PASS" if fake["present"] and real["present"] and cleanup["status"] == "PASS" else "FAIL"
            surfaces.append(
                {
                    "surface": spec.surface,
                    "phase_id": spec.phase_id,
                    "scenario": spec.scenario,
                    "status": surface_status,
                    "fake_coverage": fake,
                    "real_coverage": real,
                    "cleanup": cleanup,
                    "metrics": sorted(set(surface_metrics)),
                }
            )
        return surfaces

    def build_report_checks(self) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        catalog_path = "artifacts/loop_engineering/reports/metric_catalog.json"
        coverage_path = "artifacts/loop_engineering/reports/coverage_matrix.json"
        report_index_path = "artifacts/loop_engineering/reports/report_index.json"
        for path_text in [catalog_path, coverage_path, report_index_path]:
            self.source_meta(path_text)
        catalog = self.load_json(catalog_path)
        statuses = {metric.get("value_status") for metric in catalog.get("metrics", []) if isinstance(metric, dict)}
        for status in ["MEASURED", "MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"]:
            present = status in statuses
            checks.append({"name": f"metric_status_{status.lower()}_present", "status": "PASS" if present else "FAIL", "value": present})
            if not present:
                self.finding(
                    severity="high",
                    category="report_status_missing",
                    blocking=True,
                    description="Required metric status is absent from metric catalog",
                    evidence=[status, catalog_path],
                )
        if self.validate_report_views:
            for metric in catalog.get("metrics", []):
                if not isinstance(metric, dict):
                    continue
                measured = metric.get("value_status") in {"MEASURED", "PASS"} and metric.get("value") is not None
                source = str(metric.get("source_artifact", ""))
                if measured and Path(source).suffix.lower() in RENDERED_SUFFIXES:
                    self.finding(
                        severity="high",
                        category="rendered_view_metric_source",
                        blocking=True,
                        description="Measured metric is sourced from a rendered view",
                        evidence=[str(metric.get("name")), source],
                    )
            checks.append({"name": "rendered_views_not_measured_sources", "status": "PASS", "value": True})
        report_index = self.load_json(report_index_path)
        source_of_truth = report_index.get("source_of_truth")
        reports = report_index.get("reports") if isinstance(report_index.get("reports"), list) else []
        rendered_false = all(report.get("source_of_truth") is False for report in reports if isinstance(report, dict))
        checks.append({"name": "report_index_source_of_truth_false", "status": "PASS" if source_of_truth is False else "FAIL", "value": source_of_truth})
        checks.append({"name": "rendered_reports_source_of_truth_false", "status": "PASS" if rendered_false else "FAIL", "value": rendered_false})
        if source_of_truth is not False or not rendered_false:
            self.finding(
                severity="high",
                category="report_source_of_truth_invalid",
                blocking=True,
                description="Report index or rendered reports are incorrectly marked source-of-truth",
                evidence=[report_index_path],
            )
        command_guard = self.check_l06_commands()
        checks.append(command_guard)
        return checks

    def check_l06_commands(self) -> dict[str, Any]:
        command_log = self.root / "artifacts" / "loop_engineering" / "stages" / STAGE_ID / "commands.jsonl"
        if not command_log.exists():
            return {"name": "p14_forbidden_command_guard", "status": "SKIPPED_WITH_REASON", "reason": "L06 command log not present yet"}
        offending: list[str] = []
        for line in command_log.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            command_text = " ".join(str(part) for part in entry.get("command", []))
            env_text = json.dumps(entry.get("environment", {}), sort_keys=True)
            for token in COMMAND_FORBIDDEN_TOKENS:
                if token in command_text or token in env_text:
                    offending.append(token)
        if offending:
            self.finding(
                severity="high",
                category="p14_forbidden_command",
                blocking=True,
                description="L06 command log contains forbidden P14 execution or opt-in token",
                evidence=sorted(set(offending)),
            )
        return {
            "name": "p14_forbidden_command_guard",
            "status": "PASS" if not offending else "FAIL",
            "value": not offending,
            "forbidden_tokens": sorted(COMMAND_FORBIDDEN_TOKENS),
        }

    def build(self) -> dict[str, Any]:
        surfaces = self.build_surfaces()
        report_checks = self.build_report_checks()
        status_counts = Counter(metric["value_status"] for metric in self.metrics)
        blocking = [finding for finding in self.findings if finding["blocking"]]
        fake_surfaces = [surface for surface in surfaces if surface["fake_coverage"]["present"]]
        real_surfaces = [surface for surface in surfaces if surface["real_coverage"]["present"]]
        cleanup_pass = [surface for surface in surfaces if surface["cleanup"]["status"] == "PASS"]
        real_boundary = {
            "wrapper_producers": {
                "normal": "scripts/valkey_e2e_gate.py",
                "fault": "scripts/fault_safety_gate.py",
                "failover": "scripts/fault_failover_gate.py",
            },
            "version_prefix_required": "9.1.",
            "p08_expected_nodes": {
                "initial_state_nodes": 6,
                "post_fault_min_live_nodes": 5,
                "reason": "primary-stop failover evidence observes live nodes after the stopped primary is removed from the probe set",
            },
            "p14_real_valkey_coverage": False,
            "p14_execution_allowed": False,
        }
        result = {
            "schema_version": "v1",
            "artifact_type": "small_real_parity_audit",
            "stage_id": STAGE_ID,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": {"name": "scripts/audit_small_real_scenario_parity.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "summary": {
                "surface_count": len(surfaces),
                "required_surface_count": len(SURFACES),
                "fake_covered_count": len(fake_surfaces),
                "real_covered_count": len(real_surfaces),
                "cleanup_pass_count": len(cleanup_pass),
                "metric_count": len(self.metrics),
                "measured_count": status_counts["MEASURED"] + status_counts["PASS"],
                "missing_count": status_counts["MISSING"],
                "skipped_count": status_counts["SKIPPED_WITH_REASON"],
                "no_baseline_count": status_counts["NO_BASELINE_YET"],
                "blocking_findings_count": len(blocking),
            },
            "source_artifacts": sorted(self.sources.values(), key=lambda item: item["path"]),
            "surfaces": surfaces,
            "metrics": sorted(self.metrics, key=lambda item: (item["evidence_layer"], item["surface"], item["name"], item["source_artifact"])),
            "fake_real_parity": {
                "required_surfaces": [spec.surface for spec in SURFACES],
                "fake_surfaces": sorted(surface["surface"] for surface in fake_surfaces),
                "real_surfaces": sorted(surface["surface"] for surface in real_surfaces),
                "fake_can_satisfy_real": False,
            },
            "real_valkey_boundary": real_boundary,
            "report_checks": report_checks,
            "findings": self.findings,
        }
        return result


def validate_output(root: Path, artifact: dict[str, Any]) -> list[str]:
    return validate(artifact, load_json(root / "schemas/artifact/small_real_parity_audit.schema.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit six-node small-real scenario parity")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--require-fake", action="store_true")
    parser.add_argument("--require-real", action="store_true")
    parser.add_argument("--validate-report-views", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    audit = SmallRealParityAudit(
        root,
        require_fake=args.require_fake,
        require_real=args.require_real,
        validate_report_views=args.validate_report_views,
    )
    artifact = audit.build()
    schema_errors = validate_output(root, artifact)
    if schema_errors:
        for error in schema_errors:
            print(f"small_real_parity_audit schema error: {error}", file=sys.stderr)
        artifact["status"] = "FAIL"
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    status = artifact["status"]
    print(f"{status} small_real_parity_audit {rel(root, out)}")
    return 0 if status == "PASS" and not schema_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
