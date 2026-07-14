from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = INTEGRATION_ROOT.parents[2]
PROJECT_ROOT = REPOSITORY_ROOT / "project"


def _module(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


COMPILER = _module("tested_valkey_compiler", INTEGRATION_ROOT / "compile_contract.py")
MILESTONE_EVALUATOR = _module(
    "tested_valkey_milestone_evaluator",
    INTEGRATION_ROOT / "evaluators/milestone_evaluator.py",
)
PRODUCER = _module(
    "tested_contract_verification_producer",
    INTEGRATION_ROOT / "tools/run_verification.py",
)
PREREQUISITE = _module(
    "tested_prerequisite_contract",
    INTEGRATION_ROOT / "evaluators/_prerequisite.py",
)
PREREQUISITE_SEALER = _module(
    "tested_prerequisite_sealer",
    INTEGRATION_ROOT / "tools/seal_prerequisite.py",
)


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def test_compiler_maps_project_conditions_and_evidence_one_to_one() -> None:
    draft = COMPILER.compile_contract("m1")
    source = json.loads((PROJECT_ROOT / "milestones/m1/milestone.json").read_text())
    assert [row["id"] for row in draft["success_conditions"]] == [
        row["id"] for row in source["success_conditions"]
    ]
    evidence_ids = {row["id"] for row in draft["evidence_requirements"]}
    assert {
        f"evidence.{row['id']}"
        for row in source["real_evidence_requirements"]
    } <= evidence_ids
    assert {
        f"verification.{suite_id}"
        for condition in source["success_conditions"]
        for suite_id in condition["suite_ids"]
    } <= evidence_ids
    assert {"objectives", "depends_on", "profiles", "gates", "order"}.isdisjoint(
        _walk_keys(draft)
    )
    assert draft["safety"]["capability_policies"]
    assert "product/milestones" in draft["safety"]["immutable_roots"]
    assert "product/milestones/m1/milestone.json" in draft["evaluators"][0]["inputs"]
    assert "authority/verification_receipts.json" not in json.dumps(draft)
    assert "authority/tools/run_verification.py" in json.dumps(draft)


def test_compiled_draft_is_accepted_by_the_controller_contract_parser(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT / "controller/src"))
    from controller.contracts import parse_contract

    source = json.loads(
        (PROJECT_ROOT / "milestones/m1/milestone.json").read_text()
    )
    contract = parse_contract(COMPILER.compile_contract("m1"), project_root=REPOSITORY_ROOT)
    assert contract.milestone.id == "ValkeyScaleLab.m1"
    assert len(contract.success_conditions) == len(source["success_conditions"])
    expected_evidence = {
        f"verification.{suite_id}"
        for condition in source["success_conditions"]
        for suite_id in condition["suite_ids"]
    } | {
        f"evidence.{requirement['id']}"
        for requirement in source["real_evidence_requirements"]
    }
    assert {item.id for item in contract.evidence_requirements} == expected_evidence


def test_planned_milestones_compile_without_pretending_suites_are_ready() -> None:
    for milestone_id in ("m2", "m3"):
        draft = COMPILER.compile_contract(milestone_id)
        milestone_input = f"product/milestones/{milestone_id}/milestone.json"
        assert milestone_input in draft["evaluators"][0]["inputs"]
        assert draft["milestone"]["id"] == f"ValkeyScaleLab.{milestone_id}"
        prerequisite = "m1" if milestone_id == "m2" else "m2"
        assert (
            f"authority/prerequisites/{prerequisite}/completion.json"
            in draft["evaluators"][0]["inputs"]
        )


def test_milestone_evaluator_only_checks_sealed_structure_and_prerequisites() -> None:
    milestone_path = PROJECT_ROOT / "milestones/m1/milestone.json"
    catalog_path = PROJECT_ROOT / "verification/catalog.json"
    results = MILESTONE_EVALUATOR.evaluate(
        milestone_path=milestone_path,
        catalog_path=catalog_path,
        prerequisite_paths=[],
    )
    assert {row["status"] for row in results} == {"PASS"}


def test_product_digest_matches_the_controller_product_root_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT / "controller/src"))
    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "src"))
    from valkey_scale_lab.gates.real import product_tree_digest
    from controller.integrity import canonical_digest, tree_manifest

    staged_product = tmp_path / "product"
    shutil.copytree(
        PROJECT_ROOT,
        staged_product,
        ignore=shutil.ignore_patterns(
            ".pytest_cache",
            "__pycache__",
            "*.pyc",
            "*.pyo",
            "artifacts",
            "audit",
            "runs",
        ),
    )
    expected = canonical_digest(
        {"product": {"kind": "directory", "manifest": tree_manifest(staged_product)}}
    )
    assert product_tree_digest(staged_product) == expected


