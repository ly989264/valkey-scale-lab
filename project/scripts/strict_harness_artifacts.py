#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import STRICT_200_EXCEPTIONS, STRICT_STAGE_IDS, load_json, phase_dir, phase_map, rel  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    if args.phase != "P27_STRICT_MATRIX_REBASE_HARNESS":
        print("strict_harness_artifacts is only for P27", file=sys.stderr)
        return 2

    created_at = utc_now()
    run_id = "p27-strict-harness-rebase"
    base = phase_dir(args.phase)
    manifest = load_json(ROOT / "codex" / "phase_manifest.json")
    phases = phase_map(manifest)
    strict_phase_entries = [phases[stage_id] for stage_id in STRICT_STAGE_IDS if stage_id in phases]
    strict_docs = [f"docs/codex/goal-loop-strict/stages/{stage_id}.md" for stage_id in STRICT_STAGE_IDS]
    assertion_scripts = [
        "scripts/assert_strict_stage_contract.py",
        "scripts/assert_no_bypass.py",
        "scripts/assert_coverage_registry.py",
        "scripts/assert_exact_scale_real_evidence.py",
        "scripts/assert_quant_completeness.py",
        "scripts/assert_management_matrix_strict.py",
        "scripts/assert_fault_matrix_strict.py",
        "scripts/assert_full_flow_e2e.py",
        "scripts/assert_200_plus_dry_run.py",
        "scripts/assert_analysis_provenance.py",
        "scripts/assert_report_quality.py",
        "scripts/assert_final_strict_closeout.py",
    ]
    artifact_refs = [
        f"artifacts/phases/{args.phase}/phase_summary.json",
        f"artifacts/phases/{args.phase}/quant_summary.json",
        f"artifacts/phases/{args.phase}/harness_extension_report.json",
        f"artifacts/phases/{args.phase}/strict_manifest_report.json",
    ]
    missing_runtime = [
        {
            "field": field,
            "status": "SKIPPED_WITH_REASON",
            "reason": "P27 is harness/scaffolding only and must not claim real Valkey runtime evidence.",
        }
        for field in [
            "valkey_e2e_evidence",
            "management_operation_metrics",
            "fault_failover_metrics",
            "workload_qps_latency_error_impact",
        ]
    ]

    phase_summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": args.phase,
        "run_id": run_id,
        "created_at": created_at,
        "producer": {"name": "scripts/strict_harness_artifacts.py", "version": "v1"},
        "status": "PASS",
        "summary": "Strict P27-P40 harness entries and fail-closed assertions were added without claiming real runtime evidence.",
        "required_artifacts": artifact_refs,
        "missing_metrics": [
            {"metric": item["field"], "status": item["status"], "reason": item["reason"]} for item in missing_runtime
        ],
        "risks": [
            {
                "risk": "Future real stages still need implementation evidence.",
                "mitigation": "P27 assertions fail closed on missing future-stage artifacts.",
            }
        ],
        "real_runtime_claimed": False,
    }
    quant_summary = {
        "schema_version": "v1",
        "artifact_type": "quant_summary",
        "phase_id": args.phase,
        "run_id": run_id,
        "created_at": created_at,
        "producer": {"name": "scripts/strict_harness_artifacts.py", "version": "v1"},
        "status": "SKIPPED_WITH_REASON",
        "summary": "Runtime quantification is skipped because P27 is a harness-only rebase.",
        "artifact_refs": artifact_refs,
        "missing_data": missing_runtime,
        "runtime_claims": {
            "real_valkey_claimed": False,
            "management_runtime_claimed": False,
            "fault_runtime_claimed": False,
            "full_flow_runtime_claimed": False,
        },
    }
    harness_report = {
        "schema_version": "v1",
        "artifact_type": "harness_extension_report",
        "phase_id": args.phase,
        "run_id": run_id,
        "created_at": created_at,
        "status": "PASS",
        "no_real_runtime_claimed": True,
        "lock_update_reason": "P27 strengthened locked harness controls by adding strict P27-P40 discovery, reviews, assertions, schemas, and manifest entries.",
        "harness_changes": [
            "automatic_stop_after updated to P40_STRICT_FINAL_AUDIT_CLOSEOUT",
            "P27-P40 strict stages appended in order",
            "strict review path artifacts/goal_loop_strict/<STAGE_ID>/REVIEW.md enforced by postcheck",
            "fail-closed strict assertion scripts added",
        ],
        "assertion_scripts": assertion_scripts,
        "coverage_ids": [
            "strict.harness.manifest_p27_p40_appended",
            "strict.harness.automatic_stop_after_p40",
            "strict.harness.p14_non_automatic_preserved",
            "strict.harness.default_max_nodes_100_preserved",
            "strict.harness.bounded_200_exceptions_declared",
            "strict.harness.strict_review_required",
            "strict.harness.assertions_fail_closed",
            "strict.harness.p37_dry_run_only_declared",
            "strict.harness.no_real_runtime_claimed_by_p27",
        ],
        "runtime_claims": quant_summary["runtime_claims"],
    }
    manifest_report = {
        "schema_version": "v1",
        "artifact_type": "strict_manifest_report",
        "phase_id": args.phase,
        "run_id": run_id,
        "created_at": created_at,
        "status": "PASS",
        "manifest_path": "codex/phase_manifest.json",
        "manifest_sha256": sha256_file(ROOT / "codex" / "phase_manifest.json"),
        "automatic_stop_after": manifest.get("automatic_stop_after"),
        "default_max_nodes": manifest.get("default_max_nodes"),
        "p14_automatic": phases.get("P14_SCALE_1000_OPTIN_DRYRUN", {}).get("automatic"),
        "strict_stage_order": [phase["id"] for phase in strict_phase_entries],
        "bounded_200_exceptions": sorted(STRICT_200_EXCEPTIONS),
        "p37_dry_run_target_nodes": phases.get("P37_200_PLUS_DRY_RUN_SUPPORT", {}).get("dry_run_target_nodes", []),
        "strict_stage_docs": strict_docs,
    }
    write_json(base / "phase_summary.json", phase_summary)
    write_json(base / "quant_summary.json", quant_summary)
    write_json(base / "harness_extension_report.json", harness_report)
    write_json(base / "strict_manifest_report.json", manifest_report)
    print(f"WROTE P27 strict harness artifacts under {rel(base)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

