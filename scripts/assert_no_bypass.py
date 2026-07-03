#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from strict_harness_lib import (  # noqa: E402
    STRICT_200_EXCEPTIONS,
    STRICT_NON_RUNTIME_STAGES,
    STRICT_STAGE_IDS,
    load_json,
    load_manifest,
    phase_map,
    print_errors,
    rel,
)

BYPASS_COMMAND_PATTERNS = [
    re.compile(r"\becho\s+PASS\b"),
    re.compile(r"\bprintf\s+PASS\b"),
]

HOST_MUTATION_TOKENS = [
    "pf" + "ctl",
    "ip" + "tables",
    "nf" + "t",
    "ip " + "route",
    "route " + "add",
    "route " + "delete",
    "if" + "config",
    "network" + "setup",
]


def validate_manifest_for_bypass(phase: str, manifest_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    manifest = load_manifest(manifest_path)
    phases = phase_map(manifest)
    for pid, item in phases.items():
        max_nodes = int(item.get("max_nodes", 0))
        if item.get("automatic", True) and max_nodes > 200:
            errors.append(f"{pid}: automatic real execution above 200 nodes is forbidden")
        if pid in STRICT_STAGE_IDS and max_nodes == 200 and pid not in STRICT_200_EXCEPTIONS:
            errors.append(f"{pid}: only P32/P35/P36 may be strict 200-node bounded exceptions")
        if pid in STRICT_STAGE_IDS and pid not in STRICT_NON_RUNTIME_STAGES and item.get("fake_only_allowed"):
            errors.append(f"{pid}: real strict stages must not be fake-only")
        if pid == "P37_200_PLUS_DRY_RUN_SUPPORT":
            if item.get("execution_mode") != "dry_run":
                errors.append("P37 must remain dry-run-only")
            if item.get("real_valkey_required") is True:
                errors.append("P37 must not require live Valkey")
        if pid in STRICT_200_EXCEPTIONS:
            commands = " ".join(str(gate.get("command", "")) for gate in item.get("gates", []))
            if "--nodes 200" not in commands and "--scales 50,100,200" not in commands:
                errors.append(f"{pid}: 200-node stage is missing exact 200-node assertion")
            if "--nodes 100" in commands and "--nodes 200" not in commands:
                errors.append(f"{pid}: suspected 200-node downshift to 100 nodes")
        for gate in item.get("gates", []):
            command = str(gate.get("command", ""))
            for pattern in BYPASS_COMMAND_PATTERNS:
                if pattern.search(command):
                    errors.append(f"{pid}/{gate.get('name')}: PASS-only command is forbidden")
            lowered = command.lower()
            if ("su" + "do") in lowered and any(token in lowered for token in HOST_MUTATION_TOKENS):
                errors.append(f"{pid}/{gate.get('name')}: elevated host network mutation command is forbidden")
            if any(token in lowered for token in HOST_MUTATION_TOKENS) and "container" not in lowered and "sandbox" not in lowered:
                errors.append(f"{pid}/{gate.get('name')}: host network mutation command is forbidden")
    if phase not in phases:
        errors.append(f"unknown phase: {phase}")
    return errors


def validate_gate_result_if_present(phase: str) -> list[str]:
    errors: list[str] = []
    path = ROOT / "artifacts" / "gates" / phase / "gate_result.json"
    if not path.exists():
        return errors
    try:
        result = load_json(path)
    except Exception as exc:
        return [f"{rel(path)}: invalid JSON: {exc}"]
    if result.get("runner") != "scripts/codex_gate.py":
        errors.append(f"{rel(path)}: gate result runner must be scripts/codex_gate.py")
    if result.get("status") == "PASS" and not result.get("gates"):
        errors.append(f"{rel(path)}: PASS gate result must include gate records")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--scan-all-strict-stages", action="store_true")
    args = parser.parse_args()

    errors = validate_manifest_for_bypass(args.phase, args.manifest)
    phases = STRICT_STAGE_IDS if args.scan_all_strict_stages else [args.phase]
    for phase in phases:
        errors.extend(validate_gate_result_if_present(phase))
    if errors:
        return print_errors(errors)
    print(f"PASS no-bypass assertion phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
