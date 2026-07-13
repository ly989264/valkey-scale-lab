from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from valkey_scale_lab.goal.contracts import ContractError, load_json, parse_goal_definition
from valkey_scale_lab.goal.models import KernelManifest
from valkey_scale_lab.goal.scheduler import check_plan
from valkey_scale_lab.goal.service import GoalService, GoalServiceError

from .migration import V8MigrationReceipt, verify_v7_kernel_gap_state


MigrationVerifier = Callable[[Path, Path, Path], V8MigrationReceipt]


def load_v8_kernel_manifest(project_root: Path, relative_path: str) -> KernelManifest:
    project_root = project_root.resolve()
    path = (project_root / relative_path).resolve()
    if not path.is_relative_to(project_root):
        raise ContractError("kernel manifest escapes project root")
    raw = load_json(path)
    if raw.get("schema_version") != "meta-loop-v8-kernel-manifest-v1":
        raise ContractError("unsupported v8 kernel manifest schema")
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


class MetaLoopV8Controller(GoalService):
    """V8 facade that closes the sealed V7 retry-accounting kernel gap."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        control_path: Path,
        state_root: Path,
        migration_verifier: MigrationVerifier = verify_v7_kernel_gap_state,
    ):
        goal = parse_goal_definition(load_json(control_path), expected_version="v8")
        manifest = load_v8_kernel_manifest(project_root, goal.kernel_manifest_path)
        super().__init__(
            project_root=project_root,
            workspace_root=workspace_root,
            control_path=control_path,
            state_root=state_root,
            schema_version="v8",
            kernel_manifest=manifest,
            migration_verifier=migration_verifier,
        )

    def migrate_v7(self, source_state_path: Path) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            if self.store.exists():
                return self._status_view(self._state(), goal)
            receipt = self.migration_verifier(self.project_root, self.workspace_root, source_state_path.resolve())
            state = self._new_state(goal)
            state["migration"] = {"status": "PASS", **asdict(receipt)}

            # Preserve consumed retry/review budget, but admit no V7 PASS, cache,
            # mutable review check, or completion claim into the fresh V8 run.
            objective = state["objectives"]["O1_GOAL_SCHEDULER_AND_CONTRACTS"]
            objective.update(
                {
                    "status": "REVERIFY",
                    "attempts": 1,
                    "replans": 0,
                    "review_rounds": 1,
                    "last_result": {"status": "MIGRATED_KERNEL_GAP_REVERIFY"},
                }
            )
            self._event(state, "MIGRATED_FROM_V7_KERNEL_GAP", {"source_state_sha256": receipt.source_state_sha256})
            self.store.save(state)
            return self._status_view(state, goal)

    def evaluate_active(self) -> dict[str, Any]:
        goal = self._goal()
        with self.store.locked():
            state = self._state()
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") not in {"WORK", "VERIFY"}:
                raise GoalServiceError("evaluate requires active WORK or VERIFY")
            objective = goal.objective(str(work["objective_id"]))
            progress = state["objectives"][objective.id]
            checks = check_plan(goal, objective, self._added_checks(progress))
            results = self._run_checks(checks, state, goal)
            passed = len(results) == len(checks) and all(result["status"] == "PASS" for result in results)
            report = self._evaluation(objective.id, results, len(checks), passed)
            failed = next((result for result in results if result["status"] == "FAIL"), None)
            if failed is not None:
                fingerprint = hashlib.sha256(str(failed["check_id"]).encode()).hexdigest()
                if fingerprint != progress.get("failure_fingerprint"):
                    progress.update(
                        {
                            "failure_fingerprint": fingerprint,
                            "stagnant_attempts": 0,
                            "best_score": report["score"],
                        }
                    )
                elif report["score"] > progress["best_score"]:
                    progress.update({"best_score": report["score"], "stagnant_attempts": 0})
                else:
                    progress["stagnant_attempts"] += 1
            else:
                progress.update(
                    {
                        "failure_fingerprint": None,
                        "stagnant_attempts": 0,
                        "best_score": report["score"],
                        "active_gap": None,
                    }
                )
            progress["last_result"] = report
            progress["status"] = "PROGRAM_PASS" if passed else "PENDING"
            state["active_work_item"] = None
            self._event(state, "PROGRAM_EVALUATED", {"objective_id": objective.id, "status": report["status"]})
            self.store.save(state)
            return self._compact(report)
