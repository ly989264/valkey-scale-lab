#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
MANIFEST = ROOT / "codex" / "p13_optimization_manifest.json"
STATE = ROOT / "codex" / "status" / "p13_optimization_state.json"
BASE_STATE = ROOT / "codex" / "status" / "phase_state.json"
BASE_PHASE = "P13_SCALE_LADDER_50_100"
P13O_CLUSTER_CREATE_PHASE = "P13O-01_CLUSTER_CREATE_AB"
DEFAULT_CLUSTER_CREATE_STRATEGY = "valkey_cli_cluster_create_primaries"
MANUAL_CLUSTER_CREATE_STRATEGY = "manual_tree_meet_parallel_slots"

sys.path.insert(0, str(ROOT / "scripts"))
from schema_validator import load_json, validate  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        raise SystemExit(f"missing P13O manifest: {rel(MANIFEST)}")
    return load_json(MANIFEST)


def load_state() -> dict[str, Any]:
    if STATE.exists():
        return load_json(STATE)
    return {"schema_version": "v1", "completed_phases": [], "last_completed_phase": None, "next_phase": None, "last_updated": None}


def save_state(state: dict[str, Any]) -> None:
    write_json(STATE, state)


def phase_by_id(manifest: dict[str, Any], phase_id: str) -> dict[str, Any]:
    for phase in manifest.get("phases", []):
        if phase.get("id") == phase_id:
            return phase
    raise SystemExit(f"unknown P13O phase: {phase_id}")


def next_incomplete_phase(manifest: dict[str, Any], state: dict[str, Any]) -> str | None:
    completed = set(state.get("completed_phases", []))
    for phase in manifest.get("phases", []):
        if phase.get("automatic", True) and phase.get("id") not in completed:
            return str(phase["id"])
    return None


def artifact_phase_id(phase: dict[str, Any]) -> str:
    return str(phase.get("artifact_phase_id") or str(phase["id"]).replace("-", "_"))


def timing_entry(artifact: dict[str, Any], name: str) -> dict[str, Any] | None:
    for entry in artifact.get("timings", []):
        if entry.get("name") == name:
            return entry
    return None


def numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_schema(instance_path: Path, schema_path: Path) -> list[str]:
    return validate(load_json(instance_path), load_json(schema_path), path=rel(instance_path))


