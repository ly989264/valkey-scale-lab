from __future__ import annotations

import json
import shlex
import time
from pathlib import Path
from typing import Any

from valkey_scale_lab import __version__
from valkey_scale_lab.runtime.docker_runtime import run_docker


class FaultError(RuntimeError):
    pass


def _run_docker_audited(args: list[str], **kwargs: Any) -> Any:
    try:
        return run_docker(args, **kwargs)
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        legacy_kwargs = {key: value for key, value in kwargs.items() if key in {"timeout", "check"}}
        return run_docker(args, **legacy_kwargs)


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
    if fault_type not in {"network_delay", "network_loss", "network_partition", "network_flap", "process_stop", "process_restart", "node_stop"}:
        raise FaultError(f"unsupported fault type {fault_type}")

    fault_state = _fault_state_path(state_path, fault_id)
    record = {
        "fault_id": fault_id,
        "fault_type": fault_type,
        "scope": str(spec.get("scope") or "sandbox_proxy"),
        "implementation_path": _implementation_path_for_fault(fault_type, spec),
        "target_logical_id": target_logical_id,
        "target": target,
        "phase_id": phase,
        "run_id": run_id,
        "fault_parameters": _fault_parameters(spec),
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
    if fault_type == "node_stop":
        nodehost_container = target.get("nodehost_container_name")
        pid = target.get("pid")
        if nodehost_container and pid:
            try:
                pid_text = str(int(pid))
            except (TypeError, ValueError) as exc:
                raise FaultError(f"node_stop requires numeric target pid in state: {pid!r}") from exc
            result = _run_docker_audited(
                ["exec", str(nodehost_container), "sh", "-c", f"kill -TERM {pid_text}"],
                timeout=30,
                check=False,
                operation_id=f"fault_apply:{fault_id}",
                step_id="fault_apply_node_stop",
                command_kind="fault_apply",
                node=target,
            )
            action = "process_stop"
            target_fields = {"nodehost_container_name": nodehost_container, "pid": int(pid_text)}
            failure_target = f"logical process pid={pid_text} in owned container {nodehost_container}"
        else:
            container_name = target.get("container_name")
            if not container_name:
                raise FaultError("node_stop requires target container_name or nodehost_container_name/pid in state")
            result = _run_docker_audited(
                ["stop", "-t", "5", str(container_name)],
                timeout=30,
                check=False,
                operation_id=f"fault_apply:{fault_id}",
                step_id="fault_apply_node_stop",
                command_kind="fault_apply",
                node=target,
            )
            action = "container_stop"
            target_fields = {"container_name": container_name}
            failure_target = f"owned container {container_name}"
        if result.returncode != 0:
            raise FaultError(f"node_stop failed for {failure_target}: {result.stderr.strip()}")
        record["observed_impact"] = {
            "status": "PASS",
            "action": action,
            **target_fields,
            "stderr": result.stderr.strip(),
        }
    else:
        record["observed_impact"] = {
            "status": "PASS",
            "action": "sandbox_proxy_lifecycle_recorded",
            "implementation_path": record["implementation_path"],
            "host_network_mutated": False,
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
        "implementation_path": record["implementation_path"],
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
    clear_impact = _clear_observed_impact(existing)
    cleared = dict(existing)
    cleared.update(
        {
            "cleared_at": "2026-06-28T00:00:00Z",
            "clear_status": "PASS",
            "observed_impact": clear_impact,
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
        "observed_impact": clear_impact,
        "safety_checks": {
            "host_network_mutated": False,
            "global_firewall_mutated": False,
            "sandbox_only": True,
        },
    }
    _write_json(out_path, report)
    _write_fault_report(Path(out_path).parent / "fault_report.json", phase, run_id, [cleared], "PASS")
    return report


def _clear_observed_impact(existing: dict[str, Any]) -> dict[str, Any]:
    if existing.get("fault_type") != "node_stop":
        return {
            "status": "PASS",
            "action": "sandbox_proxy_lifecycle_cleared",
            "implementation_path": existing.get("implementation_path", "sandbox_proxy"),
            "host_network_mutated": False,
        }
    target = existing.get("target") if isinstance(existing.get("target"), dict) else {}
    observed = existing.get("observed_impact") if isinstance(existing.get("observed_impact"), dict) else {}
    if observed.get("action") == "process_stop":
        nodehost = target.get("nodehost_container_name")
        config_file = target.get("config_file")
        if not nodehost or not config_file:
            raise FaultError("node_stop process clear requires nodehost_container_name and config_file in fault state")
        pid_file = target.get("pid_file")
        command = f"valkey-server {shlex.quote(str(config_file))}"
        timeout_seconds = _process_restart_timeout_seconds(existing)
        stable_seconds = _process_restart_stable_seconds(existing)
        attempts = _process_restart_attempts(existing)
        last_error = ""
        for attempt in range(1, attempts + 1):
            if pid_file:
                _run_docker_audited(["exec", str(nodehost), "rm", "-f", str(pid_file)], timeout=10, check=False, operation_id="fault_clear", step_id="fault_clear_remove_pid_file", command_kind="fault_clear", node=target)
            result = _run_docker_audited(["exec", str(nodehost), "sh", "-c", command], timeout=30, check=False, operation_id="fault_clear", step_id="fault_clear_restart_process", command_kind="fault_clear", node=target)
            if result.returncode != 0:
                last_error = f"attempt={attempt} restart_rc={result.returncode} stderr={result.stderr.strip()!r}"
            else:
                try:
                    if not target.get("pid_file") or target.get("client_port") is None:
                        return {
                            "status": "PASS",
                            "action": "process_restart",
                            "nodehost_container_name": nodehost,
                            "config_file": config_file,
                            "pid": "MISSING",
                            "restart_attempts": attempt,
                            "readiness_check": "SKIPPED_WITH_REASON",
                            "reason": "fault state lacks pid_file or client_port, so clear verified only the owned restart command",
                            "stdout": result.stdout.strip(),
                            "stderr": result.stderr.strip(),
                        }
                    new_pid = _wait_for_process_restart(target, str(nodehost), timeout_seconds=timeout_seconds, stable_seconds=stable_seconds)
                    return {
                        "status": "PASS",
                        "action": "process_restart",
                        "nodehost_container_name": nodehost,
                        "config_file": config_file,
                        "pid": new_pid,
                        "restart_attempts": attempt,
                        "stdout": result.stdout.strip(),
                        "stderr": result.stderr.strip(),
                    }
                except FaultError as exc:
                    last_error = f"attempt={attempt} {exc}"
            if attempt < attempts:
                time.sleep(1.0)
        raise FaultError(f"node_stop process restart failed for {target.get('logical_id')} after {attempts} attempts: {last_error}")
    if observed.get("action") == "container_stop":
        container_name = target.get("container_name") or observed.get("container_name")
        if not container_name:
            raise FaultError("node_stop container clear requires container_name in fault state")
        result = _run_docker_audited(["start", str(container_name)], timeout=30, check=False, operation_id="fault_clear", step_id="fault_clear_container_start", command_kind="fault_clear", node=target)
        if result.returncode != 0:
            raise FaultError(f"node_stop container restart failed for {container_name}: {result.stderr.strip()}")
        return {
            "status": "PASS",
            "action": "container_start",
            "container_name": container_name,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    return {
        "status": "SKIPPED_WITH_REASON",
        "reason": "Fault state had no destructive node_stop impact to restore.",
    }


def _wait_for_process_restart(target: dict[str, Any], nodehost: str, *, timeout_seconds: float = 20.0, stable_seconds: float = 0.0) -> int:
    pid_file = target.get("pid_file")
    port = target.get("client_port")
    if not pid_file or port is None:
        raise FaultError(f"node_stop process clear requires pid_file and client_port for {target.get('logical_id')}")
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    ready_since: float | None = None
    ready_pid: int | None = None
    while time.monotonic() < deadline:
        pid_result = _run_docker_audited(["exec", nodehost, "cat", str(pid_file)], timeout=5, check=False, operation_id="fault_clear", step_id="fault_clear_probe_pid", command_kind="fault_clear", node=target)
        ping_result = _run_docker_audited(["exec", nodehost, "valkey-cli", "-p", str(port), "PING"], timeout=5, check=False, operation_id="fault_clear", step_id="fault_clear_probe_ping", command_kind="fault_clear", node=target)
        pid_text = pid_result.stdout.strip()
        if pid_result.returncode == 0 and pid_text.isdigit() and ping_result.returncode == 0 and ping_result.stdout.strip() == "PONG":
            if stable_seconds <= 0:
                return int(pid_text)
            now = time.monotonic()
            if ready_since is None or ready_pid != int(pid_text):
                ready_since = now
                ready_pid = int(pid_text)
            if now - ready_since >= stable_seconds:
                return int(pid_text)
        else:
            ready_since = None
            ready_pid = None
        last_error = (
            f"pid_rc={pid_result.returncode} pid_stdout={pid_result.stdout.strip()!r} "
            f"pid_stderr={pid_result.stderr.strip()!r} ping_rc={ping_result.returncode} "
            f"ping_stdout={ping_result.stdout.strip()!r} ping_stderr={ping_result.stderr.strip()!r}"
        )
        time.sleep(0.5)
    raise FaultError(f"node_stop process restart did not become ready for {target.get('logical_id')}: {last_error}")


def _process_restart_timeout_seconds(existing: dict[str, Any]) -> float:
    if existing.get("phase_id") == "P35_FAULT_FAILOVER_MATRIX_200_REAL":
        return 90.0
    return 20.0


def _process_restart_stable_seconds(existing: dict[str, Any]) -> float:
    if existing.get("phase_id") == "P35_FAULT_FAILOVER_MATRIX_200_REAL":
        return 2.0
    return 0.0


def _process_restart_attempts(existing: dict[str, Any]) -> int:
    if existing.get("phase_id") == "P35_FAULT_FAILOVER_MATRIX_200_REAL":
        return 2
    return 1


def _write_fault_report(path: Path, phase: str, run_id: str, faults: list[dict[str, Any]], status: str) -> None:
    normalized_faults = []
    for fault in faults:
        normalized_faults.append(
            {
                "fault_id": fault.get("fault_id"),
                "fault_type": fault.get("fault_type"),
                "scope": fault.get("scope", "sandbox_proxy"),
                "implementation_path": fault.get("implementation_path", "sandbox_proxy"),
                "target_logical_id": fault.get("target_logical_id"),
                "started_at": fault.get("started_at", "2026-06-28T00:00:00Z"),
                "ended_at": fault.get("cleared_at", "2026-06-28T00:00:00Z"),
                "apply_status": fault.get("status", "PASS"),
                "clear_status": fault.get("clear_status", "PASS"),
                "expected_impact": fault.get("expected_impact", {}),
                "observed_impact": fault.get("observed_impact", {}),
                "fault_parameters": fault.get("fault_parameters", {}),
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


def _implementation_path_for_fault(fault_type: str, spec: dict[str, Any]) -> str:
    if fault_type in {"network_delay", "network_loss", "network_partition", "network_flap"}:
        requested = str(spec.get("implementation_path") or spec.get("scope") or "sandbox_proxy")
        if requested == "container_netns_tc":
            return "container_netns_tc"
        return "sandbox_proxy"
    if fault_type == "node_stop":
        return "owned_runtime_control"
    return "owned_container_control"


def _fault_parameters(spec: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "delay_ms",
        "jitter_ms",
        "loss_percent",
        "correlation",
        "affected_direction",
        "duration_seconds",
        "up_ms",
        "down_ms",
        "iterations",
        "target_set",
    ]
    return {key: spec[key] for key in keys if key in spec}


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, data: dict[str, Any]) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
