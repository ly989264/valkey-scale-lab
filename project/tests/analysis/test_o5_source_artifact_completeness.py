from __future__ import annotations

import dataclasses
import importlib.util
from pathlib import Path

import pytest

from valkey_scale_lab.analysis import ValidatedAnalysisError, analyze_validated_evidence


ROOT = Path(__file__).resolve().parents[2]


def test_analysis_rejects_a_capability_that_omits_an_admitted_source_artifact(
    tmp_path: Path,
) -> None:
    support_path = ROOT / "tests/analysis/test_validated_analysis_v9.py"
    spec = importlib.util.spec_from_file_location("o5_source_support", support_path)
    assert spec is not None and spec.loader is not None
    support = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(support)
    bundle = support._bundle(tmp_path)
    forged = dataclasses.replace(bundle, artifacts=bundle.artifacts[:-1])

    with pytest.raises(ValidatedAnalysisError, match="artifact"):
        analyze_validated_evidence(forged, tmp_path / "analysis.json")
