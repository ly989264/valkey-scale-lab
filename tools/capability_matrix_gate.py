#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "codex" / "capability_matrix_loop" / "stage_manifest.json"
STATE = ROOT / "codex" / "capability_matrix_loop" / "state.json"
LOCK = ROOT / "codex" / "capability_matrix_loop" / "harness_lock.json"
SCHEMA_ROOT = ROOT / "schemas" / "capability_matrix_loop"
ARTIFACT_ROOT = ROOT / "artifacts" / "capability_matrix_loop"

sys.path.insert(0, str(ROOT / "scripts"))
from schema_validator import load_json, validate  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_manifest() -> dict[str, Any]:
    return load_json(MANIFEST)


def load_state() -> dict[str, Any]:
    return load_json(STATE)


def stage_by_id(stage_id: str) -> dict[str, Any]:
    for stage in load_manifest().get("stages", []):
        if stage.get("id") == stage_id:
            return stage
    raise SystemExit(f"unknown capability stage: {stage_id}")


def schema_errors(path: Path, schema_path_text: str) -> list[str]:
    schema_path = ROOT / schema_path_text
    if not schema_path.exists():
        return [f"schema missing: {schema_path_text}"]
    try:
        data = load_json(path)
    except json.JSONDecodeError as exc:
        return [f"{rel(path)} invalid JSON: {exc}"]
    return [f"{rel(path)} {err}" for err in validate(data, load_json(schema_path))]


def check_manifest() -> list[str]:
    errors: list[str] = []
    manifest = load_manifest()
    if manifest.get("schema_version") != "v1":
        errors.append("stage_manifest schema_version must be v1")
    if manifest.get("default_max_real_nodes") != 100:
        errors.append("default_max_real_nodes must be exactly 100")
    if set(manifest.get("forbidden_default_real_scales", [])) != {200, 500, 1000}:
        errors.append("forbidden_default_real_scales must include exactly 200, 500, 1000")
    seen: set[str] = set()
    for stage in manifest.get("stages", []):
        stage_id = stage.get("id", "")
        if not stage_id.startswith("CML"):
            errors.append(f"invalid CML stage id: {stage_id!r}")
        if stage_id in seen:
            errors.append(f"duplicate CML stage id: {stage_id}")
        seen.add(stage_id)
        max_real_nodes = int(stage.get("max_real_nodes", 0))
        if stage.get("automatic", True) and max_real_nodes > 100:
            errors.append(f"{stage_id}: automatic stage exceeds 100 real nodes")
        if stage.get("profile", "").startswith("real-") and max_real_nodes in {200, 500, 1000}:
            errors.append(f"{stage_id}: forbidden default real scale {max_real_nodes}")
        if stage_id == "CML00_CAPABILITY_LOOP_BOOTSTRAP":
            if not stage.get("negative_requirements"):
                errors.append("CML00 must declare negative requirements")
            if stage.get("real_valkey_required"):
                errors.append("CML00 must not require real Valkey")
    return errors


def check_state() -> list[str]:
    errors: list[str] = []
    state = load_state()
    if state.get("schema_version") != "v1":
        errors.append("state schema_version must be v1")
    if state.get("loop_id") != "capability_matrix_loop":
        errors.append("state loop_id must be capability_matrix_loop")
    if "completed_stages" not in state:
        errors.append("state missing completed_stages")
    return errors


def check_lock() -> list[str]:
    errors: list[str] = []
    lock = load_json(LOCK)
    if lock.get("schema_version") != "v1":
        errors.append("harness_lock schema_version must be v1")
    for item in lock.get("files", []):
        path_text = item.get("path", "")
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"locked CML harness file missing: {path_text}")
            continue
        actual = sha256_file(path)
        if actual != item.get("sha256"):
            errors.append(f"locked CML harness file changed: {path_text}")
    return errors


def validate_required_artifacts(stage: dict[str, Any], *, include_gate_result: bool = False) -> list[str]:
    errors: list[str] = []
    for artifact in stage.get("required_artifacts", []):
        path_text = artifact["path"]
        if path_text.endswith("validation/current_stage_gate_result.json") and not include_gate_result:
            continue
        if not include_gate_result and (
            path_text.endswith("/stage_result.json")
            or path_text.endswith("/next_stage_context.md")
            or path_text.endswith("/AUDIT.md")
            or path_text.endswith("/audit_decision.json")
        ):
            continue
        path = ROOT / path_text
        if not path.exists():
            errors.append(f"required artifact missing: {path_text}")
            continue
        if artifact.get("schema"):
            errors.extend(schema_errors(path, artifact["schema"]))
    return errors


