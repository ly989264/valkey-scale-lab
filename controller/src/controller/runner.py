from __future__ import annotations

import json
import os
import platform
import resource
import signal
import shutil
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .integrity import (
    IntegrityError,
    canonical_digest,
    file_digest,
    manifest_diff,
    resolve_inside,
    tree_manifest,
)
from .models import EvaluatorDefinition, MilestoneContract
from .schema_validation import SchemaValidationError, validate_json_schema


RESULT_SCHEMA = "controller-evaluator-result-v1"
CONDITION_STATUSES = frozenset({"PASS", "FAIL", "MISSING", "BLOCKED_ENV", "ERROR", "STALE"})
EVIDENCE_STATUSES = frozenset({"PASS", "MISSING", "STALE", "UNTRUSTED", "SUBSTITUTED", "ERROR"})


class EvaluatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolSeal:
    name: str
    path: str
    sha256: str


@dataclass(frozen=True)
class EvaluatorRun:
    evaluator_id: str
    report: dict[str, Any]
    report_digest: str
    input_digest: str
    return_code: int
    duration_seconds: float
    report_path: str
    log_path: str
    log_digest: str
    evidence_artifacts: tuple[dict[str, Any], ...]


class EvaluatorRunner:
    """Invoke sealed independent evaluators and reject product-side effects."""

    def __init__(
        self,
        *,
        project_root: Path,
        workspace_root: Path,
        run_root: Path,
        contract: MilestoneContract,
        tool_seals: Mapping[str, ToolSeal],
    ):
        self.project_root = Path(project_root).resolve()
        self.workspace_root = Path(workspace_root).resolve()
        self.run_root = Path(run_root).resolve()
        self.contract = contract
        self.tool_seals = dict(tool_seals)
        if not self.project_root.is_relative_to(self.workspace_root):
            raise EvaluatorError("project root must be inside the worker workspace")
        if self.run_root.is_relative_to(self.workspace_root):
            raise EvaluatorError("controller run root must be outside the worker workspace")

    @staticmethod
    def seal_tools(
        names: tuple[str, ...],
        *,
        workspace_root: Path,
        run_root: Path,
    ) -> dict[str, ToolSeal]:
        workspace_root = Path(workspace_root).resolve()
        run_root = Path(run_root).resolve()
        seals: dict[str, ToolSeal] = {}
        for name in names:
            located = shutil.which(name)
            if located is None:
                raise EvaluatorError(f"allowed tool is unavailable: {name}")
            path = Path(located).resolve()
            if not path.is_file() or path.is_symlink():
                raise EvaluatorError(f"allowed tool is not a regular resolved file: {name}")
            if path.is_relative_to(workspace_root) or path.is_relative_to(run_root):
                raise EvaluatorError(f"allowed tool is inside a writable authority root: {name}")
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o022:
                raise EvaluatorError(f"allowed tool is group/world writable: {path}")
            current = path.parent
            while True:
                parent_mode = stat.S_IMODE(current.stat().st_mode)
                if parent_mode & 0o022:
                    raise EvaluatorError(f"allowed tool parent is group/world writable: {current}")
                if current == current.parent:
                    break
                current = current.parent
            seals[name] = ToolSeal(name=name, path=str(path), sha256=file_digest(path))
        return seals

    def verify_tool_seals(self) -> None:
        for name, seal in self.tool_seals.items():
            path = Path(seal.path)
            if not path.is_file() or path.is_symlink() or file_digest(path) != seal.sha256:
                raise EvaluatorError(f"sealed tool drift: {name}")

    def run(
        self,
        evaluator: EvaluatorDefinition,
        *,
        run_id: str,
        product_digest: str,
        evaluation_id: str,
    ) -> EvaluatorRun:
        self.verify_tool_seals()
        try:
            tool = self.tool_seals[evaluator.argv[0]]
        except KeyError as exc:
            raise EvaluatorError(f"evaluator uses an unsealed tool: {evaluator.argv[0]}") from exc
        evaluation_root = self.run_root / "evaluations" / evaluation_id
        result_path = evaluation_root / "results" / evaluator.id / "result.json"
        log_path = evaluation_root / "logs" / f"{evaluator.id}.log"
        evidence_root = self.run_root / "evidence"
        scratch_root = evaluation_root / "scratch" / evaluator.id
        for path in (result_path.parent, log_path.parent, evidence_root, scratch_root):
            path.mkdir(parents=True, exist_ok=True)
        input_digest = self._input_digest(evaluator, evidence_root=evidence_root)
        if result_path.exists():
            raise EvaluatorError(f"evaluator result already exists: {result_path}")

        before = tree_manifest(self.workspace_root)
        evidence_before = tree_manifest(evidence_root)
        command = [tool.path, *evaluator.argv[1:]]
        cwd = self.project_root if evaluator.cwd == "." else resolve_inside(self.project_root, evaluator.cwd)
        command, command_cwd = self._sandboxed_command(
            command,
            cwd=cwd,
            result_path=result_path,
            scratch_root=scratch_root,
            evidence_root=evidence_root,
            allowed_executable=Path(tool.path),
            read_paths=tuple(resolve_inside(self.project_root, item) for item in evaluator.inputs),
            read_evidence=evaluator.mode == "admission",
        )
        environment = {
            "HOME": str(scratch_root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": str(Path(tool.path).parent),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": str(scratch_root),
            "CONTROLLER_RUN_ID": run_id,
            "CONTROLLER_EVALUATOR_ID": evaluator.id,
            "CONTROLLER_INPUT_DIGEST": input_digest,
            "CONTROLLER_PRODUCT_DIGEST": product_digest,
            "CONTROLLER_RESULT_PATH": str(result_path),
            "CONTROLLER_EVIDENCE_ROOT": str(evidence_root),
        }
        started = time.monotonic()
        timed_out = False
        try:
            with log_path.open("wb") as log_handle:
                process = subprocess.Popen(
                    command,
                    cwd=command_cwd,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    preexec_fn=self._evaluator_resource_limit,
                    start_new_session=True,
                )
                try:
                    return_code = process.wait(timeout=evaluator.timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    return_code = process.wait()
        except subprocess.TimeoutExpired:
            timed_out = True
            return_code = 124
        duration = time.monotonic() - started
        try:
            scratch_manifest = tree_manifest(scratch_root)
            scratch_bytes = sum(
                item["size"] for item in scratch_manifest.values() if item["kind"] == "file"
            )
            scratch_files = sum(item["kind"] == "file" for item in scratch_manifest.values())
        finally:
            shutil.rmtree(scratch_root, ignore_errors=True)
        if scratch_bytes > self.contract.resource_budget.max_evidence_bytes or scratch_files > 4096:
            raise EvaluatorError(f"evaluator {evaluator.id!r} exceeded its scratch-space bound")
        after = tree_manifest(self.workspace_root)
        diff = manifest_diff(before, after)
        if any(diff.values()):
            raise IntegrityError(
                f"independent evaluator {evaluator.id!r} modified the worker workspace: {diff}"
            )
        evidence_after = tree_manifest(evidence_root)
        evidence_diff = manifest_diff(evidence_before, evidence_after)
        if any(evidence_diff.values()):
            raise IntegrityError(
                f"independent evaluator {evaluator.id!r} modified controller evidence: {evidence_diff}"
            )
        if timed_out:
            raise EvaluatorError(f"evaluator {evaluator.id!r} timed out")
        report = self._load_report(result_path, evaluator)
        try:
            declared_schema = json.loads(
                resolve_inside(self.project_root, evaluator.output_schema).read_text(encoding="utf-8")
            )
            validate_json_schema(report, declared_schema)
        except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
            raise EvaluatorError(
                f"evaluator {evaluator.id!r} result violates its sealed output schema: {exc}"
            ) from exc
        evidence_artifacts = self._validate_binding(
            report,
            evaluator=evaluator,
            run_id=run_id,
            product_digest=product_digest,
            input_digest=input_digest,
            return_code=return_code,
            evidence_root=evidence_root,
        )
        evidence_artifacts = self._archive_evidence(evidence_artifacts, evaluation_root)
        return EvaluatorRun(
            evaluator_id=evaluator.id,
            report=report,
            report_digest=canonical_digest(report),
            input_digest=input_digest,
            return_code=return_code,
            duration_seconds=duration,
            report_path=str(result_path),
            log_path=str(log_path),
            log_digest=file_digest(log_path),
            evidence_artifacts=evidence_artifacts,
        )

    def _input_digest(self, evaluator: EvaluatorDefinition, *, evidence_root: Path) -> str:
        values: dict[str, Any] = {}
        for relative in evaluator.inputs:
            path = resolve_inside(self.project_root, relative)
            if not path.exists():
                values[relative] = {"kind": "missing"}
            elif path.is_file():
                values[relative] = {
                    "kind": "file",
                    "sha256": file_digest(path),
                    "mode": stat.S_IMODE(path.stat().st_mode),
                }
            elif path.is_dir():
                values[relative] = {"kind": "directory", "manifest": tree_manifest(path)}
            else:
                raise EvaluatorError(f"unsupported evaluator input: {relative}")
        if evaluator.mode == "admission":
            values["@controller_evidence"] = {
                "kind": "directory",
                "manifest": tree_manifest(evidence_root),
            }
        return canonical_digest(values)

    def _sandboxed_command(
        self,
        command: list[str],
        *,
        cwd: Path,
        result_path: Path,
        scratch_root: Path,
        evidence_root: Path,
        allowed_executable: Path,
        read_paths: tuple[Path, ...],
        read_evidence: bool,
    ) -> tuple[list[str], Path]:
        system = platform.system()
        if system == "Darwin":
            sandbox = Path("/usr/bin/sandbox-exec")
            self._verify_system_sandbox(sandbox)
            read_rules = []
            system_roots = {
                Path("/System/Library"),
                Path("/usr/lib"),
                Path("/Library/Apple"),
                allowed_executable.parent,
            }
            for path in sorted(system_roots, key=str):
                if path.exists():
                    read_rules.append(f'(allow file-read* (subpath {json.dumps(str(path))}))')
            for path in read_paths:
                selector = "subpath" if path.is_dir() else "literal"
                read_rules.append(f'(allow file-read* ({selector} {json.dumps(str(path))}))')
            if read_evidence and evidence_root.exists():
                read_rules.append(f'(allow file-read* (subpath {json.dumps(str(evidence_root))}))')
            profile = "\n".join(
                [
                    "(version 1)",
                    "(deny default)",
                    *read_rules,
                    '(allow file-read* (literal "/dev/null"))',
                    f'(allow process-exec (literal {json.dumps(str(allowed_executable))}))',
                    "(allow sysctl-read)",
                    "(allow mach-lookup)",
                    "(allow signal (target self))",
                    f'(allow file-write* (subpath {json.dumps(str(scratch_root))}))',
                    f'(allow file-write* (literal {json.dumps(str(result_path))}))',
                    "(deny network*)",
                ]
            )
            return [str(sandbox), "-p", profile, *command], cwd
        if system == "Linux":
            located = shutil.which("bwrap")
            if located is None:
                raise EvaluatorError("Linux evaluator isolation requires an operator-sealed bwrap")
            sandbox = Path(located).resolve()
            self._verify_system_sandbox(sandbox)
            system_roots = tuple(
                path for path in (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"))
                if path.exists()
            )
            readonly = [*system_roots, *read_paths]
            if not any(allowed_executable.is_relative_to(root) for root in system_roots):
                readonly.append(allowed_executable)
            if read_evidence:
                readonly.append(evidence_root)
            writable = (scratch_root, result_path.parent)
            destinations = [cwd, *readonly, *writable]
            directories: set[Path] = set()
            for destination in destinations:
                current = destination if destination.is_dir() else destination.parent
                while current != current.parent:
                    directories.add(current)
                    current = current.parent
            command_prefix = [
                str(sandbox),
                "--die-with-parent",
                "--new-session",
                "--unshare-all",
                "--tmpfs",
                "/",
            ]
            for directory in sorted(directories, key=lambda item: (len(item.parts), str(item))):
                command_prefix.extend(("--dir", str(directory)))
            for path in readonly:
                command_prefix.extend(("--ro-bind", str(path), str(path)))
            command_prefix.extend(("--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"))
            for path in writable:
                command_prefix.extend(("--bind", str(path), str(path)))
            command_prefix.extend(("--chdir", str(cwd)))
            return ([*command_prefix, *command], Path("/"))
        raise EvaluatorError(f"unsupported evaluator sandbox platform: {system}")

    @staticmethod
    def _verify_system_sandbox(path: Path) -> None:
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise EvaluatorError(f"sandbox backend is missing or unsafe: {path}")
        current = path
        while True:
            if stat.S_IMODE(current.stat().st_mode) & 0o022:
                raise EvaluatorError(f"sandbox backend authority is writable: {current}")
            if current == current.parent:
                break
            current = current.parent

    def _evaluator_resource_limit(self) -> None:
        soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        requested = self.contract.resource_budget.max_evidence_bytes
        ceiling = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        resource.setrlimit(resource.RLIMIT_FSIZE, (ceiling, hard))
        nofile_soft, nofile_hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        nofile_ceiling = 64 if nofile_hard == resource.RLIM_INFINITY else min(64, nofile_hard)
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile_ceiling, nofile_hard))

    @staticmethod
    def _load_report(path: Path, evaluator: EvaluatorDefinition) -> dict[str, Any]:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvaluatorError(f"evaluator {evaluator.id!r} did not produce valid JSON: {exc}") from exc
        if not isinstance(report, dict):
            raise EvaluatorError(f"evaluator {evaluator.id!r} result must be an object")
        return report

    def _validate_binding(
        self,
        report: dict[str, Any],
        *,
        evaluator: EvaluatorDefinition,
        run_id: str,
        product_digest: str,
        input_digest: str,
        return_code: int,
        evidence_root: Path,
    ) -> tuple[dict[str, Any], ...]:
        required = {
            "schema_version",
            "evaluator_id",
            "run_id",
            "product_digest",
            "input_digest",
            "condition_results",
            "evidence_results",
            "facts",
        }
        if set(report) != required:
            raise EvaluatorError(
                f"evaluator {evaluator.id!r} result fields mismatch: "
                f"missing={sorted(required - set(report))}, extra={sorted(set(report) - required)}"
            )
        expected_bindings = {
            "schema_version": RESULT_SCHEMA,
            "evaluator_id": evaluator.id,
            "run_id": run_id,
            "product_digest": product_digest,
            "input_digest": input_digest,
        }
        for key, expected in expected_bindings.items():
            if report[key] != expected:
                raise EvaluatorError(f"evaluator {evaluator.id!r} result has stale or false {key}")
        conditions = self._records(report["condition_results"], "condition_results")
        evidence = self._records(report["evidence_results"], "evidence_results")
        facts = self._records(report["facts"], "facts")
        self._validate_conditions(evaluator, conditions)
        evidence_artifacts = self._validate_evidence(
            evaluator,
            evidence,
            evidence_root,
            run_id,
            product_digest,
        )
        self._validate_facts(evaluator, facts)
        condition_statuses = {item["status"] for item in conditions}
        evidence_statuses = {item["status"] for item in evidence}
        all_pass = condition_statuses <= {"PASS"} and evidence_statuses <= {"PASS"}
        has_result = bool(condition_statuses or evidence_statuses)
        expected_code = (
            0
            if has_result and all_pass
            else 75
            if condition_statuses and condition_statuses <= {"BLOCKED_ENV"} and not evidence_statuses
            else 1
        )
        if return_code != expected_code:
            raise EvaluatorError(
                f"evaluator {evaluator.id!r} exit code {return_code} contradicts verdicts (expected {expected_code})"
            )
        return evidence_artifacts

    @staticmethod
    def _records(value: Any, location: str) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise EvaluatorError(f"{location} must be an array")
        if not all(isinstance(item, dict) for item in value):
            raise EvaluatorError(f"{location} entries must be objects")
        return value

    def _validate_conditions(self, evaluator: EvaluatorDefinition, values: list[dict[str, Any]]) -> None:
        expected = {
            condition.id
            for condition in self.contract.success_conditions
            if evaluator.id in condition.evaluator_ids
        }
        seen: set[str] = set()
        for item in values:
            if set(item) != {"condition_id", "status", "summary"}:
                raise EvaluatorError("condition result fields are invalid")
            condition_id = item["condition_id"]
            status = item["status"]
            if condition_id not in expected or condition_id in seen:
                raise EvaluatorError(f"evaluator returned unknown or duplicate condition {condition_id!r}")
            if status not in CONDITION_STATUSES:
                raise EvaluatorError(f"invalid condition status {status!r}")
            if not isinstance(item["summary"], str) or not item["summary"].strip():
                raise EvaluatorError("condition result summary must be non-empty")
            seen.add(condition_id)
        if seen != expected:
            raise EvaluatorError(f"evaluator omitted success conditions: {sorted(expected - seen)}")

    def _validate_evidence(
        self,
        evaluator: EvaluatorDefinition,
        values: list[dict[str, Any]],
        evidence_root: Path,
        run_id: str,
        product_digest: str,
    ) -> tuple[dict[str, Any], ...]:
        expected = {
            requirement.id
            for requirement in self.contract.evidence_requirements
            if evaluator.id in requirement.admission_evaluator_ids
        }
        seen: set[str] = set()
        artifacts: list[dict[str, Any]] = []
        for item in values:
            required_fields = {
                "requirement_id",
                "status",
                "artifact",
                "capture_class",
                "provenance",
                "captured_at_unix",
                "run_id",
                "product_digest",
                "substituted",
            }
            if set(item) != required_fields:
                raise EvaluatorError("evidence result fields are invalid")
            requirement_id = item["requirement_id"]
            if requirement_id not in expected or requirement_id in seen:
                raise EvaluatorError(f"evaluator returned unknown or duplicate evidence {requirement_id!r}")
            requirement = self.contract.evidence_requirement(requirement_id)
            status = item["status"]
            if status not in EVIDENCE_STATUSES:
                raise EvaluatorError(f"invalid evidence status {status!r}")
            if item["capture_class"] != requirement.capture_class:
                raise EvaluatorError("evidence capture class was weakened")
            if item["substituted"] is not False:
                raise EvaluatorError("substituted evidence is forbidden")
            if status == "PASS":
                if requirement.freshness.bind_to_run_id and item["run_id"] != run_id:
                    raise EvaluatorError("evidence is bound to another run")
                if requirement.freshness.bind_to_product_digest and item["product_digest"] != product_digest:
                    raise EvaluatorError("evidence is stale for the current product")
                captured = item["captured_at_unix"]
                if not isinstance(captured, int) or captured > int(time.time()) + 60:
                    raise EvaluatorError("evidence timestamp is invalid")
                if int(time.time()) - captured > requirement.freshness.max_age_seconds:
                    raise EvaluatorError("evidence is stale")
                if requirement.provenance_required and not isinstance(item["provenance"], dict):
                    raise EvaluatorError("evidence provenance is missing")
                if requirement.provenance_required and not item["provenance"]:
                    raise EvaluatorError("evidence provenance is empty")
                artifact = item["artifact"]
                if not isinstance(artifact, str) or not artifact:
                    raise EvaluatorError("passing evidence must name an artifact")
                artifact_path = resolve_inside(evidence_root, artifact)
                if not artifact_path.is_file() or artifact_path.is_symlink():
                    raise EvaluatorError("passing evidence artifact is missing or unsafe")
                artifacts.append(
                    {
                        "requirement_id": requirement_id,
                        "path": str(artifact_path),
                        "sha256": file_digest(artifact_path),
                        "captured_at_unix": captured,
                        "run_id": item["run_id"],
                        "product_digest": item["product_digest"],
                        "capture_class": item["capture_class"],
                        "provenance_digest": canonical_digest(item["provenance"]),
                    }
                )
            seen.add(requirement_id)
        if seen != expected:
            raise EvaluatorError(f"evaluator omitted evidence requirements: {sorted(expected - seen)}")
        return tuple(sorted(artifacts, key=lambda item: (item["requirement_id"], item["sha256"])))

    def _validate_facts(self, evaluator: EvaluatorDefinition, values: list[dict[str, Any]]) -> None:
        known = {condition.id for condition in self.contract.success_conditions}
        for item in values:
            if set(item) != {"relation", "source_condition_id", "target_condition_id", "statement"}:
                raise EvaluatorError("evaluator fact fields are invalid")
            if item["relation"] != "BLOCKS":
                raise EvaluatorError("only evidence-backed BLOCKS facts are accepted")
            if item["source_condition_id"] not in known or item["target_condition_id"] not in known:
                raise EvaluatorError("evaluator fact references an unknown condition")
            if item["source_condition_id"] == item["target_condition_id"]:
                raise EvaluatorError("evaluator fact cannot self-block")
            if not isinstance(item["statement"], str) or not item["statement"].strip():
                raise EvaluatorError("evaluator fact statement is required")

    @staticmethod
    def _archive_evidence(
        artifacts: tuple[dict[str, Any], ...],
        evaluation_root: Path,
    ) -> tuple[dict[str, Any], ...]:
        archived: list[dict[str, Any]] = []
        archive_root = evaluation_root / "admitted-evidence"
        for artifact in artifacts:
            source = Path(artifact["path"])
            requirement_root = archive_root / artifact["requirement_id"]
            requirement_root.mkdir(parents=True, exist_ok=True)
            destination = requirement_root / f"{artifact['sha256']}.artifact"
            if destination.exists():
                if destination.is_symlink() or file_digest(destination) != artifact["sha256"]:
                    raise IntegrityError(f"archived evidence collision: {destination}")
            else:
                temporary = requirement_root / f".{artifact['sha256']}.{uuid.uuid4().hex}.tmp"
                try:
                    shutil.copyfile(source, temporary)
                    if file_digest(temporary) != artifact["sha256"]:
                        raise IntegrityError("raw evidence changed while it was being archived")
                    temporary.chmod(0o400)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            if destination.is_symlink() or file_digest(destination) != artifact["sha256"]:
                raise IntegrityError(f"archived evidence digest mismatch: {destination}")
            record = dict(artifact)
            record["source_path"] = str(source)
            record["path"] = str(destination)
            archived.append(record)
        return tuple(archived)


def new_evaluation_id(iteration: int, phase: str) -> str:
    return f"{iteration:06d}-{phase.lower()}-{uuid.uuid4().hex}"
