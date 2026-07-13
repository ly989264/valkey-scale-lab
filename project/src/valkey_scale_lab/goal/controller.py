from __future__ import annotations

from pathlib import Path

from .contracts import load_json, load_kernel_manifest, parse_goal_definition
from .service import GoalService


class GoalController(GoalService):
    """Configured facade; scheduling and I/O remain in the reusable Goal core."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        control_path: Path,
        state_root: Path,
        schema_version: str,
        migration_verifier=None,
    ):
        goal = parse_goal_definition(load_json(control_path), expected_version=schema_version)
        manifest = load_kernel_manifest(project_root, goal.kernel_manifest_path)
        kwargs = {}
        if migration_verifier is not None:
            kwargs["migration_verifier"] = migration_verifier
        super().__init__(
            project_root=project_root,
            workspace_root=workspace_root,
            control_path=control_path,
            state_root=state_root,
            schema_version=schema_version,
            kernel_manifest=manifest,
            **kwargs,
        )
