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


P13_ID = "P13_SCALE_LADDER_50_100"
P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"
LEGACY_GATE_MANIFEST_SHA256ES = {
    "87fa9952002f6f606dd10984fd6700d4eb577c7388cb755ece52e4688c2adad4",
    "5f96e9eb5697dba41d9bf0f1d0d5a585b71b7687b3a51c9fcafdb13b6073d7a8",
}
P13_DIR = Path("artifacts/phases") / P13_ID
P13O_DIRS = [
    Path("artifacts/phases/P13O_CLUSTER_CREATE_AB"),
    Path("artifacts/phases/P13O_REPLICA_REPLICATE_BREAKDOWN"),
]
P13_REQUIRED_TIMING_NAMES = {
    "nodehost_start",
    "process_config_prepare",
    "process_start",
    "process_ready_wait",
    "primary_cluster_create",
    "replica_meet",
    "replica_replicate",
    "runtime_representative_probe",
    "runtime_final_full_probe",
    "wrapper_wait_cluster_ok",
    "wrapper_data_path_probe",
    "cleanup",
    "setup_command_wall",
    "state_load",
    "cleanup_command_wall",
    "artifact_write",
}
P13_REQUIRED_SUMMARY_FIELDS = {
    "total_gate_seconds",
    "setup_command_wall_seconds",
    "state_load_seconds",
    "artifact_write_seconds",
    "cleanup_command_wall_seconds",
    "cluster_create_duration_seconds",
    "replica_config_duration_seconds",
    "wrapper_probe_duration_seconds",
    "final_full_probe_duration_seconds",
    "unattributed_seconds",
    "unattributed_status",
}


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
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


