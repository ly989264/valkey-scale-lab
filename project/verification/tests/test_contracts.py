from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from verification.catalog import GateError, load_catalog
from verification.milestone import load_milestone
from verification.planning import (
    build_plan,
    build_milestone_plan,
    parse_cli_parameters,
    select_milestone,
    select_test,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _command_test(test_id: str = "sample.test") -> dict[str, object]:
    return {
        "test_id": test_id,
        "description": "Sample command test.",
        "parameters": {},
        "runner": {
            "type": "command",
            "argv": [sys.executable, "-c", "raise SystemExit(0)"],
            "cwd": "{gate.project_root}",
            "timeout_seconds": 10,
            "result": "exit_code",
        },
    }


def _catalog_document() -> dict[str, object]:
    return {
        "schema_version": "verification-catalog-v2",
        "suites": [
            {
                "suite_id": "sample.suite",
                "description": "Sample suite.",
                "test_ids": ["sample.test"],
            }
        ],
        "tests": [_command_test()],
    }


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _milestone_document() -> dict[str, object]:
    return {
        "id": "m1",
        "goal": "Observe the sample behavior.",
        "criteria": [
            {
                "id": "sample.behavior",
                "statement": "The sample behavior is observable.",
                "check": [{"id": "sample.test"}],
            }
        ],
    }


def test_catalog_v2_loads_and_schema_document_is_current() -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")
    schema = json.loads(
        (PROJECT_ROOT / "verification/catalog.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["schema_version"]["const"] == "verification-catalog-v2"
    assert len(catalog.tests) == 96
    assert "real.local.full-flow" in catalog.tests
    assert "real.local.m2-cluster-formation" in catalog.tests
    assert "real.local.m2-automatic-failover" in catalog.tests
    assert "real.local.m2-stability-resource" in catalog.tests
    assert "repository.all" in catalog.suites


def test_catalog_registers_every_pytest_file_once() -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")
    expected = {
        path.relative_to(PROJECT_ROOT).as_posix()
        for root in (PROJECT_ROOT / "tests", PROJECT_ROOT / "verification/tests")
        for path in root.rglob("test_*.py")
    }
    registered: list[str] = []
    for test in catalog.tests.values():
        if test.runner.type != "pytest":
            continue
        paths = [
            argument
            for argument in test.runner.argv
            if argument.startswith("tests/") or argument.startswith("verification/tests/")
        ]
        assert len(paths) == 1, test.test_id
        registered.extend(paths)

    assert set(registered) == expected
    assert len(registered) == len(expected)
    assert set(catalog.suites["repository.all"].test_ids) == {
        test.test_id for test in catalog.tests.values() if test.runner.type == "pytest"
    }


def test_catalog_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        '{"schema_version":"verification-catalog-v2",'
        '"schema_version":"verification-catalog-v2","suites":[],"tests":[]}',
        encoding="utf-8",
    )

    with pytest.raises(GateError, match="duplicate JSON key"):
        load_catalog(path)


def test_catalog_rejects_duplicate_test_ids(tmp_path: Path) -> None:
    document = _catalog_document()
    document["tests"] = [_command_test(), _command_test()]

    with pytest.raises(GateError, match="duplicate test id"):
        load_catalog(_write(tmp_path / "catalog.json", document))


def test_catalog_rejects_duplicate_suite_ids(tmp_path: Path) -> None:
    document = _catalog_document()
    document["suites"] = document["suites"] * 2

    with pytest.raises(GateError, match="duplicate suite id"):
        load_catalog(_write(tmp_path / "catalog.json", document))


def test_catalog_rejects_test_and_suite_id_collision(tmp_path: Path) -> None:
    document = _catalog_document()
    document["suites"][0]["suite_id"] = "sample.test"

    with pytest.raises(GateError, match="globally unique"):
        load_catalog(_write(tmp_path / "catalog.json", document))


def test_catalog_rejects_unknown_suite_test(tmp_path: Path) -> None:
    document = _catalog_document()
    document["suites"][0]["test_ids"] = ["unknown.test"]

    with pytest.raises(GateError, match="unknown tests"):
        load_catalog(_write(tmp_path / "catalog.json", document))


@pytest.mark.parametrize(
    ("runner_type", "result_type"),
    [("pytest", "exit_code"), ("command", "junit")],
)
def test_catalog_rejects_invalid_runner_pairs(
    tmp_path: Path, runner_type: str, result_type: str
) -> None:
    document = _catalog_document()
    document["tests"][0]["runner"]["type"] = runner_type
    document["tests"][0]["runner"]["result"] = result_type

    with pytest.raises(GateError, match=r"pytest\+junit"):
        load_catalog(_write(tmp_path / "catalog.json", document))


def test_catalog_rejects_unknown_and_malformed_placeholders(tmp_path: Path) -> None:
    document = _catalog_document()
    document["tests"][0]["runner"]["argv"].append("{gate.unknown}")
    with pytest.raises(GateError, match="unknown placeholder"):
        load_catalog(_write(tmp_path / "unknown.json", document))

    document = _catalog_document()
    document["tests"][0]["runner"]["argv"].append("{gate.run_id")
    with pytest.raises(GateError, match="malformed template"):
        load_catalog(_write(tmp_path / "malformed.json", document))


def test_catalog_rejects_undeclared_or_unused_parameters(tmp_path: Path) -> None:
    document = _catalog_document()
    document["tests"][0]["runner"]["argv"].append("{param.nodes}")
    with pytest.raises(GateError, match="undeclared parameter"):
        load_catalog(_write(tmp_path / "undeclared.json", document))

    document = _catalog_document()
    document["tests"][0]["parameters"] = {
        "nodes": {"type": "integer", "required": True}
    }
    with pytest.raises(GateError, match="unused parameters"):
        load_catalog(_write(tmp_path / "unused.json", document))


def test_cli_parameter_parser_rejects_duplicates_and_bad_shape() -> None:
    with pytest.raises(GateError, match="duplicate parameter"):
        parse_cli_parameters(("nodes=50", "nodes=100"))
    with pytest.raises(GateError, match="NAME=VALUE"):
        parse_cli_parameters(("nodes",))


def test_real_parameter_contract_validates_bounds_and_project_paths() -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")
    tests = select_test(catalog, "real.local.full-flow")

    plan = build_plan(
        tests,
        {
            "real.local.full-flow": {
                "nodes": "50",
                "config": "templates/configs/scale_50.yaml",
            }
        },
        PROJECT_ROOT,
        selection_kind="test",
        selection_id="real.local.full-flow",
        cli_source=True,
        invocation_id="gate-contract-test",
    )
    assert plan.tests[0].cwd == PROJECT_ROOT
    assert f"PYTHONPATH={PROJECT_ROOT}/src" in plan.tests[0].argv
    assert str(PROJECT_ROOT / "templates/configs/scale_50.yaml") in plan.tests[0].argv
    assert "--operator-opt-in" not in plan.tests[0].argv

    with pytest.raises(GateError, match="must be <= 200"):
        build_plan(
            tests,
            {
                "real.local.full-flow": {
                    "nodes": "201",
                    "config": "templates/configs/scale_50.yaml",
                }
            },
            PROJECT_ROOT,
            selection_kind="test",
            selection_id="real.local.full-flow",
            cli_source=True,
        )


@pytest.mark.parametrize("path", ["../outside", "/tmp/outside"])
def test_path_parameters_reject_absolute_and_escaping_paths(path: str) -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")

    with pytest.raises(GateError, match="project root|project path"):
        build_plan(
            select_test(catalog, "real.local.full-flow"),
            {"real.local.full-flow": {"nodes": "50", "config": path}},
            PROJECT_ROOT,
            selection_kind="test",
            selection_id="real.local.full-flow",
            cli_source=True,
        )


def test_milestone_schema_and_current_definitions_are_valid() -> None:
    schema = json.loads(
        (PROJECT_ROOT / "milestones/milestone.schema.json").read_text(encoding="utf-8")
    )
    assert schema["required"] == ["id", "goal", "criteria"]
    assert schema["$defs"]["criterion"]["properties"]["check"]["minItems"] == 1

    milestones = {
        milestone_id: load_milestone(
            PROJECT_ROOT / f"milestones/{milestone_id}/milestone.json",
            expected_id=milestone_id,
        )
        for milestone_id in ("m1", "m2", "m3", "m4")
    }
    assert milestones["m1"].definition_status == "READY"
    assert milestones["m2"].definition_status == "READY"
    assert milestones["m3"].definition_status == "DEFINED"
    assert milestones["m4"].definition_status == "DEFINED"


def test_milestone_rejects_duplicate_criteria_empty_check_and_directory_mismatch(
    tmp_path: Path,
) -> None:
    document = _milestone_document()
    document["criteria"] = document["criteria"] * 2
    with pytest.raises(GateError, match="duplicate criterion"):
        load_milestone(_write(tmp_path / "duplicate.json", document))

    document = _milestone_document()
    document["criteria"][0]["check"] = []
    with pytest.raises(GateError, match="non-empty array"):
        load_milestone(_write(tmp_path / "empty.json", document))

    with pytest.raises(GateError, match="does not match directory"):
        load_milestone(
            _write(tmp_path / "mismatch.json", _milestone_document()),
            expected_id="m2",
        )


def test_milestone_rejects_unknown_check_and_parameterized_suite(
    tmp_path: Path,
) -> None:
    catalog = load_catalog(_write(tmp_path / "catalog.json", _catalog_document()))
    document = _milestone_document()
    document["criteria"][0]["check"] = [{"id": "unknown.check"}]
    milestone = load_milestone(_write(tmp_path / "unknown.json", document))
    with pytest.raises(GateError, match="unknown milestone check"):
        select_milestone(catalog, milestone)

    document = _milestone_document()
    document["criteria"][0]["check"] = [
        {"id": "sample.suite", "parameters": {}}
    ]
    milestone = load_milestone(_write(tmp_path / "suite-empty-params.json", document))
    with pytest.raises(GateError, match="cannot declare parameters"):
        select_milestone(catalog, milestone)

    document = _catalog_document()
    document["tests"][0] = _command_test()
    document["tests"][0]["parameters"] = {
        "nodes": {"type": "integer", "required": True}
    }
    document["tests"][0]["runner"]["argv"].append("{param.nodes}")
    catalog = load_catalog(_write(tmp_path / "parameterized.json", document))
    milestone_document = _milestone_document()
    milestone_document["criteria"][0]["check"] = [{"id": "sample.suite"}]
    milestone = load_milestone(_write(tmp_path / "suite.json", milestone_document))
    with pytest.raises(GateError, match="must be referenced directly"):
        select_milestone(catalog, milestone)


def test_m1_expands_every_product_test_once_and_real_check_twice() -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")
    milestone = load_milestone(
        PROJECT_ROOT / "milestones/m1/milestone.json", expected_id="m1"
    )
    plan = build_milestone_plan(
        catalog,
        milestone,
        PROJECT_ROOT,
        invocation_id="m1-contract-test",
    )

    assert plan.definition_status == "READY"
    assert len(plan.tests) == 91
    product_ids = set(catalog.suites["product.all"].test_ids)
    assert "product.unit.m2_fault_client_sampler" in product_ids
    assert "product.unit.m2_performance_capture" in product_ids
    counts = Counter(
        planned.test.test_id
        for planned in plan.tests
        if planned.test.test_id in product_ids
    )
    assert set(counts) == product_ids
    assert set(counts.values()) == {1}
    real = [
        planned
        for planned in plan.tests
        if planned.test.test_id == "real.local.full-flow"
    ]
    assert [planned.parameters["nodes"] for planned in real] == [50, 200]
    assert [
        Path(planned.parameters["config"]).relative_to(PROJECT_ROOT).as_posix()
        for planned in real
    ] == ["templates/configs/scale_50.yaml", "templates/configs/scale_200.yaml"]
    assert real[0].artifacts_dir != real[1].artifacts_dir
    assert len({planned.instance_id for planned in plan.tests}) == 91


def test_m2_m3_and_m4_attach_only_executable_checks() -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")
    m2 = load_milestone(
        PROJECT_ROOT / "milestones/m2/milestone.json", expected_id="m2"
    )
    m3 = load_milestone(
        PROJECT_ROOT / "milestones/m3/milestone.json", expected_id="m3"
    )
    m4 = load_milestone(
        PROJECT_ROOT / "milestones/m4/milestone.json", expected_id="m4"
    )

    assert select_milestone(catalog, m2)
    assert [selected.test.test_id for selected in select_milestone(catalog, m3)] == [
        "product.orchestrator.local_orchestrator"
    ]
    assert [selected.test.test_id for selected in select_milestone(catalog, m4)] == [
        "product.config.config_validation",
        "product.planner.planner",
        "product.scenarios.definition_contract",
        "product.scenarios.gate_plan_compiler",
    ]


def test_m2_check_mapping_runs_each_real_performance_matrix_once() -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")
    milestone = load_milestone(
        PROJECT_ROOT / "milestones/m2/milestone.json", expected_id="m2"
    )

    mapping = {
        criterion.id: [
            (check.id, dict(check.parameters)) for check in criterion.checks or ()
        ]
        for criterion in milestone.criteria
    }
    assert mapping == {
        "performance.measurement-contract": [("gate.m2.contracts", {})],
        "performance.cluster-formation-experiment": [
            (
                "real.local.m2-cluster-formation",
                {
                    "selected_strategy": "tree_meet_addslotsrange",
                    "selected_parallelism": "16",
                },
            )
        ],
        "performance.cluster-formation-budget": [("gate.m2.contracts", {})],
        "performance.automatic-failover-experiment": [
            (
                "real.local.m2-automatic-failover",
                {"selected_timeout_ms": "20000"},
            )
        ],
        "performance.automatic-failover-budget": [("gate.m2.contracts", {})],
        "performance.stability-and-resource-safety": [
            (
                "real.local.m2-stability-resource",
                {
                    "selected_strategy": "tree_meet_addslotsrange",
                    "selected_parallelism": "16",
                    "selected_timeout_ms": "20000",
                },
            )
        ],
        "performance.promotion-and-regression": [
            ("gate.m2.contracts", {}),
            ("product.all", {}),
            (
                "real.local.full-flow",
                {
                    "nodes": 50,
                    "config": "templates/configs/scale_50.yaml",
                },
            ),
            (
                "real.local.full-flow",
                {
                    "nodes": 200,
                    "config": "templates/configs/scale_200.yaml",
                },
            ),
        ],
    }

    plan = build_milestone_plan(
        catalog,
        milestone,
        PROJECT_ROOT,
        invocation_id="m2-contract-test",
    )
    assert plan.definition_status == "READY"
    real_m2_ids = [
        planned.test.test_id
        for planned in plan.tests
        if planned.test.test_id.startswith("real.local.m2-")
    ]
    assert real_m2_ids == [
        "real.local.m2-cluster-formation",
        "real.local.m2-automatic-failover",
        "real.local.m2-stability-resource",
    ]
    assert len({planned.instance_id for planned in plan.tests}) == len(plan.tests)


def test_m2_real_tests_are_current_invocation_json_runners_not_repository_tests() -> None:
    catalog = load_catalog(PROJECT_ROOT / "catalog.json")
    repository_ids = set(catalog.suites["repository.all"].test_ids)
    expected = {
        "real.local.m2-cluster-formation": (
            86400,
            {"selected_strategy", "selected_parallelism"},
        ),
        "real.local.m2-automatic-failover": (172800, {"selected_timeout_ms"}),
        "real.local.m2-stability-resource": (
            14400,
            {"selected_strategy", "selected_parallelism", "selected_timeout_ms"},
        ),
    }

    for test_id, (timeout, parameters) in expected.items():
        test = catalog.tests[test_id]
        assert test_id not in repository_ids
        assert test.runner.type == "command"
        assert test.runner.result == "json"
        assert test.runner.timeout_seconds == timeout
        assert set(test.parameters) == parameters
        assert "scripts/m2_performance_gate.py" in test.runner.argv
        assert "{gate.run_id}" in test.runner.argv
        assert "{gate.artifacts_dir}" in test.runner.argv
        assert "{gate.result_path}" in test.runner.argv

    assert "gate.m2.contracts" in repository_ids
