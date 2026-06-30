#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "loop_engineering"

sys.path.insert(0, str(ROOT / "scripts"))
from schema_validator import load_json, validate  # noqa: E402


REQUIRED_AGENT_ROLES = [
    "requirements_analyst",
    "harness_architect",
    "risk_auditor",
    "implementation_worker",
    "review_agent",
    "validation_agent",
    "anti_regression_guardian",
]

PHASE_ORDER = [
    "READ_CONTEXT",
    "PREVIOUS_HARNESS",
    "DESIGN",
    "HARNESS",
    "IMPLEMENT",
    "REVIEW",
    "VALIDATE",
    "COMMIT",
    "PUSH",
    "PASS",
    "BLOCKED",
]

CONTROLLED_PATH_PREFIXES = (
    "tests/",
    "scripts/",
    "schemas/",
    ".github/",
    "codex/",
    "artifacts/gates/",
    "artifacts/phases/",
    "artifacts/loop_engineering/",
)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def schema(name: str) -> dict[str, Any]:
    return load_json(SCHEMA_DIR / f"{name}.schema.json")


def load_json_with_errors(path: Path) -> tuple[Any | None, list[str]]:
    try:
        return load_json(path), []
    except json.JSONDecodeError as exc:
        return None, [f"{rel(path)}: invalid JSON: {exc}"]
    except OSError as exc:
        return None, [f"{rel(path)}: cannot read JSON: {exc}"]


def validate_json_file(path: Path, schema_name: str) -> list[str]:
    data, errors = load_json_with_errors(path)
    if errors:
        return errors
    return [f"{rel(path)}: {error}" for error in validate(data, schema(schema_name))]


def validate_command_log(path: Path) -> list[str]:
    errors: list[str] = []
    entry_schema = schema("command_log_entry")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{rel(path)}: cannot read command log: {exc}"]
    if not raw.strip():
        return [f"{rel(path)}: command log is empty"]
    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel(path)}:{lineno}: invalid JSONL entry: {exc}")
            continue
        for error in validate(entry, entry_schema, f"$[line {lineno}]"):
            errors.append(f"{rel(path)}:{lineno}: {error}")
        status = entry.get("status")
        exit_code = entry.get("exit_code")
        if status == "PASS" and exit_code != 0:
            errors.append(f"{rel(path)}:{lineno}: PASS entry has non-zero exit_code {exit_code!r}")
        if status == "FAIL" and exit_code == 0:
            errors.append(f"{rel(path)}:{lineno}: FAIL entry has zero exit_code")
        if status == "SKIPPED_WITH_REASON" and not entry.get("reason"):
            errors.append(f"{rel(path)}:{lineno}: skipped entry requires reason")
    return errors


def validate_subagent(path: Path, stage_id: str) -> list[str]:
    errors = validate_json_file(path, "subagent_response")
    data, load_errors = load_json_with_errors(path)
    if load_errors or data is None:
        return errors + load_errors
    role = data.get("agent_role")
    if data.get("stage_id") != stage_id:
        errors.append(f"{rel(path)}: stage_id does not match parent stage {stage_id}")
    if path.stem != role:
        errors.append(f"{rel(path)}: filename role {path.stem!r} does not match agent_role {role!r}")
    if role in {"requirements_analyst", "harness_architect", "risk_auditor"}:
        if not data.get("context_files_read"):
            errors.append(f"{rel(path)}: design-phase agent must list context_files_read")
        if not data.get("acceptance_criteria"):
            errors.append(f"{rel(path)}: design-phase agent must list acceptance_criteria")
    return errors


def existing_repo_path(path_text: str) -> bool:
    return (ROOT / path_text).exists()


def validate_stage_result(path: Path, stage_id: str, stage_dir: Path) -> list[str]:
    errors = validate_json_file(path, "stage_result")
    data, load_errors = load_json_with_errors(path)
    if load_errors or data is None:
        return errors + load_errors
    if data.get("stage_id") != stage_id:
        errors.append(f"{rel(path)}: stage_id does not match parent stage {stage_id}")
    if data.get("status") == "PASS":
        if not data.get("previous_harness_passed"):
            errors.append(f"{rel(path)}: PASS requires previous_harness_passed true")
        if not data.get("current_harness_passed"):
            errors.append(f"{rel(path)}: PASS requires current_harness_passed true")
        if not data.get("pushed"):
            errors.append(f"{rel(path)}: PASS requires pushed true")
        if not data.get("commit_sha"):
            errors.append(f"{rel(path)}: PASS requires non-empty commit_sha")
        commands_log = data.get("commands_log", "")
        if not commands_log or not existing_repo_path(commands_log):
            errors.append(f"{rel(path)}: commands_log does not exist: {commands_log}")
        verdicts = data.get("subagent_verdicts", {})
        for role in REQUIRED_AGENT_ROLES:
            subagent_path = stage_dir / "subagents" / f"{role}.json"
            if not subagent_path.exists():
                errors.append(f"{rel(path)}: PASS requires subagent artifact {rel(subagent_path)}")
            if verdicts.get(role) != "APPROVED":
                errors.append(f"{rel(path)}: PASS requires {role} verdict APPROVED")
        for artifact in data.get("artifacts", []):
            if not existing_repo_path(artifact):
                errors.append(f"{rel(path)}: referenced artifact missing: {artifact}")
    return errors