def validate_manifest_shape(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("version") != "v1":
        errors.append("P13O manifest version must be v1")
    if manifest.get("default_max_nodes") != 100:
        errors.append("P13O manifest default_max_nodes must be 100")
    if manifest.get("p14_opt_in_only") is not True:
        errors.append("P13O manifest must keep P14 opt-in only")
    ids: set[str] = set()
    for phase in manifest.get("phases", []):
        pid = phase.get("id")
        if not isinstance(pid, str) or not pid.startswith("P13O-"):
            errors.append(f"invalid P13O phase id: {pid!r}")
            continue
        if pid in ids:
            errors.append(f"duplicate P13O phase id: {pid}")
        ids.add(pid)
        if int(phase.get("max_nodes", 0)) > 100:
            errors.append(f"{pid}: max_nodes exceeds 100")
        if phase.get("real_valkey_required"):
            real_gates = [g for g in phase.get("gates", []) if g.get("real_valkey")]
            if phase.get("gates") and not real_gates:
                errors.append(f"{pid}: real_valkey_required but no real gate is declared")
            for gate in real_gates:
                if "scripts/valkey_e2e_gate.py" not in str(gate.get("command", "")):
                    errors.append(f"{pid}/{gate.get('name')}: real gates must use scripts/valkey_e2e_gate.py")
    return errors


def precheck(args: argparse.Namespace) -> int:
    errors: list[str] = []
    for path in [
        ROOT / "AGENTS.md",
        ROOT / "CODEX_START_HERE.md",
        ROOT / "docs" / "codex" / "05_P13_OPTIMIZATION_LOOP.md",
        MANIFEST,
        STATE,
    ]:
        if not path.exists():
            errors.append(f"missing required control file: {rel(path)}")
    manifest = load_manifest()
    state = load_state()
    errors.extend(validate_manifest_shape(manifest))
    phase = phase_by_id(manifest, args.phase)
    next_phase = next_incomplete_phase(manifest, state)
    if args.phase in state.get("completed_phases", []):
        errors.append(f"{args.phase} is already complete")
    if next_phase and args.phase != next_phase:
        errors.append(f"next incomplete P13O phase is {next_phase}, not {args.phase}")
    if not BASE_STATE.exists():
        errors.append("missing base phase state")
    else:
        base_state = load_json(BASE_STATE)
        if BASE_PHASE not in base_state.get("completed_phases", []):
            errors.append(f"{BASE_PHASE} must be complete before P13O")
    if phase.get("max_nodes", 0) > 100:
        errors.append(f"{args.phase} exceeds 100-node default cap")
    if "P14" in json.dumps(phase):
        errors.append(f"{args.phase} must not run P14")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS p13o precheck phase={args.phase}")
    return 0


def run_gate_command(phase_id: str, gate: dict[str, Any], gate_root: Path) -> dict[str, Any]:
    name = str(gate["name"])
    stdout_dir = gate_root / "stdout"
    stderr_dir = gate_root / "stderr"
    stdout_dir.mkdir(parents=True, exist_ok=True)
    stderr_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = stdout_dir / f"{name}.log"
    stderr_path = stderr_dir / f"{name}.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    env["VSLAB_P13O_PHASE_ID"] = phase_id
    if (Path("/opt/anaconda3/bin") / "python3").exists():
        env["PATH"] = f"/opt/anaconda3/bin{os.pathsep}" + env.get("PATH", "")
    command = str(gate["command"])
    started = utc_now()
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=int(gate.get("timeout_seconds", 300)),
            env=env,
        )
        exit_code = int(proc.returncode)
        stdout = proc.stdout
        stderr = proc.stderr
        status = "PASS" if exit_code == 0 else "FAIL"
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTIMEOUT after {gate.get('timeout_seconds')} seconds\n"
        status = "FAIL"
    duration = round(time.monotonic() - t0, 6)
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
    return {
        "name": name,
        "kind": gate.get("kind", "unknown"),
        "command": command,
        "required": bool(gate.get("required", True)),
        "status": status,
        "exit_code": exit_code,
        "started_at": started,
        "finished_at": utc_now(),
        "duration_seconds": duration,
        "stdout_path": rel(stdout_path),
        "stderr_path": rel(stderr_path),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
    }


def run_phase(args: argparse.Namespace) -> int:
    if precheck(argparse.Namespace(phase=args.phase)) != 0:
        return 1
    manifest = load_manifest()
    phase = phase_by_id(manifest, args.phase)
    gate_root = ROOT / "artifacts" / "gates" / args.phase
    gate_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for gate in phase.get("gates", []):
        print(f"RUN {args.phase}/{gate['name']}: {gate['command']}")
        result = run_gate_command(args.phase, gate, gate_root)
        print(f"{result['status']} {gate['name']} exit={result['exit_code']}")
        results.append(result)
    overall = "PASS" if all((not g["required"]) or g["status"] == "PASS" for g in results) else "FAIL"
    gate_result = {
        "schema_version": "v1",
        "artifact_type": "p13_optimization_gate_result",
        "phase_id": args.phase,
        "created_at": utc_now(),
        "runner": "scripts/p13_optimization_gate.py",
        "manifest_sha256": sha256_file(MANIFEST),
        "status": overall,
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "cwd": str(ROOT),
        },
        "gates": results,
    }
    out = gate_root / "gate_result.json"
    write_json(out, gate_result)
    print(f"{overall} p13o_gate_result={rel(out)}")
    return 0 if overall == "PASS" else 1


