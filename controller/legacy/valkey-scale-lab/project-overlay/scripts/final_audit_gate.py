#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402
from historical_schema_compat import allowed_historical_report_commit  # noqa: E402


STAGE_ID = "L10_FULL_CHAIN_FINAL_AUDIT_AND_VISUALIZATION_GATE"
RENDERED_SUFFIXES = {".html", ".csv", ".svg", ".md"}
SOURCE_ARTIFACTS = {
    "audit_report": "artifacts/loop_engineering/reports/audit_report.json",
    "provenance_graph": "artifacts/loop_engineering/reports/provenance_graph.json",
    "metric_catalog": "artifacts/loop_engineering/reports/metric_catalog.json",
    "coverage_matrix": "artifacts/loop_engineering/reports/coverage_matrix.json",
    "p13_p14_scale_audit": "artifacts/loop_engineering/reports/p13_p14_scale_audit.json",
    "small_real_parity_audit": "artifacts/loop_engineering/reports/small_real_parity_audit.json",
    "scale_build_metrics": "artifacts/loop_engineering/reports/scale_build_metrics.json",
    "fault_failover_scale": "artifacts/loop_engineering/reports/fault_failover_scale.json",
    "stability_soak_metrics": "artifacts/loop_engineering/reports/stability_soak_metrics.json",
    "report_index": "artifacts/loop_engineering/reports/report_index.json",
}


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
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def root_commit(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


class FinalAudit:
    def __init__(self, root: Path, out_dir: Path) -> None:
        self.root = root
        self.out_dir = out_dir
        self.findings: list[dict[str, Any]] = []
        self.invariants: list[dict[str, Any]] = []
        self.seq = 0
        self.payloads = {name: load_json(root / path) for name, path in SOURCE_ARTIFACTS.items()}

    def finding(self, category: str, description: str, evidence: list[str], severity: str = "high", blocking: bool = True) -> None:
        self.seq += 1
        self.findings.append(
            {
                "id": f"FA-{self.seq:04d}",
                "severity": severity,
                "category": category,
                "blocking": blocking,
                "description": description,
                "evidence": evidence,
            }
        )

    def invariant(self, name: str, ok: bool, description: str) -> None:
        self.invariants.append({"name": name, "status": "PASS" if ok else "FAIL", "description": description})

    def validate_source_schemas(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        schema_map = {
            "audit_report": "schemas/artifact/audit_report.schema.json",
            "provenance_graph": "schemas/artifact/provenance_graph.schema.json",
            "metric_catalog": "schemas/artifact/metric_catalog.schema.json",
            "coverage_matrix": "schemas/artifact/coverage_matrix.schema.json",
            "p13_p14_scale_audit": "schemas/artifact/p13_p14_scale_audit.schema.json",
            "small_real_parity_audit": "schemas/artifact/small_real_parity_audit.schema.json",
            "scale_build_metrics": "schemas/artifact/scale_build_metrics.schema.json",
            "fault_failover_scale": "schemas/artifact/fault_failover_scale.schema.json",
            "stability_soak_metrics": "schemas/artifact/stability_soak_rollup.schema.json",
            "report_index": "schemas/artifact/loop_report_index.schema.json",
        }
        for name, path_text in SOURCE_ARTIFACTS.items():
            path = self.root / path_text
            payload = self.payloads[name]
            errors = validate(payload, load_json(self.root / schema_map[name]))
            if errors:
                self.finding("source_schema", f"{path_text} failed schema validation.", errors[:5])
            if payload.get("status") != "PASS":
                self.finding("source_status", f"{path_text} status is not PASS.", [str(payload.get("status"))])
            records.append(
                {
                    "path": path_text,
                    "sha256": sha256_file(path),
                    "artifact_type": str(payload.get("artifact_type")),
                    "status": str(payload.get("status")),
                    "source_of_truth": True,
                }
            )
        ok = not any(f["category"] in {"source_schema", "source_status"} for f in self.findings)
        self.invariant("source_artifacts_schema_status", ok, "All final source artifacts are schema-valid PASS JSON artifacts.")
        return records

    def check_coverage(self) -> None:
        coverage = self.payloads["coverage_matrix"]
        layers = set(coverage.get("layers", []))
        surfaces = set(coverage.get("surfaces", []))
        entries = coverage.get("entries", [])
        ok_shape = len(entries) == 60 and len(layers) == 6 and len(surfaces) == 10
        if not ok_shape:
            self.finding("coverage_shape", "Coverage matrix does not contain the required 60 layer/surface cells.", [str(len(entries))])
        dry_bad = [
            f"{entry.get('layer')}:{entry.get('surface')}"
            for entry in entries
            if entry.get("layer") == "1000-dry-run" and (entry.get("dry_run_only") is not True or entry.get("real_valkey_coverage") is not False)
        ]
        if dry_bad:
            self.finding("dry_run_counted_as_real", "1000-dry-run coverage entries must be dry-run only and not real coverage.", dry_bad)
        self.invariant("coverage_matrix_layers_surfaces", ok_shape and not dry_bad, "Coverage has fake/small-real/30/50/100/1000-dry-run layers across all required surfaces.")

    def check_p14(self) -> dict[str, Any]:
        p13 = self.payloads["p13_p14_scale_audit"]
        p14 = p13.get("p14_boundary", {})
        ok = p14.get("dry_run_only") is True and p14.get("real_valkey_coverage") is False and int(p14.get("real_evidence_count", 0)) == 0
        if not ok:
            self.finding("p14_boundary", "P14 boundary is not dry-run-only with zero real evidence.", [json.dumps(p14, sort_keys=True)])
        self.invariant("p14_not_real_coverage", ok, "P14 remains opt-in dry-run/resource/planner only.")
        return p14

    def check_missing_impacts(self) -> list[dict[str, Any]]:
        rows = []
        for metric in self.payloads["metric_catalog"].get("metrics", []):
            status = metric.get("value_status")
            if status not in {"MISSING", "SKIPPED_WITH_REASON", "NO_BASELINE_YET"}:
                continue
            semantics = metric.get("missing_semantics", {}) if isinstance(metric.get("missing_semantics"), dict) else {}
            reason = str(semantics.get("reason") or "")
            impact = str(metric.get("impact") or semantics.get("impact") or "")
            record = {
                "metric": str(metric.get("name")),
                "status": str(status),
                "reason": reason,
                "impact": impact,
                "source_artifact": str(metric.get("source_artifact")),
                "source_pointer": str(metric.get("source_pointer")),
                "evidence_layer": str(metric.get("evidence_layer")),
                "dry_run_only": metric.get("dry_run_only") is True,
            }
            rows.append(record)
            if not reason or not impact:
                self.finding("missing_metric_impact", "Missing/skipped/no-baseline metric lacks reason or impact.", [record["metric"]])
        self.invariant("missing_metric_reason_impact", not any(f["category"] == "missing_metric_impact" for f in self.findings), "Every missing-like metric has reason and impact.")
        return rows

    def check_reports(self) -> list[dict[str, Any]]:
        report_index = self.payloads["report_index"]
        records = []
        for report in report_index.get("reports", []):
            path_text = str(report.get("path"))
            if report.get("source_of_truth") is not False:
                self.finding("report_source_truth", "Rendered report is incorrectly marked source_of_truth.", [path_text])
            if not report.get("source_artifacts"):
                self.finding("report_sources", "Rendered report lacks source artifact links.", [path_text])
            path = self.root / path_text
            if not path.exists():
                self.finding("report_missing", "Rendered report path is missing.", [path_text])
                continue
            copied = self.out_dir / Path(path_text).name
            if path.resolve() != copied.resolve():
                shutil.copy2(path, copied)
            records.append(
                {
                    "path": rel(self.root, path),
                    "sha256": sha256_file(path),
                    "role": str(report.get("role")),
                    "source_of_truth": False,
                    "source_artifacts": list(report.get("source_artifacts", [])),
                }
            )
        index_html = self.root / "artifacts/loop_engineering/reports/index.html"
        html = index_html.read_text(encoding="utf-8") if index_html.exists() else ""
        commit = self.payloads["provenance_graph"].get("root_commit_sha")
        if commit and str(commit) not in html and not allowed_historical_report_commit(self.root, str(commit), html):
            self.finding("report_commit_sha", "Final HTML report does not expose root commit SHA.", [str(commit), rel(self.root, index_html)])
        self.invariant("report_views_are_views", not any(f["category"].startswith("report_") for f in self.findings), "Rendered reports are traceable views and expose commit/source context.")
        return records

    def write_missing_csv(self, rows: list[dict[str, Any]]) -> None:
        with (self.out_dir / "missing_metrics.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["metric", "status", "reason", "impact", "source_artifact", "source_pointer", "evidence_layer", "dry_run_only"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def write_index_html(self, report: dict[str, Any]) -> None:
        source_rows = "\n".join(
            f"<tr><td><code>{r['path']}</code></td><td><code>{r['sha256'][:12]}</code></td><td>{r['status']}</td></tr>"
            for r in report["source_artifacts"]
        )
        doc = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Valkey Scale Lab Final Audit</title></head>
<body>
<h1>Valkey Scale Lab Final Audit</h1>
<p>Status: <code>{report['status']}</code></p>
<p>Root commit SHA: <code>{report['root_commit_sha']}</code></p>
<p>P14: <code>{report['p14_boundary'].get('status')}</code>, dry-run only, real Valkey coverage false.</p>
<ul>
<li><a href="coverage_matrix.csv">coverage_matrix.csv</a></li>
<li><a href="missing_metrics.csv">missing_metrics.csv</a></li>
<li><a href="coverage_heatmap.svg">coverage_heatmap.svg</a></li>
<li><a href="scale_ladder.svg">scale_ladder.svg</a></li>
<li><a href="p13_timing_waterfall.svg">p13_timing_waterfall.svg</a></li>
</ul>
<h2>Source Artifacts</h2>
<table><thead><tr><th>Path</th><th>SHA256</th><th>Status</th></tr></thead><tbody>{source_rows}</tbody></table>
</body></html>
"""
        (self.out_dir / "index.html").write_text(doc, encoding="utf-8")

    def build(self) -> dict[str, Any]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        source_records = self.validate_source_schemas()
        self.check_coverage()
        p14 = self.check_p14()
        missing_impacts = self.check_missing_impacts()
        generated_reports = self.check_reports()
        self.write_missing_csv(missing_impacts)
        blocking = [finding for finding in self.findings if finding["blocking"]]
        report = {
            "schema_version": "v1",
            "artifact_type": "final_audit_report",
            "stage_id": STAGE_ID,
            "root_commit_sha": root_commit(self.root),
            "created_at": utc_now(),
            "producer": {"name": "scripts/final_audit_gate.py", "version": "v1"},
            "status": "PASS" if not blocking else "FAIL",
            "summary": {
                "source_artifact_count": len(source_records),
                "generated_report_count": len(generated_reports),
                "invariant_count": len(self.invariants),
                "missing_metric_impact_count": len(missing_impacts),
                "blocking_findings_count": len(blocking),
            },
            "source_artifacts": source_records,
            "generated_reports": generated_reports,
            "invariant_results": self.invariants,
            "missing_metric_impacts": missing_impacts,
            "p14_boundary": p14,
            "findings": self.findings,
        }
        self.write_index_html(report)
        report["generated_reports"].append(
            {
                "path": rel(self.root, self.out_dir / "index.html"),
                "sha256": sha256_file(self.out_dir / "index.html"),
                "role": "html_report",
                "source_of_truth": False,
                "source_artifacts": [record["path"] for record in source_records],
            }
        )
        report["summary"]["generated_report_count"] = len(report["generated_reports"])
        (self.out_dir / "final_audit_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run L10 full-chain final audit gate")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    report = FinalAudit(root, out_dir).build()
    print(f"{report['status']} final_audit sources={report['summary']['source_artifact_count']} findings={report['summary']['blocking_findings_count']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
