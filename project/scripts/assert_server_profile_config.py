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
from valkey_scale_lab.config.validation import load_effective_config, normalize_config  # noqa: E402

DEFAULT_CONFIGS = [
    "templates/configs/scale_10.yaml",
    "templates/configs/scale_30.yaml",
    "templates/configs/scale_50.yaml",
    "templates/configs/scale_100.yaml",
    "templates/configs/scale_200.yaml",
    "templates/configs/scale_1000_dryrun_optin.yaml",
]
REQUIRED_VALKEY_KEYS = {
    "io_threads",
    "io_threads_auto",
    "io_threads_max_per_node",
    "io_threads_max_total",
    "log_format",
}
MERGE_ORDER = ["built-in defaults", "global config", "scenario config", "CLI override"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability-id", required=True)
    parser.add_argument("--global-config", default="config/valkey_scale_lab_global.yaml")
    parser.add_argument("--config", action="append", dest="configs")
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()

    errors: list[str] = []
    global_path = _path(args.global_config)
    configs = [_path(item) for item in (args.configs or DEFAULT_CONFIGS)]
    artifact_dir = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "capabilities" / args.capability_id

    _check_global_config(global_path, errors)
    for config_path in configs:
        _check_effective_config(config_path, global_path, errors)
    if configs:
        _check_merge_precedence(configs[0], global_path, errors)
    _check_capability_artifacts_if_present(artifact_dir, errors)

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS server profile config capability_id={args.capability_id}")
    return 0


def _path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _check_global_config(path: Path, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"global config missing: {path}")
        return
    try:
        config = parse_config_file(path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"global config invalid YAML: {exc}")
        return
    runtime = config.get("runtime")
    cluster = config.get("cluster")
    if not isinstance(runtime, dict):
        errors.append("global config missing runtime object")
        return
    if runtime.get("server_profile") not in {"correctness", "one_b_dev", "one_b_perf"}:
        errors.append("global config runtime.server_profile must be correctness, one_b_dev, or one_b_perf")
    valkey = runtime.get("valkey")
    if not isinstance(valkey, dict):
        errors.append("global config missing runtime.valkey object")
        return
    missing = sorted(REQUIRED_VALKEY_KEYS - set(valkey))
    if missing:
        errors.append(f"global config missing runtime.valkey keys {missing}")
    if valkey.get("log_format") not in {"text", "json"}:
        errors.append("global config runtime.valkey.log_format must be text or json")
    if valkey.get("io_threads_auto") not in {True, False}:
        errors.append("global config runtime.valkey.io_threads_auto must be boolean")
    io_threads = _int(valkey.get("io_threads"), 0)
    max_per_node = _int(valkey.get("io_threads_max_per_node"), 0)
    max_total = _int(valkey.get("io_threads_max_total"), 0)
    if io_threads < 1 or max_per_node < 1 or max_total < 1:
        errors.append("global config io-thread settings must be positive integers")
    if io_threads >= 6:
        errors.append("global config must not blindly set runtime.valkey.io_threads >= 6")
    if io_threads > max_per_node:
        errors.append("global config runtime.valkey.io_threads exceeds io_threads_max_per_node")
    if not isinstance(cluster, dict) or _int(cluster.get("node_memory_limit_mb") if isinstance(cluster, dict) else None, 0) != 64:
        errors.append("global config cluster.node_memory_limit_mb must be 64")


def _check_effective_config(config_path: Path, global_path: Path, errors: list[str]) -> None:
    if not config_path.exists():
        errors.append(f"scenario config missing: {config_path}")
        return
    try:
        config = load_effective_config(config_path, global_config_path=global_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{_rel(config_path)}: failed to load effective config: {exc}")
        return
    sources = config.get("_config_sources", {})
    if sources.get("merge_order") != MERGE_ORDER:
        errors.append(f"{_rel(config_path)}: merge order not recorded as {MERGE_ORDER}")
    runtime = config.get("runtime", {})
    valkey = runtime.get("valkey", {})
    if runtime.get("server_profile") not in {"correctness", "one_b_dev", "one_b_perf"}:
        errors.append(f"{_rel(config_path)}: invalid effective server_profile")
    missing = sorted(REQUIRED_VALKEY_KEYS - set(valkey))
    if missing:
        errors.append(f"{_rel(config_path)}: missing effective runtime.valkey keys {missing}")
    profile = config.get("_effective_server_profile", {})
    _check_profile_fields(_rel(config_path), profile, errors)
    if _int(config.get("cluster", {}).get("node_memory_limit_mb"), 0) != 64:
        errors.append(f"{_rel(config_path)}: effective cluster.node_memory_limit_mb must be 64 unless explicitly profile-justified")
    if profile.get("effective_node_memory_limit_mb") != 64:
        errors.append(f"{_rel(config_path)}: effective profile memory must be 64 MB")
    total_threads = _int(profile.get("total_valkey_threads"), 0)
    max_total = _int(profile.get("io_threads_max_total"), 0)
    if total_threads > max_total:
        errors.append(f"{_rel(config_path)}: total_valkey_threads exceeds io_threads_max_total")


def _check_merge_precedence(config_path: Path, global_path: Path, errors: list[str]) -> None:
    try:
        raw = parse_config_file(config_path)
        scenario_raw = json.loads(json.dumps(raw))
        scenario_raw.setdefault("runtime", {}).setdefault("valkey", {})["io_threads"] = 2
        scenario_raw["runtime"]["valkey"]["io_threads_max_per_node"] = 2
        scenario_config = normalize_config(scenario_raw, scenario_config_path=config_path, global_config_path=global_path)
        scenario_profile = scenario_config.get("_effective_server_profile", {})
        if scenario_profile.get("requested_io_threads") != 2 or scenario_profile.get("effective_io_threads") != 2:
            errors.append("scenario runtime.valkey.io_threads override did not beat global config")
        cli_config = normalize_config(
            scenario_raw,
            scenario_config_path=config_path,
            global_config_path=global_path,
            cli_overrides={"runtime": {"valkey": {"io_threads": 1}}},
        )
        cli_profile = cli_config.get("_effective_server_profile", {})
        if cli_profile.get("requested_io_threads") != 1 or cli_profile.get("effective_io_threads") != 1:
            errors.append("CLI io_threads override did not beat scenario config")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"merge precedence check failed: {exc}")


def _check_capability_artifacts_if_present(base: Path, errors: list[str]) -> None:
    if not base.exists():
        return
    for name in ["effective_server_profile.json", "config_validation_report.json", "cluster_plan.json"]:
        path = base / name
        if not path.exists():
            errors.append(f"SERVER_PROFILE artifact missing: {name}")
            continue
        obj = _load_json(path, errors, name)
        if name == "effective_server_profile.json":
            _check_profile_fields(name, obj, errors)
        if name == "config_validation_report.json":
            for field in [
                "requested_io_threads",
                "effective_io_threads",
                "requested_node_memory_limit_mb",
                "effective_node_memory_limit_mb",
                "io_thread_budget_status",
                "memory_budget_status",
            ]:
                if field not in obj:
                    errors.append(f"{name}: missing {field}")


def _check_profile_fields(label: str, profile: dict[str, Any], errors: list[str]) -> None:
    required = [
        "server_profile",
        "requested_io_threads",
        "effective_io_threads",
        "io_threads_auto",
        "io_threads_max_per_node",
        "io_threads_max_total",
        "total_valkey_threads",
        "io_thread_budget_status",
        "requested_node_memory_limit_mb",
        "effective_node_memory_limit_mb",
        "memory_budget_status",
        "log_format",
    ]
    missing = [field for field in required if field not in profile]
    if missing:
        errors.append(f"{label}: missing effective server profile fields {missing}")
        return
    if profile.get("server_profile") not in {"correctness", "one_b_dev", "one_b_perf"}:
        errors.append(f"{label}: invalid server_profile {profile.get('server_profile')!r}")
    if _int(profile.get("effective_io_threads"), 0) < 1:
        errors.append(f"{label}: effective_io_threads must be >= 1")
    if _int(profile.get("requested_io_threads"), 0) >= 6 and profile.get("io_threads_auto") is not True:
        errors.append(f"{label}: explicit io_threads >= 6 without auto is forbidden")
    if profile.get("io_thread_budget_status") not in {"PASS", "DEGRADED_WITH_REASON", "PENDING_PREFLIGHT"}:
        errors.append(f"{label}: invalid io_thread_budget_status {profile.get('io_thread_budget_status')!r}")
    if profile.get("log_format") not in {"text", "json"}:
        errors.append(f"{label}: invalid log_format {profile.get('log_format')!r}")


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{label}: invalid JSON: {exc}")
        return {}
    if not isinstance(obj, dict):
        errors.append(f"{label}: must be a JSON object")
        return {}
    return obj


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
