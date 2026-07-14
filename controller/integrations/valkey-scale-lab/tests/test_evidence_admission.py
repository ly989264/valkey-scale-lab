from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = INTEGRATION_ROOT.parents[2]
PROJECT_ROOT = REPOSITORY_ROOT / "project"
EVALUATOR_ROOT = INTEGRATION_ROOT / "evaluators"
MILESTONE_PATH = PROJECT_ROOT / "milestones/m1/milestone.json"
CANDIDATE_SCHEMA_PATH = PROJECT_ROOT / "schemas/artifact/evidence_admission_candidate.schema.json"


def _module(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


POLICY = _module("tested_valkey_admission", EVALUATOR_ROOT / "evidence_admission.py")
COMMON = _module("tested_valkey_common", EVALUATOR_ROOT / "_common.py")

sys.path.insert(0, str(PROJECT_ROOT / "src"))
try:
    from valkey_scale_lab.evidence import build_candidate_admission, canonical_bundle_spec
    from valkey_scale_lab.scenarios import load_local_full_flow_definition
finally:
    sys.path.pop(0)


DEFINITION = load_local_full_flow_definition()
SPEC = canonical_bundle_spec(DEFINITION)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _raw_bundle(root: Path, nodes: int, captured_at: int) -> None:
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    runtime_run_id = f"runtime-{nodes}"
    started_ms = (captured_at - 60) * 1000
    common = {
        "schema_version": "v1",
        "status": "PASS",
        "run_id": runtime_run_id,
        "node_count": nodes,
    }
    scenarios = [*SPEC.management_scenario_ids, *SPEC.fault_scenario_ids]
    events: list[dict[str, Any]] = []
    management_commands: list[dict[str, Any]] = []
    fault_commands: list[dict[str, Any]] = []
    scenario_results: list[dict[str, Any]] = []
    for index, scenario_id in enumerate(scenarios):
        operation_id = f"operation-{nodes}-{scenario_id}"
        event_id = f"event-{nodes}-{scenario_id}"
        command_id = f"command-{nodes}-{scenario_id}"
        events.append(
            {
                "schema_version": "v1",
                "run_id": runtime_run_id,
                "event_id": event_id,
                "event_type": "scenario_observed",
                "operation_id": operation_id,
                "scenario_id": scenario_id,
                "timestamp_unix_ms": started_ms + index,
                "monotonic_ms": float(index + 1),
            }
        )
        command = {
            "schema_version": "v1",
            "run_id": runtime_run_id,
            "command_id": command_id,
            "command_kind": "observed_operation",
            "operation_id": operation_id,
            "scenario_id": scenario_id,
            "status": "PASS",
            "started_at_unix_ms": started_ms + 100 + index,
            "ended_at_unix_ms": started_ms + 101 + index,
        }
        is_management = scenario_id in SPEC.management_scenario_ids
        (management_commands if is_management else fault_commands).append(command)
        scenario_results.append(
            {
                "id": scenario_id,
                "run_id": runtime_run_id,
                "status": "REAL_PASS",
                "event_ids": [event_id],
                "command_ids": [command_id],
                "evidence_refs": [
                    "runtime/management_sequence.json"
                    if is_management
                    else "runtime/fault_sequence.json"
                ],
            }
        )
    lifecycle_rows: list[dict[str, Any]] = []
    for index, step_id in enumerate(SPEC.lifecycle_ids):
        event_id = f"lifecycle-{nodes}-{step_id}"
        events.append(
            {
                "schema_version": "v1",
                "run_id": runtime_run_id,
                "event_id": event_id,
                "event_type": "lifecycle_step_measured",
                "operation_id": f"lifecycle:{nodes}:{step_id}",
                "scenario_id": "lifecycle",
                "step_id": step_id,
                "timestamp_unix_ms": started_ms + 300 + index,
                "monotonic_ms": float(100 + index * 10 + 5),
            }
        )
        lifecycle_rows.append(
            {
                "id": step_id,
                "run_id": runtime_run_id,
                "status": "PASS",
                "started_monotonic_ms": float(100 + index * 10),
                "ended_monotonic_ms": float(105 + index * 10),
                "event_ids": [event_id],
            }
        )
    objects = {
        "run_state.json": {
            **common,
            "nodes": [{"logical_id": f"node-{index}"} for index in range(nodes)],
        },
        "resource_preflight.json": {**common, "can_run": True, "nodes_requested": nodes},
        "workload_windows.json": {**common, "windows": [{"status": "PASS"}]},
        "lifecycle_timeline.json": {**common, "steps": lifecycle_rows},
        "scenario_results.json": {**common, "scenarios": scenario_results},
        "management_sequence.json": common,
        "fault_sequence.json": {**common, "recovery_health": {"status": "PASS"}},
        "cleanup_report.json": {**common, "resources_remaining": [], "cleanup_errors": []},
        "analysis_summary.json": {
            **common,
            **{surface: {} for surface in SPEC.report_surface_ids},
        },
        "report_index.json": {**common, "views": [{"status": "PASS"}]},
        "full_flow_result.json": common,
    }
    for name, value in objects.items():
        _write_json(runtime / name, value)
    _write_jsonl(runtime / "management_command_log.jsonl", management_commands)
    _write_jsonl(runtime / "fault_command_log.jsonl", fault_commands)
    _write_jsonl(runtime / "events.jsonl", events)
    _write_jsonl(
        runtime / "metrics_timeseries.jsonl",
        [
            {
                "run_id": runtime_run_id,
                "metric_name": "used_memory",
                "metric_value": 1,
                "timestamp_unix_ms": started_ms + 500,
            }
        ],
    )


def _write_requirement_capture(
    evidence_root: Path,
    requirement_id: str,
    nodes: int,
    *,
    controller_run_id: str,
    product_digest: str,
    captured_at: int,
    promotion: str | None = None,
) -> dict[str, Any]:
    root = evidence_root / requirement_id
    _raw_bundle(root, nodes, captured_at)
    return build_candidate_admission(
        root,
        nodes,
        product_digest,
        definition=DEFINITION,
        run_started_unix_ms=(captured_at - 60) * 1000,
        run_ended_unix_ms=captured_at * 1000,
        valkey_versions=["9.1.0"],
        independent_probe={
            "cluster_state": "ok",
            "known_nodes": nodes,
            "slots_assigned": 16384,
            "slots_ok": 16384,
        },
        source_commit="c" * 40,
        promoted_from_admission_digest=promotion,
        invocation_run_id=controller_run_id,
    )


def _rewrite_candidate(path: Path, mutation) -> dict[str, Any]:
    candidate = json.loads(path.read_text(encoding="utf-8"))
    mutation(candidate)
    candidate.pop("admission_digest", None)
    candidate["admission_digest"] = COMMON.canonical_digest(candidate)
    _write_json(path, candidate)
    return candidate


def _prerequisite_completion(root: Path, final_digest: str) -> Path:
    terminal = {
        "schema_version": "controller-terminal-receipt-v1",
        "status": "SUCCESS",
        "milestone_id": "ValkeyScaleLab.m1",
        "product_digest": "9" * 64,
        "receipt_tag": "8" * 64,
    }
    terminal_path = root / "terminal.json"
    _write_json(terminal_path, terminal)
    completion = {
        "schema_version": "valkey-prerequisite-completion-v2",
        "milestone_id": "m1",
        "controller_milestone_id": "ValkeyScaleLab.m1",
        "terminal_status": "SUCCESS",
        "product_digest": terminal["product_digest"],
        "completed_at_unix": 1_999_000_000,
        "final_evidence_requirement_id": "local.exact.200",
        "final_admission_digest": final_digest,
        "terminal_receipt": {
            "path": "terminal.json",
            "sha256": COMMON.file_digest(terminal_path),
        },
    }
    completion["attestation_digest"] = COMMON.canonical_digest(completion)
    path = root / "completion.json"
    _write_json(path, completion)
    return path


@pytest.fixture
def admitted(tmp_path: Path) -> tuple[Path, str, str, int]:
    evidence_root = tmp_path / "run_evidence"
    run_id = "controller-run-1"
    product_digest = "a" * 64
    now = 2_000_000_000
    first = _write_requirement_capture(
        evidence_root,
        "local.exact.50",
        50,
        controller_run_id=run_id,
        product_digest=product_digest,
        captured_at=now - 10,
    )
    _write_requirement_capture(
        evidence_root,
        "local.exact.200",
        200,
        controller_run_id=run_id,
        product_digest=product_digest,
        captured_at=now - 5,
        promotion=first["admission_digest"],
    )
    return evidence_root, run_id, product_digest, now


def _evaluate(admitted: tuple[Path, str, str, int]) -> list[dict[str, Any]]:
    root, run_id, digest, now = admitted
    return POLICY.evaluate(
        milestone_path=MILESTONE_PATH,
        evidence_root=root,
        product_root=PROJECT_ROOT,
        candidate_schema_path=CANDIDATE_SCHEMA_PATH,
        prerequisite_paths=[],
        run_id=run_id,
        product_digest=digest,
        now_unix=now,
    )


def _errors(results: list[dict[str, Any]], requirement_id: str) -> list[str]:
    row = next(
        item
        for item in results
        if item["requirement_id"] == f"evidence.{requirement_id}"
    )
    assert row["status"] != "PASS"
    return row["provenance"]["errors"]


def test_complete_exact_real_evidence_and_promotion_chain_are_admitted(admitted) -> None:
    assert [row["status"] for row in _evaluate(admitted)] == ["PASS", "PASS"]


def test_minimal_self_consistent_bundle_is_rejected(tmp_path: Path) -> None:
    evidence_root = tmp_path / "run_evidence"
    root = evidence_root / "local.exact.50"
    raw = root / "runtime/raw.json"
    admitted_path = root / "runtime/admitted.json"
    _write_json(raw, {"run_id": "runtime-50", "node_count": 50})
    _write_json(admitted_path, {"run_id": "runtime-50", "node_count": 50})
    candidate = {
        "schema_version": "valkey-exact-scale-admission-v1",
        "execution_kind": "REAL_VALKEY_EXACT_SCALE",
        "run_id": "runtime-50",
        "invocation_run_id": "controller-run-1",
        "run_nonce": "1" * 32,
        "run_started_unix_ms": 1_999_999_000_000,
        "run_ended_unix_ms": 2_000_000_000_000,
        "source_commit": "c" * 40,
        "product_digest": "a" * 64,
        "definition_digest": DEFINITION.digest,
        "capture_digest": "d" * 64,
        "requested_nodes": 50,
        "observed_nodes": 50,
        "status": "PASS",
        "valkey_versions": ["9.1.0"],
        "independent_probe": {"status": "PASS", "observed_nodes": 50},
        "cleanup": {"status": "PASS", "residual_owned_resources": 0},
        "artifacts": [],
    }
    candidate["admission_digest"] = COMMON.canonical_digest(candidate)
    _write_json(root / "admission.json", candidate)
    results = POLICY.evaluate(
        milestone_path=MILESTONE_PATH,
        evidence_root=evidence_root,
        product_root=PROJECT_ROOT,
        candidate_schema_path=CANDIDATE_SCHEMA_PATH,
        prerequisite_paths=[],
        run_id="controller-run-1",
        product_digest="a" * 64,
        now_unix=2_000_000_000,
    )
    assert any("required raw artifact" in error for error in _errors(results, "local.exact.50"))


def test_stale_capture_is_rejected(admitted) -> None:
    path = admitted[0] / "local.exact.200/admission.json"
    _rewrite_candidate(path, lambda value: value.__setitem__("run_ended_unix_ms", 1))
    assert any("stale" in error for error in _errors(_evaluate(admitted), "local.exact.200"))


def test_fixture_capture_is_rejected(admitted) -> None:
    path = admitted[0] / "local.exact.200/admission.json"
    _rewrite_candidate(path, lambda value: value.__setitem__("source", "fixture"))
    assert any("fixture" in error for error in _errors(_evaluate(admitted), "local.exact.200"))


def test_downscaled_capture_is_rejected(admitted) -> None:
    path = admitted[0] / "local.exact.200/admission.json"
    _rewrite_candidate(path, lambda value: value.__setitem__("observed_nodes", 199))
    assert any("observed_nodes" in error for error in _errors(_evaluate(admitted), "local.exact.200"))


def test_cross_run_artifact_is_rejected(admitted) -> None:
    root = admitted[0] / "local.exact.200"
    candidate_path = root / "admission.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    artifact = root / candidate["artifacts"][0]["path"]
    value = json.loads(artifact.read_text(encoding="utf-8"))
    value["run_id"] = "another-runtime"
    _write_json(artifact, value)

    def update(document):
        document["artifacts"][0]["sha256"] = COMMON.file_digest(artifact)

    _rewrite_candidate(candidate_path, update)
    assert any("cross-run" in error for error in _errors(_evaluate(admitted), "local.exact.200"))


def test_forged_admission_digest_is_rejected(admitted) -> None:
    path = admitted[0] / "local.exact.200/admission.json"
    candidate = json.loads(path.read_text(encoding="utf-8"))
    candidate["admission_digest"] = "f" * 64
    _write_json(path, candidate)
    assert any("forged" in error for error in _errors(_evaluate(admitted), "local.exact.200"))


def test_residual_resources_are_rejected(admitted) -> None:
    path = admitted[0] / "local.exact.200/admission.json"
    _rewrite_candidate(
        path,
        lambda value: value["cleanup"].__setitem__("residual_owned_resources", 1),
    )
    assert any("residual" in error for error in _errors(_evaluate(admitted), "local.exact.200"))


def test_wrong_promotion_chain_is_rejected(admitted) -> None:
    path = admitted[0] / "local.exact.200/admission.json"
    _rewrite_candidate(
        path,
        lambda value: value.__setitem__("promoted_from_admission_digest", "e" * 64),
    )
    assert any("promotion" in error for error in _errors(_evaluate(admitted), "local.exact.200"))


def test_cross_product_and_cross_invocation_are_rejected(admitted) -> None:
    path = admitted[0] / "local.exact.200/admission.json"

    def update(candidate):
        candidate["product_digest"] = "b" * 64
        candidate["invocation_run_id"] = "another-controller-run"

    _rewrite_candidate(path, update)
    errors = _errors(_evaluate(admitted), "local.exact.200")
    assert any("product_digest" in error for error in errors)
    assert any("invocation_run_id" in error for error in errors)


def test_missing_raw_artifact_and_empty_provenance_are_rejected(admitted) -> None:
    root = admitted[0] / "local.exact.200"
    (root / "runtime/fault_sequence.json").unlink()
    candidate_path = root / "admission.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    provenance_path = root / candidate["provenance"]["path"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["capture_nodes"] = []
    provenance["admission_nodes"] = []
    provenance.pop("provenance_digest")
    provenance["provenance_digest"] = COMMON.canonical_digest(provenance)
    _write_json(provenance_path, provenance)

    def update(document):
        document["provenance"]["sha256"] = COMMON.file_digest(provenance_path)
        document["provenance"]["digest"] = provenance["provenance_digest"]

    _rewrite_candidate(candidate_path, update)
    errors = _errors(_evaluate(admitted), "local.exact.200")
    assert any("required raw artifact" in error for error in errors)
    assert any("complete canonical" in error for error in errors)


def test_first_requirement_binds_sealed_cross_milestone_admission(
    admitted, tmp_path: Path
) -> None:
    evidence_root, run_id, product_digest, now = admitted
    milestone = json.loads(MILESTONE_PATH.read_text(encoding="utf-8"))
    milestone["milestone"]["id"] = "m2"
    milestone["prerequisite_milestone_ids"] = ["m1"]
    milestone_path = tmp_path / "m2.json"
    _write_json(milestone_path, milestone)
    prerequisite_digest = "7" * 64
    completion_path = _prerequisite_completion(
        tmp_path / "authority/prerequisites/m1", prerequisite_digest
    )
    first_path = evidence_root / "local.exact.50/admission.json"
    first = _rewrite_candidate(
        first_path,
        lambda value: value.__setitem__(
            "promoted_from_admission_digest", prerequisite_digest
        ),
    )
    second_path = evidence_root / "local.exact.200/admission.json"
    _rewrite_candidate(
        second_path,
        lambda value: value.__setitem__(
            "promoted_from_admission_digest", first["admission_digest"]
        ),
    )
    results = POLICY.evaluate(
        milestone_path=milestone_path,
        evidence_root=evidence_root,
        product_root=PROJECT_ROOT,
        candidate_schema_path=CANDIDATE_SCHEMA_PATH,
        prerequisite_paths=[completion_path],
        run_id=run_id,
        product_digest=product_digest,
        now_unix=now,
    )
    assert [row["status"] for row in results] == ["PASS", "PASS"]

    _rewrite_candidate(
        first_path,
        lambda value: value.__setitem__(
            "promoted_from_admission_digest", "6" * 64
        ),
    )
    results = POLICY.evaluate(
        milestone_path=milestone_path,
        evidence_root=evidence_root,
        product_root=PROJECT_ROOT,
        candidate_schema_path=CANDIDATE_SCHEMA_PATH,
        prerequisite_paths=[completion_path],
        run_id=run_id,
        product_digest=product_digest,
        now_unix=now,
    )
    assert any(
        "sealed prerequisite" in error
        for error in _errors(results, "local.exact.50")
    )
