from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from valkey_scale_lab.goal.contracts import ContractError, load_json
from valkey_scale_lab.goal.digests import files_digest, sha256_file
from valkey_scale_lab.goal.migration import verify_v6_terminal_state
from valkey_scale_lab.goal.store import StateStore


V7_STATE_SHA256 = "9518e516238aa578c72c1d50bf9309c01de8cc9f3357d25b07ea2d9feafe38e8"
V7_EVENTS_SHA256 = "ab2bd21f7dc85ad2670a7ccf76f1ab63000f33310b0c27792b6b14363a279906"
V7_REVIEW_TEST_SHA256 = "74aabd88c2ac7c3dcce76f201c137a3a9f895fd293a624b0414747fa151bdf48"
V7_REPRODUCTION_LOG_SHA256 = "b5316f467e30ef4e0a547ea4013299f5ac60fb6bbfd85358546a2b96dcb38077"
V7_ACTIVE_WORK_SHA256 = "bc3fb5c15d859b0fd7c1fbbe115633e51ecf6bd7dfc3e1d53813f805286f3437"
V7_ACTIVE_GAP_SHA256 = "7bece5be5bc172ffd7a6f45b7078d09bd4fcc639c5112cd8c805c80d6a68d335"
V7_MIGRATION_SHA256 = "a15ac7456bf3bf33a0cc20e775cb6b9aa5a01827ce2972cef6a197bdb59a3483"
V7_LAST_EVENT_HASH = "f2854cce1a9590800a9dc38a8d605bf2977f0c7a6abfce60097183746f440906"
V7_REVIEW_CHECK_ID = "o1-changing-failure-identity-budget"
V8_SUCCESSOR_CHECK_ID = "o1-changing-failure-identity-budget-v8"


@dataclass(frozen=True)
class V8MigrationReceipt:
    source_state_path: str
    source_state_sha256: str
    source_control_sha256: str
    source_kernel_sha256: str
    source_evaluator_sha256: str
    source_last_event_hash: str
    source_active_work_sha256: str
    source_active_gap_sha256: str
    source_review_check_id: str
    source_review_test_sha256: str
    source_reproduction_log_sha256: str
    source_v6_receipt_sha256: str
    successor_check_id: str
    successor_test_sha256: str


