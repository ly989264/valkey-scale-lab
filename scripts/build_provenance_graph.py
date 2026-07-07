#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402


TARGET_PHASES = [
    "P09_ANALYSIS_REPORTING",
    "P11_STABILITY_SOAK",
    "P12_SCALE_LADDER_10_30",
    "P13_SCALE_LADDER_50_100",
]
P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"
REPORT_VIEW_SUFFIXES = {".csv", ".html", ".md", ".svg"}
JSON_SUFFIXES = {".json", ".jsonl"}
PROVENANCE_SOURCE_RELATIONS = {
    "source_artifact",
    "report_input",
    "stability_source",
    "scale_source",
    "rung_evidence",
    "rung_preflight",
    "timing_source",
    "setup_timeline_source",
    "fault_failover_source",
    "stability_soak_source",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_safe(path: Path) -> tuple[Any | None, str | None]:
    try:
        return load_json(path), None
    except Exception as exc:  # noqa: BLE001 - provenance reports exact parse errors.
        return None, str(exc)


def load_jsonl_first(path: Path) -> tuple[Any | None, str | None]:
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return json.loads(line), None
        return None, "JSONL file has no records"
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def git_head(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode == 0:
        return proc.stdout.strip()
    return "UNKNOWN"


class ProvenanceGraph:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = load_json(root / "codex" / "phase_manifest.json")
        self.manifest_sha256 = sha256_file(root / "codex" / "phase_manifest.json")
        self.schema_by_path: dict[str, str] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.node_payloads: dict[str, Any] = {}
        self.edges: list[dict[str, Any]] = []
        self.edge_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.skipped_declared_source_keys: set[tuple[str, str]] = set()
        self.findings: list[dict[str, Any]] = []
        self.finding_seq = 0
        self.report_view_paths: set[str] = set()
        self.phase_required_paths: dict[str, list[str]] = defaultdict(list)

    def finding(
        self,
        *,
        severity: str,
        category: str,
        blocking: bool,
        description: str,
        evidence: list[str],
        phase_id: str | None = None,
        path: str | None = None,
    ) -> str:
        self.finding_seq += 1
        fid = f"PV-{self.finding_seq:04d}"
        record: dict[str, Any] = {
            "id": fid,
            "severity": severity,
            "category": category,
            "blocking": blocking,
            "description": description,
            "evidence": evidence,
        }
        if phase_id:
            record["phase_id"] = phase_id
        if path:
            record["path"] = path
        self.findings.append(record)
        return fid

    def rel_path(self, path_text: str | Path) -> str:
        path = Path(path_text)
        if path.is_absolute():
            return rel(self.root, path)
        return path.as_posix()

    def load_payload(self, path_text: str) -> tuple[Any | None, str | None]:
        path = self.root / path_text
        if not path.exists():
            return None, None
        if path.suffix == ".json":
            return load_json_safe(path)
        if path.suffix == ".jsonl":
            return load_jsonl_first(path)
        return None, None

    def infer_schema_path(self, path_text: str, payload: Any | None) -> str | None:
        if self.schema_skip_reason(path_text, payload):
            return None
        if path_text in self.schema_by_path:
            return self.schema_by_path[path_text]
        artifact_type = payload.get("artifact_type") if isinstance(payload, dict) else None
        if artifact_type:
            candidate = self.root / "schemas" / "artifact" / f"{artifact_type}.schema.json"
            if candidate.exists():
                return rel(self.root, candidate)
        if path_text.endswith(".jsonl") and isinstance(payload, dict):
            artifact_type = payload.get("artifact_type")
            if artifact_type:
                candidate = self.root / "schemas" / "artifact" / f"{artifact_type}.schema.json"
                if candidate.exists():
                    return rel(self.root, candidate)
        return None

    def schema_skip_reason(self, path_text: str, payload: Any | None) -> str | None:
        suffix = Path(path_text).suffix
        if suffix not in JSON_SUFFIXES:
            return "Non-JSON evidence is hash-tracked but has no JSON schema."
        if "/runtime_timing_breakdown_scale_" in path_text:
            return (
                "Historical runtime timing source predates the stricter "
                "p13_timing_breakdown schema; canonical p13_timing_breakdown_scale "
                "artifacts are schema-validated separately."
            )
        artifact_type = payload.get("artifact_type") if isinstance(payload, dict) else None
        if artifact_type:
            candidate = self.root / "schemas" / "artifact" / f"{artifact_type}.schema.json"
            if not candidate.exists():
                return f"No artifact schema is defined for historical artifact_type={artifact_type}."
        return None

    def artifact_role(self, path_text: str, payload: Any | None, force_report_view: bool = False) -> str:
        suffix = Path(path_text).suffix
        if force_report_view or path_text in self.report_view_paths:
            if suffix == ".html":
                return "html_report"
            if suffix == ".md":
                return "markdown_report"
            if suffix == ".svg":
                return "visualization"
            if suffix == ".csv":
                return "csv_view"
            return "report_view"
        if isinstance(payload, dict):
            artifact_type = payload.get("artifact_type")
            if artifact_type == "valkey_e2e_evidence":
                return "real_evidence"
            if artifact_type == "resource_preflight":
                return "resource_preflight"
            if artifact_type == "cleanup_report":
                return "cleanup"
            if artifact_type == "phase_summary":
                return "phase_summary"
            if artifact_type == "analysis_summary":
                return "analysis"
            if artifact_type == "report_index":
                return "report_index"
            if artifact_type == "stability_report":
                return "stability_report"
            if artifact_type == "scale_ladder_report":
                return "scale_report"
            if artifact_type == "p13_timing_breakdown":
                return "timing_analysis"
            if artifact_type == "cluster_plan" and self.is_dry_run(payload, path_text):
                return "dry_run_plan"
            if artifact_type:
                return str(artifact_type)
        if suffix == ".jsonl":
            return "timeseries"
        if suffix == ".log":
            return "log"
        if suffix == ".html":
            return "html_report"
        if suffix == ".md":
            return "markdown_report"
        if suffix == ".svg":
            return "visualization"
        if suffix == ".csv":
            return "csv_view"
        return "artifact"

    def is_dry_run(self, payload: Any | None, path_text: str) -> bool:
        if "1000_dryrun" in path_text or "scale_1000_dryrun" in path_text:
            return True
        if not isinstance(payload, dict):
            return False
        runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
        constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
        return runtime.get("dry_run") is True or constraints.get("no_execution") is True

    def add_node(self, path_text: str | Path, schema_path: str | None = None, *, force_report_view: bool = False) -> dict[str, Any]:
        path_text = self.rel_path(path_text)
        if force_report_view:
            self.report_view_paths.add(path_text)
        if path_text in self.nodes:
            node = self.nodes[path_text]
            if schema_path and not node.get("schema_path"):
                node["schema_path"] = schema_path
            if force_report_view:
                node["source_of_truth"] = False
                node["artifact_role"] = self.artifact_role(path_text, self.node_payloads.get(path_text), True)
            return node

        path = self.root / path_text
        exists = path.exists()
        payload, parse_error = self.load_payload(path_text)
        if payload is not None:
            self.node_payloads[path_text] = payload
        inferred_schema = schema_path or self.infer_schema_path(path_text, payload)
        schema_sha: str | None = None
        schema_valid: bool | None = None
        schema_errors: list[str] = []
        if inferred_schema:
            schema_file = self.root / inferred_schema
            if schema_file.exists():
                schema_sha = sha256_file(schema_file)
                if payload is not None and Path(path_text).suffix in JSON_SUFFIXES:
                    schema = load_json(schema_file)
                    if Path(path_text).suffix == ".jsonl":
                        errors: list[str] = []
                        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                            if line.strip():
                                try:
                                    errors.extend(validate(json.loads(line), schema, f"$[line {line_no}]"))
                                except json.JSONDecodeError as exc:
                                    errors.append(f"$[line {line_no}]: invalid JSON: {exc}")
                        schema_valid = not errors
                        schema_errors = errors[:20]
                    else:
                        errors = validate(payload, schema)
                        schema_valid = not errors
                        schema_errors = errors[:20]
        artifact_type = payload.get("artifact_type") if isinstance(payload, dict) else None
        phase_id = payload.get("phase_id") if isinstance(payload, dict) else None
        run_id = payload.get("run_id") if isinstance(payload, dict) else None
        producer = payload.get("producer") if isinstance(payload, dict) else None
        status = payload.get("status") if isinstance(payload, dict) else None
        role = self.artifact_role(path_text, payload, force_report_view)
        source_of_truth = role not in {"html_report", "markdown_report", "visualization", "csv_view", "report_view"}
        dry_run_only = self.is_dry_run(payload, path_text)
        node = {
            "id": path_text,
            "path": path_text,
            "exists": exists,
            "sha256": sha256_file(path) if exists else None,
            "hash_status": "PRESENT" if exists else "MISSING",
            "artifact_role": role,
            "source_of_truth": source_of_truth,
            "artifact_type": artifact_type or role,
            "phase_id": phase_id,
            "run_id": run_id,
            "producer": producer if isinstance(producer, dict) else None,
            "status": status,
            "schema_path": inferred_schema,
            "schema_sha256": schema_sha,
            "schema_valid": schema_valid,
            "metadata_status": {},
            "dry_run_only": dry_run_only,
            "real_valkey_coverage": bool(isinstance(payload, dict) and payload.get("real_valkey") is True and not dry_run_only),
        }
        if schema_errors:
            node["schema_errors"] = schema_errors
        if parse_error:
            node["parse_error"] = parse_error
            self.finding(
                severity="high",
                category="invalid_json",
                blocking=True,
                path=path_text,
                phase_id=phase_id,
                description=f"Artifact could not be parsed: {path_text}",
                evidence=[parse_error],
            )
        self.nodes[path_text] = node
        return node

    def add_edge(
        self,
        source_path: str | Path,
        target_path: str | Path,
        *,
        relation: str,
        discovered_by: str,
        evidence_pointer: str,
        required: bool = True,
        expected_source_sha256: str | None = None,
        expected_target_sha256: str | None = None,
    ) -> dict[str, Any]:
        source_path = self.rel_path(source_path)
        target_path = self.rel_path(target_path)
        edge_key = (
            source_path,
            target_path,
            relation,
            discovered_by,
            evidence_pointer,
            required,
            expected_source_sha256,
            expected_target_sha256,
        )
        if edge_key in self.edge_by_key:
            return self.edge_by_key[edge_key]

        source = self.add_node(source_path)
        target = self.add_node(target_path)
        status = "PASS"
        hash_status = "NOT_DECLARED"
        finding_ids: list[str] = []

        if not source["exists"]:
            status = "FAIL"
            hash_status = "MISSING"
            if required:
                finding_ids.append(
                    self.finding(
                        severity="high",
                        category="missing_source_artifact",
                        blocking=True,
                        path=source_path,
                        phase_id=target.get("phase_id"),
                        description=f"Required provenance source is missing: {source_path}",
                        evidence=[f"target={target_path}", f"relation={relation}", evidence_pointer],
                    )
                )
        if not target["exists"]:
            status = "FAIL"
            if required:
                finding_ids.append(
                    self.finding(
                        severity="high",
                        category="missing_edge_endpoint",
                        blocking=True,
                        path=target_path,
                        phase_id=source.get("phase_id"),
                        description=f"Provenance edge target is missing: {target_path}",
                        evidence=[f"source={source_path}", f"relation={relation}", evidence_pointer],
                    )
                )
        if source["exists"] and expected_source_sha256:
            if source["sha256"] == expected_source_sha256:
                hash_status = "MATCH"
            else:
                status = "FAIL"
                hash_status = "MISMATCH"
                finding_ids.append(
                    self.finding(
                        severity="high",
                        category="source_hash_mismatch",
                        blocking=True,
                        path=source_path,
                        phase_id=target.get("phase_id"),
                        description=f"Source artifact hash mismatch: {source_path}",
                        evidence=[
                            f"expected={expected_source_sha256}",
                            f"actual={source['sha256']}",
                            f"target={target_path}",
                            evidence_pointer,
                        ],
                    )
                )
        if target["exists"] and expected_target_sha256:
            if target["sha256"] == expected_target_sha256:
                hash_status = "MATCH"
            else:
                status = "FAIL"
                hash_status = "MISMATCH"
                category = "report_view_hash_mismatch" if not target["source_of_truth"] else "source_hash_mismatch"
                finding_ids.append(
                    self.finding(
                        severity="high",
                        category=category,
                        blocking=True,
                        path=target_path,
                        phase_id=target.get("phase_id") or source.get("phase_id"),
                        description=f"Target artifact hash mismatch: {target_path}",
                        evidence=[
                            f"expected={expected_target_sha256}",
                            f"actual={target['sha256']}",
                            f"source={source_path}",
                            evidence_pointer,
                        ],
                    )
                )
        if not source["source_of_truth"] and relation in {"source_artifact", "derived_from", "scale_source", "stability_source"}:
            status = "FAIL"
            finding_ids.append(
                self.finding(
                    severity="high",
                    category="report_view_used_as_source",
                    blocking=True,
                    path=source_path,
                    phase_id=target.get("phase_id"),
                    description=f"Rendered report view cannot be a source-of-truth node: {source_path}",
                    evidence=[f"target={target_path}", f"relation={relation}", evidence_pointer],
                )
            )

        edge = {
            "source_path": source_path,
            "target_path": target_path,
            "relation": relation,
            "discovered_by": discovered_by,
            "evidence_pointer": evidence_pointer,
            "required": required,
            "status": status,
            "hash_status": hash_status,
            "source_sha256": source.get("sha256"),
            "target_sha256": target.get("sha256"),
            "declared_source_sha256": expected_source_sha256,
            "declared_target_sha256": expected_target_sha256,
            "finding_ids": finding_ids,
        }
        self.edges.append(edge)
        self.edge_by_key[edge_key] = edge
        return edge

    def should_skip_declared_source(self, target_path: str, source_path: str, payload: dict[str, Any]) -> bool:
        if payload.get("artifact_type") != "p13_setup_exhaustive_timeline":
            return False
        if "/p13_timing_breakdown_scale_" not in source_path:
            return False
        key = (source_path, target_path)
        if key not in self.skipped_declared_source_keys:
            self.skipped_declared_source_keys.add(key)
            self.finding(
                severity="medium",
                category="legacy_declared_source_skipped",
                blocking=False,
                path=target_path,
                phase_id=payload.get("phase_id"),
                description=(
                    "Skipped legacy P13 setup timeline source_artifacts edge that "
                    "points opposite the L02 timing-source provenance relation."
                ),
                evidence=[f"declared_source={source_path}", f"target={target_path}"],
            )
        return True

    def register_manifest_artifacts(self) -> None:
        for phase in self.manifest.get("phases", []):
            phase_id = phase.get("id", "")
            if phase.get("automatic", True) and phase_id != P14_ID:
                for artifact in phase.get("required_artifacts", []):
                    if artifact.get("required", True):
                        path = artifact["path"]
                        self.schema_by_path[path] = artifact.get("schema", "")
                        self.phase_required_paths[phase_id].append(path)
                        self.add_node(path, artifact.get("schema", ""))

    def process_explicit_sources(self) -> None:
        processed: set[str] = set()
        changed = True
        while changed:
            changed = False
            for path_text, payload in list(self.node_payloads.items()):
                if path_text in processed or not isinstance(payload, dict):
                    continue
                processed.add(path_text)
                for idx, item in enumerate(payload.get("source_artifacts", []) or []):
                    if isinstance(item, dict) and item.get("path"):
                        source_path = item["path"]
                        if self.should_skip_declared_source(path_text, source_path, payload):
                            continue
                        target_type = str(payload.get("artifact_type") or "")
                        allows_report_view_inputs = target_type in {
                            "analysis_provenance",
                            "final_artifact_manifest",
                            "report_index",
                            "strict_visual_report_index",
                        }
                        relation = (
                            "report_view_input"
                            if allows_report_view_inputs and Path(str(source_path)).suffix in REPORT_VIEW_SUFFIXES
                            else "source_artifact"
                        )
                        self.add_edge(
                            source_path,
                            path_text,
                            relation=relation,
                            discovered_by="source_artifacts",
                            evidence_pointer=f"{path_text}.source_artifacts[{idx}]",
                            expected_source_sha256=item.get("sha256"),
                        )
                        changed = True
                for idx, item in enumerate(payload.get("sidecars", []) or []):
                    if isinstance(item, dict) and item.get("path"):
                        self.add_edge(
                            path_text,
                            item["path"],
                            relation="sidecar",
                            discovered_by="sidecars",
                            evidence_pointer=f"{path_text}.sidecars[{idx}]",
                            expected_target_sha256=item.get("sha256"),
                            required=False,
                        )
                        changed = True

    def build_p09(self) -> None:
        phase_dir = "artifacts/phases/P09_ANALYSIS_REPORTING"
        analysis = f"{phase_dir}/analysis_summary.json"
        report_index = f"{phase_dir}/report_index.json"
        self.add_node(analysis, self.schema_by_path.get(analysis))
        index_node = self.add_node(report_index, self.schema_by_path.get(report_index))
        payload = self.node_payloads.get(report_index)
        if isinstance(payload, dict) and payload.get("analysis_path"):
            analysis = payload["analysis_path"]
        self.add_edge(analysis, report_index, relation="report_input", discovered_by="analysis_path", evidence_pointer=f"{report_index}.analysis_path")
        if isinstance(payload, dict):
            for idx, item in enumerate(payload.get("reports", []) or []):
                if isinstance(item, dict) and item.get("path"):
                    view_path = item["path"]
                    self.add_node(view_path, force_report_view=True)
                    self.add_edge(
                        report_index,
                        view_path,
                        relation="renders",
                        discovered_by="report_index.reports",
                        evidence_pointer=f"{report_index}.reports[{idx}]",
                        expected_target_sha256=item.get("sha256"),
                    )
        self.process_explicit_sources()

    def build_p11(self) -> None:
        phase_dir = "artifacts/phases/P11_STABILITY_SOAK"
        report = f"{phase_dir}/stability_report.json"
        self.add_node(report, self.schema_by_path.get(report))
        payload = self.node_payloads.get(report)
        metrics = f"{phase_dir}/stability_metrics.jsonl"
        baseline = f"{phase_dir}/stability_baseline_comparison.json"
        if isinstance(payload, dict):
            metrics = payload.get("metrics_timeseries_path") or metrics
            baseline = payload.get("baseline_comparison_path") or baseline
        for source in [
            metrics,
            baseline,
            f"{phase_dir}/valkey_e2e_evidence.json",
            f"{phase_dir}/cleanup_report.json",
            f"{phase_dir}/phase_summary.json",
        ]:
            self.add_edge(source, report, relation="stability_source", discovered_by="deterministic_p11", evidence_pointer=report)
        self.build_stability_soak_rollup()

    def build_stability_soak_rollup(self) -> None:
        rollup = "artifacts/loop_engineering/reports/stability_soak_metrics.json"
        rollup_path = self.root / rollup
        if not rollup_path.exists():
            return
        self.add_node(rollup, self.schema_by_path.get(rollup))
        payload = self.node_payloads.get(rollup)
        if not isinstance(payload, dict):
            return
        for profile_idx, profile in enumerate(payload.get("profiles", []) or []):
            if not isinstance(profile, dict):
                continue
            for source in profile.get("source_artifacts", []) or []:
                if isinstance(source, str):
                    self.add_edge(
                        source,
                        rollup,
                        relation="stability_soak_source",
                        discovered_by=f"profile_{profile.get('node_count')}",
                        evidence_pointer=f"{rollup}.profiles[{profile_idx}]",
                    )

    def build_scale_phase(self, phase_id: str, rungs: list[int]) -> None:
        phase_dir = f"artifacts/phases/{phase_id}"
        report = f"{phase_dir}/scale_ladder_report.json"
        self.add_node(report, self.schema_by_path.get(report))
        common_sources = [f"{phase_dir}/cleanup_report.json", f"{phase_dir}/phase_summary.json"]
        for source in common_sources:
            self.add_edge(source, report, relation="scale_source", discovered_by="manifest_required_artifact", evidence_pointer=report)
        for rung in rungs:
            rung_sources = [
                f"{phase_dir}/resource_preflight_{rung}.json",
                f"{phase_dir}/valkey_e2e_evidence_{rung}.json",
                f"{phase_dir}/scale_rung_{rung}.json",
                f"{phase_dir}/cleanup_report_scale_{rung}.json",
            ]
            for source in rung_sources:
                self.add_edge(source, report, relation="scale_source", discovered_by=f"scale_rung_{rung}", evidence_pointer=report)
            rung_path = f"{phase_dir}/scale_rung_{rung}.json"
            evidence_path = f"{phase_dir}/valkey_e2e_evidence_{rung}.json"
            self.add_edge(evidence_path, rung_path, relation="rung_evidence", discovered_by=f"scale_rung_{rung}", evidence_pointer=rung_path)
            preflight_path = f"{phase_dir}/resource_preflight_{rung}.json"
            self.add_edge(preflight_path, rung_path, relation="rung_preflight", discovered_by=f"scale_rung_{rung}", evidence_pointer=rung_path)

    def build_p13_timing(self) -> None:
        phase_dir = "artifacts/phases/P13_SCALE_LADDER_50_100"
        scale_report = f"{phase_dir}/scale_ladder_report.json"
        for rung in [50, 100]:
            timing = f"{phase_dir}/p13_timing_breakdown_scale_{rung}.json"
            self.add_node(timing)
            self.add_edge(timing, scale_report, relation="timing_source", discovered_by=f"p13_timing_{rung}", evidence_pointer=scale_report)
            timing_payload = self.node_payloads.get(timing)
            setup_timeline_paths: set[str] = set()
            if isinstance(timing_payload, dict):
                for idx, item in enumerate(timing_payload.get("timings", []) or []):
                    details = item.get("details") if isinstance(item, dict) else None
                    if isinstance(details, dict) and details.get("setup_timeline_path"):
                        setup_timeline_paths.add(self.rel_path(details["setup_timeline_path"]))
            default_setup_timeline = f"{phase_dir}/setup_timeline_scale_{rung}.json"
            if not setup_timeline_paths:
                setup_timeline_paths.add(default_setup_timeline)
            for idx, setup_timeline in enumerate(sorted(setup_timeline_paths)):
                self.add_edge(
                    setup_timeline,
                    timing,
                    relation="setup_timeline_source",
                    discovered_by="p13_timing_breakdown.timings.details.setup_timeline_path",
                    evidence_pointer=f"{timing}.timings[*].details.setup_timeline_path[{idx}]",
                )
            for source in [
                f"{phase_dir}/runtime_timing_breakdown_scale_{rung}.json",
                f"{phase_dir}/valkey_e2e_evidence_{rung}.json",
                f"{phase_dir}/cleanup_report_scale_{rung}.json",
                f"{phase_dir}/scale_{rung}_setup.stdout.log",
                f"{phase_dir}/scale_{rung}_setup.stderr.log",
                f"{phase_dir}/scale_{rung}_cleanup.stdout.log",
                f"{phase_dir}/scale_{rung}_cleanup.stderr.log",
            ]:
                self.add_edge(source, timing, relation="timing_source", discovered_by=f"p13_timing_{rung}", evidence_pointer=timing)
        self.process_explicit_sources()

    def build_l08_fault_failover(self) -> None:
        report = "artifacts/loop_engineering/reports/fault_failover_scale.json"
        if not (self.root / report).exists():
            return
        self.add_node(report)
        payload = self.node_payloads.get(report)
        if isinstance(payload, dict):
            for idx, item in enumerate(payload.get("canonical_rungs", []) or []):
                if not isinstance(item, dict):
                    continue
                for source_idx, source in enumerate(item.get("source_artifacts", []) or []):
                    if isinstance(source, dict) and source.get("path"):
                        self.add_edge(
                            source["path"],
                            report,
                            relation="fault_failover_source",
                            discovered_by="fault_failover_scale.rungs.source_artifacts",
                            evidence_pointer=f"{report}.canonical_rungs[{idx}].source_artifacts[{source_idx}]",
                            expected_source_sha256=source.get("sha256"),
                        )
        self.process_explicit_sources()

    def metadata_entry(self, status: str, reason: str | None = None) -> dict[str, str]:
        entry = {"status": status}
        if reason:
            entry["reason"] = reason
        return entry

    def missing_field_entry(self, path_text: str, node: dict[str, Any], field: str) -> dict[str, str]:
        payload = self.node_payloads.get(path_text)
        suffix = Path(path_text).suffix
        artifact_type = payload.get("artifact_type") if isinstance(payload, dict) else None
        if suffix not in JSON_SUFFIXES:
            return self.metadata_entry("SKIPPED_WITH_REASON", "Unstructured non-JSON evidence has no embedded artifact metadata.")
        if artifact_type == "metric_sample" and field in {"producer", "status"}:
            return self.metadata_entry("SKIPPED_WITH_REASON", "metric_sample v1 lines identify source, timestamp, phase_id, and run_id but do not carry producer/status.")
        return self.metadata_entry("MISSING", f"{field} is absent from this source artifact.")

    def schema_metadata_entry(self, path_text: str, node: dict[str, Any]) -> dict[str, str]:
        payload = self.node_payloads.get(path_text)
        if node.get("schema_path") and node.get("schema_valid") is True:
            return self.metadata_entry("VALID")
        if node.get("schema_path") and node.get("schema_valid") is False:
            return self.metadata_entry("INVALID", "Artifact payload does not validate against the inferred schema.")
        reason = self.schema_skip_reason(path_text, payload)
        if reason:
            return self.metadata_entry("SKIPPED_WITH_REASON", reason)
        return self.metadata_entry("MISSING", "No schema could be inferred for this source artifact.")

    def node_metadata_status(self, path_text: str, node: dict[str, Any]) -> dict[str, dict[str, str]]:
        payload = self.node_payloads.get(path_text)
        suffix = Path(path_text).suffix
        artifact_type_present = isinstance(payload, dict) and bool(payload.get("artifact_type"))
        if artifact_type_present:
            artifact_type_status = self.metadata_entry("PRESENT")
        elif suffix not in JSON_SUFFIXES:
            artifact_type_status = self.metadata_entry("SKIPPED_WITH_REASON", "Unstructured non-JSON evidence is typed by file role.")
        else:
            artifact_type_status = self.metadata_entry("MISSING", "artifact_type is absent from this source artifact.")

        statuses = {"artifact_type": artifact_type_status, "schema": self.schema_metadata_entry(path_text, node)}
        for field in ["phase_id", "run_id", "producer", "status"]:
            if node.get(field) is not None:
                statuses[field] = self.metadata_entry("PRESENT")
            else:
                statuses[field] = self.missing_field_entry(path_text, node, field)
        return statuses

    def provenance_source_paths(self) -> set[str]:
        return {
            edge["source_path"]
            for edge in self.edges
            if edge.get("required") and edge.get("relation") in PROVENANCE_SOURCE_RELATIONS
        }

    def evaluate_node_metadata(self) -> None:
        source_paths = self.provenance_source_paths()
        target_prefixes = tuple(f"artifacts/phases/{phase_id}/" for phase_id in TARGET_PHASES)
        for path_text, node in self.nodes.items():
            metadata_status = self.node_metadata_status(path_text, node)
            node["metadata_status"] = metadata_status
            if not node.get("exists") or not node.get("source_of_truth"):
                continue
            is_target_source = path_text in source_paths or path_text.startswith(target_prefixes)
            if not is_target_source:
                continue
            schema_status = metadata_status["schema"]["status"]
            if schema_status == "INVALID":
                self.finding(
                    severity="high",
                    category="invalid_source_schema",
                    blocking=path_text in source_paths,
                    path=path_text,
                    phase_id=node.get("phase_id"),
                    description=f"Required provenance source has invalid schema: {path_text}",
                    evidence=node.get("schema_errors", [])[:5] or [metadata_status["schema"].get("reason", "")],
                )
            for field, entry in metadata_status.items():
                if entry["status"] != "MISSING":
                    continue
                self.finding(
                    severity="medium",
                    category="missing_metadata",
                    blocking=False,
                    path=path_text,
                    phase_id=node.get("phase_id"),
                    description=f"Provenance source metadata is missing: {field}",
                    evidence=[f"field={field}", entry.get("reason", ""), f"source={path_text}"],
                )

    def add_target_coverage(self) -> None:
        self.build_p09()
        self.build_p11()
        self.build_scale_phase("P12_SCALE_LADDER_10_30", [10, 30])
        self.build_scale_phase("P13_SCALE_LADDER_50_100", [50, 100])
        self.build_p13_timing()
        self.build_l08_fault_failover()
        dryrun = "artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json"
        if (self.root / dryrun).exists():
            self.add_node(dryrun, self.schema_by_path.get(dryrun))

    def detect_cycles(self) -> None:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            adjacency[edge["source_path"]].append(edge["target_path"])
        visiting: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = []

        def visit(node: str) -> bool:
            if node in visiting:
                cycle = stack[stack.index(node) :] + [node] if node in stack else stack + [node]
                self.finding(
                    severity="high",
                    category="graph_cycle",
                    blocking=True,
                    path=node,
                    description="Provenance graph contains a cycle",
                    evidence=[" -> ".join(cycle)],
                )
                return True
            if node in visited:
                return False
            visiting.add(node)
            stack.append(node)
            found = False
            for nxt in adjacency.get(node, []):
                found = visit(nxt) or found
            stack.pop()
            visiting.remove(node)
            visited.add(node)
            return found

        for node in sorted(self.nodes):
            visit(node)

    def phase_coverage(self) -> list[dict[str, Any]]:
        coverage: list[dict[str, Any]] = []
        required_by_phase = {
            "P09_ANALYSIS_REPORTING": [
                "artifacts/phases/P09_ANALYSIS_REPORTING/analysis_summary.json",
                "artifacts/phases/P09_ANALYSIS_REPORTING/report_index.json",
                "artifacts/phases/P09_ANALYSIS_REPORTING/report/metrics.csv",
                "artifacts/phases/P09_ANALYSIS_REPORTING/report/missing_metrics.csv",
                "artifacts/phases/P09_ANALYSIS_REPORTING/report/baseline_comparison.csv",
                "artifacts/phases/P09_ANALYSIS_REPORTING/report/metric_chart.svg",
                "artifacts/phases/P09_ANALYSIS_REPORTING/report/report.md",
                "artifacts/phases/P09_ANALYSIS_REPORTING/report/index.html",
            ],
            "P11_STABILITY_SOAK": [
                "artifacts/phases/P11_STABILITY_SOAK/stability_report.json",
                "artifacts/phases/P11_STABILITY_SOAK/stability_metrics.jsonl",
                "artifacts/phases/P11_STABILITY_SOAK/stability_baseline_comparison.json",
                "artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json",
                "artifacts/phases/P11_STABILITY_SOAK/cleanup_report.json",
                "artifacts/phases/P11_STABILITY_SOAK/phase_summary.json",
            ],
            "P12_SCALE_LADDER_10_30": [
                "artifacts/phases/P12_SCALE_LADDER_10_30/scale_ladder_report.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/resource_preflight_10.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/resource_preflight_30.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_10.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/scale_rung_10.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/scale_rung_30.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/phase_summary.json",
            ],
            "P13_SCALE_LADDER_50_100": [
                "artifacts/phases/P13_SCALE_LADDER_50_100/scale_ladder_report.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_50.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_100.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/scale_rung_50.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/scale_rung_100.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_100.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report.json",
                "artifacts/phases/P13_SCALE_LADDER_50_100/phase_summary.json",
            ],
        }
        for phase_id, required_paths in required_by_phase.items():
            covered = [path for path in required_paths if path in self.nodes and self.nodes[path]["exists"]]
            finding_ids: list[str] = []
            missing = sorted(set(required_paths) - set(covered))
            for path in missing:
                finding_ids.append(
                    self.finding(
                        severity="high",
                        category="missing_phase_coverage",
                        blocking=True,
                        phase_id=phase_id,
                        path=path,
                        description=f"Required L02 provenance coverage path is missing: {path}",
                        evidence=[phase_id, path],
                    )
                )
            coverage.append(
                {
                    "phase_id": phase_id,
                    "status": "FAIL" if missing else "PASS",
                    "required_paths": required_paths,
                    "covered_paths": covered,
                    "finding_ids": finding_ids,
                }
            )
        return coverage

    def p14_boundary(self) -> dict[str, Any]:
        phase = next((p for p in self.manifest.get("phases", []) if p.get("id") == P14_ID), {})
        p14_artifacts = list((self.root / "artifacts" / "phases" / P14_ID).glob("*")) if (self.root / "artifacts" / "phases" / P14_ID).exists() else []
        real_nodes = [node for node in self.nodes.values() if node.get("phase_id") == P14_ID and node.get("real_valkey_coverage")]
        status = "SKIPPED_WITH_REASON"
        finding_ids: list[str] = []
        if phase.get("automatic") is not False or real_nodes:
            status = "FAIL"
            finding_ids.append(
                self.finding(
                    severity="high",
                    category="p14_real_evidence_boundary",
                    blocking=True,
                    phase_id=P14_ID,
                    description="P14 must remain optional dry-run and cannot provide default real Valkey evidence",
                    evidence=[f"automatic={phase.get('automatic')}", f"real_nodes={len(real_nodes)}"],
                )
            )
        return {
            "phase_id": P14_ID,
            "automatic": bool(phase.get("automatic", True)),
            "status": status,
            "real_valkey_coverage": False,
            "dry_run_artifact_count": len(p14_artifacts),
            "reason": "P14 is opt-in dry-run only and was not executed by L02.",
            "finding_ids": finding_ids,
        }

    def build(self) -> dict[str, Any]:
        self.register_manifest_artifacts()
        self.add_target_coverage()
        self.process_explicit_sources()
        self.evaluate_node_metadata()
        self.detect_cycles()
        phase_coverage = self.phase_coverage()
        p14_boundary = self.p14_boundary()
        blocking = [finding for finding in self.findings if finding["blocking"]]
        hash_mismatches = [finding for finding in self.findings if "hash_mismatch" in finding["category"]]
        missing_sources = [finding for finding in self.findings if finding["category"] == "missing_source_artifact"]
        missing_metadata = [finding for finding in self.findings if finding["category"] == "missing_metadata"]
        invalid_schemas = [finding for finding in self.findings if finding["category"] == "invalid_source_schema"]
        automatic_phase_ids = [
            phase["id"] for phase in self.manifest.get("phases", []) if phase.get("automatic", True) and phase.get("id") != P14_ID
        ]
        optional_phase_ids = [phase["id"] for phase in self.manifest.get("phases", []) if not phase.get("automatic", True)]
        nodes = [self.nodes[path] for path in sorted(self.nodes)]
        return {
            "schema_version": "v1",
            "artifact_type": "provenance_graph",
            "created_at": utc_now(),
            "producer": {"name": "scripts/build_provenance_graph.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "root_commit_sha": git_head(self.root),
            "manifest_sha256": self.manifest_sha256,
            "scope": {
                "target_phase_ids": TARGET_PHASES,
                "automatic_phase_ids": automatic_phase_ids,
                "optional_phase_ids": optional_phase_ids,
            },
            "summary": {
                "node_count": len(nodes),
                "edge_count": len(self.edges),
                "source_of_truth_node_count": sum(1 for node in nodes if node["source_of_truth"]),
                "report_view_node_count": sum(1 for node in nodes if not node["source_of_truth"]),
                "blocking_findings_count": len(blocking),
                "missing_source_count": len(missing_sources),
                "hash_mismatch_count": len(hash_mismatches),
                "missing_metadata_count": len(missing_metadata),
                "invalid_source_schema_count": len(invalid_schemas),
            },
            "report_view_policy": {
                "source_of_truth": False,
                "suffixes": sorted(REPORT_VIEW_SUFFIXES),
            },
            "p14_boundary": p14_boundary,
            "phase_coverage": phase_coverage,
            "nodes": nodes,
            "edges": self.edges,
            "findings": self.findings,
        }


def build_graph(root: Path) -> dict[str, Any]:
    return ProvenanceGraph(root).build()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build committed artifact provenance graph")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    report = build_graph(root)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"{report['status']} provenance_graph {rel(root, out_path)}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
