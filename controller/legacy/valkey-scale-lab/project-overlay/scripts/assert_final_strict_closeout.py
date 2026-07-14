#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import STRICT_STAGE_IDS, load_json, phase_dir, print_errors, rel, require_json, strict_handoff_dir  # noqa: E402

P40 = "P40_STRICT_FINAL_AUDIT_CLOSEOUT"
REQUIRED_P40_OUTPUTS = [
    "phase_summary.json",
    "final_strict_audit_report.json",
    "final_coverage_verdict.json",
    "final_artifact_manifest.json",
    "final_no_bypass_report.json",
    "final_report_quality_verdict.json",
    "analysis_provenance.json",
    "quant_summary.json",
    "FINAL_STRICT_SUMMARY.md",
]


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_status(obj: dict[str, Any] | None, path: Path, errors: list[str]) -> None:
    if obj and obj.get("status") != "PASS":
        errors.append(f"{rel(path)}: status must be PASS")


def validate_artifact_ref(ref: Any, errors: list[str], label: str) -> None:
    if not isinstance(ref, dict):
        errors.append(f"{label}: artifact ref must be an object")
        return
    path_text = ref.get("path")
    if not isinstance(path_text, str) or not path_text:
        errors.append(f"{label}: artifact ref missing path")
        return
    path = ROOT / path_text
    if not path.exists():
        errors.append(f"{label}: artifact missing: {path_text}")
        return
    if path.is_file() and path.stat().st_size <= 0:
        errors.append(f"{label}: artifact is empty: {path_text}")
    if ref.get("sha256_status") == "SKIPPED_WITH_REASON":
        if not ref.get("reason"):
            errors.append(f"{label}: skipped sha256 requires reason")
        return
    expected = ref.get("sha256")
    if not isinstance(expected, str) or not expected:
        errors.append(f"{label}: artifact ref requires sha256: {path_text}")
        return
    if sha256_file(path) != expected:
        errors.append(f"{label}: sha256 mismatch: {path_text}")


def validate_prior_stage(stage_id: str, completed: set[str], errors: list[str]) -> None:
    if stage_id not in completed:
        errors.append(f"{stage_id}: not marked complete")
    gate_path = ROOT / "artifacts" / "gates" / stage_id / "gate_result.json"
    gate = require_json(gate_path, errors, "gate result")
    if gate:
        if gate.get("status") != "PASS":
            errors.append(f"{rel(gate_path)}: status must be PASS")
        if gate.get("runner") != "scripts/codex_gate.py":
            errors.append(f"{rel(gate_path)}: runner must be scripts/codex_gate.py")
        records = gate.get("gates")
        if not isinstance(records, list) or not records:
            errors.append(f"{rel(gate_path)}: gates must be non-empty")
        else:
            for record in records:
                if not isinstance(record, dict) or record.get("status") != "PASS" or record.get("exit_code") != 0:
                    errors.append(f"{rel(gate_path)}: all gate records must be PASS exit_code=0")
                    break
    review = strict_handoff_dir(stage_id) / "REVIEW.md"
    if not review.exists() or "Decision: PASS" not in review.read_text(encoding="utf-8", errors="replace"):
        errors.append(f"{stage_id}: strict review Decision: PASS missing")
    completion = strict_handoff_dir(stage_id) / "COMPLETION.md"
    if not completion.exists():
        errors.append(f"{stage_id}: completion record missing")
    else:
        text = completion.read_text(encoding="utf-8", errors="replace")
        lowered = text.lower()
        if "commit" not in lowered or ("push" not in lowered and "pushed" not in lowered):
            errors.append(f"{stage_id}: completion record must include commit and pushed-branch evidence")
    audit_path = ROOT / "audit" / stage_id / "audit_decision.json"
    audit = require_json(audit_path, errors, "audit decision")
    if audit and (audit.get("decision") != "PASS" or audit.get("fresh_context") is not True):
        errors.append(f"{rel(audit_path)}: decision must be PASS and fresh_context=true")


