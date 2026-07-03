#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
MANIFEST = ROOT / "codex" / "phase_manifest.json"
LOCK = ROOT / "codex" / "gate_lock.json"
STATE = ROOT / "codex" / "status" / "phase_state.json"

GOAL_LOOP_FIRST = "P15_GOAL_REBASE_HARNESS_EXTENSION"
GOAL_LOOP_LAST = "P26_FINAL_REPORT_REGRESSION"
STRICT_GOAL_LOOP_FIRST = "P27_STRICT_MATRIX_REBASE_HARNESS"
STRICT_GOAL_LOOP_LAST = "P40_STRICT_FINAL_AUDIT_CLOSEOUT"
LEGACY_HARNESS_ONLY_NO_REAL_VALKEY = {"P15_GOAL_REBASE_HARNESS_EXTENSION"}
STRICT_NON_RUNTIME_NO_REAL_VALKEY = {
    "P27_STRICT_MATRIX_REBASE_HARNESS",
    "P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER",
    "P37_200_PLUS_DRY_RUN_SUPPORT",
    "P38_CROSS_SCALE_ANALYSIS_REGRESSION",
    "P39_VISUAL_REPORT_QUALITY_GATE",
    "P40_STRICT_FINAL_AUDIT_CLOSEOUT",
}
HARNESS_ONLY_NO_REAL_VALKEY = LEGACY_HARNESS_ONLY_NO_REAL_VALKEY | STRICT_NON_RUNTIME_NO_REAL_VALKEY
BOUNDED_SCALE_EXCEPTIONS = {
    "P21_FAILOVER_LATENCY_CURVE_200": 200,
    "P32_MANAGEMENT_MATRIX_200_REAL": 200,
    "P35_FAULT_FAILOVER_MATRIX_200_REAL": 200,
    "P36_FULL_FLOW_E2E_50_100_200_REAL": 200,
}
STRICT_STAGE_IDS = [
    "P27_STRICT_MATRIX_REBASE_HARNESS",
    "P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER",
    "P29_QUANT_TELEMETRY_COLLECTOR_HARDENING",
    "P30_MANAGEMENT_MATRIX_50_REAL",
    "P31_MANAGEMENT_MATRIX_100_REAL",
    "P32_MANAGEMENT_MATRIX_200_REAL",
    "P33_FAULT_FAILOVER_MATRIX_50_REAL",
    "P34_FAULT_FAILOVER_MATRIX_100_REAL",
    "P35_FAULT_FAILOVER_MATRIX_200_REAL",
    "P36_FULL_FLOW_E2E_50_100_200_REAL",
    "P37_200_PLUS_DRY_RUN_SUPPORT",
    "P38_CROSS_SCALE_ANALYSIS_REGRESSION",
    "P39_VISUAL_REPORT_QUALITY_GATE",
    "P40_STRICT_FINAL_AUDIT_CLOSEOUT",
]

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


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        raise SystemExit(f"missing manifest: {MANIFEST}")
    return load_json(MANIFEST)


def phase_by_id(manifest: dict[str, Any], phase_id: str) -> dict[str, Any]:
    for phase in manifest.get("phases", []):
        if phase.get("id") == phase_id:
            return phase
    raise SystemExit(f"unknown phase: {phase_id}")


def manifest_sha() -> str:
    return sha256_file(MANIFEST)


def load_state() -> dict[str, Any]:
    if STATE.exists():
        return load_json(STATE)
    return {"schema_version": "v1", "completed_phases": [], "last_updated": None}


def save_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def all_phase_ids(manifest: dict[str, Any], automatic_only: bool = False) -> list[str]:
    return [p["id"] for p in manifest["phases"] if (p.get("automatic", True) or not automatic_only)]