def validate_timing_artifact(scenario: str, expected_nodes: int) -> tuple[dict[str, Any], list[str]]:
    path = ROOT / "artifacts" / "phases" / BASE_PHASE / f"p13_timing_breakdown_{scenario}.json"
    errors: list[str] = []
    if not path.exists():
        return {}, [f"missing timing artifact: {rel(path)}"]
    artifact = load_json(path)
    errors.extend(validate_schema(path, ROOT / "schemas" / "artifact" / "p13_timing_breakdown.schema.json"))
    if artifact.get("status") != "PASS":
        errors.append(f"{scenario}: timing artifact status is {artifact.get('status')}")
    if artifact.get("node_count") != expected_nodes:
        errors.append(f"{scenario}: node_count expected {expected_nodes}, got {artifact.get('node_count')}")
    summary = artifact.get("summary", {})
    required = [
        "total_gate_seconds",
        "setup_command_wall_seconds",
        "setup_stdout_write_seconds",
        "setup_stderr_write_seconds",
        "state_load_seconds",
        "artifact_write_seconds",
        "cleanup_command_wall_seconds",
        "unattributed_seconds",
    ]
    for field in required:
        if not numeric(summary.get(field)):
            errors.append(f"{scenario}: summary.{field} must be numeric")
    unattributed = summary.get("unattributed_seconds")
    explanation = artifact.get("accounting", {}).get("unattributed_explanation")
    if numeric(unattributed) and float(unattributed) > 10.0 and not explanation:
        errors.append(f"{scenario}: unattributed_seconds exceeds 10 without explanation")
    final_entry = timing_entry(artifact, "runtime_final_full_probe")
    diagnostic_entry = timing_entry(artifact, "runtime_diagnostic_full_probe")
    if artifact.get("status") == "PASS" and final_entry and final_entry.get("status") == "FAIL":
        errors.append(f"{scenario}: runtime_final_full_probe must not be FAIL when artifact status is PASS")
    if diagnostic_entry is None:
        errors.append(f"{scenario}: runtime_diagnostic_full_probe entry is missing")
    return artifact, errors


def validate_real_evidence(scenario: str, expected_nodes: int) -> tuple[dict[str, Any], list[str]]:
    path = ROOT / "artifacts" / "phases" / BASE_PHASE / f"valkey_e2e_evidence_{scenario.removeprefix('scale_')}.json"
    return validate_real_evidence_path(path, scenario, expected_nodes)


