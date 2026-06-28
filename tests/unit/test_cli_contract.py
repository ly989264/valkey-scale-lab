from __future__ import annotations

import pytest

from valkey_scale_lab import __version__
from valkey_scale_lab.cli import UNIMPLEMENTED, main


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


@pytest.mark.parametrize(
    "argv",
    [
        ["analyze", "--artifacts-dir", "artifacts", "--out", "analysis.json"],
        ["report", "--artifacts-dir", "artifacts", "--out", "report"],
    ],
)
def test_contract_commands_are_explicitly_unimplemented(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == 2
    assert UNIMPLEMENTED in capsys.readouterr().err
