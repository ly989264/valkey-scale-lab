from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from valkey_scale_lab.runtime import docker_runtime


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_l09_stability_timeseries_schema_accepts_generated_rows(tmp_path: Path, monkeypatch) -> None:
    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        if args[0] == "INFO":
            return "used_memory:1000\nconnected_clients:1\ntotal_commands_processed:42\n"
        if args[0] == "CLUSTER":
            return "cluster_state:ok\ncluster_known_nodes:2\n"
        return "OK"

    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    monkeypatch.setattr(docker_runtime, "run_container_cluster_cli", fake_cli)
    monkeypatch.setattr(docker_runtime, "_container_restart_count", lambda container: 0)
    nodes = [
        {"logical_id": "shard-0000-primary", "container_name": "c1"},
        {"logical_id": "shard-0001-primary", "container_name": "c2"},
    ]
    docker_runtime.write_stability_artifacts(
        tmp_path,
        "P11_STABILITY_SOAK",
        "stability_soak_smoke",
        "run",
        {"workload": {}},
        nodes,
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_json_schema.py",
            "--schema",
            "schemas/artifact/stability_timeseries_sample.schema.json",
            "--instance",
            str(tmp_path / "stability_metrics.jsonl"),
            "--jsonl",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((tmp_path / "stability_report.json").read_text(encoding="utf-8"))
    for window in ["baseline", "steady", "fault", "recovery", "post_recovery"]:
        latency = report["summary"]["windows"][window]["workload"]["latency_ms"]
        assert latency["p50"] <= latency["p95"] <= latency["p99"]
        taxonomy = report["summary"]["windows"][window]["errors"]["taxonomy"]
        assert set(taxonomy["categories"]) >= {
            "none",
            "workload_error",
            "timeout",
            "cluster_unavailable",
            "fault_expected",
            "recovery_error",
            "unknown",
        }
