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
REQUIRED_SCRIPTS = [
    "build_evidence_manifest.py",
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
    for gate_name in H00_REQUIRED_GATE_RESULTS:
        path = gates_root / f"{gate_name}.json"
        _validate_gate_result(path, gate_name, stage_id, violations, blocked)
    stage_root = root / "runs" / "m1-hardening" / stage_id
    for rel in REQUIRED_STAGE_ARTIFACTS:
        path = stage_root / rel
        if not path.exists():
            blocked.append(f"runs/m1-hardening/{stage_id}/{rel} is missing.")
    review_path = stage_root / "handoff" / "REVIEW.md"
    if review_path.exists() and "Decision: PASS" not in review_path.read_text(encoding="utf-8"):
        violations.append(violation("review_not_pass", "Review artifact exists but does not contain Decision: PASS.", path=str(review_path)))
    return violations, blocked


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
