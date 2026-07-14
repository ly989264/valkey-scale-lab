from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_bundle
from .integrity import FrameworkIntegrityError, verify_framework_release
from .milestone import load_milestone_template, validate_milestone
from .runner import ProgramRunnerError
from .service import VProController, VProServiceError
from .store import StateStoreError


FRAMEWORK_ROOT = Path(__file__).resolve().parents[3]
_ACTOR = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fixed VPRO v1 milestone controller")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--state-root", "--run-root", dest="state_root", type=Path)
    parser.add_argument("--actor", default=os.environ.get("VPRO_ACTOR"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("framework-verify")
    commands.add_parser("bundle-validate")
    commands.add_parser("milestone-validate")
    commands.add_parser("milestone-template")
    commands.add_parser("bind")
    commands.add_parser("doctor")
    commands.add_parser("status")
    commands.add_parser("next")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--work-item-id", required=True)
    repair = commands.add_parser("accept-evaluator-repair")
    repair.add_argument("--work-item-id", required=True)
    commands.add_parser("audit")
    commands.add_parser("verify-completion")
    review = commands.add_parser("review")
    review.add_argument("--report", type=Path, required=True)
    approve = commands.add_parser("approve-gate")
    approve.add_argument("--approval", type=Path, required=True)
    return parser


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VProServiceError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VProServiceError(f"{path} must contain a JSON object")
    return value


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _actor(args: argparse.Namespace) -> str:
    if not isinstance(args.actor, str) or not _ACTOR.fullmatch(args.actor):
        raise VProServiceError("this command requires --actor with a strict ASCII actor id")
    return args.actor


def _controller(args: argparse.Namespace, release) -> VProController:
    if (
        args.project_root is None
        or args.workspace_root is None
        or args.bundle is None
        or args.profile is None
        or args.state_root is None
    ):
        raise VProServiceError(
            "run commands require --project-root, --workspace-root, --bundle, --profile, and --state-root"
        )
    state_key_path, state_key = _protected_hmac_key(
        args,
        environment_name="VPRO_STATE_HMAC_KEY_FILE",
        label="controller state",
    )
    approval_key_path, approval_key = _protected_hmac_key(
        args,
        environment_name="VPRO_APPROVAL_HMAC_KEY_FILE",
        label="gate approval",
    )
    if state_key_path == approval_key_path or state_key == approval_key:
        raise VProServiceError("state and gate approval HMAC keys must be distinct")
    return VProController(
        project_root=args.project_root,
        workspace_root=args.workspace_root,
        bundle_path=args.bundle,
        profile_id=args.profile,
        state_root=args.state_root,
        release=release,
        state_seal_key=state_key,
        approval_key=approval_key,
        secret_paths=(state_key_path, approval_key_path),
    )


def _protected_hmac_key(
    args: argparse.Namespace,
    *,
    environment_name: str,
    label: str,
) -> tuple[Path, bytes]:
    raw_path = os.environ.get(environment_name)
    if not raw_path:
        raise VProServiceError(f"the protected controller must set {environment_name}")
    path = Path(raw_path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise VProServiceError(f"{label} HMAC key path must not traverse a symlink")
    protected_roots = (
        FRAMEWORK_ROOT,
        args.project_root.resolve(),
        args.workspace_root.resolve(),
        args.state_root.resolve(),
    )
    resolved = path.resolve()
    if any(resolved == root or resolved.is_relative_to(root) for root in protected_roots):
        raise VProServiceError(f"{label} HMAC key file must be outside framework, workspace, and state roots")
    try:
        key = resolved.read_bytes()
    except OSError as exc:
        raise VProServiceError(f"cannot read {label} HMAC key: {exc}") from exc
    if len(key) < 32:
        raise VProServiceError(f"{label} HMAC key must contain at least 32 bytes")
    metadata = resolved.stat()
    if metadata.st_mode & 0o022:
        raise VProServiceError(f"{label} HMAC key file must not be group/world writable")
    if metadata.st_nlink != 1:
        raise VProServiceError(f"{label} HMAC key file must not have hard links")
    return resolved, key


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.isolated or not sys.flags.no_site or not sys.flags.dont_write_bytecode:
        print("ERROR: VPRO must be started by VPRO_LAUNCH.py with Python flags -I -S -B", file=sys.stderr)
        return 1
    args = _parser().parse_args(argv)
    try:
        anchor = os.environ.get("VPRO_FRAMEWORK_ANCHOR")
        if not anchor:
            raise VProServiceError("the protected launcher must set VPRO_FRAMEWORK_ANCHOR")
        release = verify_framework_release(
            FRAMEWORK_ROOT,
            FRAMEWORK_ROOT / "codex/vpro/framework_manifest.json",
            Path(anchor),
        )
        if args.command == "framework-verify":
            result = {"status": "PASS", "framework_version": release.version, "framework_digest": release.digest, "protected_paths": list(release.protected_paths)}
        elif args.command == "milestone-template":
            result = load_milestone_template(FRAMEWORK_ROOT)
        elif args.command in {"bundle-validate", "milestone-validate"}:
            if args.bundle is None or args.project_root is None:
                raise VProServiceError(
                    f"{args.command} requires --project-root and --bundle"
                )
            result = validate_milestone(
                args.bundle,
                project_root=args.project_root,
                schema_path=FRAMEWORK_ROOT / "schemas/vpro/milestone_bundle.schema.json",
            )
            if result["status"] == "PASS" and args.profile is not None:
                bundle = load_bundle(args.bundle, project_root=args.project_root)
                try:
                    resolved = bundle.resolve_profile(args.profile)
                except KeyError as exc:
                    raise VProServiceError(f"unknown milestone profile: {args.profile}") from exc
                result.update({"profile_id": resolved.profile.id, "claim": resolved.claim, "objective_ids": list(resolved.objective_ids), "gate_ids": list(resolved.gate_ids)})
        else:
            service = _controller(args, release)
            if args.command == "bind":
                result = service.bind(actor=_actor(args))
            elif args.command == "doctor":
                result = service.doctor()
            elif args.command == "status":
                result = service.status()
            elif args.command == "next":
                result = service.next_work_item(actor=_actor(args))
            elif args.command == "evaluate":
                result = service.evaluate_active(
                    actor=_actor(args),
                    work_item_id=args.work_item_id,
                )
            elif args.command == "review":
                result = service.submit_review(_json_object(args.report), actor=_actor(args))
            elif args.command == "accept-evaluator-repair":
                result = service.accept_evaluator_repair(
                    actor=_actor(args),
                    work_item_id=args.work_item_id,
                )
            elif args.command == "approve-gate":
                result = service.approve_gate(_json_object(args.approval), actor=_actor(args))
            elif args.command == "audit":
                result = service.audit()
            elif args.command == "verify-completion":
                result = service.verify_completion()
            else:  # pragma: no cover
                raise VProServiceError(f"unknown command: {args.command}")
    except (ContractError, FrameworkIntegrityError, ProgramRunnerError, StateStoreError, VProServiceError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _emit(result)
    return 1 if result.get("status") == "FAIL" else 0
