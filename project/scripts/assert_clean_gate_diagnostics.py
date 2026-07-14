#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed CLEAN_GATE_DIAGNOSTICS clean-gate diagnostics assertion")
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()
    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "capabilities" / args.capability_id
    errors: list[str] = []
    diagnostics = _load_json(base / "clean_gate_diagnostics.json", errors)
    rounds = _load_jsonl(base / "clean_gate_probe_rounds.jsonl", errors)
    required = [
        "clean_gate_total_ms",
        "probe_round_count",
        "full_probe_count",
        "representative_probe_count",
        "all_nodes_probe_count",
        "probe_timeout_count",
        "max_single_probe_ms",
        "slowest_probe_node",
        "slowest_probe_ms",
        "last_failing_reason",
    ]
    for field in required:
        if field not in diagnostics or diagnostics.get(field) in {None, ""}:
            errors.append(f"clean_gate_diagnostics.json missing {field}")
    if diagnostics.get("capability_id") != args.capability_id:
        errors.append("clean_gate_diagnostics.json capability_id mismatch")
    if diagnostics.get("probe_round_count") != len(rounds):
        errors.append("probe_round_count must match clean_gate_probe_rounds.jsonl rows")
    full = [row for row in rounds if row.get("sample_scope") == "all_nodes"]
    reps = [row for row in rounds if row.get("sample_scope") == "representative"]
    if diagnostics.get("full_probe_count") != len(full):
        errors.append("full_probe_count must derive from all-node rounds")
    if diagnostics.get("representative_probe_count") != len(reps):
        errors.append("representative_probe_count must derive from representative rounds")
    for index, row in enumerate(rounds, start=1):
        _check_round(index, row, args.capability_id, errors)
    if rounds and rounds[0].get("status") != "PASS" and diagnostics.get("last_failing_reason") in {"", "MISSING", None}:
        errors.append("last_failing_reason is required when the clean-gate did not immediately pass")
    slowest = max((row for row in rounds if isinstance(row.get("slowest_probe_ms"), (int, float))), key=lambda r: float(r.get("slowest_probe_ms", 0)), default=None)
    if slowest and diagnostics.get("slowest_probe_ms") != slowest.get("slowest_probe_ms"):
        errors.append("slowest_probe_ms must derive from clean_gate_probe_rounds.jsonl")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS clean-gate diagnostics capability_id={args.capability_id}")
    return 0


def _check_round(index: int, row: dict[str, Any], capability_id: str, errors: list[str]) -> None:
    for field in ["probe_start_ms", "probe_end_ms", "probe_duration_ms", "sample_scope", "sample_count", "failed_reason", "slowest_node"]:
        if field not in row:
            errors.append(f"round {index}: missing {field}")
    if row.get("capability_id") != capability_id:
        errors.append(f"round {index}: capability_id mismatch")
    if row.get("sample_scope") not in {"representative", "all_nodes"}:
        errors.append(f"round {index}: invalid sample_scope")
    if isinstance(row.get("probe_start_ms"), (int, float)) and isinstance(row.get("probe_end_ms"), (int, float)):
        if row["probe_end_ms"] < row["probe_start_ms"]:
            errors.append(f"round {index}: probe_end_ms precedes probe_start_ms")
        if row.get("probe_duration_ms") != max(0, row["probe_end_ms"] - row["probe_start_ms"]):
            errors.append(f"round {index}: probe_duration_ms does not derive from endpoints")
    if row.get("status") != "PASS" and not row.get("failed_reason"):
        errors.append(f"round {index}: failed round requires failed_reason")


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"missing artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return {}


def _load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        errors.append(f"missing artifact: {path}")
        return []
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            errors.append(f"{path}:{lineno}: invalid JSON: {exc}")
    if not rows:
        errors.append(f"empty jsonl artifact: {path}")
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