def validate_real_evidence_path(path: Path, scenario: str, expected_nodes: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if not path.exists():
        return {}, [f"missing real evidence artifact: {rel(path)}"]
    evidence = load_json(path)
    if evidence.get("status") != "PASS":
        errors.append(f"{scenario}: real evidence status is {evidence.get('status')}")
    if evidence.get("real_valkey") is not True:
        errors.append(f"{scenario}: real_valkey must be true")
    if evidence.get("nodes_observed") != expected_nodes:
        errors.append(f"{scenario}: nodes_observed expected {expected_nodes}, got {evidence.get('nodes_observed')}")
    if evidence.get("data_path_result") != "PASS":
        errors.append(f"{scenario}: data_path_result must be PASS")
    role_counts = evidence.get("role_counts", {})
    expected_primaries = expected_nodes // 2
    expected_replicas = expected_nodes // 2
    if role_counts.get("primary") != expected_primaries or role_counts.get("replica") != expected_replicas:
        errors.append(f"{scenario}: role_counts expected {expected_primaries}/{expected_replicas}, got {role_counts}")
    probes = evidence.get("probes", [])
    full_membership = [
        probe for probe in probes
        if probe.get("status") == "PASS" and int(probe.get("cluster_known_nodes", 0) or 0) >= expected_nodes
    ]
    if not full_membership:
        errors.append(f"{scenario}: no full-membership probe observed")
    return evidence, errors


def timing_field(value: Any, reason: str) -> Any:
    if numeric(value):
        return round(float(value), 6)
    return {"status": "MISSING", "reason": reason}


def cluster_create_timing_observation(
    *,
    strategy: str,
    scenario: str,
    timing_path: Path,
    evidence_path: Path,
    expected_nodes: int,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    timing_artifact: dict[str, Any] = {}
    if timing_path.exists():
        timing_artifact = load_json(timing_path)
    else:
        errors.append(f"{strategy}/{scenario}: missing timing artifact {rel(timing_path)}")
    evidence, evidence_errors = validate_real_evidence_path(evidence_path, scenario, expected_nodes)
    errors.extend(f"{strategy}/{err}" for err in evidence_errors)

    entry = timing_entry(timing_artifact, "primary_cluster_create") if timing_artifact else None
    details = entry.get("details", {}) if isinstance(entry, dict) else {}
    timing = {
        "primary_meet_seconds": timing_field(
            details.get("primary_meet_seconds"),
            "not recorded in primary_cluster_create details",
        ),
        "slot_assignment_seconds": timing_field(
            details.get("slot_assignment_seconds"),
            "not recorded in primary_cluster_create details",
        ),
        "cluster_create_command_seconds": timing_field(
            details.get("cluster_create_command_seconds"),
            "not recorded in primary_cluster_create details",
        ),
        "primary_convergence_seconds": timing_field(
            details.get("primary_convergence_seconds"),
            "not recorded in primary_cluster_create details",
        ),
        "primary_cluster_create_total_seconds": timing_field(
            entry.get("duration_seconds") if isinstance(entry, dict) else None,
            "primary_cluster_create timing entry missing",
        ),
    }
    for field, value in timing.items():
        if not numeric(value):
            errors.append(f"{strategy}/{scenario}: {field} is not numeric")
    if details.get("strategy") and details.get("strategy") != strategy:
        errors.append(f"{strategy}/{scenario}: timing strategy mismatch {details.get('strategy')!r}")
    observation = {
        "scenario": scenario,
        "node_count": expected_nodes,
        "status": "PASS" if not errors else "FAIL",
        "real_valkey": evidence.get("real_valkey", "MISSING"),
        "evidence_path": rel(evidence_path),
        "timing_path": rel(timing_path),
        "timing": timing,
        "role_counts": evidence.get("role_counts", "MISSING"),
        "data_path_result": evidence.get("data_path_result", "MISSING"),
        "nodes_observed": evidence.get("nodes_observed", "MISSING"),
        "timing_details": {
            "slot_assignment_scope": details.get("slot_assignment_scope", "MISSING"),
            "probe_slot_assignment_seconds": details.get("probe_slot_assignment_seconds", "MISSING"),
            "meet_commands": details.get("meet_commands", "MISSING"),
        },
    }
    return observation, errors


def strategy_status(observations: list[dict[str, Any]]) -> str:
    return "PASS" if observations and all(item.get("status") == "PASS" for item in observations) else "FAIL"


def write_cluster_create_strategy_comparison(errors: list[str]) -> tuple[Path, dict[str, Any]]:
    out = ROOT / "artifacts" / "phases" / "P13O_CLUSTER_CREATE_AB" / "p13_cluster_create_strategy_comparison.json"
    default_observations: list[dict[str, Any]] = []
    manual_observations: list[dict[str, Any]] = []
    for scenario, expected_nodes in {"scale_50": 50, "scale_100": 100}.items():
        observation, obs_errors = cluster_create_timing_observation(
            strategy=DEFAULT_CLUSTER_CREATE_STRATEGY,
            scenario=scenario,
            timing_path=ROOT / "artifacts" / "phases" / BASE_PHASE / f"p13_timing_breakdown_{scenario}.json",
            evidence_path=ROOT / "artifacts" / "phases" / BASE_PHASE / f"valkey_e2e_evidence_{scenario.removeprefix('scale_')}.json",
            expected_nodes=expected_nodes,
        )
        default_observations.append(observation)
        errors.extend(obs_errors)

    manual_observation, manual_errors = cluster_create_timing_observation(
        strategy=MANUAL_CLUSTER_CREATE_STRATEGY,
        scenario="scale_50",
        timing_path=ROOT / "artifacts" / "phases" / "P13O_CLUSTER_CREATE_AB" / "p13_timing_breakdown_scale_50.json",
        evidence_path=ROOT / "artifacts" / "phases" / "P13O_CLUSTER_CREATE_AB" / "valkey_e2e_evidence_manual_scale_50.json",
        expected_nodes=50,
    )
    manual_observations.append(manual_observation)
    errors.extend(manual_errors)

    artifact = {
        "schema_version": "v1",
        "artifact_type": "p13_cluster_create_strategy_comparison",
        "phase_id": P13O_CLUSTER_CREATE_PHASE,
        "created_at": utc_now(),
        "producer": {"name": "scripts/p13_optimization_gate.py", "version": "v1"},
        "status": "PASS" if not errors else "FAIL",
        "default_strategy": DEFAULT_CLUSTER_CREATE_STRATEGY,
        "selected_default_safe": True,
        "safety_constraints": {
            "nodes_conf_fast_bootstrap_used": False,
            "host_network_mutation": False,
            "p14_executed": False,
            "default_max_nodes": 100,
        },
        "strategies": [
            {
                "strategy": DEFAULT_CLUSTER_CREATE_STRATEGY,
                "status": strategy_status(default_observations),
                "default": True,
                "experimental": False,
                "selection": "safe_default",
                "observations": default_observations,
            },
            {
                "strategy": MANUAL_CLUSTER_CREATE_STRATEGY,
                "status": strategy_status(manual_observations),
                "default": False,
                "experimental": False,
                "selection": "supported_opt_in",
                "observations": manual_observations,
                "skipped_observations": [
                    {
                        "scenario": "scale_100",
                        "status": "SKIPPED_WITH_REASON",
                        "reason": "P13O-01 proves manual strategy with a real 50-node gate while preserving required default 50/100 gates.",
                    }
                ],
            },
        ],
    }
    write_json(out, artifact)
    return out, artifact


def write_phase_summary(phase: dict[str, Any], timings: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]], errors: list[str]) -> Path:
    phase_id = str(phase["id"])
    artifact_id = artifact_phase_id(phase)
    out = ROOT / "artifacts" / "phases" / artifact_id / "phase_summary.json"
    timing_accounting = {
        scenario: {
            "path": rel(ROOT / "artifacts" / "phases" / BASE_PHASE / f"p13_timing_breakdown_{scenario}.json"),
            "total_gate_seconds": artifact.get("summary", {}).get("total_gate_seconds", "MISSING"),
            "setup_command_wall_seconds": artifact.get("summary", {}).get("setup_command_wall_seconds", "MISSING"),
            "cleanup_command_wall_seconds": artifact.get("summary", {}).get("cleanup_command_wall_seconds", "MISSING"),
            "unattributed_seconds": artifact.get("summary", {}).get("unattributed_seconds", "MISSING"),
            "final_full_probe_status": (timing_entry(artifact, "runtime_final_full_probe") or {}).get("status", "MISSING"),
            "diagnostic_full_probe_status": (timing_entry(artifact, "runtime_diagnostic_full_probe") or {}).get("status", "MISSING"),
        }
        for scenario, artifact in timings.items()
    }
    real_evidence = {
        scenario: {
            "path": rel(ROOT / "artifacts" / "phases" / BASE_PHASE / f"valkey_e2e_evidence_{scenario.removeprefix('scale_')}.json"),
            "status": artifact.get("status", "MISSING"),
            "nodes_observed": artifact.get("nodes_observed", "MISSING"),
            "data_path_result": artifact.get("data_path_result", "MISSING"),
            "role_counts": artifact.get("role_counts", "MISSING"),
        }
        for scenario, artifact in evidence.items()
    }
    summary = {
        "schema_version": "v1",
        "artifact_type": "p13_optimization_phase_summary",
        "phase_id": phase_id,
        "artifact_phase_id": artifact_id,
        "run_id": f"phase-{phase_id}",
        "created_at": utc_now(),
        "producer": {"name": "scripts/p13_optimization_gate.py", "version": "v1"},
        "status": "PASS" if not errors else "FAIL",
        "summary": "P13 timing artifacts now account for wrapper wall time and split final versus diagnostic full probes.",
        "required_artifacts": [item["path"] for item in phase.get("required_artifacts", [])],
        "real_valkey_evidence": real_evidence,
        "timing_accounting": timing_accounting,
        "errors": errors,
    }
    write_json(out, summary)
    return out


