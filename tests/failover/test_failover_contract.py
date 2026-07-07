from __future__ import annotations

import json
import importlib.util
from argparse import Namespace
from pathlib import Path


def load_fault_failover_gate():
    script = Path(__file__).resolve().parents[2] / "scripts" / "fault_failover_gate.py"
    spec = importlib.util.spec_from_file_location("fault_failover_gate_contract", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failover_report_shape_allows_measured_or_missing_duration(tmp_path: Path) -> None:
    report = {
        "schema_version": "v1",
        "artifact_type": "failover_report",
        "phase_id": "P08_FAILOVER_SPLIT_BRAIN",
        "run_id": "test",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "test", "version": "v1"},
        "status": "PASS",
        "failovers": [
            {
                "fault_id": "fault-primary-stop",
                "target_logical_id": "shard-0000-primary",
                "promoted_node_id": "node-2",
                "failover_latency_ms": 1234.0,
            }
        ],
        "summary": {
            "primary_stop_observed": True,
            "promotion_observed": True,
            "split_brain_duration_ms": {
                "value": None,
                "status": "MISSING",
                "reason": "not_measured_by_primary_stop_gate",
            },
        },
    }
    path = tmp_path / "failover_report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["artifact_type"] == "failover_report"
    assert loaded["summary"]["promotion_observed"] is True
    assert loaded["summary"]["split_brain_duration_ms"]["status"] == "MISSING"


def test_p20_sample_scenario_maps_to_unique_scale_setup_alias() -> None:
    gate = load_fault_failover_gate()

    assert gate.scale_setup_scenario("scale_100_sample_03_fault_failover") == "scale_100_sample_03"
    assert gate.scale_setup_scenario("scale_30_fault_failover") == "scale_30"


def test_failover_timeout_resolves_global_config_when_cli_absent() -> None:
    gate = load_fault_failover_gate()

    value, source, profile = gate.resolve_failover_timeout(
        Namespace(
            config="templates/configs/scale_10.yaml",
            timeout_config_ms=None,
            failover_node_timeout_ms=None,
        )
    )

    assert value == 30000
    assert source == "global"
    assert profile == "MISSING"


def test_failover_timeout_marks_legacy_flag_as_cli_source() -> None:
    gate = load_fault_failover_gate()

    value, source, profile = gate.resolve_failover_timeout(
        Namespace(
            config="templates/configs/scale_10.yaml",
            timeout_config_ms=None,
            failover_node_timeout_ms=10000,
        )
    )

    assert value == 10000
    assert source == "cli"
    assert profile == "failover_node_timeout_ms"


def test_failover_timeout_resolves_scenario_override(tmp_path: Path) -> None:
    gate = load_fault_failover_gate()
    source = Path("templates/configs/scale_10.yaml")
    config = tmp_path / "scale_10_timeout.yaml"
    text = source.read_text(encoding="utf-8")
    text = text.replace("  cluster_bus_port_base: 17200", "  cluster_bus_port_base: 17200\n  cluster_node_timeout_ms: 60000")
    config.write_text(text, encoding="utf-8")

    value, source_name, profile = gate.resolve_failover_timeout(
        Namespace(
            config=config.as_posix(),
            timeout_config_ms=None,
            failover_node_timeout_ms=None,
        )
    )

    assert value == 60000
    assert source_name == "scenario"
    assert profile == "MISSING"
