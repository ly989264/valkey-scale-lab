#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TIMEOUTS = [5000, 10000, 15000, 30000, 60000]


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit failover RTO cluster-node-timeout matrix runner")
    parser.add_argument("--phase", default="P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--node-count", type=int, required=True)
    parser.add_argument("--timeout-ms", type=int, action="append", dest="timeouts", default=[])
    parser.add_argument("--execute", action="store_true", help="Run real fault_failover_gate cells. Without this, selected cells are NOT_RUN_WITH_REASON.")
    parser.add_argument("--require-data-path", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    selected = args.timeouts or []
    for timeout in selected:
        if timeout not in ALLOWED_TIMEOUTS:
            errors.append(f"timeout {timeout} is not in configured matrix {ALLOWED_TIMEOUTS}")
            continue
        rows.append(_run_or_record_cell(args, timeout, out.parent))
    if not selected:
        rows.append(_not_run_row(args.node_count, 30000, "No timeout cells selected; runner is explicit by design."))

    status = "FAIL" if errors else ("PASS" if rows and all(row.get("status") == "PASS" for row in rows) else "NOT_RUN_WITH_REASON")
    report = {
        "schema_version": "v1",
        "artifact_type": "timeout_matrix_report",
        "phase_id": args.phase,
        "status": status,
        "configured_matrix_ms": ALLOWED_TIMEOUTS,
        "selection_policy": "explicit_timeout_ms_required",
        "rows": rows,
        "errors": errors,
    }
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"WROTE timeout matrix report rows={len(rows)} out={out}")
    return 0


def _run_or_record_cell(args: argparse.Namespace, timeout: int, base: Path) -> dict[str, Any]:
    if not args.execute:
        return _not_run_row(args.node_count, timeout, "Selected matrix cell was not executed because --execute was not set.")
    scenario = f"p43_timeout_matrix_{args.node_count}_{timeout}"
    evidence = base / f"timeout_matrix_{args.node_count}_{timeout}_evidence.json"
    failover = base / f"timeout_matrix_{args.node_count}_{timeout}_failover.json"
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "fault_failover_gate.py"),
        "--phase",
        args.phase,
        "--scenario",
        scenario,
        "--config",
        args.config,
        "--out",
        str(evidence),
        "--failover-report",
        str(failover),
        "--min-nodes",
        str(args.node_count),
        "--timeout-config-ms",
        str(timeout),
    ]
    if args.require_data_path:
        cmd.append("--require-data-path")
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
    (base / f"timeout_matrix_{args.node_count}_{timeout}.stdout.log").write_text(proc.stdout, encoding="utf-8", errors="replace")
    (base / f"timeout_matrix_{args.node_count}_{timeout}.stderr.log").write_text(proc.stderr, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not evidence.exists():
        row = _not_run_row(args.node_count, timeout, f"Real matrix cell failed exit={proc.returncode}; see command logs.")
        row["status"] = "BLOCKED"
        return row
    data = json.loads(evidence.read_text(encoding="utf-8"))
    return {
        "status": "PASS" if data.get("status") == "PASS" else "FAIL",
        "node_count": args.node_count,
        "nodes_observed": data.get("nodes_observed", "MISSING"),
        "real_valkey": data.get("real_valkey", False),
        "timeout_config_ms": timeout,
        "kill_to_pfail_ms": data.get("kill_to_pfail_ms", "MISSING"),
        "pfail_to_cluster_ok_ms": data.get("pfail_to_cluster_ok_ms", "MISSING"),
        "kill_to_client_recovered_ms": data.get("kill_to_client_recovered_ms", "MISSING"),
        "false_pfail_count": data.get("false_pfail_count", "MISSING"),
        "false_failover_count": data.get("false_failover_count", "MISSING"),
        "static_artifact": False,
        "evidence_refs": [evidence.as_posix(), failover.as_posix()],
    }


def _not_run_row(node_count: int, timeout: int, reason: str) -> dict[str, Any]:
    return {
        "status": "NOT_RUN_WITH_REASON",
        "node_count": node_count,
        "timeout_config_ms": timeout,
        "kill_to_pfail_ms": "NOT_RUN_WITH_REASON",
        "pfail_to_cluster_ok_ms": "NOT_RUN_WITH_REASON",
        "kill_to_client_recovered_ms": "NOT_RUN_WITH_REASON",
        "false_pfail_count": "NOT_RUN_WITH_REASON",
        "false_failover_count": "NOT_RUN_WITH_REASON",
        "reason": reason,
        "real_valkey": False,
        "static_artifact": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
