from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from valkey_scale_lab.vpro.contracts import ContractError, SCHEMA_VERSION, parse_bundle
from valkey_scale_lab.vpro.integrity import verify_framework_release
from valkey_scale_lab.vpro.milestone import (
    load_milestone_template,
    missing_required_fields,
    validate_milestone,
)
from valkey_scale_lab.vpro.service import VProServiceError


def test_two_unrelated_synthetic_bundles_use_the_same_fixed_parser(vpro_project, bundle_factory) -> None:
    delivery = bundle_factory()
    rotation = copy.deepcopy(delivery)
    rotation["milestone"].update(
        {
            "id": "RotateCredentials",
            "title": "Rotate local credentials",
            "goal": "Replace an expired credential and independently validate the result.",
        }
    )
    rotation["clauses"][0]["text"] = "The replacement credential is current and independently accepted."
    rotation["objectives"][0]["title"] = "Rotate the credential"

    first = parse_bundle(delivery, project_root=vpro_project.root)
    second = parse_bundle(rotation, project_root=vpro_project.root)

    assert first.schema_version == second.schema_version == SCHEMA_VERSION
    assert (first.milestone.id, second.milestone.id) == ("SyntheticDelivery", "RotateCredentials")
    assert first.milestone.goal != second.milestone.goal


def test_generic_parser_accepts_a_distinct_graph_tier_tool_and_program_gate(
    vpro_project,
    bundle_factory,
) -> None:
    raw = bundle_factory()
    raw["milestone"].update(
        {"id": "CredentialRotation", "title": "Rotate credentials", "goal": "Rotate and release two artifacts."}
    )
    raw["clauses"].append({"id": "RotationReleased", "text": "The rotated artifact passes the release gate."})
    raw["tiers"].append({"id": "normal", "rank": 1, "cost": "normal", "reviewer_admissible": True})
    raw["integrity"]["allowed_tools"].append("python")
    raw["checks"].extend(
        [
            {
                **copy.deepcopy(raw["checks"][1]),
                "id": "rotation-check",
                "tier": "normal",
                "argv": ["python", "acceptance/pass.py"],
                "inputs": ["acceptance/pass.py", "product/rotated.txt"],
            },
            {
                **copy.deepcopy(raw["checks"][0]),
                "id": "release-check",
                "tier": "normal",
                "argv": ["python", "acceptance/pass.py"],
            },
        ]
    )
    raw["objectives"].append(
        {
            "id": "RotateArtifact",
            "title": "Rotate the second artifact",
            "depends_on": ["CreateArtifact"],
            "clause_ids": ["RotationReleased"],
            "check_ids": ["rotation-check"],
            "context_paths": ["product"],
            "worker_write_paths": ["product/rotated.txt"],
            "required_for_milestone": True,
        }
    )
    raw["gates"] = [
        {
            "id": "release-program-gate",
            "kind": "program",
            "after_objective_ids": ["CreateArtifact", "RotateArtifact"],
            "check_ids": ["release-check"],
            "operator_approval_required": False,
            "required_for_milestone": True,
        }
    ]
    raw["profiles"][0].update(
        {"objective_ids": ["RotateArtifact"], "gate_ids": ["release-program-gate"]}
    )

    parsed = parse_bundle(raw, project_root=vpro_project.root)
    resolved = parsed.resolve_profile("complete")

    assert resolved.objective_ids == ("CreateArtifact", "RotateArtifact")
    assert resolved.gate_ids == ("release-program-gate",)
    assert parsed.check("rotation-check").argv[0] == "python"


