#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
P15 = "P15_GOAL_REBASE_HARNESS_EXTENSION"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit harness-only artifacts for the P15 goal-loop bootstrap stage")
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    if args.phase != P15:
        raise SystemExit(f"goal_loop_harness_artifacts.py is only valid for {P15}")

    out_dir = ROOT / "artifacts" / "phases" / args.phase
    created_at = utc_now()
    run_id = f"{args.phase}-harness-bootstrap"
    phase_summary_path = out_dir / "phase_summary.json"
    quant_summary_path = out_dir / "quant_summary.json"
    required_artifacts = [
        f"artifacts/phases/{args.phase}/phase_summary.json",
        f"artifacts/phases/{args.phase}/quant_summary.json",
    ]

    write_json(
        phase_summary_path,
        {
            "schema_version": "v1",
            "artifact_type": "phase_summary",
            "phase_id": args.phase,
            "run_id": run_id,
            "created_at": created_at,
            "producer": {"name": "scripts/goal_loop_harness_artifacts.py", "version": "v1"},
            "status": "PASS",
            "summary": "P15 extended the goal-loop harness scaffolding only; it does not claim management, fault, or real Valkey runtime behavior.",
            "required_artifacts": required_artifacts,
            "missing_metrics": [
                {
                    "metric": "real_valkey_runtime_evidence",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P15 is a harness-scaffolding stage and is explicitly exempt from real Valkey runtime evidence.",
                    "impact": "Future P16-P26 stages remain real-Valkey-gated in the manifest.",
                }
            ],
            "risks": [
                {
                    "risk": "Future-stage gates are fail-closed placeholders until their runtime implementations are added.",
                    "severity": "medium",
                    "mitigation": "P16-P26 manifest entries require real wrapper gates and assertion scripts before completion.",
                }
            ],
            "harness_only": True,
            "real_valkey_claimed": False,
        },
    )
    write_json(
        quant_summary_path,
        {
            "schema_version": "v1",
            "artifact_type": "quant_summary",
            "phase_id": args.phase,
            "run_id": run_id,
            "created_at": created_at,
            "producer": {"name": "scripts/goal_loop_harness_artifacts.py", "version": "v1"},
            "status": "PASS",
            "summary": "P15 generated quantitative metadata for harness coverage only. No runtime measurements were collected or claimed.",
            "artifact_refs": required_artifacts,
            "missing_data": [
                {
                    "field": "events.jsonl",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P15 does not execute a Valkey scenario.",
                },
                {
                    "field": "metrics_timeseries.jsonl",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P15 does not collect runtime metrics.",
                },
                {
                    "field": "workload_windows.json",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P15 does not run a workload.",
                },
            ],
            "runtime_claims": {
                "real_valkey_claimed": False,
                "management_runtime_claimed": False,
                "fault_runtime_claimed": False,
            },
            "stage_coverage": {
                "manifest_entries_added": ["P15", "P16", "P17", "P18", "P19", "P20", "P21", "P22", "P23", "P24", "P25", "P26"],
                "automatic_stop_after": "P26_FINAL_REPORT_REGRESSION",
                "p14_preserved_non_automatic": True,
                "default_max_nodes": 100,
                "bounded_200_node_exception": "P21_FAILOVER_LATENCY_CURVE_200",
            },
        },
    )
    print(f"WROTE {phase_summary_path.relative_to(ROOT)}")
    print(f"WROTE {quant_summary_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
