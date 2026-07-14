#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import (  # noqa: E402
    STRICT_200_EXCEPTIONS,
    STRICT_COMMON_GATE_NAMES,
    STRICT_NON_RUNTIME_STAGES,
    STRICT_STAGE_IDS,
    STRICT_STAGES,
    load_manifest,
    phase_map,
    print_errors,
    rel,
    strict_handoff_dir,
    strict_stage_doc,
)


def validate_strict_contract(phase: str, manifest_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    manifest = load_manifest(manifest_path)
    phases = phase_map(manifest)
    all_ids = [item.get("id") for item in manifest.get("phases", [])]

    if manifest.get("default_max_nodes") != 100:
        errors.append("default_max_nodes must remain exactly 100")
    if manifest.get("automatic_stop_after") != "P40_STRICT_FINAL_AUDIT_CLOSEOUT":
        errors.append("automatic_stop_after must be P40_STRICT_FINAL_AUDIT_CLOSEOUT")

    p14 = phases.get("P14_SCALE_1000_OPTIN_DRYRUN")
    if not p14:
        errors.append("P14_SCALE_1000_OPTIN_DRYRUN missing")
    elif p14.get("automatic") is not False:
        errors.append("P14 must remain non-automatic")

    missing = [stage_id for stage_id in STRICT_STAGE_IDS if stage_id not in phases]
    if missing:
        errors.append(f"missing strict stages: {missing}")
    else:
        positions = [all_ids.index(stage_id) for stage_id in STRICT_STAGE_IDS]
        if positions != sorted(positions):
            errors.append("strict stages are not in P27-P40 order")
        if all_ids[positions[0] : positions[-1] + 1] != STRICT_STAGE_IDS:
            errors.append("strict stages must be contiguous P27-P40 entries")

    observed_200 = {
        pid
        for pid, item in phases.items()
        if pid in STRICT_STAGE_IDS and item.get("automatic", True) and int(item.get("max_nodes", 0)) == 200
    }
    if observed_200 != STRICT_200_EXCEPTIONS:
        errors.append(f"strict 200-node bounded exceptions must be exact: {sorted(STRICT_200_EXCEPTIONS)}")

    for stage in STRICT_STAGES:
        stage_id = stage["id"]
        doc = strict_stage_doc(stage_id)
        if not doc.exists():
            errors.append(f"{stage_id}: strict stage document missing: {rel(doc)}")
        phase_entry = phases.get(stage_id)
        if not phase_entry:
            continue
        if phase_entry.get("automatic") is not True:
            errors.append(f"{stage_id}: strict stages must be automatic")
        if phase_entry.get("real_valkey_required") is not stage["real"]:
            errors.append(f"{stage_id}: real_valkey_required must be {stage['real']}")
        if int(phase_entry.get("max_nodes", -1)) != int(stage["max_nodes"]):
            errors.append(f"{stage_id}: max_nodes must be {stage['max_nodes']}")
        if stage_id in STRICT_NON_RUNTIME_STAGES and phase_entry.get("real_valkey_required"):
            errors.append(f"{stage_id}: non-runtime strict stage must not require live Valkey")
        if stage_id == "P37_200_PLUS_DRY_RUN_SUPPORT":
            if phase_entry.get("execution_mode") != "dry_run":
                errors.append("P37 must be declared execution_mode=dry_run")
            targets = phase_entry.get("dry_run_target_nodes", [])
            if [201, 250, 300, 500, 1000] != targets:
                errors.append("P37 dry_run_target_nodes must be exactly [201, 250, 300, 500, 1000]")
        if int(phase_entry.get("max_nodes", 0)) > 200:
            errors.append(f"{stage_id}: no strict automatic stage may declare max_nodes above 200")

        gate_names = {gate.get("name") for gate in phase_entry.get("gates", [])}
        missing_gates = sorted(STRICT_COMMON_GATE_NAMES - gate_names)
        if missing_gates:
            errors.append(f"{stage_id}: missing strict common gates {missing_gates}")
        for gate in phase_entry.get("gates", []):
            command = str(gate.get("command", ""))
            if "scripts/codex_gate.py run" in command or "scripts/codex_gate.py postcheck" in command:
                errors.append(f"{stage_id}/{gate.get('name')}: recursive codex_gate run/postcheck is forbidden")
            if gate.get("real_valkey") and "scripts/valkey_e2e_gate.py" not in command and "scripts/fault_" not in command:
                errors.append(f"{stage_id}/{gate.get('name')}: real_valkey gate must use an authored wrapper")
        if stage["real"] and not any(gate.get("real_valkey") for gate in phase_entry.get("gates", [])):
            errors.append(f"{stage_id}: missing real_valkey wrapper gate")
        if stage_id in {"P30_MANAGEMENT_MATRIX_50_REAL", "P31_MANAGEMENT_MATRIX_100_REAL", "P32_MANAGEMENT_MATRIX_200_REAL", "P33_FAULT_FAILOVER_MATRIX_50_REAL", "P34_FAULT_FAILOVER_MATRIX_100_REAL", "P35_FAULT_FAILOVER_MATRIX_200_REAL"}:
            scale = int(stage["max_nodes"])
            exact = f"assert_exact_scale_real_evidence.py --phase {stage_id} --nodes {scale}"
            if not any(exact in str(gate.get("command", "")) for gate in phase_entry.get("gates", [])):
                errors.append(f"{stage_id}: missing exact-scale assertion command for {scale} nodes")

    if phase not in phases:
        errors.append(f"unknown phase: {phase}")
    if phase in STRICT_STAGE_IDS:
        handoff_dir = strict_handoff_dir(phase)
        for name in ["CONTEXT_RELOAD.md", "DESIGN_BRIEF.md"]:
            path = handoff_dir / name
            if not path.exists():
                errors.append(f"{phase}: strict handoff missing: {rel(path)}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    errors = validate_strict_contract(args.phase, args.manifest)
    if errors:
        return print_errors(errors)
    print(f"PASS strict stage contract phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

