from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PHASE = "P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG"


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def profile(node_count: int = 10, io_threads: int = 1) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "effective_server_profile",
        "phase_id": PHASE,
        "status": "PASS",
        "server_profile": "one_b_dev",
        "requested_io_threads": io_threads,
        "effective_io_threads": io_threads,
        "io_threads_auto": False,
        "io_threads_auto_candidate": "SKIPPED_WITH_REASON",
        "io_threads_max_per_node": 2,
        "io_threads_max_total": max(256, node_count * io_threads),
        "total_valkey_threads": node_count * io_threads,
        "io_thread_budget_status": "PASS",
        "requested_node_memory_limit_mb": 64,
        "effective_node_memory_limit_mb": 64,
        "memory_budget_status": "PASS",
        "log_format": "text",
        "runtime_memory_limit_enforced": True,
        "runtime_memory_limit_method": "valkey_maxmemory",
        "logical_node_count": node_count,
        "nodehost_count": 1,
    }


def make_phase_artifacts(base: Path, *, node_count: int = 10, io_threads: int = 1, include_io_line: bool = False) -> None:
    prof = profile(node_count=node_count, io_threads=io_threads)
    write_json(base / "effective_server_profile.json", prof)
    write_json(base / "config_validation_report.json", {**prof, "artifact_type": "config_validation_report", "server_profile": prof, "valid": True})
    checks = [
        {
            "name": "memory_budget",
            "status": "PASS",
            "details": {
                "node_count_times_node_memory_limit_mb": node_count * 64,
                "node_memory_limit_mb": 64,
                "host_available_memory_mb": 65536,
                "projected_nodehost_memory_mb": {"nodehost-0": node_count * 64},
                "can_run": True,
            },
        }
    ]
    write_json(
        base / "resource_preflight.json",
        {
            "artifact_type": "resource_preflight",
            "status": "PASS",
            "node_count": node_count,
            "can_run": True,
            "requested_io_threads": io_threads,
            "effective_io_threads": io_threads,
            "requested_node_memory_limit_mb": 64,
            "effective_node_memory_limit_mb": 64,
            "io_thread_budget_status": "PASS",
            "memory_budget_status": "PASS",
            "projected_node_memory_mb": node_count * 64,
            "projected_nodehost_memory_mb": {"nodehost-0": node_count * 64},
            "host_available_memory_mb": 65536,
            "checks": checks,
        },
    )
    nodes = [node(base, index, io_threads=io_threads, include_io_line=include_io_line) for index in range(node_count)]
    write_json(
        base / "cluster_plan.json",
        {
            "artifact_type": "cluster_plan",
            "status": "PASS",
            "node_count": node_count,
            "runtime": {"server_profile": prof, "effective_io_threads": io_threads, "effective_node_memory_limit_mb": 64},
            "effective_server_profile": prof,
            "nodes": nodes,
        },
    )
    write_json(
        base / "run_state.json",
        {
            "artifact_type": "strict_run_state",
            "status": "PASS",
            "node_count": node_count,
            "runtime": {"server_profile": prof, "effective_io_threads": io_threads, "effective_node_memory_limit_mb": 64},
            "effective_server_profile": prof,
            "nodes": nodes,
        },
    )
    write_json(
        base / "generated_valkey_configs_manifest.json",
        {
            "artifact_type": "generated_valkey_configs_manifest",
            "status": "PASS",
            "node_count": node_count,
            "entries": [
                {
                    "logical_id": item["logical_id"],
                    "config_artifact_file": item["config_artifact_file"],
                    "effective_io_threads": io_threads,
                    "effective_node_memory_limit_mb": 64,
                    "io_threads_line_required": io_threads > 1,
                    "io_threads_line_present": True if io_threads > 1 and include_io_line else "SKIPPED_WITH_REASON",
                    "maxmemory_line_present": True,
                    "runtime_memory_limit_enforced": True,
                    "runtime_memory_limit_method": "valkey_maxmemory",
                }
                for item in nodes
            ],
        },
    )
    write_json(base / "valkey_e2e_evidence.json", evidence(base / "valkey_e2e_evidence.json", node_count, io_threads, nodes, prof))


def node(base: Path, index: int, *, io_threads: int, include_io_line: bool) -> dict[str, Any]:
    config_path = base / "node_configs" / f"node-{index:04d}.conf"
    lines = ["port 7000", "cluster-enabled yes"]
    if include_io_line:
        lines.append(f"io-threads {io_threads}")
    lines.append("maxmemory 64mb")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "logical_id": f"node-{index:04d}",
        "effective_server_profile": "one_b_dev",
        "effective_io_threads": io_threads,
        "effective_node_memory_limit_mb": 64,
        "runtime_memory_limit_enforced": True,
        "runtime_memory_limit_method": "valkey_maxmemory",
        "config_artifact_file": str(config_path),
    }


