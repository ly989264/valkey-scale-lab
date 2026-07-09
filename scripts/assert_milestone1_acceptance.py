#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

M1H = Path(__file__).resolve().parent / "m1h"
sys.path.insert(0, str(M1H))

from build_acceptance_reset import build_acceptance_reset
from common import write_json
from manifest import CAPABILITIES, REQUIRED_CLAIMS, build_manifest

LEGACY_COMPAT_CATEGORIES = [
    "cluster_setup",
    "management_ops",
    "fault_failover",
    "workload_benchmark",
    "system_metrics",
    "analysis",
    "visual_report_zh",
    "cleanup",
    "cross_scenario_coverage",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and assert the milestone1 hardening acceptance report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--allow-blocked", action="store_true", help="Exit 0 when exact-scale claims are blocked with reasons.")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    if not manifest_path.exists():
        manifest = build_manifest(root)
        write_json(manifest_path, manifest)

    report = build_report(root, manifest_path)
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if report["milestone1_status"] == "PASS":
        print(f"PASS: milestone1 acceptance report written to {out}")
        return 0
    if report["milestone1_status"] == "BLOCKED_WITH_REASON" and args.allow_blocked:
        print(f"BLOCKED_WITH_REASON: milestone1 acceptance report written to {out}")
        return 0
    print(f"{report['milestone1_status']}: milestone1 acceptance report written to {out}", file=sys.stderr)
    return 1


def build_report(root: Path, manifest_path: Path) -> dict[str, Any]:
    report, violations = build_acceptance_reset(
        root,
        manifest_path,
        stage_id="M1-HARDENING",
        historical_acceptance_report=None,
        artifact_type="milestone1_acceptance_report",
    )
    report["category_results"] = _category_results(report)
    report["heavy_real_rungs"] = _heavy_rungs(report)
    report["source_artifacts"] = _source_artifacts(report)
    for category in LEGACY_COMPAT_CATEGORIES:
        report[category] = report["category_results"][category]["status"]
    if violations:
        report["hardening_loop_status"] = "FAIL"
        report["violations"] = violations
    return report


def _category_results(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims = [claim for claim in report.get("claims", []) if isinstance(claim, dict)]
    by_capability: dict[str, list[dict[str, Any]]] = {capability: [] for capability in CAPABILITIES}
    for claim in claims:
        by_capability.setdefault(str(claim.get("capability")), []).append(claim)

    mapping = {
        "cluster_setup": ["setup_telemetry"],
        "management_ops": ["management_matrix", "command_audit"],
        "fault_failover": ["fault_timeline"],
        "workload_benchmark": ["workload_benchmark"],
        "system_metrics": ["system_metrics"],
        "analysis": ["setup_telemetry", "command_audit", "management_matrix", "workload_benchmark", "fault_timeline", "system_metrics"],
        "visual_report_zh": ["report"],
        "cleanup": ["cleanup"],
        "cross_scenario_coverage": [capability for capability, _scale in REQUIRED_CLAIMS],
    }
    results: dict[str, dict[str, Any]] = {}
    for category, capabilities in mapping.items():
        category_claims = [claim for capability in capabilities for claim in by_capability.get(capability, [])]
        statuses = {claim.get("acceptance_status") for claim in category_claims}
        if "FAIL" in statuses:
            status = "FAIL"
        elif "BLOCKED_WITH_REASON" in statuses or not category_claims:
            status = "BLOCKED_WITH_REASON"
        else:
            status = "PASS"
        results[category] = {
            "status": status,
            "reason": _category_reason(category, status),
            "claim_count": len(category_claims),
            "blocked_claim_count": sum(1 for claim in category_claims if claim.get("acceptance_status") == "BLOCKED_WITH_REASON"),
        }
    return results


def _category_reason(category: str, status: str) -> str:
    if status == "PASS":
        return f"{category} has accepted exact-scale M1-format claims."
    if status == "FAIL":
        return f"{category} contains a non-promotable or malformed PASS claim."
    return f"{category} is blocked until exact-scale M1-format claims are accepted by hardening gates."


def _heavy_rungs(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for claim in report.get("claims", []):
        if not isinstance(claim, dict):
            continue
        rows.append(
            {
                "scale": claim.get("scale", "MISSING"),
                "category": claim.get("capability", "MISSING"),
                "status": claim.get("acceptance_status", "BLOCKED_WITH_REASON"),
                "reason": claim.get("reason", "Missing exact-scale M1-format acceptance reason."),
                "evidence_kind": claim.get("evidence_kind", "MISSING"),
                "nodes_observed": claim.get("semantic_checks", {}).get("nodes_observed", "MISSING") if isinstance(claim.get("semantic_checks"), dict) else "MISSING",
            }
        )
    return rows


def _source_artifacts(report: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for claim in report.get("claims", []):
        if not isinstance(claim, dict):
            continue
        for source in claim.get("source_artifacts", []):
            if not isinstance(source, str) or source in seen:
                continue
            seen.add(source)
            sources.append({"path": source, "status": "NON_PROMOTED"})
    return sources


if __name__ == "__main__":
    raise SystemExit(main())
