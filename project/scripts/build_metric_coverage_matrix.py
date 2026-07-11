#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402


LAYERS = ["fake", "small-real", "30", "50", "100", "1000-dry-run"]
SURFACES = [
    "cluster_build",
    "management",
    "workload",
    "observability",
    "fault",
    "failover",
    "stability",
    "cleanup",
    "scale",
    "report_visualization",
]
REPORT_VIEW_SUFFIXES = {".csv", ".html", ".md", ".svg"}
P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
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


class MetricCoverageBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.metrics: list[dict[str, Any]] = []
        self.findings: list[dict[str, Any]] = []
        self.finding_seq = 0
        self.source_cache: dict[str, dict[str, Any]] = {}

    def existing(self, path_text: str) -> bool:
        return (self.root / path_text).exists()

    def load_json(self, path_text: str) -> dict[str, Any] | None:
        path = self.root / path_text
        if not path.exists():
            return None
        return load_json(path)

    def source_meta(self, path_text: str) -> dict[str, Any]:
        path_text = rel(self.root, path_text)
        if path_text in self.source_cache:
            return self.source_cache[path_text]
        path = self.root / path_text
        payload: dict[str, Any] = {}
        if path.exists():
            if path.suffix == ".json":
                loaded = load_json(path)
                payload = loaded if isinstance(loaded, dict) else {}
            elif path.suffix == ".jsonl":
                rows = read_jsonl(path)
                payload = rows[0] if rows else {}
        meta = {
            "path": path_text,
            "exists": path.exists(),
            "sha256": sha256_file(path) if path.exists() else "MISSING",
            "artifact_type": str(payload.get("artifact_type") or ("report_view" if path.suffix in REPORT_VIEW_SUFFIXES else "artifact")),
            "phase_id": str(payload.get("phase_id") or self.phase_from_path(path_text) or "MISSING"),
            "run_id": payload.get("run_id"),
            "scenario": payload.get("scenario"),
            "node_count": payload.get("node_count") or payload.get("nodes_observed"),
            "dry_run_only": self.is_dry_run(payload, path_text),
        }
        self.source_cache[path_text] = meta
        return meta

    def phase_from_path(self, path_text: str) -> str | None:
        parts = Path(path_text).parts
        if len(parts) >= 3 and parts[0] == "artifacts" and parts[1] == "phases":
            return parts[2]
        return None

    def is_dry_run(self, payload: dict[str, Any], path_text: str) -> bool:
        if "1000_dryrun" in path_text or "scale_1000_dryrun" in path_text:
            return True
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
        return runtime.get("dry_run") is True or constraints.get("no_execution") is True

    def finding(
        self,
        *,
        severity: str,
        category: str,
        blocking: bool,
        description: str,
        evidence: list[str],
    ) -> None:
        self.finding_seq += 1
        self.findings.append(
            {
                "id": f"MC-{self.finding_seq:04d}",
                "severity": severity,
                "category": category,
                "blocking": blocking,
                "description": description,
                "evidence": evidence,
            }
        )

    def layer_for(self, *, node_count: Any, dry_run_only: bool, real_valkey: bool) -> str:
        try:
            count = int(node_count)
        except (TypeError, ValueError):
            count = 0
        if dry_run_only or count >= 1000:
            return "1000-dry-run"
        if count == 100:
            return "100"
        if count == 50:
            return "50"
        if count == 30:
            return "30"
        return "small-real" if real_valkey or count else "small-real"

    def missing_impact(self, *, status: str, surface: str, layer: str, source_artifact: str) -> str:
        if status == "NO_BASELINE_YET":
            return f"Trend and regression comparison for {surface} on {layer} cannot be evaluated until a prior baseline artifact exists."
        if status == "SKIPPED_WITH_REASON":
            return f"{surface} coverage for {layer} is intentionally excluded from real Valkey conclusions; see {source_artifact}."
        if status == "MISSING":
            return f"{surface} coverage for {layer} is incomplete and must not be inferred from reports or default values."
        return ""

    def missing_semantics(self, status: str, reason: str = "", impact: str = "") -> dict[str, str]:
        if status in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"}:
            return {"status": status, "reason": reason or status, "impact": impact or status}
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
        node_count_scope: str | None = None,
        evidence_layer: str | None = None,
        evidence_class: str = "source_artifact",
        real_valkey_coverage: bool = False,
        dry_run_only: bool | None = None,
        source_kind: str = "source_artifact",
    ) -> None:
        source_artifact = rel(self.root, source_artifact)
        meta = self.source_meta(source_artifact)
        dry = bool(meta["dry_run_only"]) if dry_run_only is None else dry_run_only
        layer = evidence_layer or self.layer_for(
            node_count=node_count_scope or meta.get("node_count"),
            dry_run_only=dry,
            real_valkey=real_valkey_coverage,
        )
        if layer == "1000-dry-run" and real_valkey_coverage:
            self.finding(
                severity="high",
                category="dry_run_counted_as_real",
                blocking=True,
                description="1000 dry-run metric cannot count as real Valkey coverage",
                evidence=[name, source_artifact],
            )
        if Path(source_artifact).suffix in REPORT_VIEW_SUFFIXES and evidence_class != "report_view":
            self.finding(
                severity="high",
                category="report_view_used_as_metric_source",
                blocking=True,
                description="Rendered report view cannot be a source metric artifact",
                evidence=[name, source_artifact],
            )
        if value_status in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"} and not reason:
            self.finding(
                severity="high",
                category="missing_reason_absent",
                blocking=True,
                description="Missing or skipped metric lacks reason",
                evidence=[name, source_artifact, value_status],
            )
        impact = self.missing_impact(status=value_status, surface=surface, layer=layer, source_artifact=source_artifact)
        self.metrics.append(
            {
                "name": name,
                "surface": surface,
                "unit": unit,
                "source_artifact": source_artifact,
                "source_sha256": meta["sha256"],
                "source_artifact_type": meta["artifact_type"],
                "source_kind": source_kind,
                "source_pointer": source_pointer,
                "phase_id": meta["phase_id"],
                "run_id": meta["run_id"],
                "scenario": scenario if scenario is not None else meta["scenario"],
                "node_count_scope": str(node_count_scope if node_count_scope is not None else meta.get("node_count") or "unknown"),
                "evidence_layer": layer,
                "evidence_class": evidence_class,
                "real_valkey_coverage": real_valkey_coverage,
                "dry_run_only": dry,
                "value_status": value_status,
                "value": value,
                "missing_semantics": self.missing_semantics(value_status, reason, impact),
                "impact": impact,
            }
        )

    def validate_real_evidence(self, path_text: str, expected_nodes: int | None = None) -> tuple[bool, dict[str, Any]]:
        payload = self.load_json(path_text) or {}
        data_path_result = payload.get("data_path_result")
        ok = (
            payload.get("real_valkey") is True
            and payload.get("status") == "PASS"
            and payload.get("probe_result") == "PASS"
            and payload.get("cluster_state_observed") == "ok"
            and data_path_result in {"PASS", "SKIPPED_WITH_REASON"}
            and all(str(v).startswith("9.1.") for v in payload.get("valkey_versions", []))
        )
        if expected_nodes is not None:
            ok = ok and payload.get("nodes_observed") == expected_nodes
        if not ok:
            self.finding(
                severity="high",
                category="invalid_real_evidence",
                blocking=True,
                description="Real coverage entry does not satisfy real Valkey evidence requirements",
                evidence=[path_text, f"expected_nodes={expected_nodes}", f"nodes_observed={payload.get('nodes_observed')}"],
            )
        return ok, payload

    def add_real_evidence_metrics(self) -> None:
        surface_by_phase = {
            "P03_LOCAL_DOCKER_VALKEY": "cluster_build",
            "P04_CLUSTER_MANAGEMENT_OPS": "management",
            "P05_WORKLOAD_ENGINE": "workload",
            "P06_OBSERVABILITY_METRICS": "observability",
            "P07_FAULT_INJECTION_SANDBOX": "fault",
            "P08_FAILOVER_SPLIT_BRAIN": "failover",
            "P09_ANALYSIS_REPORTING": "report_visualization",
            "P10_MULTI_HOST_ORCHESTRATION": "cluster_build",
            "P11_STABILITY_SOAK": "stability",
            "P12_SCALE_LADDER_10_30": "scale",
            "P13_SCALE_LADDER_50_100": "scale",
        }
        for path in sorted((self.root / "artifacts" / "phases").glob("P*/valkey_e2e_evidence*.json")):
            path_text = rel(self.root, path)
            payload = load_json(path)
            phase_id = payload.get("phase_id") or self.phase_from_path(path_text) or "MISSING"
            surface = surface_by_phase.get(phase_id, "cluster_build")
            nodes = payload.get("nodes_observed")
            ok, _ = self.validate_real_evidence(path_text, nodes if isinstance(nodes, int) else None)
            layer = self.layer_for(node_count=nodes, dry_run_only=False, real_valkey=ok)
            for metric_name, unit, pointer, value in [
                ("real_evidence.nodes_observed", "nodes", "$.nodes_observed", nodes),
                ("real_evidence.cluster_state_observed", "status", "$.cluster_state_observed", payload.get("cluster_state_observed")),
                ("real_evidence.data_path_result", "status", "$.data_path_result", payload.get("data_path_result")),
            ]:
                value_status = "PASS" if value in {"PASS", "ok"} else "MEASURED"
                reason = ""
                if value == "SKIPPED_WITH_REASON":
                    value_status = "SKIPPED_WITH_REASON"
                    reason = "Wrapper evidence skipped the data-path probe while live Valkey liveness and cluster probes passed."
                self.add_metric(
                    name=f"{surface}.{metric_name}",
                    surface=surface,
                    unit=unit,
                    source_artifact=path_text,
                    source_pointer=pointer,
                    value=value,
                    value_status=value_status,
                    reason=reason,
                    node_count_scope=str(nodes or "unknown"),
                    evidence_layer=layer,
                    evidence_class="real_valkey",
                    real_valkey_coverage=ok,
                )

    def add_cleanup_metrics(self) -> None:
        for path in sorted((self.root / "artifacts" / "phases").glob("P*/cleanup_report*.json")):
            path_text = rel(self.root, path)
            payload = load_json(path)
            remaining = payload.get("resources_remaining")
            actions = payload.get("cleanup_actions") or []
            node_scope = self.node_scope_from_path(path_text)
            self.add_metric(
                name="cleanup.resources_remaining",
                surface="cleanup",
                unit="count",
                source_artifact=path_text,
                source_pointer="$.resources_remaining",
                value=len(remaining) if isinstance(remaining, list) else None,
                value_status="MEASURED" if isinstance(remaining, list) else "MISSING",
                reason="" if isinstance(remaining, list) else "cleanup_report lacks resources_remaining",
                node_count_scope=node_scope,
                evidence_layer=self.layer_from_scope(node_scope),
            )
            self.add_metric(
                name="cleanup.action_count",
                surface="cleanup",
                unit="count",
                source_artifact=path_text,
                source_pointer="$.cleanup_actions",
                value=len(actions),
                node_count_scope=node_scope,
                evidence_layer=self.layer_from_scope(node_scope),
            )

    def node_scope_from_path(self, path_text: str) -> str:
        for count in [100, 50, 30, 10]:
            if f"scale_{count}" in path_text:
                return str(count)
        return "6"

    def layer_from_scope(self, scope: str) -> str:
        return scope if scope in {"30", "50", "100"} else "small-real"

    def add_management_metrics(self) -> None:
        path = "artifacts/phases/P04_CLUSTER_MANAGEMENT_OPS/management_ops_report.json"
        payload = self.load_json(path)
        if not payload:
            return
        for idx, op in enumerate(payload.get("operations", [])):
            status = op.get("status")
            skipped = status == "SKIPPED_WITH_REASON"
            self.add_metric(
                name=f"management.operation.{op.get('operation')}.duration_seconds",
                surface="management",
                unit="seconds",
                source_artifact=path,
                source_pointer=f"$.operations.{idx}.duration_seconds",
                value=None if skipped else op.get("duration_seconds"),
                value_status="SKIPPED_WITH_REASON" if skipped else "MEASURED",
                reason=op.get("reason", ""),
                scenario=payload.get("scenario"),
                node_count_scope="6",
                evidence_layer="small-real",
            )

    def add_workload_metrics(self) -> None:
        path = "artifacts/phases/P05_WORKLOAD_ENGINE/workload_report.json"
        payload = self.load_json(path)
        if not payload:
            return
        for name, unit, pointer in [
            ("workload.requested_qps", "qps", "$.requested_qps"),
            ("workload.achieved_qps", "qps", "$.achieved_qps"),
            ("workload.latency.p50", "ms", "$.latency.p50"),
            ("workload.latency.p95", "ms", "$.latency.p95"),
            ("workload.latency.p99", "ms", "$.latency.p99"),
            ("workload.operations.completed_total", "count", "$.operation_counts.completed_total"),
            ("workload.errors.total", "count", "$.errors.total"),
        ]:
            self.add_metric(
                name=name,
                surface="workload",
                unit=unit,
                source_artifact=path,
                source_pointer=pointer,
                value=nested_get(payload, pointer),
                scenario=payload.get("scenario"),
                node_count_scope="6",
                evidence_layer="small-real",
            )
        for idx, window in enumerate(payload.get("timing_windows", [])):
            skipped = window.get("status") == "SKIPPED_WITH_REASON"
            self.add_metric(
                name=f"workload.timing_window.{window.get('name')}.duration_seconds",
                surface="workload",
                unit="seconds",
                source_artifact=path,
                source_pointer=f"$.timing_windows.{idx}.duration_seconds",
                value=None if skipped else window.get("duration_seconds"),
                value_status="SKIPPED_WITH_REASON" if skipped else "MEASURED",
                reason=window.get("reason", ""),
                scenario=payload.get("scenario"),
                node_count_scope="6",
                evidence_layer="small-real",
            )

    def add_observability_metrics(self) -> None:
        path = "artifacts/phases/P06_OBSERVABILITY_METRICS/metrics_timeseries.jsonl"
        full = self.root / path
        if not full.exists():
            return
        rows = read_jsonl(full)
        if not rows:
            return
        sample = rows[0]
        metrics = sample.get("metrics", {})
        for group, group_payload in metrics.items():
            if not isinstance(group_payload, dict):
                continue
            for key, value in sorted(group_payload.items()):
                if isinstance(value, bool) or isinstance(value, (int, float, str)):
                    unit = self.infer_unit(key, value)
                    self.add_metric(
                        name=f"observability.{group}.{key}",
                        surface="observability",
                        unit=unit,
                        source_artifact=path,
                        source_pointer=f"$[0].metrics.{group}.{key}",
                        value=value,
                        scenario="observability_smoke",
                        node_count_scope="6",
                        evidence_layer="small-real",
                    )

    def infer_unit(self, name: str, value: Any) -> str:
        lowered = name.lower()
        if "memory" in lowered or "bytes" in lowered:
            return "bytes"
        if "seconds" in lowered or "uptime" in lowered:
            return "seconds"
        if "percent" in lowered or (isinstance(value, str) and "%" in value):
            return "percent"
        if isinstance(value, str):
            return "raw_string"
        return "count"

    def add_fault_metrics(self) -> None:
        path = "artifacts/phases/P07_FAULT_INJECTION_SANDBOX/fault_report.json"
        payload = self.load_json(path)
        if not payload:
            return
        for key in ["sandbox_only", "host_network_mutated", "global_firewall_mutated", "fault_state_cleared"]:
            self.add_metric(
                name=f"fault.safety.{key}",
                surface="fault",
                unit="boolean",
                source_artifact=path,
                source_pointer=f"$.safety_checks.{key}",
                value=payload.get("safety_checks", {}).get(key),
                node_count_scope="6",
                evidence_layer="small-real",
            )
        for idx, fault in enumerate(payload.get("faults", [])):
            observed = fault.get("observed_impact", {})
            self.add_metric(
                name=f"fault.{fault.get('fault_type')}.observed_impact",
                surface="fault",
                unit="status",
                source_artifact=path,
                source_pointer=f"$.faults.{idx}.observed_impact",
                value=None if observed.get("status") == "SKIPPED_WITH_REASON" else observed.get("status"),
                value_status=observed.get("status", "MEASURED"),
                reason=observed.get("reason", ""),
                node_count_scope="6",
                evidence_layer="small-real",
            )

    def add_failover_metrics(self) -> None:
        path = "artifacts/phases/P08_FAILOVER_SPLIT_BRAIN/failover_report.json"
        payload = self.load_json(path)
        if not payload:
            return
        for idx, failover in enumerate(payload.get("failovers", [])):
            self.add_metric(
                name="failover.failover_latency_ms",
                surface="failover",
                unit="ms",
                source_artifact=path,
                source_pointer=f"$.failovers.{idx}.failover_latency_ms",
                value=failover.get("failover_latency_ms"),
                node_count_scope="6",
                evidence_layer="small-real",
            )
        split = payload.get("summary", {}).get("split_brain_duration_ms", {})
        self.add_metric(
            name="failover.split_brain_duration_ms",
            surface="failover",
            unit="ms",
            source_artifact=path,
            source_pointer="$.summary.split_brain_duration_ms",
            value=split.get("value"),
            value_status=split.get("status", "MISSING"),
            reason=split.get("reason", "missing split-brain duration"),
            node_count_scope="6",
            evidence_layer="small-real",
        )

    def add_analysis_report_metrics(self) -> None:
        analysis = "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json"
        report_index = "artifacts/phases/P09_ANALYSIS_REPORTING/report_index.json"
        payload = self.load_json(analysis)
        if payload:
            for idx, metric in enumerate(payload.get("metrics", [])):
                status = metric.get("status", "MEASURED")
                self.add_metric(
                    name=f"report_visualization.analysis.{metric.get('name')}",
                    surface="report_visualization",
                    unit=metric.get("unit") or "unknown",
                    source_artifact=analysis,
                    source_pointer=f"$.metrics.{idx}",
                    value=metric.get("value"),
                    value_status=status if status in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"} else "MEASURED",
                    reason=metric.get("reason", ""),
                    scenario="analysis_reporting",
                    node_count_scope="6",
                    evidence_layer="small-real",
                )
        report_payload = self.load_json(report_index)
        if report_payload:
            reports = report_payload.get("reports", [])
            self.add_metric(
                name="report_visualization.rendered_view_count",
                surface="report_visualization",
                unit="count",
                source_artifact=report_index,
                source_pointer="$.reports",
                value=len(reports),
                scenario="analysis_reporting",
                node_count_scope="6",
                evidence_layer="small-real",
                evidence_class="report_view",
                source_kind="report_index_view_manifest",
            )

    def add_stability_metrics(self) -> None:
        path = "artifacts/phases/P11_STABILITY_SOAK/stability_report.json"
        payload = self.load_json(path)
        if not payload:
            return
        for name, unit, pointer in [
            ("stability.duration_seconds", "seconds", "$.duration_seconds"),
            ("stability.leaks.max_growth_bytes", "bytes", "$.summary.leaks.max_growth_bytes"),
            ("stability.metrics.sample_count", "count", "$.summary.metrics.sample_count"),
            ("stability.nodes_observed", "nodes", "$.summary.nodes_observed"),
        ]:
            self.add_metric(
                name=name,
                surface="stability",
                unit=unit,
                source_artifact=path,
                source_pointer=pointer,
                value=nested_get(payload, pointer),
                scenario=payload.get("scenario"),
                node_count_scope="6",
                evidence_layer="small-real",
            )
        for idx, comparison in enumerate(payload.get("summary", {}).get("baseline", {}).get("comparisons", [])):
            status = comparison.get("status", "MEASURED")
            self.add_metric(
                name=f"stability.baseline.{comparison.get('metric')}",
                surface="stability",
                unit="count",
                source_artifact=path,
                source_pointer=f"$.summary.baseline.comparisons.{idx}",
                value=comparison.get("delta") if status == "NO_BASELINE_YET" else comparison.get("current_value"),
                value_status=status,
                reason="No previous stability baseline artifact exists." if status == "NO_BASELINE_YET" else "",
                scenario=payload.get("scenario"),
                node_count_scope="6",
                evidence_layer="small-real",
            )
        self.add_stability_soak_rollup_metrics()

    def add_stability_soak_rollup_metrics(self) -> None:
        path = "artifacts/loop_engineering/reports/stability_soak_metrics.json"
        payload = self.load_json(path)
        if not payload:
            return
        for profile_idx, profile in enumerate(payload.get("profiles", [])):
            if not isinstance(profile, dict):
                continue
            node_count = profile.get("node_count")
            layer = str(profile.get("evidence_layer") or self.layer_for(
                node_count=node_count,
                dry_run_only=False,
                real_valkey=profile.get("real_valkey_coverage") is True,
            ))
            real = profile.get("real_valkey_coverage") is True
            evidence_class = "real_valkey" if real else "source_artifact"
            for record_idx, record in enumerate(profile.get("metric_records", [])):
                if not isinstance(record, dict):
                    continue
                status = str(record.get("status") or "MISSING")
                value_status = status if status in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"} else "MEASURED"
                self.add_metric(
                    name=f"stability_soak.{record.get('name')}",
                    surface=record.get("surface") or "stability",
                    unit=record.get("unit") or "status",
                    source_artifact=record.get("source_artifact") or path,
                    source_pointer=record.get("source_pointer") or f"$.profiles.{profile_idx}.metric_records.{record_idx}",
                    value=record.get("value"),
                    value_status=value_status,
                    reason=record.get("reason", ""),
                    scenario=profile.get("run_id"),
                    node_count_scope=str(node_count),
                    evidence_layer=layer,
                    evidence_class=evidence_class,
                    real_valkey_coverage=real,
                )
            if profile.get("status") == "SKIPPED_WITH_REASON":
                self.add_metric(
                    name="stability_soak.profile.resource_aware_status",
                    surface="stability",
                    unit="status",
                    source_artifact=path,
                    source_pointer=f"$.profiles.{profile_idx}.status",
                    value=None,
                    value_status="SKIPPED_WITH_REASON",
                    reason=profile.get("reason", "Resource-aware bounded profile was not measured."),
                    scenario=profile.get("run_id"),
                    node_count_scope=str(node_count),
                    evidence_layer=layer,
                    evidence_class="source_artifact",
                    real_valkey_coverage=False,
                )

    def add_scale_metrics(self) -> None:
        for path in sorted((self.root / "artifacts" / "phases").glob("P*/scale_rung_*.json")):
            path_text = rel(self.root, path)
            payload = load_json(path)
            node_count = int(payload.get("node_count", 0))
            if node_count not in {10, 30, 50, 100}:
                continue
            evidence_path = payload.get("evidence_path")
            real = False
            if isinstance(evidence_path, str):
                real, _ = self.validate_real_evidence(evidence_path, node_count)
            layer = self.layer_for(node_count=node_count, dry_run_only=False, real_valkey=real)
            for name, unit, pointer, value in [
                ("scale.node_count", "nodes", "$.node_count", node_count),
                ("scale.primary_count", "count", "$.primary_count", payload.get("primary_count")),
                ("scale.replica_count", "count", "$.replica_count", payload.get("replica_count")),
                ("scale.management.cluster_known_nodes_max", "nodes", "$.management.cluster_known_nodes_max", nested_get(payload, "$.management.cluster_known_nodes_max")),
                ("scale.metrics.total_used_memory", "bytes", "$.metrics.total_used_memory", nested_get(payload, "$.metrics.total_used_memory")),
                ("scale.metrics.avg_used_memory", "bytes", "$.metrics.avg_used_memory", nested_get(payload, "$.metrics.avg_used_memory")),
                ("scale.metrics.total_commands_processed", "count", "$.metrics.total_commands_processed", nested_get(payload, "$.metrics.total_commands_processed")),
            ]:
                self.add_metric(
                    name=name,
                    surface="scale",
                    unit=unit,
                    source_artifact=path_text,
                    source_pointer=pointer,
                    value=value,
                    scenario=payload.get("scenario"),
                    node_count_scope=str(node_count),
                    evidence_layer=layer,
                    evidence_class="real_valkey" if real else "source_artifact",
                    real_valkey_coverage=real,
                )
        for path in sorted((self.root / "artifacts" / "phases" / "P13_SCALE_LADDER_50_100").glob("p13_timing_breakdown_scale_*.json")):
            path_text = rel(self.root, path)
            payload = load_json(path)
            node_count = int(payload.get("node_count", 0))
            layer = self.layer_for(node_count=node_count, dry_run_only=False, real_valkey=True)
            for idx, item in enumerate(payload.get("timings", [])[:8]):
                if isinstance(item, dict) and isinstance(item.get("duration_seconds"), (int, float)):
                    self.add_metric(
                        name=f"scale.timing.{item.get('name')}.duration_seconds",
                        surface="scale",
                        unit="seconds",
                        source_artifact=path_text,
                        source_pointer=f"$.timings.{idx}.duration_seconds",
                        value=item.get("duration_seconds"),
                        scenario=payload.get("scenario"),
                        node_count_scope=str(node_count),
                        evidence_layer=layer,
                    )

    def add_scale_build_metrics(self) -> None:
        path = "artifacts/loop_engineering/reports/scale_build_metrics.json"
        payload = self.load_json(path)
        if not payload:
            return
        for rung_idx, rung in enumerate(payload.get("canonical_rungs", [])):
            if not isinstance(rung, dict):
                continue
            node_count = rung.get("node_count")
            if node_count not in {30, 50, 100}:
                self.finding(
                    severity="high",
                    category="invalid_scale_build_rung",
                    blocking=True,
                    description="Scale build metrics may only include canonical real rungs 30, 50, and 100",
                    evidence=[str(node_count)],
                )
                continue
            layer = self.layer_for(node_count=int(node_count), dry_run_only=False, real_valkey=rung.get("real_valkey") is True)
            for metric_idx, record in enumerate(rung.get("metric_records", [])):
                if not isinstance(record, dict):
                    continue
                value_status = {
                    "MEASURED": "MEASURED",
                    "MISSING": "MISSING",
                    "SKIPPED_WITH_REASON": "SKIPPED_WITH_REASON",
                    "NO_BASELINE_YET": "NO_BASELINE_YET",
                }.get(str(record.get("status")), "MISSING")
                source_artifact = record.get("source_artifact") or path
                if value_status != "MEASURED":
                    source_artifact = path
                self.add_metric(
                    name=f"cluster_build.{record.get('name')}",
                    surface="cluster_build",
                    unit=record.get("unit") or "status",
                    source_artifact=source_artifact,
                    source_pointer=f"$.canonical_rungs.{rung_idx}.metric_records.{metric_idx}",
                    value=record.get("value"),
                    value_status=value_status,
                    reason=record.get("reason", ""),
                    scenario=rung.get("scenario"),
                    node_count_scope=str(node_count),
                    evidence_layer=layer,
                    evidence_class="real_valkey",
                    real_valkey_coverage=rung.get("real_valkey") is True,
                )

    def add_fault_failover_scale_metrics(self) -> None:
        path = "artifacts/loop_engineering/reports/fault_failover_scale.json"
        payload = self.load_json(path)
        if not payload:
            return
        if payload.get("status") != "PASS":
            return
        for rung_idx, rung in enumerate(payload.get("canonical_rungs", [])):
            if not isinstance(rung, dict):
                continue
            node_count = rung.get("node_count")
            if node_count not in {30, 50, 100}:
                self.finding(
                    severity="high",
                    category="invalid_fault_failover_rung",
                    blocking=True,
                    description="Fault/failover scale metrics may only include canonical real rungs 30, 50, and 100",
                    evidence=[str(node_count)],
                )
                continue
            real = rung.get("real_valkey") is True and rung.get("status") == "PASS"
            layer = self.layer_for(node_count=int(node_count), dry_run_only=False, real_valkey=real)
            for metric_idx, record in enumerate(rung.get("metric_records", [])):
                if not isinstance(record, dict):
                    continue
                value_status = {
                    "MEASURED": "MEASURED",
                    "MISSING": "MISSING",
                    "SKIPPED_WITH_REASON": "SKIPPED_WITH_REASON",
                    "NO_BASELINE_YET": "NO_BASELINE_YET",
                }.get(str(record.get("status")), "MISSING")
                source_artifact = record.get("source_artifact") or path
                if value_status != "MEASURED":
                    source_artifact = path
                self.add_metric(
                    name=f"fault_failover_scale.{record.get('name')}",
                    surface=record.get("surface") or "failover",
                    unit=record.get("unit") or "status",
                    source_artifact=source_artifact,
                    source_pointer=f"$.canonical_rungs.{rung_idx}.metric_records.{metric_idx}",
                    value=record.get("value"),
                    value_status=value_status,
                    reason=record.get("reason", ""),
                    scenario=rung.get("scenario"),
                    node_count_scope=str(node_count),
                    evidence_layer=layer,
                    evidence_class="real_valkey",
                    real_valkey_coverage=real,
                )

    def add_dryrun_metrics(self) -> None:
        path = "artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json"
        payload = self.load_json(path)
        if payload:
            self.add_metric(
                name="scale.dryrun_1000.planned_node_count",
                surface="scale",
                unit="nodes",
                source_artifact=path,
                source_pointer="$.node_count",
                value=payload.get("node_count"),
                scenario="scale_1000_dryrun",
                node_count_scope="1000",
                evidence_layer="1000-dry-run",
                evidence_class="dry_run_planner",
                real_valkey_coverage=False,
                dry_run_only=True,
                source_kind="dry_run_planner",
            )
        else:
            self.finding(
                severity="medium",
                category="p14_dryrun_absent",
                blocking=False,
                description="1000 dry-run planner artifact is absent",
                evidence=[path],
            )

    def add_fake_placeholders(self) -> None:
        for surface in SURFACES:
            self.add_metric(
                name=f"fake.{surface}.coverage_placeholder",
                surface=surface,
                unit="status",
                source_artifact="artifacts/loop_engineering/stages/L03_METRIC_CATALOG_AND_COVERAGE_MATRIX/current_harness_plan.json",
                source_pointer=f"$.L03.required_layers.fake.{surface}",
                value=None,
                value_status="SKIPPED_WITH_REASON",
                reason="Fake coverage is represented by deterministic tests and is not committed as real artifact evidence.",
                scenario="fake",
                node_count_scope="fake",
                evidence_layer="fake",
                evidence_class="fake",
                real_valkey_coverage=False,
                dry_run_only=False,
                source_kind="harness_layer_placeholder",
            )

    def build_metrics(self) -> None:
        self.add_fake_placeholders()
        self.add_real_evidence_metrics()
        self.add_cleanup_metrics()
        self.add_management_metrics()
        self.add_workload_metrics()
        self.add_observability_metrics()
        self.add_fault_metrics()
        self.add_failover_metrics()
        self.add_analysis_report_metrics()
        self.add_stability_metrics()
        self.add_scale_metrics()
        self.add_scale_build_metrics()
        self.add_fault_failover_scale_metrics()
        self.add_dryrun_metrics()
        self.check_required_surfaces()

    def check_required_surfaces(self) -> None:
        present = {metric["surface"] for metric in self.metrics}
        for surface in SURFACES:
            if surface not in present:
                self.finding(
                    severity="high",
                    category="missing_surface",
                    blocking=True,
                    description=f"Required metric surface is missing: {surface}",
                    evidence=[surface],
                )

    def build_catalog(self) -> dict[str, Any]:
        blocking = [finding for finding in self.findings if finding["blocking"]]
        counts = defaultdict(int)
        for metric in self.metrics:
            counts[metric["value_status"]] += 1
        return {
            "schema_version": "v1",
            "artifact_type": "metric_catalog",
            "created_at": utc_now(),
            "producer": {"name": "scripts/build_metric_coverage_matrix.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "summary": {
                "metric_count": len(self.metrics),
                "measured_count": counts["MEASURED"] + counts["PASS"],
                "missing_count": counts["MISSING"],
                "skipped_count": counts["SKIPPED_WITH_REASON"],
                "no_baseline_count": counts["NO_BASELINE_YET"],
                "blocking_findings_count": len(blocking),
                "surfaces": SURFACES,
                "layers": LAYERS,
            },
            "metrics": sorted(self.metrics, key=lambda item: (item["evidence_layer"], item["surface"], item["name"], item["source_artifact"])),
            "findings": self.findings,
        }

    def build_matrix(self) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for metric in self.metrics:
            by_key[(metric["evidence_layer"], metric["surface"])].append(metric)
        for layer in LAYERS:
            for surface in SURFACES:
                metrics = by_key.get((layer, surface), [])
                entries.append(self.matrix_entry(layer, surface, metrics))
        blocking = [finding for finding in self.findings if finding["blocking"]]
        p14_artifacts = list((self.root / "artifacts" / "phases" / P14_ID).glob("*")) if (self.root / "artifacts" / "phases" / P14_ID).exists() else []
        return {
            "schema_version": "v1",
            "artifact_type": "coverage_matrix",
            "created_at": utc_now(),
            "producer": {"name": "scripts/build_metric_coverage_matrix.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "summary": {
                "entry_count": len(entries),
                "covered_entry_count": sum(1 for entry in entries if entry["status"] == "COVERED"),
                "real_coverage_entry_count": sum(1 for entry in entries if entry["real_valkey_coverage"]),
                "dry_run_entry_count": sum(1 for entry in entries if entry["dry_run_only"]),
                "blocking_findings_count": len(blocking),
            },
            "layers": LAYERS,
            "surfaces": SURFACES,
            "entries": entries,
            "p14_boundary": {
                "phase_id": P14_ID,
                "status": "SKIPPED_WITH_REASON",
                "real_valkey_coverage": False,
                "dry_run_only": True,
                "dry_run_artifact_count": len(p14_artifacts),
                "reason": "P14 is opt-in dry-run only and was not executed by L03.",
            },
            "findings": self.findings,
        }

    def matrix_entry(self, layer: str, surface: str, metrics: list[dict[str, Any]]) -> dict[str, Any]:
        if not metrics:
            return {
                "layer": layer,
                "surface": surface,
                "status": "SKIPPED_WITH_REASON",
                "evidence_class": "none",
                "metric_count": 0,
                "metric_names": [],
                "source_artifacts": [],
                "node_count_scope": "1000" if layer == "1000-dry-run" else layer,
                "real_valkey_coverage": False,
                "dry_run_only": layer == "1000-dry-run",
                "reason": f"No committed metric artifacts for {surface} in {layer} layer.",
            }
        statuses = {metric["value_status"] for metric in metrics}
        if statuses <= {"SKIPPED_WITH_REASON"}:
            status = "SKIPPED_WITH_REASON"
            reason = "All metrics in this cell are explicitly skipped with reason."
        elif statuses <= {"MISSING", "NO_BASELINE_YET"}:
            status = "MISSING"
            reason = "All metrics in this cell are missing or have no baseline yet."
        else:
            status = "COVERED"
            reason = ""
        evidence_class = "source_artifact"
        if any(metric["real_valkey_coverage"] for metric in metrics):
            evidence_class = "real_valkey"
        elif any(metric["dry_run_only"] for metric in metrics):
            evidence_class = "dry_run_planner"
        elif all(metric["evidence_class"] == "fake" for metric in metrics):
            evidence_class = "fake"
        elif any(metric["evidence_class"] == "report_view" for metric in metrics):
            evidence_class = "report_view"
        return {
            "layer": layer,
            "surface": surface,
            "status": status,
            "evidence_class": evidence_class,
            "metric_count": len(metrics),
            "metric_names": sorted({metric["name"] for metric in metrics}),
            "source_artifacts": sorted({metric["source_artifact"] for metric in metrics}),
            "node_count_scope": "1000" if layer == "1000-dry-run" else layer,
            "real_valkey_coverage": any(metric["real_valkey_coverage"] for metric in metrics),
            "dry_run_only": any(metric["dry_run_only"] for metric in metrics) or layer == "1000-dry-run",
            "reason": reason,
        }


