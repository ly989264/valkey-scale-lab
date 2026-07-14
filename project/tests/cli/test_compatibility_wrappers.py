from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from valkey_scale_lab import cli, cli_compat
from valkey_scale_lab.planner.plan import PlannerError
from valkey_scale_lab.runtime import docker_runtime
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline


_SETUP_TIMELINE = object()


@pytest.mark.parametrize(
    ("backend", "backend_name", "invoke", "expected_args", "expected_kwargs"),
    [
        (
            cli_compat.config_validation,
            "validate_config_file",
            lambda: cli_compat.validate_config_file("config.yaml", "validation.json", global_config_path="global.yaml", cli_overrides={"runtime": {"io_threads": 2}}),
            ("config.yaml", "validation.json"),
            {"global_config_path": "global.yaml", "cli_overrides": {"runtime": {"io_threads": 2}}},
        ),
        (cli_compat.config_validation, "emit_schema_report", lambda: cli_compat.emit_schema_report("schema.json"), ("schema.json",), {}),
        (
            cli_compat.planner,
            "create_plan_file",
            lambda: cli_compat.create_plan_file("config.yaml", "plan.json", True, global_config_path="global.yaml", cli_overrides={"cluster": {"cluster_node_timeout_ms": 5000}}),
            ("config.yaml", "plan.json"),
            {"dry_run": True, "global_config_path": "global.yaml", "cli_overrides": {"cluster": {"cluster_node_timeout_ms": 5000}}},
        ),
        (
            cli_compat.docker_runtime,
            "create_scenario",
            lambda: cli_compat.create_scenario(phase="P", scenario="S", config_path="config.yaml", artifacts_dir="artifacts", state_out="state.json", setup_timeline=_SETUP_TIMELINE, global_config_path="global.yaml", cli_overrides={"runtime": {"io_threads": 2}}),
            (),
            {"phase": "P", "scenario": "S", "config_path": "config.yaml", "artifacts_dir": "artifacts", "state_out": "state.json", "setup_timeline": _SETUP_TIMELINE, "global_config_path": "global.yaml", "cli_overrides": {"runtime": {"io_threads": 2}}},
        ),
        (
            cli_compat.docker_runtime,
            "cleanup_scenario",
            lambda: cli_compat.cleanup_scenario(state_path="state.json", artifacts_dir="artifacts", out_path="cleanup.json"),
            (),
            {"state_path": "state.json", "artifacts_dir": "artifacts", "out_path": "cleanup.json"},
        ),
        (
            cli_compat.fault_sandbox,
            "apply_fault",
            lambda: cli_compat.apply_fault(state_path="state.json", target_logical_id="node-1", fault_json="fault.json", out_path="apply.json"),
            (),
            {"state_path": "state.json", "target_logical_id": "node-1", "fault_json": "fault.json", "out_path": "apply.json"},
        ),
        (
            cli_compat.fault_sandbox,
            "clear_fault",
            lambda: cli_compat.clear_fault(state_path="state.json", fault_id="fault-1", out_path="clear.json"),
            (),
            {"state_path": "state.json", "fault_id": "fault-1", "out_path": "clear.json"},
        ),
        (cli_compat.analysis_summary, "create_analysis_summary", lambda: cli_compat.create_analysis_summary("input", "analysis.json"), ("input", "analysis.json"), {}),
        (
            cli_compat.workload_impact,
            "build_workload_impact_analysis",
            lambda: cli_compat.build_workload_impact_analysis("input", "analysis", phase_id="P25", run_id="run-1"),
            ("input", "analysis"),
            {"phase_id": "P25", "run_id": "run-1"},
        ),
        (cli_compat.summary_report, "render_report", lambda: cli_compat.render_report("analysis.json", "reports", "index.json"), ("analysis.json", "reports", "index.json"), {}),
        (
            cli_compat.final_report,
            "build_final_goal_loop_report",
            lambda: cli_compat.build_final_goal_loop_report("input", "reports", "P26"),
            ("input", "reports"),
            {"phase_id": "P26"},
        ),
    ],
)
def test_compatibility_wrappers_preserve_arguments_returns_and_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    backend: Any,
    backend_name: str,
    invoke: Callable[[], Any],
    expected_args: tuple[Any, ...],
    expected_kwargs: dict[str, Any],
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    sentinel = object()

    def fake(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setattr(backend, backend_name, fake)
    assert invoke() is sentinel
    assert calls == [(expected_args, expected_kwargs)]

    error = RuntimeError("backend failure")

    def fail(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(backend, backend_name, fail)
    with pytest.raises(RuntimeError) as caught:
        invoke()
    assert caught.value is error


def test_cli_keeps_legacy_symbols_bound_for_import_compatibility() -> None:
    assert cli.create_scenario is docker_runtime.create_scenario
    assert cli.cleanup_scenario is docker_runtime.cleanup_scenario


def test_config_and_plan_handlers_use_compatibility_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(cli_compat, "validate_config_file", lambda *a, **kw: calls.append(("validate", a, kw)) or {"valid": True})
    monkeypatch.setattr(cli_compat, "emit_schema_report", lambda *a, **kw: calls.append(("schema", a, kw)) or {})

    assert cli.main(["config", "validate", "--config", "config.yaml", "--out", str(tmp_path / "validation.json")]) == 0
    assert cli.main(["config", "emit-schema", "--out", str(tmp_path / "schema.json")]) == 0

    def bad_plan(*args: Any, **kwargs: Any) -> None:
        calls.append(("plan", args, kwargs))
        raise PlannerError("bad plan")

    monkeypatch.setattr(cli_compat, "create_plan_file", bad_plan)
    assert cli.main(["plan", "--config", "config.yaml", "--out", str(tmp_path / "plan.json"), "--dry-run"]) == 1
    assert "ERROR: plan: bad plan" in capsys.readouterr().err
    assert [call[0] for call in calls] == ["validate", "schema", "plan"]
    assert calls[0][2] == {"global_config_path": None, "cli_overrides": None}
    assert calls[2][2] == {"dry_run": True, "global_config_path": None, "cli_overrides": None}


def test_gate_scenario_and_cleanup_handlers_use_compatibility_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    artifacts = tmp_path / "artifacts"
    state_path = tmp_path / "state.json"

    def create(**kwargs: Any) -> dict[str, Any]:
        calls.append(("create", kwargs))
        return {"cluster_id": "cluster-1", "nodes": [{"logical_id": "node-1"}], "runtime": {}}

    monkeypatch.setattr(cli_compat, "create_scenario", create)
    monkeypatch.setattr(cli, "_finalize_setup_timeline", lambda *args, **kwargs: None)
    assert cli.main(["gate", "scenario", "--phase", "P", "--scenario", "S", "--config", "config.yaml", "--artifacts-dir", str(artifacts), "--state-out", str(state_path)]) == 0
    assert isinstance(calls[0][1]["setup_timeline"], SetupTimeline)
    assert calls[0][1]["global_config_path"] is None
    assert calls[0][1]["cli_overrides"] is None

    state_path.write_text(json.dumps({"phase_id": "P", "scenario": "S", "runtime": {"run_id": "run-1"}}), encoding="utf-8")

    def cleanup(**kwargs: Any) -> dict[str, Any]:
        calls.append(("cleanup", kwargs))
        return {"status": "PASS"}

    monkeypatch.setattr(cli_compat, "cleanup_scenario", cleanup)
    cleanup_path = tmp_path / "cleanup.json"
    assert cli.main(["gate", "cleanup", "--state", str(state_path), "--artifacts-dir", str(artifacts), "--out", str(cleanup_path)]) == 0
    assert calls[1] == ("cleanup", {"state_path": str(state_path), "artifacts_dir": str(artifacts), "out_path": str(cleanup_path)})


def test_fault_handlers_use_compatibility_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"phase_id": "P", "scenario": "S", "runtime": {"run_id": "run-1"}}), encoding="utf-8")
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(cli_compat, "apply_fault", lambda **kw: calls.append(("apply", kw)) or {})
    monkeypatch.setattr(cli_compat, "clear_fault", lambda **kw: calls.append(("clear", kw)) or {})
    assert cli.main(["fault", "apply", "--state", str(state), "--target-logical-id", "node-1", "--fault-json", "fault.json", "--out", str(tmp_path / "apply.json")]) == 0
    assert cli.main(["fault", "clear", "--state", str(state), "--fault-id", "fault-1", "--out", str(tmp_path / "clear.json")]) == 0
    assert [name for name, _ in calls] == ["apply", "clear"]


