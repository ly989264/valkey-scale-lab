from __future__ import annotations

from pathlib import Path

from .contracts import load_json, load_kernel_manifest, parse_goal_definition
from .digests import files_digest


def integrity_digests(project_root: Path, control_path: Path, *, expected_version: str) -> dict[str, str]:
    goal = parse_goal_definition(load_json(control_path), expected_version=expected_version)
    manifest = load_kernel_manifest(project_root, goal.kernel_manifest_path)
    return {
        "kernel_digest": files_digest(project_root, (manifest.manifest_path, *manifest.paths)),
        "evaluator_digest": files_digest(project_root, goal.evaluator_paths),
    }
