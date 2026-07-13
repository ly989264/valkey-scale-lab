from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from valkey_scale_lab.goal.contracts import ContractError, load_json
from valkey_scale_lab.goal.digests import files_digest, sha256_file
from valkey_scale_lab.goal.store import StateStore
from valkey_scale_lab.meta_loop_v8.migration import verify_v7_kernel_gap_state


V8_STATE_SHA256 = "9e5eebe76ac849414809dd255d029d5698a96a562e310e9b3222e494da740ee7"
V8_EVENTS_SHA256 = "8af1e8a8c333a260436dfa8bbf7aa1605bfa5b7a520bccc3f78ab4646962c95e"
V8_LAST_EVENT_HASH = "a6404715517a5b2be97abf2c97becfdf5172175bf0b47c1a9d8a2bed005680c9"
V8_ACTIVE_GAP_SHA256 = "6cb3294c07d4d5c34b456df75aae0ed983453063b481e022a6ca69ebd847ab63"
V8_MIGRATION_SHA256 = "04bb85bae19044c82cc8851be7cbd1b5929b60b7d769b0c0fd5431200ef53656"
V8_REVIEW_TEST_SHA256 = "a13bb40976a287bc16b8362c8e75b4a13199db66c8103083dce03ebba7e30b66"
V8_RETRY_TEST_SHA256 = "bf742fabdc017e8f69a8d619a1d4885397fa632a1f86bb4e153588be60636279"
V8_REPRODUCTION_LOG_SHA256 = "c862c222e1ea52de1d861d75a23a96ea885007b9743493ffdbb04dd914319394"
V8_REVIEW_CHECK_ID = "o1-seal-v7-reproduction-and-v8-successor"
V9_SUCCESSOR_CHECK_ID = "o1-seal-v7-v8-kernel-gap-evidence-v9"


@dataclass(frozen=True)
class V9MigrationReceipt:
    source_state_path: str
    source_state_sha256: str
    source_events_sha256: str
    source_control_sha256: str
    source_kernel_sha256: str
    source_evaluator_sha256: str
    source_last_event_hash: str
    source_active_gap_sha256: str
    source_review_check_id: str
    source_review_test_sha256: str
    source_retry_test_sha256: str
    source_reproduction_log_sha256: str
    source_v7_v6_receipt_sha256: str
    successor_check_id: str
    successor_test_sha256: str


