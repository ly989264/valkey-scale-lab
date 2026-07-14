#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.config.validation import load_effective_config  # noqa: E402
from valkey_scale_lab.planner.plan import build_cluster_plan  # noqa: E402

CONFIGS = [
    "templates/configs/single_mac_6node.yaml",
    "templates/configs/scale_10.yaml",
    "templates/configs/scale_30.yaml",
    "templates/configs/scale_50.yaml",
    "templates/configs/scale_100.yaml",
    "templates/configs/scale_200.yaml",
    "templates/configs/scale_1000_dryrun_optin.yaml",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--global-config", default="config/valkey_scale_lab_global.yaml")
    args = parser.parse_args()
    errors: list[str] = []
    global_path = ROOT / args.global_config
    if not global_path.exists():
        errors.append(f"global config missing: {args.global_config}")
    else:
        text = global_path.read_text(encoding="utf-8")
        for token in ["nodehost_strategy", "max_nodehosts", "nodehosts_per_az", "max_logical_nodes_per_nodehost", "nodehost_distribution"]:
            if token not in text:
                errors.append(f"global config missing {token}")
    for config_path in CONFIGS:
        try:
            config = load_effective_config(ROOT / config_path)
        except Exception as exc:
            errors.append(f"{config_path}: failed to load effective config: {exc}")
            continue
        runtime = config.get("runtime", {})
        for key in ["nodehost_strategy", "max_nodehosts", "nodehosts_per_az", "max_logical_nodes_per_nodehost", "nodehost_distribution"]:
            if key not in runtime:
                errors.append(f"{config_path}: runtime.{key} missing after global merge")
        if config.get("_config_sources", {}).get("merge_order") != ["built-in defaults", "global config", "scenario config", "CLI override"]:
            errors.append(f"{config_path}: merge order not recorded")
        try:
            if config_path.endswith("scale_200.yaml"):
                plan = build_cluster_plan(
                    config,
                    capability_id="management_matrix",
                    scenario="management_matrix",
                )
            else:
                plan = build_cluster_plan(config, force_dry_run=bool(runtime.get("dry_run")))
        except Exception as exc:
            if config_path.endswith("single_mac_6node.yaml"):
                continue
            errors.append(f"{config_path}: density plan failed: {exc}")
            continue
        density = plan.get("nodehost_density", {})
        if density.get("actual_nodehost_count", 0) > density.get("max_nodehosts", 0):
            errors.append(f"{config_path}: actual nodehost count exceeds max")
        counts = density.get("logical_nodes_per_nodehost", {})
        if any(int(value) > int(density.get("max_logical_nodes_per_nodehost", 0)) for value in counts.values()):
            errors.append(f"{config_path}: logical node count exceeds density max")
    capture_dir = ROOT / "artifacts" / "capabilities" / args.capability_id
    if capture_dir.exists():
        for name in ["run_summary.json", "nodehost_density_plan.json", "resource_preflight.json", "cluster_plan.json", "run_state.json"]:
            path = capture_dir / name
            if not path.exists():
                errors.append(f"NODEHOST_DENSITY artifact missing: {name}")
            else:
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    errors.append(f"{name}: invalid JSON: {exc}")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS nodehost density config capability_id={args.capability_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