def _json_digest(value: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def verify_v7_kernel_gap_state(project_root: Path, workspace_root: Path, source_state_path: Path) -> V8MigrationReceipt:
    project_root = project_root.resolve()
    workspace_root = workspace_root.resolve()
    source_state_path = source_state_path.resolve()
    canonical = (workspace_root / "loop_evidence/meta_runs/milestone1-v7/state/loop_state.json").resolve()
    if source_state_path != canonical or not source_state_path.is_file():
        raise ContractError("v8 migration source must be the canonical sealed v7 state")
    if sha256_file(source_state_path) != V7_STATE_SHA256:
        raise ContractError("sealed v7 kernel-gap state hash changed")

    state = load_json(source_state_path)
    if state.get("schema_version") != "v7" or state.get("goal_id") != "milestone1-pipeline-refactor-v7":
        raise ContractError("migration source is not the sealed v7 goal")
    if state.get("iteration") != 3 or state.get("last_event_hash") != V7_LAST_EVENT_HASH:
        raise ContractError("sealed v7 kernel-gap iteration changed")
    errors = StateStore.verify(state)
    if errors:
        raise ContractError("v7 state integrity failure: " + "; ".join(errors))

    events_path = source_state_path.with_name("events.jsonl")
    if not events_path.is_file() or sha256_file(events_path) != V7_EVENTS_SHA256:
        raise ContractError("sealed v7 event journal changed")
    expected_events = "".join(json.dumps(event, sort_keys=True) + "\n" for event in state["events"])
    if events_path.read_text(encoding="utf-8") != expected_events:
        raise ContractError("sealed v7 event journal does not match state")
    tail = state["events"][-2:]
    if [event.get("event") for event in tail] != ["REVIEW_SUBMITTED", "WORK_ISSUED"]:
        raise ContractError("sealed v7 gap-to-work event order changed")
    if tail[0].get("decision") != "GAP" or tail[0].get("check_id") != V7_REVIEW_CHECK_ID or tail[1].get("type") != "WORK":
        raise ContractError("sealed v7 gap-to-work event payload changed")

    active = state.get("active_work_item")
    if _json_digest(active) != V7_ACTIVE_WORK_SHA256 or not isinstance(active, dict):
        raise ContractError("sealed v7 active work item changed")
    if active.get("type") != "WORK" or active.get("objective_id") != "O1_GOAL_SCHEDULER_AND_CONTRACTS" or active.get("attempt") != 1:
        raise ContractError("sealed v7 active work item is not the proven O1 attempt")
    objectives = state.get("objectives")
    if not isinstance(objectives, dict) or set(objectives) != {
        "O1_GOAL_SCHEDULER_AND_CONTRACTS",
        "O2_CANONICAL_SCENARIO_DEFINITION",
        "O3_GATE_ORCHESTRATION_AND_RUNTIME_ADAPTERS",
        "O4_EVIDENCE_AND_ADMISSION",
        "O5_ANALYSIS_AND_REPORT",
        "O6_COMPATIBILITY_SAFETY_AND_EXACT_50",
        "O7_EXACT_200_AND_FINAL_CLOSURE",
    }:
        raise ContractError("sealed v7 objective set changed")
    o1 = objectives["O1_GOAL_SCHEDULER_AND_CONTRACTS"]
    expected_counters = ("WORKING", 1, 0, 1)
    if tuple(o1.get(key) for key in ("status", "attempts", "replans", "review_rounds")) != expected_counters:
        raise ContractError("sealed v7 O1 budget continuity changed")
    if any(value.get("status") != "PENDING" for key, value in objectives.items() if key != "O1_GOAL_SCHEDULER_AND_CONTRACTS"):
        raise ContractError("sealed v7 successor objectives changed")
    gap = o1.get("active_gap")
    if _json_digest(gap) != V7_ACTIVE_GAP_SHA256 or not isinstance(gap, dict):
        raise ContractError("sealed v7 active PRODUCT_GAP changed")
    check = gap.get("program_check")
    if gap.get("kind") != "PRODUCT_GAP" or not isinstance(check, dict) or check.get("id") != V7_REVIEW_CHECK_ID:
        raise ContractError("sealed v7 retry-budget check changed")

    review_test = (project_root / "tests/meta_loop_v7/test_o1_retry_budget_gap.py").resolve()
    if not review_test.is_file() or sha256_file(review_test) != V7_REVIEW_TEST_SHA256:
        raise ContractError("frozen v7 retry-budget test changed")
    anchor = o1.get("check_anchors", {}).get(V7_REVIEW_CHECK_ID)
    if anchor != {"targets": ["tests/meta_loop_v7/test_o1_retry_budget_gap.py"], "digest": "f829b505396d7fbe6aef432ad1ed9102c4c36eb5ec6142b26c92a14a8880fe9a"}:
        raise ContractError("sealed v7 reviewer check anchor changed")
    reproduction = o1.get("last_result", {}).get("reproduction", {})
    log_path = Path(str(reproduction.get("log_path", ""))).resolve()
    canonical_log = (workspace_root / "loop_evidence/meta_runs/milestone1-v7/logs/o1-changing-failure-identity-budget-8bd3f3e7a07d.log").resolve()
    if reproduction.get("status") != "FAIL" or log_path != canonical_log or not log_path.is_file() or sha256_file(log_path) != V7_REPRODUCTION_LOG_SHA256:
        raise ContractError("sealed v7 retry-budget failure reproduction changed")

    control_path = project_root / "codex/meta_m1_v7/control_block.json"
    manifest_path = project_root / "codex/meta_m1_v7/kernel_manifest.json"
    manifest = load_json(manifest_path)
    control_digest = sha256_file(control_path)
    kernel_digest = files_digest(project_root, ("codex/meta_m1_v7/kernel_manifest.json", *tuple(manifest.get("files", ()))))
    evaluator_digest = files_digest(project_root, ("scripts/meta_m1_evidence_gate_v7.py", "scripts/meta_m1_product_gate_contract_v7.py"))
    for label, actual in (("control", control_digest), ("kernel", kernel_digest), ("evaluator", evaluator_digest)):
        if state.get(f"{label}_digest") != actual:
            raise ContractError(f"sealed v7 {label} digest no longer matches its files")

    v6_source = workspace_root / "loop_evidence/meta_runs/milestone1-v6/state/loop_state.json"
    v6_receipt = asdict(verify_v6_terminal_state(project_root, workspace_root, v6_source))
    sealed_v6_receipt = dict(state.get("migration", {}))
    sealed_v6_receipt.pop("status", None)
    if _json_digest(v6_receipt) != _json_digest(sealed_v6_receipt) or _json_digest(state.get("migration")) != V7_MIGRATION_SHA256:
        raise ContractError("sealed v7 migration receipt does not match verified v6 provenance")

    successor = project_root / "tests/meta_loop_v8/test_retry_budget.py"
    if not successor.is_file():
        raise ContractError("v8 retry-budget successor test is missing")
    v8_control = load_json(project_root / "codex/meta_m1_v8/control_block.json")
    successor_checks = [
        check
        for objective in v8_control.get("objectives", [])
        if isinstance(objective, dict) and objective.get("id") == "O1_GOAL_SCHEDULER_AND_CONTRACTS"
        for check in objective.get("checks", [])
        if isinstance(check, dict) and check.get("id") == V8_SUCCESSOR_CHECK_ID
    ]
    if len(successor_checks) != 1 or successor_checks[0].get("command") != [
        "python3",
        "-m",
        "pytest",
        "-q",
        "tests/meta_loop_v8/test_retry_budget.py",
    ]:
        raise ContractError("v8 control does not bind the retry-budget successor check")
    return V8MigrationReceipt(
        source_state_path=str(source_state_path),
        source_state_sha256=V7_STATE_SHA256,
        source_control_sha256=control_digest,
        source_kernel_sha256=kernel_digest,
        source_evaluator_sha256=evaluator_digest,
        source_last_event_hash=V7_LAST_EVENT_HASH,
        source_active_work_sha256=V7_ACTIVE_WORK_SHA256,
        source_active_gap_sha256=V7_ACTIVE_GAP_SHA256,
        source_review_check_id=V7_REVIEW_CHECK_ID,
        source_review_test_sha256=V7_REVIEW_TEST_SHA256,
        source_reproduction_log_sha256=V7_REPRODUCTION_LOG_SHA256,
        source_v6_receipt_sha256=V7_MIGRATION_SHA256,
        successor_check_id=V8_SUCCESSOR_CHECK_ID,
        successor_test_sha256=sha256_file(successor),
    )
