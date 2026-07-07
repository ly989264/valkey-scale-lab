#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab.config.simple_yaml import parse_config_file  # noqa: E402
from valkey_scale_lab.config.validation import load_effective_config, validate_config_file  # noqa: E402

DEFAULT_CONFIGS = [
    "templates/configs/scale_10.yaml",
    "templates/configs/scale_30.yaml",
    "templates/configs/scale_50.yaml",
    "templates/configs/scale_100.yaml",
    "templates/configs/scale_200.yaml",
    "templates/configs/scale_1000_dryrun_optin.yaml",
]
DEFAULT_TIMEOUT_MS = 30000
MATRIX = [5000, 10000, 15000, 30000, 60000]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--global-config", default="config/valkey_scale_lab_global.yaml")
    parser.add_argument("--config", action="append", dest="configs")
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()

    errors: list[str] = []
    global_path = _path(args.global_config)
    artifact_dir = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "phases" / args.phase
    configs = [_path(item) for item in (args.configs or DEFAULT_CONFIGS)]

    _check_global_config(global_path, errors)
    for config in configs:
        _check_effective_config(config, global_path, errors)
    _check_validation_report(configs[0], global_path, errors)
    _check_artifacts_if_present(artifact_dir, errors)

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS cluster timeout config phase={args.phase}")
    return 0


def _check_global_config(path: Path, errors: list[str]) -> None:
    try:
        obj = parse_config_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"global config invalid: {exc}")
        return
    cluster = obj.get("cluster", {})
    fault = obj.get("fault", {})
    profiles = obj.get("profiles", {})
    if cluster.get("cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
        errors.append("global cluster.cluster_node_timeout_ms must be 30000")
    if fault.get("cluster_node_timeout_matrix_ms") != MATRIX:
        errors.append(f"global fault.cluster_node_timeout_matrix_ms must be {MATRIX}")
    for name in ["correctness", "failover_rto", "management_safe"]:
        profile = profiles.get(name)
        if not isinstance(profile, dict) or profile.get("cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
            errors.append(f"global profiles.{name}.cluster_node_timeout_ms must be 30000")
    if profiles.get("management_safe", {}).get("allow_override") is not True:
        errors.append("global profiles.management_safe.allow_override must be true")


def _check_effective_config(config_path: Path, global_path: Path, errors: list[str]) -> None:
    try:
        config = load_effective_config(config_path, global_config_path=global_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{_rel(config_path)} failed to load: {exc}")
        return
    timeout = config.get("_effective_cluster_timeout", {})
    if timeout.get("effective_cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
        errors.append(f"{_rel(config_path)} effective timeout is not 30000")
    if timeout.get("cluster_node_timeout_source") not in {"global", "profile", "scenario", "cli"}:
        errors.append(f"{_rel(config_path)} missing explicit timeout source")
    if timeout.get("cluster_node_timeout_matrix_ms") != MATRIX:
        errors.append(f"{_rel(config_path)} timeout matrix is not {MATRIX}")
    sources = config.get("_config_sources", {}).get("cluster_node_timeout", {})
    if sources.get("merge_order") != ["built-in defaults", "global config", "selected profile", "scenario config", "CLI override"]:
        errors.append(f"{_rel(config_path)} timeout merge order missing selected profile")
    if sources.get("effective_cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
        errors.append(f"{_rel(config_path)} config_sources missing effective timeout")


def _check_validation_report(config_path: Path, global_path: Path, errors: list[str]) -> None:
    out = ROOT / "artifacts" / "_p43_assert_tmp" / f"{config_path.stem}_validation.json"
    report = validate_config_file(config_path, out, global_config_path=global_path)
    for field in ["requested_cluster_node_timeout_ms", "effective_cluster_node_timeout_ms", "cluster_node_timeout_source"]:
        if field not in report:
            errors.append(f"validation report missing {field}")
    if report.get("effective_cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
        errors.append("validation report effective timeout is not 30000")


def _check_artifacts_if_present(base: Path, errors: list[str]) -> None:
    if not base.exists():
        return
    for name in ["config_validation_report.json", "effective_cluster_timeout.json", "cluster_plan.json", "resource_preflight.json"]:
        path = base / name
        if path.exists():
            obj = _load_json(path, errors)
            observed = (
                obj.get("effective_cluster_node_timeout_ms")
                or obj.get("cluster_node_timeout", {}).get("effective_cluster_node_timeout_ms")
                or obj.get("effective_cluster_timeout", {}).get("effective_cluster_node_timeout_ms")
                or obj.get("runtime", {}).get("effective_cluster_node_timeout_ms")
                or obj.get("runtime", {}).get("cluster_timeout", {}).get("effective_cluster_node_timeout_ms")
            )
            if observed != DEFAULT_TIMEOUT_MS:
                errors.append(f"{name}: does not record effective timeout 30000")
    run_state = _load_json(base / "run_state.json", errors) if (base / "run_state.json").exists() else {}
    nodes = run_state.get("nodes", []) if isinstance(run_state, dict) else []
    for node in nodes:
        if node.get("effective_cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
            errors.append(f"run_state node {node.get('logical_id')} missing effective timeout 30000")
    manifest = _load_json(base / "generated_valkey_configs_manifest.json", errors) if (base / "generated_valkey_configs_manifest.json").exists() else {}
    for entry in manifest.get("entries", []) if isinstance(manifest, dict) else []:
        if entry.get("cluster_node_timeout_line_present") is not True or entry.get("cluster_node_timeout_source_present") is not True:
            errors.append(f"generated config {entry.get('logical_id')} lacks timeout line/source proof")
    for name, expected in [
        ("valkey_e2e_evidence.json", 10),
        ("valkey_e2e_evidence_30.json", 30),
        ("valkey_e2e_evidence_50.json", 50),
        ("valkey_e2e_evidence_100.json", 100),
        ("valkey_e2e_evidence_200.json", 200),
    ]:
        path = base / name
        if path.exists():
            evidence = _load_json(path, errors)
            if evidence.get("real_valkey") is not True:
                errors.append(f"{name}: real_valkey must be true")
            if int(evidence.get("nodes_observed", 0) or 0) < expected:
                errors.append(f"{name}: silent downscale observed={evidence.get('nodes_observed')} expected={expected}")
            for proc in evidence.get("node_processes", [])[:expected]:
                if proc.get("effective_cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
                    errors.append(f"{name}: node_processes missing timeout evidence")
    projection = base / "dry_run_gt_200_projection.json"
    if projection.exists():
        obj = _load_json(projection, errors)
        if obj.get("real_valkey") is True:
            errors.append("greater-than-200 projection must not claim real_valkey")
        if obj.get("effective_cluster_timeout", {}).get("effective_cluster_node_timeout_ms") != DEFAULT_TIMEOUT_MS:
            errors.append("greater-than-200 projection missing timeout config")


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{_rel(path)} invalid JSON: {exc}")
        return {}


def _path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