def test_schema_objects_are_strict_and_use_the_parser_version() -> None:
    project = Path(__file__).resolve().parents[2]
    schema = json.loads((project / "schemas/vpro/milestone_bundle.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert schema["$id"] == "urn:vpro:schema:milestone-bundle:v1"
    assert schema["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    for name in ("milestone", "clause", "tier", "check", "objective", "profile", "gate", "acceptance", "integrity"):
        assert schema["$defs"][name]["additionalProperties"] is False
    gate = schema["$defs"]["gate"]
    assert gate["properties"]["preflight_check_ids"]["allOf"][1]["minItems"] == 1
    assert gate["allOf"][0]["then"]["not"]["anyOf"]
    assert gate["allOf"][1]["then"]["not"] == {"required": ["check_ids"]}
    manifest = json.loads((project / "codex/vpro/framework_manifest.json").read_text(encoding="utf-8"))
    assert {"AGENTS.md", "codex/vpro/framework_release.json"}.issubset(manifest["protected_paths"])


def test_repository_framework_manifest_matches_distribution_receipt() -> None:
    project = Path(__file__).resolve().parents[2]
    release = verify_framework_release(
        project,
        project / "codex/vpro/framework_manifest.json",
        project / "codex/vpro/framework_release.json",
    )

    assert release.version == "1.0.0"


def test_manifest_closure_runs_from_an_external_framework_against_an_unrelated_product(
    tmp_path: Path,
    vpro_project,
    bundle_factory,
) -> None:
    source = Path(__file__).resolve().parents[2]
    manifest = json.loads((source / "codex/vpro/framework_manifest.json").read_text(encoding="utf-8"))
    framework = tmp_path / "operator/framework/vpro"
    for item in manifest["files"]:
        relative = Path(item["path"])
        target = framework / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    for relative in (
        Path("codex/vpro/framework_manifest.json"),
        Path("codex/vpro/framework_release.json"),
    ):
        target = framework / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    trust = tmp_path / "operator/trust"
    trust.mkdir(parents=True)
    anchor = trust / "vpro-anchor.json"
    shutil.copy2(source / "codex/vpro/framework_release.json", anchor)
    raw = bundle_factory()
    raw["milestone"].update(
        {
            "id": "StaticSitePublication",
            "title": "Publish a static site",
            "goal": "Build and independently validate a static publication artifact.",
        }
    )
    raw["clauses"][0]["text"] = "The publication artifact passes its independent acceptance check."
    raw["objectives"][0]["title"] = "Build the publication artifact"
    bundle_path = trust / "static-site.bundle.json"
    bundle_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["VPRO_FRAMEWORK_ANCHOR"] = str(anchor)
    invocation = tmp_path / "invocation"
    invocation.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(framework / "VPRO_LAUNCH.py"),
            "--project-root",
            str(vpro_project.root),
            "--bundle",
            str(bundle_path),
            "--profile",
            "complete",
            "milestone-validate",
        ],
        cwd=invocation,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["milestone_id"] == "StaticSitePublication"
    assert report["profile_id"] == "complete"
    assert not (framework / "milestones").exists()
    assert not (framework / "checks").exists()
    assert not (framework / "evaluators").exists()


def test_real_launcher_completes_an_authenticated_synthetic_milestone(
    tmp_path: Path,
    vpro_project,
    bundle_factory,
) -> None:
    framework = Path(__file__).resolve().parents[2]
    operator = tmp_path / "e2e-operator"
    keys = operator / "keys"
    keys.mkdir(parents=True)
    state_key = keys / "state.key"
    approval_key = keys / "approval.key"
    state_key.write_bytes(b"s" * 32 + b"-state")
    approval_key.write_bytes(b"a" * 32 + b"-approval")
    state_key.chmod(0o600)
    approval_key.chmod(0o600)
    bundle_path = operator / "bundles/synthetic.bundle.json"
    bundle_path.parent.mkdir()
    bundle_path.write_text(
        json.dumps(bundle_factory(evidence_gate=True), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run_root = operator / "runs/run-1"
    invocation = tmp_path / "e2e-invocation"
    invocation.mkdir()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "VPRO_FRAMEWORK_ANCHOR": str(framework / "codex/vpro/framework_release.json"),
            "VPRO_STATE_HMAC_KEY_FILE": str(state_key),
            "VPRO_APPROVAL_HMAC_KEY_FILE": str(approval_key),
        }
    )
    common = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(framework / "VPRO_LAUNCH.py"),
        "--project-root",
        str(vpro_project.root),
        "--workspace-root",
        str(vpro_project.workspace),
        "--bundle",
        str(bundle_path),
        "--profile",
        "complete",
        "--run-root",
        str(run_root),
    ]

    def invoke(*arguments: str) -> dict:
        completed = subprocess.run(
            [*common, *arguments],
            cwd=invocation,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0 and "sandbox_apply: Operation not permitted" in (
            completed.stdout + completed.stderr
        ):
            pytest.skip("nested macOS sandbox is unavailable in this test environment")
        assert completed.returncode == 0, completed.stdout + completed.stderr
        return json.loads(completed.stdout)

    assert invoke("--actor", "operator", "bind")["status"] == "ACTIVE"
    work = invoke("--actor", "worker", "next")
    assert work["type"] == "WORK"
    assert invoke("--actor", "worker", "evaluate", "--work-item-id", work["work_item_id"])["status"] == "PASS"
    review = invoke("--actor", "reviewer", "next")
    assert review["type"] == "REVIEW_ACCEPTANCE"
    report_path = operator / "reviews/no-gap.json"
    report_path.parent.mkdir()
    report_path.write_text(
        json.dumps({"work_item_id": review["work_item_id"], "decision": "NO_GAP"}) + "\n",
        encoding="utf-8",
    )
    assert invoke("--actor", "reviewer", "review", "--report", str(report_path))["status"] == "ACTIVE"

    guard = invoke("--actor", "gate-runner", "next")
    assert guard["type"] == "GATE_GUARD"
    assert invoke(
        "--actor", "gate-runner", "evaluate", "--work-item-id", guard["work_item_id"]
    )["status"] == "PASS"
    preflight = invoke("--actor", "gate-runner", "next")
    assert preflight["type"] == "GATE_PREFLIGHT"
    assert invoke(
        "--actor", "gate-runner", "evaluate", "--work-item-id", preflight["work_item_id"]
    )["status"] == "PASS"
    approval_required = invoke("--actor", "gate-runner", "next")
    assert approval_required["type"] == "GATE_APPROVAL_REQUIRED"
    unsigned_approval = {
        "schema_version": "vpro-gate-approval-v2",
        "run_id": approval_required["run_id"],
        "gate_id": approval_required["gate_id"],
        "bundle_digest": approval_required["bundle_digest"],
        "product_digest": approval_required["product_digest"],
        "approval_challenge_digest": approval_required["approval_challenge_digest"],
        "cost_acknowledged": True,
        "expires_at_unix": int(time.time()) + 60,
        "nonce": "real-launcher-e2e-approval-1",
        "operator_id": "operator",
    }
    approval_payload = json.dumps(
        unsigned_approval,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    approval = {
        **unsigned_approval,
        "hmac_sha256": hmac.new(
            approval_key.read_bytes(),
            b"vpro-gate-approval-v2\0" + approval_payload,
            hashlib.sha256,
        ).hexdigest(),
    }
    approval_path = operator / "approvals/release-gate.json"
    approval_path.parent.mkdir()
    approval_path.write_text(json.dumps(approval) + "\n", encoding="utf-8")
    assert invoke(
        "--actor", "operator", "approve-gate", "--approval", str(approval_path)
    )["status"] == "ACTIVE"

    capture = invoke("--actor", "gate-runner", "next")
    assert capture["type"] == "GATE_CAPTURE"
    assert invoke(
        "--actor", "gate-runner", "evaluate", "--work-item-id", capture["work_item_id"]
    )["status"] == "PASS"
    admission = invoke("--actor", "gate-runner", "next")
    assert admission["type"] == "GATE_ADMISSION"
    assert invoke(
        "--actor", "gate-runner", "evaluate", "--work-item-id", admission["work_item_id"]
    )["status"] == "PASS"
    done = invoke("--actor", "operator", "next")
    assert done["type"] == "DONE"
    assert done["claim"] == "MILESTONE_COMPLETE"
    assert invoke("verify-completion")["status"] == "PASS"


def test_milestone_template_is_structurally_complete_and_semantically_usable(
    vpro_project,
) -> None:
    project = Path(__file__).resolve().parents[2]
    raw = load_milestone_template(project)
    schema = json.loads(
        (project / "schemas/vpro/milestone_bundle.schema.json").read_text(encoding="utf-8")
    )
    checks = vpro_project.root / "checks"
    checks.mkdir()
    (checks / "authoritative_check.py").write_text("raise SystemExit(0)\n", encoding="utf-8")

    assert missing_required_fields(raw, schema) == []
    with pytest.raises(ContractError, match="strict ASCII identifier"):
        parse_bundle(raw, project_root=vpro_project.root)

    raw["milestone"].update(
        {"id": "ExampleMilestone", "title": "Example milestone", "goal": "Deliver the example."}
    )
    raw["clauses"][0].update(
        {"id": "Requirement", "text": "The example passes its authoritative checks."}
    )
    raw["objectives"][0].update(
        {
            "id": "ImplementRequirement",
            "title": "Implement the requirement",
            "clause_ids": ["Requirement"],
        }
    )
    raw["profiles"][0]["objective_ids"] = ["ImplementRequirement"]
    assert parse_bundle(raw, project_root=vpro_project.root).milestone.id == "ExampleMilestone"


def test_milestone_validation_reports_all_missing_template_fields(
    vpro_project,
    bundle_factory,
) -> None:
    project = Path(__file__).resolve().parents[2]
    raw = bundle_factory(evidence_gate=True)
    del raw["integrity"]
    del raw["milestone"]["goal"]
    del raw["milestone"]["title"]
    del raw["objectives"][0]["worker_write_paths"]
    del raw["gates"][0]["capture_check_id"]
    path = vpro_project.operator / "bundles" / "incomplete.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(raw), encoding="utf-8")

    report = validate_milestone(
        path,
        project_root=vpro_project.root,
        schema_path=project / "schemas/vpro/milestone_bundle.schema.json",
    )

    assert report["status"] == "FAIL"
    assert report["missing_fields"] == [
        "$.gates[0].capture_check_id",
        "$.integrity",
        "$.milestone.goal",
        "$.milestone.title",
        "$.objectives[0].worker_write_paths",
    ]
    assert report["errors"]
    assert report["template_command"] == "vpro milestone-template"


def test_missing_field_diagnostics_do_not_invent_a_gate_kind(
    vpro_project,
    bundle_factory,
) -> None:
    project = Path(__file__).resolve().parents[2]
    raw = bundle_factory(evidence_gate=True)
    del raw["gates"][0]["kind"]
    schema = json.loads(
        (project / "schemas/vpro/milestone_bundle.schema.json").read_text(encoding="utf-8")
    )

    assert missing_required_fields(raw, schema) == ["$.gates[0].kind"]


def test_milestone_validation_distinguishes_config_from_execution_readiness(
    vpro_project,
    bundle_factory,
) -> None:
    project = Path(__file__).resolve().parents[2]
    raw = bundle_factory()
    raw["integrity"]["allowed_tools"].append("definitely-missing-vpro-tool")
    raw["integrity"]["evaluator_paths"] = ["evaluator/missing.py"]
    raw["checks"][3]["inputs"] = ["acceptance/pass.py", "evaluator/missing.py"]
    path = vpro_project.operator / "bundles" / "not-ready.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(raw), encoding="utf-8")

    report = validate_milestone(
        path,
        project_root=vpro_project.root,
        schema_path=project / "schemas/vpro/milestone_bundle.schema.json",
    )

    assert report["status"] == "PASS"
    assert report["execution_readiness"] == {
        "status": "BLOCKED",
        "scope": "STATIC_AUTHORITY_PATHS_AND_DECLARED_TOOLS",
        "missing_authority_paths": ["evaluator/missing.py"],
        "missing_tools": ["definitely-missing-vpro-tool"],
        "dynamic_preflight_required": False,
    }


def test_bind_revalidates_the_selected_milestone_bundle(
    controller_factory,
    bundle_factory,
) -> None:
    raw = bundle_factory()
    del raw["milestone"]["goal"]
    controller, _, _ = controller_factory(bundle=raw)

    with pytest.raises(ContractError, match="bundle.milestone is missing keys"):
        controller.bind(actor="operator")


def test_bind_and_doctor_reject_missing_authoritative_assets(
    controller_factory,
    bundle_factory,
) -> None:
    raw = bundle_factory()
    raw["integrity"]["evaluator_paths"] = ["evaluator/missing.py"]
    raw["checks"][3]["inputs"] = ["acceptance/pass.py", "evaluator/missing.py"]
    controller, _, _ = controller_factory(bundle=raw)

    doctor = controller.doctor()
    assert doctor["status"] == "BLOCKED"
    assert doctor["execution_readiness"]["missing_authority_paths"] == [
        "evaluator/missing.py"
    ]
    with pytest.raises(VProServiceError, match="execution readiness is BLOCKED"):
        controller.bind(actor="operator")


def test_controller_rejects_an_unknown_milestone_profile(controller_factory) -> None:
    controller, _, _ = controller_factory()
    controller.profile_id = "unknown-profile"

    with pytest.raises(VProServiceError, match="unknown milestone profile: unknown-profile"):
        controller.bind(actor="operator")


def test_evidence_gate_requires_a_nonempty_preflight(vpro_project, bundle_factory) -> None:
    raw = bundle_factory(evidence_gate=True)
    raw["gates"][0]["preflight_check_ids"] = []

    with pytest.raises(ContractError, match="preflight_check_ids must be a non-empty list"):
        parse_bundle(raw, project_root=vpro_project.root)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"capabilities": ["container"]}, "must be unprivileged"),
        ({"tier": "operator"}, "must be unprivileged"),
        (
            {"mode": "capture", "outputs": ["evidence/guard.json"], "cache": "never"},
            "read-only standard",
        ),
    ],
)
def test_evaluator_guard_must_be_safe_before_operator_approval(
    vpro_project,
    bundle_factory,
    change: dict,
    message: str,
) -> None:
    raw = bundle_factory(evidence_gate=True)
    guard = next(check for check in raw["checks"] if check["id"] == "evaluator-guard")
    guard.update(change)

    with pytest.raises(ContractError, match=message):
        parse_bundle(raw, project_root=vpro_project.root)


