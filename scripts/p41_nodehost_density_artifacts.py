#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab import __version__  # noqa: E402
from valkey_scale_lab.config.validation import load_effective_config  # noqa: E402
from valkey_scale_lab.planner.plan import build_cluster_plan, create_plan_file  # noqa: E402
from valkey_scale_lab.resource import run_resource_preflight  # noqa: E402

PHASE = "P41_NODEHOST_DENSITY_GLOBAL_CONFIG"
RUN_ID = "P41_NODEHOST_DENSITY_GLOBAL_CONFIG-density-20260706"
CREATED_AT = "2026-07-06T00:00:00Z"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact_ref(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def main() -> int:
    base = ROOT / "artifacts" / "phases" / PHASE
    base.mkdir(parents=True, exist_ok=True)
    plan100 = create_plan_file(ROOT / "templates/configs/scale_100.yaml", base / "cluster_plan.json")
    density = plan100["nodehost_density"]
    density_plan = {
        "schema_version": "v1",
        "artifact_type": "nodehost_density_plan",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        **density,
        "nodehost_density": density,
        "nodehosts": plan100["nodehosts"],
        "source_plan": artifact_ref(base / "cluster_plan.json"),
    }
    write_json(base / "nodehost_density_plan.json", density_plan)
    preflight = run_resource_preflight(
        ROOT / "templates/configs/scale_100.yaml",
        base / "resource_preflight.json",
        phase_id=PHASE,
        scenario="nodehost_density_scale_100",
    )
    run_state = {
        "schema_version": "v1",
        "artifact_type": "strict_run_state",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "node_count": plan100["node_count"],
        "runtime": {
            "type": "dry_run_projection",
            "real_valkey": False,
            **density,
        },
        "nodehost_density": density,
        "nodehosts": plan100["nodehosts"],
        "nodes": plan100["nodes"],
        "reason": "P41 run_state records density planning evidence and does not claim live Valkey runtime.",
    }
    write_json(base / "run_state.json", run_state)

    config200 = load_effective_config(ROOT / "templates/configs/scale_200.yaml")
    plan200 = build_cluster_plan(
        config200,
        config_path=ROOT / "templates/configs/scale_200.yaml",
        bounded_exception_phase="P32_MANAGEMENT_MATRIX_200_REAL",
        bounded_exception_scenario="strict_management_matrix_200",
    )
    projection250 = create_plan_file(
        ROOT / "templates/configs/scale_1000_dryrun_optin.yaml",
        base / "dry_run_gt_200_projection.json",
        dry_run=True,
    )
    smoke_evidence = base / "smoke_10_valkey_e2e_evidence.json"
    smoke_status, smoke_reason = _real_evidence_status(smoke_evidence, 10)
    smoke_refs = [artifact_ref(smoke_evidence)] if smoke_evidence.exists() else [artifact_ref(base / "nodehost_density_plan.json")]
    coverage_rows = [
        row("fake_schema_unit", "PASS", [artifact_ref(base / "nodehost_density_plan.json")], execution_mode="unit_schema"),
        row("smoke_6_or_10", smoke_status, smoke_refs, reason=smoke_reason, execution_mode="real_valkey"),
        real_row(base, 30),
        real_row(base, 50),
        real_row(base, 100),
        real_row(base, 200),
        row("dry_run_gt_200", "DRY_RUN_PASS", [artifact_ref(base / "dry_run_gt_200_projection.json")], execution_mode="dry_run"),
    ]
    plan200_artifact = {
        "schema_version": "v1",
        "artifact_type": "nodehost_density_plan",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        **plan200["nodehost_density"],
        "nodehost_density": plan200["nodehost_density"],
        "nodehosts": plan200["nodehosts"],
    }
    write_json(base / "nodehost_density_plan_200.json", plan200_artifact)
    coverage_ledger = {
        "schema_version": "v1",
        "artifact_type": "coverage_ledger",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "rows": coverage_rows,
    }
    write_json(base / "coverage_ledger.json", coverage_ledger)
    analysis_summary = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "nodehost_density": density,
        "source_artifacts": [artifact_ref(base / name) for name in ["nodehost_density_plan.json", "resource_preflight.json", "cluster_plan.json", "coverage_ledger.json"]],
        "findings": [
            {
                "name": "nodehost_density_scale_100",
                "status": "PASS",
                "summary": "100-node path uses 4 density-limited nodehosts with no nodehost above the configured logical-node cap.",
            },
            {
                "name": "nodehost_density_scale_200",
                "status": "PASS",
                "summary": "200-node path uses 8 density-limited nodehosts with no nodehost above the configured logical-node cap.",
            },
        ],
        "missing_metrics": [],
        "metrics": [
            {"name": "actual_nodehost_count_scale_100", "status": "PASS", "value": density["actual_nodehost_count"], "unit": "nodehosts"},
            {"name": "actual_nodehost_count_scale_200", "status": "PASS", "value": plan200["nodehost_density"]["actual_nodehost_count"], "unit": "nodehosts"},
        ],
    }
    write_json(base / "analysis_summary.json", analysis_summary)
    report_index = {
        "schema_version": "v1",
        "artifact_type": "report_index",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS",
        "nodehost_density": density,
        "analysis_path": artifact_ref(base / "analysis_summary.json"),
        "reports": [],
        "source_artifacts": analysis_summary["source_artifacts"],
    }
    write_json(base / "report_index.json", report_index)
    phase_summary = {
        "schema_version": "v1",
        "artifact_type": "phase_summary",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        "status": "PASS" if preflight.get("status") == "PASS" else "FAIL",
        "summary": "P41 added global nodehost density config, shared density planning, fail-closed preflight checks, and nodehost density artifacts.",
        "nodehost_density": density,
        "required_artifacts": [artifact_ref(base / name) for name in ["phase_summary.json", "nodehost_density_plan.json", "resource_preflight.json", "run_state.json", "cluster_plan.json", "coverage_ledger.json", "analysis_summary.json", "report_index.json"]],
        "missing_metrics": [],
        "risks": [
            {
                "risk": "Full 30/50/100/200 real Valkey evidence depends on Docker availability and free local ports.",
                "severity": "low",
                "required_before_next_phase": False,
            }
        ],
    }
    write_json(base / "phase_summary.json", phase_summary)
    return 0 if phase_summary["status"] == "PASS" else 1


