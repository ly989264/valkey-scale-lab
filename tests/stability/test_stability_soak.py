from __future__ import annotations

from pathlib import Path

from valkey_scale_lab.runtime import docker_runtime


def test_stability_artifacts_encode_bounded_soak_and_baseline(tmp_path: Path, monkeypatch) -> None:
    calls = {"workload": 0}

    def fake_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        command = args[0]
        if command == "INFO":
            return "used_memory:1000\nconnected_clients:1\ntotal_commands_processed:42\n"
        if command == "CLUSTER":
            return "cluster_state:ok\ncluster_known_nodes:2\n"
        return "OK"

    def fake_cluster_cli(container: str, *args, timeout: int = 60, check: bool = True) -> str:
        calls["workload"] += 1
        return "OK" if args[0] == "SET" else "value"

    monkeypatch.setattr(docker_runtime, "run_container_cli", fake_cli)
    monkeypatch.setattr(docker_runtime, "run_container_cluster_cli", fake_cluster_cli)
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

    report = docker_runtime.json.loads((tmp_path / "stability_report.json").read_text(encoding="utf-8"))
    baseline = docker_runtime.json.loads((tmp_path / "stability_baseline_comparison.json").read_text(encoding="utf-8"))
    metrics = (tmp_path / "stability_metrics.jsonl").read_text(encoding="utf-8").strip().splitlines()

    assert report["status"] == "PASS"
    assert report["soak_profile"]["bounded"] is True
    assert report["soak_profile"]["long_run_stability_claim"] is False
    assert report["soak_profile"]["windows"] == ["baseline", "steady", "fault", "recovery", "post_recovery"]
    assert report["summary"]["metrics"]["sample_count"] == 10
    assert set(report["summary"]["windows"]) == {"baseline", "steady", "fault", "recovery", "post_recovery"}
    assert all(window["bounded"] is True for window in report["summary"]["windows"].values())
    assert all(window["long_run_stability_claim"] is False for window in report["summary"]["windows"].values())
    assert report["summary"]["restarts"]["total_restart_delta"] == 0
    assert report["summary"]["baseline"]["status"] == "NO_BASELINE_YET"
    assert baseline["status"] == "NO_BASELINE_YET"
    assert len(metrics) == 10
    parsed = [docker_runtime.json.loads(line) for line in metrics]
    assert {row["window"] for row in parsed} == {"baseline", "steady", "fault", "recovery", "post_recovery"}
    assert all(row["bounded"] is True for row in parsed)
    assert calls["workload"] == 60


def test_memory_growth_summary_marks_missing_with_too_few_samples() -> None:
    summary = docker_runtime._memory_growth_summary({"node-a": [1], "node-b": [1, 3]})
    assert summary["max_growth_bytes"] == 2
    assert summary["nodes"][0]["status"] == "MISSING"
    assert summary["nodes"][1]["growth_bytes"] == 2