def test_check_inputs_and_outputs_must_be_disjoint(vpro_project, bundle_factory) -> None:
    raw = bundle_factory(evidence_gate=True)
    capture = next(check for check in raw["checks"] if check["id"] == "capture")
    capture["inputs"].append("evidence/capture.json")

    with pytest.raises(ContractError, match="inputs and outputs overlap"):
        parse_bundle(raw, project_root=vpro_project.root)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update({"surprise": True}), "unknown keys"),
        (lambda raw: raw["milestone"].update({"id": "../bad"}), "strict ASCII identifier"),
        (lambda raw: raw["integrity"].update({"product_roots": ["../outside"]}), "escapes project root"),
        (lambda raw: raw["objectives"][0].update({"depends_on": ["CreateArtifact"]}), "cycle"),
        (
            lambda raw: raw["integrity"].update({"authoritative_check_paths": ["evaluator"]}),
            "authority write overlap",
        ),
        (
            lambda raw: (
                raw["integrity"].update({"allowed_tools": ["python3", "sh"]}),
                raw["checks"][0].update({"argv": ["sh", "-c", "exit 0"]}),
            ),
            "not an allowed direct executable",
        ),
        (lambda raw: raw["checks"][0].update({"argv": ["python3", "-c", "raise SystemExit(0)"]}), "inline Python"),
    ],
)
def test_contract_rejects_untrusted_bundle_shapes(vpro_project, bundle_factory, mutate, message: str) -> None:
    raw = bundle_factory()
    mutate(raw)
    with pytest.raises(ContractError, match=message):
        parse_bundle(raw, project_root=vpro_project.root)


