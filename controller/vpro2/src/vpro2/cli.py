from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from .contracts import ContractError, load_contract
from .roles import Authority
from .service import VPro2Controller, VPro2ServiceError


KEY_ENV = {
    "state": "VPRO2_STATE_HMAC_KEY_FILE",
    Authority.CONTROLLER: "VPRO2_CONTROLLER_HMAC_KEY_FILE",
    Authority.WORKER: "VPRO2_WORKER_HMAC_KEY_FILE",
    Authority.REVIEWER: "VPRO2_REVIEWER_HMAC_KEY_FILE",
    Authority.EVALUATOR: "VPRO2_EVALUATOR_HMAC_KEY_FILE",
    Authority.OPERATOR: "VPRO2_OPERATOR_HMAC_KEY_FILE",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vpro2")
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--run-id")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("framework-verify")
    subparsers.add_parser("milestone-template")
    subparsers.add_parser("milestone-validate")
    subparsers.add_parser("bind-challenge")
    bind = subparsers.add_parser("bind")
    bind.add_argument("--envelope", type=Path, required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("audit")
    subparsers.add_parser("verify-terminal")
    subparsers.add_parser("evaluate")
    for name in ("submit-plan", "review-plan", "approve-objective", "worker-result", "review-change", "abort"):
        command = subparsers.add_parser(name)
        command.add_argument("--envelope", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "framework-verify":
            result = {
                "status": "PASS",
                "framework_version": _verified_environment("VPRO2_VERIFIED_FRAMEWORK_VERSION"),
                "framework_digest": _verified_environment("VPRO2_VERIFIED_FRAMEWORK_DIGEST"),
            }
        elif args.command == "milestone-template":
            template = Path(__file__).resolve().parents[2] / "templates/vpro2/milestone.template.json"
            result = json.loads(template.read_text(encoding="utf-8"))
        elif args.command == "milestone-validate":
            project_root = _required(args.project_root, "--project-root")
            contract_path = _required(args.contract, "--contract")
            contract = load_contract(contract_path, project_root=project_root)
            result = {
                "status": "PASS",
                "schema_version": contract.schema_version,
                "milestone_id": contract.milestone.id,
                "condition_ids": [item.id for item in contract.success_conditions],
                "evaluator_ids": [item.id for item in contract.evaluators],
                "evidence_requirement_ids": [item.id for item in contract.evidence_requirements],
            }
        else:
            controller = _controller(args)
            if args.command == "bind-challenge":
                result = controller.bind_challenge(run_id=_required(args.run_id, "--run-id"))
            elif args.command == "bind":
                result = controller.bind(
                    run_id=_required(args.run_id, "--run-id"),
                    operator_envelope=_json_object(args.envelope),
                )
            elif args.command == "status":
                result = controller.status()
            elif args.command == "audit":
                result = controller.audit()
            elif args.command == "verify-terminal":
                result = controller.verify_terminal()
            elif args.command == "evaluate":
                result = controller.evaluate()
            elif args.command == "submit-plan":
                result = controller.submit_plan(_json_object(args.envelope))
            elif args.command == "review-plan":
                result = controller.review_plan(_json_object(args.envelope))
            elif args.command == "approve-objective":
                result = controller.approve_objective(_json_object(args.envelope))
            elif args.command == "worker-result":
                result = controller.submit_worker_result(_json_object(args.envelope))
            elif args.command == "review-change":
                result = controller.review_change(_json_object(args.envelope))
            elif args.command == "abort":
                result = controller.abort(_json_object(args.envelope))
            else:  # pragma: no cover - argparse owns command selection
                raise VPro2ServiceError(f"unsupported command {args.command}")
    except (ContractError, VPro2ServiceError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _controller(args: argparse.Namespace) -> VPro2Controller:
    project_root = _required(args.project_root, "--project-root")
    workspace_root = _required(args.workspace_root, "--workspace-root")
    contract_path = _required(args.contract, "--contract")
    run_root = _required(args.run_root, "--run-root")
    framework_root = Path(__file__).resolve().parents[2]
    forbidden_roots = (
        framework_root,
        project_root.resolve(),
        workspace_root.resolve(),
        run_root.resolve(),
    )
    state_key = _secret(KEY_ENV["state"], forbidden_roots)
    authority_keys = {
        role: _secret(KEY_ENV[role], forbidden_roots)
        for role in Authority
    }
    return VPro2Controller(
        project_root=project_root,
        workspace_root=workspace_root,
        contract_path=contract_path,
        run_root=run_root,
        framework_digest=_verified_environment("VPRO2_VERIFIED_FRAMEWORK_DIGEST"),
        state_seal_key=state_key,
        authority_keys=authority_keys,
    )


def _secret(name: str, forbidden_roots: tuple[Path, ...]) -> bytes:
    raw = os.environ.get(name)
    if not raw:
        raise VPro2ServiceError(f"the protected launcher must set {name}")
    path = Path(raw)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise VPro2ServiceError(f"{name} must identify an absolute regular file")
    resolved = path.resolve()
    if any(resolved.is_relative_to(root) for root in forbidden_roots):
        raise VPro2ServiceError(f"{name} must be outside worker and controller roots")
    metadata = resolved.stat()
    if metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise VPro2ServiceError(f"{name} must have one link and mode 0600 or stricter")
    value = resolved.read_bytes()
    if len(value) < 32:
        raise VPro2ServiceError(f"{name} must contain at least 32 bytes")
    return value


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise VPro2ServiceError(f"{path} must contain a JSON object")
    return value


def _verified_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise VPro2ServiceError(f"verified launcher did not set {name}")
    return value


def _required(value: Any, name: str) -> Any:
    if value is None:
        raise VPro2ServiceError(f"{name} is required for this command")
    return value
