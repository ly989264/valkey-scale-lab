from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from valkey_scale_lab.vpro.digests import workspace_minus_allowed_digest
from valkey_scale_lab.vpro.integrity import FrameworkIntegrityError, verify_framework_release
from valkey_scale_lab.vpro.runner import ProgramRunner, ProgramRunnerError
from valkey_scale_lab.vpro.service import VProServiceError
from valkey_scale_lab.vpro.store import StateStore

TEST_APPROVAL_KEY = b"vpro-test-approval-key-32-bytes-minimum"


def _active_work_item_id(controller) -> str:
    work = controller.store.load().get("active_work_item")
    assert isinstance(work, dict)
    return str(work["work_item_id"])


def _evaluate(controller, *, actor: str) -> dict:
    return controller.evaluate_active(
        actor=actor,
        work_item_id=_active_work_item_id(controller),
    )


def _accept_repair(controller, *, actor: str) -> dict:
    return controller.accept_evaluator_repair(
        actor=actor,
        work_item_id=_active_work_item_id(controller),
    )


def _complete_objective(controller) -> None:
    controller.bind(actor="operator")
    work = controller.next_work_item(actor="worker")
    assert work["type"] == "WORK"
    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    assert review["type"] == "REVIEW_ACCEPTANCE"
    controller.submit_review(
        {"work_item_id": review["work_item_id"], "decision": "NO_GAP"},
        actor="reviewer",
    )


def _approval(
    controller,
    required: dict,
    *,
    run_id: str | None = None,
    actor: str = "operator",
    expires_at_unix: int | None = None,
) -> dict:
    unsigned = {
        "schema_version": "vpro-gate-approval-v2",
        "run_id": run_id or required["run_id"],
        "gate_id": required["gate_id"],
        "bundle_digest": required["bundle_digest"],
        "product_digest": required["product_digest"],
        "approval_challenge_digest": required["approval_challenge_digest"],
        "cost_acknowledged": True,
        "expires_at_unix": expires_at_unix or int(time.time()) + 300,
        "nonce": "approval-nonce-1",
        "operator_id": actor,
    }
    encoded = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(
        TEST_APPROVAL_KEY,
        b"vpro-gate-approval-v2\0" + encoded,
        hashlib.sha256,
    ).hexdigest()
    return {**unsigned, "hmac_sha256": signature}


def _reach_capture(controller) -> dict:
    _complete_objective(controller)
    guard = controller.next_work_item(actor="gate-runner")
    assert guard["type"] == "GATE_GUARD"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    preflight = controller.next_work_item(actor="gate-runner")
    assert preflight["type"] == "GATE_PREFLIGHT"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    required = controller.next_work_item(actor="gate-runner")
    assert required["type"] == "GATE_APPROVAL_REQUIRED"
    controller.approve_gate(_approval(controller, required), actor="operator")
    capture = controller.next_work_item(actor="gate-runner")
    assert capture["type"] == "GATE_CAPTURE"
    return capture


def test_bind_work_pass_fresh_review_and_done(controller_factory) -> None:
    controller, _, _ = controller_factory()

    _complete_objective(controller)
    done = controller.next_work_item(actor="operator")

    assert done["type"] == "DONE"
    assert done["claim"] == "MILESTONE_COMPLETE"
    assert controller.status()["status"] == "COMPLETE"
    assert controller.verify_completion()["status"] == "PASS"


def test_stale_upstream_objective_is_reverified_before_dag_completion(
    controller_factory,
    bundle_factory,
    vpro_project,
) -> None:
    raw = bundle_factory()
    raw["clauses"].append(
        {"id": "SecondArtifactExists", "text": "The dependent artifact passes acceptance."}
    )
    raw["checks"].append(
        {
            **raw["checks"][1],
            "id": "second-objective-check",
            "inputs": ["acceptance/pass.py", "product/second.txt"],
        }
    )
    raw["objectives"].append(
        {
            "id": "CreateSecondArtifact",
            "title": "Create the dependent artifact",
            "depends_on": ["CreateArtifact"],
            "clause_ids": ["SecondArtifactExists"],
            "check_ids": ["second-objective-check"],
            "context_paths": ["product"],
            "worker_write_paths": ["product/second.txt"],
            "required_for_milestone": True,
        }
    )
    raw["profiles"][0]["objective_ids"] = ["CreateSecondArtifact"]
    (vpro_project.root / "product/second.txt").write_text("ready\n", encoding="utf-8")
    controller, _, _ = controller_factory(bundle=raw)
    controller.bind(actor="operator")

    first = controller.next_work_item(actor="worker-a")
    assert (first["type"], first["objective_id"]) == ("WORK", "CreateArtifact")
    assert _evaluate(controller, actor="worker-a")["status"] == "PASS"
    first_review = controller.next_work_item(actor="reviewer-a")
    controller.submit_review(
        {"work_item_id": first_review["work_item_id"], "decision": "NO_GAP"},
        actor="reviewer-a",
    )

    second = controller.next_work_item(actor="worker-b")
    assert (second["type"], second["objective_id"]) == ("WORK", "CreateSecondArtifact")
    assert _evaluate(controller, actor="worker-b")["status"] == "PASS"
    second_review = controller.next_work_item(actor="reviewer-b")
    controller.submit_review(
        {"work_item_id": second_review["work_item_id"], "decision": "NO_GAP"},
        actor="reviewer-b",
    )

    (vpro_project.root / "product/work.txt").write_text("changed upstream\n", encoding="utf-8")
    verify = controller.next_work_item(actor="verifier")
    assert (verify["type"], verify["objective_id"]) == ("VERIFY", "CreateArtifact")
    assert _evaluate(controller, actor="verifier")["status"] == "PASS"
    verify_review = controller.next_work_item(actor="reviewer-c")
    controller.submit_review(
        {"work_item_id": verify_review["work_item_id"], "decision": "NO_GAP"},
        actor="reviewer-c",
    )

    dependent_verify = controller.next_work_item(actor="verifier-2")
    assert (dependent_verify["type"], dependent_verify["objective_id"]) == (
        "VERIFY",
        "CreateSecondArtifact",
    )
    assert _evaluate(controller, actor="verifier-2")["status"] == "PASS"
    dependent_review = controller.next_work_item(actor="reviewer-d")
    controller.submit_review(
        {"work_item_id": dependent_review["work_item_id"], "decision": "NO_GAP"},
        actor="reviewer-d",
    )
    assert controller.next_work_item(actor="operator")["type"] == "DONE"
    assert controller.verify_completion()["status"] == "PASS"


