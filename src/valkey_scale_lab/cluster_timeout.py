from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_CLUSTER_NODE_TIMEOUT_MS = 30000
DEFAULT_CLUSTER_NODE_TIMEOUT_MATRIX_MS = [5000, 10000, 15000, 30000, 60000]
MIN_CLUSTER_NODE_TIMEOUT_MS = 100
MAX_CLUSTER_NODE_TIMEOUT_MS = 600000
EXPLICIT_TIMEOUT_SOURCES = {"global", "profile", "scenario", "cli"}


def selected_timeout_profile(raw: dict[str, Any] | None, cli_overrides: dict[str, Any] | None = None) -> str | None:
    cli_cluster = _obj(cli_overrides or {}, "cluster")
    raw_cluster = _obj(raw or {}, "cluster")
    value = cli_cluster.get("cluster_node_timeout_profile", raw_cluster.get("cluster_node_timeout_profile"))
    return str(value) if value not in {None, ""} else None


def profile_timeout_overlay(config: dict[str, Any], profile_name: str | None) -> dict[str, Any]:
    if not profile_name:
        return {}
    profiles = _obj(config, "profiles")
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        return {}
    overlay: dict[str, Any] = {"cluster": {"cluster_node_timeout_profile": profile_name}}
    if "cluster_node_timeout_ms" in profile:
        overlay["cluster"]["cluster_node_timeout_ms"] = profile["cluster_node_timeout_ms"]
    if "allow_override" in profile:
        overlay["cluster"]["cluster_node_timeout_allow_override"] = bool(profile["allow_override"])
    return overlay


def compute_cluster_timeout_source(
    *,
    raw: dict[str, Any],
    global_config: dict[str, Any],
    cli_overrides: dict[str, Any] | None,
    profile_name: str | None,
) -> str:
    if "cluster_node_timeout_ms" in _obj(cli_overrides or {}, "cluster"):
        return "cli"
    if "cluster_node_timeout_ms" in _obj(raw, "cluster"):
        return "scenario"
    profile = _obj(global_config, "profiles").get(profile_name) if profile_name else None
    if isinstance(profile, dict) and "cluster_node_timeout_ms" in profile:
        return "profile"
    return "global"


def normalize_cluster_timeout_config(
    config: dict[str, Any],
    *,
    source: str,
    profile_name: str | None,
) -> dict[str, Any]:
    cluster = config.setdefault("cluster", {})
    fault = config.setdefault("fault", {})
    cluster.setdefault("cluster_node_timeout_ms", DEFAULT_CLUSTER_NODE_TIMEOUT_MS)
    fault.setdefault("cluster_node_timeout_matrix_ms", list(DEFAULT_CLUSTER_NODE_TIMEOUT_MATRIX_MS))
    effective = compute_effective_cluster_timeout(config, source=source, profile_name=profile_name)
    config["_effective_cluster_timeout"] = effective
    return config


def compute_effective_cluster_timeout(
    config: dict[str, Any],
    *,
    source: str | None = None,
    profile_name: str | None = None,
) -> dict[str, Any]:
    existing = config.get("_effective_cluster_timeout")
    if isinstance(existing, dict) and source is None and profile_name is None:
        return deepcopy(existing)
    cluster = _obj(config, "cluster")
    fault = _obj(config, "fault")
    profiles = _obj(config, "profiles")
    selected_profile = profile_name or cluster.get("cluster_node_timeout_profile")
    selected_profile_obj = profiles.get(selected_profile) if selected_profile else None
    selected_profile_obj = selected_profile_obj if isinstance(selected_profile_obj, dict) else {}
    requested = _positive_timeout(cluster.get("cluster_node_timeout_ms"), DEFAULT_CLUSTER_NODE_TIMEOUT_MS)
    matrix = normalize_timeout_matrix(fault.get("cluster_node_timeout_matrix_ms", DEFAULT_CLUSTER_NODE_TIMEOUT_MATRIX_MS))
    src = source or str(cluster.get("cluster_node_timeout_source") or "global")
    return {
        "schema_version": "v1",
        "artifact_type": "effective_cluster_timeout",
        "requested_cluster_node_timeout_ms": requested,
        "effective_cluster_node_timeout_ms": requested,
        "cluster_node_timeout_source": src,
        "source": src,
        "cluster_node_timeout_profile": selected_profile or "MISSING",
        "cluster_node_timeout_allow_override": bool(cluster.get("cluster_node_timeout_allow_override", selected_profile_obj.get("allow_override", False))),
        "cluster_node_timeout_matrix_ms": matrix,
        "merge_order": ["built-in defaults", "global config", "selected profile", "scenario config", "CLI override"],
    }


def cluster_timeout_node_fields(timeout: dict[str, Any]) -> dict[str, Any]:
    effective = int(timeout["effective_cluster_node_timeout_ms"])
    requested = int(timeout["requested_cluster_node_timeout_ms"])
    source = str(timeout["cluster_node_timeout_source"])
    profile = str(timeout.get("cluster_node_timeout_profile", "MISSING"))
    return {
        "cluster_node_timeout": str(effective),
        "cluster_node_timeout_ms": effective,
        "requested_cluster_node_timeout_ms": requested,
        "effective_cluster_node_timeout_ms": effective,
        "cluster_node_timeout_source": source,
        "cluster_node_timeout_profile": profile,
    }