def build_reports(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    builder = MetricCoverageBuilder(root)
    builder.build_metrics()
    catalog = builder.build_catalog()
    matrix = builder.build_matrix()
    return catalog, matrix


def validate_output(root: Path, artifact: dict[str, Any], schema_path: str) -> list[str]:
    schema = load_json(root / schema_path)
    return validate(artifact, schema)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build metric catalog and coverage matrix")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog, matrix = build_reports(root)
    catalog_errors = validate_output(root, catalog, "schemas/artifact/metric_catalog.schema.json")
    matrix_errors = validate_output(root, matrix, "schemas/artifact/coverage_matrix.schema.json")
    if catalog_errors:
        for error in catalog_errors:
            print(f"metric_catalog schema error: {error}", file=sys.stderr)
    if matrix_errors:
        for error in matrix_errors:
            print(f"coverage_matrix schema error: {error}", file=sys.stderr)

    (out_dir / "metric_catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    (out_dir / "coverage_matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")

    status = "PASS" if catalog["status"] == "PASS" and matrix["status"] == "PASS" and not catalog_errors and not matrix_errors else "FAIL"
    print(f"{status} metric_coverage {rel(root, out_dir / 'metric_catalog.json')} {rel(root, out_dir / 'coverage_matrix.json')}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
