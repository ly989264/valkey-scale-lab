from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_all_real_valkey_report_runner_default_covers_every_real_phase_and_cml15(tmp_path: Path) -> None:
    out = tmp_path / "all_real_valkey_cluster_report_run.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_all_real_valkey_cluster_reports.py",
            "--dry-run",
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["skip_real_runs"] is False
    assert payload["real_phase_ids"] == [
        "P03_LOCAL_DOCKER_VALKEY",
        "P04_CLUSTER_MANAGEMENT_OPS",
        "P05_WORKLOAD_ENGINE",
        "P06_OBSERVABILITY_METRICS",
        "P07_FAULT_INJECTION_SANDBOX",
        "P08_FAILOVER_SPLIT_BRAIN",
        "P09_ANALYSIS_REPORTING",
        "P10_MULTI_HOST_ORCHESTRATION",
        "P11_STABILITY_SOAK",
        "P12_SCALE_LADDER_10_30",
        "P13_SCALE_LADDER_50_100",
    ]
    assert payload["cml15_stage_ids"] == [
        "CML15A_ADD_NODE_REMOVE_NODE_30",
        "CML15B_RESHARD_SLOTS_30",
        "CML15C_REBALANCE_SLOTS_30",
        "CML15D_ROLLING_RESTART_ONE_PRIMARY_30",
        "CML15E_LIFECYCLE_MATRIX_REPORT_30",
    ]
    commands = [" ".join(item["command"]) for item in payload["commands"]]
    assert any("scripts/codex_gate.py run --phase P03_LOCAL_DOCKER_VALKEY" in command for command in commands)
    assert any("scripts/codex_gate.py run --phase P13_SCALE_LADDER_50_100" in command for command in commands)
    assert any("tools/cml15_lifecycle_runner.py --stage CML15A_ADD_NODE_REMOVE_NODE_30" in command for command in commands)
    assert any("tools/cml15_lifecycle_runner.py --stage CML15E_LIFECYCLE_MATRIX_REPORT_30" in command for command in commands)
    assert any("scripts/render_audit_report.py --input-dir artifacts/loop_engineering/reports --out-dir artifacts/loop_engineering/reports" in command for command in commands)