def check_lock() -> list[str]:
    errors: list[str] = []
    if not LOCK.exists():
        errors.append("missing codex/gate_lock.json")
        return errors
    lock = load_json(LOCK)
    for item in lock.get("files", []):
        path = ROOT / item["path"]
        expected = item["sha256"]
        if not path.exists():
            errors.append(f"locked harness file missing: {item['path']}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"locked harness file changed: {item['path']} expected={expected} actual={actual}")
    return errors


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("version") != "v1":
        errors.append("manifest version must be v1")
    if manifest.get("default_max_nodes") != 100:
        errors.append("manifest default_max_nodes must be exactly 100")
    ids: list[str] = []
    for phase in manifest.get("phases", []):
        pid = phase.get("id")
        if not isinstance(pid, str) or not pid.startswith("P"):
            errors.append(f"invalid phase id: {pid!r}")
            continue
        if pid in ids:
            errors.append(f"duplicate phase id: {pid}")
        ids.append(pid)
        max_nodes = int(phase.get("max_nodes", 0))
        if max_nodes > 200 and phase.get("automatic", True):
            errors.append(f"automatic phase {pid} exceeds absolute 200-node real-execution cap")
        if max_nodes > 100 and phase.get("automatic", True):
            if BOUNDED_SCALE_EXCEPTIONS.get(pid) != max_nodes:
                errors.append(f"automatic phase {pid} exceeds default 100-node cap")
        if pid.startswith("P14") and phase.get("automatic", True):
            errors.append("P14 must not be automatic")
        if (
            phase_number(pid) >= 3
            and phase.get("automatic", True)
            and pid not in HARNESS_ONLY_NO_REAL_VALKEY
            and not phase.get("real_valkey_required")
        ):
            errors.append(f"{pid} must require real Valkey")
        if pid in STRICT_NON_RUNTIME_NO_REAL_VALKEY and phase.get("real_valkey_required"):
            errors.append(f"{pid} must not require live Valkey because it is a strict non-runtime stage")
        if pid == "P37_200_PLUS_DRY_RUN_SUPPORT":
            if phase.get("execution_mode") != "dry_run":
                errors.append("P37 must declare execution_mode=dry_run")
            if phase.get("dry_run_target_nodes") != [201, 250, 300, 500, 1000]:
                errors.append("P37 dry_run_target_nodes must be exactly [201, 250, 300, 500, 1000]")
        gate_names = set()
        for gate in phase.get("gates", []):
            name = gate.get("name")
            if not name:
                errors.append(f"{pid}: gate missing name")
            if name in gate_names:
                errors.append(f"{pid}: duplicate gate name {name}")
            gate_names.add(name)
            cmd = gate.get("command", "")
            if not cmd or not isinstance(cmd, str):
                errors.append(f"{pid}/{name}: gate command missing")
            if "scripts/codex_gate.py run" in cmd or "scripts/codex_gate.py postcheck" in cmd:
                errors.append(f"{pid}/{name}: recursive codex_gate run/postcheck is not allowed in manifest gates")
            if "echo PASS" in cmd or "printf PASS" in cmd:
                errors.append(f"{pid}/{name}: suspicious PASS-only gate command")
            if gate.get("real_valkey") and "scripts/valkey_e2e_gate.py" not in cmd and "scripts/fault_" not in cmd:
                errors.append(f"{pid}/{name}: real_valkey gate must use pre-authored wrapper")
        if pid in {"P30_MANAGEMENT_MATRIX_50_REAL", "P31_MANAGEMENT_MATRIX_100_REAL", "P32_MANAGEMENT_MATRIX_200_REAL", "P33_FAULT_FAILOVER_MATRIX_50_REAL", "P34_FAULT_FAILOVER_MATRIX_100_REAL", "P35_FAULT_FAILOVER_MATRIX_200_REAL"}:
            exact = f"assert_exact_scale_real_evidence.py --phase {pid} --nodes {max_nodes}"
            if not any(exact in str(g.get("command", "")) for g in phase.get("gates", [])):
                errors.append(f"{pid}: missing exact-scale evidence assertion for {max_nodes} nodes")
        for artifact in phase.get("required_artifacts", []):
            apath = artifact.get("path", "")
            if not apath.startswith("artifacts/phases/"):
                errors.append(f"{pid}: artifact path must be under artifacts/phases/: {apath}")
            schema = artifact.get("schema")
            if schema and not (ROOT / schema).exists():
                errors.append(f"{pid}: artifact schema missing: {schema}")
    strict_present = all(stage_id in ids for stage_id in STRICT_STAGE_IDS)
    expected_stop_after = STRICT_GOAL_LOOP_LAST if strict_present else GOAL_LOOP_LAST
    if manifest.get("automatic_stop_after") != expected_stop_after:
        errors.append(f"automatic_stop_after must be {expected_stop_after}")
    if strict_present:
        positions = [ids.index(stage_id) for stage_id in STRICT_STAGE_IDS]
        if positions != sorted(positions):
            errors.append("strict P27-P40 stages must be in order")
        elif ids[positions[0] : positions[-1] + 1] != STRICT_STAGE_IDS:
            errors.append("strict P27-P40 stages must be contiguous")
    return errors


def phase_number(phase_id: str) -> int:
    try:
        return int(phase_id[1:3])
    except Exception:
        return -1


def precheck(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    errors = []
    errors.extend(validate_manifest(manifest))
    errors.extend(check_lock())
    phases = all_phase_ids(manifest) if args.all else [args.phase]
    for pid in phases:
        phase = phase_by_id(manifest, pid)
        if pid.startswith("P14") and not args.all:
            required = "I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE"
            if os.environ.get("VSLAB_ALLOW_1000_DRYRUN") != required:
                errors.append("P14 requires VSLAB_ALLOW_1000_DRYRUN=I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE")
        if phase.get("real_valkey_required"):
            has_real_gate = any(g.get("real_valkey") for g in phase.get("gates", []))
            has_evidence_artifact = any("valkey_e2e_evidence" in a.get("path", "") for a in phase.get("required_artifacts", []))
            if not has_real_gate:
                errors.append(f"{pid}: real_valkey_required but no real_valkey gate")
            if not has_evidence_artifact:
                errors.append(f"{pid}: real_valkey_required but no valkey evidence artifact")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print("PASS precheck")
    return 0


def run_gate_command(phase_id: str, gate: dict[str, Any], gate_root: Path) -> dict[str, Any]:
    name = gate["name"]
    stdout_dir = gate_root / "stdout"
    stderr_dir = gate_root / "stderr"
    stdout_dir.mkdir(parents=True, exist_ok=True)
    stderr_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = stdout_dir / f"{name}.log"
    stderr_path = stderr_dir / f"{name}.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    env["VSLAB_PHASE_ID"] = phase_id
    env["VSLAB_ARTIFACT_DIR"] = str(ROOT / "artifacts" / "phases" / phase_id)
    env.setdefault("PYTHONPYCACHEPREFIX", str(ROOT / ".pycache"))
    command = gate["command"]
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
    finished = utc_now()
    duration = time.monotonic() - t0
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
        "finished_at": finished,
        "duration_seconds": round(duration, 6),
        "stdout_path": rel(stdout_path),
        "stderr_path": rel(stderr_path),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
    }


def run_phase(args: argparse.Namespace) -> int:
    if precheck(argparse.Namespace(phase=args.phase, all=False)) != 0:
        return 1
    manifest = load_manifest()
    phase = phase_by_id(manifest, args.phase)
    gate_root = ROOT / "artifacts" / "gates" / args.phase
    gate_root.mkdir(parents=True, exist_ok=True)
    results = []
    for gate in phase.get("gates", []):
        print(f"RUN {args.phase}/{gate['name']}: {gate['command']}")
        result = run_gate_command(args.phase, gate, gate_root)
        print(f"{result['status']} {gate['name']} exit={result['exit_code']}")
        results.append(result)
    overall = "PASS" if all((not g["required"]) or g["status"] == "PASS" for g in results) else "FAIL"
    gate_result = {
        "schema_version": "v1",
        "artifact_type": "gate_result",
        "phase_id": args.phase,
        "created_at": utc_now(),
        "runner": "scripts/codex_gate.py",
        "manifest_sha256": manifest_sha(),
        "status": overall,
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "cwd": str(ROOT),
        },
        "gates": results,
    }
    out = gate_root / "gate_result.json"
    out.write_text(json.dumps(gate_result, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"WROTE {rel(out)} status={overall}")
    return 0 if overall == "PASS" else 1


def validate_artifact(path: Path, schema_path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"artifact missing: {rel(path)}"]
    if not schema_path.exists():
        return [f"schema missing: {rel(schema_path)}"]
    schema = load_json(schema_path)
    if path.suffix == ".jsonl":
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return [f"jsonl artifact empty: {rel(path)}"]
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{rel(path)}:{lineno}: invalid JSON: {exc}")
                continue
            errors.extend(validate(obj, schema, f"$[line {lineno}]"))
    else:
        try:
            obj = load_json(path)
        except Exception as exc:
            return [f"artifact not valid JSON: {rel(path)}: {exc}"]
        errors.extend(validate(obj, schema))
    return errors


def validate_gate_result(phase: dict[str, Any], gate_result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema_path = ROOT / "schemas" / "artifact" / "gate_result.schema.json"
    errors.extend(validate(gate_result, load_json(schema_path)))
    if gate_result.get("phase_id") != phase["id"]:
        errors.append("gate result phase_id does not match")
    if gate_result.get("status") != "PASS":
        errors.append("gate result status is not PASS")
    if gate_result.get("manifest_sha256") != manifest_sha():
        errors.append("gate result manifest_sha256 does not match current manifest")
    expected = {g["name"]: g for g in phase.get("gates", [])}
    observed = {g.get("name"): g for g in gate_result.get("gates", [])}
    if set(expected) != set(observed):
        errors.append(f"gate set mismatch expected={sorted(expected)} observed={sorted(observed)}")
    for name, exp in expected.items():
        obs = observed.get(name)
        if not obs:
            continue
        if obs.get("command") != exp.get("command"):
            errors.append(f"gate {name}: command mismatch")
        if exp.get("required", True) and obs.get("status") != "PASS":
            errors.append(f"gate {name}: required gate did not PASS")
        if exp.get("required", True) and obs.get("exit_code") != 0:
            errors.append(f"gate {name}: exit_code is not 0")
        for key in ["stdout_path", "stderr_path"]:
            p = ROOT / obs.get(key, "")
            if not p.exists():
                errors.append(f"gate {name}: log missing {key}={obs.get(key)}")
                continue
            sha_key = key.replace("_path", "_sha256")
            if sha256_file(p) != obs.get(sha_key):
                errors.append(f"gate {name}: checksum mismatch for {key}")
    return errors


def check_real_evidence(phase: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    evidence_paths = [ROOT / a["path"] for a in phase.get("required_artifacts", []) if "valkey_e2e_evidence" in a.get("path", "")]
    if phase.get("real_valkey_required") and not evidence_paths:
        return [f"{phase['id']}: real Valkey required but no evidence artifact declared"]
    for path in evidence_paths:
        if not path.exists():
            errors.append(f"real evidence missing: {rel(path)}")
            continue
        try:
            ev = load_json(path)
        except Exception as exc:
            errors.append(f"real evidence invalid JSON: {rel(path)}: {exc}")
            continue
        if ev.get("real_valkey") is not True:
            errors.append(f"{rel(path)}: real_valkey must be true")
        if ev.get("probe_result") != "PASS":
            errors.append(f"{rel(path)}: probe_result must be PASS")
        if ev.get("valkey_version_prefix_required") != "9.1.":
            errors.append(f"{rel(path)}: version prefix requirement must be 9.1.")
        versions = ev.get("valkey_versions") or []
        if versions and not all(str(v).startswith("9.1.") for v in versions if v):
            errors.append(f"{rel(path)}: observed non-9.1 Valkey versions: {versions}")
        if int(ev.get("nodes_observed", 0)) < 1:
            errors.append(f"{rel(path)}: nodes_observed must be >= 1")
    return errors


def check_audit(phase: dict[str, Any], gate_result_path: Path) -> list[str]:
    errors: list[str] = []
    audit = phase.get("audit", {})
    md_path = ROOT / audit.get("md_path", "")
    json_path = ROOT / audit.get("decision_json_path", "")
    if not md_path.exists():
        errors.append(f"audit markdown missing: {rel(md_path)}")
        return errors
    if not json_path.exists():
        errors.append(f"audit decision json missing: {rel(json_path)}")
        return errors
    text = md_path.read_text(encoding="utf-8")
    gate_sha = sha256_file(gate_result_path)
    required_strings = [
        "Decision: PASS",
        "Fresh Context: YES",
        rel(gate_result_path),
        gate_sha,
    ]
    for s in required_strings:
        if s not in text:
            errors.append(f"audit markdown missing required text: {s}")
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True) and artifact["path"] not in text:
            errors.append(f"audit markdown does not cite artifact: {artifact['path']}")
    decision = load_json(json_path)
    errors.extend(validate(decision, load_json(ROOT / "schemas/artifact/audit_decision.schema.json")))
    if decision.get("decision") != "PASS":
        errors.append("audit_decision decision must be PASS")
    if decision.get("fresh_context") is not True:
        errors.append("audit_decision fresh_context must be true")
    if decision.get("gate_result_path") != rel(gate_result_path):
        errors.append("audit_decision gate_result_path mismatch")
    if decision.get("gate_result_sha256") != gate_sha:
        errors.append("audit_decision gate_result_sha256 mismatch")
    declared_paths = set(decision.get("artifact_paths", []))
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True) and artifact["path"] not in declared_paths:
            errors.append(f"audit_decision missing artifact path: {artifact['path']}")
    return errors


def is_goal_loop_stage(phase_id: str) -> bool:
    number = phase_number(phase_id)
    return 15 <= number <= 26


def is_strict_stage(phase_id: str) -> bool:
    return phase_id in STRICT_STAGE_IDS


def check_goal_loop_review(phase: dict[str, Any], gate_result_path: Path) -> list[str]:
    errors: list[str] = []
    phase_id = phase["id"]
    if not is_goal_loop_stage(phase_id):
        return errors
    review_path = ROOT / "artifacts" / "goal_loop" / phase_id / "REVIEW.md"
    if not review_path.exists():
        return [f"goal-loop review missing: {rel(review_path)}"]
    text = review_path.read_text(encoding="utf-8")
    gate_sha = sha256_file(gate_result_path)
    required_strings = [
        "Decision: PASS",
        rel(gate_result_path),
        gate_sha,
    ]
    for item in required_strings:
        if item not in text:
            errors.append(f"goal-loop review missing required text: {item}")
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True) and artifact["path"] not in text:
            errors.append(f"goal-loop review does not cite artifact: {artifact['path']}")
    return errors