def test_successful_evaluator_repair_reverifies_and_completes(
    controller_factory,
    vpro_project,
) -> None:
    gap_oracle = vpro_project.root / "acceptance/evaluator_gap.py"
    gap_oracle.write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if 'VERSION = 2' in Path('evaluator/evaluator.py').read_text() else 1)\n",
        encoding="utf-8",
    )
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "contract_clause_id": "ArtifactExists",
            "gap_kind": "EVALUATOR_GAP",
            "program_check": {
                "id": "evaluator-version-gap",
                "tier": "cheap",
                "argv": ["python3", "acceptance/evaluator_gap.py"],
                "cwd": ".",
                "timeout_seconds": 30,
                "inputs": ["acceptance/evaluator_gap.py", "evaluator/evaluator.py"],
                "outputs": [],
                "authority": "evaluator",
                "capabilities": [],
                "cache": "by_input_digest",
                "mode": "standard",
            },
        },
        actor="reviewer",
    )

    repair = controller.next_work_item(actor="repairer")
    assert repair["type"] == "EVALUATOR_REPAIR"
    (vpro_project.root / "evaluator/evaluator.py").write_text(
        "EVALUATOR_VERSION = 2\n",
        encoding="utf-8",
    )
    assert _accept_repair(controller, actor="repairer")["status"] == "PASS"
    state = controller.store.load()
    assert state["evaluator_generation"] == 1
    assert state["objectives"]["CreateArtifact"]["status"] == "REVERIFY"

    verify = controller.next_work_item(actor="worker-2")
    assert verify["type"] == "VERIFY"
    assert _evaluate(controller, actor="worker-2")["status"] == "PASS"
    state = controller.store.load()
    results = state["objectives"]["CreateArtifact"]["last_result"]["results"]
    assert [result["check_id"] for result in results] == [
        "common",
        "objective-check",
        "evaluator-version-gap",
        "closure",
    ]
    gap_result = next(result for result in results if result["check_id"] == "evaluator-version-gap")
    bundle, _ = controller._definition()
    assert gap_result["input_digest"] == controller._runner(bundle, state).input_digest(
        ("acceptance/evaluator_gap.py", "evaluator/evaluator.py")
    )
    final_review = controller.next_work_item(actor="reviewer-2")
    controller.submit_review(
        {"work_item_id": final_review["work_item_id"], "decision": "NO_GAP"},
        actor="reviewer-2",
    )
    assert controller.next_work_item(actor="operator")["type"] == "DONE"
    assert controller.verify_completion()["status"] == "PASS"


def test_review_budget_exhaustion_blocks_without_a_final_no_gap(
    controller_factory,
    bundle_factory,
    vpro_project,
) -> None:
    raw = bundle_factory()
    raw["acceptance"]["max_review_rounds"] = 1
    gap_oracle = vpro_project.root / "acceptance/review_gap.py"
    gap_oracle.write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if Path('product/work.txt').read_text() == 'fixed\\n' else 1)\n",
        encoding="utf-8",
    )
    controller, _, _ = controller_factory(bundle=raw)
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "contract_clause_id": "ArtifactExists",
            "gap_kind": "PRODUCT_GAP",
            "program_check": {
                "id": "review-gap",
                "tier": "cheap",
                "argv": ["python3", "acceptance/review_gap.py"],
                "cwd": ".",
                "timeout_seconds": 30,
                "inputs": ["acceptance/review_gap.py", "product/work.txt"],
                "outputs": [],
                "authority": "bundle",
                "capabilities": [],
                "cache": "by_input_digest",
                "mode": "standard",
            },
        },
        actor="reviewer",
    )
    controller.next_work_item(actor="worker")
    (vpro_project.root / "product/work.txt").write_text("fixed\n", encoding="utf-8")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"

    blocked = controller.next_work_item(actor="reviewer-2")

    assert blocked["type"] == "BLOCKED"
    assert controller.status()["status"] == "BLOCKED"
    state = controller.store.load()
    assert state["objectives"]["CreateArtifact"]["status"] == "BLOCKED"
    assert state["events"][-1]["event"] == "OBJECTIVE_BLOCKED"
    assert state["events"][-1]["reason"] == "acceptance review budget exhausted without NO_GAP"


def test_replan_diagnosis_is_bounded_and_reaches_the_next_worker(
    controller_factory,
    bundle_factory,
    monkeypatch,
) -> None:
    raw = bundle_factory()
    raw["acceptance"]["max_attempts"] = 1
    raw["acceptance"]["failure_excerpt_bytes"] = 3000
    raw["acceptance"]["max_context_bytes"] = 3000
    controller, _, _ = controller_factory(bundle=raw)
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    monkeypatch.setattr(
        controller,
        "_run_checks",
        lambda *args, **kwargs: [
            {
                "check_id": "common",
                "definition_digest": "definition-a",
                "tier": "cheap",
                "status": "FAIL",
                "input_digest": "input-a",
                "returncode": 1,
                "cached": False,
            }
        ],
    )
    assert _evaluate(controller, actor="worker")["status"] == "FAIL"
    review = controller.next_work_item(actor="reviewer")
    assert review["type"] == "REVIEW_REPLAN"
    oversized = "x" * (raw["acceptance"]["failure_excerpt_bytes"] + 1)
    with pytest.raises(VProServiceError, match="diagnosis exceeds failure excerpt budget"):
        controller.submit_review(
            {"work_item_id": review["work_item_id"], "decision": "REPLAN", "diagnosis": oversized},
            actor="reviewer",
        )
    with pytest.raises(VProServiceError, match="does not fit next work item context budget"):
        controller.submit_review(
            {"work_item_id": review["work_item_id"], "decision": "REPLAN", "diagnosis": "界" * 800},
            actor="reviewer",
        )

    diagnosis = "The current implementation never reaches the required artifact branch."
    controller.submit_review(
        {"work_item_id": review["work_item_id"], "decision": "REPLAN", "diagnosis": diagnosis},
        actor="reviewer",
    )
    work = controller.next_work_item(actor="worker-2")

    assert work["type"] == "WORK"
    assert work["last_program_result"]["status"] == "REPLAN"
    assert work["last_program_result"]["diagnosis"] == diagnosis


