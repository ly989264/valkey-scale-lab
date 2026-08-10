from __future__ import annotations

import json

import pytest

from valkey_scale_lab import __version__
from valkey_scale_lab import cli as cli_module
from valkey_scale_lab.cli import main
from valkey_scale_lab.observability.contracts import CollectionError
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError


def test_version_is_available() -> None:
    assert __version__


def test_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Valkey scale lab CLI" in out
    assert "gate" in out


@pytest.mark.parametrize("argv", [["analyze", "--help"], ["report", "--help"], ["resource", "preflight", "--help"]])
def test_analysis_and_report_help_succeed(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 0


def test_legacy_analyze_requires_out(capsys: pytest.CaptureFixture[str], tmp_path) -> None:
    assert main(["analyze", "--input", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "--out is required" in err


def test_workload_impact_analyze_creates_consolidated_artifacts(tmp_path) -> None:
    source = tmp_path / "capabilities"
    source.mkdir()
    out = tmp_path / "fault_workload_impact"

    assert main(["analyze", "--kind", "workload-impact", "--input", str(source), "--out-dir", str(out)]) == 0

    assert (out / "workload_impact_analysis.json").exists()
    assert (out / "csv_export_index.json").exists()


def test_resource_preflight_cli_passes_capability_and_scenario(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_preflight(config, out, dry_run=False, *, capability_id=None, scenario=None):
        calls.append({
            "config": config,
            "out": out,
            "dry_run": dry_run,
            "capability_id": capability_id,
            "scenario": scenario,
        })
        return {"can_run": True}

    monkeypatch.setattr(cli_module, "run_resource_preflight", fake_preflight)

    assert main([
        "resource",
        "preflight",
        "--config",
        "templates/configs/scale_200.yaml",
        "--out",
        str(tmp_path / "preflight.json"),
        "--capability-id",
        "fault_matrix",
        "--scenario",
        "fault_matrix",
    ]) == 0

    assert calls == [
        {
            "config": "templates/configs/scale_200.yaml",
            "out": str(tmp_path / "preflight.json"),
            "dry_run": False,
            "capability_id": "fault_matrix",
            "scenario": "fault_matrix",
        }
    ]


def _gate_execute_argv(tmp_path, result_path: str | None) -> list[str]:
    argv = [
        "gate",
        "execute",
        "--definition",
        "src/valkey_scale_lab/scenarios/definitions/local_full_flow_v1.json",
        "--nodes",
        "50",
        "--config",
        "templates/configs/scale_50.yaml",
        "--run-id",
        "cli-verdict",
        "--ownership-id",
        "cli-verdict",
        "--provenance-id",
        "cli-verdict",
        "--artifacts-dir",
        str(tmp_path / "evidence"),
    ]
    if result_path is not None:
        argv += ["--result-path", result_path]
    return argv


@pytest.mark.parametrize("outcome", ["pass", "fail", "error"])
def test_gate_execute_writes_its_own_verdict_and_still_exits_zero(
    tmp_path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """With `--result-path` the file carries the verdict, not the exit code.

    `real.local.full-flow` declares `result: json`, and the Gate only reads that
    file when the process exits 0. A failing run must therefore still exit 0 and
    say FAIL in the file; exiting non-zero would make the Gate report FAIL
    without reading anything, which is the collapse this route removes.
    """

    def fake_run(**_kwargs: object) -> dict[str, object]:
        if outcome == "fail":
            raise DockerRuntimeError("cluster convergence did not hold")
        if outcome == "error":
            raise CollectionError("resource sampler produced no evidence")
        return {"status": "PASS"}

    monkeypatch.setattr(cli_module, "run_exact_gate", fake_run)
    monkeypatch.setattr(cli_module, "product_tree_digest", lambda: "0" * 64)
    result_path = tmp_path / "result.json"

    assert main(_gate_execute_argv(tmp_path, str(result_path))) == 0
    written = json.loads(result_path.read_text(encoding="utf-8"))
    assert written["status"] == {"pass": "PASS", "fail": "FAIL", "error": "ERROR"}[outcome]
    # The Gate rejects a result file carrying anything else, so the run says only
    # what it decided and why.
    assert set(written) == {"status", "summary"}
    if outcome == "fail":
        assert "cluster convergence did not hold" in written["summary"]
    if outcome == "error":
        # Not "failed": §12.1 makes this the collector's own failure, and saying
        # the cluster failed is the misreport the whole change exists to remove.
        assert "could not complete" in written["summary"]
        assert "resource sampler produced no evidence" in written["summary"]


@pytest.mark.parametrize(("outcome", "expected"), [("pass", 0), ("fail", 1)])
def test_gate_execute_without_result_path_keeps_the_exit_code_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch, outcome: str, expected: int
) -> None:
    """Driving the product directly is how a scale the Gate refuses is reached,
    so the exit code stays meaningful when no result path is supplied."""

    def fake_run(**_kwargs: object) -> dict[str, object]:
        if outcome == "fail":
            raise DockerRuntimeError("six nodes give one AZ")
        return {"status": "PASS"}

    monkeypatch.setattr(cli_module, "run_exact_gate", fake_run)
    monkeypatch.setattr(cli_module, "product_tree_digest", lambda: "0" * 64)

    assert main(_gate_execute_argv(tmp_path, None)) == expected