def test_contract_rejects_symlink_paths(vpro_project, bundle_factory) -> None:
    alias = vpro_project.root / "product-alias"
    alias.symlink_to(vpro_project.root / "product", target_is_directory=True)
    raw = bundle_factory()
    raw["integrity"]["product_roots"] = ["product-alias"]
    raw["objectives"][0]["context_paths"] = ["product-alias"]
    raw["objectives"][0]["worker_write_paths"] = ["product-alias/work.txt"]

    with pytest.raises(ContractError, match="traverses symlink"):
        parse_bundle(raw, project_root=vpro_project.root)


def test_check_inputs_must_be_inside_a_declared_integrity_zone(vpro_project, bundle_factory) -> None:
    raw = bundle_factory()
    raw["checks"][0]["inputs"] = ["acceptance/pass.py", "undeclared/input.txt"]

    with pytest.raises(ContractError, match="inputs are outside declared integrity zones"):
        parse_bundle(raw, project_root=vpro_project.root)


def test_module_execution_without_an_authoritative_argv_target_is_rejected(vpro_project, bundle_factory) -> None:
    raw = bundle_factory()
    raw["checks"][0]["argv"] = ["python3", "-m", "pytest"]

    with pytest.raises(ContractError, match="authoritative.*argv|argv.*authoritative"):
        parse_bundle(raw, project_root=vpro_project.root)