def test_bind_rejects_a_nonempty_run_root(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory()
    vpro_project.state_root.mkdir(parents=True)
    (vpro_project.state_root / "leftover.txt").write_text("stale run material\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="new empty run root"):
        controller.bind(actor="operator")


def test_path_prepend_cannot_replace_a_tool_sealed_at_bind(
    controller_factory,
    vpro_project,
    monkeypatch,
) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    fake_bin = vpro_project.workspace / "fake-bin"
    fake_bin.mkdir()
    marker = vpro_project.workspace / "fake-python-ran"
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\n" + f"printf ran > {marker!s}\n" + "exit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    try:
        _evaluate(controller, actor="worker")
    except (ProgramRunnerError, VProServiceError):
        pass
    assert not marker.exists(), "a PATH-prepended executable bypassed the sealed tool identity"


def test_python_check_isolated_startup_ignores_worker_sitecustomize(
    controller_factory,
    vpro_project,
) -> None:
    marker = vpro_project.workspace / "sitecustomize-ran"
    source = vpro_project.root / "src"
    source.mkdir()
    (source / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")

    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    assert not marker.exists(), "worker sitecustomize executed before the authoritative adapter"


def test_check_receives_only_exact_controller_sealed_tool_paths(
    controller_factory,
    vpro_project,
) -> None:
    expected_python = str(Path(shutil.which("python3") or "").resolve())
    (vpro_project.root / "acceptance/pass.py").write_text(
        "import json, os\n"
        "tools = json.loads(os.environ['VPRO_SEALED_TOOLS_JSON'])\n"
        f"if tools != {{'python3': {expected_python!r}}}:\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")

    assert _evaluate(controller, actor="worker")["status"] == "PASS"


def test_input_digest_rejects_a_symlink_directory(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    target = vpro_project.workspace / "mutable-target"
    target.mkdir()
    (target / "value.txt").write_text("first\n", encoding="utf-8")
    (vpro_project.root / "product/linked").symlink_to(target, target_is_directory=True)

    with pytest.raises(ProgramRunnerError, match="contains a symlink"):
        controller.next_work_item(actor="worker")


def test_directory_input_digest_has_unambiguous_file_record_boundaries(
    controller_factory,
    vpro_project,
) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    bundle, _ = controller._definition()
    runner = controller._runner(bundle, controller.store.load())
    capture = vpro_project.state_root / "evidence/capture"
    capture.mkdir(parents=True)
    first = capture / "a"
    second = capture / "b"
    first.write_bytes(b"X")
    second.write_bytes(b"Y")
    before = runner.input_digest(("evidence/capture",))
    injected_record = f"FILE\0{second.relative_to(vpro_project.state_root).as_posix()}\0".encode()
    first.write_bytes(b"X" + injected_record + b"Y")
    second.unlink()

    assert runner.input_digest(("evidence/capture",)) != before


@pytest.mark.parametrize("directory", ["__pycache__", ".pytest_cache", ".mypy_cache", ".git"])
def test_directory_input_digest_includes_conventional_cache_and_metadata_directories(
    controller_factory,
    vpro_project,
    directory: str,
) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    bundle, _ = controller._definition()
    runner = controller._runner(bundle, controller.store.load())
    before = runner.input_digest(("product",))
    metadata = vpro_project.root / "product" / directory / "state"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("changes execution inputs\n", encoding="utf-8")

    assert runner.input_digest(("product",)) != before


@pytest.mark.parametrize("target_name", ["product", "product/work.txt"])
def test_directory_input_digest_includes_file_and_directory_modes(
    controller_factory,
    vpro_project,
    target_name: str,
) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    bundle, _ = controller._definition()
    runner = controller._runner(bundle, controller.store.load())
    before = runner.input_digest(("product",))
    target = vpro_project.root / target_name
    current_mode = target.stat().st_mode & 0o7777
    target.chmod(current_mode ^ 0o010)

    assert runner.input_digest(("product",)) != before


def test_workspace_authorization_digest_has_unambiguous_file_record_boundaries(
    tmp_path: Path,
) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.write_bytes(b"X")
    second.write_bytes(b"Y")
    before = workspace_minus_allowed_digest(tmp_path, ())
    first.write_bytes(b"X\0b\0FILE\0Y")
    second.unlink()

    assert workspace_minus_allowed_digest(tmp_path, ()) != before


@pytest.mark.parametrize("operation", ["create", "remove", "rename"])
def test_workspace_authorization_detects_empty_directory_changes(
    controller_factory,
    vpro_project,
    operation: str,
) -> None:
    original = vpro_project.workspace / "unauthorized-empty"
    if operation in {"remove", "rename"}:
        original.mkdir()
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    if operation == "create":
        original.mkdir()
    elif operation == "remove":
        original.rmdir()
    else:
        original.rename(vpro_project.workspace / "renamed-empty")

    with pytest.raises(VProServiceError, match="outside the work-item authorization"):
        _evaluate(controller, actor="worker")


@pytest.mark.parametrize("target_kind", ["directory", "file"])
def test_workspace_authorization_detects_mode_changes(
    controller_factory,
    vpro_project,
    target_kind: str,
) -> None:
    target = vpro_project.workspace / f"unauthorized-{target_kind}"
    if target_kind == "directory":
        target.mkdir(mode=0o700)
    else:
        target.write_text("mode-sensitive\n", encoding="utf-8")
        target.chmod(0o600)
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    target.chmod(0o755 if target_kind == "directory" else 0o700)

    with pytest.raises(VProServiceError, match="outside the work-item authorization"):
        _evaluate(controller, actor="worker")


def test_workspace_authorization_detects_workspace_root_mode_change(
    controller_factory,
    vpro_project,
) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    current_mode = vpro_project.workspace.stat().st_mode & 0o7777
    vpro_project.workspace.chmod(current_mode ^ 0o010)

    with pytest.raises(VProServiceError, match="outside the work-item authorization"):
        _evaluate(controller, actor="worker")


def test_objective_work_prepares_and_authorizes_missing_nested_write_parents(
    controller_factory,
    bundle_factory,
    vpro_project,
) -> None:
    raw = bundle_factory()
    raw["objectives"][0]["worker_write_paths"] = ["product/new/nested/artifact.txt"]
    next(check for check in raw["checks"] if check["id"] == "objective-check")["inputs"].append(
        "product/new/nested/artifact.txt"
    )
    controller, _, _ = controller_factory(bundle=raw)
    controller.bind(actor="operator")

    work = controller.next_work_item(actor="worker")
    target = vpro_project.root / "product/new/nested/artifact.txt"
    assert target.parent.is_dir()
    target.write_text("authorized\n", encoding="utf-8")

    assert work["allowed_write_paths"] == ["product/new/nested/artifact.txt"]
    assert _evaluate(controller, actor="worker")["status"] == "PASS"


@pytest.mark.parametrize("backend", ["sandbox-exec", "bubblewrap"])
def test_check_sandbox_allows_writes_only_below_controller_state(
    vpro_project,
    monkeypatch,
    backend: str,
) -> None:
    secret = vpro_project.operator / "keys" / "controller.key"
    secret.parent.mkdir(parents=True)
    secret.write_text("secret-value\n", encoding="utf-8")
    runner = ProgramRunner(
        project_root=vpro_project.root,
        workspace_root=vpro_project.workspace,
        state_root=vpro_project.state_root,
        logs_root=vpro_project.state_root / "logs",
        excerpt_bytes=100,
        allowed_tools=(),
        tool_seals=None,
        sandbox_seal={
            "backend": backend,
            "entrypoint": "/operator/sandbox",
            "path": "/operator/sandbox",
            "sha256": "0" * 64,
        },
        run_context={},
        secret_paths=(secret,),
    )
    writable = vpro_project.state_root / "scratch" / "check"
    writable.mkdir(parents=True)
    readonly_input = writable / "raw-capture.json"
    readonly_input.write_text("preserve\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_sealed_sandbox_executable", lambda: "/operator/sandbox")

    command = runner._sandboxed_command(
        ["/operator/python", "acceptance/pass.py"],
        cwd=vpro_project.root,
        writable_paths=(writable,),
        readonly_paths=(readonly_input,),
    )
    try:
        joined = " ".join(command)
        assert str(writable) in joined
        if backend == "sandbox-exec":
            assert "deny file-write*" in command[2]
            assert "deny file-read*" in command[2]
            assert f"(deny file-write* (literal {json.dumps(str(readonly_input))}))" in command[2]
            assert str(secret) in command[2]
            assert "deny network*" in command[2]
            assert str(vpro_project.workspace) not in command[2]
        else:
            assert command[1:7] == [
                "--die-with-parent",
                "--new-session",
                "--unshare-pid",
                "--ro-bind",
                "/",
                "/",
            ]
            assert "--dev-bind" not in command
            assert "--dev" in command
            assert "--unshare-net" in command
            assert "--seccomp" in command
            seccomp_fd = int(command[command.index("--seccomp") + 1])
            assert seccomp_fd in runner._sandbox_pass_fds
            assert ["--ro-bind", "/dev/null", str(secret)] == command[
                command.index(str(secret)) - 2 : command.index(str(secret)) + 1
            ]
            assert "--bind" in command
            writable_bind = command.index(str(writable))
            readonly_bind = command.index(str(readonly_input))
            assert writable_bind < readonly_bind
            assert command[readonly_bind - 1 : readonly_bind + 2] == [
                "--ro-bind",
                str(readonly_input),
                str(readonly_input),
            ]
    finally:
        runner._close_sandbox_fds()


@pytest.mark.parametrize(
    (
        "machine",
        "expected_arch",
        "reject_x32",
        "blocked_socket_syscalls",
        "allowed_local_ipc_syscalls",
        "blocked_security_syscalls",
    ),
    [
        (
            "x86_64",
            0xC000003E,
            True,
            (41, 42, 43, 49, 50, 288),
            (44, 45, 46, 47, 48, 51, 52, 53, 54, 55, 299, 307),
            (248, 249, 250, 425, 426, 427, 438),
        ),
        (
            "aarch64",
            0xC00000B7,
            False,
            (198, 200, 201, 202, 203, 242),
            (199, 204, 205, 206, 207, 208, 209, 210, 211, 212, 243, 269),
            (217, 218, 219, 425, 426, 427, 438),
        ),
    ],
)
def test_linux_seccomp_policy_blocks_external_socket_entrypoints_but_keeps_local_ipc(
    monkeypatch,
    machine: str,
    expected_arch: int,
    reject_x32: bool,
    blocked_socket_syscalls: tuple[int, ...],
    allowed_local_ipc_syscalls: tuple[int, ...],
    blocked_security_syscalls: tuple[int, ...],
) -> None:
    monkeypatch.setattr("valkey_scale_lab.vpro.runner.platform.machine", lambda: machine)
    fd = ProgramRunner._no_external_services_seccomp_fd()
    try:
        payload = os.read(fd, 65536)
    finally:
        os.close(fd)
    instructions = [
        struct.unpack("HBBI", payload[offset : offset + 8])
        for offset in range(0, len(payload), 8)
    ]

    def action(syscall_number: int, *, arch: int = expected_arch) -> int:
        accumulator = 0
        program_counter = 0
        while True:
            code, jump_true, jump_false, value = instructions[program_counter]
            if code == 0x20:
                accumulator = arch if value == 4 else syscall_number
                program_counter += 1
            elif code == 0x15:
                program_counter += 1 + (jump_true if accumulator == value else jump_false)
            elif code == 0x45:
                program_counter += 1 + (jump_true if accumulator & value else jump_false)
            elif code == 0x06:
                return value
            else:  # pragma: no cover - this fixed generator emits only these operations
                raise AssertionError(f"unexpected BPF opcode: {code:#x}")

    assert instructions[:4] == [
        (0x20, 0, 0, 4),
        (0x15, 1, 0, expected_arch),
        (0x06, 0, 0, 0x80000000),
        (0x20, 0, 0, 0),
    ]
    assert ((0x45, 0, 1, 0x40000000) in instructions) is reject_x32
    for syscall_number in (*blocked_socket_syscalls, *blocked_security_syscalls):
        assert (0x15, 0, 1, syscall_number) in instructions
        assert action(syscall_number) == 0x00050001
    for syscall_number in allowed_local_ipc_syscalls:
        assert (0x15, 0, 1, syscall_number) not in instructions
        assert action(syscall_number) == 0x7FFF0000
    assert action(53, arch=0xDEADBEEF) == 0x80000000
    if reject_x32:
        assert action(0x40000000 | 53) == 0x00050001


def test_linux_sandbox_fails_at_bind_on_an_unsupported_architecture(
    vpro_project,
    monkeypatch,
) -> None:
    monkeypatch.setattr("valkey_scale_lab.vpro.runner.platform.system", lambda: "Linux")
    monkeypatch.setattr("valkey_scale_lab.vpro.runner.platform.machine", lambda: "riscv64")

    with pytest.raises(ProgramRunnerError, match="no fail-closed Linux seccomp policy"):
        ProgramRunner.seal_sandbox(
            workspace_root=vpro_project.workspace,
            state_root=vpro_project.state_root,
        )


def test_real_platform_sandbox_smoke(vpro_project) -> None:
    try:
        seal = ProgramRunner.seal_sandbox(
            workspace_root=vpro_project.workspace,
            state_root=vpro_project.state_root,
        )
    except ProgramRunnerError as exc:
        if "sandbox is unavailable" in str(exc) or "no filesystem sandbox backend" in str(exc):
            pytest.skip(str(exc))
        raise
    secret = vpro_project.operator / "keys" / "sandbox-secret.key"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("must-not-be-readable\n", encoding="utf-8")
    scratch = vpro_project.state_root / "scratch" / "smoke"
    scratch.mkdir(parents=True)
    readonly_input = scratch / "raw-capture.json"
    readonly_input.write_text("preserve\n", encoding="utf-8")
    denied = vpro_project.workspace / "sandbox-denied.txt"
    socket_path = Path("/tmp") / f"vpro-sandbox-{os.getpid()}-{time.time_ns()}.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(socket_path))
        listener.listen(1)
    except OSError as exc:
        listener.close()
        socket_path.unlink(missing_ok=True)
        pytest.skip(f"host Unix-socket sandbox probe is unavailable: {exc}")
    local_ipc_probe = ""
    if seal["backend"] == "bubblewrap":
        listener.set_inheritable(True)
        listener_fd = listener.fileno()
        listener_link = f"socket:[{os.fstat(listener_fd).st_ino}]"
        local_ipc_probe = (
            "left, right = socket.socketpair()\n"
            "left.sendall(b'local-ipc')\n"
            "if right.recv(32) != b'local-ipc':\n"
            "    raise SystemExit(11)\n"
            "left.close()\n"
            "right.close()\n"
            "import os\n"
            "try:\n"
            f"    inherited = os.readlink('/proc/self/fd/{listener_fd}')\n"
            "except OSError:\n"
            "    pass\n"
            "else:\n"
            f"    if inherited == {listener_link!r}:\n"
            "        raise SystemExit(12)\n"
        )
    socket_probe = (
        "import socket\n"
        + local_ipc_probe
        + "try:\n"
        "    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
        f"    client.connect({str(socket_path)!r})\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit(10)\n"
    )
    runner = ProgramRunner(
        project_root=vpro_project.root,
        workspace_root=vpro_project.workspace,
        state_root=vpro_project.state_root,
        logs_root=vpro_project.state_root / "logs",
        excerpt_bytes=100,
        allowed_tools=(),
        tool_seals=None,
        sandbox_seal=seal,
        run_context={},
        secret_paths=(secret,),
    )
    script = (
        "from pathlib import Path\n"
        f"Path({str(scratch / 'allowed.txt')!r}).write_text('ok')\n"
        "try:\n"
        f"    Path({str(readonly_input)!r}).write_text('tampered')\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit(7)\n"
        f"secret = Path({str(secret)!r})\n"
        "try:\n"
        "    exposed = secret.read_bytes()\n"
        "except OSError:\n"
        "    exposed = b''\n"
        "if b'must-not-be-readable' in exposed:\n"
        "    raise SystemExit(8)\n"
        "try:\n"
        f"    Path({str(denied)!r}).write_text('bad')\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit(9)\n"
        + socket_probe
    )
    command = runner._sandboxed_command(
        [sys.executable, "-I", "-S", "-B", "-c", script],
        cwd=vpro_project.root,
        writable_paths=(scratch,),
        readonly_paths=(readonly_input,),
    )
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            close_fds=True,
            pass_fds=runner._sandbox_pass_fds,
            stdin=subprocess.DEVNULL,
        )
    finally:
        runner._close_sandbox_fds()
        listener.close()
        socket_path.unlink(missing_ok=True)
    if completed.returncode == 71 and "sandbox_apply: Operation not permitted" in completed.stdout:
        pytest.skip("nested macOS sandbox is unavailable in this test environment")
    assert completed.returncode == 0, completed.stdout
    assert (scratch / "allowed.txt").is_file()
    assert readonly_input.read_text(encoding="utf-8") == "preserve\n"
    assert not denied.exists()


def test_isolated_launcher_keeps_stdlib_ahead_of_worker_source(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[2]
    shutil.copyfile(project / "VPRO_LAUNCH.py", tmp_path / "VPRO_LAUNCH.py")
    package = tmp_path / "src/valkey_scale_lab/vpro"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    marker = tmp_path / "stdlib-shadow-ran"
    success = tmp_path / "bootstrap-ran"
    (tmp_path / "src/json.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    (package / "__main__.py").write_text(
        f"import json\nfrom pathlib import Path\nPath({str(success)!r}).write_text(json.dumps({{'ok': True}}))\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(tmp_path / "VPRO_LAUNCH.py")],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
    assert success.is_file()
    assert not marker.exists(), "worker source shadowed a standard-library bootstrap import"


def test_framework_root_cannot_be_inside_worker_workspace(controller_factory, vpro_project) -> None:
    with pytest.raises(VProServiceError, match="framework root must be outside"):
        controller_factory(framework_root=vpro_project.root)


def test_bundle_and_state_roots_cannot_be_inside_worker_workspace(controller_factory, vpro_project) -> None:
    with pytest.raises(VProServiceError, match="bound bundle must be outside"):
        controller_factory(bundle_path=vpro_project.root / "bundle.json")
    with pytest.raises(VProServiceError, match="state root must be outside"):
        controller_factory(state_root=vpro_project.workspace / "runs" / "run-1")


@pytest.mark.parametrize(
    "relative",
    [
        "sibling-write.txt",
        "__pycache__/state",
        ".pytest_cache/lastfailed",
        ".mypy_cache/state",
        ".git/index.lock",
    ],
)
def test_workspace_sibling_write_invalidates_active_work(
    controller_factory,
    vpro_project,
    relative: str,
) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    unauthorized = vpro_project.workspace / relative
    unauthorized.parent.mkdir(parents=True, exist_ok=True)
    unauthorized.write_text("unauthorized\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="outside the work-item authorization"):
        _evaluate(controller, actor="worker")


def test_worker_cannot_review_own_result_and_review_items_are_actor_bound(controller_factory) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"

    with pytest.raises(VProServiceError, match="fresh actor"):
        controller.next_work_item(actor="worker")

    review = controller.next_work_item(actor="reviewer")
    with pytest.raises(VProServiceError, match="belongs to another actor"):
        controller.submit_review(
            {"work_item_id": review["work_item_id"], "decision": "NO_GAP"},
            actor="worker-two",
        )


@pytest.mark.parametrize("review_kind", ["acceptance", "replan"])
@pytest.mark.parametrize("drift_target", ["product", "workspace-sibling"])
def test_review_rejects_drift_outside_its_empty_write_authority(
    controller_factory,
    bundle_factory,
    vpro_project,
    monkeypatch,
    review_kind: str,
    drift_target: str,
) -> None:
    raw = bundle_factory()
    if review_kind == "replan":
        raw["acceptance"]["max_attempts"] = 1
    controller, _, _ = controller_factory(bundle=raw)
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    if review_kind == "replan":
        monkeypatch.setattr(
            controller,
            "_run_checks",
            lambda *args, **kwargs: [
                {
                    "check_id": "common",
                    "definition_digest": "definition-a",
                    "tier": "cheap",
                    "status": "FAIL",
                    "input_digest": "input-a",
                    "returncode": 1,
                    "cached": False,
                }
            ],
        )
        assert _evaluate(controller, actor="worker")["status"] == "FAIL"
    else:
        assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    expected_type = "REVIEW_REPLAN" if review_kind == "replan" else "REVIEW_ACCEPTANCE"
    assert review["type"] == expected_type
    if drift_target == "product":
        drift = vpro_project.root / "product/work.txt"
    else:
        drift = vpro_project.workspace / "review-sibling.txt"
    drift.write_text("unauthorized review drift\n", encoding="utf-8")
    report = (
        {"work_item_id": review["work_item_id"], "decision": "REPLAN", "diagnosis": "Try another branch."}
        if review_kind == "replan"
        else {"work_item_id": review["work_item_id"], "decision": "NO_GAP"}
    )

    with pytest.raises(VProServiceError, match="outside the work-item authorization"):
        controller.submit_review(report, actor="reviewer")

    assert controller.store.load()["active_work_item"]["work_item_id"] == review["work_item_id"]


def test_evaluate_rejects_a_stale_work_item_id(controller_factory) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    work = controller.next_work_item(actor="worker")

    with pytest.raises(VProServiceError, match="work item id does not match"):
        controller.evaluate_active(actor="worker", work_item_id="stale-work-item")

    assert controller.evaluate_active(
        actor="worker",
        work_item_id=work["work_item_id"],
    )["status"] == "PASS"


def test_bundle_tamper_is_rejected_after_bind(controller_factory) -> None:
    controller, bundle_path, raw = controller_factory()
    controller.bind(actor="operator")
    raw["milestone"]["title"] = "Tampered title"
    bundle_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="sealed bundle_digest changed"):
        controller.status()


def test_authoritative_acceptance_tamper_is_rejected_after_bind(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    (vpro_project.root / "acceptance/pass.py").write_text("raise SystemExit(1)\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="authoritative acceptance assets changed"):
        controller.status()


@pytest.mark.parametrize("target", ["state", "events"])
def test_state_and_mirrored_event_journal_tamper_fail_closed(controller_factory, target: str) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    if target == "state":
        state = json.loads(controller.store.state_path.read_text(encoding="utf-8"))
        state["iteration"] = 999
        controller.store.state_path.write_text(json.dumps(state), encoding="utf-8")
    else:
        controller.store.events_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="state integrity failure"):
        controller.status()


def test_unkeyed_event_chain_recomputation_cannot_forge_state(controller_factory) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    state = controller.store.load()
    state["iteration"] = 999
    latest = state["events"][-1]
    latest["state_payload_hash"] = StateStore.payload_digest(state)
    latest.pop("event_hash")
    encoded = json.dumps(latest, separators=(",", ":"), sort_keys=True).encode()
    latest["event_hash"] = hashlib.sha256(encoded).hexdigest()
    state["last_event_hash"] = latest["event_hash"]
    controller.store.state_path.write_text(json.dumps(state), encoding="utf-8")
    controller.store.events_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in state["events"]),
        encoding="utf-8",
    )

    with pytest.raises(VProServiceError, match="state integrity failure:.*hash mismatch"):
        controller.status()


def test_framework_manifest_anchor_and_kernel_tamper_fail_closed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    kernel = project / "kernel"
    kernel.mkdir(parents=True)
    protected = kernel / "controller.py"
    protected.write_text("VERSION = 1\n", encoding="utf-8")
    protected_digest = hashlib.sha256(protected.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "vpro-framework-manifest-v1",
        "framework_version": "1.0.0",
        "roots": ["kernel"],
        "files": [{"path": "kernel/controller.py", "sha256": protected_digest}],
        "protected_paths": [],
    }
    manifest_path = project / "framework_manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    anchor_path = tmp_path / "operator-anchor.json"
    anchor = {
        "schema_version": "vpro-framework-anchor-v1",
        "framework_version": "1.0.0",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    anchor_path.write_text(json.dumps(anchor, sort_keys=True) + "\n", encoding="utf-8")
    assert verify_framework_release(project, manifest_path, anchor_path).version == "1.0.0"

    protected.write_text("VERSION = 2\n", encoding="utf-8")
    with pytest.raises(FrameworkIntegrityError, match="framework file drift"):
        verify_framework_release(project, manifest_path, anchor_path)

    protected.write_text("VERSION = 1\n", encoding="utf-8")
    anchor["manifest_sha256"] = "0" * 64
    anchor_path.write_text(json.dumps(anchor, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(FrameworkIntegrityError, match="not authorized by the external anchor"):
        verify_framework_release(project, manifest_path, anchor_path)


def test_framework_same_content_symlink_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "framework"
    kernel = project / "kernel"
    kernel.mkdir(parents=True)
    protected = kernel / "controller.py"
    protected.write_text("VERSION = 1\n", encoding="utf-8")
    same_content = project / "same-content.py"
    same_content.write_bytes(protected.read_bytes())
    manifest = {
        "schema_version": "vpro-framework-manifest-v1",
        "framework_version": "1.0.0",
        "roots": ["kernel"],
        "files": [{"path": "kernel/controller.py", "sha256": hashlib.sha256(protected.read_bytes()).hexdigest()}],
        "protected_paths": [],
    }
    manifest_path = project / "framework_manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    anchor_path = tmp_path / "anchor.json"
    anchor_path.write_text(
        json.dumps(
            {
                "schema_version": "vpro-framework-anchor-v1",
                "framework_version": "1.0.0",
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    verify_framework_release(project, manifest_path, anchor_path)
    protected.unlink()
    protected.symlink_to(same_content)

    with pytest.raises(FrameworkIntegrityError, match="traverses a symlink"):
        verify_framework_release(project, manifest_path, anchor_path)


def test_changing_failure_identity_does_not_reset_attempts(controller_factory, monkeypatch) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    failures = iter(("input-a", "input-b"))

    def changing_failure(*args, **kwargs):
        input_digest = next(failures)
        return [
            {
                "check_id": "same-check",
                "definition_digest": "same-definition",
                "tier": "cheap",
                "status": "FAIL",
                "input_digest": input_digest,
                "returncode": 1,
                "cached": False,
            }
        ]

    monkeypatch.setattr(controller, "_run_checks", changing_failure)
    for expected_attempt in (1, 2):
        work = controller.next_work_item(actor="worker")
        assert work["attempt"] == expected_attempt
        assert _evaluate(controller, actor="worker")["status"] == "FAIL"

    progress = controller.store.load()["objectives"]["CreateArtifact"]
    assert progress["attempts_used"] == 2
    assert progress["stagnant_attempts"] == 0


def test_evaluator_repair_rejects_product_write(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    gap_check = {
        "id": "evaluator-gap",
        "tier": "cheap",
        "argv": ["python3", "acceptance/fail.py"],
        "cwd": ".",
        "timeout_seconds": 30,
        "inputs": ["acceptance/fail.py", "evaluator/evaluator.py"],
        "outputs": [],
        "authority": "evaluator",
        "capabilities": [],
        "cache": "by_input_digest",
        "mode": "standard",
    }
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "contract_clause_id": "ArtifactExists",
            "gap_kind": "EVALUATOR_GAP",
            "program_check": gap_check,
        },
        actor="reviewer",
    )
    repair = controller.next_work_item(actor="repairer")
    assert repair["type"] == "EVALUATOR_REPAIR"
    (vpro_project.root / "product/work.txt").write_text("unauthorized repair edit\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="outside the work-item authorization"):
        _accept_repair(controller, actor="repairer")


@pytest.mark.parametrize(
    ("gap_kind", "authority", "inputs", "capabilities", "message"),
    [
        (
            "PRODUCT_GAP",
            "bundle",
            ["acceptance/fail.py", "product/work.txt"],
            ["network"],
            "review check must be reviewer-admissible, cheap, and standard mode",
        ),
        (
            "EVALUATOR_GAP",
            "bundle",
            ["acceptance/fail.py", "evaluator/evaluator.py"],
            [],
            "gap classification does not match check authority",
        ),
        (
            "PRODUCT_GAP",
            "bundle",
            ["product/work.txt"],
            [],
            r"invalid reviewer check:.*argv\[1\].*authoritative",
        ),
    ],
    ids=["capabilities", "authority", "authoritative-input"],
)
def test_reviewer_checks_cannot_expand_authority(
    controller_factory,
    gap_kind: str,
    authority: str,
    inputs: list[str],
    capabilities: list[str],
    message: str,
) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    argv = ["python3", "product/fail.py"] if inputs == ["product/work.txt"] else ["python3", "acceptance/fail.py"]
    if inputs == ["product/work.txt"]:
        inputs = ["product/fail.py", *inputs]
    check = {
        "id": "unauthorized-review-check",
        "tier": "cheap",
        "argv": argv,
        "cwd": ".",
        "timeout_seconds": 30,
        "inputs": inputs,
        "outputs": [],
        "authority": authority,
        "capabilities": capabilities,
        "cache": "by_input_digest",
        "mode": "standard",
    }

    with pytest.raises(VProServiceError, match=message):
        controller.submit_review(
            {
                "work_item_id": review["work_item_id"],
                "decision": "GAP",
                "contract_clause_id": "ArtifactExists",
                "gap_kind": gap_kind,
                "program_check": check,
            },
            actor="reviewer",
        )


def test_gate_approval_capture_and_admission_happy_path(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory(evidence_gate=True)
    _complete_objective(controller)

    guard = controller.next_work_item(actor="gate-runner")
    assert guard["type"] == "GATE_GUARD"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    preflight = controller.next_work_item(actor="gate-runner")
    assert preflight["type"] == "GATE_PREFLIGHT"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    required = controller.next_work_item(actor="gate-runner")
    assert required["type"] == "GATE_APPROVAL_REQUIRED"
    with pytest.raises(VProServiceError, match="another run"):
        controller.approve_gate(_approval(controller, required, run_id="wrong-run"), actor="operator")
    controller.approve_gate(_approval(controller, required), actor="operator")

    capture = controller.next_work_item(actor="gate-runner")
    assert capture["type"] == "GATE_CAPTURE"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    assert (vpro_project.state_root / "evidence/capture.json").is_file()
    admission = controller.next_work_item(actor="gate-runner")
    assert admission["type"] == "GATE_ADMISSION"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    assert controller.next_work_item(actor="operator")["type"] == "DONE"


def test_evidence_gate_runs_evaluator_guard_before_approval_or_capture(
    controller_factory,
    bundle_factory,
    vpro_project,
) -> None:
    raw = bundle_factory(evidence_gate=True)
    guard = next(check for check in raw["checks"] if check["id"] == "evaluator-guard")
    guard.update(
        {
            "argv": ["python3", "acceptance/fail.py"],
            "inputs": ["acceptance/fail.py", "evaluator/evaluator.py"],
        }
    )
    preflight = next(check for check in raw["checks"] if check["id"] == "preflight")
    preflight.update({"tier": "operator", "capabilities": ["container"]})
    controller, _, _ = controller_factory(bundle=raw)
    _complete_objective(controller)

    gate_guard = controller.next_work_item(actor="gate-runner")
    assert gate_guard["type"] == "GATE_GUARD"
    assert gate_guard["check_ids"] == ["evaluator-guard"]
    report = _evaluate(controller, actor="gate-runner")

    assert report["status"] == "FAIL"
    assert report["failed_check"]["check_id"] == "evaluator-guard"
    state = controller.store.load()
    assert state["gates"]["release-gate"]["status"] == "BLOCKED"
    assert state["gates"]["release-gate"]["approval_challenge_digest"] is None
    assert state["approvals"] == {}
    assert not (vpro_project.state_root / "evidence/capture.json").exists()


def test_evidence_gate_accepts_declared_directory_outputs(
    controller_factory,
    bundle_factory,
    vpro_project,
) -> None:
    raw = bundle_factory(evidence_gate=True)
    capture = next(check for check in raw["checks"] if check["id"] == "capture")
    capture["outputs"] = ["evidence/capture"]
    admission = next(check for check in raw["checks"] if check["id"] == "admission")
    admission["inputs"][-1] = "evidence/capture"
    admission["outputs"] = ["evidence/admission"]
    (vpro_project.root / "acceptance/capture.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['VPRO_EVIDENCE_ROOT']) / 'capture'\n"
        "root.mkdir(parents=True, exist_ok=True)\n"
        "(root / 'data.json').write_text('{\"captured\": true}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (vpro_project.root / "acceptance/admit.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "root = Path(os.environ['VPRO_EVIDENCE_ROOT'])\n"
        "if not (root / 'capture/data.json').is_file():\n"
        "    raise SystemExit(1)\n"
        "output = root / 'admission'\n"
        "output.mkdir(parents=True, exist_ok=True)\n"
        "(output / 'decision.json').write_text('{\"status\": \"PASS\"}\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    controller, _, _ = controller_factory(bundle=raw)

    _reach_capture(controller)
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    assert (vpro_project.state_root / "evidence/capture/data.json").is_file()
    assert controller.next_work_item(actor="gate-runner")["type"] == "GATE_ADMISSION"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    assert (vpro_project.state_root / "evidence/admission/decision.json").is_file()
    assert controller.next_work_item(actor="operator")["type"] == "DONE"


def test_gate_approval_requires_an_authenticated_operator_signature(controller_factory) -> None:
    controller, _, _ = controller_factory(evidence_gate=True)
    _complete_objective(controller)
    controller.next_work_item(actor="gate-runner")
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    controller.next_work_item(actor="gate-runner")
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    required = controller.next_work_item(actor="gate-runner")
    forged = _approval(controller, required)
    forged["hmac_sha256"] = "0" * 64

    with pytest.raises(VProServiceError, match="signature is invalid"):
        controller.approve_gate(forged, actor="operator")

    wrong_domain = _approval(controller, required)
    unsigned = {key: value for key, value in wrong_domain.items() if key != "hmac_sha256"}
    wrong_domain["hmac_sha256"] = controller.store.authentication_tag(unsigned)
    with pytest.raises(VProServiceError, match="signature is invalid"):
        controller.approve_gate(wrong_domain, actor="operator")

    signed_for_operator = _approval(controller, required)
    with pytest.raises(VProServiceError, match="signer does not match actor"):
        controller.approve_gate(signed_for_operator, actor="attacker")


def test_gate_approval_is_rechecked_immediately_before_execution(
    controller_factory,
    monkeypatch,
) -> None:
    controller, _, _ = controller_factory(evidence_gate=True)
    _complete_objective(controller)
    controller.next_work_item(actor="gate-runner")
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    controller.next_work_item(actor="gate-runner")
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    required = controller.next_work_item(actor="gate-runner")
    expiry = int(time.time()) + 10
    controller.approve_gate(
        _approval(controller, required, expires_at_unix=expiry),
        actor="operator",
    )
    capture = controller.next_work_item(actor="gate-runner")
    assert capture["type"] == "GATE_CAPTURE"
    monkeypatch.setattr("valkey_scale_lab.vpro.service.time.time", lambda: expiry + 1)

    with pytest.raises(VProServiceError, match="approval expired"):
        controller.evaluate_active(
            actor="gate-runner",
            work_item_id=capture["work_item_id"],
        )


def test_privileged_preflight_requires_approval_before_execution(
    controller_factory,
    bundle_factory,
) -> None:
    raw = bundle_factory(evidence_gate=True)
    preflight = next(check for check in raw["checks"] if check["id"] == "preflight")
    preflight.update({"tier": "operator", "capabilities": ["container"]})
    controller, _, _ = controller_factory(bundle=raw)
    _complete_objective(controller)

    guard = controller.next_work_item(actor="gate-runner")
    assert guard["type"] == "GATE_GUARD"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    required = controller.next_work_item(actor="gate-runner")
    assert required["type"] == "GATE_APPROVAL_REQUIRED"
    controller.approve_gate(_approval(controller, required), actor="operator")
    assert controller.next_work_item(actor="gate-runner")["type"] == "GATE_PREFLIGHT"


def test_gate_approval_is_invalidated_when_product_changes(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory(evidence_gate=True)
    _complete_objective(controller)
    controller.next_work_item(actor="gate-runner")
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    controller.next_work_item(actor="gate-runner")
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    required = controller.next_work_item(actor="gate-runner")
    controller.approve_gate(_approval(controller, required), actor="operator")
    (vpro_project.root / "product/work.txt").write_text("changed after approval\n", encoding="utf-8")

    verify = controller.next_work_item(actor="gate-runner")
    assert verify["type"] == "VERIFY"


@pytest.mark.parametrize(
    ("drift", "message"),
    [("product", "files outside the work-item authorization changed"), ("raw-evidence", "run evidence changed outside")],
)
def test_gate_check_cannot_modify_product_or_undeclared_raw_evidence(
    controller_factory,
    vpro_project,
    drift: str,
    message: str,
) -> None:
    root = "root = Path(os.environ['VPRO_EVIDENCE_ROOT'])\nroot.mkdir(parents=True, exist_ok=True)\n"
    mutation = (
        "Path('product/work.txt').write_text('gate mutation\\n', encoding='utf-8')\n"
        if drift == "product"
        else "(root / 'rogue.json').write_text('{}\\n', encoding='utf-8')\n"
    )
    (vpro_project.root / "acceptance/capture.py").write_text(
        "import os\nfrom pathlib import Path\n"
        + root
        + "(root / 'capture.json').write_text('{\"captured\": true}\\n', encoding='utf-8')\n"
        + mutation,
        encoding="utf-8",
    )
    controller, _, _ = controller_factory(evidence_gate=True)
    _reach_capture(controller)

    with pytest.raises(VProServiceError, match=message):
        _evaluate(controller, actor="gate-runner")


def test_gate_check_that_omits_declared_output_fails(controller_factory, vpro_project) -> None:
    (vpro_project.root / "acceptance/capture.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    controller, _, _ = controller_factory(evidence_gate=True)
    _reach_capture(controller)

    report = _evaluate(controller, actor="gate-runner")
    assert report["status"] == "FAIL"
    assert report["failed_check"]["returncode"] == 125
    assert "did not create every declared output" in report["failed_check"]["excerpt"]


@pytest.mark.parametrize("invalid_kind", ["nested-symlink", "root-symlink"])
def test_invalid_directory_output_fails_and_consumes_the_costly_run(
    controller_factory,
    bundle_factory,
    vpro_project,
    invalid_kind: str,
) -> None:
    raw = bundle_factory(evidence_gate=True)
    capture = next(check for check in raw["checks"] if check["id"] == "capture")
    capture["outputs"] = ["evidence/capture"]
    admission = next(check for check in raw["checks"] if check["id"] == "admission")
    admission["inputs"][-1] = "evidence/capture"
    target = "Path(os.environ['VPRO_EVIDENCE_ROOT']) / 'capture'"
    invalid_output = (
        f"root = {target}\n"
        "root.mkdir(parents=True, exist_ok=True)\n"
        "(root / 'linked').symlink_to(Path('product/work.txt').resolve())\n"
        if invalid_kind == "nested-symlink"
        else f"root = {target}\nroot.symlink_to(Path('product/work.txt').resolve())\n"
    )
    (vpro_project.root / "acceptance/capture.py").write_text(
        "import os\nfrom pathlib import Path\n" + invalid_output,
        encoding="utf-8",
    )
    controller, _, _ = controller_factory(bundle=raw)
    capture_work = _reach_capture(controller)

    report = _evaluate(controller, actor="gate-runner")

    assert report["status"] == "FAIL"
    assert report["failed_check"]["returncode"] == 125
    assert "declared outputs are invalid" in report["failed_check"]["excerpt"]
    state = controller.store.load()
    assert state["active_work_item"] is None
    assert state["gates"]["release-gate"]["status"] == "BLOCKED"
    assert sum(state["run_counts"].values()) == 1
    with pytest.raises(VProServiceError, match="active work item"):
        controller.evaluate_active(
            actor="gate-runner",
            work_item_id=capture_work["work_item_id"],
        )


def test_unreadable_directory_output_fails_and_consumes_the_costly_run(
    controller_factory,
    bundle_factory,
    vpro_project,
) -> None:
    raw = bundle_factory(evidence_gate=True)
    capture = next(check for check in raw["checks"] if check["id"] == "capture")
    capture["outputs"] = ["evidence/capture"]
    admission = next(check for check in raw["checks"] if check["id"] == "admission")
    admission["inputs"][-1] = "evidence/capture"
    (vpro_project.root / "acceptance/capture.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "root = Path(os.environ['VPRO_EVIDENCE_ROOT']) / 'capture'\n"
        "root.mkdir(parents=True, exist_ok=True)\n"
        "output = root / 'unreadable.json'\n"
        "output.write_text('{}\\n', encoding='utf-8')\n"
        "output.chmod(0)\n",
        encoding="utf-8",
    )
    controller, _, _ = controller_factory(bundle=raw)
    capture_work = _reach_capture(controller)
    output = vpro_project.state_root / "evidence/capture/unreadable.json"

    try:
        report = _evaluate(controller, actor="gate-runner")
    finally:
        if output.exists():
            output.chmod(0o600)

    assert report["status"] == "FAIL"
    assert report["failed_check"]["returncode"] == 125
    assert "declared outputs are invalid" in report["failed_check"]["excerpt"]
    state = controller.store.load()
    assert state["active_work_item"] is None
    assert state["gates"]["release-gate"]["status"] == "BLOCKED"
    assert sum(state["run_counts"].values()) == 1
    with pytest.raises(VProServiceError, match="active work item"):
        controller.evaluate_active(
            actor="gate-runner",
            work_item_id=capture_work["work_item_id"],
        )


def test_cached_gate_result_revalidates_output_and_log(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory(evidence_gate=True)
    controller.bind(actor="operator")
    bundle, _ = controller._definition()
    state = controller.store.load()
    evidence = vpro_project.state_root / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "capture.json").write_text('{"captured": true}\n', encoding="utf-8")
    runner = controller._runner(bundle, state)
    check = bundle.check("admission")
    cache = {}

    first = runner.run(check, cache)
    assert first["status"] == "PASS" and first["cached"] is False
    (evidence / "admission.json").write_text("tampered\n", encoding="utf-8")
    second = runner.run(check, cache)
    assert second["status"] == "PASS" and second["cached"] is False
    Path(second["log_path"]).write_text("tampered log\n", encoding="utf-8")
    third = runner.run(check, cache)
    assert third["status"] == "PASS" and third["cached"] is False


def test_failed_results_are_never_cached_by_tool_specific_error_text(controller_factory) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    bundle, _ = controller._definition()
    state = controller.store.load()
    check = replace(
        bundle.check("common"),
        id="generic-failure",
        argv=("python3", "acceptance/fail.py"),
        inputs=("acceptance/fail.py",),
    )
    runner = controller._runner(bundle, state)
    cache = {}

    first = runner.run(check, cache)
    second = runner.run(check, cache)

    assert first["status"] == second["status"] == "FAIL"
    assert first["cached"] is second["cached"] is False
    assert cache == {}


@pytest.mark.parametrize("target", ["product", "evidence", "log"])
def test_terminal_run_rejects_product_evidence_and_log_drift(
    controller_factory,
    vpro_project,
    target: str,
) -> None:
    controller, _, _ = controller_factory(evidence_gate=True)
    _reach_capture(controller)
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    assert controller.next_work_item(actor="gate-runner")["type"] == "GATE_ADMISSION"
    assert _evaluate(controller, actor="gate-runner")["status"] == "PASS"
    assert controller.next_work_item(actor="operator")["type"] == "DONE"
    if target == "product":
        (vpro_project.root / "product/work.txt").write_text("terminal drift\n", encoding="utf-8")
    elif target == "evidence":
        (vpro_project.state_root / "evidence/capture.json").write_text("terminal drift\n", encoding="utf-8")
    else:
        state = controller.store.load()
        log_path = Path(state["objectives"]["CreateArtifact"]["last_result"]["results"][0]["log_path"])
        log_path.write_text("terminal drift\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="terminal .* stale"):
        controller.status()


def test_failed_evaluator_repair_rejects_inter_attempt_drift(controller_factory, vpro_project) -> None:
    controller, _, _ = controller_factory()
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    gap_check = {
        "id": "persistent-evaluator-gap",
        "tier": "cheap",
        "argv": ["python3", "acceptance/fail.py"],
        "cwd": ".",
        "timeout_seconds": 30,
        "inputs": ["acceptance/fail.py", "evaluator/evaluator.py"],
        "outputs": [],
        "authority": "evaluator",
        "capabilities": [],
        "cache": "by_input_digest",
        "mode": "standard",
    }
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "contract_clause_id": "ArtifactExists",
            "gap_kind": "EVALUATOR_GAP",
            "program_check": gap_check,
        },
        actor="reviewer",
    )
    controller.next_work_item(actor="repairer")
    evaluator = vpro_project.root / "evaluator/evaluator.py"
    evaluator.write_text("EVALUATOR_VERSION = 2\n", encoding="utf-8")
    assert _accept_repair(controller, actor="repairer")["status"] == "FAIL"
    evaluator.write_text("EVALUATOR_VERSION = 3\n", encoding="utf-8")

    with pytest.raises(VProServiceError, match="evaluator changed outside controlled repair"):
        controller.status()


def test_exhausted_evaluator_repair_remains_stably_blocked(
    controller_factory,
    bundle_factory,
    vpro_project,
) -> None:
    raw = bundle_factory()
    raw["acceptance"]["max_attempts"] = 1
    controller, _, _ = controller_factory(bundle=raw)
    controller.bind(actor="operator")
    controller.next_work_item(actor="worker")
    assert _evaluate(controller, actor="worker")["status"] == "PASS"
    review = controller.next_work_item(actor="reviewer")
    gap_check = {
        "id": "budgeted-evaluator-gap",
        "tier": "cheap",
        "argv": ["python3", "acceptance/fail.py"],
        "cwd": ".",
        "timeout_seconds": 30,
        "inputs": ["acceptance/fail.py", "evaluator/evaluator.py"],
        "outputs": [],
        "authority": "evaluator",
        "capabilities": [],
        "cache": "by_input_digest",
        "mode": "standard",
    }
    controller.submit_review(
        {
            "work_item_id": review["work_item_id"],
            "decision": "GAP",
            "contract_clause_id": "ArtifactExists",
            "gap_kind": "EVALUATOR_GAP",
            "program_check": gap_check,
        },
        actor="reviewer",
    )
    controller.next_work_item(actor="repairer")
    (vpro_project.root / "evaluator/evaluator.py").write_text("EVALUATOR_VERSION = 2\n", encoding="utf-8")
    assert _accept_repair(controller, actor="repairer")["status"] == "FAIL"

    assert controller.next_work_item(actor="operator")["type"] == "BLOCKED"
    assert controller.status()["status"] == "BLOCKED"
    assert controller.doctor()["status"] == "PASS"