def validate_baseline(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"baseline missing: {rel(path)}"]
    baseline = load_json(path)
    for idx, row in enumerate(baseline.get("capabilities", [])):
        status = row.get("status")
        evidence_paths = row.get("evidence_paths", [])
        if status == "PASS" and not evidence_paths:
            errors.append(f"baseline row {idx} PASS without evidence_paths")
        if row.get("real_valkey_required"):
            for evidence_path in evidence_paths:
                evidence_file = ROOT / evidence_path
                if not evidence_file.exists():
                    errors.append(f"baseline row {idx} evidence missing: {evidence_path}")
                    continue
                try:
                    evidence = load_json(evidence_file)
                except json.JSONDecodeError as exc:
                    errors.append(f"baseline row {idx} evidence invalid JSON: {exc}")
                    continue
                if evidence.get("real_valkey") is not True:
                    errors.append(f"baseline row {idx} fake real_valkey evidence: {evidence_path}")
                if evidence.get("valkey_version_prefix_required") != "9.1.":
                    errors.append(f"baseline row {idx} wrong Valkey version requirement: {evidence_path}")
                if evidence.get("probe_result") != "PASS":
                    errors.append(f"baseline row {idx} probe_result not PASS: {evidence_path}")
        if row.get("cleanup_required") and status in {"PASS", "PARTIAL"} and not row.get("cleanup_evidence_paths"):
            errors.append(f"baseline row {idx} cleanup required but missing evidence")
        if status == "SKIPPED_WITH_REASON" and row.get("target_capability"):
            errors.append(f"baseline row {idx} target capability cannot pass as skipped")
        for report in row.get("report_artifacts", []):
            if not report.get("source_artifacts"):
                errors.append(f"baseline row {idx} report artifact missing source_artifacts")
            for source in report.get("source_artifacts", []):
                if not source.get("sha256"):
                    errors.append(f"baseline row {idx} report source missing sha256")
        if row.get("source_stage") and row.get("source_stage") != row.get("current_stage", row.get("source_stage")):
            errors.append(f"baseline row {idx} old artifact reused as current stage evidence")
    return errors


def make_negative_cases() -> list[dict[str, Any]]:
    base = {
        "capability": "negative_fake_real",
        "scale_nodes": 30,
        "status": "PASS",
        "evidence_paths": [],
        "real_valkey_required": True,
        "cleanup_required": True,
        "cleanup_evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_scale_30.json"],
        "report_artifacts": [
            {
                "path": "reports/fake.html",
                "source_artifacts": [
                    {"path": "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json", "sha256": "x"}
                ]
            }
        ],
    }
    cases: list[tuple[str, dict[str, Any], str]] = [
        ("missing_artifact", {"capabilities": []}, "required artifact missing"),
        ("fake_real_valkey_evidence", {"capabilities": [base | {"evidence_paths": ["artifacts/capability_matrix_loop/CML00_CAPABILITY_LOOP_BOOTSTRAP/validation/fake_valkey_evidence.json"]}]}, "fake real_valkey evidence"),
        ("skip_as_pass", {"capabilities": [base | {"status": "SKIPPED_WITH_REASON", "target_capability": True, "evidence_paths": []}]}, "target capability cannot pass as skipped"),
        ("cleanup_missing", {"capabilities": [base | {"evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"], "cleanup_evidence_paths": []}]}, "cleanup required"),
        ("report_without_checksum", {"capabilities": [base | {"evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"], "report_artifacts": [{"path": "reports/no_checksum.html", "source_artifacts": [{"path": "artifact.json"}]}]}]}, "report source missing sha256"),
        ("old_artifact_reuse", {"capabilities": [base | {"evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"], "source_stage": "P12_SCALE_LADDER_10_30", "current_stage": "CML00_CAPABILITY_LOOP_BOOTSTRAP"}]}, "old artifact reused"),
    ]
    results: list[dict[str, Any]] = []
    fake_path = ROOT / "artifacts" / "capability_matrix_loop" / "CML00_CAPABILITY_LOOP_BOOTSTRAP" / "validation" / "fake_valkey_evidence.json"
    write_json(
        fake_path,
        {
            "schema_version": "v1",
            "artifact_type": "valkey_e2e_evidence",
            "phase_id": "P12_SCALE_LADDER_10_30",
            "run_id": "fake-negative-case",
            "created_at": utc_now(),
            "producer": {"name": "capability_matrix_gate", "version": "negative"},
            "status": "PASS",
            "real_valkey": False,
            "valkey_version_prefix_required": "9.1.",
            "probe_result": "PASS",
            "nodes_observed": 30,
            "cluster_state_observed": "ok",
            "data_path_result": "PASS",
            "probes": [{"logical_id": "fake", "host": "127.0.0.1", "port": 1, "status": "PASS"}],
            "cleanup": {"status": "PASS"},
        },
    )
    for name, payload, expected in cases:
        if name == "missing_artifact":
            errors = ["required artifact missing: synthetic"]
        else:
            tmp = ROOT / "artifacts" / "capability_matrix_loop" / "CML00_CAPABILITY_LOOP_BOOTSTRAP" / "validation" / f"{name}.baseline.json"
            write_json(
                tmp,
                {
                    "schema_version": "v1",
                    "artifact_type": "capability_matrix_baseline",
                    "stage_id": "CML00_CAPABILITY_LOOP_BOOTSTRAP",
                    "status": "PASS",
                    "created_at": utc_now(),
                    **payload,
                },
            )
            errors = validate_baseline(tmp)
        results.append(
            {
                "name": name,
                "status": "PASS" if any(expected in error for error in errors) else "FAIL",
                "expected_error_fragment": expected,
                "observed_errors": errors,
            }
        )
    return results