def validate_stage(stage_dir: Path) -> list[str]:
    errors: list[str] = []
    stage_id = stage_dir.name
    stage_state = stage_dir / "stage_state.json"
    phase = "READ_CONTEXT"
    if not stage_state.exists():
        errors.append(f"{rel(stage_state)}: missing required stage artifact")
    else:
        errors.extend(validate_json_file(stage_state, "stage_state"))
        data, load_errors = load_json_with_errors(stage_state)
        errors.extend(load_errors)
        if isinstance(data, dict):
            phase = str(data.get("phase", phase))

    def phase_at_least(required: str) -> bool:
        try:
            return PHASE_ORDER.index(phase) >= PHASE_ORDER.index(required)
        except ValueError:
            return True

    conditional_artifacts = [
        ("previous_harness_result.json", "previous_harness_result", "DESIGN"),
        ("current_harness_plan.json", "current_harness_plan", "DESIGN"),
    ]
    for filename, schema_name, required_phase in conditional_artifacts:
        path = stage_dir / filename
        if not path.exists():
            if phase_at_least(required_phase):
                errors.append(f"{rel(path)}: missing required stage artifact")
        else:
            errors.extend(validate_json_file(path, schema_name))

    command_log = stage_dir / "commands.jsonl"
    if not command_log.exists():
        errors.append(f"{rel(command_log)}: missing required command log")
    else:
        errors.extend(validate_command_log(command_log))

    subagent_dir = stage_dir / "subagents"
    if not subagent_dir.exists():
        if phase_at_least("DESIGN"):
            errors.append(f"{rel(subagent_dir)}: missing subagent directory")
    else:
        for subagent_path in sorted(subagent_dir.glob("*.json")):
            errors.extend(validate_subagent(subagent_path, stage_id))

    optional_schema_files = [
        ("validation_result.json", "validation_result"),
        ("global_loop_state.json", "global_loop_state"),
    ]
    for filename, schema_name in optional_schema_files:
        path = stage_dir / filename
        if path.exists():
            errors.extend(validate_json_file(path, schema_name))

    stage_result = stage_dir / "stage_result.json"
    if stage_result.exists():
        errors.extend(validate_stage_result(stage_result, stage_id, stage_dir))
    return errors


def validate_loop_root(root: Path, stage: str | None = None) -> list[str]:
    errors: list[str] = []
    root_path = root if root.is_absolute() else ROOT / root
    if not root_path.exists():
        return [f"{rel(root_path)}: loop root does not exist"]

    global_state = root_path / "global_loop_state.json"
    if global_state.exists():
        errors.extend(validate_json_file(global_state, "global_loop_state"))

    stages_root = root_path / "stages"
    if not stages_root.exists():
        return errors
    stage_dirs = [stages_root / stage] if stage else sorted(p for p in stages_root.iterdir() if p.is_dir())
    for stage_dir in stage_dirs:
        if not stage_dir.exists():
            errors.append(f"{rel(stage_dir)}: selected stage does not exist")
            continue
        errors.extend(validate_stage(stage_dir))
    return errors


def split_diff_by_file(diff_text: str) -> dict[str, list[str]]:
    by_file: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                current = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                by_file.setdefault(current, [])
            continue
        if current is not None:
            by_file.setdefault(current, []).append(line)
    return by_file