def test_analyze_and_report_handlers_use_compatibility_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    for name in ("create_analysis_summary", "build_workload_impact_analysis", "render_report", "build_final_goal_loop_report"):
        monkeypatch.setattr(cli_compat, name, lambda *a, _name=name, **kw: calls.append((_name, a, kw)) or {})
    assert cli.main(["analyze", "--input", "input", "--out", str(tmp_path / "analysis.json")]) == 0
    assert cli.main(["analyze", "--kind", "workload-impact", "--input", "input", "--out-dir", str(tmp_path / "impact")]) == 0
    assert cli.main(["report", "--analysis", "analysis.json", "--out-dir", str(tmp_path / "reports"), "--index-out", str(tmp_path / "index.json")]) == 0
    assert cli.main(["report", "--kind", "final-goal-loop", "--input", "input", "--out-dir", str(tmp_path / "final")]) == 0
    assert [name for name, _, _ in calls] == ["create_analysis_summary", "build_workload_impact_analysis", "render_report", "build_final_goal_loop_report"]


def test_exact_gate_handler_uses_product_neutral_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[dict[str, Any]] = []
    definition = object()

    def fail(**kwargs: Any) -> None:
        calls.append(kwargs)
        raise DockerRuntimeError("runtime denied")

    monkeypatch.setattr(cli, "load_scenario_definition", lambda _path: definition)
    monkeypatch.setattr(cli, "run_exact_gate", fail)
    assert cli.main([
        "gate", "execute",
        "--definition", "flow.json",
        "--nodes", "50",
        "--config", "scale-50.yaml",
        "--run-id", "run-50",
        "--ownership-id", "owner-50",
        "--provenance-id", "capture-50",
        "--artifacts-dir", "evidence",
        "--product-digest", "a" * 64,
    ]) == 1
    assert calls[0]["definition"] is definition
    assert calls[0]["scale"] == 50
    assert calls[0]["ownership_id"] == "owner-50"
    assert "ERROR: gate execute: runtime denied" in capsys.readouterr().err