def validate_coverage_registry(errors: list[str]) -> dict[str, int]:
    registry_path = ROOT / "artifacts" / "coverage" / "strict_coverage_registry.json"
    registry = require_json(registry_path, errors, "coverage registry")
    rows = registry.get("rows", []) if registry else []
    if not isinstance(rows, list):
        errors.append("coverage registry rows must be list")
        rows = []
    counts = Counter()
    cleanup_refs: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.append("coverage registry row must be object")
            continue
        cid = str(row.get("coverage_id", "MISSING"))
        scale = int(row.get("scale", 0) or 0)
        mode = row.get("execution_mode")
        category = row.get("category")
        status = row.get("status")
        counts[f"{mode}.{status}"] += 1
        if mode == "real" and category in {"lifecycle", "management", "fault"}:
            if scale not in {50, 100, 200} or row.get("node_count") != scale:
                errors.append(f"{cid}: real row must be exact 50/100/200 scale")
            if status != "PASS":
                errors.append(f"{cid}: final real row must be PASS")
            for key in ["source_artifacts", "validation_artifacts", "metric_refs"]:
                refs = row.get(key)
                if not isinstance(refs, list) or not refs:
                    errors.append(f"{cid}: {key} must be non-empty")
                    refs = []
                for ref in refs:
                    if not isinstance(ref, str) or not (ROOT / ref).exists():
                        errors.append(f"{cid}: missing {key} ref {ref!r}")
            cleanup_ref = row.get("cleanup_ref")
            if isinstance(cleanup_ref, str) and cleanup_ref:
                cleanup_refs.add(cleanup_ref)
            else:
                errors.append(f"{cid}: cleanup_ref required")
            review_ref = row.get("review_ref")
            if not isinstance(review_ref, str) or not (ROOT / review_ref).exists():
                errors.append(f"{cid}: review_ref missing")
        if scale > 200:
            if mode != "dry_run" or status != "DRY_RUN_PASS":
                errors.append(f"{cid}: >200 rows must be DRY_RUN_PASS dry_run")
            validation_refs = row.get("validation_artifacts", [])
            if not isinstance(validation_refs, list) or not validation_refs:
                errors.append(f"{cid}: dry-run validation_artifacts required")
                validation_refs = []
            if not any(isinstance(ref, str) and "no_runtime" in ref for ref in validation_refs):
                errors.append(f"{cid}: dry-run row requires no-runtime proof")
            for ref in validation_refs:
                if not isinstance(ref, str) or not (ROOT / ref).exists():
                    errors.append(f"{cid}: missing dry-run validation ref {ref!r}")
    for ref in sorted(cleanup_refs):
        cleanup = require_json(ROOT / ref, errors, "cleanup report")
        if cleanup and (cleanup.get("status") or cleanup.get("cleanup_status") or cleanup.get("overall_status")) != "PASS":
            errors.append(f"{ref}: cleanup status must be PASS")
    if len(rows) != 145:
        errors.append(f"coverage registry must contain 145 rows, found {len(rows)}")
    if counts["real.PASS"] != 105:
        errors.append(f"coverage registry must contain 105 real PASS rows, found {counts['real.PASS']}")
    if counts["dry_run.DRY_RUN_PASS"] != 40:
        errors.append(f"coverage registry must contain 40 dry-run PASS rows, found {counts['dry_run.DRY_RUN_PASS']}")
    return {"total_rows": len(rows), "real_pass_rows": counts["real.PASS"], "dry_run_pass_rows": counts["dry_run.DRY_RUN_PASS"]}


