from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_runtime_distribution_assertion_fails_on_over_limit_density(tmp_path: Path) -> None:
    base = tmp_path / "phase"
    density = {
        "nodehost_strategy": "density_limited",
        "max_nodehosts": 64,
        "nodehosts_per_az": 2,
        "max_logical_nodes_per_nodehost": 25,
        "actual_nodehost_count": 1,
        "logical_nodes_per_nodehost": {"nodehost-az-a-00": 26},
        "nodehost_distribution": "round_robin_by_az",
        "node_count": 26,
    }
    for name in ["nodehost_density_plan.json", "resource_preflight.json", "cluster_plan.json", "run_state.json"]:
        write_json(base / name, {"schema_version": "v1", "artifact_type": name[:-5], "status": "PASS", "nodehost_density": density})

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/assert_runtime_nodehost_distribution.py"),
            "--phase",
            "P41_NODEHOST_DENSITY_GLOBAL_CONFIG",
            "--artifact-dir",
            str(base),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert proc.returncode != 0
    assert "exceed max_logical_nodes_per_nodehost" in proc.stderr


def test_partial_coverage_assertion_fails_when_scale_rows_missing(tmp_path: Path) -> None:
    phase = "P41_NODEHOST_DENSITY_GLOBAL_CONFIG"
    base = ROOT / "artifacts" / "phases" / phase
    saved = (base / "coverage_ledger.json").read_text(encoding="utf-8") if (base / "coverage_ledger.json").exists() else None
    try:
        write_json(
            base / "coverage_ledger.json",
            {
                "schema_version": "v1",
                "artifact_type": "coverage_ledger",
                "phase_id": phase,
                "rows": [{"coverage_id": "fake_schema_unit", "status": "PASS", "artifact_refs": ["x"]}],
            },
        )
        proc = subprocess.run(
            [sys.executable, "scripts/assert_no_nodehost_partial_coverage.py", "--phase", phase],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode != 0
        assert "missing nodehost density coverage rows" in proc.stderr
    finally:
        if saved is not None:
            (base / "coverage_ledger.json").write_text(saved, encoding="utf-8")
