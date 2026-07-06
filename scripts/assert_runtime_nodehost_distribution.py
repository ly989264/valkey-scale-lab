#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FIELDS = [
    "nodehost_strategy",
    "max_nodehosts",
    "nodehosts_per_az",
    "max_logical_nodes_per_nodehost",
    "actual_nodehost_count",
    "logical_nodes_per_nodehost",
    "nodehost_distribution",
]


def load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        errors.append(f"{label} missing: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{label} invalid JSON: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{label} must be a JSON object")
        return {}
    return data


def density(obj: dict[str, Any]) -> dict[str, Any]:
    if isinstance(obj.get("nodehost_density"), dict):
        return obj["nodehost_density"]
    if isinstance(obj.get("runtime"), dict):
        runtime = obj["runtime"]
        found = {field: runtime[field] for field in REQUIRED_FIELDS if field in runtime}
        if found:
            return found
    return {field: obj[field] for field in REQUIRED_FIELDS if field in obj}


def validate_density(label: str, obj: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    d = density(obj)
    missing = [field for field in REQUIRED_FIELDS if field not in d]
    if missing:
        errors.append(f"{label}: missing density fields {missing}")
        return d
    if d["nodehost_strategy"] != "density_limited":
        errors.append(f"{label}: nodehost_strategy must be density_limited")
    if d["nodehost_distribution"] != "round_robin_by_az":
        errors.append(f"{label}: nodehost_distribution must be round_robin_by_az")
    counts = d.get("logical_nodes_per_nodehost", {})
    if not isinstance(counts, dict) or not counts:
        errors.append(f"{label}: logical_nodes_per_nodehost must be non-empty object")
        return d
    actual = int(d["actual_nodehost_count"])
    max_nodehosts = int(d["max_nodehosts"])
    max_per = int(d["max_logical_nodes_per_nodehost"])
    if actual != len(counts):
        errors.append(f"{label}: actual_nodehost_count {actual} != logical_nodes_per_nodehost count {len(counts)}")
    if actual > max_nodehosts:
        errors.append(f"{label}: actual_nodehost_count {actual} exceeds max_nodehosts {max_nodehosts}")
    over = {key: value for key, value in counts.items() if int(value) > max_per}
    if over:
        errors.append(f"{label}: nodehosts exceed max_logical_nodes_per_nodehost {max_per}: {over}")
    node_count = int(d.get("node_count", sum(int(value) for value in counts.values())) or 0)
    if node_count == 200 and actual <= 2:
        errors.append(f"{label}: 200 nodes must not be concentrated into {actual} nodehosts")
    if node_count == 200 and max_per == 25 and actual != 8:
        errors.append(f"{label}: 200 nodes with max 25 must use 8 nodehosts, got {actual}")
    return d


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()

    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "phases" / args.phase
    errors: list[str] = []
    artifacts = {
        "nodehost_density_plan": load_json(base / "nodehost_density_plan.json", errors, "nodehost_density_plan"),
        "resource_preflight": load_json(base / "resource_preflight.json", errors, "resource_preflight"),
        "cluster_plan": load_json(base / "cluster_plan.json", errors, "cluster_plan"),
        "run_state": load_json(base / "run_state.json", errors, "run_state"),
    }
    densities = {label: validate_density(label, obj, errors) for label, obj in artifacts.items() if obj}
    reference = next((item for item in densities.values() if item), {})
    for label, item in densities.items():
        for field in REQUIRED_FIELDS[:5] + ["nodehost_distribution"]:
            if field in reference and item.get(field) != reference.get(field):
                errors.append(f"{label}: {field} {item.get(field)!r} != reference {reference.get(field)!r}")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS runtime nodehost distribution phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
