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


WINDOWS = ["baseline", "steady", "fault", "recovery", "post_recovery"]
REQUIRED_NODE_COUNTS = [6, 30, 50, 100]
SCALE_PLANNING_ID = "scale_planning"
EXPLICIT_MISSING_STATUSES = {"MISSING", "SKIPPED_WITH_REASON"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                row = json.loads(line)
                row["_line"] = lineno
                rows.append(row)
    return rows


def explicit_missing_reason(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("status") not in EXPLICIT_MISSING_STATUSES:
        return ""
    reason = value.get("reason")
    return reason if isinstance(reason, str) and reason.strip() else ""


def measured_or_explicit_missing(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) or bool(explicit_missing_reason(value))


def metric_record_value(value: Any) -> tuple[Any, str, str]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value, "MEASURED", ""
    reason = explicit_missing_reason(value)
    if reason:
        return None, str(value.get("status")), reason
    return None, "MISSING", "Metric missing without an explicit source reason."


class StabilitySoakAuditor:
    def __init__(self, root: Path, required_node_counts: list[int]) -> None:
        self.root = root
        self.required_node_counts = required_node_counts
        self.findings: list[dict[str, Any]] = []
        self.finding_seq = 0
        self.sample_schema = load_json(root / "schemas/artifact/stability_timeseries_sample.schema.json")
        self.report_schema = load_json(root / "schemas/artifact/stability_report.schema.json")
        self.evidence_schema = load_json(root / "schemas/artifact/valkey_e2e_evidence.schema.json")

    def finding(self, *, severity: str, category: str, blocking: bool, description: str, evidence: list[str]) -> None:
        self.finding_seq += 1
        self.findings.append(
            {
                "id": f"SS-{self.finding_seq:04d}",
                "severity": severity,
                "category": category,
                "blocking": blocking,
                "description": description,
                "evidence": evidence,
            }
        )

    def source_record(self, path_text: str) -> dict[str, Any]:
        path = self.root / path_text
        return {
            "path": path_text,
            "exists": path.exists(),
            "sha256": sha256_file(path) if path.exists() else "MISSING",
        }

    def audit_small_real_profile(self) -> dict[str, Any]:
        finding_start = len(self.findings)
        capture_dir = self.root / "artifacts/captures/stability"
        report_path = capture_dir / "stability_report.json"
        evidence_path = capture_dir / "valkey_e2e_evidence.json"
        cleanup_path = capture_dir / "cleanup_report_stability.json"
        baseline_path = capture_dir / "stability_baseline_comparison.json"
        source_artifacts = [
            rel(self.root, report_path),
            rel(self.root, capture_dir / "stability_metrics.jsonl"),
            rel(self.root, baseline_path),
            rel(self.root, evidence_path),
            rel(self.root, cleanup_path),
        ]
        report = load_json(report_path)
        evidence = load_json(evidence_path)
        cleanup = load_json(cleanup_path)
        evidence_errors = validate(evidence, self.evidence_schema)
        if evidence_errors:
            self.finding(
                severity="high",
                category="real_evidence_schema",
                blocking=True,
                description="Small-real stability evidence does not satisfy the Valkey E2E evidence schema.",
                evidence=evidence_errors[:5],
            )
        schema_errors = validate(report, self.report_schema)
        if schema_errors:
            self.finding(
                severity="high",
                category="stability_report_schema",
                blocking=True,
                description="STABILITY report does not satisfy the canonical stability schema.",
                evidence=schema_errors[:5],
            )
        metrics_path = self.root / str(report.get("metrics_timeseries_path", ""))
        rows = read_jsonl(metrics_path) if metrics_path.exists() else []
        if not rows:
            self.finding(
                severity="high",
                category="empty_timeseries",
                blocking=True,
                description="Measured small-real stability profile has no JSONL time series rows.",
                evidence=[rel(self.root, metrics_path)],
            )
        timestamps = [str(row.get("timestamp")) for row in rows]
        if timestamps != sorted(timestamps):
            self.finding(
                severity="high",
                category="non_monotonic_timeseries",
                blocking=True,
                description="Stability JSONL timestamps are not monotonic.",
                evidence=[rel(self.root, metrics_path)],
            )
        windows_seen = {row.get("window") for row in rows}
        missing_windows = [window for window in WINDOWS if window not in windows_seen]
        if missing_windows:
            self.finding(
                severity="high",
                category="missing_timeseries_windows",
                blocking=True,
                description="Stability JSONL is missing required lifecycle windows.",
                evidence=missing_windows,
            )
        for row in rows:
            errors = validate({k: v for k, v in row.items() if k != "_line"}, self.sample_schema)
            if errors:
                self.finding(
                    severity="high",
                    category="timeseries_schema",
                    blocking=True,
                    description="Stability JSONL row does not satisfy the canonical sample schema.",
                    evidence=[f"{rel(self.root, metrics_path)}:{row.get('_line')}: {errors[0]}"],
                )
                break
        if evidence.get("producer", {}).get("name") != "scripts/valkey_e2e_gate.py":
            self.finding(
                severity="high",
                category="real_evidence_producer",
                blocking=True,
                description="Small-real stability evidence was not produced by the real Valkey wrapper.",
                evidence=[rel(self.root, evidence_path)],
            )
        versions = evidence.get("valkey_versions", [])
        invalid_versions = [str(version) for version in versions if not str(version).startswith("9.1.")]
        if evidence.get("status") != "PASS" or evidence.get("probe_result") != "PASS":
            self.finding(
                severity="high",
                category="real_evidence_status",
                blocking=True,
                description="Small-real stability evidence status/probe_result is not PASS.",
                evidence=[rel(self.root, evidence_path)],
            )
        if evidence.get("cluster_state_observed") != "ok":
            self.finding(
                severity="high",
                category="real_evidence_cluster_state",
                blocking=True,
                description="Small-real stability evidence did not observe cluster_state ok.",
                evidence=[str(evidence.get("cluster_state_observed"))],
            )
        if not versions or invalid_versions:
            self.finding(
                severity="high",
                category="real_evidence_valkey_version",
                blocking=True,
                description="Small-real stability evidence does not prove Valkey 9.1.x versions.",
                evidence=invalid_versions or ["MISSING"],
            )
        if evidence.get("real_valkey") is not True or evidence.get("data_path_result") != "PASS":
            self.finding(
                severity="high",
                category="real_evidence_invalid",
                blocking=True,
                description="Small-real stability evidence lacks real Valkey data-path proof.",
                evidence=[rel(self.root, evidence_path)],
            )
        if int(evidence.get("nodes_observed", 0)) < 6:
            self.finding(
                severity="high",
                category="node_count_mismatch",
                blocking=True,
                description="Small-real stability evidence observed too few nodes.",
                evidence=[str(evidence.get("nodes_observed"))],
            )
        if cleanup.get("status") != "PASS" or cleanup.get("resources_remaining"):
            self.finding(
                severity="high",
                category="cleanup_invalid",
                blocking=True,
                description="Small-real stability cleanup did not pass cleanly.",
                evidence=[rel(self.root, cleanup_path)],
            )
        windows = report.get("summary", {}).get("windows", {})
        for name in WINDOWS:
            window = windows.get(name, {})
            workload = window.get("workload", {})
            for metric_name in ["attempted_operations", "completed_operations", "error_count"]:
                if not measured_or_explicit_missing(workload.get(metric_name)):
                    self.finding(
                        severity="high",
                        category="missing_window_metric",
                        blocking=True,
                        description="Measured stability window metric is absent without explicit MISSING/SKIPPED_WITH_REASON semantics.",
                        evidence=[f"$.summary.windows.{name}.workload.{metric_name}"],
                    )
            latency = window.get("workload", {}).get("latency_ms", {})
            p50 = latency.get("p50")
            p95 = latency.get("p95")
            p99 = latency.get("p99")
            for percentile, value in [("p50", p50), ("p95", p95), ("p99", p99)]:
                if not measured_or_explicit_missing(value):
                    self.finding(
                        severity="high",
                        category="missing_window_metric",
                        blocking=True,
                        description="Measured stability window latency percentile is absent without explicit MISSING/SKIPPED_WITH_REASON semantics.",
                        evidence=[f"$.summary.windows.{name}.workload.latency_ms.{percentile}"],
                    )
            if all(isinstance(value, (int, float)) for value in [p50, p95, p99]) and not (p50 <= p95 <= p99):
                self.finding(
                    severity="high",
                    category="latency_percentile_order",
                    blocking=True,
                    description="Window latency percentiles are not ordered p50 <= p95 <= p99.",
                    evidence=[name],
                )
        if report.get("soak_profile", {}).get("bounded") is not True or report.get("soak_profile", {}).get("long_run_stability_claim") is not False:
            self.finding(
                severity="high",
                category="bounded_claim_invalid",
                blocking=True,
                description="Small-real automatic soak must be bounded and must not claim long-run stability.",
                evidence=[rel(self.root, report_path)],
            )
        profile_blocking = any(finding["blocking"] for finding in self.findings[finding_start:])
        real_coverage = not profile_blocking and evidence.get("real_valkey") is True
        return {
            "schema_version": "v1",
            "artifact_type": "stability_soak_profile",
            "capability_id": "stability",
            "run_id": str(report.get("run_id")),
            "created_at": utc_now(),
            "producer": {"name": "scripts/audit_stability_soak_metrics.py", "version": "v1"},
            "status": "PASS" if not profile_blocking else "FAIL",
            "node_count": int(report.get("summary", {}).get("nodes_observed", 0)),
            "evidence_layer": "small-real",
            "evidence_class": "real_valkey",
            "real_valkey_coverage": real_coverage,
            "resource_aware": True,
            "bounded": report.get("soak_profile", {}).get("bounded") is True,
            "long_run_stability_claim": False,
            "metrics_timeseries_path": rel(self.root, metrics_path),
            "baseline_comparison_path": rel(self.root, baseline_path),
            "windows": windows,
            "metric_records": self.metric_records_for_measured_profile(report, "small-real", rel(self.root, report_path)),
            "source_artifacts": source_artifacts,
            "source_hashes": [self.source_record(path) for path in source_artifacts],
        }

    def metric_records_for_measured_profile(self, report: dict[str, Any], layer: str, source: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = [
            {
                "name": "duration_seconds",
                "surface": "stability",
                "unit": "seconds",
                "value": report.get("duration_seconds"),
                "status": "MEASURED",
                "source_artifact": source,
                "source_pointer": "$.duration_seconds",
                "evidence_layer": layer,
            },
            {
                "name": "nodes_observed",
                "surface": "stability",
                "unit": "nodes",
                "value": report.get("summary", {}).get("nodes_observed"),
                "status": "MEASURED",
                "source_artifact": source,
                "source_pointer": "$.summary.nodes_observed",
                "evidence_layer": layer,
            },
            {
                "name": "restart_delta_total",
                "surface": "stability",
                "unit": "count",
                "value": report.get("summary", {}).get("restarts", {}).get("total_restart_delta"),
                "status": "MEASURED",
                "source_artifact": source,
                "source_pointer": "$.summary.restarts.total_restart_delta",
                "evidence_layer": layer,
            },
        ]
        for window, summary in sorted(report.get("summary", {}).get("windows", {}).items()):
            latency = summary.get("workload", {}).get("latency_ms", {})
            for percentile in ["p50", "p95", "p99"]:
                value, status, reason = metric_record_value(latency.get(percentile))
                records.append(
                    {
                        "name": f"window.{window}.latency_ms.{percentile}",
                        "surface": "stability",
                        "unit": "milliseconds",
                        "value": value,
                        "status": status,
                        "reason": reason,
                        "source_artifact": source,
                        "source_pointer": f"$.summary.windows.{window}.workload.latency_ms.{percentile}",
                        "evidence_layer": layer,
                    }
                )
            error_count_value, error_count_status, error_count_reason = metric_record_value(summary.get("workload", {}).get("error_count"))
            records.append(
                {
                    "name": f"window.{window}.error_count",
                    "surface": "stability",
                    "unit": "count",
                    "value": error_count_value,
                    "status": error_count_status,
                    "reason": error_count_reason,
                    "source_artifact": source,
                    "source_pointer": f"$.summary.windows.{window}.workload.error_count",
                    "evidence_layer": layer,
                }
            )
        for idx, comparison in enumerate(report.get("summary", {}).get("baseline", {}).get("comparisons", [])):
            status = str(comparison.get("status") or "MISSING")
            records.append(
                {
                    "name": f"baseline.{comparison.get('metric')}",
                    "surface": "stability",
                    "unit": "count",
                    "value": comparison.get("delta"),
                    "status": status,
                    "reason": "No previous stability baseline artifact exists." if status == "NO_BASELINE_YET" else "",
                    "source_artifact": source,
                    "source_pointer": f"$.summary.baseline.comparisons.{idx}",
                    "evidence_layer": layer,
                }
            )
        return records

    def resource_profile(self, node_count: int) -> dict[str, Any]:
        capability_id = "scale_ladder"
        preflight = self.root / f"artifacts/captures/{capability_id}/resource_preflight_{node_count}.json"
        deferral = self.root / "artifacts/captures/stability/resource_aware_profile_deferral.json"
        if preflight.exists():
            payload = load_json(preflight)
        else:
            payload = {"status": "MISSING", "can_run": False}
            self.finding(
                severity="high",
                category="resource_preflight_missing",
                blocking=True,
                description="Resource-aware stability profile is missing required resource preflight evidence.",
                evidence=[rel(self.root, preflight)],
            )
        can_run = payload.get("can_run") is True and payload.get("status") == "PASS"
        if can_run and deferral.exists():
            deferral_payload = load_json(deferral)
            reason = str(deferral_payload.get("reason") or "Bounded large stability measurement deferred by a reviewed resource-aware profile.")
            skip_category = "MEASUREMENT_DEFERRED_WITH_REVIEWED_REASON"
            extra_sources = [rel(self.root, deferral)]
        elif can_run:
            reason = "Resource preflight passed, but no reviewed measurement deferral artifact exists."
            skip_category = "MISSING_MEASUREMENT_DEFERRAL"
            extra_sources = []
            self.finding(
                severity="high",
                category="resource_preflight_passed_without_measurement",
                blocking=True,
                description="A 30/50/100 stability profile with passing resource preflight needs measured evidence or a reviewed deferral artifact.",
                evidence=[rel(self.root, preflight)],
            )
        else:
            reason = "Resource preflight did not pass for this bounded soak profile."
            skip_category = "RESOURCE_PREFLIGHT_BLOCKED"
            extra_sources = []
        windows = {
            window: {
                "status": "SKIPPED_WITH_REASON",
                "reason": reason,
                "skip_category": skip_category,
                "bounded": True,
                "long_run_stability_claim": False,
            }
            for window in WINDOWS
        }
        return {
            "schema_version": "v1",
            "artifact_type": "stability_soak_profile",
            "capability_id": capability_id,
            "run_id": f"{capability_id}-stability-resource-aware-{node_count}-20260701",
            "created_at": utc_now(),
            "producer": {"name": "scripts/audit_stability_soak_metrics.py", "version": "v1"},
            "status": "SKIPPED_WITH_REASON",
            "reason": reason,
            "skip_category": skip_category,
            "node_count": node_count,
            "evidence_layer": str(node_count),
            "evidence_class": "resource_aware_profile",
            "real_valkey_coverage": False,
            "resource_aware": True,
            "bounded": True,
            "long_run_stability_claim": False,
            "windows": windows,
            "metric_records": [
                {
                    "name": "resource_aware_profile.status",
                    "surface": "stability",
                    "unit": "status",
                    "value": None,
                    "status": "SKIPPED_WITH_REASON",
                    "reason": reason,
                    "source_artifact": rel(self.root, preflight),
                    "source_pointer": "$.can_run",
                    "evidence_layer": str(node_count),
                }
            ],
            "source_artifacts": [rel(self.root, preflight), *extra_sources],
            "source_hashes": [self.source_record(path) for path in [rel(self.root, preflight), *extra_sources]],
        }

    def audit_scale_planning_boundary(self) -> dict[str, Any]:
        scale_planning_dir = self.root / "artifacts/captures" / SCALE_PLANNING_ID
        real_artifacts = []
        if scale_planning_dir.exists():
            for path in scale_planning_dir.glob("*.json"):
                try:
                    payload = load_json(path)
                except Exception:  # noqa: BLE001
                    continue
                if payload.get("real_valkey") is True:
                    real_artifacts.append(rel(self.root, path))
        if real_artifacts:
            self.finding(
                severity="high",
                category="scale_planning_real_stability_evidence",
                blocking=True,
                description="SCALE_PLANNING/1000-node real evidence is forbidden for automatic stability coverage.",
                evidence=real_artifacts,
            )
        return {
            "capability_id": SCALE_PLANNING_ID,
            "status": "SKIPPED_WITH_REASON",
            "real_valkey_coverage": False,
            "dry_run_only": True,
            "reason": "SCALE_PLANNING is opt-in dry-run only and is not executed by automatic stability coverage.",
        }

    def build(self) -> dict[str, Any]:
        profiles = [self.audit_small_real_profile()]
        for node_count in [30, 50, 100]:
            if node_count in self.required_node_counts:
                profiles.append(self.resource_profile(node_count))
        scale_planning_boundary = self.audit_scale_planning_boundary()
        present_counts = {profile["node_count"] for profile in profiles}
        missing_counts = [count for count in self.required_node_counts if count not in present_counts]
        if missing_counts:
            self.finding(
                severity="high",
                category="missing_required_profile",
                blocking=True,
                description="Missing required stability profile node counts.",
                evidence=[str(count) for count in missing_counts],
            )
        missing_metric_count = 0
        for profile in profiles:
            for record in profile.get("metric_records", []):
                if record.get("status") in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"}:
                    missing_metric_count += 1
        blocking = [finding for finding in self.findings if finding["blocking"]]
        return {
            "schema_version": "v1",
            "artifact_type": "stability_soak_metrics",
            "created_at": utc_now(),
            "producer": {"name": "scripts/audit_stability_soak_metrics.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "summary": {
                "required_node_counts": self.required_node_counts,
                "profile_count": len(profiles),
                "measured_profile_count": sum(1 for profile in profiles if profile.get("status") == "PASS"),
                "resource_aware_profile_count": sum(1 for profile in profiles if profile.get("resource_aware") is True),
                "missing_metric_count": missing_metric_count,
                "blocking_findings_count": len(blocking),
                "windows": WINDOWS,
            },
            "profiles": profiles,
            "scale_planning_boundary": scale_planning_boundary,
            "findings": self.findings,
        }


def parse_node_counts(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit canonical stability soak metrics artifacts")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--require-node-counts", default="6,30,50,100")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    auditor = StabilitySoakAuditor(root, parse_node_counts(args.require_node_counts))
    report = auditor.build()
    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{report['status']} stability_soak_metrics profiles={report['summary']['profile_count']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
