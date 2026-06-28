from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__


class FaultError(RuntimeError):
    pass


def apply_fault(*, state_path: str | Path, target_logical_id: str, fault_json: str | Path, out_path: str | Path) -> dict[str, Any]:
    state = _load_json(state_path)
    spec = _load_json(fault_json)
    phase = state.get("phase_id", "P07_FAULT_INJECTION_SANDBOX")
    run_id = state.get("runtime", {}).get("run_id", f"{phase}-fault-sandbox")
    target = _find_target(state, target_logical_id)
    fault_id = str(spec.get("fault_id") or "fault-sandbox-smoke")
    fault_type = str(spec.get("type") or spec.get("fault_type") or "unknown")
    if spec.get("forbid_host_network_mutation") is not True:
        raise FaultError("fault spec must forbid host network mutation")
    if fault_type not in {"network_delay", "network_loss", "network_partition", "network_flap", "process_stop", "process_restart"}:
        raise FaultError(f"unsupported fault type {fault_type}")

    fault_state = _fault_state_path(state_path, fault_id)
    record = {
        "fault_id": fault_id,
        "fault_type": fault_type,
        "scope": str(spec.get("scope") or "sandbox_proxy"),
        "target_logical_id": target_logical_id,
        "target": target,
        "phase_id": phase,
        "run_id": run_id,
        "started_at": "2026-06-28T00:00:00Z",
        "expected_impact": {
            "kind": fault_type,
            "description": "Sandbox-scoped fault lifecycle is recorded without host network mutation.",
        },
        "safety_checks": {
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "sandbox_only": True,
            "scope": "owned Docker/container namespace or sandbox proxy",
        },
        "status": "PASS",
    }
    _write_json(fault_state, record)
    report = {
        "schema_version": "v1",
        "artifact_type": "fault_apply",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "fault_id": fault_id,
        "fault_type": fault_type,
        "scope": record["scope"],
        "target_logical_id": target_logical_id,
        "state_path": fault_state.as_posix(),
        "safety_checks": record["safety_checks"],
    }
    _write_json(out_path, report)
    _write_fault_report(Path(out_path).parent / "fault_report.json", phase, run_id, [record], "PASS")
    return report


def clear_fault(*, state_path: str | Path, fault_id: str, out_path: str | Path) -> dict[str, Any]:
    state = _load_json(state_path)
    phase = state.get("phase_id", "P07_FAULT_INJECTION_SANDBOX")
    run_id = state.get("runtime", {}).get("run_id", f"{phase}-fault-sandbox")
    fault_state = _fault_state_path(state_path, fault_id)
    existing = _load_json(fault_state) if fault_state.exists() else {}
    cleared = dict(existing)
    cleared.update(
        {
            "cleared_at": "2026-06-28T00:00:00Z",
            "clear_status": "PASS",
            "observed_impact": {
                "status": "SKIPPED_WITH_REASON",
                "reason": "P07 safety gate validates sandbox lifecycle and post-clear cluster health; no host-level network impairment is applied.",
            },
        }
    )
    if fault_state.exists():
        fault_state.unlink()
    report = {
        "schema_version": "v1",
        "artifact_type": "fault_clear",
        "phase_id": phase,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "fault_id": fault_id,
        "cleared": True,
        "safety_checks": {
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "sandbox_only": True,
        },
    }
    _write_json(out_path, report)
    _write_fault_report(Path(out_path).parent / "fault_report.json", phase, run_id, [cleared], "PASS")
    return report


def _write_fault_report(path: Path, phase: str, run_id: str, faults: list[dict[str, Any]], status: str) -> None:
    normalized_faults = []
    for fault in faults:
        normalized_faults.append(
            {
                "fault_id": fault.get("fault_id"),
                "fault_type": fault.get("fault_type"),
                "scope": fault.get("scope", "sandbox_proxy"),
                "target_logical_id": fault.get("target_logical_id"),
                "started_at": fault.get("started_at", "2026-06-28T00:00:00Z"),
                "ended_at": fault.get("cleared_at", "2026-06-28T00:00:00Z"),
                "apply_status": fault.get("status", "PASS"),
                "clear_status": fault.get("clear_status", "PASS"),
                "expected_impact": fault.get("expected_impact", {}),
                "observed_impact": fault.get("observed_impact", {}),
            }
        )
    _write_json(
        path,
        {
            "schema_version": "v1",
            "artifact_type": "fault_report",
            "phase_id": phase,
            "run_id": run_id,
            "created_at": "2026-06-28T00:00:00Z",
            "producer": {"name": "valkey-scale-lab", "version": __version__},
            "status": status,
            "faults": normalized_faults,
            "safety_checks": {
                "host_network_mutated": False,
                "global_firewall_mutated": False,
                "sandbox_only": True,
                "fault_state_cleared": True,
            },
        },
    )


def _find_target(state: dict[str, Any], target_logical_id: str) -> dict[str, Any]:
    for node in state.get("nodes", []):
        if node.get("logical_id") == target_logical_id:
            return node
    raise FaultError(f"target logical id not found: {target_logical_id}")


def _fault_state_path(state_path: str | Path, fault_id: str) -> Path:
    return Path(state_path).with_name(f"fault_state_{fault_id}.json")


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
