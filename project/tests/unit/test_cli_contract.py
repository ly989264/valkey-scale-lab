from __future__ import annotations

import pytest

from valkey_scale_lab import __version__
from valkey_scale_lab import cli as cli_module
from valkey_scale_lab.cli import main


def test_version_is_available() -> None:
    assert __version__


def test_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Valkey scale lab CLI" in out
    assert "gate" in out
    assert "fault" in out


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
