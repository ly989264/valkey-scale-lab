from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "github-coverage-gates.yml"
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import fault_failover_gate  # noqa: E402


def test_fault_failover_scale_gate_in_workflow_after_scale_build_audit() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 scripts/audit_fault_failover_scale.py --out artifacts/loop_engineering/reports/fault_failover_scale.json" in workflow
    scale_build_pos = workflow.index("python3 scripts/audit_scale_build_metrics.py --root . --out artifacts/loop_engineering/reports/scale_build_metrics.json")
    l08_pos = workflow.index("python3 scripts/audit_fault_failover_scale.py --out artifacts/loop_engineering/reports/fault_failover_scale.json")
    coverage_pos = workflow.index("python3 scripts/build_metric_coverage_matrix.py --out-dir artifacts/loop_engineering/reports")
    assert scale_build_pos < l08_pos < coverage_pos


def test_l08_stage_command_log_does_not_execute_p14() -> None:
    command_log = REPO_ROOT / "artifacts" / "loop_engineering" / "stages" / "L08_30_50_100_FAULT_FAILOVER_SCENARIOS" / "commands.jsonl"
    if command_log.exists():
        rows = [json.loads(line) for line in command_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        commands = [" ".join(str(part) for part in row.get("command", [])) for row in rows]
        assert commands
        for forbidden in ["VSLAB_ALLOW_1000_DRYRUN", "scale_1000", "P14_SCALE_1000_OPTIN_DRYRUN"]:
            assert all(forbidden not in command for command in commands)


def test_l08_worktree_has_no_cache_or_scratch_pollution() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    polluted = []
    for tracked_path in completed.stdout.split("\0"):
        if not tracked_path:
            continue
        path = Path(tracked_path)
        if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
            polluted.append(tracked_path)
        elif any(part.startswith("_fault_failover_work_") for part in path.parts):
            polluted.append(tracked_path)
        elif path.suffix == ".pyc":
            polluted.append(tracked_path)
    assert polluted == []


def test_l08_real_fault_failover_pass_entries_have_positive_duration() -> None:
    command_log = REPO_ROOT / "artifacts" / "loop_engineering" / "stages" / "L08_30_50_100_FAULT_FAILOVER_SCENARIOS" / "commands.jsonl"
    if not command_log.exists():
        return

    rows = [json.loads(line) for line in command_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    real_gate_rows = [
        row
        for row in rows
        if row.get("status") == "PASS"
        and row.get("command", [])[:2] == ["python3", "scripts/fault_failover_gate.py"]
        and "--min-nodes" in row.get("command", [])
        and row["command"][row["command"].index("--min-nodes") + 1] in {"30", "50", "100"}
    ]
    assert real_gate_rows

    for row in real_gate_rows:
        started = datetime.fromisoformat(row["started_at"].removesuffix("Z") + "+00:00")
        finished = datetime.fromisoformat(row["finished_at"].removesuffix("Z") + "+00:00")
        assert finished > started


def test_l08_latest_real_fault_failover_runs_require_data_path() -> None:
    command_log = REPO_ROOT / "artifacts" / "loop_engineering" / "stages" / "L08_30_50_100_FAULT_FAILOVER_SCENARIOS" / "commands.jsonl"
    if not command_log.exists():
        return

    rows = [json.loads(line) for line in command_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    latest_by_node_count: dict[str, dict] = {}
    for row in rows:
        command = row.get("command", [])
        if (
            row.get("status") == "PASS"
            and command[:2] == ["python3", "scripts/fault_failover_gate.py"]
            and "--min-nodes" in command
        ):
            node_count = command[command.index("--min-nodes") + 1]
            if node_count in {"30", "50", "100"}:
                latest_by_node_count[node_count] = row

    assert sorted(latest_by_node_count) == ["100", "30", "50"]
    for row in latest_by_node_count.values():
        assert "--require-data-path" in row["command"]


def test_fault_failover_gate_enforces_require_data_path_flag() -> None:
    source = (REPO_ROOT / "scripts" / "fault_failover_gate.py").read_text(encoding="utf-8")
    assert "if args.require_data_path and data_path_result != \"PASS\":" in source
    assert "required data path proof missing" in source


def test_workload_target_uses_selected_primary_slot() -> None:
    endpoint = fault_failover_gate.Endpoint(logical_id="shard-0007-primary", host="127.0.0.1", port=7007)
    probes = [
        {
            "status": "PASS",
            "logical_id": "shard-0007-primary",
            "myself_node_id": "node-7",
            "cluster_nodes": {
                "node-7": {
                    "role": "primary",
                    "flags": ["myself", "master"],
                    "slots": ["2000-2400"],
                }
            },
        }
    ]

    target = fault_failover_gate.workload_target_for_logical([endpoint], probes, "shard-0007-primary")

    assert target is not None
    assert target["scope"] == "failed_primary_slot"
    assert target["source_logical_id"] == "shard-0007-primary"
    assert 2000 <= target["slot"] <= 2400


def test_workload_window_fails_get_mismatch(monkeypatch) -> None:
    endpoint = fault_failover_gate.Endpoint(logical_id="shard-0007-primary", host="127.0.0.1", port=7007)
    target = {
        "scope": "failed_primary_slot",
        "source_logical_id": "shard-0007-primary",
        "source_node_id": "node-7",
        "slot_range": [2000, 2400],
        "slot_key": "{w117}",
        "slot": fault_failover_gate.key_slot("{w117}"),
        "entry_logical_id": "shard-0007-primary",
    }

    def fake_execute(endpoints, entry_endpoint, *command):
        if command[0] == "SET":
            return "OK", entry_endpoint, 0
        return "wrong-value", entry_endpoint, 0

    monkeypatch.setattr(fault_failover_gate, "execute_workload_command", fake_execute)

    window = fault_failover_gate.workload_window("before_fault", [endpoint], 1, "test-run", target)

    assert window["status"] == "MEASURED"
    assert window["roundtrip_successes"] == 0
    assert window["roundtrip_failures"] == 1
    assert window["errors_total"] == 1
    assert any(sample["command"] == "GET" and sample["status"] == "FAIL" for sample in window["samples"])
