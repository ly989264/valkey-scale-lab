from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from .evaluation import EnvironmentBlocked, EvaluationError
from .models import Milestone
from .planner import path_is_covered, path_overlaps_any


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitCheckpoint:
    commit: str


@dataclass(frozen=True)
class ChangedPath:
    repository_path: str
    project_path: str | None


class GitWorkspace:
    """The small Git boundary used for checkpoint, scope checks, and rollback."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        root = self._run("rev-parse", "--show-toplevel").strip()
        self.repository_root = Path(root).resolve()
        try:
            self.project_prefix = self.project_root.relative_to(self.repository_root)
        except ValueError as exc:
            raise GitError("project root must be inside its Git repository") from exc

    def ensure_clean(self) -> None:
        output = self._run("status", "--porcelain", "--untracked-files=all")
        if output:
            raise GitError("Controller requires a clean Git worktree before each objective")

    def checkpoint(self) -> GitCheckpoint:
        self.ensure_clean()
        return GitCheckpoint(self._run("rev-parse", "HEAD").strip())

    def changed_paths(self) -> tuple[ChangedPath, ...]:
        tracked = self._run_bytes("diff", "--name-only", "-z", "HEAD")
        untracked = self._run_bytes("ls-files", "--others", "--exclude-standard", "-z")
        raw_paths = {
            item.decode("utf-8")
            for item in (*tracked.split(b"\0"), *untracked.split(b"\0"))
            if item
        }
        prefix = PurePosixPath(self.project_prefix.as_posix())
        values: list[ChangedPath] = []
        for raw in sorted(raw_paths):
            repository_path = PurePosixPath(raw)
            if prefix == PurePosixPath("."):
                project_path = repository_path.as_posix()
            elif repository_path == prefix:
                project_path = "."
            elif repository_path.is_relative_to(prefix):
                project_path = repository_path.relative_to(prefix).as_posix()
            else:
                project_path = None
            values.append(ChangedPath(raw, project_path))
        return tuple(values)

    def validate_changes(
        self,
        changes: tuple[ChangedPath, ...],
        *,
        allowed_write_paths: tuple[str, ...],
        objective_write_paths: tuple[str, ...],
        protected_paths: tuple[str, ...],
    ) -> tuple[str, ...]:
        violations: list[str] = []
        for change in changes:
            path = change.project_path
            if path is None:
                violations.append(change.repository_path)
                continue
            if not path_is_covered(path, allowed_write_paths):
                violations.append(change.repository_path)
                continue
            if not path_is_covered(path, objective_write_paths):
                violations.append(change.repository_path)
                continue
            if path_overlaps_any(path, protected_paths):
                violations.append(change.repository_path)
        return tuple(violations)

    def rollback(self, checkpoint: GitCheckpoint) -> None:
        self._run("reset", "--hard", checkpoint.commit)
        self._run("clean", "-fd")
        self.ensure_clean()

    def retain(self, objective_id: str) -> str | None:
        if not self.changed_paths():
            return None
        self._run("add", "-A")
        self._run(
            "-c",
            "user.name=Milestone Controller",
            "-c",
            "user.email=controller@local",
            "commit",
            "-m",
            f"controller: retain {objective_id}",
        )
        self.ensure_clean()
        return self._run("rev-parse", "HEAD").strip()

    def _run(self, *args: str) -> str:
        return self._run_bytes(*args).decode("utf-8")

    def _run_bytes(self, *args: str) -> bytes:
        completed = subprocess.run(
            ["git", "-C", str(self.repository_root if hasattr(self, "repository_root") else self.project_root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise GitError(f"git {' '.join(args)} failed: {detail}")
        return completed.stdout


class CommandEvaluator:
    """Run one ordinary command that returns a complete evaluator result as JSON."""

    def __init__(self, argv: Sequence[str], *, cwd: Path | None = None, timeout_seconds: int = 300):
        if not argv:
            raise ValueError("evaluator command must not be empty")
        self.argv = tuple(argv)
        self.cwd = None if cwd is None else Path(cwd)
        self.timeout_seconds = timeout_seconds

    def __call__(self, milestone: Milestone, project_root: Path) -> dict[str, Any]:
        environment = dict(os.environ)
        environment["CONTROLLER_MILESTONE_ID"] = milestone.id
        try:
            completed = subprocess.run(
                self.argv,
                cwd=self.cwd or project_root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EnvironmentBlocked(f"evaluator could not run: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise EnvironmentBlocked(
                f"evaluator exited with {completed.returncode}: {detail[-1000:]}"
            )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise EvaluationError(f"evaluator did not return JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise EvaluationError("evaluator result must be a JSON object")
        return value
