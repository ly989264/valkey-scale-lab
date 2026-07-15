from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from verification.gate import main


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _test(
    test_id: str,
    argv: list[str],
    *,
    runner_type: str = "command",
    result: str = "exit_code",
    timeout: int = 10,
    parameters: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "test_id": test_id,
        "description": f"{test_id} description",
        "parameters": parameters or {},
        "runner": {
            "type": runner_type,
            "argv": argv,
            "cwd": "{gate.project_root}",
            "timeout_seconds": timeout,
            "result": result,
        },
    }


def _catalog(
    root: Path,
    tests: list[dict[str, object]],
    test_ids: list[str] | None = None,
) -> Path:
    path = root / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "verification-catalog-v2",
                "suites": [
                    {
                        "suite_id": "sample.suite",
                        "description": "Sample suite.",
                        "test_ids": test_ids or [test["test_id"] for test in tests],
                    }
                ],
                "tests": tests,
            }
        ),
        encoding="utf-8",
    )
    return path


def _summaries(root: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (root / "artifacts/gate-runs").glob("*/summary.json")
    ]


def test_outer_gate_help_is_runnable() -> None:
    completed = subprocess.run(
        [str(PROJECT_ROOT / "gate"), "help"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "./gate test <test-id>" in completed.stdout
    assert "./gate suite <suite-id>" in completed.stdout


def test_single_command_test_passes_and_writes_summary(tmp_path: Path, capsys) -> None:
    catalog = _catalog(
        tmp_path,
        [_test("sample.pass", [sys.executable, "-c", "print('ok')"])],
    )

    assert main(
        ["test", "sample.pass"], project_root=tmp_path, catalog_path=catalog
    ) == 0
    output = capsys.readouterr().out
    assert "sample.pass" in output
    assert "1/1 passed" in output
    summary = _summaries(tmp_path)[0]
    assert summary["status"] == "PASS"
    log = next((tmp_path / "artifacts/gate-runs").glob("*/sample.pass/stdout.log"))
    assert log.read_text(encoding="utf-8").strip() == "ok"


def test_suite_continues_after_failure_and_summarizes_every_test(
    tmp_path: Path, capsys
) -> None:
    catalog = _catalog(
        tmp_path,
        [
            _test("sample.fail", [sys.executable, "-c", "raise SystemExit(3)"]),
            _test("sample.pass", [sys.executable, "-c", "print('continued')"]),
        ],
    )

    assert main(
        ["suite", "sample.suite"], project_root=tmp_path, catalog_path=catalog
    ) == 1
    output = capsys.readouterr().out
    assert "sample.fail" in output
    assert "sample.pass" in output
    summary = _summaries(tmp_path)[0]
    assert [row["status"] for row in summary["tests"]] == ["FAIL", "PASS"]


def test_suite_parameters_are_grouped_by_test_id(tmp_path: Path) -> None:
    marker = tmp_path / "value.txt"
    test = _test(
        "sample.parameter",
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])",
            str(marker),
            "{param.nodes}",
        ],
        parameters={
            "nodes": {"type": "integer", "minimum": 30, "maximum": 200, "required": True}
        },
    )
    catalog = _catalog(tmp_path, [test])
    params = tmp_path / "params.json"
    params.write_text(json.dumps({"sample.parameter": {"nodes": 50}}), encoding="utf-8")

    assert main(
        ["suite", "sample.suite", "--params-file", str(params)],
        project_root=tmp_path,
        catalog_path=catalog,
    ) == 0
    assert marker.read_text(encoding="utf-8") == "50"


