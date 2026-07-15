#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".py", ".toml", ".yaml", ".yml"}
COMPATIBILITY_FILES = {
    "src/valkey_scale_lab/compat/phase_aliases.py",
    "src/valkey_scale_lab/compat/__init__.py",
    "src/valkey_scale_lab/cli_compat.py",
    "scripts/fault_safety_gate.py",
    "tests/cli/test_compatibility_wrappers.py",
}
SCAN_ROOTS = (
    "artifacts",
    "docs",
    "milestones",
    "schemas",
    "scripts",
    "src",
    "templates",
    "tests",
    "verification",
)
PXX = re.compile(r"\bP[0-9]{2}(?:[A-Z0-9_-]*)\b")
ROLLOUT_ID = re.compile(r"\b(?:L|CML)[0-9]{2}(?:[A-Z0-9_-]*)\b")
MILESTONE_STAGE_ID = re.compile(
    r"\bM[0-9]+[-_](?:S|STAGE|PHASE)[0-9]+(?:[A-Z0-9_-]*)\b",
    flags=re.IGNORECASE,
)
CONTROLLER_TERMS = (
    "loop_engineering",
    "capability_matrix_loop",
    "goal_loop",
    "startup_optimization",
    "stage_owner",
    "stage_window",
)
SCALE_BOUND_SCENARIO = re.compile(
    r"(?i)[\"']?scenario(?:_name)?[\"']?\s*(?:=|:)\s*[^\n]{0,120}(?:scale_[0-9]+|strict_[a-z0-9_]*_[0-9]+)"
)
NUMBERED_CAPABILITY = re.compile(r"\b[A-Z][A-Z0-9_]+-[0-9]{2}_[A-Z0-9_]+\b")
PROFILE_SEMANTIC_KEY = re.compile(
    r"^\s*(?:bounded_exception_)?(?:capability|scenario)(?:_id|_name)?\s*:",
    flags=re.IGNORECASE,
)
DUPLICATE_EXECUTION_PROFILE = re.compile(
    r"(?:class\s+\w*ExecutionProfile\b|\b\w*EXECUTION_PROFILES\s*=)"
)


def _files() -> list[Path]:
    rows = [
        path
        for path in ROOT.iterdir()
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and path.resolve() != SELF
    ]
    for name in SCAN_ROOTS:
        base = ROOT / name
        if not base.exists():
            continue
        rows.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in TEXT_SUFFIXES
            and "__pycache__" not in path.parts
            and path.resolve() != SELF
        )
    return sorted(rows)


def audit() -> list[str]:
    errors: list[str] = []
    for path in _files():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        compatible = rel in COMPATIBILITY_FILES
        if not compatible and "phase" in path.name.lower():
            errors.append(f"{rel}: compatibility-only term appears in filename")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if compatible:
                continue
            if PXX.search(line):
                errors.append(f"{rel}:{line_number}: Pxx identifier outside compatibility boundary")
            if ROLLOUT_ID.search(line):
                errors.append(f"{rel}:{line_number}: controller rollout identifier remains in product content")
            if MILESTONE_STAGE_ID.search(line):
                errors.append(f"{rel}:{line_number}: milestone-stage identifier remains in product content")
            if NUMBERED_CAPABILITY.search(line):
                errors.append(f"{rel}:{line_number}: numbered capability identifier remains")
            if (
                "phase_id" in line
                or "stage_id" in line
                or "artifacts/phases" in line
                or "artifacts/capabilities" in line
            ):
                errors.append(f"{rel}:{line_number}: phase-owned artifact contract remains")
            if any(term in line.lower() for term in CONTROLLER_TERMS):
                errors.append(f"{rel}:{line_number}: controller-owned rollout term remains")
            if rel.startswith("templates/configs/") and PROFILE_SEMANTIC_KEY.search(line):
                errors.append(
                    f"{rel}:{line_number}: profile config owns scenario/capability semantics"
                )
            if rel != "src/valkey_scale_lab/execution.py" and DUPLICATE_EXECUTION_PROFILE.search(line):
                errors.append(
                    f"{rel}:{line_number}: duplicate execution profile registry/class remains"
                )
            if re.search(r"\bphase\b", line, flags=re.IGNORECASE):
                cli_alias = (
                    rel == "src/valkey_scale_lab/cli.py"
                    and 'add_argument("--phase"' in line
                    and "argparse.SUPPRESS" in line
                )
                if not cli_alias:
                    errors.append(f"{rel}:{line_number}: phase term outside compatibility boundary")
        for match in SCALE_BOUND_SCENARIO.finditer(text):
            line_number = text.count("\n", 0, match.start()) + 1
            errors.append(
                f"{rel}:{line_number}: scenario semantics encode scale; use profile_id/node count"
            )

    catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    if catalog.get("schema_version") != "verification-catalog-v2":
        errors.append("catalog.json: executable catalog must use v2")
    for test in catalog.get("tests", []):
        runner = test.get("runner", {})
        if runner.get("type") == "pytest" and runner.get("result") != "junit":
            errors.append(
                f"catalog.json: pytest Test {test.get('test_id')} must use JUnit"
            )

    definition = json.loads(
        (ROOT / "src" / "valkey_scale_lab" / "scenarios" / "definitions" / "local_full_flow_v1.json").read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps(definition, sort_keys=True)
    if PXX.search(serialized) or "phase" in serialized.lower():
        errors.append("local_full_flow_v1.json: scenario definition contains compatibility-owned semantics")
    if "execution_steps" not in definition or "profile_bindings" in definition:
        errors.append("local_full_flow_v1.json: scenario must own steps, not profile bindings")
    return errors


def main() -> int:
    errors = audit()
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: scenario, backend, and profile axes are product-neutral")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