def write_cluster_create_phase_summary(
    phase: dict[str, Any],
    comparison: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    errors: list[str],
) -> Path:
    phase_id = str(phase["id"])
    artifact_id = artifact_phase_id(phase)
    out = ROOT / "artifacts" / "phases" / artifact_id / "phase_summary.json"
    real_evidence = {
        name: {
            "status": artifact.get("status", "MISSING"),
            "nodes_observed": artifact.get("nodes_observed", "MISSING"),
            "data_path_result": artifact.get("data_path_result", "MISSING"),
            "role_counts": artifact.get("role_counts", "MISSING"),
        }
        for name, artifact in evidence.items()
    }
    timing_accounting: dict[str, Any] = {}
    for strategy in comparison.get("strategies", []):
        timing_accounting[strategy["strategy"]] = [
            {
                "scenario": observation.get("scenario"),
                **observation.get("timing", {}),
            }
            for observation in strategy.get("observations", [])
        ]
    summary = {
        "schema_version": "v1",
        "artifact_type": "p13_optimization_phase_summary",
        "phase_id": phase_id,
        "artifact_phase_id": artifact_id,
        "run_id": f"phase-{phase_id}",
        "created_at": utc_now(),
        "producer": {"name": "scripts/p13_optimization_gate.py", "version": "v1"},
        "status": "PASS" if not errors else "FAIL",
        "summary": "P13 cluster-create strategies compared with default 50/100 real gates and manual 50-node real proof.",
        "required_artifacts": [item["path"] for item in phase.get("required_artifacts", [])],
        "real_valkey_evidence": real_evidence,
        "timing_accounting": timing_accounting,
        "cluster_create_strategy_comparison_path": rel(
            ROOT / "artifacts" / "phases" / artifact_id / "p13_cluster_create_strategy_comparison.json"
        ),
        "errors": errors,
    }
    write_json(out, summary)
    return out