def test_suite_parameter_errors_abort_before_any_process_starts(tmp_path: Path) -> None:
    marker = tmp_path / "started"
    first = _test(
        "sample.first",
        [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
    )
    second = _test(
        "sample.second",
        [sys.executable, "-c", "print('{param.nodes}')"],
        parameters={"nodes": {"type": "integer", "required": True}},
    )
    catalog = _catalog(tmp_path, [first, second])

    assert main(
        ["suite", "sample.suite"], project_root=tmp_path, catalog_path=catalog
    ) == 2
    assert not marker.exists()


@pytest.mark.parametrize(("status", "expected"), [("PASS", 0), ("FAIL", 1)])
def test_command_json_result_contract(
    tmp_path: Path, status: str, expected: int
) -> None:
    code = (
        "from pathlib import Path; import json,sys; "
        f"Path(sys.argv[1]).write_text(json.dumps(dict(status={status!r}, summary='done')))"
    )
    catalog = _catalog(
        tmp_path,
        [
            _test(
                "sample.json",
                [sys.executable, "-c", code, "{gate.result_path}"],
                result="json",
            )
        ],
    )

    assert main(
        ["test", "sample.json"], project_root=tmp_path, catalog_path=catalog
    ) == expected


def test_malformed_command_json_is_error(tmp_path: Path) -> None:
    code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('not-json')"
    catalog = _catalog(
        tmp_path,
        [
            _test(
                "sample.json",
                [sys.executable, "-c", code, "{gate.result_path}"],
                result="json",
            )
        ],
    )

    assert main(
        ["test", "sample.json"], project_root=tmp_path, catalog_path=catalog
    ) == 1
    assert _summaries(tmp_path)[0]["tests"][0]["status"] == "ERROR"


@pytest.mark.parametrize(("body", "expected"), [("def test_ok(): pass", 0), ("import pytest\ndef test_skip(): pytest.skip('no')", 1)])
def test_pytest_junit_is_read_and_skips_fail_closed(
    tmp_path: Path, body: str, expected: int
) -> None:
    test_path = tmp_path / "test_sample.py"
    test_path.write_text(body + "\n", encoding="utf-8")
    catalog = _catalog(
        tmp_path,
        [
            _test(
                "sample.pytest",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    str(test_path),
                    "--junitxml={gate.result_path}",
                ],
                runner_type="pytest",
                result="junit",
            )
        ],
    )

    assert main(
        ["test", "sample.pytest"], project_root=tmp_path, catalog_path=catalog
    ) == expected
    result = _summaries(tmp_path)[0]["tests"][0]
    assert result["counts"]["tests"] == 1
    assert result["counts"]["skipped"] == (1 if expected else 0)


def test_timeout_kills_the_child_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "child-survived"
    child = f"import time; time.sleep(2); open({str(marker)!r}, 'w').close()"
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(10)"
    )
    catalog = _catalog(
        tmp_path,
        [_test("sample.timeout", [sys.executable, "-c", parent], timeout=1)],
    )

    assert main(
        ["test", "sample.timeout"], project_root=tmp_path, catalog_path=catalog
    ) == 1
    time.sleep(1.5)
    assert not marker.exists()
    assert _summaries(tmp_path)[0]["tests"][0]["status"] == "TIMEOUT"


def test_failure_output_is_bounded_but_full_log_is_kept(
    tmp_path: Path, capsys
) -> None:
    code = "[print('line-%d' % i) for i in range(100)]; raise SystemExit(1)"
    catalog = _catalog(
        tmp_path,
        [_test("sample.noisy", [sys.executable, "-c", code])],
    )

    assert main(
        ["test", "sample.noisy"], project_root=tmp_path, catalog_path=catalog
    ) == 1
    output = capsys.readouterr().out
    assert "line-99" in output
    assert "line-0\n" not in output
    log = next((tmp_path / "artifacts/gate-runs").glob("*/sample.noisy/stdout.log"))
    assert len(log.read_text(encoding="utf-8").splitlines()) == 100


def test_selection_and_parameter_errors_return_two(tmp_path: Path) -> None:
    catalog = _catalog(
        tmp_path,
        [_test("sample.pass", [sys.executable, "-c", "pass"])],
    )

    assert main(
        ["test", "unknown.test"], project_root=tmp_path, catalog_path=catalog
    ) == 2
    assert main(
        ["test", "sample.pass", "--param", "extra=1"],
        project_root=tmp_path,
        catalog_path=catalog,
    ) == 2
