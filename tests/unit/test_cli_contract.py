from __future__ import annotations

import pytest

from valkey_scale_lab import __version__
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


def test_workload_impact_analyze_creates_cross_stage_artifacts(tmp_path) -> None:
    source = tmp_path / "phases"
    source.mkdir()
    out = tmp_path / "p25"

    assert main(["analyze", "--kind", "workload-impact", "--input", str(source), "--out-dir", str(out)]) == 0

    assert (out / "workload_impact_cross_stage.json").exists()
    assert (out / "csv_export_index.json").exists()
