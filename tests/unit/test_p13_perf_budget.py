from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_p13_optimization_gate():
    path = Path("scripts/p13_optimization_gate.py")
    spec = importlib.util.spec_from_file_location("p13_optimization_gate_for_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_perf_budget_warns_by_default_when_over_budget() -> None:
    gate = _load_p13_optimization_gate()

    result = gate.perf_budget_result(
        name="scale_100_cleanup",
        metric="cleanup_duration_seconds",
        scenario="scale_100",
        observed_seconds=31.0,
        budget_seconds=30.0,
        strict_enabled=False,
    )

    assert result["status"] == "WARN"
    assert result["result"] == "OVER_BUDGET"
    assert result["over_by_seconds"] == 1.0


def test_perf_budget_fails_in_strict_mode_when_over_budget() -> None:
    gate = _load_p13_optimization_gate()

    result = gate.perf_budget_result(
        name="scale_100_cleanup",
        metric="cleanup_duration_seconds",
        scenario="scale_100",
        observed_seconds=31.0,
        budget_seconds=30.0,
        strict_enabled=True,
    )

    assert result["status"] == "FAIL"
    assert result["result"] == "OVER_BUDGET"
    assert "strict" in result["message"]


def test_perf_budget_missing_metric_fails() -> None:
    gate = _load_p13_optimization_gate()

    result = gate.perf_budget_result(
        name="scale_100_unattributed_seconds",
        metric="unattributed_seconds",
        scenario="scale_100",
        observed_seconds={"status": "MISSING", "reason": "not recorded"},
        budget_seconds=10.0,
        strict_enabled=False,
    )

    assert result["status"] == "FAIL"
    assert result["result"] == "MISSING"


def test_perf_budget_strict_env_is_opt_in() -> None:
    gate = _load_p13_optimization_gate()

    assert gate.strict_perf_budget_enabled({}) is False
    assert gate.strict_perf_budget_enabled({"VSLAB_STRICT_PERF_BUDGET": "0"}) is False
    assert gate.strict_perf_budget_enabled({"VSLAB_STRICT_PERF_BUDGET": "1"}) is True
