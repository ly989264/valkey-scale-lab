from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import ModuleType


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_goal_loop_manifest_policy_allows_only_named_exceptions() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()

    assert gate.validate_manifest(manifest) == []

    by_id = {phase["id"]: phase for phase in manifest["phases"]}
    assert by_id["P15_GOAL_REBASE_HARNESS_EXTENSION"]["real_valkey_required"] is False
    assert by_id["P21_FAILOVER_LATENCY_CURVE_200"]["max_nodes"] == 200

    mutated = copy.deepcopy(manifest)
    by_id = {phase["id"]: phase for phase in mutated["phases"]}
    by_id["P22_FAULT_REPLICA_HOST_AZ_STOP"]["max_nodes"] = 200
    errors = gate.validate_manifest(mutated)
    assert any("P22_FAULT_REPLICA_HOST_AZ_STOP exceeds default 100-node cap" in error for error in errors)


def test_goal_loop_manifest_rejects_recursive_run_and_postcheck_gates() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()
    mutated = copy.deepcopy(manifest)
    phase = next(p for p in mutated["phases"] if p["id"] == "P15_GOAL_REBASE_HARNESS_EXTENSION")
    phase["gates"].append(
        {
            "name": "bad_recursive_gate",
            "kind": "harness",
            "command": "python3 scripts/codex_gate.py run --phase P15_GOAL_REBASE_HARNESS_EXTENSION",
            "timeout_seconds": 120,
            "required": True,
            "real_valkey": False,
        }
    )

    errors = gate.validate_manifest(mutated)
    assert any("recursive codex_gate run/postcheck is not allowed" in error for error in errors)


def test_goal_loop_manifest_preserves_p14_non_automatic() -> None:
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()
    mutated = copy.deepcopy(manifest)
    phase = next(p for p in mutated["phases"] if p["id"] == "P14_SCALE_1000_OPTIN_DRYRUN")
    phase["automatic"] = True

    errors = gate.validate_manifest(mutated)
    assert any("P14 must not be automatic" in error for error in errors)


def test_goal_loop_assertion_stage_table_matches_manifest() -> None:
    assertion = load_script("assert_goal_loop_stage")
    gate = load_script("codex_gate")
    manifest = gate.load_manifest()
    phases = assertion.phase_map(manifest)

    expected_ids = [stage["id"] for stage in assertion.GOAL_STAGES]
    assert expected_ids == [phase["id"] for phase in manifest["phases"][-12:]]
    assert phases["P15_GOAL_REBASE_HARNESS_EXTENSION"]["fake_only_allowed"] is True
    assert phases["P21_FAILOVER_LATENCY_CURVE_200"]["max_nodes"] == 200
    p21_real_gates = [gate for gate in phases["P21_FAILOVER_LATENCY_CURVE_200"]["gates"] if gate.get("real_valkey")]
    assert p21_real_gates
    for gate_entry in p21_real_gates:
        command = gate_entry["command"]
        assert "scale_100.yaml" not in command
        assert "scale_200.yaml" in command
        assert "--min-nodes 200" in command