def evidence(path: Path, node_count: int, io_threads: int, nodes: list[dict[str, Any]], prof: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": PHASE,
        "status": "PASS",
        "probe_result": "PASS",
        "real_valkey": True,
        "nodes_requested": node_count,
        "min_nodes_requested": node_count,
        "nodes_observed": node_count,
        "valkey_versions": ["9.1.0"],
        "runtime": {"server_profile": prof, "effective_io_threads": io_threads, "effective_node_memory_limit_mb": 64},
        "node_processes": nodes,
        "source_path": str(path),
    }


def test_io_thread_memory_assertion_rejects_missing_io_threads_line(tmp_path: Path) -> None:
    base = tmp_path / "phase"
    make_phase_artifacts(base, node_count=2, io_threads=2, include_io_line=False)

    proc = run_script("assert_io_thread_memory_evidence.py", "--phase", PHASE, "--artifact-dir", str(base))

    assert proc.returncode != 0
    assert "missing io-threads 2" in proc.stderr


def test_io_thread_memory_assertion_accepts_io_threads_one_without_config_line(tmp_path: Path) -> None:
    base = tmp_path / "phase"
    make_phase_artifacts(base, node_count=2, io_threads=1, include_io_line=False)

    proc = run_script("assert_io_thread_memory_evidence.py", "--phase", PHASE, "--artifact-dir", str(base))

    assert proc.returncode == 0, proc.stderr


def test_partial_coverage_assertion_rejects_missing_real_scales(tmp_path: Path) -> None:
    base = tmp_path / "phase"
    write_json(
        base / "coverage_ledger.json",
        {
            "artifact_type": "coverage_ledger",
            "rows": [{"coverage_id": "fake_schema_unit", "status": "PASS", "execution_mode": "unit_schema", "artifact_refs": ["tests/unit/test_server_profile_assertions.py"]}],
        },
    )

    proc = run_script("assert_no_server_profile_partial_coverage.py", "--phase", PHASE, "--artifact-dir", str(base))

    assert proc.returncode != 0
    assert "missing server profile coverage rows" in proc.stderr


def test_partial_coverage_assertion_accepts_real_and_dry_run_rows(tmp_path: Path) -> None:
    base = tmp_path / "phase"
    rows = [{"coverage_id": "fake_schema_unit", "status": "PASS", "execution_mode": "unit_schema", "artifact_refs": ["tests/unit/test_server_profile_assertions.py"]}]
    for coverage_id, count, name in [
        ("smoke_10", 10, "valkey_e2e_evidence.json"),
        ("real_30", 30, "valkey_e2e_evidence_30.json"),
        ("real_50", 50, "valkey_e2e_evidence_50.json"),
        ("real_100", 100, "valkey_e2e_evidence_100.json"),
        ("real_200", 200, "valkey_e2e_evidence_200.json"),
    ]:
        nodes = [node(base / str(count), index, io_threads=1, include_io_line=False) for index in range(count)]
        prof = profile(node_count=count)
        path = base / name
        write_json(path, evidence(path, count, 1, nodes, prof))
        rows.append({"coverage_id": coverage_id, "status": "PASS", "execution_mode": "real_valkey", "artifact_refs": [str(path)]})
    projection = {
        "artifact_type": "cluster_plan",
        "status": "PASS",
        "node_count": 1000,
        "dry_run": True,
        "real_valkey": False,
        "runtime_resources_created": False,
        "runtime": {"dry_run": True, "server_profile": profile(node_count=1000)},
        "effective_server_profile": profile(node_count=1000),
    }
    write_json(base / "dry_run_gt_200_projection.json", projection)
    rows.append({"coverage_id": "dry_run_gt_200", "status": "DRY_RUN_PASS", "execution_mode": "dry_run_projection", "artifact_refs": [str(base / "dry_run_gt_200_projection.json")]})
    write_json(base / "coverage_ledger.json", {"artifact_type": "coverage_ledger", "rows": rows})

    proc = run_script("assert_no_server_profile_partial_coverage.py", "--phase", PHASE, "--artifact-dir", str(base))

    assert proc.returncode == 0, proc.stderr


def test_server_profile_config_assertion_rejects_blind_global_io_threads_six(tmp_path: Path) -> None:
    global_config = tmp_path / "global.yaml"
    global_config.write_text(
        """
runtime:
  server_profile: one_b_dev
  valkey:
    io_threads: 6
    io_threads_auto: false
    io_threads_max_per_node: 6
    io_threads_max_total: 256
    log_format: text
cluster:
  node_memory_limit_mb: 64
""",
        encoding="utf-8",
    )
    scenario = tmp_path / "scale_10.yaml"
    scenario.write_text((ROOT / "templates/configs/scale_10.yaml").read_text(encoding="utf-8"), encoding="utf-8")

    proc = run_script(
        "assert_server_profile_config.py",
        "--phase",
        PHASE,
        "--global-config",
        str(global_config),
        "--config",
        str(scenario),
        "--artifact-dir",
        str(tmp_path / "missing_artifacts_ok"),
    )

    assert proc.returncode != 0
    assert "io_threads >= 6" in proc.stderr