class P13P14Audit:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.findings: list[dict[str, Any]] = []
        self.finding_seq = 0

    def path(self, path_text: str | Path) -> Path:
        return self.root / Path(path_text)

    def load(self, path_text: str | Path, *, schema_path: str | None = None, required: bool = True) -> Any | None:
        path = self.path(path_text)
        if not path.exists():
            self.finding(
                severity="high",
                category="missing_artifact",
                blocking=required,
                description=f"Artifact is missing: {rel(self.root, path)}",
                evidence=[rel(self.root, path)],
            )
            return None
        if path.is_file() and not path.read_text(encoding="utf-8").strip():
            self.finding(
                severity="high",
                category="empty_artifact",
                blocking=required,
                description=f"Artifact is empty: {rel(self.root, path)}",
                evidence=[rel(self.root, path)],
            )
            return None
        try:
            payload = load_json(path)
        except Exception as exc:  # noqa: BLE001
            self.finding(
                severity="high",
                category="invalid_json",
                blocking=required,
                description=f"Artifact is not valid JSON: {rel(self.root, path)}",
                evidence=[str(exc)],
            )
            return None
        if schema_path:
            schema_file = self.path(schema_path)
            if not schema_file.exists():
                self.finding(
                    severity="high",
                    category="missing_schema",
                    blocking=required,
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
                        description=f"Artifact does not validate against {schema_path}: {rel(self.root, path)}",
                        evidence=errors[:8],
                    )
        return payload

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
        finding_id = f"P13P14-{self.finding_seq:04d}"
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

    def check(self, condition: bool, *, category: str, description: str, evidence: list[str], severity: str = "high", blocking: bool = True, classification: str = "current") -> str | None:
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

    def phase_by_id(self, phase_id: str) -> dict[str, Any] | None:
        manifest = self.load("codex/phase_manifest.json")
        if not isinstance(manifest, dict):
            return None
        for phase in manifest.get("phases", []):
            if isinstance(phase, dict) and phase.get("id") == phase_id:
                return phase
        self.finding(
            severity="high",
            category="missing_manifest_phase",
            blocking=True,
            description=f"Phase is missing from manifest: {phase_id}",
            evidence=[phase_id],
        )
        return None

    def manifest_sha256(self) -> str:
        path = self.path("codex/phase_manifest.json")
        return sha256_file(path) if path.exists() else "MISSING"

    def audit_required_p13_artifacts(self, phase: dict[str, Any] | None) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not phase:
            return records
        for artifact in phase.get("required_artifacts", []):
            path_text = artifact.get("path")
            schema_path = artifact.get("schema")
            if not isinstance(path_text, str):
                continue
            payload = self.load(path_text, schema_path=schema_path if isinstance(schema_path, str) else None)
            records.append(
                {
                    "path": path_text,
                    "schema_path": schema_path,
                    "exists": self.path(path_text).exists(),
                    "status": payload.get("status") if isinstance(payload, dict) else None,
                    "sha256": sha256_file(self.path(path_text)) if self.path(path_text).exists() else None,
                }
            )
        return records

    def audit_p13_rung(self, node_count: int) -> dict[str, Any]:
        scenario = f"scale_{node_count}"
        evidence_path = P13_DIR / f"valkey_e2e_evidence_{node_count}.json"
        timing_path = P13_DIR / f"p13_timing_breakdown_scale_{node_count}.json"
        scale_rung_path = P13_DIR / f"scale_rung_{node_count}.json"
        cleanup_path = P13_DIR / f"cleanup_report_scale_{node_count}.json"
        finding_ids: list[str] = []

        evidence = self.load(evidence_path, schema_path="schemas/artifact/valkey_e2e_evidence.schema.json")
        timing = self.load(timing_path, schema_path="schemas/artifact/p13_timing_breakdown.schema.json")
        scale_rung = self.load(scale_rung_path)
        cleanup = self.load(cleanup_path, schema_path="schemas/artifact/cleanup_report.schema.json")

        def add(finding: str | None) -> None:
            if finding:
                finding_ids.append(finding)

        if isinstance(evidence, dict):
            add(self.check(evidence.get("phase_id") == P13_ID, category="invalid_p13_real_evidence", description="P13 evidence has wrong phase_id", evidence=[rel(self.root, evidence_path), str(evidence.get("phase_id"))]))
            add(self.check(evidence.get("scenario") == scenario, category="invalid_p13_real_evidence", description="P13 evidence has wrong scenario", evidence=[rel(self.root, evidence_path), str(evidence.get("scenario"))]))
            add(self.check(evidence.get("status") == "PASS", category="invalid_p13_real_evidence", description="P13 evidence is not PASS", evidence=[rel(self.root, evidence_path), str(evidence.get("status"))]))
            add(self.check(evidence.get("real_valkey") is True, category="invalid_p13_real_evidence", description="P13 evidence is not marked real_valkey=true", evidence=[rel(self.root, evidence_path)]))
            add(self.check(evidence.get("nodes_observed") == node_count, category="invalid_p13_real_evidence", description="P13 evidence nodes_observed does not match canonical rung size", evidence=[rel(self.root, evidence_path), f"expected={node_count}", f"actual={evidence.get('nodes_observed')}"]))
            add(self.check(evidence.get("cluster_state_observed") == "ok", category="invalid_p13_real_evidence", description="P13 evidence cluster_state_observed is not ok", evidence=[rel(self.root, evidence_path), str(evidence.get("cluster_state_observed"))]))
            add(self.check(evidence.get("probe_result") == "PASS", category="invalid_p13_real_evidence", description="P13 evidence probe_result is not PASS", evidence=[rel(self.root, evidence_path), str(evidence.get("probe_result"))]))
            add(self.check(evidence.get("data_path_result") == "PASS", category="invalid_p13_real_evidence", description="P13 evidence data_path_result is not PASS", evidence=[rel(self.root, evidence_path), str(evidence.get("data_path_result"))]))
            versions = evidence.get("valkey_versions", [])
            add(self.check(isinstance(versions, list) and bool(versions) and all(str(version).startswith("9.1.") for version in versions), category="invalid_p13_real_evidence", description="P13 evidence Valkey versions are missing or not 9.1.x", evidence=[rel(self.root, evidence_path), str(versions)]))
            probes = evidence.get("probes", [])
            failed = [probe for probe in probes if isinstance(probe, dict) and probe.get("status") != "PASS"]
            add(self.check(isinstance(probes, list) and len(probes) == node_count, category="invalid_p13_real_evidence", description="P13 evidence probe count does not match node count", evidence=[rel(self.root, evidence_path), f"expected={node_count}", f"actual={len(probes) if isinstance(probes, list) else 'not-list'}"]))
            add(self.check(not failed, category="invalid_p13_real_evidence", description="P13 evidence contains failed probes", evidence=[rel(self.root, evidence_path), str(failed[:3])]))
            cleanup_ref = evidence.get("cleanup", {})
            add(self.check(isinstance(cleanup_ref, dict) and cleanup_ref.get("status") == "PASS", category="invalid_p13_cleanup", description="P13 evidence cleanup reference is not PASS", evidence=[rel(self.root, evidence_path), str(cleanup_ref)]))
            add(self.check(isinstance(cleanup_ref, dict) and cleanup_ref.get("path") == rel(self.root, P13_DIR / "cleanup_report.json"), category="p13_cross_artifact_mismatch", description="P13 evidence cleanup reference does not point to the canonical P13 cleanup report", evidence=[rel(self.root, evidence_path), str(cleanup_ref)]))
            add(self.check(evidence.get("timing_breakdown_path") == rel(self.root, timing_path), category="p13_cross_artifact_mismatch", description="P13 evidence timing path does not match canonical timing artifact", evidence=[rel(self.root, evidence_path), str(evidence.get("timing_breakdown_path"))]))

        timing_checks = self.audit_timing(node_count, timing, timing_path)
        cleanup_checks = self.audit_cleanup(node_count, cleanup, cleanup_path)
        scale_checks = self.audit_scale_rung(node_count, scale_rung, scale_rung_path, rel(self.root, evidence_path))
        for block in [timing_checks, cleanup_checks, scale_checks]:
            finding_ids.extend(block.get("finding_ids", []))

        return {
            "node_count": node_count,
            "scenario": scenario,
            "status": "PASS" if not finding_ids else "FAIL",
            "evidence_path": rel(self.root, evidence_path),
            "evidence_sha256": sha256_file(self.path(evidence_path)) if self.path(evidence_path).exists() else "MISSING",
            "timing_path": rel(self.root, timing_path),
            "scale_rung_path": rel(self.root, scale_rung_path),
            "cleanup_path": rel(self.root, cleanup_path),
            "real_valkey": bool(evidence.get("real_valkey")) if isinstance(evidence, dict) else False,
            "nodes_observed": int(evidence.get("nodes_observed", 0)) if isinstance(evidence, dict) else 0,
            "probe_count": len(evidence.get("probes", [])) if isinstance(evidence, dict) and isinstance(evidence.get("probes"), list) else 0,
            "failed_probe_count": len([probe for probe in evidence.get("probes", []) if isinstance(probe, dict) and probe.get("status") != "PASS"]) if isinstance(evidence, dict) and isinstance(evidence.get("probes"), list) else 0,
            "cluster_state_observed": str(evidence.get("cluster_state_observed")) if isinstance(evidence, dict) else "MISSING",
            "data_path_result": str(evidence.get("data_path_result")) if isinstance(evidence, dict) else "MISSING",
            "valkey_versions": evidence.get("valkey_versions", []) if isinstance(evidence, dict) else [],
            "timing_checks": timing_checks,
            "cleanup_checks": cleanup_checks,
            "scale_rung_checks": scale_checks,
            "findings": finding_ids,
        }

    def audit_timing(self, node_count: int, timing: Any, timing_path: Path) -> dict[str, Any]:
        finding_ids: list[str] = []
        if not isinstance(timing, dict):
            return {"status": "FAIL", "finding_ids": finding_ids, "required_names_present": [], "missing_names": sorted(P13_REQUIRED_TIMING_NAMES)}
        expected_scenario = f"scale_{node_count}"
        for condition, category, description, actual in [
            (timing.get("status") == "PASS", "invalid_timing_artifact", "P13 timing artifact status is not PASS", timing.get("status")),
            (timing.get("node_count") == node_count, "invalid_timing_artifact", "P13 timing artifact node_count does not match canonical rung size", timing.get("node_count")),
            (timing.get("scenario") == expected_scenario, "invalid_timing_artifact", "P13 timing artifact scenario does not match canonical rung", timing.get("scenario")),
            (timing.get("phase_id") == P13_ID, "invalid_timing_artifact", "P13 timing artifact phase_id is not canonical P13", timing.get("phase_id")),
        ]:
            if not condition:
                finding_ids.append(
                    self.finding(
                        severity="high",
                        category=category,
                        blocking=True,
                        description=description,
                        evidence=[rel(self.root, timing_path), f"expected={expected_scenario if 'scenario' in description else node_count if 'node_count' in description else 'PASS' if 'status' in description else P13_ID}", f"actual={actual}"],
                    )
                )
        names = {entry.get("name") for entry in timing.get("timings", []) if isinstance(entry, dict)}
        missing_names = sorted(P13_REQUIRED_TIMING_NAMES - names)
        if missing_names:
            finding_ids.append(
                self.finding(
                    severity="high",
                    category="missing_timing_category",
                    blocking=True,
                    description="P13 timing breakdown is missing required timing categories",
                    evidence=[rel(self.root, timing_path), ",".join(missing_names)],
                )
            )
        summary = timing.get("summary", {})
        accounting = timing.get("accounting", {})
        missing_summary = sorted(P13_REQUIRED_SUMMARY_FIELDS - set(summary if isinstance(summary, dict) else {}))
        if missing_summary:
            finding_ids.append(
                self.finding(
                    severity="high",
                    category="missing_timing_summary",
                    blocking=True,
                    description="P13 timing summary is missing required fields",
                    evidence=[rel(self.root, timing_path), ",".join(missing_summary)],
                )
            )
        for field in P13_REQUIRED_SUMMARY_FIELDS - {"unattributed_status"}:
            value = summary.get(field) if isinstance(summary, dict) else None
            if not isinstance(value, (int, float)) or value < 0:
                finding_ids.append(
                    self.finding(
                        severity="high",
                        category="invalid_timing_duration",
                        blocking=True,
                        description="P13 timing duration is missing, nonnumeric, or negative",
                        evidence=[rel(self.root, timing_path), field, repr(value)],
                    )
                )
        if isinstance(summary, dict) and summary.get("diagnostic_full_probe_duration_seconds") == "MISSING":
            missing_semantics = {
                "status": "MISSING",
                "reason": "Diagnostic full probe duration is optional diagnostic data; wrapper and final full probes are measured.",
            }
        else:
            missing_semantics = {"status": "PRESENT", "reason": ""}
        if not isinstance(accounting, dict) or accounting.get("unattributed_status") not in {"PASS", "SKIPPED_WITH_REASON"}:
            finding_ids.append(
                self.finding(
                    severity="high",
                    category="invalid_timing_accounting",
                    blocking=True,
                    description="P13 timing accounting status is not acceptable",
                    evidence=[rel(self.root, timing_path), str(accounting.get("unattributed_status") if isinstance(accounting, dict) else None)],
                )
            )
        for entry in timing.get("timings", []):
            if isinstance(entry, dict) and "duration_seconds" in entry:
                value = entry.get("duration_seconds")
                if not isinstance(value, (int, float)) or value < 0:
                    finding_ids.append(
                        self.finding(
                            severity="high",
                            category="invalid_timing_duration",
                            blocking=True,
                            description="P13 timing entry duration is missing, nonnumeric, or negative",
                            evidence=[rel(self.root, timing_path), str(entry.get("name")), repr(value)],
                        )
                    )
        return {
            "status": "PASS" if not finding_ids else "FAIL",
            "finding_ids": finding_ids,
            "node_count": node_count,
            "required_names_present": sorted(P13_REQUIRED_TIMING_NAMES & names),
            "missing_names": missing_names,
            "summary_fields_present": sorted(set(summary) & P13_REQUIRED_SUMMARY_FIELDS) if isinstance(summary, dict) else [],
            "missing_semantics": missing_semantics,
        }

    def audit_cleanup(self, node_count: int, cleanup: Any, cleanup_path: Path) -> dict[str, Any]:
        finding_ids: list[str] = []
        if not isinstance(cleanup, dict):
            return {"status": "FAIL", "finding_ids": finding_ids, "resources_remaining_count": None, "action_count": 0}
        resources = cleanup.get("resources_remaining")
        actions = cleanup.get("cleanup_actions")
        if cleanup.get("status") != "PASS":
            finding_ids.append(self.finding(severity="high", category="invalid_p13_cleanup", blocking=True, description="P13 cleanup report is not PASS", evidence=[rel(self.root, cleanup_path), str(cleanup.get("status"))]))
        if not isinstance(resources, list) or resources:
            finding_ids.append(self.finding(severity="high", category="cleanup_residue", blocking=True, description="P13 cleanup report has residual resources", evidence=[rel(self.root, cleanup_path), str(resources)]))
        if not isinstance(actions, list) or not actions:
            finding_ids.append(self.finding(severity="high", category="invalid_p13_cleanup", blocking=True, description="P13 cleanup report has no cleanup actions", evidence=[rel(self.root, cleanup_path)]))
        skipped_without_reason = [
            action for action in actions or []
            if isinstance(action, dict) and action.get("status") == "SKIPPED_WITH_REASON" and not action.get("reason")
        ]
        skipped_policy = "SKIPPED_WITH_REASON cleanup actions without per-action reason are accepted only because final cleanup status is PASS and resources_remaining is empty."
        if skipped_without_reason and (cleanup.get("status") != "PASS" or resources):
            finding_ids.append(self.finding(severity="high", category="cleanup_skip_without_residual_proof", blocking=True, description="Skipped cleanup actions lack residual-free proof", evidence=[rel(self.root, cleanup_path), str(len(skipped_without_reason))]))
        return {
            "status": "PASS" if not finding_ids else "FAIL",
            "finding_ids": finding_ids,
            "node_count": node_count,
            "resources_remaining_count": len(resources) if isinstance(resources, list) else None,
            "action_count": len(actions) if isinstance(actions, list) else 0,
            "skipped_without_reason_count": len(skipped_without_reason),
            "skipped_policy": skipped_policy if skipped_without_reason else "",
        }

    def audit_scale_rung(self, node_count: int, scale_rung: Any, scale_rung_path: Path, evidence_path: str) -> dict[str, Any]:
        finding_ids: list[str] = []
        if not isinstance(scale_rung, dict):
            return {"status": "FAIL", "finding_ids": finding_ids}
        checks = [
            (scale_rung.get("phase_id") == P13_ID, "scale_rung phase_id mismatch", scale_rung.get("phase_id")),
            (scale_rung.get("scenario") == f"scale_{node_count}", "scale_rung scenario mismatch", scale_rung.get("scenario")),
            (scale_rung.get("status") == "PASS", "scale_rung status mismatch", scale_rung.get("status")),
            (scale_rung.get("node_count") == node_count, "scale_rung node_count mismatch", scale_rung.get("node_count")),
            (scale_rung.get("evidence_path") == evidence_path, "scale_rung evidence path mismatch", scale_rung.get("evidence_path")),
        ]
        for condition, description, actual in checks:
            if not condition:
                finding_ids.append(self.finding(severity="high", category="p13_cross_artifact_mismatch", blocking=True, description=description, evidence=[rel(self.root, scale_rung_path), str(actual)]))
        return {"status": "PASS" if not finding_ids else "FAIL", "finding_ids": finding_ids}

    def audit_scale_report(self) -> dict[str, Any]:
        path = P13_DIR / "scale_ladder_report.json"
        report = self.load(path, schema_path="schemas/artifact/scale_ladder_report.schema.json")
        finding_ids: list[str] = []
        canonical = {
            50: f"artifacts/phases/{P13_ID}/valkey_e2e_evidence_50.json",
            100: f"artifacts/phases/{P13_ID}/valkey_e2e_evidence_100.json",
        }
        if isinstance(report, dict):
            rungs = report.get("rungs", [])
            by_count = {rung.get("node_count"): rung for rung in rungs if isinstance(rung, dict)}
            if set(by_count) != {50, 100}:
                finding_ids.append(self.finding(severity="high", category="p13_scale_report_inconsistent", blocking=True, description="P13 scale report does not contain exactly 50 and 100 rungs", evidence=[rel(self.root, path), str(sorted(by_count))]))
            for count, evidence_path in canonical.items():
                rung = by_count.get(count, {})
                if rung.get("status") != "PASS" or rung.get("evidence_path") != evidence_path:
                    finding_ids.append(self.finding(severity="high", category="p13_scale_report_inconsistent", blocking=True, description="P13 scale report rung is not PASS or points to noncanonical evidence", evidence=[rel(self.root, path), str(count), str(rung)]))
            summary = report.get("summary", {})
            comparison = summary.get("comparison", {}) if isinstance(summary, dict) else {}
            if comparison.get("from_nodes") != 50 or comparison.get("to_nodes") != 100 or comparison.get("node_count_multiplier") != 2.0:
                finding_ids.append(self.finding(severity="high", category="p13_scale_report_inconsistent", blocking=True, description="P13 scale report comparison is not 50 -> 100 with multiplier 2.0", evidence=[rel(self.root, path), str(comparison)]))
            real_paths = set(summary.get("real_evidence_paths", [])) if isinstance(summary, dict) else set()
            if real_paths != set(canonical.values()):
                finding_ids.append(self.finding(severity="high", category="p13_scale_report_inconsistent", blocking=True, description="P13 scale report real evidence paths are not canonical", evidence=[rel(self.root, path), str(sorted(real_paths))]))
        return {
            "path": rel(self.root, path),
            "status": "PASS" if not finding_ids else "FAIL",
            "finding_ids": finding_ids,
            "expected_rungs": [50, 100],
        }

    def audit_gate_compatibility(self, phase: dict[str, Any] | None) -> dict[str, Any]:
        path = Path("artifacts/gates") / P13_ID / "gate_result.json"
        gate_result = self.load(path, schema_path="schemas/artifact/gate_result.schema.json")
        finding_ids: list[str] = []
        historical_findings: list[str] = []
        if not isinstance(gate_result, dict) or not phase:
            return {"path": rel(self.root, path), "status": "FAIL", "finding_ids": finding_ids}
        if gate_result.get("status") != "PASS":
            finding_ids.append(self.finding(severity="high", category="p13_gate_incompatible", blocking=True, description="P13 gate result is not PASS", evidence=[rel(self.root, path), str(gate_result.get("status"))]))
        manifest_sha = self.manifest_sha256()
        observed_manifest_sha = gate_result.get("manifest_sha256")
        if observed_manifest_sha != manifest_sha:
            if observed_manifest_sha in LEGACY_GATE_MANIFEST_SHA256ES:
                historical_findings.append(
                    self.finding(
                        severity="medium",
                        category="p13_historical_manifest_drift",
                        blocking=False,
                        classification="historical",
                        description="P13 gate result has allowlisted legacy manifest SHA drift",
                        evidence=[str(observed_manifest_sha), manifest_sha],
                    )
                )
            else:
                finding_ids.append(self.finding(severity="high", category="p13_gate_incompatible", blocking=True, description="P13 gate result manifest SHA drift is not allowlisted", evidence=[str(observed_manifest_sha), manifest_sha]))
        actual_by_name = {gate.get("name"): gate for gate in gate_result.get("gates", []) if isinstance(gate, dict)}
        for expected in phase.get("gates", []):
            name = expected.get("name")
            actual = actual_by_name.get(name)
            if not actual:
                finding_ids.append(self.finding(severity="high", category="p13_gate_incompatible", blocking=True, description="P13 gate result is missing a manifest gate", evidence=[str(name)]))
                continue
            if actual.get("status") != "PASS":
                finding_ids.append(self.finding(severity="high", category="p13_gate_incompatible", blocking=True, description="P13 gate result contains non-PASS gate", evidence=[str(name), str(actual.get("status"))]))
            if actual.get("command") != expected.get("command"):
                if name == "scale_tests":
                    historical_findings.append(
                        self.finding(
                            severity="medium",
                            category="p13_historical_command_drift",
                            blocking=False,
                            classification="historical",
                            description="P13 scale_tests command drift is historical and explicitly recorded",
                            evidence=[str(actual.get("command")), str(expected.get("command"))],
                        )
                    )
                else:
                    finding_ids.append(self.finding(severity="high", category="p13_gate_incompatible", blocking=True, description="Unexpected P13 gate command mismatch", evidence=[str(name), str(actual.get("command")), str(expected.get("command"))]))
            for log_key, sha_key in [("stdout_path", "stdout_sha256"), ("stderr_path", "stderr_sha256")]:
                log_path = actual.get(log_key)
                if isinstance(log_path, str) and self.path(log_path).exists():
                    actual_sha = sha256_file(self.path(log_path))
                    if actual.get(sha_key) != actual_sha:
                        finding_ids.append(self.finding(severity="high", category="p13_gate_log_mismatch", blocking=True, description="P13 gate log checksum mismatch", evidence=[str(name), log_path, str(actual.get(sha_key)), actual_sha]))
                else:
                    finding_ids.append(self.finding(severity="high", category="p13_gate_log_missing", blocking=True, description="P13 gate log path is missing", evidence=[str(name), str(log_path)]))
        audit_path = "audit/P13_SCALE_LADDER_50_100/audit_decision.json"
        audit_decision = self.load(audit_path, schema_path="schemas/artifact/audit_decision.schema.json")
        if isinstance(audit_decision, dict) and audit_decision.get("decision") != "PASS":
            finding_ids.append(self.finding(severity="high", category="p13_audit_decision_invalid", blocking=True, description="P13 audit decision is not PASS", evidence=[audit_path, str(audit_decision.get("decision"))]))
        return {
            "path": rel(self.root, path),
            "status": "PASS" if not finding_ids else "FAIL",
            "finding_ids": finding_ids,
            "historical_finding_ids": historical_findings,
            "historical_drift_allowed": bool(historical_findings),
        }

    def audit_p13o(self) -> dict[str, Any]:
        paths: list[str] = []
        canonical = {
            f"artifacts/phases/{P13_ID}/valkey_e2e_evidence_50.json",
            f"artifacts/phases/{P13_ID}/valkey_e2e_evidence_100.json",
        }
        for directory in P13O_DIRS:
            if self.path(directory).exists():
                paths.extend(sorted(rel(self.root, path) for path in self.path(directory).glob("*.json")))
        return {
            "classified_separately": True,
            "paths": paths,
            "canonical_evidence_paths": sorted(canonical),
        }

    def audit_p14(self, phase: dict[str, Any] | None) -> dict[str, Any]:
        finding_ids: list[str] = []
        dry_artifacts: list[str] = []
        p14_dir = self.path(Path("artifacts/phases") / P14_ID)
        p14_gate = self.path(Path("artifacts/gates") / P14_ID / "gate_result.json")
        real_evidence = list(p14_dir.glob("valkey_e2e_evidence*.json")) if p14_dir.exists() else []
        if real_evidence:
            finding_ids.append(self.finding(severity="high", category="p14_real_evidence_present", blocking=True, description="P14 real evidence artifact is present by default", evidence=[rel(self.root, path) for path in real_evidence]))
        if p14_gate.exists():
            finding_ids.append(self.finding(severity="high", category="p14_default_gate_present", blocking=True, description="P14 gate_result is present without explicit L04 opt-in", evidence=[rel(self.root, p14_gate)]))
        if phase:
            if phase.get("max_nodes") != 1000:
                finding_ids.append(self.finding(severity="high", category="p14_boundary_violation", blocking=True, description="P14 manifest max_nodes is not 1000", evidence=[str(phase.get("max_nodes"))]))
            if phase.get("automatic") is not False:
                finding_ids.append(self.finding(severity="high", category="p14_boundary_violation", blocking=True, description="P14 manifest automatic flag is not false", evidence=[str(phase.get("automatic"))]))
            if phase.get("real_valkey_required") is not False:
                finding_ids.append(self.finding(severity="high", category="p14_boundary_violation", blocking=True, description="P14 manifest real_valkey_required is not false", evidence=[str(phase.get("real_valkey_required"))]))
            for gate in phase.get("gates", []):
                if gate.get("real_valkey") is not False:
                    finding_ids.append(self.finding(severity="high", category="p14_boundary_violation", blocking=True, description="P14 gate has real_valkey=true", evidence=[str(gate.get("name"))]))
            command_text = "\n".join(str(gate.get("command", "")) for gate in phase.get("gates", []))
            if "VSLAB_ALLOW_1000_DRYRUN" not in command_text:
                finding_ids.append(self.finding(severity="high", category="p14_opt_in_missing", blocking=True, description="P14 manifest commands do not include opt-in guard", evidence=[P14_ID]))
            for gate in phase.get("gates", []):
                command = str(gate.get("command", ""))
                if gate.get("name") in {"resource_preflight_1000_dryrun", "planner_1000_dryrun"} and "--dry-run" not in command:
                    finding_ids.append(self.finding(severity="high", category="p14_dry_run_missing", blocking=True, description="P14 dry-run command lacks --dry-run", evidence=[str(gate.get("name")), command]))
        template = self.path("templates/configs/scale_1000_dryrun_optin.yaml")
        if not template.exists():
            finding_ids.append(self.finding(severity="high", category="p14_config_missing", blocking=True, description="P14 opt-in dry-run config is missing", evidence=[rel(self.root, template)]))
        else:
            text = template.read_text(encoding="utf-8")
            for token in ["allow_1000_nodes: true", "require_1000_env: VSLAB_ALLOW_1000_DRYRUN", "dry_run: true", "dry_run_only: true", "opt_in_1000: true"]:
                if token not in text:
                    finding_ids.append(self.finding(severity="high", category="p14_config_boundary_violation", blocking=True, description="P14 opt-in config is missing required dry-run token", evidence=[token]))
        plan_path = "artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json"
        plan = self.load(plan_path, schema_path="schemas/artifact/cluster_plan.schema.json", required=False)
        if isinstance(plan, dict):
            dry_artifacts.append(plan_path)
            constraints = plan.get("constraints", {})
            runtime = plan.get("runtime", {})
            ok = (
                plan.get("node_count") == 1000
                and plan.get("phase_id") == "P02_PLANNER"
                and plan.get("status") == "PASS"
                and isinstance(constraints, dict)
                and constraints.get("dry_run") is True
                and constraints.get("no_execution") is True
                and constraints.get("opt_in_1000") is True
                and constraints.get("default_node_cap") == 100
                and isinstance(runtime, dict)
                and runtime.get("dry_run") is True
            )
            if not ok:
                finding_ids.append(self.finding(severity="high", category="invalid_1000_dryrun_plan", blocking=True, description="P02 1000-node planner artifact is not constrained to dry-run/no-execution/opt-in", evidence=[plan_path, str(constraints), str(runtime)]))
        return {
            "phase_id": P14_ID,
            "status": "SKIPPED_WITH_REASON" if not finding_ids else "FAIL",
            "automatic": bool(phase.get("automatic")) if phase else True,
            "real_valkey_required": bool(phase.get("real_valkey_required")) if phase else True,
            "max_nodes": int(phase.get("max_nodes", 0)) if isinstance(phase, dict) and isinstance(phase.get("max_nodes"), int) else 0,
            "dry_run_only": True,
            "real_valkey_coverage": False,
            "opt_in_required": True,
            "default_gate_result_present": p14_gate.exists(),
            "real_evidence_count": len(real_evidence),
            "dry_run_artifacts": dry_artifacts,
            "finding_ids": finding_ids,
            "reason": "P14 is opt-in dry-run/resource/planner only and was not executed by L04.",
        }

    def build(self) -> dict[str, Any]:
        p13_phase = self.phase_by_id(P13_ID)
        p14_phase = self.phase_by_id(P14_ID)
        required_artifacts = self.audit_required_p13_artifacts(p13_phase)
        rungs = [self.audit_p13_rung(50), self.audit_p13_rung(100)]
        scale_report = self.audit_scale_report()
        gate_compatibility = self.audit_gate_compatibility(p13_phase)
        p13o = self.audit_p13o()
        p14 = self.audit_p14(p14_phase)
        p13_status = "PASS" if all(rung["status"] == "PASS" for rung in rungs) and scale_report["status"] == "PASS" and gate_compatibility["status"] == "PASS" else "FAIL"
        blocking = [finding for finding in self.findings if finding["blocking"]]
        return {
            "schema_version": "v1",
            "artifact_type": "p13_p14_scale_audit",
            "created_at": utc_now(),
            "producer": {"name": "scripts/audit_p13_p14_scale.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "summary": {
                "blocking_findings_count": len(blocking),
                "p13_rung_count": len(rungs),
                "p13_real_evidence_count": sum(1 for rung in rungs if rung["real_valkey"] and rung["status"] == "PASS"),
                "p13_canonical_node_counts": [rung["node_count"] for rung in rungs],
                "p14_status": p14["status"],
                "p14_real_evidence_count": p14["real_evidence_count"],
                "p14_dry_run_only": p14["dry_run_only"],
            },
            "p13": {
                "phase_id": P13_ID,
                "status": p13_status,
                "canonical_artifact_dir": rel(self.root, self.path(P13_DIR)),
                "rungs": rungs,
                "scale_report": scale_report,
                "gate_compatibility": gate_compatibility,
                "optimization_artifacts": p13o,
                "required_artifacts": required_artifacts,
            },
            "p14_boundary": p14,
            "findings": self.findings,
        }


def build_report(root: Path) -> dict[str, Any]:
    return P13P14Audit(root).build()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit P13/P14 scale artifact boundaries")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    report = build_report(root)
    schema_path = root / "schemas/artifact/p13_p14_scale_audit.schema.json"
    schema_errors = validate(report, load_json(schema_path)) if schema_path.exists() else [f"schema missing: {schema_path}"]
    if schema_errors:
        for error in schema_errors:
            print(f"p13_p14_scale_audit schema error: {error}", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    status = "PASS" if report["status"] == "PASS" and not schema_errors else "FAIL"
    print(f"{status} p13_p14_scale_audit {rel(root, out)}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