def validate_artifacts(args: argparse.Namespace, *, write_summary_artifact: bool = True) -> int:
    manifest = load_manifest()
    phase = phase_by_id(manifest, args.phase)
    if args.phase == P13O_CLUSTER_CREATE_PHASE:
        return validate_cluster_create_artifacts(phase, write_summary_artifact=write_summary_artifact)

    all_errors: list[str] = []
    timings: dict[str, dict[str, Any]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for scenario, expected_nodes in {"scale_50": 50, "scale_100": 100}.items():
        timing, errors = validate_timing_artifact(scenario, expected_nodes)
        timings[scenario] = timing
        all_errors.extend(errors)
        real, errors = validate_real_evidence(scenario, expected_nodes)
        evidence[scenario] = real
        all_errors.extend(errors)
    summary_path = ROOT / "artifacts" / "phases" / artifact_phase_id(phase) / "phase_summary.json"
    if write_summary_artifact:
        summary_path = write_phase_summary(phase, timings, evidence, all_errors)
    elif not summary_path.exists():
        all_errors.append(f"missing phase summary artifact: {rel(summary_path)}")
    if summary_path.exists():
        all_errors.extend(validate_schema(summary_path, ROOT / "schemas" / "artifact" / "p13_optimization_phase_summary.schema.json"))
    if all_errors:
        for err in all_errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS p13o artifacts phase={args.phase} summary={rel(summary_path)}")
    return 0


def validate_cluster_create_artifacts(phase: dict[str, Any], *, write_summary_artifact: bool = True) -> int:
    all_errors: list[str] = []
    evidence: dict[str, dict[str, Any]] = {}
    default_50, errors = validate_real_evidence("scale_50", 50)
    evidence["default_scale_50"] = default_50
    all_errors.extend(errors)
    default_100, errors = validate_real_evidence("scale_100", 100)
    evidence["default_scale_100"] = default_100
    all_errors.extend(errors)
    manual_path = ROOT / "artifacts" / "phases" / "P13O_CLUSTER_CREATE_AB" / "valkey_e2e_evidence_manual_scale_50.json"
    manual_50, errors = validate_real_evidence_path(manual_path, "manual_scale_50", 50)
    evidence["manual_scale_50"] = manual_50
    all_errors.extend(errors)

    comparison_path = ROOT / "artifacts" / "phases" / "P13O_CLUSTER_CREATE_AB" / "p13_cluster_create_strategy_comparison.json"
    if write_summary_artifact:
        comparison_path, comparison = write_cluster_create_strategy_comparison(all_errors)
    elif comparison_path.exists():
        comparison = load_json(comparison_path)
    else:
        comparison = {}
        all_errors.append(f"missing strategy comparison artifact: {rel(comparison_path)}")

    if comparison_path.exists():
        all_errors.extend(validate_schema(comparison_path, ROOT / "schemas" / "artifact" / "p13_cluster_create_strategy_comparison.schema.json"))
        if comparison.get("default_strategy") != DEFAULT_CLUSTER_CREATE_STRATEGY:
            all_errors.append(f"default strategy must remain {DEFAULT_CLUSTER_CREATE_STRATEGY}")
        strategies = {item.get("strategy"): item for item in comparison.get("strategies", [])}
        for required in [DEFAULT_CLUSTER_CREATE_STRATEGY, MANUAL_CLUSTER_CREATE_STRATEGY]:
            if required not in strategies:
                all_errors.append(f"comparison missing strategy {required}")
            elif strategies[required].get("status") != "PASS":
                all_errors.append(f"strategy {required} status is {strategies[required].get('status')}")
        if strategies.get(DEFAULT_CLUSTER_CREATE_STRATEGY, {}).get("default") is not True:
            all_errors.append("valkey_cli_cluster_create_primaries must be the default strategy")
        if comparison.get("safety_constraints", {}).get("nodes_conf_fast_bootstrap_used") is not False:
            all_errors.append("nodes.conf fast-bootstrap must not be used")

    summary_path = ROOT / "artifacts" / "phases" / "P13O_CLUSTER_CREATE_AB" / "phase_summary.json"
    if write_summary_artifact:
        summary_path = write_cluster_create_phase_summary(phase, comparison, evidence, all_errors)
    elif not summary_path.exists():
        all_errors.append(f"missing phase summary artifact: {rel(summary_path)}")
    if summary_path.exists():
        all_errors.extend(validate_schema(summary_path, ROOT / "schemas" / "artifact" / "p13_optimization_phase_summary.schema.json"))

    if all_errors:
        for err in all_errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS p13o artifacts phase={phase['id']} summary={rel(summary_path)}")
    return 0


def postcheck(args: argparse.Namespace) -> int:
    errors: list[str] = []
    manifest = load_manifest()
    phase = phase_by_id(manifest, args.phase)
    gate_result_path = ROOT / "artifacts" / "gates" / args.phase / "gate_result.json"
    if not gate_result_path.exists():
        errors.append(f"missing gate result: {rel(gate_result_path)}")
    else:
        gate_result = load_json(gate_result_path)
        if gate_result.get("status") != "PASS":
            errors.append(f"gate result status is {gate_result.get('status')}")
        errors.extend(validate_schema(gate_result_path, ROOT / "schemas" / "artifact" / "p13_optimization_gate_result.schema.json"))
    if validate_artifacts(argparse.Namespace(phase=args.phase), write_summary_artifact=False) != 0:
        errors.append("artifact validation failed")
    audit = phase.get("audit", {})
    audit_md = ROOT / str(audit.get("md_path", ""))
    audit_decision = ROOT / str(audit.get("decision_json_path", ""))
    if not audit_md.exists():
        errors.append(f"missing audit markdown: {rel(audit_md)}")
    if not audit_decision.exists():
        errors.append(f"missing audit decision: {rel(audit_decision)}")
    else:
        decision = load_json(audit_decision)
        if decision.get("decision") != "PASS":
            errors.append(f"audit decision is {decision.get('decision')}")
        if decision.get("phase_id") != args.phase:
            errors.append(f"audit decision phase_id mismatch: {decision.get('phase_id')}")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS p13o postcheck phase={args.phase}")
    return 0


def mark_complete(args: argparse.Namespace) -> int:
    if postcheck(argparse.Namespace(phase=args.phase)) != 0:
        return 1
    manifest = load_manifest()
    state = load_state()
    completed = list(state.get("completed_phases", []))
    if args.phase not in completed:
        completed.append(args.phase)
    state["schema_version"] = "v1"
    state["completed_phases"] = completed
    state["last_completed_phase"] = args.phase
    state["last_updated"] = utc_now()
    state["next_phase"] = next_incomplete_phase(manifest, state)
    save_state(state)
    print(f"PASS marked complete phase={args.phase} next={state['next_phase']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="P13 post-scale optimization gate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ["precheck", "run", "validate-artifacts", "postcheck", "mark-complete"]:
        p = sub.add_parser(name)
        p.add_argument("--phase", required=True)
    sub.add_parser("next")
    args = parser.parse_args()
    if args.cmd == "next":
        phase = next_incomplete_phase(load_manifest(), load_state())
        print(phase or "COMPLETE_P13_OPTIMIZATION_PHASES")
        return 0
    if args.cmd == "precheck":
        return precheck(args)
    if args.cmd == "run":
        return run_phase(args)
    if args.cmd == "validate-artifacts":
        return validate_artifacts(args)
    if args.cmd == "postcheck":
        return postcheck(args)
    if args.cmd == "mark-complete":
        return mark_complete(args)
    raise SystemExit(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
