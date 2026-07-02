#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PHASE_MANIFEST = ROOT / "codex" / "phase_manifest.json"
CML15_STAGES = [
    "CML15A_ADD_NODE_REMOVE_NODE_30",
    "CML15B_RESHARD_SLOTS_30",
    "CML15C_REBALANCE_SLOTS_30",
    "CML15D_ROLLING_RESTART_ONE_PRIMARY_30",
    "CML15E_LIFECYCLE_MATRIX_REPORT_30",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def real_automatic_phase_ids() -> list[str]:
    manifest = load_json(PHASE_MANIFEST)
    return [
        phase["id"]
        for phase in manifest.get("phases", [])
        if phase.get("automatic", True)
        and phase.get("real_valkey_required") is True
        and phase["id"] <= manifest.get("automatic_stop_after", "P13_SCALE_LADDER_50_100")
    ]


def command_record(name: str, command: list[str], *, status: str, exit_code: int, started_at: str, duration: float) -> dict[str, Any]:
    return {
        "name": name,
        "command": command,
        "status": status,
        "exit_code": exit_code,
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": round(duration, 6),
    }


def run_command(name: str, command: list[str], *, dry_run: bool) -> dict[str, Any]:
    started = utc_now()
    t0 = time.monotonic()
    if dry_run:
        return command_record(name, command, status="SKIPPED_WITH_REASON", exit_code=0, started_at=started, duration=0.0) | {"reason": "dry run"}
    proc = subprocess.run(command, cwd=ROOT, check=False)
    return command_record(name, command, status="PASS" if proc.returncode == 0 else "FAIL", exit_code=int(proc.returncode), started_at=started, duration=time.monotonic() - t0)


def report_refresh_commands() -> list[tuple[str, list[str]]]:
    py = sys.executable
    return [
        ("committed_artifact_audit", [py, "scripts/audit_committed_artifacts.py", "--out", "artifacts/loop_engineering/reports/audit_report.json"]),
        ("provenance_graph", [py, "scripts/build_provenance_graph.py", "--out", "artifacts/loop_engineering/reports/provenance_graph.json"]),
        ("scale_build_metrics", [py, "scripts/audit_scale_build_metrics.py", "--root", ".", "--out", "artifacts/loop_engineering/reports/scale_build_metrics.json"]),
        ("fault_failover_scale", [py, "scripts/audit_fault_failover_scale.py", "--out", "artifacts/loop_engineering/reports/fault_failover_scale.json"]),
        ("metric_coverage_matrix", [py, "scripts/build_metric_coverage_matrix.py", "--out-dir", "artifacts/loop_engineering/reports"]),
        ("p13_p14_scale_audit", [py, "scripts/audit_p13_p14_scale.py", "--out", "artifacts/loop_engineering/reports/p13_p14_scale_audit.json"]),
        (
            "small_real_parity_audit",
            [
                py,
                "scripts/audit_small_real_scenario_parity.py",
                "--root",
                ".",
                "--out",
                "artifacts/loop_engineering/reports/small_real_parity_audit.json",
                "--require-fake",
                "--require-real",
                "--validate-report-views",
            ],
        ),
        ("loop_report_render", [py, "scripts/render_audit_report.py", "--input-dir", "artifacts/loop_engineering/reports", "--out-dir", "artifacts/loop_engineering/reports"]),
        (
            "loop_report_schema",
            [
                py,
                "scripts/validate_json_schema.py",
                "--schema",
                "schemas/artifact/loop_report_index.schema.json",
                "--instance",
                "artifacts/loop_engineering/reports/report_index.json",
            ],
        ),
        ("loop_report_tests", [py, "-m", "pytest", "-q", "tests/report", "tests/visualization", "tests/ci/test_loop_report_gate.py"]),
    ]


def run_all(args: argparse.Namespace) -> int:
    py = sys.executable
    commands: list[tuple[str, list[str], bool]] = []
    if not args.skip_real_runs:
        for phase_id in real_automatic_phase_ids():
            commands.append((f"phase_{phase_id}", [py, "scripts/codex_gate.py", "run", "--phase", phase_id], False))
        for stage_id in CML15_STAGES:
            commands.append((f"cml15_runner_{stage_id}", [py, "tools/cml15_lifecycle_runner.py", "--stage", stage_id], False))
            commands.append((f"cml15_gate_{stage_id}", [py, "tools/capability_matrix_gate.py", "run", "--stage", stage_id], False))
    else:
        for stage_id in CML15_STAGES:
            commands.append((f"cml15_refresh_{stage_id}", [py, "tools/cml15_lifecycle_runner.py", "--stage", stage_id, "--refresh-reports-only"], False))
            commands.append((f"cml15_gate_{stage_id}", [py, "tools/capability_matrix_gate.py", "run", "--stage", stage_id], False))

    commands.extend((name, command, False) for name, command in report_refresh_commands())

    results: list[dict[str, Any]] = []
    for name, command, dry_run in commands:
        print(f"RUN {name}: {' '.join(command)}")
        result = run_command(name, command, dry_run=args.dry_run or dry_run)
        print(f"{result['status']} {name} exit={result['exit_code']}")
        results.append(result)
        if result["status"] == "FAIL" and not args.keep_going:
            break

    status = "PASS" if results and all(result["status"] != "FAIL" for result in results) else "FAIL"
    summary = {
        "schema_version": "v1",
        "artifact_type": "all_real_valkey_cluster_report_run",
        "created_at": utc_now(),
        "status": status,
        "skip_real_runs": bool(args.skip_real_runs),
        "dry_run": bool(args.dry_run),
        "real_phase_ids": real_automatic_phase_ids(),
        "cml15_stage_ids": CML15_STAGES,
        "loop_report_index": "artifacts/loop_engineering/reports/report_index.json",
        "loop_report_html": "artifacts/loop_engineering/reports/index.html",
        "commands": results,
    }
    out = ROOT / args.out
    write_json(out, summary)
    print(f"{status} all_real_valkey_cluster_report_run out={rel(out)} report=artifacts/loop_engineering/reports/index.html")
    return 0 if status == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all automatic real Valkey cluster gates, CML15 lifecycle gates, and the aggregate report renderer.")
    parser.add_argument("--skip-real-runs", action="store_true", help="Reuse existing real Valkey artifacts and only refresh CML15/report outputs.")
    parser.add_argument("--keep-going", action="store_true", help="Continue after a failed command and report FAIL at the end.")
    parser.add_argument("--dry-run", action="store_true", help="Print and record commands without executing them.")
    parser.add_argument("--out", default="artifacts/loop_engineering/reports/all_real_valkey_cluster_report_run.json")
    return run_all(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
