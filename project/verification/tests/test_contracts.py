from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from verification.catalog import GateError, load_catalog
from verification.planning import (
    build_plan,
    parse_cli_parameters,
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


def test_catalog_v2_loads_and_schema_document_is_current() -> None:
    catalog = load_catalog(PROJECT_ROOT / "verification/catalog.json")
    schema = json.loads(
        (PROJECT_ROOT / "verification/catalog.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["schema_version"]["const"] == "verification-catalog-v2"
    assert len(catalog.tests) == 88
    assert "real.local.full-flow" in catalog.tests
    assert "repository.all" in catalog.suites


def test_catalog_registers_every_pytest_file_once() -> None:
    catalog = load_catalog(PROJECT_ROOT / "verification/catalog.json")
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
    catalog = load_catalog(PROJECT_ROOT / "verification/catalog.json")
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
    assert plan.tests[0].cwd == PROJECT_ROOT / "src"
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
    catalog = load_catalog(PROJECT_ROOT / "verification/catalog.json")

    with pytest.raises(GateError, match="project root|project path"):
        build_plan(
            select_test(catalog, "real.local.full-flow"),
            {"real.local.full-flow": {"nodes": "50", "config": path}},
            PROJECT_ROOT,
            selection_kind="test",
            selection_id="real.local.full-flow",
            cli_source=True,
        )
