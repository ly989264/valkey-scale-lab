from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from typing import Any, Callable

import pytest

from valkey_scale_lab import cli, cli_compat
from valkey_scale_lab.execution import ExecutionSelectionError
from valkey_scale_lab.planner.plan import PlannerError
from valkey_scale_lab.runtime import docker_runtime, teardown
from valkey_scale_lab.runtime.docker_runtime import DockerRuntimeError
from valkey_scale_lab.runtime.setup_timeline import SetupTimeline


_SETUP_TIMELINE = object()


def _load_fault_safety_alias():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fault_safety_gate.py"
    spec = importlib.util.spec_from_file_location("fault_safety_alias", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fault_safety_legacy_alias_delegates_to_one_canonical_selection() -> None:
    gate = _load_fault_safety_alias()
    args = gate._parser().parse_args(
        [
            "--phase",
            "P22_FAULT_REPLICA_HOST_AZ_STOP",
            "--out",
            "evidence.json",
            "--fault-report",
            "fault.json",
        ]
    )

    assert gate._selection(args) == (
        "fault_matrix",
        "fault_matrix",
        "docker_container",
        "small-real",
        6,
    )


def test_fault_safety_canonical_selection_rejects_profile_node_mismatch() -> None:
    gate = _load_fault_safety_alias()
    args = gate._parser().parse_args(
        [
            "--profile",
            "exact-200",
            "--nodes",
            "50",
            "--out",
            "evidence.json",
            "--fault-report",
            "fault.json",
        ]
    )

    with pytest.raises(ExecutionSelectionError):
        gate._selection(args)


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
            "execute_scenario",
            lambda: cli_compat.execute_scenario(scenario_id="local_full_flow", backend_id="docker_process", profile_id="exact-50", requested_nodes=50, config_path="config.yaml", artifacts_dir="artifacts", state_out="state.json", setup_timeline=_SETUP_TIMELINE, global_config_path="global.yaml", cli_overrides={"runtime": {"io_threads": 2}}),
            (),
            {"capability_id": "local_full_flow", "scenario_id": "local_full_flow", "backend_id": "docker_process", "profile_id": "exact-50", "requested_nodes": 50, "config_path": "config.yaml", "artifacts_dir": "artifacts", "state_out": "state.json", "setup_timeline": _SETUP_TIMELINE, "global_config_path": "global.yaml", "cli_overrides": {"runtime": {"io_threads": 2}}},
        ),
        (
            cli_compat.teardown,
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
            lambda: cli_compat.build_workload_impact_analysis("input", "analysis", capability_id="P25", run_id="run-1"),
            ("input", "analysis"),
            {"capability_id": "P25", "run_id": "run-1"},
        ),
        (cli_compat.summary_report, "render_report", lambda: cli_compat.render_report("analysis.json", "reports", "index.json"), ("analysis.json", "reports", "index.json"), {}),
        (
            cli_compat.final_report,
            "build_final_report",
            lambda: cli_compat.build_final_goal_loop_report("input", "reports", "P26"),
            ("input", "reports"),
            {"capability_id": "P26"},
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


def test_cli_keeps_product_symbols_bound_for_import_compatibility() -> None:
    assert cli.execute_scenario is docker_runtime.execute_scenario
    assert cli.cleanup_scenario is teardown.cleanup_scenario


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
    assert cli.main(["gate", "scenario", "--phase", "P03_LOCAL_DOCKER_VALKEY", "--scenario", "cluster_smoke", "--config", "config.yaml", "--artifacts-dir", str(artifacts), "--state-out", str(state_path)]) == 0
    assert calls[0][1]["alias_id"] == "P03_LOCAL_DOCKER_VALKEY"
    assert calls[0][1]["scenario"] == "cluster_smoke"
    assert isinstance(calls[0][1]["setup_timeline"], SetupTimeline)
    assert calls[0][1]["global_config_path"] is None
    assert calls[0][1]["cli_overrides"] is None
    command_audit = json.loads((artifacts / "command_audit_summary.json").read_text(encoding="utf-8"))
    assert command_audit["capability_id"] == "cluster_lifecycle"
    assert command_audit["scenario"] == "cluster_lifecycle"

    state_path.write_text(json.dumps({"capability_id": "P", "scenario": "S", "runtime": {"run_id": "run-1"}}), encoding="utf-8")

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
    state.write_text(json.dumps({"capability_id": "P", "scenario": "S", "runtime": {"run_id": "run-1"}}), encoding="utf-8")
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
    for name in ("create_analysis_summary", "build_workload_impact_analysis", "render_report", "build_final_report"):
        monkeypatch.setattr(cli_compat, name, lambda *a, _name=name, **kw: calls.append((_name, a, kw)) or {})
    assert cli.main(["analyze", "--input", "input", "--out", str(tmp_path / "analysis.json")]) == 0
    assert cli.main(["analyze", "--kind", "workload-impact", "--input", "input", "--out-dir", str(tmp_path / "impact")]) == 0
    assert cli.main(["analyze", "--kind", "workload-impact", "--phase", "P25_FAULT_WORKLOAD_IMPACT_ANALYSIS", "--input", "input", "--out-dir", str(tmp_path / "legacy-impact")]) == 0
    assert cli.main(["report", "--analysis", "analysis.json", "--out-dir", str(tmp_path / "reports"), "--index-out", str(tmp_path / "index.json")]) == 0
    assert cli.main(["report", "--kind", "final-report", "--input", "input", "--out-dir", str(tmp_path / "final")]) == 0
    assert cli.main(["report", "--kind", "final-report", "--phase", "P26_FINAL_REPORT_REGRESSION", "--input", "input", "--out-dir", str(tmp_path / "legacy-final")]) == 0
    assert [name for name, _, _ in calls] == ["create_analysis_summary", "build_workload_impact_analysis", "build_workload_impact_analysis", "render_report", "build_final_report", "build_final_report"]
    assert calls[2][2]["capability_id"] == "fault_workload_impact"
    assert calls[5][2]["capability_id"] == "final_report"


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