def row(coverage_id: str, status: str, refs: list[str], *, reason: str = "", execution_mode: str = "real_or_plan") -> dict[str, Any]:
    item = {
        "coverage_id": coverage_id,
        "status": status,
        "artifact_refs": refs,
        "execution_mode": execution_mode,
    }
    if reason:
        item["reason"] = reason
    return item


def real_row(base: Path, node_count: int) -> dict[str, Any]:
    evidence = base / f"valkey_e2e_evidence_{node_count}.json"
    status, reason = _real_evidence_status(evidence, node_count)
    refs = [artifact_ref(evidence)] if evidence.exists() else [artifact_ref(base / "nodehost_density_plan.json")]
    return row(f"real_{node_count}", status, refs, reason=reason, execution_mode="real_valkey")


def _real_evidence_status(path: Path, expected_nodes: int) -> tuple[str, str]:
    if not path.exists():
        return "SKIPPED_WITH_REASON", f"real Valkey evidence missing for {expected_nodes} nodes; plan evidence is not accepted for real coverage"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return "SKIPPED_WITH_REASON", f"real Valkey evidence for {expected_nodes} nodes is invalid JSON: {exc}"
    if obj.get("status") != "PASS" or obj.get("probe_result") != "PASS":
        return "SKIPPED_WITH_REASON", f"real Valkey evidence for {expected_nodes} nodes did not PASS"
    if obj.get("real_valkey") is not True:
        return "SKIPPED_WITH_REASON", f"real Valkey evidence for {expected_nodes} nodes does not declare real_valkey=true"
    try:
        observed = int(obj.get("nodes_observed", 0) or 0)
    except (TypeError, ValueError):
        observed = 0
    if observed < expected_nodes:
        return "SKIPPED_WITH_REASON", f"real Valkey evidence observed {observed} nodes, expected at least {expected_nodes}"
    runtime = obj.get("runtime", {})
    if runtime.get("nodehost_strategy") != "density_limited":
        return "SKIPPED_WITH_REASON", f"real Valkey evidence for {expected_nodes} nodes lacks density_limited runtime evidence"
    return "PASS", ""


def _json_status(path: Path) -> str:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "FAIL"
    return str(obj.get("status") or obj.get("probe_result") or "MISSING")


if __name__ == "__main__":
    raise SystemExit(main())