def test_compiled_dynamic_receipt_path_runs_through_the_controller_evaluator_runner(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    product = workspace / "product"
    authority = workspace / "authority"
    milestone = {
        "schema_version": "valkey-milestone-v2",
        "milestone": {
            "id": "m1",
            "version": "2.0.0",
            "title": "sample",
            "final_goal": "sample",
        },
        "prerequisite_milestone_ids": [],
        "success_conditions": [
            {
                "id": "sample.condition",
                "statement": "sample passes",
                "suite_ids": ["sample.contract"],
                "evidence_requirement_ids": [],
                "required": True,
            }
        ],
        "real_evidence_requirements": [],
    }
    catalog = {
        "schema_version": "verification-catalog-v1",
        "suites": [
            {
                "id": "sample.contract",
                "title": "sample",
                "kind": "command",
                "status": "READY",
                "argv": ["python3", "-c", "print('verified')"],
                "timeout_seconds": 60,
                "capabilities": [],
                "outputs": [],
                "skip_policy": "FAIL",
            }
        ],
    }

    def write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    write(product / "milestones/m1/milestone.json", milestone)
    write(product / "verification/catalog.json", catalog)
    shutil.copy2(PROJECT_ROOT / "verification/run.py", product / "verification/run.py")
    shutil.copy2(
        PROJECT_ROOT / "verification/suite-result.schema.json",
        product / "verification/suite-result.schema.json",
    )
    for name in (
        "milestone_evaluator.py",
        "verification_admission.py",
        "_common.py",
        "_schema.py",
        "_prerequisite.py",
    ):
        target = authority / "evaluators" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(INTEGRATION_ROOT / "evaluators" / name, target)
    for name in (
        "evaluator_result.schema.json",
        "verification_receipts.schema.json",
        "verification_policy.schema.json",
        "prerequisite_completion.schema.json",
    ):
        target = authority / "schemas" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(INTEGRATION_ROOT / "schemas" / name, target)
    producer_path = authority / "tools/run_verification.py"
    producer_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(INTEGRATION_ROOT / "tools/run_verification.py", producer_path)
    policy_path = authority / "verification_policy.json"
    write(policy_path, PRODUCER.fingerprint(Path(sys.executable)))
    draft = COMPILER.compile_contract("m1", project_root=product)

    monkeypatch.syspath_prepend(str(REPOSITORY_ROOT / "controller/src"))
    from controller.contracts import parse_contract
    from controller.runner import EvaluatorRunner

    # Kernel sandbox profiles have dedicated CONTROLLER tests. This integration test
    # exercises the real evaluator protocol in environments that prohibit a
    # nested sandbox-exec invocation.
    monkeypatch.setattr(
        EvaluatorRunner,
        "_sandboxed_command",
        lambda self, command, *, cwd, **_kwargs: (command, cwd),
    )

    contract = parse_contract(draft, project_root=workspace)
    product_digest = PRODUCER.product_tree_digest(product)
    run_root = tmp_path / "controller-run"
    evidence_root = run_root / "evidence"
    envelope = PRODUCER.produce(
        python=Path(sys.executable),
        workspace_root=workspace,
        product_relative="product",
        milestone_id="m1",
        run_id="controller-run-1",
        expected_product_digest=product_digest,
        evidence_root=evidence_root,
        policy_path=policy_path,
        allowed_capabilities=[],
    )
    assert envelope["receipts"][0]["status"] == "PASS"
    seals = EvaluatorRunner.seal_tools(
        contract.safety.allowed_tools,
        workspace_root=workspace,
        run_root=run_root,
    )
    runner = EvaluatorRunner(
        project_root=workspace,
        workspace_root=workspace,
        run_root=run_root,
        contract=contract,
        tool_seals=seals,
    )
    milestone_run = runner.run(
        contract.evaluator("ValkeyMilestoneEvaluator"),
        run_id="controller-run-1",
        product_digest=product_digest,
        evaluation_id="evaluation-1",
    )
    verification_run = runner.run(
        contract.evaluator("ValkeyVerificationAdmissionEvaluator"),
        run_id="controller-run-1",
        product_digest=product_digest,
        evaluation_id="evaluation-2",
    )
    assert milestone_run.report["condition_results"][0]["status"] == "PASS"
    assert verification_run.report["evidence_results"][0]["status"] == "PASS"


def test_operator_seals_a_prior_terminal_and_final_admission(tmp_path: Path) -> None:
    milestone = json.loads(
        (PROJECT_ROOT / "milestones/m1/milestone.json").read_text()
    )
    milestone["real_evidence_requirements"].reverse()
    milestone_path = tmp_path / "milestone.json"
    milestone_path.write_text(json.dumps(milestone), encoding="utf-8")
    terminal = {
        "schema_version": "controller-terminal-receipt-v1",
        "status": "SUCCESS",
        "milestone_id": "ValkeyScaleLab.m1",
        "run_id": "prior-run",
        "product_digest": "a" * 64,
        "created_at_unix": 2_000_000_000,
        "receipt_tag": "b" * 64,
    }
    terminal_path = tmp_path / "prior-terminal.json"
    terminal_path.write_text(json.dumps(terminal), encoding="utf-8")
    admission = {
        "status": "PASS",
        "requested_nodes": 200,
        "observed_nodes": 200,
        "product_digest": terminal["product_digest"],
        "invocation_run_id": terminal["run_id"],
    }
    admission["admission_digest"] = PREREQUISITE_SEALER.canonical_digest(admission)
    admission_path = tmp_path / "admission.json"
    admission_path.write_text(json.dumps(admission), encoding="utf-8")
    output = tmp_path / "authority/prerequisites/m1"
    completion = PREREQUISITE_SEALER.seal(
        milestone_path=milestone_path,
        terminal_path=terminal_path,
        final_admission_path=admission_path,
        output_dir=output,
        terminal_verified=True,
    )
    loaded = PREREQUISITE.load_completion(output / "completion.json", "m1")
    assert loaded == completion
    assert loaded["final_evidence_requirement_id"] == "local.exact.200"
    assert loaded["final_admission_digest"] == admission["admission_digest"]