def valkey_cluster_timeout_config_lines(timeout: dict[str, Any]) -> list[str]:
    effective = int(timeout["effective_cluster_node_timeout_ms"])
    source = str(timeout["cluster_node_timeout_source"])
    requested = int(timeout["requested_cluster_node_timeout_ms"])
    profile = str(timeout.get("cluster_node_timeout_profile", "MISSING"))
    return [
        f"# vslab cluster-node-timeout-source source={source} requested={requested} effective={effective} profile={profile}",
        f"cluster-node-timeout {effective}",
    ]


def validate_cluster_timeout_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    cluster = _obj(config, "cluster")
    fault = _obj(config, "fault")
    profiles = _obj(config, "profiles")
    _validate_timeout_value(cluster.get("cluster_node_timeout_ms"), "cluster.cluster_node_timeout_ms", errors)
    profile_name = cluster.get("cluster_node_timeout_profile")
    if profile_name not in {None, "", "MISSING"}:
        if str(profile_name) not in profiles:
            errors.append(_err("CLUSTER_NODE_TIMEOUT_PROFILE", f"cluster.cluster_node_timeout_profile {profile_name!r} is not defined in profiles"))
        else:
            profile = profiles[str(profile_name)]
            if isinstance(profile, dict) and "cluster_node_timeout_ms" in profile:
                _validate_timeout_value(profile.get("cluster_node_timeout_ms"), f"profiles.{profile_name}.cluster_node_timeout_ms", errors)
    for name, profile in profiles.items():
        if isinstance(profile, dict) and "cluster_node_timeout_ms" in profile:
            _validate_timeout_value(profile.get("cluster_node_timeout_ms"), f"profiles.{name}.cluster_node_timeout_ms", errors)
        if isinstance(profile, dict) and "allow_override" in profile and not isinstance(profile.get("allow_override"), bool):
            errors.append(_err("CLUSTER_NODE_TIMEOUT_PROFILE_ALLOW_OVERRIDE", f"profiles.{name}.allow_override must be boolean"))
    matrix = fault.get("cluster_node_timeout_matrix_ms")
    if not isinstance(matrix, list) or not matrix:
        errors.append(_err("CLUSTER_NODE_TIMEOUT_MATRIX", "fault.cluster_node_timeout_matrix_ms must be a non-empty list"))
    else:
        normalized: list[int] = []
        for idx, value in enumerate(matrix):
            _validate_timeout_value(value, f"fault.cluster_node_timeout_matrix_ms[{idx}]", errors)
            if isinstance(value, int) and not isinstance(value, bool):
                normalized.append(value)
        if len(normalized) != len(set(normalized)):
            errors.append(_err("CLUSTER_NODE_TIMEOUT_MATRIX_DUPLICATE", "fault.cluster_node_timeout_matrix_ms values must be unique"))
    effective = config.get("_effective_cluster_timeout", {})
    source = effective.get("cluster_node_timeout_source") if isinstance(effective, dict) else None
    effective_ms = effective.get("effective_cluster_node_timeout_ms") if isinstance(effective, dict) else None
    if source not in EXPLICIT_TIMEOUT_SOURCES:
        errors.append(_err("CLUSTER_NODE_TIMEOUT_SOURCE", "cluster-node-timeout source must be global, profile, scenario, or cli"))
    if effective_ms != DEFAULT_CLUSTER_NODE_TIMEOUT_MS and source == "global":
        errors.append(
            _err(
                "CLUSTER_NODE_TIMEOUT_GLOBAL_NON_DEFAULT",
                "non-30000 cluster-node-timeout requires explicit profile, scenario, or cli source",
            )
        )
    return errors


def normalize_timeout_matrix(value: Any) -> list[int]:
    if not isinstance(value, list):
        return list(DEFAULT_CLUSTER_NODE_TIMEOUT_MATRIX_MS)
    return [_positive_timeout(item, DEFAULT_CLUSTER_NODE_TIMEOUT_MS) for item in value]


def _validate_timeout_value(value: Any, field: str, errors: list[dict[str, Any]]) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(_err("CLUSTER_NODE_TIMEOUT_VALUE", f"{field} must be an integer"))
        return
    if value < MIN_CLUSTER_NODE_TIMEOUT_MS or value > MAX_CLUSTER_NODE_TIMEOUT_MS:
        errors.append(
            _err(
                "CLUSTER_NODE_TIMEOUT_VALUE",
                f"{field} must be between {MIN_CLUSTER_NODE_TIMEOUT_MS} and {MAX_CLUSTER_NODE_TIMEOUT_MS} milliseconds",
            )
        )


def _positive_timeout(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return int(default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return parsed


def _obj(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key, {})
    return value if isinstance(value, dict) else {}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}
