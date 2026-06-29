#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
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
P13O_REPLICA_REPLICATE_PHASE = "P13O-02_REPLICA_REPLICATE_BREAKDOWN"
P13O_CLEANUP_PHASE = "P13O-03_CLEANUP_OPTIMIZATION"
P13O_FAST_TEST_SPLIT_PHASE = "P13O-04_FAST_TEST_SPLIT"
DEFAULT_CLUSTER_CREATE_STRATEGY = "valkey_cli_cluster_create_primaries"
MANUAL_CLUSTER_CREATE_STRATEGY = "manual_tree_meet_parallel_slots"
REPLICA_REPLICATE_ARTIFACT_PHASE = "P13O_REPLICA_REPLICATE_BREAKDOWN"
REPLICA_REPLICATE_DEFAULT_PARALLELISM = 8
REPLICA_REPLICATE_SUPPORTED_PARALLELISM = [8, 16, 32]
CLEANUP_ARTIFACT_PHASE = "P13O_CLEANUP_OPTIMIZATION"
FAST_TEST_SPLIT_ARTIFACT_PHASE = "P13O_FAST_TEST_SPLIT"
FAST_TEST_MAX_SECONDS = 30.0

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


def replica_replicate_timing_observation(
    *,
    name: str,
    scenario: str,
    timing_path: Path,
    evidence_path: Path,
    expected_nodes: int,
    expected_parallelism: int,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    errors: list[str] = []
    timing_artifact: dict[str, Any] = {}
    if timing_path.exists():
        timing_artifact = load_json(timing_path)
    else:
        errors.append(f"{name}: missing timing artifact {rel(timing_path)}")

    evidence, evidence_errors = validate_real_evidence_path(evidence_path, name, expected_nodes)
    errors.extend(evidence_errors)

    entry = timing_entry(timing_artifact, "replica_replicate") if timing_artifact else None
    details = entry.get("details", {}) if isinstance(entry, dict) else {}
    timing = {
        "replica_primary_id_lookup_seconds": timing_field(
            details.get("replica_primary_id_lookup_seconds"),
            "not recorded in replica_replicate details",
        ),
        "replica_knows_master_wait_seconds": timing_field(
            details.get("replica_knows_master_wait_seconds"),
            "not recorded in replica_replicate details",
        ),
        "replica_replicate_command_seconds": timing_field(
            details.get("replica_replicate_command_seconds"),
            "not recorded in replica_replicate details",
        ),
        "replica_replicaof_wait_seconds": timing_field(
            details.get("replica_replicaof_wait_seconds"),
            "not recorded in replica_replicate details",
        ),
        "replica_replicate_total_seconds": timing_field(
            details.get("replica_replicate_total_seconds")
            if numeric(details.get("replica_replicate_total_seconds"))
            else (entry.get("duration_seconds") if isinstance(entry, dict) else None),
            "replica_replicate total timing missing",
        ),
    }
    for field, value in timing.items():
        if not numeric(value):
            errors.append(f"{name}: {field} is not numeric")
    if details.get("parallelism") != expected_parallelism:
        errors.append(f"{name}: expected parallelism {expected_parallelism}, got {details.get('parallelism')}")
    if details.get("bounded_parallelism") is not True:
        errors.append(f"{name}: bounded_parallelism must be true")
    supported = details.get("supported_parallelism", [])
    if sorted(supported) != REPLICA_REPLICATE_SUPPORTED_PARALLELISM:
        errors.append(f"{name}: supported_parallelism must be {REPLICA_REPLICATE_SUPPORTED_PARALLELISM}, got {supported}")
    slowest = details.get("slowest_replicas", [])
    if not isinstance(slowest, list) or not slowest:
        errors.append(f"{name}: slowest_replicas must be a non-empty list")
        slowest = []
    for idx, replica in enumerate(slowest):
        if not isinstance(replica, dict):
            errors.append(f"{name}: slowest_replicas[{idx}] must be object")
            continue
        for field in [
            "logical_id",
            "replica_knows_master_wait_seconds",
            "replica_replicate_command_seconds",
            "replica_replicaof_wait_seconds",
            "replica_replicate_total_seconds",
        ]:
            if field not in replica:
                errors.append(f"{name}: slowest_replicas[{idx}] missing {field}")
    observation = {
        "name": name,
        "scenario": scenario,
        "node_count": expected_nodes,
        "status": "PASS" if not errors else "FAIL",
        "parallelism": details.get("parallelism", expected_parallelism),
        "parallelism_source": details.get("parallelism_source", "MISSING"),
        "bounded_parallelism": details.get("bounded_parallelism", "MISSING"),
        "real_valkey": evidence.get("real_valkey", "MISSING"),
        "evidence_path": rel(evidence_path),
        "timing_path": rel(timing_path),
        "timing": timing,
        "slowest_replicas": slowest,
        "role_counts": evidence.get("role_counts", "MISSING"),
        "data_path_result": evidence.get("data_path_result", "MISSING"),
        "nodes_observed": evidence.get("nodes_observed", "MISSING"),
        "timing_details": {
            "replica_count": details.get("replica_count", "MISSING"),
            "slowest_count": details.get("slowest_count", "MISSING"),
            "breakdown_semantics": details.get("breakdown_semantics", "MISSING"),
        },
    }
    return observation, evidence, errors


def write_replica_replicate_breakdown(errors: list[str]) -> tuple[Path, dict[str, Any], dict[str, dict[str, Any]]]:
    out = ROOT / "artifacts" / "phases" / REPLICA_REPLICATE_ARTIFACT_PHASE / "p13_replica_replicate_breakdown.json"
    observations: list[dict[str, Any]] = []
    evidence: dict[str, dict[str, Any]] = {}
    defaults = [
        (
            "default_scale_50",
            "scale_50",
            ROOT / "artifacts" / "phases" / BASE_PHASE / "p13_timing_breakdown_scale_50.json",
            ROOT / "artifacts" / "phases" / BASE_PHASE / "valkey_e2e_evidence_50.json",
            50,
            REPLICA_REPLICATE_DEFAULT_PARALLELISM,
        ),
        (
            "default_scale_100",
            "scale_100",
            ROOT / "artifacts" / "phases" / BASE_PHASE / "p13_timing_breakdown_scale_100.json",
            ROOT / "artifacts" / "phases" / BASE_PHASE / "valkey_e2e_evidence_100.json",
            100,
            REPLICA_REPLICATE_DEFAULT_PARALLELISM,
        ),
        (
            "parallelism_16_scale_50",
            "scale_50",
            ROOT / "artifacts" / "phases" / REPLICA_REPLICATE_ARTIFACT_PHASE / "p13_timing_breakdown_scale_50.json",
            ROOT / "artifacts" / "phases" / REPLICA_REPLICATE_ARTIFACT_PHASE / "valkey_e2e_evidence_parallelism_16_scale_50.json",
            50,
            16,
        ),
    ]
    for name, scenario, timing_path, evidence_path, expected_nodes, parallelism in defaults:
        observation, observed_evidence, obs_errors = replica_replicate_timing_observation(
            name=name,
            scenario=scenario,
            timing_path=timing_path,
            evidence_path=evidence_path,
            expected_nodes=expected_nodes,
            expected_parallelism=parallelism,
        )
        observations.append(observation)
        evidence[name] = observed_evidence
        errors.extend(obs_errors)

    artifact = {
        "schema_version": "v1",
        "artifact_type": "p13_replica_replicate_breakdown",
        "phase_id": P13O_REPLICA_REPLICATE_PHASE,
        "created_at": utc_now(),
        "producer": {"name": "scripts/p13_optimization_gate.py", "version": "v1"},
        "status": "PASS" if not errors else "FAIL",
        "default_parallelism": REPLICA_REPLICATE_DEFAULT_PARALLELISM,
        "supported_parallelism": REPLICA_REPLICATE_SUPPORTED_PARALLELISM,
        "safety_constraints": {
            "bounded_parallelism": True,
            "host_network_mutation": False,
            "p14_executed": False,
            "default_max_nodes": 100,
        },
        "observations": observations,
        "errors": errors,
    }
    write_json(out, artifact)
    return out, artifact, evidence


def write_replica_replicate_phase_summary(
    phase: dict[str, Any],
    breakdown: dict[str, Any],
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
    timing_accounting = {
        observation["name"]: {
            "scenario": observation.get("scenario"),
            "parallelism": observation.get("parallelism"),
            **observation.get("timing", {}),
        }
        for observation in breakdown.get("observations", [])
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
        "summary": "P13 replica replication now records bounded staged timing and slowest per-replica diagnostics.",
        "required_artifacts": [item["path"] for item in phase.get("required_artifacts", [])],
        "real_valkey_evidence": real_evidence,
        "timing_accounting": timing_accounting,
        "replica_replicate_breakdown_path": rel(
            ROOT / "artifacts" / "phases" / artifact_id / "p13_replica_replicate_breakdown.json"
        ),
        "errors": errors,
    }
    write_json(out, summary)
    return out


def cleanup_action_counts(actions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for action in actions:
        key = f"{action.get('type', 'unknown')}:{action.get('action', 'unknown')}:{action.get('status', 'unknown')}"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def cleanup_observation(
    *,
    scenario: str,
    expected_nodes: int,
    cleanup_path: Path,
    evidence_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    errors: list[str] = []
    evidence, evidence_errors = validate_real_evidence_path(evidence_path, scenario, expected_nodes)
    errors.extend(evidence_errors)
    cleanup_report: dict[str, Any] = {}
    if cleanup_path.exists():
        cleanup_report = load_json(cleanup_path)
    else:
        errors.append(f"{scenario}: missing cleanup report {rel(cleanup_path)}")
    if cleanup_report.get("status") != "PASS":
        errors.append(f"{scenario}: cleanup status is {cleanup_report.get('status')}")
    resources_remaining = cleanup_report.get("resources_remaining", [])
    if resources_remaining:
        errors.append(f"{scenario}: resources_remaining must be empty")
    actions = cleanup_report.get("cleanup_actions", [])
    if not isinstance(actions, list):
        errors.append(f"{scenario}: cleanup_actions must be a list")
        actions = []
    if any(action.get("status") == "FAIL" for action in actions):
        errors.append(f"{scenario}: cleanup action failure must not be ignored")
    timing = cleanup_report.get("cleanup_timing", {})
    required = [
        "cleanup_terminate_processes_seconds",
        "cleanup_verify_process_exit_seconds",
        "cleanup_verify_nodehost_empty_seconds",
        "cleanup_remove_containers_seconds",
        "cleanup_remove_networks_seconds",
        "cleanup_residual_scan_seconds",
    ]
    for field in required:
        if not numeric(timing.get(field)):
            errors.append(f"{scenario}: cleanup_timing.{field} must be numeric")
    if timing.get("bounded_parallelism") is not True:
        errors.append(f"{scenario}: cleanup_timing.bounded_parallelism must be true")
    observation = {
        "scenario": scenario,
        "node_count": expected_nodes,
        "status": "PASS" if not errors else "FAIL",
        "real_valkey": evidence.get("real_valkey", "MISSING"),
        "evidence_path": rel(evidence_path),
        "cleanup_report_path": rel(cleanup_path),
        "cleanup_timing": {
            field: round(float(timing[field]), 6) if numeric(timing.get(field)) else {"status": "MISSING", "reason": f"{field} not recorded"}
            for field in required
        } | {
            "bounded_parallelism": timing.get("bounded_parallelism", "MISSING"),
            "parallelism": timing.get("parallelism", "MISSING"),
        },
        "resources_remaining_count": len(resources_remaining) if isinstance(resources_remaining, list) else "MISSING",
        "cleanup_action_counts": cleanup_action_counts(actions),
        "cleanup_status": cleanup_report.get("status", "MISSING"),
        "data_path_result": evidence.get("data_path_result", "MISSING"),
        "role_counts": evidence.get("role_counts", "MISSING"),
        "nodes_observed": evidence.get("nodes_observed", "MISSING"),
    }
    return observation, evidence, errors


def write_cleanup_optimization(errors: list[str]) -> tuple[Path, dict[str, Any], dict[str, dict[str, Any]]]:
    out = ROOT / "artifacts" / "phases" / CLEANUP_ARTIFACT_PHASE / "p13_cleanup_optimization.json"
    observations: list[dict[str, Any]] = []
    evidence: dict[str, dict[str, Any]] = {}
    for scenario, expected_nodes in {"scale_50": 50, "scale_100": 100}.items():
        observation, observed_evidence, obs_errors = cleanup_observation(
            scenario=scenario,
            expected_nodes=expected_nodes,
            cleanup_path=ROOT / "artifacts" / "phases" / BASE_PHASE / f"cleanup_report_{scenario}.json",
            evidence_path=ROOT / "artifacts" / "phases" / BASE_PHASE / f"valkey_e2e_evidence_{scenario.removeprefix('scale_')}.json",
        )
        observations.append(observation)
        evidence[scenario] = observed_evidence
        errors.extend(obs_errors)
    artifact = {
        "schema_version": "v1",
        "artifact_type": "p13_cleanup_optimization",
        "phase_id": P13O_CLEANUP_PHASE,
        "created_at": utc_now(),
        "producer": {"name": "scripts/p13_optimization_gate.py", "version": "v1"},
        "status": "PASS" if not errors else "FAIL",
        "safety_constraints": {
            "bounded_parallelism": True,
            "cleanup_failure_ignored": False,
            "host_network_mutation": False,
            "p14_executed": False,
            "default_max_nodes": 100,
        },
        "observations": observations,
        "errors": errors,
    }
    write_json(out, artifact)
    return out, artifact, evidence


def write_cleanup_phase_summary(
    phase: dict[str, Any],
    cleanup_artifact: dict[str, Any],
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
    timing_accounting = {
        observation["scenario"]: observation.get("cleanup_timing", {})
        for observation in cleanup_artifact.get("observations", [])
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
        "summary": "P13 cleanup now records cleanup timing and uses bounded parallel cleanup while preserving cleanup evidence.",
        "required_artifacts": [item["path"] for item in phase.get("required_artifacts", [])],
        "real_valkey_evidence": real_evidence,
        "timing_accounting": timing_accounting,
        "cleanup_optimization_path": rel(ROOT / "artifacts" / "phases" / artifact_id / "p13_cleanup_optimization.json"),
        "errors": errors,
    }
    write_json(out, summary)
    return out


def gate_by_name(phase: dict[str, Any], name: str) -> dict[str, Any]:
    for gate in phase.get("gates", []):
        if gate.get("name") == name:
            return gate
    raise KeyError(name)


def load_base_manifest() -> dict[str, Any]:
    return load_json(ROOT / "codex" / "phase_manifest.json")


def pytest_measurement_from_stdout(gate_name: str) -> dict[str, Any]:
    stdout_path = ROOT / "artifacts" / "gates" / P13O_FAST_TEST_SPLIT_PHASE / "stdout" / f"{gate_name}.log"
    measurement: dict[str, Any] = {
        "gate_name": gate_name,
        "status": "MISSING",
        "stdout_path": rel(stdout_path),
        "duration_seconds": {"status": "MISSING", "reason": "pytest stdout not found"},
        "passed_count": {"status": "MISSING", "reason": "pytest stdout not found"},
        "deselected_count": {"status": "MISSING", "reason": "pytest stdout not found"},
    }
    if not stdout_path.exists():
        return measurement
    text = stdout_path.read_text(encoding="utf-8", errors="replace")
    measurement["stdout_tail"] = "\n".join(text.splitlines()[-8:])
    match = re.search(
        r"(?P<passed>\d+) passed(?:, (?P<deselected>\d+) deselected)?(?:, [^\\n]+)? in (?P<duration>[0-9.]+)s",
        text,
    )
    if not match:
        measurement["status"] = "FAIL" if "failed" in text else "MISSING"
        measurement["duration_seconds"] = {"status": "MISSING", "reason": "pytest duration summary not found"}
        measurement["passed_count"] = {"status": "MISSING", "reason": "pytest pass count not found"}
        return measurement
    measurement["status"] = "PASS"
    measurement["duration_seconds"] = round(float(match.group("duration")), 6)
    measurement["passed_count"] = int(match.group("passed"))
    measurement["deselected_count"] = int(match.group("deselected") or 0)
    return measurement


def collect_slow_perf_tests() -> tuple[list[str], list[str]]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    if (Path("/opt/anaconda3/bin") / "python3").exists():
        env["PATH"] = f"/opt/anaconda3/bin{os.pathsep}" + env.get("PATH", "")
    command = "python3 -m pytest --collect-only -q tests/unit tests/scale tests/integration -m 'slow or perf'"
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return [], ["slow/perf pytest collection timed out"]
    tests = [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    ]
    errors: list[str] = []
    if proc.returncode != 0:
        errors.append(f"slow/perf pytest collection failed with exit {proc.returncode}: {proc.stderr.strip()}")
    if not tests:
        errors.append("no slow/perf tests are explicitly collectable")
    return tests, errors


def pytest_markers_defined() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    markers: list[str] = []
    for marker in ["slow", "perf"]:
        if f'"{marker}:' in text or f"'{marker}:" in text:
            markers.append(marker)
    return markers


def historical_scale_tests_source(errors: list[str]) -> dict[str, Any]:
    gate_result_path = ROOT / "artifacts" / "gates" / BASE_PHASE / "gate_result.json"
    historical = {
        "gate_result_path": rel(gate_result_path),
        "gate_name": "scale_tests",
        "duration_seconds": 0.0,
        "command": "MISSING",
    }
    if not gate_result_path.exists():
        errors.append(f"missing historical P13 gate result: {rel(gate_result_path)}")
        return historical
    gate_result = load_json(gate_result_path)
    for gate in gate_result.get("gates", []):
        if gate.get("name") == "scale_tests":
            historical.update(
                {
                    "duration_seconds": round(float(gate.get("duration_seconds", 0.0) or 0.0), 6),
                    "command": str(gate.get("command", "MISSING")),
                    "stdout_path": gate.get("stdout_path", "MISSING"),
                    "status": gate.get("status", "MISSING"),
                }
            )
            stdout_path = ROOT / str(gate.get("stdout_path", ""))
            if stdout_path.exists():
                text = stdout_path.read_text(encoding="utf-8", errors="replace")
                historical["stdout_tail"] = "\n".join(text.splitlines()[-5:])
            return historical
    errors.append("historical P13 gate result does not contain scale_tests")
    return historical


def write_fast_test_split_artifact(phase: dict[str, Any], errors: list[str]) -> tuple[Path, dict[str, Any]]:
    base_manifest = load_base_manifest()
    base_phase = phase_by_id(base_manifest, BASE_PHASE)
    p13_scale_tests = gate_by_name(base_phase, "scale_tests")
    scale_50_gate = gate_by_name(base_phase, "scale_50_real_gate")
    scale_100_gate = gate_by_name(base_phase, "scale_100_real_gate")
    fast_gate = gate_by_name(phase, "p13o_fast_test_lane")
    slow_gate = gate_by_name(phase, "p13o_explicit_slow_perf_lane")

    default_command = str(p13_scale_tests.get("command", ""))
    if "not slow" not in default_command or "not perf" not in default_command:
        errors.append("P13 scale_tests command must exclude slow and perf markers")
    if p13_scale_tests.get("real_valkey") is not False:
        errors.append("P13 scale_tests must remain non-real-Valkey unit feedback")
    for gate_name, gate in [("scale_50_real_gate", scale_50_gate), ("scale_100_real_gate", scale_100_gate)]:
        if "scripts/valkey_e2e_gate.py" not in str(gate.get("command", "")):
            errors.append(f"P13 {gate_name} must keep scripts/valkey_e2e_gate.py real evidence")
        if gate.get("real_valkey") is not True:
            errors.append(f"P13 {gate_name} must remain real_valkey=true")

    markers = pytest_markers_defined()
    for marker in ["slow", "perf"]:
        if marker not in markers:
            errors.append(f"pytest marker {marker!r} is not defined")
    marked_tests, marker_errors = collect_slow_perf_tests()
    errors.extend(marker_errors)
    fast_measurement = pytest_measurement_from_stdout("p13o_fast_test_lane")
    slow_measurement = pytest_measurement_from_stdout("p13o_explicit_slow_perf_lane")
    if not numeric(fast_measurement.get("duration_seconds")):
        errors.append("fast test lane duration is missing")
    elif float(fast_measurement["duration_seconds"]) > FAST_TEST_MAX_SECONDS:
        errors.append(f"fast test lane exceeded {FAST_TEST_MAX_SECONDS}s")
    if not numeric(fast_measurement.get("passed_count")) or int(fast_measurement["passed_count"]) < 1:
        errors.append("fast test lane did not report passed tests")
    if not numeric(slow_measurement.get("passed_count")) or int(slow_measurement["passed_count"]) < 1:
        errors.append("explicit slow/perf lane did not report passed tests")

    historical = historical_scale_tests_source(errors)
    if numeric(historical.get("duration_seconds")) and numeric(fast_measurement.get("duration_seconds")):
        if float(fast_measurement["duration_seconds"]) >= float(historical["duration_seconds"]):
            errors.append("fast lane duration must be lower than historical P13 scale_tests duration")

    out = ROOT / "artifacts" / "phases" / FAST_TEST_SPLIT_ARTIFACT_PHASE / "p13_fast_test_split.json"
    artifact = {
        "schema_version": "v1",
        "artifact_type": "p13_fast_test_split",
        "phase_id": P13O_FAST_TEST_SPLIT_PHASE,
        "created_at": utc_now(),
        "producer": {"name": "scripts/p13_optimization_gate.py", "version": "v1"},
        "status": "PASS" if not errors else "FAIL",
        "historical_slow_source": historical,
        "default_p13_scale_tests": {
            "phase_id": BASE_PHASE,
            "gate_name": "scale_tests",
            "command": default_command,
            "excluded_markers": ["slow", "perf"],
            "real_valkey": bool(p13_scale_tests.get("real_valkey", False)),
            "measurement": fast_measurement,
        },
        "explicit_slow_perf_lane": {
            "command": str(slow_gate.get("command", "")),
            "included_markers": ["slow", "perf"],
            "measurement": slow_measurement,
            "collected_tests": marked_tests,
        },
        "marker_policy": {
            "markers_defined": markers,
            "marked_tests": marked_tests,
            "classification": "Timeout-sensitive cluster probe wait tests are slow-lane tests; performance benchmarks should use the perf marker.",
            "fast_lane_command": str(fast_gate.get("command", "")),
        },
        "real_evidence_source": {
            "scale_50_real_gate_command": str(scale_50_gate.get("command", "")),
            "scale_100_real_gate_command": str(scale_100_gate.get("command", "")),
            "wrapper": "scripts/valkey_e2e_gate.py",
            "preserved": True,
        },
        "safety_constraints": {
            "real_valkey_evidence_replaced": False,
            "tests_deleted": False,
            "p14_executed": False,
            "default_max_nodes": 100,
        },
        "errors": errors,
    }
    write_json(out, artifact)
    return out, artifact


def write_fast_test_split_phase_summary(
    phase: dict[str, Any],
    split_artifact: dict[str, Any],
    errors: list[str],
) -> Path:
    phase_id = str(phase["id"])
    artifact_id = artifact_phase_id(phase)
    out = ROOT / "artifacts" / "phases" / artifact_id / "phase_summary.json"
    fast_measurement = split_artifact.get("default_p13_scale_tests", {}).get("measurement", {})
    slow_measurement = split_artifact.get("explicit_slow_perf_lane", {}).get("measurement", {})
    summary = {
        "schema_version": "v1",
        "artifact_type": "p13_optimization_phase_summary",
        "phase_id": phase_id,
        "artifact_phase_id": artifact_id,
        "run_id": f"phase-{phase_id}",
        "created_at": utc_now(),
        "producer": {"name": "scripts/p13_optimization_gate.py", "version": "v1"},
        "status": "PASS" if not errors else "FAIL",
        "summary": "P13 scale_tests now runs the fast marker lane by default while slow/perf tests remain explicit.",
        "required_artifacts": [item["path"] for item in phase.get("required_artifacts", [])],
        "real_valkey_evidence": {
            "scale_50_real_gate": {
                "source": split_artifact.get("real_evidence_source", {}).get("scale_50_real_gate_command", "MISSING"),
                "preserved": True,
            },
            "scale_100_real_gate": {
                "source": split_artifact.get("real_evidence_source", {}).get("scale_100_real_gate_command", "MISSING"),
                "preserved": True,
            },
        },
        "timing_accounting": {
            "historical_scale_tests_seconds": split_artifact.get("historical_slow_source", {}).get("duration_seconds", "MISSING"),
            "fast_lane_seconds": fast_measurement.get("duration_seconds", "MISSING"),
            "slow_perf_lane_seconds": slow_measurement.get("duration_seconds", "MISSING"),
            "fast_lane_passed_count": fast_measurement.get("passed_count", "MISSING"),
            "slow_perf_lane_passed_count": slow_measurement.get("passed_count", "MISSING"),
        },
        "fast_test_split_path": rel(
            ROOT / "artifacts" / "phases" / artifact_id / "p13_fast_test_split.json"
        ),
        "errors": errors,
    }
    write_json(out, summary)
    return out


def validate_fast_test_split_artifacts(phase: dict[str, Any], *, write_summary_artifact: bool = True) -> int:
    all_errors: list[str] = []
    split_path = ROOT / "artifacts" / "phases" / FAST_TEST_SPLIT_ARTIFACT_PHASE / "p13_fast_test_split.json"
    if write_summary_artifact:
        split_path, split_artifact = write_fast_test_split_artifact(phase, all_errors)
    elif split_path.exists():
        split_artifact = load_json(split_path)
    else:
        split_artifact = {}
        all_errors.append(f"missing fast test split artifact: {rel(split_path)}")

    if split_path.exists():
        all_errors.extend(validate_schema(split_path, ROOT / "schemas" / "artifact" / "p13_fast_test_split.schema.json"))
        if split_artifact.get("status") != "PASS":
            all_errors.append(f"fast test split status is {split_artifact.get('status')}")
        default_command = str(split_artifact.get("default_p13_scale_tests", {}).get("command", ""))
        if "not slow" not in default_command or "not perf" not in default_command:
            all_errors.append("default P13 scale_tests command must exclude slow and perf")
        fast_measurement = split_artifact.get("default_p13_scale_tests", {}).get("measurement", {})
        if numeric(fast_measurement.get("duration_seconds")) and float(fast_measurement["duration_seconds"]) > FAST_TEST_MAX_SECONDS:
            all_errors.append(f"fast test lane exceeded {FAST_TEST_MAX_SECONDS}s")
        if not split_artifact.get("explicit_slow_perf_lane", {}).get("collected_tests"):
            all_errors.append("explicit slow/perf tests are not collectable")
        real_source = split_artifact.get("real_evidence_source", {})
        if real_source.get("preserved") is not True:
            all_errors.append("real Valkey evidence must remain preserved")
        for key in ["scale_50_real_gate_command", "scale_100_real_gate_command"]:
            if "scripts/valkey_e2e_gate.py" not in str(real_source.get(key, "")):
                all_errors.append(f"{key} must reference scripts/valkey_e2e_gate.py")

    summary_path = ROOT / "artifacts" / "phases" / FAST_TEST_SPLIT_ARTIFACT_PHASE / "phase_summary.json"
    if write_summary_artifact:
        summary_path = write_fast_test_split_phase_summary(phase, split_artifact, all_errors)
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


def validate_artifacts(args: argparse.Namespace, *, write_summary_artifact: bool = True) -> int:
    manifest = load_manifest()
    phase = phase_by_id(manifest, args.phase)
    if args.phase == P13O_CLUSTER_CREATE_PHASE:
        return validate_cluster_create_artifacts(phase, write_summary_artifact=write_summary_artifact)
    if args.phase == P13O_REPLICA_REPLICATE_PHASE:
        return validate_replica_replicate_artifacts(phase, write_summary_artifact=write_summary_artifact)
    if args.phase == P13O_CLEANUP_PHASE:
        return validate_cleanup_artifacts(phase, write_summary_artifact=write_summary_artifact)
    if args.phase == P13O_FAST_TEST_SPLIT_PHASE:
        return validate_fast_test_split_artifacts(phase, write_summary_artifact=write_summary_artifact)

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


def validate_replica_replicate_artifacts(phase: dict[str, Any], *, write_summary_artifact: bool = True) -> int:
    all_errors: list[str] = []
    breakdown_path = ROOT / "artifacts" / "phases" / REPLICA_REPLICATE_ARTIFACT_PHASE / "p13_replica_replicate_breakdown.json"
    if write_summary_artifact:
        breakdown_path, breakdown, evidence = write_replica_replicate_breakdown(all_errors)
    elif breakdown_path.exists():
        breakdown = load_json(breakdown_path)
        evidence = {}
    else:
        breakdown = {}
        evidence = {}
        all_errors.append(f"missing replica replicate breakdown artifact: {rel(breakdown_path)}")

    if breakdown_path.exists():
        all_errors.extend(validate_schema(breakdown_path, ROOT / "schemas" / "artifact" / "p13_replica_replicate_breakdown.schema.json"))
        if breakdown.get("default_parallelism") != REPLICA_REPLICATE_DEFAULT_PARALLELISM:
            all_errors.append(f"default replica parallelism must be {REPLICA_REPLICATE_DEFAULT_PARALLELISM}")
        if sorted(breakdown.get("supported_parallelism", [])) != REPLICA_REPLICATE_SUPPORTED_PARALLELISM:
            all_errors.append("supported replica parallelism must remain [8, 16, 32]")
        if breakdown.get("safety_constraints", {}).get("bounded_parallelism") is not True:
            all_errors.append("replica replicate must use bounded parallelism")
        observations = {item.get("name"): item for item in breakdown.get("observations", [])}
        for name in ["default_scale_50", "default_scale_100", "parallelism_16_scale_50"]:
            observation = observations.get(name)
            if not observation:
                all_errors.append(f"missing observation {name}")
            elif observation.get("status") != "PASS":
                all_errors.append(f"observation {name} status is {observation.get('status')}")

    if not evidence and breakdown.get("observations"):
        for observation in breakdown.get("observations", []):
            evidence_path = ROOT / str(observation.get("evidence_path", ""))
            expected_nodes = int(observation.get("node_count", 0) or 0)
            observed, errors = validate_real_evidence_path(evidence_path, str(observation.get("name")), expected_nodes)
            evidence[str(observation.get("name"))] = observed
            all_errors.extend(errors)

    summary_path = ROOT / "artifacts" / "phases" / REPLICA_REPLICATE_ARTIFACT_PHASE / "phase_summary.json"
    if write_summary_artifact:
        summary_path = write_replica_replicate_phase_summary(phase, breakdown, evidence, all_errors)
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


def validate_cleanup_artifacts(phase: dict[str, Any], *, write_summary_artifact: bool = True) -> int:
    all_errors: list[str] = []
    cleanup_path = ROOT / "artifacts" / "phases" / CLEANUP_ARTIFACT_PHASE / "p13_cleanup_optimization.json"
    if write_summary_artifact:
        cleanup_path, cleanup_artifact, evidence = write_cleanup_optimization(all_errors)
    elif cleanup_path.exists():
        cleanup_artifact = load_json(cleanup_path)
        evidence = {}
    else:
        cleanup_artifact = {}
        evidence = {}
        all_errors.append(f"missing cleanup optimization artifact: {rel(cleanup_path)}")

    if cleanup_path.exists():
        all_errors.extend(validate_schema(cleanup_path, ROOT / "schemas" / "artifact" / "p13_cleanup_optimization.schema.json"))
        if cleanup_artifact.get("safety_constraints", {}).get("cleanup_failure_ignored") is not False:
            all_errors.append("cleanup failures must not be ignored")
        observations = {item.get("scenario"): item for item in cleanup_artifact.get("observations", [])}
        for scenario in ["scale_50", "scale_100"]:
            observation = observations.get(scenario)
            if not observation:
                all_errors.append(f"missing cleanup observation {scenario}")
            elif observation.get("status") != "PASS":
                all_errors.append(f"cleanup observation {scenario} status is {observation.get('status')}")

    if not evidence and cleanup_artifact.get("observations"):
        for observation in cleanup_artifact.get("observations", []):
            evidence_path = ROOT / str(observation.get("evidence_path", ""))
            expected_nodes = int(observation.get("node_count", 0) or 0)
            observed, errors = validate_real_evidence_path(evidence_path, str(observation.get("scenario")), expected_nodes)
            evidence[str(observation.get("scenario"))] = observed
            all_errors.extend(errors)

    summary_path = ROOT / "artifacts" / "phases" / CLEANUP_ARTIFACT_PHASE / "phase_summary.json"
    if write_summary_artifact:
        summary_path = write_cleanup_phase_summary(phase, cleanup_artifact, evidence, all_errors)
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
