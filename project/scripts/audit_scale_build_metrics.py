#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402


P12_ID = "P12_SCALE_LADDER_10_30"
P13_ID = "P13_SCALE_LADDER_50_100"
P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"
RUNG_CONFIG = {
    30: {"phase_id": P12_ID, "phase_dir": Path("artifacts/phases") / P12_ID},
    50: {"phase_id": P13_ID, "phase_dir": Path("artifacts/phases") / P13_ID},
    100: {"phase_id": P13_ID, "phase_dir": Path("artifacts/phases") / P13_ID},
}
REPORT_VIEW_SUFFIXES = {".html", ".svg", ".csv", ".md"}


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


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class ScaleBuildAudit:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.findings: list[dict[str, Any]] = []
        self.finding_seq = 0

    def path(self, path_text: str | Path) -> Path:
        return self.root / Path(path_text)

    def finding(
        self,
        *,
        severity: str,
        category: str,
        blocking: bool,
        description: str,
        evidence: list[str],
        classification: str = "current",
    ) -> str:
        self.finding_seq += 1
        finding_id = f"L07-SCALE-{self.finding_seq:04d}"
        self.findings.append(
            {
                "id": finding_id,
                "severity": severity,
                "category": category,
                "classification": classification,
                "blocking": blocking,
                "description": description,
                "evidence": evidence,
            }
        )
        return finding_id

    def check(
        self,
        condition: bool,
        *,
        category: str,
        description: str,
        evidence: list[str],
        severity: str = "high",
        blocking: bool = True,
        classification: str = "current",
    ) -> str | None:
        if condition:
            return None
        return self.finding(
            severity=severity,
            category=category,
            blocking=blocking,
            description=description,
            evidence=evidence,
            classification=classification,
        )

    def load(self, path_text: str | Path, *, schema_path: str | None = None, required: bool = True) -> Any | None:
        path = self.path(path_text)
        path_label = rel(self.root, path)
        if not path.exists():
            self.finding(
                severity="high",
                category="missing_artifact",
                blocking=required,
                description=f"Artifact is missing: {path_label}",
                evidence=[path_label],
            )
            return None
        if path.suffix in REPORT_VIEW_SUFFIXES:
            self.finding(
                severity="high",
                category="report_view_used_as_source",
                blocking=True,
                description=f"Rendered view cannot be a measured metric source: {path_label}",
                evidence=[path_label],
            )
            return None
        try:
            payload = load_json(path)
        except Exception as exc:  # noqa: BLE001
            self.finding(
                severity="high",
                category="invalid_json",
                blocking=required,
                description=f"Artifact is not valid JSON: {path_label}",
                evidence=[str(exc)],
            )
            return None
        if schema_path:
            schema_file = self.path(schema_path)
            if not schema_file.exists():
                self.finding(
                    severity="high",
                    category="missing_schema",
                    blocking=True,
                    description=f"Schema is missing: {schema_path}",
                    evidence=[schema_path],
                )
            else:
                errors = validate(payload, load_json(schema_file))
                if errors:
                    self.finding(
                        severity="high",
                        category="schema_invalid",
                        blocking=required,
                        description=f"Artifact does not validate against {schema_path}: {path_label}",
                        evidence=errors[:8],
                    )
        return payload

    def source_record(self, role: str, path_text: str | Path) -> dict[str, Any]:
        path = self.path(path_text)
        payload: Any | None = None
        if path.exists() and path.suffix == ".json":
            try:
                payload = load_json(path)
            except Exception:  # noqa: BLE001
                payload = None
        return {
            "role": role,
            "path": rel(self.root, path),
            "exists": path.exists(),
            "sha256": sha256_file(path) if path.exists() and path.is_file() else None,
            "artifact_type": payload.get("artifact_type") if isinstance(payload, dict) else None,
            "status": payload.get("status") if isinstance(payload, dict) else None,
        }

    def metric(
        self,
        name: str,
        *,
        value: Any = None,
        unit: str | None = None,
        source_artifact: str = "",
        source_role: str = "",
        required: bool = True,
        reason: str = "",
        missing_status: str = "MISSING",
    ) -> dict[str, Any]:
        if is_number(value) or isinstance(value, bool) or (isinstance(value, str) and value not in {"", "MISSING"}):
            status = "MEASURED"
            metric_reason = reason
        else:
            status = missing_status
            metric_reason = reason or "metric not present in committed source artifact"
        if status == "MEASURED" and Path(source_artifact).suffix in REPORT_VIEW_SUFFIXES:
            self.finding(
                severity="high",
                category="report_view_used_as_source",
                blocking=True,
                description=f"Measured metric {name} uses rendered view source {source_artifact}",
                evidence=[source_artifact],
            )
        return {
            "name": name,
            "status": status,
            "required": required,
            "value": value if status == "MEASURED" else None,
            "unit": unit,
            "source_artifact": source_artifact,
            "source_role": source_role,
            "reason": metric_reason,
        }

    def timing_by_name(self, timing: dict[str, Any] | None, name: str) -> Any:
        if not isinstance(timing, dict):
            return None
        for entry in timing.get("timings", []):
            if isinstance(entry, dict) and entry.get("name") == name:
                return entry.get("duration_seconds")
        return None

    def setup_segment(self, setup: dict[str, Any] | None, category: str) -> Any:
        if not isinstance(setup, dict):
            return None
        total = 0.0
        found = False
        for segment in setup.get("segments", []):
            if isinstance(segment, dict) and segment.get("category") == category and is_number(segment.get("duration_seconds")):
                total += float(segment["duration_seconds"])
                found = True
        return round(total, 6) if found else None

    def final_snapshot(self, snapshots: Any) -> dict[str, Any]:
        if isinstance(snapshots, list) and snapshots:
            last = snapshots[-1]
            return last if isinstance(last, dict) else {}
        if isinstance(snapshots, dict):
            items = snapshots.get("snapshots")
            if isinstance(items, list) and items:
                last = items[-1]
                return last if isinstance(last, dict) else {}
        return {}

    def audit_rung(self, node_count: int) -> dict[str, Any]:
        cfg = RUNG_CONFIG[node_count]
        phase_id = str(cfg["phase_id"])
        phase_dir = Path(cfg["phase_dir"])
        scenario = f"scale_{node_count}"
        evidence_path = phase_dir / f"valkey_e2e_evidence_{node_count}.json"
        preflight_path = phase_dir / f"resource_preflight_{node_count}.json"
        scale_rung_path = phase_dir / f"scale_rung_{node_count}.json"
        cleanup_path = phase_dir / f"cleanup_report_scale_{node_count}.json"
        snapshots_path = phase_dir / f"cluster_snapshots_scale_{node_count}.json"
        scale_report_path = phase_dir / "scale_ladder_report.json"
        timing_path = phase_dir / f"p13_timing_breakdown_scale_{node_count}.json"
        runtime_timing_path = phase_dir / f"runtime_timing_breakdown_scale_{node_count}.json"
        setup_timeline_path = phase_dir / f"setup_timeline_scale_{node_count}.json"

        finding_ids: list[str] = []

        def add(finding: str | None) -> None:
            if finding:
                finding_ids.append(finding)

        preflight = self.load(preflight_path, schema_path="schemas/artifact/resource_preflight.schema.json")
        evidence = self.load(evidence_path, schema_path="schemas/artifact/valkey_e2e_evidence.schema.json")
        scale_rung = self.load(scale_rung_path)
        cleanup = self.load(cleanup_path, schema_path="schemas/artifact/cleanup_report.schema.json")
        snapshots = self.load(snapshots_path)
        scale_report = self.load(scale_report_path, schema_path="schemas/artifact/scale_ladder_report.schema.json")
        timing = self.load(timing_path, schema_path="schemas/artifact/p13_timing_breakdown.schema.json", required=node_count in {50, 100})
        runtime_timing = self.load(runtime_timing_path, required=False)
        setup_timeline = self.load(setup_timeline_path, required=False)
        final_snapshot = self.final_snapshot(snapshots)

        source_paths = [
            ("resource_preflight", preflight_path),
            ("real_evidence", evidence_path),
            ("scale_rung", scale_rung_path),
            ("cleanup", cleanup_path),
            ("cluster_snapshots", snapshots_path),
            ("scale_ladder_report", scale_report_path),
        ]
        if self.path(timing_path).exists():
            source_paths.append(("timing_breakdown", timing_path))
        if self.path(runtime_timing_path).exists():
            source_paths.append(("runtime_timing", runtime_timing_path))
        if self.path(setup_timeline_path).exists():
            source_paths.append(("setup_timeline", setup_timeline_path))
        source_artifacts = [self.source_record(role, path) for role, path in source_paths]

        preflight_ok = isinstance(preflight, dict) and preflight.get("status") == "PASS" and preflight.get("can_run") is True
        add(self.check(preflight_ok, category="resource_preflight_blocked", description=f"Resource preflight must pass for {scenario}", evidence=[rel(self.root, preflight_path), str(preflight.get("status") if isinstance(preflight, dict) else None), str(preflight.get("can_run") if isinstance(preflight, dict) else None)]))

        if isinstance(evidence, dict):
            add(self.check(evidence.get("status") == "PASS", category="invalid_real_evidence", description=f"{scenario} evidence status must be PASS", evidence=[rel(self.root, evidence_path), str(evidence.get("status"))]))
            add(self.check(evidence.get("phase_id") == phase_id, category="invalid_real_evidence", description=f"{scenario} evidence phase_id must match canonical phase", evidence=[rel(self.root, evidence_path), str(evidence.get("phase_id"))]))
            add(self.check(evidence.get("scenario") == scenario, category="invalid_real_evidence", description=f"{scenario} evidence scenario mismatch", evidence=[rel(self.root, evidence_path), str(evidence.get("scenario"))]))
            add(self.check(evidence.get("real_valkey") is True, category="invalid_real_evidence", description=f"{scenario} must be real Valkey evidence", evidence=[rel(self.root, evidence_path)]))
            add(self.check(evidence.get("nodes_observed") == node_count, category="invalid_real_evidence", description=f"{scenario} observed node count must match rung", evidence=[rel(self.root, evidence_path), str(evidence.get("nodes_observed"))]))
            add(self.check(evidence.get("cluster_state_observed") == "ok", category="invalid_real_evidence", description=f"{scenario} cluster_state_observed must be ok", evidence=[rel(self.root, evidence_path), str(evidence.get("cluster_state_observed"))]))
            add(self.check(evidence.get("probe_result") == "PASS", category="invalid_real_evidence", description=f"{scenario} probe_result must be PASS", evidence=[rel(self.root, evidence_path), str(evidence.get("probe_result"))]))
            add(self.check(evidence.get("data_path_result") == "PASS", category="invalid_real_evidence", description=f"{scenario} SET/GET data_path_result must be PASS", evidence=[rel(self.root, evidence_path), str(evidence.get("data_path_result"))]))
            add(self.check(len(evidence.get("probes", [])) == node_count, category="invalid_real_evidence", description=f"{scenario} probe count must equal node count", evidence=[rel(self.root, evidence_path), str(len(evidence.get("probes", [])))]))
            versions = evidence.get("valkey_versions", [])
            add(self.check(bool(versions) and all(str(v).startswith("9.1.") for v in versions), category="invalid_real_evidence", description=f"{scenario} Valkey versions must be 9.1.x", evidence=[rel(self.root, evidence_path), json.dumps(versions)]))

        if isinstance(scale_rung, dict):
            mgmt = scale_rung.get("management", {})
            add(self.check(scale_rung.get("status") == "PASS", category="scale_rung_invalid", description=f"{scenario} scale rung must PASS", evidence=[rel(self.root, scale_rung_path), str(scale_rung.get("status"))]))
            add(self.check(scale_rung.get("node_count") == node_count, category="scale_rung_invalid", description=f"{scenario} scale rung node_count mismatch", evidence=[rel(self.root, scale_rung_path), str(scale_rung.get("node_count"))]))
            add(self.check(mgmt.get("slots_assigned") == 16384, category="slot_assignment_invalid", description=f"{scenario} slots_assigned must be 16384", evidence=[rel(self.root, scale_rung_path), str(mgmt.get("slots_assigned"))]))

        if final_snapshot:
            add(self.check(final_snapshot.get("known_nodes") == node_count, category="membership_convergence_invalid", description=f"{scenario} final known_nodes must match node count", evidence=[rel(self.root, snapshots_path), str(final_snapshot.get("known_nodes"))]))
            add(self.check(final_snapshot.get("slots_assigned") == 16384 and final_snapshot.get("slots_ok") == 16384 and final_snapshot.get("slots_fail") == 0, category="slot_assignment_invalid", description=f"{scenario} final slots must be fully assigned and ok", evidence=[rel(self.root, snapshots_path), json.dumps({k: final_snapshot.get(k) for k in ['slots_assigned', 'slots_ok', 'slots_fail']})]))
            add(self.check(final_snapshot.get("primary_count") == node_count // 2 and final_snapshot.get("replica_count") == node_count // 2, category="role_convergence_invalid", description=f"{scenario} role counts must converge to half primaries and half replicas", evidence=[rel(self.root, snapshots_path), json.dumps({k: final_snapshot.get(k) for k in ['primary_count', 'replica_count']})]))
            add(self.check(final_snapshot.get("handshake_count") == 0 and final_snapshot.get("fail_count") == 0 and final_snapshot.get("pfail_count") == 0, category="membership_convergence_invalid", description=f"{scenario} final cluster must not have handshake/fail/pfail nodes", evidence=[rel(self.root, snapshots_path), json.dumps({k: final_snapshot.get(k) for k in ['handshake_count', 'fail_count', 'pfail_count']})]))

        if isinstance(cleanup, dict):
            add(self.check(cleanup.get("status") == "PASS", category="cleanup_invalid", description=f"{scenario} cleanup must PASS", evidence=[rel(self.root, cleanup_path), str(cleanup.get("status"))]))
            add(self.check(cleanup.get("resources_remaining") == [], category="cleanup_residue", description=f"{scenario} cleanup residual scan must be empty", evidence=[rel(self.root, cleanup_path), json.dumps(cleanup.get("resources_remaining"))]))

        if isinstance(scale_report, dict):
            rungs = scale_report.get("rungs", [])
            report_rung = next((r for r in rungs if isinstance(r, dict) and r.get("node_count") == node_count), None)
            add(self.check(report_rung is not None, category="scale_report_inconsistent", description=f"Scale report must include {scenario}", evidence=[rel(self.root, scale_report_path)]))
            if isinstance(report_rung, dict):
                add(self.check(report_rung.get("evidence_path") == rel(self.root, evidence_path), category="scale_report_inconsistent", description=f"Scale report evidence path must match canonical {scenario} evidence", evidence=[rel(self.root, scale_report_path), str(report_rung.get("evidence_path"))]))
                add(self.check(report_rung.get("status") == "PASS", category="scale_report_inconsistent", description=f"Scale report {scenario} rung must PASS", evidence=[rel(self.root, scale_report_path), str(report_rung.get("status"))]))

        metric_records: list[dict[str, Any]] = []
        metric_records.append(self.metric("resource_preflight.can_run", value=preflight.get("can_run") if isinstance(preflight, dict) else None, source_artifact=rel(self.root, preflight_path), source_role="resource_preflight", reason="resource preflight must pass before real scale evidence can be accepted"))
        metric_records.append(self.metric("resource_preflight.status", value=preflight.get("status") if isinstance(preflight, dict) else None, source_artifact=rel(self.root, preflight_path), source_role="resource_preflight"))
        metric_records.append(self.metric("process_startup.nodehost_start_seconds", value=self.timing_by_name(timing, "nodehost_start"), unit="seconds", source_artifact=rel(self.root, timing_path), source_role="timing_breakdown", reason="30-node historical evidence predates P13 timing breakdown" if node_count == 30 else ""))
        metric_records.append(self.metric("process_startup.process_config_prepare_seconds", value=self.timing_by_name(timing, "process_config_prepare"), unit="seconds", source_artifact=rel(self.root, timing_path), source_role="timing_breakdown", reason="30-node historical evidence predates P13 timing breakdown" if node_count == 30 else ""))
        metric_records.append(self.metric("process_startup.process_start_seconds", value=self.timing_by_name(timing, "process_start"), unit="seconds", source_artifact=rel(self.root, timing_path), source_role="timing_breakdown", reason="30-node historical evidence predates P13 timing breakdown" if node_count == 30 else ""))
        metric_records.append(self.metric("process_startup.process_ready_wait_seconds", value=self.timing_by_name(timing, "process_ready_wait"), unit="seconds", source_artifact=rel(self.root, timing_path), source_role="timing_breakdown", reason="30-node historical evidence predates P13 timing breakdown" if node_count == 30 else ""))
        metric_records.append(self.metric("cluster_create.primary_cluster_create_seconds", value=self.timing_by_name(timing, "primary_cluster_create"), unit="seconds", source_artifact=rel(self.root, timing_path), source_role="timing_breakdown", reason="30-node historical evidence predates P13 timing breakdown" if node_count == 30 else ""))
        metric_records.append(self.metric("cluster_create.replica_meet_seconds", value=self.timing_by_name(timing, "replica_meet"), unit="seconds", source_artifact=rel(self.root, timing_path), source_role="timing_breakdown", reason="30-node historical evidence predates P13 timing breakdown" if node_count == 30 else ""))
        metric_records.append(self.metric("role_convergence.replica_replicate_seconds", value=self.timing_by_name(timing, "replica_replicate"), unit="seconds", source_artifact=rel(self.root, timing_path), source_role="timing_breakdown", reason="30-node historical evidence predates P13 timing breakdown" if node_count == 30 else ""))
        metric_records.append(self.metric("slot_assignment.slots_assigned", value=final_snapshot.get("slots_assigned"), unit="slots", source_artifact=rel(self.root, snapshots_path), source_role="cluster_snapshots"))
        metric_records.append(self.metric("slot_assignment.slots_ok", value=final_snapshot.get("slots_ok"), unit="slots", source_artifact=rel(self.root, snapshots_path), source_role="cluster_snapshots"))
        metric_records.append(self.metric("membership_convergence.known_nodes", value=final_snapshot.get("known_nodes"), unit="nodes", source_artifact=rel(self.root, snapshots_path), source_role="cluster_snapshots"))
        metric_records.append(self.metric("membership_convergence.handshake_count", value=final_snapshot.get("handshake_count"), unit="nodes", source_artifact=rel(self.root, snapshots_path), source_role="cluster_snapshots"))
        metric_records.append(self.metric("membership_convergence.fail_count", value=final_snapshot.get("fail_count"), unit="nodes", source_artifact=rel(self.root, snapshots_path), source_role="cluster_snapshots"))
        metric_records.append(self.metric("role_convergence.primary_count", value=final_snapshot.get("primary_count"), unit="nodes", source_artifact=rel(self.root, snapshots_path), source_role="cluster_snapshots"))
        metric_records.append(self.metric("role_convergence.replica_count", value=final_snapshot.get("replica_count"), unit="nodes", source_artifact=rel(self.root, snapshots_path), source_role="cluster_snapshots"))
        metric_records.append(self.metric("data_path.result", value=evidence.get("data_path_result") if isinstance(evidence, dict) else None, source_artifact=rel(self.root, evidence_path), source_role="real_evidence"))
        metric_records.append(self.metric("data_path.probe_count", value=len(evidence.get("probes", [])) if isinstance(evidence, dict) else None, unit="probes", source_artifact=rel(self.root, evidence_path), source_role="real_evidence"))
        cleanup_timing = cleanup.get("cleanup_timing", {}) if isinstance(cleanup, dict) else {}
        for cleanup_name in [
            "cleanup_terminate_processes_seconds",
            "cleanup_verify_process_exit_seconds",
            "cleanup_verify_nodehost_empty_seconds",
            "cleanup_remove_containers_seconds",
            "cleanup_remove_networks_seconds",
            "cleanup_residual_scan_seconds",
        ]:
            metric_records.append(self.metric(f"cleanup.{cleanup_name}", value=cleanup_timing.get(cleanup_name), unit="seconds", source_artifact=rel(self.root, cleanup_path), source_role="cleanup", reason="30-node historical cleanup report predates cleanup_timing fields" if node_count == 30 else ""))
        metric_records.append(self.metric("cleanup.resources_remaining_count", value=len(cleanup.get("resources_remaining", [])) if isinstance(cleanup, dict) and isinstance(cleanup.get("resources_remaining"), list) else None, unit="resources", source_artifact=rel(self.root, cleanup_path), source_role="cleanup"))
        metric_records.append(self.metric("setup_timeline.setup_command_wall_seconds", value=setup_timeline.get("setup_command_wall_seconds") if isinstance(setup_timeline, dict) else None, unit="seconds", source_artifact=rel(self.root, setup_timeline_path), source_role="setup_timeline", reason="30-node historical evidence predates setup_timeline artifact" if node_count == 30 else ""))
        metric_records.append(self.metric("setup_timeline.total_seconds", value=setup_timeline.get("setup_timeline_total_seconds") if isinstance(setup_timeline, dict) else None, unit="seconds", source_artifact=rel(self.root, setup_timeline_path), source_role="setup_timeline", reason="30-node historical evidence predates setup_timeline artifact" if node_count == 30 else ""))
        metric_records.append(self.metric("runtime.cluster_create_duration_seconds", value=runtime_timing.get("summary", {}).get("cluster_create_duration_seconds") if isinstance(runtime_timing, dict) else None, unit="seconds", source_artifact=rel(self.root, runtime_timing_path), source_role="runtime_timing", reason="30-node historical evidence predates runtime_timing_breakdown artifact" if node_count == 30 else ""))

        for metric_record in metric_records:
            if metric_record["status"] == "MISSING" and node_count in {50, 100} and metric_record["source_role"] in {"timing_breakdown", "cleanup", "setup_timeline", "runtime_timing"}:
                add(self.finding(
                    severity="high",
                    category="missing_required_scale_build_metric",
                    blocking=True,
                    description=f"{scenario} required metric is missing: {metric_record['name']}",
                    evidence=[metric_record["source_artifact"], metric_record["reason"]],
                ))

        rung_status = "PASS" if not finding_ids else ("FAIL" if any(self.finding_by_id(fid).get("blocking") for fid in finding_ids) else "PARTIAL")
        return {
            "node_count": node_count,
            "scenario": scenario,
            "phase_id": phase_id,
            "status": rung_status,
            "evidence_path": rel(self.root, evidence_path),
            "source_artifacts": source_artifacts,
            "real_valkey": evidence.get("real_valkey") if isinstance(evidence, dict) else False,
            "nodes_observed": evidence.get("nodes_observed") if isinstance(evidence, dict) else 0,
            "cluster_state_observed": evidence.get("cluster_state_observed") if isinstance(evidence, dict) else "MISSING",
            "probe_result": evidence.get("probe_result") if isinstance(evidence, dict) else "MISSING",
            "data_path_result": evidence.get("data_path_result") if isinstance(evidence, dict) else "MISSING",
            "valkey_versions": evidence.get("valkey_versions", []) if isinstance(evidence, dict) else [],
            "metric_records": metric_records,
            "findings": finding_ids,
        }

    def finding_by_id(self, finding_id: str) -> dict[str, Any]:
        for finding in self.findings:
            if finding["id"] == finding_id:
                return finding
        return {}

    def audit_p14_boundary(self) -> dict[str, Any]:
        phase_dir = self.path(Path("artifacts/phases") / P14_ID)
        real_artifacts: list[Path] = []
        if phase_dir.exists():
            for path in sorted(phase_dir.glob("*.json")):
                try:
                    payload = load_json(path)
                except Exception:  # noqa: BLE001
                    continue
                artifact_type = str(payload.get("artifact_type", ""))
                scenario = str(payload.get("scenario", ""))
                node_count = payload.get("node_count") or payload.get("nodes_observed")
                runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
                constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
                dry_run = payload.get("dry_run") is True or runtime.get("dry_run") is True or constraints.get("dry_run") is True
                no_execution = constraints.get("no_execution") is True or payload.get("no_execution") is True
                allowed_dryrun_metadata = dry_run and (no_execution or artifact_type in {"resource_preflight", "cluster_plan", "resource_preflight_report"})
                looks_real = (
                    path.name.startswith("valkey_e2e")
                    or payload.get("real_valkey") is True
                    or scenario == "scale_1000"
                    or artifact_type in {"scale_rung_summary", "scale_ladder_report"}
                )
                if node_count == 1000 and not allowed_dryrun_metadata:
                    looks_real = True
                if artifact_type == "scale_ladder_report":
                    looks_real = looks_real and any(
                        isinstance(rung, dict)
                        and (rung.get("node_count") == 1000 or rung.get("real_valkey") is True or rung.get("evidence_path"))
                        for rung in payload.get("rungs", [])
                    )
                if looks_real:
                    real_artifacts.append(path)
        for path in real_artifacts:
            self.finding(
                severity="high",
                category="p14_real_artifact_present",
                blocking=True,
                description="P14 must not have real Valkey or real 1000-node scale artifacts in automatic L07 coverage",
                evidence=[rel(self.root, path)],
            )
        return {
            "phase_id": P14_ID,
            "status": "FAIL" if real_artifacts else "SKIPPED_WITH_REASON",
            "dry_run_only": True,
            "real_valkey_coverage": False,
            "real_evidence_count": len(real_artifacts),
            "reason": "P14 is opt-in dry-run/resource/planner only and is not counted as real scale build coverage.",
        }

    def build(self) -> dict[str, Any]:
        rungs = [self.audit_rung(node_count) for node_count in [30, 50, 100]]
        p14_boundary = self.audit_p14_boundary()
        measured = sum(1 for rung in rungs for metric in rung["metric_records"] if metric["status"] == "MEASURED")
        missing = sum(1 for rung in rungs for metric in rung["metric_records"] if metric["status"] == "MISSING")
        skipped = sum(1 for rung in rungs for metric in rung["metric_records"] if metric["status"] == "SKIPPED_WITH_REASON")
        blocking = sum(1 for finding in self.findings if finding["blocking"])
        status = "PASS" if blocking == 0 else "FAIL"
        return {
            "schema_version": "v1",
            "artifact_type": "scale_build_metrics",
            "created_at": utc_now(),
            "producer": {"name": "scripts/audit_scale_build_metrics.py", "version": "v1"},
            "status": status,
            "summary": {
                "blocking_findings_count": blocking,
                "rung_count": len(rungs),
                "canonical_node_counts": [rung["node_count"] for rung in rungs],
                "measured_metric_count": measured,
                "missing_metric_count": missing,
                "skipped_metric_count": skipped,
                "real_valkey_rung_count": sum(1 for rung in rungs if rung["real_valkey"] is True),
                "cleanup_pass_count": sum(1 for rung in rungs if any(metric["name"] == "cleanup.resources_remaining_count" and metric["value"] == 0 for metric in rung["metric_records"])),
                "p14_dry_run_only": p14_boundary["dry_run_only"],
            },
            "canonical_rungs": rungs,
            "p14_boundary": p14_boundary,
            "findings": self.findings,
        }


def build_report(root: Path) -> dict[str, Any]:
    return ScaleBuildAudit(root).build()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit 30/50/100 scale build metrics from committed artifacts")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    report = build_report(root)
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["status"] != "PASS":
        print(f"FAIL scale_build_metrics {out}", file=sys.stderr)
        return 1
    print(f"PASS scale_build_metrics {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
