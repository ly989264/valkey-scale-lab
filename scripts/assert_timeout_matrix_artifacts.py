#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_TIMEOUTS = {5000, 10000, 15000, 30000, 60000}
REQUIRED_FIELDS = {
    "timeout_config_ms",
    "kill_to_pfail_ms",
    "pfail_to_cluster_ok_ms",
    "kill_to_client_recovered_ms",
    "false_pfail_count",
    "false_failover_count",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()
    base = Path(args.artifact_dir) if args.artifact_dir else ROOT / "artifacts" / "phases" / args.phase
    path = base / "timeout_matrix_report.json"
    errors: list[str] = []
    if not path.exists():
        errors.append(f"missing timeout matrix report: {path}")
    else:
        _check_report(_load_json(path, errors), errors)
    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        return 1
    print(f"PASS timeout matrix artifacts phase={args.phase}")
    return 0


def _check_report(report: dict[str, Any], errors: list[str]) -> None:
    if report.get("artifact_type") != "timeout_matrix_report":
        errors.append("artifact_type must be timeout_matrix_report")
    rows = report.get("rows")
    if not isinstance(rows, list):
        errors.append("rows must be a list")
        return
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"rows[{idx}] must be object")
            continue
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            errors.append(f"rows[{idx}] missing fields {sorted(missing)}")
        timeout = row.get("timeout_config_ms")
        if timeout not in ALLOWED_TIMEOUTS:
            errors.append(f"rows[{idx}] timeout_config_ms {timeout!r} not in allowed matrix")
        status = row.get("status")
        if status == "PASS":
            if row.get("real_valkey") is not True:
                errors.append(f"rows[{idx}] PASS must cite real_valkey=true")
            if row.get("static_artifact") is True:
                errors.append(f"rows[{idx}] PASS must not be static artifact")
            if int(row.get("nodes_observed", 0) or 0) < int(row.get("node_count", 0) or 0):
                errors.append(f"rows[{idx}] silent downscale nodes_observed < node_count")
            for field in REQUIRED_FIELDS - {"timeout_config_ms"}:
                if isinstance(row.get(field), str) and row[field] in {"MISSING", "SKIPPED_WITH_REASON", "NOT_RUN_WITH_REASON"}:
                    errors.append(f"rows[{idx}] PASS cannot use {row[field]} for {field}")
            refs = row.get("evidence_refs", [])
            if not isinstance(refs, list) or not refs:
                errors.append(f"rows[{idx}] PASS must cite evidence_refs")
        elif status in {"BLOCKED", "NOT_RUN_WITH_REASON"}:
            if not row.get("reason"):
                errors.append(f"rows[{idx}] {status} must include reason")
            for field in REQUIRED_FIELDS - {"timeout_config_ms"}:
                value = row.get(field)
                if isinstance(value, (int, float)):
                    errors.append(f"rows[{idx}] {status} must not fabricate numeric {field}")
        else:
            errors.append(f"rows[{idx}] invalid status {status!r}")


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"invalid JSON {path}: {exc}")
        return {}


if __name__ == "__main__":
    raise SystemExit(main())
