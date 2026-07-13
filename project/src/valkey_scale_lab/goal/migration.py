from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_json
from .digests import sha256_file, tree_digest
from .models import MigrationReceipt
from .store import StateStore


V6_KERNEL_PATHS = (
    "src/valkey_scale_lab/meta_loop_v6/__init__.py",
    "src/valkey_scale_lab/meta_loop_v6/__main__.py",
    "src/valkey_scale_lab/meta_loop_v6/cli.py",
    "src/valkey_scale_lab/meta_loop_v6/contracts.py",
    "src/valkey_scale_lab/meta_loop_v6/controller.py",
    "src/valkey_scale_lab/meta_loop_v6/digests.py",
    "src/valkey_scale_lab/meta_loop_v6/runner.py",
    "src/valkey_scale_lab/meta_loop_v6/store.py",
    "scripts/meta_m1_real_gate_v6.py",
)
V6_EVALUATOR_PATHS = ("scripts/meta_m1_evidence_gate.py", "scripts/meta_m1_product_gate_contract.py")
V6_OBJECTIVES = {
    "O1_TRIGGER_AND_SAFETY",
    "O2_LIFECYCLE_AND_TELEMETRY",
    "O3_MANAGEMENT_AND_STABILITY",
    "O4_FAULT_FAILOVER_AND_RECOVERY",
    "O5_EVIDENCE_REPORT_AND_SCALE_50",
    "O6_SCALE_200_AND_FINAL",
}


def verify_v6_terminal_state(project_root: Path, workspace_root: Path, source_state_path: Path) -> MigrationReceipt:
    project_root = project_root.resolve()
    workspace_root = workspace_root.resolve()
    source_state_path = source_state_path.resolve()
    canonical = workspace_root / "loop_evidence/meta_runs/milestone1-v6/state/loop_state.json"
    if source_state_path != canonical.resolve() or not source_state_path.is_file():
        raise ContractError("v6 migration source must be the canonical state")
    state = load_json(source_state_path)
    if state.get("schema_version") != "v6" or state.get("goal_id") != "milestone1-local-complete-v6":
        raise ContractError("migration source is not the terminal v6 goal")
    if state.get("active_work_item") is not None:
        raise ContractError("v6 migration requires no active work item")
    migration = state.get("migration")
    if not isinstance(migration, dict) or migration.get("status") != "PASS":
        raise ContractError("v6 migration provenance must be PASS")
    objectives = state.get("objectives")
    if not isinstance(objectives, dict) or set(objectives) != V6_OBJECTIVES or any(not isinstance(item, dict) or item.get("status") != "COMPLETE" for item in objectives.values()):
        raise ContractError("v6 migration requires every objective COMPLETE")
    integrity_errors = StateStore.verify(state)
    if integrity_errors:
        raise ContractError("v6 state integrity failure: " + "; ".join(integrity_errors))
    control_path = project_root / "codex/meta_m1_v6/control_block.json"
    control_digest = sha256_file(control_path)
    kernel_digest = _legacy_files_digest(project_root, V6_KERNEL_PATHS)
    evaluator_digest = _legacy_files_digest(project_root, V6_EVALUATOR_PATHS)
    for label, actual in (("control", control_digest), ("kernel", kernel_digest), ("evaluator", evaluator_digest)):
        if state.get(f"{label}_digest") != actual:
            raise ContractError(f"v6 {label} digest does not match terminal state")

    evidence: list[dict[str, Any]] = []
    admissions: dict[int, dict[str, Any]] = {}
    for scale, run in ((50, "milestone1-v5"), (200, "milestone1-v6")):
        base = workspace_root / f"loop_evidence/meta_runs/{run}/evidence/scale-{scale}"
        admission_path = base / "admission.json"
        admission = load_json(admission_path)
        if admission.get("status") != "PASS" or admission.get("requested_nodes") != scale or admission.get("observed_nodes") != scale:
            raise ContractError(f"v6 migration requires a PASS exact-{scale} admission")
        if not re.fullmatch(r"[0-9a-f]{64}", str(admission.get("product_digest", ""))):
            raise ContractError(f"exact-{scale} admission product digest is invalid")
        artifacts = admission.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ContractError(f"exact-{scale} artifact manifest must be nonempty")
        for artifact in artifacts:
            if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                raise ContractError(f"exact-{scale} artifact manifest is invalid")
            if not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256", ""))):
                raise ContractError(f"exact-{scale} artifact manifest hash is invalid")
            path = (base / artifact["path"]).resolve()
            if not path.is_relative_to(base.resolve()) or not path.is_file() or sha256_file(path) != artifact.get("sha256"):
                raise ContractError(f"exact-{scale} artifact hash mismatch")
        evidence.append({
            "scale": scale,
            "path": str(base),
            "admission_sha256": sha256_file(admission_path),
            "tree_sha256": tree_digest(base),
        })
        admissions[scale] = admission
    if migration.get("scale50_evidence_digest") != evidence[0]["tree_sha256"]:
        raise ContractError("sealed v6 scale-50 evidence digest does not match preserved evidence")

    cache_results = [value for value in state.get("cache", {}).values() if isinstance(value, dict) and value.get("status") == "PASS"]
    required_passes = {"exact-real-50-admission-final", "exact-real-200-capture", "exact-real-200-admission"}
    if not required_passes.issubset({str(value.get("check_id")) for value in cache_results}):
        raise ContractError("v6 sealed cache is missing required exact-scale PASS results")
    control = load_json(control_path)
    capture_check = next(
        check
        for objective in control.get("objectives", [])
        for check in objective.get("checks", [])
        if check.get("id") == "exact-real-200-capture"
    )
    evidence_inputs = tuple(raw for raw in capture_check["inputs"] if "loop_evidence" in raw)
    digest = hashlib.sha256()
    digest.update(str(admissions[200]["product_digest"]).encode())
    digest.update(_legacy_input_digest(project_root, workspace_root, evidence_inputs).encode())
    expected_capture_input = digest.hexdigest()
    if not any(value.get("check_id") == "exact-real-200-capture" and value.get("input_digest") == expected_capture_input for value in cache_results):
        raise ContractError("v6 exact-real-200 capture cache is not current for sealed evidence")
    return MigrationReceipt(
        source_state_path=str(source_state_path),
        source_state_sha256=sha256_file(source_state_path),
        source_control_sha256=control_digest,
        source_kernel_sha256=kernel_digest,
        source_evaluator_sha256=evaluator_digest,
        source_last_event_hash=str(state["last_event_hash"]),
        evidence=tuple(evidence),
    )


def _legacy_files_digest(project_root: Path, paths: tuple[str, ...]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted((project_root / raw).resolve() for raw in paths):
        digest.update(path.relative_to(project_root.resolve()).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _legacy_input_digest(project_root: Path, workspace_root: Path, inputs: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for raw in sorted(inputs):
        path = (project_root / raw).resolve()
        digest.update(raw.encode())
        files = [path] if path.is_file() else sorted(
            candidate for candidate in path.rglob("*")
            if candidate.is_file() and not any(part in {".git", "__pycache__", ".pytest_cache", ".mypy_cache"} for part in candidate.parts)
        ) if path.exists() else []
        if not path.exists():
            digest.update(b"\0MISSING")
        for candidate in files:
            digest.update(str(candidate.relative_to(workspace_root.resolve())).encode())
            digest.update(candidate.read_bytes())
    return digest.hexdigest()