def validate_manifest_commands(errors: list[str]) -> None:
    manifest = require_json(ROOT / "codex" / "phase_manifest.json", errors, "phase manifest")
    phases = {phase.get("id"): phase for phase in manifest.get("phases", []) if isinstance(phase, dict)} if manifest else {}
    p40 = phases.get(P40, {})
    gates = {gate.get("name"): gate for gate in p40.get("gates", []) if isinstance(gate, dict)}
    if "--require-dry-run-200-plus" not in str(gates.get("coverage_registry", {}).get("command", "")):
        errors.append("P40 coverage_registry gate must include --require-dry-run-200-plus")
    if "--phase P39_VISUAL_REPORT_QUALITY_GATE" not in str(gates.get("report_quality", {}).get("command", "")):
        errors.append("P40 report_quality gate must use P39-specific report validation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    if args.phase != P40:
        errors.append(f"assert_final_strict_closeout only supports {P40}")
    state_path = ROOT / "codex" / "status" / "phase_state.json"
    state = require_json(state_path, errors, "phase state")
    completed = set(state.get("completed_phases", [])) if state else set()
    for stage_id in STRICT_STAGE_IDS[:-1]:
        validate_prior_stage(stage_id, completed, errors)
    base = phase_dir(args.phase)
    for name in REQUIRED_P40_OUTPUTS:
        path = base / name
        if not path.exists():
            errors.append(f"P40 output missing: {rel(path)}")
        elif path.is_file() and path.stat().st_size <= 0:
            errors.append(f"P40 output empty: {rel(path)}")
    closeout = require_json(base / "final_strict_audit_report.json", errors, "final strict audit report")
    coverage = require_json(base / "final_coverage_verdict.json", errors, "final coverage verdict")
    manifest = require_json(base / "final_artifact_manifest.json", errors, "final artifact manifest")
    no_bypass = require_json(base / "final_no_bypass_report.json", errors, "final no-bypass report")
    report_quality = require_json(base / "final_report_quality_verdict.json", errors, "final report quality verdict")
    provenance = require_json(base / "analysis_provenance.json", errors, "analysis provenance")
    quant = require_json(base / "quant_summary.json", errors, "quant summary")
    phase_summary = require_json(base / "phase_summary.json", errors, "phase summary")
    for path, obj in [
        (base / "final_strict_audit_report.json", closeout),
        (base / "final_coverage_verdict.json", coverage),
        (base / "final_no_bypass_report.json", no_bypass),
        (base / "final_report_quality_verdict.json", report_quality),
        (base / "analysis_provenance.json", provenance),
        (base / "quant_summary.json", quant),
        (base / "phase_summary.json", phase_summary),
    ]:
        require_status(obj, path, errors)
    counts = validate_coverage_registry(errors)
    if coverage:
        observed_counts = coverage.get("observed_counts", {})
        for key, value in counts.items():
            if observed_counts.get(key) != value:
                errors.append(f"final_coverage_verdict observed_counts.{key} must match current coverage registry")
    validate_manifest_commands(errors)
    if closeout:
        if closeout.get("runtime_started") is not False or closeout.get("audit_only") is not True:
            errors.append("final_strict_audit_report must assert audit_only=true and runtime_started=false")
        if closeout.get("invented_values_present") is not False:
            errors.append("final_strict_audit_report must assert invented_values_present=false")
        if closeout.get("blocking_findings") not in ([], None):
            errors.append("final_strict_audit_report must have no blocking_findings")
    if report_quality:
        if report_quality.get("validated_command") != "python3 scripts/assert_report_quality.py --phase P39_VISUAL_REPORT_QUALITY_GATE --report-index artifacts/phases/P39_VISUAL_REPORT_QUALITY_GATE/report_index.json":
            errors.append("final_report_quality_verdict must record the P39-specific report quality command")
    if provenance:
        for key, expected in {"audit_only": True, "analysis_only": True, "runtime_started": False, "invented_values_present": False, "raw_log_sources_present": False}.items():
            if provenance.get(key) is not expected:
                errors.append(f"analysis_provenance must assert {key}={expected}")
    if quant:
        claims = quant.get("runtime_claims", {})
        for key in ["real_valkey_claimed", "management_runtime_claimed", "fault_runtime_claimed"]:
            if claims.get(key) is not False:
                errors.append(f"quant_summary runtime_claims.{key} must be false")
        missing = quant.get("missing_data")
        if not isinstance(missing, list) or not missing:
            errors.append("quant_summary must include audit-only skipped missing_data entries")
    if manifest:
        for collection_name in ["source_artifacts", "p40_outputs"]:
            refs = manifest.get(collection_name)
            if not isinstance(refs, list) or not refs:
                errors.append(f"final_artifact_manifest {collection_name} must be non-empty")
                continue
            for index, ref_obj in enumerate(refs, start=1):
                validate_artifact_ref(ref_obj, errors, f"final_artifact_manifest.{collection_name}[{index}]")
    if errors:
        return print_errors(errors)
    print(f"PASS final strict closeout phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
