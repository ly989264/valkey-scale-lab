#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from codex_gate import validate_artifact  # noqa: E402
from schema_validator import load_json  # noqa: E402

EXPECTED = {
    "P20_FAILOVER_LATENCY_CURVE_30_50_100": {"rungs": {30, 50, 100}, "sample_file": "failover_latency_samples.jsonl", "curve_file": "failover_latency_curve.json"},
    "P21_FAILOVER_LATENCY_CURVE_200": {"rungs": {200}, "sample_file": "failover_latency_samples_200.jsonl", "curve_file": "failover_latency_curve_200.json"},
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    spec = EXPECTED.get(args.phase)
    if not spec:
        print(f"PASS failover latency curve not required for phase={args.phase}")
        return 0

    base = ROOT / "artifacts" / "phases" / args.phase
    sample_path = base / spec["sample_file"]
    curve_path = base / spec["curve_file"]
    errors: list[str] = []
    errors.extend(validate_artifact(sample_path, ROOT / "schemas/artifact/failover_latency_sample.schema.json"))
    errors.extend(validate_artifact(curve_path, ROOT / "schemas/artifact/failover_latency_curve.schema.json"))
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200":
        preflight = base / "resource_preflight_200.json"
        if not preflight.exists():
            errors.append("P21 requires resource_preflight_200.json")
        elif load_json(preflight).get("status") != "PASS":
            errors.append("P21 resource preflight must PASS or the stage is blocked")
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1

    samples = load_jsonl(sample_path)
    counts = {rung: 0 for rung in spec["rungs"]}
    for sample in samples:
        node_count = int(sample.get("node_count", -1))
        if node_count not in counts:
            errors.append(f"unexpected failover sample node_count={node_count}")
            continue
        counts[node_count] += 1
        for field in ["fault_injected_at_ms", "replica_promoted_at_ms", "slot_coverage_ok_at_ms", "first_successful_read_at_ms", "first_successful_write_at_ms"]:
            if sample.get(field) == "MISSING":
                errors.append(f"{sample.get('sample_id')}: required timestamp {field} is MISSING")
        if not sample.get("workload_impact_ref"):
            errors.append(f"{sample.get('sample_id')}: workload_impact_ref required")
    for rung, count in counts.items():
        if count < 3:
            errors.append(f"rung {rung} requires at least 3 samples, got {count}")
    curve = load_json(curve_path)
    if set(curve.get("rungs", [])) != spec["rungs"]:
        errors.append(f"curve rungs must be {sorted(spec['rungs'])}")
    if args.phase == "P21_FAILOVER_LATENCY_CURVE_200" and any(sample.get("node_count") != 200 for sample in samples):
        errors.append("P21 samples must not downshift below 200 nodes")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS failover latency curve phase={args.phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
