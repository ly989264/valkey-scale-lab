#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import phase_by_id, validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402


def require_reason(row: dict[str, Any], label: str, errors: list[str]) -> None:
    status = row.get("status")
    if status in {"MISSING", "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"} and not row.get("reason"):
        errors.append(f"{label}: {status} requires reason")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()

    manifest = load_json(ROOT / "codex" / "phase_manifest.json")
    phase = phase_by_id(manifest, args.phase)
    errors: list[str] = []
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True):
            errors.extend(validate_artifact(ROOT / artifact["path"], ROOT / artifact["schema"]))

    base = ROOT / "artifacts" / "phases" / args.phase
    quant_path = base / "quant_summary.json"
    if quant_path.exists():
        quant = load_json(quant_path)
        for idx, item in enumerate(quant.get("missing_data", [])):
            require_reason(item, f"quant_summary.missing_data[{idx}]", errors)
    if phase.get("real_valkey_required"):
        for name in ["events.jsonl", "metrics_timeseries.jsonl", "workload_windows.json", "cleanup_report.json", "valkey_e2e_evidence.json"]:
            if not (base / name).exists():
                errors.append(f"{args.phase}: required real-stage artifact missing: {name}")
        if (base / "cleanup_report.json").exists():
            cleanup = load_json(base / "cleanup_report.json")
            if cleanup.get("status") != "PASS":
                errors.append("cleanup_report status must be PASS")
            if cleanup.get("resources_remaining"):
                errors.append("cleanup_report resources_remaining must be empty")
    if (base / "events.jsonl").exists():
        errors.extend(validate_artifact(base / "events.jsonl", ROOT / "schemas/artifact/goal_loop_event.schema.json"))
    if (base / "metrics_timeseries.jsonl").exists():
        errors.extend(validate_artifact(base / "metrics_timeseries.jsonl", ROOT / "schemas/artifact/goal_loop_metric_sample.schema.json"))
        for lineno, line in enumerate((base / "metrics_timeseries.jsonl").read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if obj.get("metric_value") == "MISSING" and not obj.get("missing_reason"):
                errors.append(f"metrics_timeseries.jsonl:{lineno}: MISSING metric_value requires missing_reason")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS quant artifacts phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
