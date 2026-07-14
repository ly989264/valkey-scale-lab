from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_p13o_gate():
    path = Path("scripts/p13_optimization_gate.py")
    spec = importlib.util.spec_from_file_location("p13_optimization_gate_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_p13o_postcheck_source_freshness_fails_missing_or_stale_source(tmp_path: Path) -> None:
    gate = _load_p13o_gate()
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    artifact = {
        "source_artifacts": [
            {"path": "source.json", "sha256": "stale"},
            {"path": "missing.json", "sha256": "missing"},
        ]
    }

    errors = gate.setup_timeline_freshness_errors(artifact, root=tmp_path)

    assert any("source stale" in error for error in errors)
    assert any("source missing" in error for error in errors)