def _json_digest(value: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(value, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def verify_v8_kernel_gap_state(project_root: Path, workspace_root: Path, source_state_path: Path) -> V9MigrationReceipt:
    project_root = project_root.resolve()
    workspace_root = workspace_root.resolve()
    source_state_path = source_state_path.resolve()
    canonical = (workspace_root / "loop_evidence/meta_runs/milestone1-v8/state/loop_state.json").resolve()
    if source_state_path != canonical or not source_state_path.is_file():
        raise ContractError("v9 migration source must be the canonical sealed v8 state")
    if sha256_file(source_state_path) != V8_STATE_SHA256:
        raise ContractError("sealed v8 kernel-gap state hash changed")
    state = load_json(source_state_path)
    if state.get("schema_version") != "v8" or state.get("goal_id") != "milestone1-pipeline-refactor-v8":
        raise ContractError("migration source is not the sealed v8 goal")
    if state.get("iteration") != 2 or state.get("last_event_hash") != V8_LAST_EVENT_HASH or state.get("active_work_item") is not None:
        raise ContractError("sealed v8 kernel-gap position changed")
    errors = StateStore.verify(state)
    if errors:
        raise ContractError("v8 state integrity failure: " + "; ".join(errors))

    events_path = source_state_path.with_name("events.jsonl")
    if not events_path.is_file() or sha256_file(events_path) != V8_EVENTS_SHA256:
        raise ContractError("sealed v8 event journal changed")
    expected_events = "".join(json.dumps(event, sort_keys=True) + "\n" for event in state["events"])
    if events_path.read_text(encoding="utf-8") != expected_events:
        raise ContractError("sealed v8 event journal does not match state")
    tail = state["events"][-3:]
    if [event.get("event") for event in tail] != ["PROGRAM_EVALUATED", "WORK_ISSUED", "REVIEW_SUBMITTED"]:
        raise ContractError("sealed v8 PASS-to-gap event order changed")
    if tail[0].get("status") != "PASS" or tail[1].get("type") != "REVIEW_ACCEPTANCE":
        raise ContractError("sealed v8 review event payload changed")
    if tail[2].get("decision") != "GAP" or tail[2].get("gap_kind") != "PRODUCT_GAP" or tail[2].get("check_id") != V8_REVIEW_CHECK_ID:
        raise ContractError("sealed v8 PRODUCT_GAP event changed")

    objectives = state.get("objectives")
    expected_ids = {
        "O1_GOAL_SCHEDULER_AND_CONTRACTS",
        "O2_CANONICAL_SCENARIO_DEFINITION",
        "O3_GATE_ORCHESTRATION_AND_RUNTIME_ADAPTERS",
        "O4_EVIDENCE_AND_ADMISSION",
        "O5_ANALYSIS_AND_REPORT",
        "O6_COMPATIBILITY_SAFETY_AND_EXACT_50",
        "O7_EXACT_200_AND_FINAL_CLOSURE",
    }
    if not isinstance(objectives, dict) or set(objectives) != expected_ids:
        raise ContractError("sealed v8 objective set changed")
    o1 = objectives["O1_GOAL_SCHEDULER_AND_CONTRACTS"]
    if tuple(o1.get(key) for key in ("status", "attempts", "replans", "review_rounds")) != ("PENDING", 0, 0, 2):
        raise ContractError("sealed v8 O1 budget continuity changed")
    if any(item.get("status") != "PENDING" for key, item in objectives.items() if key != "O1_GOAL_SCHEDULER_AND_CONTRACTS"):
        raise ContractError("sealed v8 successor objectives changed")
    gap = o1.get("active_gap")
    if _json_digest(gap) != V8_ACTIVE_GAP_SHA256 or not isinstance(gap, dict):
        raise ContractError("sealed v8 active PRODUCT_GAP changed")
    check = gap.get("program_check")
    if gap.get("kind") != "PRODUCT_GAP" or not isinstance(check, dict) or check.get("id") != V8_REVIEW_CHECK_ID:
        raise ContractError("sealed v8 kernel-seal check changed")

    review_test = project_root / "tests/meta_loop_v8/test_contract.py"
    retry_test = project_root / "tests/meta_loop_v8/test_retry_budget.py"
    if not review_test.is_file() or sha256_file(review_test) != V8_REVIEW_TEST_SHA256:
        raise ContractError("frozen v8 kernel-gap test changed")
    if not retry_test.is_file() or sha256_file(retry_test) != V8_RETRY_TEST_SHA256:
        raise ContractError("frozen v8 retry-budget successor changed")
    anchor = o1.get("check_anchors", {}).get(V8_REVIEW_CHECK_ID)
    if anchor != {"targets": ["tests/meta_loop_v8/test_contract.py"], "digest": "6e0508b990da8732172313b9539e6d844790e31f4dcfc4212bebbd0b7f03ec06"}:
        raise ContractError("sealed v8 reviewer check anchor changed")
    reproduction = o1.get("last_result", {}).get("reproduction", {})
    log_path = Path(str(reproduction.get("log_path", ""))).resolve()
    canonical_log = (workspace_root / "loop_evidence/meta_runs/milestone1-v8/logs/o1-seal-v7-reproduction-and-v8-successor-e73cafeb5f5a.log").resolve()
    if reproduction.get("status") != "FAIL" or log_path != canonical_log or not log_path.is_file() or sha256_file(log_path) != V8_REPRODUCTION_LOG_SHA256:
        raise ContractError("sealed v8 kernel-gap reproduction changed")

    control_path = project_root / "codex/meta_m1_v8/control_block.json"
    manifest = load_json(project_root / "codex/meta_m1_v8/kernel_manifest.json")
    control_digest = sha256_file(control_path)
    kernel_digest = files_digest(project_root, ("codex/meta_m1_v8/kernel_manifest.json", *tuple(manifest.get("files", ()))))
    evaluator_digest = files_digest(project_root, ("scripts/meta_m1_evidence_gate_v8.py", "scripts/meta_m1_product_gate_contract_v8.py"))
    for label, actual in (("control", control_digest), ("kernel", kernel_digest), ("evaluator", evaluator_digest)):
        if state.get(f"{label}_digest") != actual:
            raise ContractError(f"sealed v8 {label} digest no longer matches its files")

    v7_source = workspace_root / "loop_evidence/meta_runs/milestone1-v7/state/loop_state.json"
    v7_receipt = asdict(verify_v7_kernel_gap_state(project_root, workspace_root, v7_source))
    sealed_receipt = dict(state.get("migration", {}))
    sealed_receipt.pop("status", None)
    if _json_digest(v7_receipt) != _json_digest(sealed_receipt) or _json_digest(state.get("migration")) != V8_MIGRATION_SHA256:
        raise ContractError("sealed v8 receipt does not match verified v7/v6 provenance")

    successor = project_root / "tests/meta_loop_v9/test_v9_contract.py"
    if not successor.is_file():
        raise ContractError("v9 kernel-seal successor test is missing")
    v9_control = load_json(project_root / "codex/meta_m1_v9/control_block.json")
    successor_checks = [
        check
        for objective in v9_control.get("objectives", [])
        if isinstance(objective, dict) and objective.get("id") == "O1_GOAL_SCHEDULER_AND_CONTRACTS"
        for check in objective.get("checks", [])
        if isinstance(check, dict) and check.get("id") == V9_SUCCESSOR_CHECK_ID
    ]
    if len(successor_checks) != 1 or successor_checks[0].get("command") != [
        "python3",
        "-m",
        "pytest",
        "-q",
        "tests/meta_loop_v9/test_v9_contract.py::test_v9_kernel_manifest_seals_v7_v8_gap_chain_and_v9_successor",
    ]:
        raise ContractError("v9 control does not bind the kernel-seal successor check")
    return V9MigrationReceipt(
        source_state_path=str(source_state_path),
        source_state_sha256=V8_STATE_SHA256,
        source_events_sha256=V8_EVENTS_SHA256,
        source_control_sha256=control_digest,
        source_kernel_sha256=kernel_digest,
        source_evaluator_sha256=evaluator_digest,
        source_last_event_hash=V8_LAST_EVENT_HASH,
        source_active_gap_sha256=V8_ACTIVE_GAP_SHA256,
        source_review_check_id=V8_REVIEW_CHECK_ID,
        source_review_test_sha256=V8_REVIEW_TEST_SHA256,
        source_retry_test_sha256=V8_RETRY_TEST_SHA256,
        source_reproduction_log_sha256=V8_REPRODUCTION_LOG_SHA256,
        source_v7_v6_receipt_sha256=V8_MIGRATION_SHA256,
        successor_check_id=V9_SUCCESSOR_CHECK_ID,
        successor_test_sha256=sha256_file(successor),
    )
