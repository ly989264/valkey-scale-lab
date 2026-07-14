from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.goal.contracts import ContractError
from valkey_scale_lab.goal.digests import sha256_file
from valkey_scale_lab.goal.migration import (
    V6_EVALUATOR_PATHS,
    V6_KERNEL_PATHS,
    V6_OBJECTIVES,
    _legacy_files_digest,
    _legacy_input_digest,
    verify_v6_terminal_state,
)
from valkey_scale_lab.goal.store import StateStore


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _source(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    workspace = tmp_path
    control = project / "codex/meta_m1_v6/control_block.json"
    capture_inputs = ["src", "scripts", "../loop_evidence/meta_runs/milestone1-v6/evidence/scale-200"]
    _write(control, json.dumps({"objectives": [{"checks": [{"id": "exact-real-200-capture", "inputs": capture_inputs}]}]}) + "\n")
    for raw in (*V6_KERNEL_PATHS, *V6_EVALUATOR_PATHS):
        _write(project / raw, f"# {raw}\n")
    for scale, run in ((50, "milestone1-v5"), (200, "milestone1-v6")):
        base = workspace / f"loop_evidence/meta_runs/{run}/evidence/scale-{scale}"
        artifact = base / "runtime/source.json"
        _write(artifact, json.dumps({"scale": scale}) + "\n")
        admission = {
            "status": "PASS",
            "requested_nodes": scale,
            "observed_nodes": scale,
            "product_digest": "1" * 64,
            "artifacts": [{"kind": "source", "path": "runtime/source.json", "sha256": sha256_file(artifact)}],
        }
        _write(base / "admission.json", json.dumps(admission) + "\n")
    state_root = workspace / "loop_evidence/meta_runs/milestone1-v6"
    store = StateStore(state_root)
    scale50 = workspace / "loop_evidence/meta_runs/milestone1-v5/evidence/scale-50"
    scale200_input = _legacy_input_digest(project, workspace, (capture_inputs[-1],))
    capture_input = __import__("hashlib").sha256((("1" * 64) + scale200_input).encode()).hexdigest()
    state = {
        "schema_version": "v6",
        "goal_id": "milestone1-local-complete-v6",
        "control_digest": sha256_file(control),
        "kernel_digest": _legacy_files_digest(project, V6_KERNEL_PATHS),
        "evaluator_digest": _legacy_files_digest(project, V6_EVALUATOR_PATHS),
        "active_work_item": None,
        "iteration": 9,
        "cache": {
            "50": {"check_id": "exact-real-50-admission-final", "status": "PASS"},
            "200-capture": {"check_id": "exact-real-200-capture", "status": "PASS", "input_digest": capture_input},
            "200-admit": {"check_id": "exact-real-200-admission", "status": "PASS"},
        },
        "migration": {"status": "PASS", "scale50_evidence_digest": __import__("valkey_scale_lab.goal.digests", fromlist=["tree_digest"]).tree_digest(scale50)},
        "objectives": {objective: {"status": "COMPLETE", "attempts": 99} for objective in V6_OBJECTIVES},
        "events": [],
        "last_event_hash": None,
    }
    store.append_event(state, {"schema_version": "v6", "event": "OBJECTIVE_COMPLETE", "iteration": 9})
    store.save(state)
    return project, workspace, store.state_path


def test_terminal_v6_migration_verifies_anchors_and_evidence(tmp_path: Path) -> None:
    project, workspace, source = _source(tmp_path)
    receipt = verify_v6_terminal_state(project, workspace, source)
    assert receipt.source_state_sha256 == sha256_file(source)
    assert [item["scale"] for item in receipt.evidence] == [50, 200]
    assert not hasattr(receipt, "cache")


def test_terminal_v6_migration_rejects_evidence_hash_change(tmp_path: Path) -> None:
    project, workspace, source = _source(tmp_path)
    artifact = workspace / "loop_evidence/meta_runs/milestone1-v6/evidence/scale-200/runtime/source.json"
    artifact.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ContractError, match="artifact hash mismatch"):
        verify_v6_terminal_state(project, workspace, source)