def check_strict_handoffs(phase: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    phase_id = phase["id"]
    if not is_strict_stage(phase_id):
        return errors
    handoff_dir = ROOT / "artifacts" / "goal_loop_strict" / phase_id
    for name in ["CONTEXT_RELOAD.md", "DESIGN_BRIEF.md", "WORKER_SUMMARY.md", "REVIEW.md"]:
        path = handoff_dir / name
        if not path.exists():
            errors.append(f"strict handoff missing: {rel(path)}")
    return errors


def check_strict_review(phase: dict[str, Any], gate_result_path: Path) -> list[str]:
    errors: list[str] = []
    phase_id = phase["id"]
    if not is_strict_stage(phase_id):
        return errors
    review_path = ROOT / "artifacts" / "goal_loop_strict" / phase_id / "REVIEW.md"
    if not review_path.exists():
        return [f"strict review missing: {rel(review_path)}"]
    text = review_path.read_text(encoding="utf-8")
    gate_sha = sha256_file(gate_result_path)
    required_strings = [
        "Decision: PASS",
        rel(gate_result_path),
        gate_sha,
    ]
    for item in required_strings:
        if item not in text:
            errors.append(f"strict review missing required text: {item}")
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True) and artifact["path"] not in text:
            errors.append(f"strict review does not cite artifact: {artifact['path']}")
    if phase_id not in {"P27_STRICT_MATRIX_REBASE_HARNESS", "P28_COVERAGE_REGISTRY_AND_SCENARIO_COMPILER"} and "Coverage IDs:" not in text:
        errors.append("strict review must cite Coverage IDs for coverage-owning stages")
    return errors