def detect_anti_regression_findings(diff_text: str, changed_files: list[str]) -> list[str]:
    findings: list[str] = []
    for path in changed_files:
        if path.endswith(".DS_Store") and path.startswith(CONTROLLED_PATH_PREFIXES):
            findings.append(f"{path}: .DS_Store must not be staged or tracked under controlled paths")
        if path.endswith((".pyc", ".pyo")) and path.startswith(CONTROLLED_PATH_PREFIXES):
            findings.append(f"{path}: generated Python bytecode must not be staged or tracked under controlled paths")

    for path, lines in split_diff_by_file(diff_text).items():
        text = "\n".join(lines)
        removed = "\n".join(line for line in lines if line.startswith("-") and not line.startswith("---"))
        added = "\n".join(line for line in lines if line.startswith("+") and not line.startswith("+++"))
        if path == "codex/phase_manifest.json":
            if '"real_valkey_required": true' in removed and '"real_valkey_required": false' in added:
                findings.append(f"{path}: real_valkey_required downgrade detected")
            if '"automatic": false' in removed and '"automatic": true' in added:
                findings.append(f"{path}: optional phase may have been made automatic")
            if "VSLAB_ALLOW_1000_DRYRUN" in removed and "VSLAB_ALLOW_1000_DRYRUN" not in added:
                findings.append(f"{path}: P14 opt-in guard removal detected")
            if '"required": true' in removed and '"required": false' in added:
                findings.append(f"{path}: required gate or artifact downgraded to optional")
        if path.startswith("schemas/") and ('"required"' in removed or '"enum"' in removed):
            findings.append(f"{path}: schema required/enum removal requires harness change approval")
        if path.startswith("tests/"):
            for line in lines:
                if line.startswith("+") and ("pytest.mark.skip" in line or "pytest.mark.xfail" in line):
                    if "reason=" not in line:
                        findings.append(f"{path}: skip/xfail added without explicit reason")
        if path.startswith("artifacts/gates/") and '"status": "PASS"' in added:
            findings.append(f"{path}: gate PASS must be produced by codex_gate.py run, not manual edits")
        if "min-nodes" in removed and "min-nodes" in added and "-min-nodes" not in text:
            findings.append(f"{path}: inspect min-nodes change for possible lowering")
    return findings


def changed_files_from_porcelain(status_text: str) -> list[str]:
    files: list[str] = []
    for line in status_text.splitlines():
        if not line:
            continue
        path = line[3:] if len(line) > 3 else ""
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            files.append(path)
    return files


def git_output(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout, proc.stderr


def run_anti_regression(base_ref: str, head_ref: str, report: Path | None) -> int:
    pathspec = list(CONTROLLED_PATH_PREFIXES)
    if head_ref in {"HEAD", "WORKTREE", ""}:
        diff_cmd = ["git", "diff", "--unified=0", base_ref, "--", *pathspec]
        changed_cmd = ["git", "diff", "--name-only", base_ref, "--", *pathspec]
    else:
        diff_cmd = ["git", "diff", "--unified=0", base_ref, head_ref, "--", *pathspec]
        changed_cmd = ["git", "diff", "--name-only", base_ref, head_ref, "--", *pathspec]
    code, diff_text, stderr = git_output(diff_cmd)
    if code != 0:
        print(stderr, file=sys.stderr)
        return 2
    code, changed_text, stderr = git_output(changed_cmd)
    if code != 0:
        print(stderr, file=sys.stderr)
        return 2
    changed_files = [line.strip() for line in changed_text.splitlines() if line.strip()]
    code, status_text, stderr = git_output(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *pathspec]
    )
    if code != 0:
        print(stderr, file=sys.stderr)
        return 2
    changed_files = sorted(set(changed_files + changed_files_from_porcelain(status_text)))

    _, staged_text, _ = git_output(["git", "diff", "--cached", "--name-only", "--", *pathspec])
    _, tracked_text, _ = git_output(["git", "ls-files", "--", *pathspec])
    ds_files = [
        line.strip()
        for line in (staged_text + "\n" + tracked_text).splitlines()
        if line.strip().endswith(".DS_Store")
    ]
    findings = detect_anti_regression_findings(diff_text, changed_files + ds_files)
    result = {
        "schema_version": "v1",
        "status": "PASS" if not findings else "FAIL",
        "base_ref": base_ref,
        "head_ref": head_ref,
        "changed_files": changed_files,
        "findings": findings,
    }
    if report:
        report_path = report if report.is_absolute() else ROOT / report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if findings:
        for finding in findings:
            print(f"FAIL: {finding}", file=sys.stderr)
        return 1
    print("PASS anti-regression")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="artifacts/loop_engineering")
    parser.add_argument("--stage")
    parser.add_argument("--anti-regression", action="store_true")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument("--report")
    args = parser.parse_args()

    if args.anti_regression:
        if not args.base_ref:
            print("--anti-regression requires --base-ref", file=sys.stderr)
            return 2
        report = Path(args.report) if args.report else None
        return run_anti_regression(args.base_ref, args.head_ref, report)

    errors = validate_loop_root(Path(args.root), args.stage)
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS loop_engineering root={args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