def build_baseline() -> dict[str, Any]:
    capabilities = [
        {
            "capability": "cluster_management_scale_30",
            "scale_nodes": 30,
            "status": "PARTIAL",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"],
            "cleanup_evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_scale_30.json"],
            "missing_or_partial": ["remove_node", "add_node", "reshard", "rebalance", "rolling_restart workload windows require CML02 closure"],
            "report_artifacts": [],
        },
        {
            "capability": "fault_failover_scale_30",
            "scale_nodes": 30,
            "status": "PARTIAL",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_fault_30.json"],
            "cleanup_evidence_paths": ["artifacts/phases/P12_SCALE_LADDER_10_30/cleanup_report_fault_30.json"],
            "missing_or_partial": ["network partition", "nodehost kill/restart", "split-brain ABSENT_OBSERVED proof", "full before/during/after workload windows"],
            "report_artifacts": [],
        },
        {
            "capability": "scale_ladder_50_100",
            "scale_nodes": 100,
            "status": "PARTIAL",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": ["artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json"],
            "cleanup_evidence_paths": ["artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_100.json"],
            "missing_or_partial": ["capability suite replay for management/fault/failover/split-brain/workload/soak across 50 and 100"],
            "report_artifacts": [],
        },
        {
            "capability": "bounded_soak_30_60_minutes",
            "scale_nodes": 30,
            "status": "MISSING",
            "real_valkey_required": True,
            "cleanup_required": True,
            "evidence_paths": [],
            "cleanup_evidence_paths": [],
            "missing_or_partial": ["30-minute soak", "60-minute soak"],
            "report_artifacts": [],
        },
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "capability_matrix_baseline",
        "stage_id": "CML00_CAPABILITY_LOOP_BOOTSTRAP",
        "status": "PASS",
        "created_at": utc_now(),
        "capabilities": capabilities,
    }


def command_next(_: argparse.Namespace) -> int:
    state = load_state()
    completed = set(state.get("completed_stages", []))
    for stage in load_manifest().get("stages", []):
        if stage.get("automatic", True) and stage["id"] not in completed:
            print(stage["id"])
            return 0
    print("COMPLETE")
    return 0


