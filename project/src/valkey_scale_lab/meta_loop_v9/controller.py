from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from valkey_scale_lab.goal.contracts import ContractError, load_json, parse_goal_definition
from valkey_scale_lab.goal.models import KernelManifest
from valkey_scale_lab.goal.service import GoalService
from valkey_scale_lab.meta_loop_v8.controller import MetaLoopV8Controller

from .migration import V9MigrationReceipt, verify_v8_kernel_gap_state


MigrationVerifier = Callable[[Path, Path, Path], V9MigrationReceipt]


def load_v9_kernel_manifest(project_root: Path, relative_path: str) -> KernelManifest:
    project_root = project_root.resolve()
    path = (project_root / relative_path).resolve()
    if not path.is_relative_to(project_root):
        raise ContractError("kernel manifest escapes project root")
    raw = load_json(path)
    if raw.get("schema_version") != "meta-loop-v9-kernel-manifest-v1":
        raise ContractError("unsupported v9 kernel manifest schema")
    files = raw.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(value, str) and value for value in files):
        raise ContractError("kernel manifest files must be a non-empty string list")
    if len(files) != len(set(files)):
        raise ContractError("kernel manifest files must be unique")
    for raw_path in files:
        candidate = (project_root / raw_path).resolve()
        if not candidate.is_relative_to(project_root) or not candidate.is_file():
            raise ContractError(f"kernel manifest file is missing or escapes project: {raw_path}")
    return KernelManifest(relative_path, tuple(files))


class MetaLoopV9Controller(MetaLoopV8Controller):
    """V9 facade sealing both proven O1 kernel-gap reproductions."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        control_path: Path,
        state_root: Path,
        migration_verifier: MigrationVerifier = verify_v8_kernel_gap_state,
    ):
        goal = parse_goal_definition(load_json(control_path), expected_version="v9")
        manifest = load_v9_kernel_manifest(project_root, goal.kernel_manifest_path)
        GoalService.__init__(
            self,
            project_root=project_root,
            workspace_root=workspace_root,
            control_path=control_path,
            state_root=state_root,
            schema_version="v9",
            kernel_manifest=manifest,
            migration_verifier=migration_verifier,
        )

    def migrate_v8(self, source_state_path: Path) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            if self.store.exists():
                return self._status_view(self._state(), goal)
            receipt = self.migration_verifier(self.project_root, self.workspace_root, source_state_path.resolve())
            state = self._new_state(goal)
            state["migration"] = {"status": "PASS", **asdict(receipt)}
            objective = state["objectives"]["O1_GOAL_SCHEDULER_AND_CONTRACTS"]
            objective.update(
                {
                    "status": "REVERIFY",
                    "attempts": 0,
                    "replans": 0,
                    "review_rounds": 2,
                    "last_result": {"status": "MIGRATED_KERNEL_GAP_REVERIFY"},
                }
            )
            self._event(state, "MIGRATED_FROM_V8_KERNEL_GAP", {"source_state_sha256": receipt.source_state_sha256})
            self.store.save(state)
            return self._status_view(state, goal)