def postcheck(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    phase = phase_by_id(manifest, args.phase)
    errors: list[str] = []
    errors.extend(validate_manifest(manifest))
    errors.extend(check_lock())
    gate_result_path = ROOT / "artifacts" / "gates" / args.phase / "gate_result.json"
    if not gate_result_path.exists():
        errors.append(f"gate result missing: {rel(gate_result_path)}")
    else:
        gate_result = load_json(gate_result_path)
        errors.extend(validate_gate_result(phase, gate_result))
    for artifact in phase.get("required_artifacts", []):
        if not artifact.get("required", True):
            continue
        errors.extend(validate_artifact(ROOT / artifact["path"], ROOT / artifact["schema"]))
    errors.extend(check_real_evidence(phase))
    if gate_result_path.exists():
        errors.extend(check_audit(phase, gate_result_path))
        errors.extend(check_goal_loop_review(phase, gate_result_path))
        errors.extend(check_strict_handoffs(phase))
        errors.extend(check_strict_review(phase, gate_result_path))
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS postcheck {args.phase}")
    return 0


def next_phase(_args: argparse.Namespace) -> int:
    manifest = load_manifest()
    state = load_state()
    completed = set(state.get("completed_phases", []))
    for phase in manifest.get("phases", []):
        if not phase.get("automatic", True):
            continue
        if phase["id"] not in completed:
            print(phase["id"])
            return 0
    print("COMPLETE_AUTOMATIC_PHASES")
    return 0


def mark_complete(args: argparse.Namespace) -> int:
    if postcheck(argparse.Namespace(phase=args.phase)) != 0:
        return 1
    manifest = load_manifest()
    ids = all_phase_ids(manifest)
    if args.phase not in ids:
        print(f"unknown phase {args.phase}", file=sys.stderr)
        return 2
    state = load_state()
    completed = list(state.get("completed_phases", []))
    if args.phase not in completed:
        completed.append(args.phase)
    state["schema_version"] = "v1"
    state["completed_phases"] = completed
    state["last_updated"] = utc_now()
    save_state(state)
    print(f"MARKED_COMPLETE {args.phase}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex phase gate runner")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("precheck")
    p.add_argument("--phase")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=precheck)
    p = sub.add_parser("run")
    p.add_argument("--phase", required=True)
    p.set_defaults(func=run_phase)
    p = sub.add_parser("postcheck")
    p.add_argument("--phase", required=True)
    p.set_defaults(func=postcheck)
    p = sub.add_parser("next")
    p.set_defaults(func=next_phase)
    p = sub.add_parser("mark-complete")
    p.add_argument("--phase", required=True)
    p.set_defaults(func=mark_complete)
    args = parser.parse_args()
    if args.cmd == "precheck" and not args.all and not args.phase:
        parser.error("precheck requires --phase or --all")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