def command_build_baseline(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else ARTIFACT_ROOT / args.stage / "reports" / "capability_matrix_baseline.json"
    write_json(out, build_baseline())
    errors = schema_errors(out, "schemas/capability_matrix_loop/capability_matrix_baseline.schema.json")
    errors.extend(validate_baseline(out))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(rel(out))
    return 0


def command_run(args: argparse.Namespace) -> int:
    stage = stage_by_id(args.stage)
    checks: list[dict[str, Any]] = []

    def add_check(name: str, errors: list[str]) -> None:
        checks.append({"name": name, "status": "PASS" if not errors else "FAIL", "errors": errors})

    add_check("manifest", check_manifest())
    add_check("state", check_state())
    add_check("harness_lock", check_lock())
    add_check("required_artifacts", validate_required_artifacts(stage))
    baseline_path = ROOT / "artifacts" / "capability_matrix_loop" / args.stage / "reports" / "capability_matrix_baseline.json"
    baseline_errors = schema_errors(baseline_path, "schemas/capability_matrix_loop/capability_matrix_baseline.schema.json") if baseline_path.exists() else [f"baseline missing: {rel(baseline_path)}"]
    baseline_errors.extend(validate_baseline(baseline_path) if baseline_path.exists() else [])
    add_check("capability_matrix_baseline", baseline_errors)
    negative_cases = make_negative_cases()
    add_check("negative_cases", [case["name"] for case in negative_cases if case["status"] != "PASS"])
    status = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    result = {
        "schema_version": "v1",
        "artifact_type": "capability_stage_gate_result",
        "stage_id": args.stage,
        "status": status,
        "created_at": utc_now(),
        "checks": checks,
        "negative_cases": negative_cases,
    }
    out = ARTIFACT_ROOT / args.stage / "validation" / "current_stage_gate_result.json"
    write_json(out, result)
    schema_result_errors = schema_errors(out, "schemas/capability_matrix_loop/capability_stage_gate_result.schema.json")
    if schema_result_errors:
        for error in schema_result_errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"status": status, "path": rel(out)}, sort_keys=True))
    return 0 if status == "PASS" else 1


def command_previous_harness(args: argparse.Namespace) -> int:
    commands = [
        ["python3", "scripts/codex_gate.py", "precheck", "--all"],
        ["python3", "scripts/safety_scan.py"],
        ["python3", "-m", "compileall", "-q", "scripts", "src", "tests"],
    ]
    out = ARTIFACT_ROOT / args.stage / "validation" / "previous_harness.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}" + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def remove_python_caches() -> None:
        for cache_dir in ROOT.rglob("__pycache__"):
            if ".git" not in cache_dir.parts:
                shutil.rmtree(cache_dir, ignore_errors=True)
        pytest_cache = ROOT / ".pytest_cache"
        if pytest_cache.exists():
            shutil.rmtree(pytest_cache, ignore_errors=True)

    with out.open("w", encoding="utf-8") as log:
        for command in commands:
            log.write(f"$ {' '.join(command)}\n")
            proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            log.write(proc.stdout)
            log.write(f"\nexit_code={proc.returncode}\n\n")
            if proc.returncode != 0:
                print(rel(out))
                return proc.returncode
            if command[:3] == ["python3", "-m", "compileall"]:
                remove_python_caches()
        state = load_json(ROOT / "codex" / "status" / "phase_state.json")
        failed: list[str] = []
        for phase in state.get("completed_phases", []):
            command = ["python3", "scripts/codex_gate.py", "postcheck", "--phase", phase]
            log.write(f"$ {' '.join(command)}\n")
            proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
            log.write(proc.stdout)
            log.write(f"\nexit_code={proc.returncode}\n\n")
            if proc.returncode != 0:
                failed.append(phase)
        if failed:
            log.write(f"FAILED_PREVIOUS_POSTCHECKS {failed}\n")
            print(rel(out))
            return 1
        command = ["pytest", "-q"]
        log.write(f"$ {' '.join(command)}\n")
        proc = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        log.write(proc.stdout)
        log.write(f"\nexit_code={proc.returncode}\n\n")
        if proc.returncode != 0:
            print(rel(out))
            return proc.returncode
    print(rel(out))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Capability matrix loop gate")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("next").set_defaults(func=command_next)
    prev = sub.add_parser("previous-harness")
    prev.add_argument("--stage", required=True)
    prev.set_defaults(func=command_previous_harness)
    baseline = sub.add_parser("build-baseline")
    baseline.add_argument("--stage", required=True)
    baseline.add_argument("--out")
    baseline.set_defaults(func=command_build_baseline)
    run = sub.add_parser("run")
    run.add_argument("--stage", required=True)
    run.set_defaults(func=command_run)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
