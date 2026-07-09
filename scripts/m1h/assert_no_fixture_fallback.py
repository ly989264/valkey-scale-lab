#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import exit_code, print_gate_summary, read_json, relpath, violation, write_gate_result

GATE = "assert_no_fixture_fallback"


def scan_fixture_fallbacks(root: Path) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    targets = [root / "scripts" / "assert_milestone1_acceptance.py"]
    gate_validation_modules = {Path(__file__).name, "assert_no_legacy_m1_pass.py", "manifest.py"}
    targets.extend(path for path in (root / "scripts" / "m1h").glob("*.py") if path.name not in gate_validation_modules)
    for path in targets:
        if not path.exists():
            continue
        rel = relpath(root, path)
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines, start=1):
            lowered = line.lower()
            if "tests/fixtures" in lowered and _looks_like_pass_path(lines, index - 1):
                violations.append(
                    violation(
                        "fixture_fallback_pass_path",
                        "Fixture path appears in milestone PASS-capable code.",
                        path=rel,
                        line=index,
                    )
                )
            if "cross-scenario fixture coverage" in lowered and "_result(\"pass\"" in lowered.replace("'", '"'):
                violations.append(
                    violation("fixture_coverage_promoted", "Cross-scenario fixture coverage is promoted to PASS.", path=rel, line=index)
                )
    return violations


def manifest_fixture_violations(root: Path, manifest_path: Path) -> list[dict[str, Any]]:
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict):
        return []
    violations: list[dict[str, Any]] = []
    for claim in manifest.get("claims", []):
        if not isinstance(claim, dict):
            continue
        if claim.get("required_for_milestone_pass") is True and claim.get("status") == "PASS":
            fixture_sources = [source for source in claim.get("source_artifacts", []) if isinstance(source, str) and "tests/fixtures/" in source]
            if fixture_sources or claim.get("evidence_kind") == "FIXTURE_ONLY":
                violations.append(
                    violation(
                        "fixture_claim_pass",
                        "Required milestone claim passed using fixture evidence.",
                        claim_id=str(claim.get("claim_id")),
                        details={"source_artifacts": fixture_sources, "evidence_kind": claim.get("evidence_kind")},
                    )
                )
    return violations


def _looks_like_pass_path(lines: list[str], index: int) -> bool:
    window = "\n".join(lines[max(0, index - 4) : min(len(lines), index + 5)]).lower()
    return any(token in window for token in ["pass", "ok =", "bool(", "not matrix", "not metrics", "not commands"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Reject fixture fallback for M1 exact-scale PASS claims.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--stage", default="H00_BOOTSTRAP_HARD_GATES")
    parser.add_argument("--manifest", default="runs/m1-hardening/evidence_manifest.json")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    violations = scan_fixture_fallbacks(root) + manifest_fixture_violations(root, manifest_path)
    blocked_reasons: list[str] = []
    extra: dict[str, Any] = {}
    if args.stage == "H00_BOOTSTRAP_HARD_GATES" and violations:
        blocked_reasons = [
            "H00 bootstraps the fixture-fallback detector; existing acceptance fallbacks are deferred to H01/H02 and must not satisfy manifest claims."
        ]
        extra["deferred_violations"] = violations
        violations = []
    status = "FAIL" if violations else "PASS"
    result = write_gate_result(
        root=root,
        stage_id=args.stage,
        gate_name=GATE,
        status=status,
        inputs=["scripts/assert_milestone1_acceptance.py", "scripts/m1h", str(manifest_path)],
        violations=violations,
        blocked_reasons=blocked_reasons,
        extra=extra,
    )
    print_gate_summary(result)
    return exit_code(status, allow_blocked=args.allow_blocked)


if __name__ == "__main__":
    raise SystemExit(main())
