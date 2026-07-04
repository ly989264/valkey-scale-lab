from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def test_p37_assertion_rejects_live_claims(tmp_path: Path) -> None:
    assertion = load_script("assert_200_plus_dry_run")
    phase = "P37_200_PLUS_DRY_RUN_SUPPORT"
    assertion.ROOT = tmp_path
    assertion.phase_dir = lambda current: tmp_path / "artifacts" / "phases" / current
    base = assertion.phase_dir(phase)
    build_minimal_p37_fixture(tmp_path, phase, 201)
    report_projection = base / "report_projection_201.json"
    payload = json.loads(report_projection.read_text(encoding="utf-8"))
    payload["live_endpoint_claimed"] = True
    write_json(report_projection, payload)

    errors = assertion.validate_phase(phase, {201})

    assert any("forbidden live/runtime/workload claim" in error for error in errors)


def test_p37_assertion_accepts_minimal_dry_run_sequence(tmp_path: Path) -> None:
    assertion = load_script("assert_200_plus_dry_run")
    phase = "P37_200_PLUS_DRY_RUN_SUPPORT"
    assertion.ROOT = tmp_path
    assertion.phase_dir = lambda current: tmp_path / "artifacts" / "phases" / current
    build_minimal_p37_fixture(tmp_path, phase, 201)

    assert assertion.validate_phase(phase, {201}) == []


def build_minimal_p37_fixture(root: Path, phase: str, target: int) -> None:
    base = root / "artifacts" / "phases" / phase
    refs = {
        "config_ref": f"artifacts/phases/{phase}/generated_configs/scale_{target}_dry_run.yaml",
        "config_validation_ref": f"artifacts/phases/{phase}/config_validation_{target}.json",
        "resource_estimate_ref": f"artifacts/phases/{phase}/resource_estimate_{target}.json",
        "plan_ref": f"artifacts/phases/{phase}/dry_run_plan_{target}.json",
        "placement_schedule_ref": f"artifacts/phases/{phase}/placement_schedule_{target}.json",
        "collision_check_ref": f"artifacts/phases/{phase}/collision_check_{target}.json",
        "artifact_schema_projection_ref": f"artifacts/phases/{phase}/artifact_schema_projection_{target}.json",
        "report_projection_ref": f"artifacts/phases/{phase}/report_projection_{target}.json",
        "no_runtime_created_proof_ref": f"artifacts/phases/{phase}/no_runtime_created_proof_{target}.json",
    }
    (root / refs["config_ref"]).parent.mkdir(parents=True, exist_ok=True)
    (root / refs["config_ref"]).write_text("runtime:\n  dry_run: true\n", encoding="utf-8")
    common = {
        "schema_version": "v1",
        "phase_id": phase,
        "status": "DRY_RUN_PASS",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "runtime_resources_created": False,
        "real_valkey_claimed": False,
        "live_endpoint_claimed": False,
        "workload_executed": False,
    }
    for key in [
        "config_validation_ref",
        "resource_estimate_ref",
        "plan_ref",
        "placement_schedule_ref",
        "collision_check_ref",
        "artifact_schema_projection_ref",
        "report_projection_ref",
    ]:
        write_json(root / refs[key], {"artifact_type": key, **common})
    proof = {
        "schema_version": "v1",
        "artifact_type": "no_runtime_created_proof",
        "phase_id": phase,
        "status": "PASS",
        "execution_mode": "dry_run",
        "runtime_resources_created": False,
        "created_resources": [],
        "before_inventory": {},
        "after_inventory": {},
    }
    write_json(root / refs["no_runtime_created_proof_ref"], proof)
    for name in [
        "phase_summary.json",
        "dry_run_targets.json",
        "resource_estimates.json",
        "placement_schedules.json",
        "report_projection_index.json",
        "quant_summary.json",
    ]:
        write_json(base / name, {"artifact_type": name, "execution_mode": "dry_run", "targets": [target], **common})
    write_json(base / "no_runtime_created_proof.json", proof)
    steps = [
        ("config_validate", refs["config_validation_ref"]),
        ("resource_estimate", refs["resource_estimate_ref"]),
        ("plan_cluster", refs["plan_ref"]),
        ("host_az_placement_schedule", refs["placement_schedule_ref"]),
        ("port_directory_collision_check", refs["collision_check_ref"]),
        ("artifact_schema_projection", refs["artifact_schema_projection_ref"]),
        ("report_projection", refs["report_projection_ref"]),
        ("no_runtime_created_proof", refs["no_runtime_created_proof_ref"]),
    ]
    write_jsonl(
        base / "dry_run_results.jsonl",
        [
            {
                **common,
                **refs,
                "dry_run": True,
                "sequence_steps": [
                    {"name": name, "status": "DRY_RUN_PASS" if name != "no_runtime_created_proof" else "PASS", "artifact_ref": ref}
                    for name, ref in steps
                ],
            }
        ],
    )
    rows = []
    for row_name in assertion_rows():
        rows.append(
            {
                "coverage_id": f"{target}.dry_run.{row_name}",
                "scale": target,
                "node_count": target,
                "category": "dry_run",
                "row_name": row_name,
                "stage_owner": phase,
                "required": True,
                "execution_mode": "dry_run",
                "status": "DRY_RUN_PASS",
                "status_reason": "test",
                "source_artifacts": [refs["config_ref"]],
                "validation_artifacts": [refs["no_runtime_created_proof_ref"]],
                "metric_refs": [],
                "cleanup_ref": refs["no_runtime_created_proof_ref"],
                "review_ref": f"artifacts/goal_loop_strict/{phase}/REVIEW.md",
                "commit_sha": "test",
            }
        )
    registry = {
        "schema_version": "v1",
        "artifact_type": "strict_coverage_registry",
        "stage_id": phase,
        "created_at": "test",
        "producer": {"name": "test", "version": "v1"},
        "source_spec_refs": ["test"],
        "summary": {},
        "rows": rows,
    }
    write_json(root / "artifacts" / "coverage" / "strict_coverage_registry.json", registry)
    write_json(base / "coverage_ledger.json", registry)


def assertion_rows() -> list[str]:
    return [
        "config_validate_dry_run",
        "resource_preflight_dry_run",
        "plan_cluster_dry_run",
        "placement_schedule_dry_run",
        "port_directory_collision_check_dry_run",
        "artifact_schema_projection_dry_run",
        "no_runtime_created_proof",
        "report_projection_dry_run",
    ]
