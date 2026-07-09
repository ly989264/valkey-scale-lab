#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, violation, write_gate_result

GATE = "assert_stage_exit"
H00_REQUIRED_GATE_RESULTS = [
    "build_evidence_manifest",
    "assert_evidence_taxonomy",
    "assert_no_fixture_fallback",
    "assert_no_legacy_m1_pass",
    "assert_no_simulated_subagents",
]
H01_REQUIRED_GATE_RESULTS = [
    "build_evidence_manifest",
    "build_acceptance_reset",
    "assert_evidence_taxonomy",
    "assert_no_fixture_fallback",
    "assert_no_legacy_m1_pass",
    "assert_no_simulated_subagents",
]
STAGE_REQUIRED_GATE_RESULTS = {
    "H00_BOOTSTRAP_HARD_GATES": H00_REQUIRED_GATE_RESULTS,
    "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET": H01_REQUIRED_GATE_RESULTS,
}
REQUIRED_SCRIPTS = [
    "build_evidence_manifest.py",
    "build_acceptance_reset.py",
    "assert_evidence_taxonomy.py",
    "assert_no_fixture_fallback.py",
    "assert_no_legacy_m1_pass.py",
    "assert_no_simulated_subagents.py",
    "assert_stage_exit.py",
    "assert_setup_core_metrics.py",
    "assert_command_audit_real.py",
    "assert_management_exact_scale.py",
    "assert_workload_benchmark_strength.py",
    "assert_fault_timeline_real.py",
    "assert_system_metrics_real_windows.py",
    "assert_report_input_quality.py",
    "assert_final_milestone1_hardened.py",
]
H01_REQUIRED_ACCEPTANCE_ARTIFACTS = [
    "artifacts/milestone1_acceptance_reset.json",
]
REQUIRED_STAGE_ARTIFACTS = [
    "agents/design.md",
    "agents/worker.md",
    "agents/review.md",
    "handoff/DESIGN_BRIEF.md",
    "handoff/WORKER_SUMMARY.md",
    "handoff/REVIEW.md",
]


def validate_stage_exit(root: Path, stage_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    violations: list[dict[str, Any]] = []
    blocked: list[str] = []
    manifest = root / "runs" / "m1-hardening" / "evidence_manifest.json"
    if not manifest.exists():
        blocked.append("runs/m1-hardening/evidence_manifest.json is missing.")
    for script in REQUIRED_SCRIPTS:
        path = root / "scripts" / "m1h" / script
        if not path.exists():
            violations.append(violation("required_script_missing", "Required H00 gate script is missing.", path=f"scripts/m1h/{script}"))
    gates_root = root / "runs" / "m1-hardening" / stage_id / "artifacts" / "gates"
    required_gates = STAGE_REQUIRED_GATE_RESULTS.get(stage_id, H00_REQUIRED_GATE_RESULTS)
    for gate_name in required_gates:
        path = gates_root / f"{gate_name}.json"
        _validate_gate_result(path, gate_name, stage_id, violations, blocked)
    stage_root = root / "runs" / "m1-hardening" / stage_id
    for rel in REQUIRED_STAGE_ARTIFACTS:
        path = stage_root / rel
        if not path.exists():
            blocked.append(f"runs/m1-hardening/{stage_id}/{rel} is missing.")
    if stage_id == "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET":
        for rel in H01_REQUIRED_ACCEPTANCE_ARTIFACTS:
            path = stage_root / rel
            _validate_h01_acceptance_reset(path, violations, blocked)
    review_path = stage_root / "handoff" / "REVIEW.md"
    if review_path.exists() and "Decision: PASS" not in review_path.read_text(encoding="utf-8"):
        violations.append(violation("review_not_pass", "Review artifact exists but does not contain Decision: PASS.", path=str(review_path)))
    return violations, blocked


def _validate_h01_acceptance_reset(path: Path, violations: list[dict[str, Any]], blocked: list[str]) -> None:
    if not path.exists():
        blocked.append(f"{path.as_posix()} is missing.")
        return
    payload = read_json(path)
    if not isinstance(payload, dict):
        violations.append(violation("acceptance_reset_invalid_json", "H01 acceptance reset is not valid JSON.", path=str(path)))
        return
    expected = {
        "schema_version": "v1",
        "artifact_type": "milestone1_acceptance_reset",
        "stage_id": "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET",
        "hardening_loop_status": "PASS",
        "milestone1_status": "BLOCKED_WITH_REASON",
        "false_pass_prevented": True,
        "required_claim_count": 29,
        "passed_claim_count": 0,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            violations.append(violation("acceptance_reset_bad_field", f"H01 acceptance reset field {key} must be {value!r}.", path=str(path), details={"actual": payload.get(key)}))
    claims = payload.get("claims")
    if not isinstance(claims, list) or len(claims) != 29:
        violations.append(violation("acceptance_reset_claims_bad", "H01 acceptance reset must include all 29 required claims.", path=str(path)))
        return
    for claim in claims:
        if not isinstance(claim, dict):
            violations.append(violation("acceptance_reset_claim_bad", "H01 acceptance reset claim must be an object.", path=str(path)))
            continue
        if claim.get("acceptance_status") == "PASS":
            violations.append(violation("acceptance_reset_unexpected_pass", "H01 reset cannot contain required claim PASS.", path=str(path), claim_id=str(claim.get("claim_id"))))
        if not isinstance(claim.get("reason"), str) or not claim.get("reason", "").strip():
            violations.append(violation("acceptance_reset_reason_missing", "H01 reset claim must include a reason.", path=str(path), claim_id=str(claim.get("claim_id"))))


def _validate_gate_result(path: Path, gate_name: str, stage_id: str, violations: list[dict[str, Any]], blocked: list[str]) -> None:
    if not path.exists():
        blocked.append(f"{path.as_posix()} is missing.")
        return
    payload = read_json(path)
    if not isinstance(payload, dict):
        violations.append(violation("gate_result_invalid_json", "Gate result is not valid JSON.", path=str(path)))
        return
    expected = {
        "schema_version": "v1",
        "artifact_type": "m1h_gate_result",
        "stage_id": stage_id,
        "gate_name": gate_name,
        "status": "PASS",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            violations.append(violation("gate_result_bad_field", f"Gate result field {key} must be {value!r}.", path=str(path), details={"actual": payload.get(key)}))
    for key in ["checked_at", "inputs", "violations", "blocked_reasons", "source_commit"]:
        if key not in payload:
            violations.append(violation("gate_result_missing_field", f"Gate result is missing {key}.", path=str(path)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Assert H00 stage exit conditions.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", required=True)
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    violations, blocked = validate_stage_exit(root, args.stage)
    status = "FAIL" if violations else "BLOCKED_WITH_REASON" if blocked else "PASS"
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=["runs/m1-hardening/evidence_manifest.json", f"runs/m1-hardening/{args.stage}/artifacts/gates"],
        violations=violations,
        blocked_reasons=blocked,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