def test_python_option_cannot_hide_a_later_authoritative_oracle_path(vpro_project, bundle_factory) -> None:
    raw = bundle_factory()
    raw["checks"][0]["argv"] = ["python3", "--version", "acceptance/fail.py"]
    raw["checks"][0]["inputs"] = ["acceptance/pass.py", "acceptance/fail.py"]

    with pytest.raises(ContractError, match=r"argv\[1\].*authoritative.*adapter|authoritative.*adapter"):
        parse_bundle(raw, project_root=vpro_project.root)


def test_argv_authority_is_resolved_from_the_declared_cwd(vpro_project, bundle_factory) -> None:
    worker_adapter = vpro_project.root / "product/acceptance"
    worker_adapter.mkdir()
    (worker_adapter / "pass.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    raw = bundle_factory()
    raw["checks"][0].update(
        {
            "cwd": "product",
            "argv": ["python3", "acceptance/pass.py"],
            "inputs": ["acceptance/pass.py", "product/acceptance/pass.py"],
        }
    )

    with pytest.raises(ContractError, match=r"argv\[1\].*authoritative"):
        parse_bundle(raw, project_root=vpro_project.root)


def test_partial_profile_cannot_claim_milestone_complete(vpro_project, bundle_factory) -> None:
    raw = bundle_factory()
    raw["clauses"].append({"id": "SecondClause", "text": "The second required outcome is accepted."})
    second_check = copy.deepcopy(raw["checks"][1])
    second_check["id"] = "second-objective-check"
    second_check["inputs"] = ["acceptance/pass.py", "product/second.txt"]
    raw["checks"].append(second_check)
    raw["objectives"].append(
        {
            "id": "SecondObjective",
            "title": "Complete another required outcome",
            "depends_on": ["CreateArtifact"],
            "clause_ids": ["SecondClause"],
            "check_ids": ["second-objective-check"],
            "context_paths": ["product"],
            "worker_write_paths": ["product/second.txt"],
            "required_for_milestone": True,
        }
    )

    with pytest.raises(ContractError, match="claims MILESTONE_COMPLETE without required objectives"):
        parse_bundle(raw, project_root=vpro_project.root)
