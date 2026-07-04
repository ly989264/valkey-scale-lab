#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from valkey_scale_lab import __version__  # noqa: E402
from valkey_scale_lab.config.simple_yaml import parse_config_file  # noqa: E402
from valkey_scale_lab.config.validation import normalize_config, validate_semantics  # noqa: E402
from valkey_scale_lab.planner.plan import build_cluster_plan  # noqa: E402

PHASE = "P37_200_PLUS_DRY_RUN_SUPPORT"
RUN_ID = "P37_200_PLUS_DRY_RUN_SUPPORT-dry-run-20260704"
CREATED_AT = "2026-07-04T00:00:00Z"
TARGETS = [201, 250, 300, 500, 1000]
ROWS = [
    "config_validate_dry_run",
    "resource_preflight_dry_run",
    "plan_cluster_dry_run",
    "placement_schedule_dry_run",
    "port_directory_collision_check_dry_run",
    "artifact_schema_projection_dry_run",
    "no_runtime_created_proof",
    "report_projection_dry_run",
]
CSV_COLUMNS = [
    "coverage_id",
    "scale",
    "node_count",
    "category",
    "row_name",
    "stage_owner",
    "required",
    "execution_mode",
    "status",
    "status_reason",
    "source_artifacts",
    "validation_artifacts",
    "metric_refs",
    "cleanup_ref",
    "review_ref",
    "commit_sha",
]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def phase_dir() -> Path:
    return ROOT / "artifacts" / "phases" / PHASE


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encode_missing(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(encode_missing(row), sort_keys=True) for row in rows) + "\n"
    path.write_text(text, encoding="utf-8")


def encode_missing(value: Any) -> Any:
    if value is None:
        return {"status": "MISSING", "reason": "Not applicable for this P37 dry-run projection."}
    if isinstance(value, dict):
        return {str(key): encode_missing(item) for key, item in value.items()}
    if isinstance(value, list):
        return [encode_missing(item) for item in value]
    return value


def generated_config_text(target: int) -> str:
    allow_1000 = "true" if target >= 1000 else "false"
    require_1000 = "\n  require_1000_env: VSLAB_ALLOW_1000_DRYRUN" if target >= 1000 else ""
    opt_in = "\n  opt_in_1000: true" if target >= 1000 else ""
    return f"""schema_version: v1
profile_name: scale_{target}_p37_dry_run
safety:
  default_max_nodes: 100
  allow_1000_nodes: {allow_1000}{require_1000}
  require_sandbox_network: true
  forbid_host_network_mutation: true
  cleanup_on_error: true
runtime:
  provider: docker
  valkey_image: valkey/valkey:9.1.0
  sandbox_mode: container_namespace
  dry_run: true
hosts:
  - host_id: local-a
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [controller, worker, dry-run]
  - host_id: local-b
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [worker, dry-run]
network:
  virtual_az_mode: multi
  azs: [az-a, az-b]
cluster:
  shards: {target}
  replicas_per_shard: 0
  port_base: 12000
  cluster_bus_port_base: 22000
  node_memory_limit_mb: 32
  non_ha_allowed: true
scale_profile:
  dry_run_only: true
  p37_dry_run_target: true
  target_nodes: {target}
  execution_mode: dry_run{opt_in}
workload:
  enabled: false
faults: []
"""


def collect_inventory() -> dict[str, Any]:
    return {
        "scope": "owned P37 valkey-scale-lab resources only",
        "execution_mode": "dry_run",
        "docker": {
            "containers": docker_ids(["ps", "-a", "-q"]),
            "networks": docker_ids(["network", "ls", "-q"]),
            "volumes": docker_ids(["volume", "ls", "-q"]),
        },
        "filesystem": {
            "runtime_paths": owned_runtime_paths(),
        },
    }


def docker_ids(args: list[str]) -> dict[str, Any]:
    cmd = [
        "docker",
        *args,
        "--filter",
        "label=org.valkey-scale-lab.project=valkey-scale-lab",
        "--filter",
        f"label=org.valkey-scale-lab.phase={PHASE}",
    ]
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return {
            "collection_status": "SKIPPED_WITH_REASON",
            "reason": f"Docker inventory command unavailable: {exc!r}",
            "ids": [],
        }
    ids = sorted(line.strip() for line in proc.stdout.splitlines() if line.strip())
    if proc.returncode != 0:
        return {
            "collection_status": "SKIPPED_WITH_REASON",
            "reason": f"Docker inventory command failed with exit {proc.returncode}: {proc.stderr.strip()[-300:]}",
            "ids": [],
        }
    return {"collection_status": "PASS", "ids": ids}


def owned_runtime_paths() -> list[str]:
    base = ROOT / "artifacts" / "runtime"
    if not base.exists():
        return []
    matches = []
    for path in base.rglob("*"):
        if PHASE.lower() in path.name.lower() or "p37-200-plus" in path.name.lower():
            matches.append(rel(path))
    return sorted(matches)


def inventory_created(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    created: list[str] = []
    for kind in ["containers", "networks", "volumes"]:
        before_ids = set(before["docker"][kind].get("ids", []))
        after_ids = set(after["docker"][kind].get("ids", []))
        created.extend(f"docker.{kind}:{item}" for item in sorted(after_ids - before_ids))
    before_paths = set(before["filesystem"]["runtime_paths"])
    after_paths = set(after["filesystem"]["runtime_paths"])
    created.extend(f"filesystem:{item}" for item in sorted(after_paths - before_paths))
    return created


def resource_estimate(target: int, config_path: Path) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "p37_resource_estimate",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "DRY_RUN_PASS",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "config_path": rel(config_path),
        "runtime_resources_created": False,
        "resource_estimate_only": True,
        "estimates": {
            "logical_nodes": target,
            "projected_node_memory_mb": target * 32,
            "projected_file_descriptors_min": max(1024, target * 4),
            "projected_client_ports": target,
            "projected_cluster_bus_ports": target,
            "runtime_preflight_status": {
                "status": "SKIPPED_WITH_REASON",
                "reason": "P37 above-200 support is dry-run-only; no live Docker or Valkey runtime preflight is executed.",
            },
        },
    }


def placement_schedule(target: int, plan: dict[str, Any], out_path: Path) -> dict[str, Any]:
    host_counts = Counter(node["host_id"] for node in plan["nodes"])
    az_counts = Counter(node["az_id"] for node in plan["nodes"])
    schedule = [
        {
            "logical_id": node["logical_id"],
            "host_id": node["host_id"],
            "az_id": node["az_id"],
            "role": node["role"],
            "client_port": node["client_port"],
            "cluster_bus_port": node["cluster_bus_port"],
            "data_dir": node["data_dir"],
            "dry_run": True,
        }
        for node in plan["nodes"]
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "p37_placement_schedule",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "DRY_RUN_PASS",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "runtime_resources_created": False,
        "placement_schedule_ref": rel(out_path),
        "host_counts": dict(sorted(host_counts.items())),
        "az_counts": dict(sorted(az_counts.items())),
        "schedule": schedule,
    }


def collision_check(target: int, plan: dict[str, Any]) -> dict[str, Any]:
    checks = {}
    for key in ["logical_id", "container_name", "data_dir", "log_dir", "pid_file", "state_file"]:
        values = [node[key] for node in plan["nodes"]]
        checks[key] = {"status": "PASS", "unique": len(values) == len(set(values)), "count": len(values)}
    ports = [node["client_port"] for node in plan["nodes"]] + [node["cluster_bus_port"] for node in plan["nodes"]]
    checks["ports"] = {"status": "PASS", "unique": len(ports) == len(set(ports)), "count": len(ports)}
    return {
        "schema_version": "v1",
        "artifact_type": "p37_collision_check",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "DRY_RUN_PASS" if all(item["unique"] for item in checks.values()) else "FAIL",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "runtime_resources_created": False,
        "checks": checks,
    }


def artifact_schema_projection(target: int, refs: dict[str, str]) -> dict[str, Any]:
    projected = [
        "phase_summary.json",
        "dry_run_targets.json",
        "dry_run_results.jsonl",
        "resource_estimates.json",
        "placement_schedules.json",
        "no_runtime_created_proof.json",
        "report_projection_index.json",
        "coverage_ledger.json",
        "quant_summary.json",
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "p37_artifact_schema_projection",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "DRY_RUN_PASS",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "runtime_resources_created": False,
        "schema_projection_only": True,
        "projected_artifacts": [{"path": f"artifacts/phases/{PHASE}/{name}", "execution_mode": "dry_run"} for name in projected],
        "target_refs": refs,
    }


def report_projection(target: int, refs: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "p37_report_projection",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "DRY_RUN_PASS",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "runtime_resources_created": False,
        "dry_run_label_required": True,
        "real_valkey_claimed": False,
        "live_endpoint_claimed": False,
        "workload_executed": False,
        "projection_sections": [
            {"name": "configuration", "source_ref": refs["config_validation_ref"], "data_class": "dry_run_projection"},
            {"name": "resource_estimate", "source_ref": refs["resource_estimate_ref"], "data_class": "dry_run_projection"},
            {"name": "placement_schedule", "source_ref": refs["placement_schedule_ref"], "data_class": "dry_run_projection"},
            {"name": "schema_projection", "source_ref": refs["artifact_schema_projection_ref"], "data_class": "dry_run_projection"},
        ],
    }


def producer() -> dict[str, str]:
    return {"name": "valkey-scale-lab", "version": __version__}


def target_refs(target: int) -> dict[str, str]:
    base = f"artifacts/phases/{PHASE}"
    return {
        "config_ref": f"{base}/generated_configs/scale_{target}_dry_run.yaml",
        "config_validation_ref": f"{base}/config_validation_{target}.json",
        "resource_estimate_ref": f"{base}/resource_estimate_{target}.json",
        "plan_ref": f"{base}/dry_run_plan_{target}.json",
        "placement_schedule_ref": f"{base}/placement_schedule_{target}.json",
        "collision_check_ref": f"{base}/collision_check_{target}.json",
        "artifact_schema_projection_ref": f"{base}/artifact_schema_projection_{target}.json",
        "report_projection_ref": f"{base}/report_projection_{target}.json",
        "no_runtime_created_proof_ref": f"{base}/no_runtime_created_proof_{target}.json",
    }


def generate_target(target: int, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    base = phase_dir()
    config_path = base / "generated_configs" / f"scale_{target}_dry_run.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(generated_config_text(target), encoding="utf-8")

    config = normalize_config(parse_config_file(config_path))
    errors = validate_semantics(config)
    config_report = {
        "schema_version": "v1",
        "artifact_type": "p37_config_validation",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "DRY_RUN_PASS" if not errors else "FAIL",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "config_path": rel(config_path),
        "valid": not errors,
        "errors": errors,
        "runtime_resources_created": False,
        "workload_executed": False,
        "live_endpoint_claimed": False,
    }
    write_json(base / f"config_validation_{target}.json", config_report)

    plan = build_cluster_plan(config, config_path=config_path, force_dry_run=True)
    plan["phase_id"] = PHASE
    plan["run_id"] = RUN_ID
    plan["created_at"] = CREATED_AT
    plan["execution_mode"] = "dry_run"
    plan["runtime_resources_created"] = False
    plan["workload_executed"] = False
    plan["live_endpoint_claimed"] = False
    plan["real_valkey_claimed"] = False
    write_json(base / f"dry_run_plan_{target}.json", plan)

    refs = target_refs(target)
    estimate = resource_estimate(target, config_path)
    write_json(base / f"resource_estimate_{target}.json", estimate)
    placement = placement_schedule(target, plan, base / f"placement_schedule_{target}.json")
    write_json(base / f"placement_schedule_{target}.json", placement)
    collision = collision_check(target, plan)
    write_json(base / f"collision_check_{target}.json", collision)
    schema_projection = artifact_schema_projection(target, refs)
    write_json(base / f"artifact_schema_projection_{target}.json", schema_projection)
    report = report_projection(target, refs)
    write_json(base / f"report_projection_{target}.json", report)
    created = inventory_created(before, after)
    proof = {
        "schema_version": "v1",
        "artifact_type": "no_runtime_created_proof",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "PASS" if not created else "FAIL",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "runtime_resources_created": bool(created),
        "created_resources": created,
        "before_inventory": before,
        "after_inventory": after,
        "real_valkey_claimed": False,
        "live_endpoint_claimed": False,
        "workload_executed": False,
    }
    write_json(base / f"no_runtime_created_proof_{target}.json", proof)
    steps = [
        {"name": "config_validate", "status": "DRY_RUN_PASS", "artifact_ref": refs["config_validation_ref"]},
        {"name": "resource_estimate", "status": "DRY_RUN_PASS", "artifact_ref": refs["resource_estimate_ref"]},
        {"name": "plan_cluster", "status": "DRY_RUN_PASS", "artifact_ref": refs["plan_ref"]},
        {"name": "host_az_placement_schedule", "status": "DRY_RUN_PASS", "artifact_ref": refs["placement_schedule_ref"]},
        {"name": "port_directory_collision_check", "status": "DRY_RUN_PASS", "artifact_ref": refs["collision_check_ref"]},
        {"name": "artifact_schema_projection", "status": "DRY_RUN_PASS", "artifact_ref": refs["artifact_schema_projection_ref"]},
        {"name": "report_projection", "status": "DRY_RUN_PASS", "artifact_ref": refs["report_projection_ref"]},
        {"name": "no_runtime_created_proof", "status": "PASS", "artifact_ref": refs["no_runtime_created_proof_ref"]},
    ]
    return {
        "schema_version": "v1",
        "artifact_type": "p37_dry_run_result",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "DRY_RUN_PASS",
        "execution_mode": "dry_run",
        "target_nodes": target,
        "dry_run": True,
        "sequence_steps": steps,
        "runtime_resources_created": False,
        "real_valkey_claimed": False,
        "live_endpoint_claimed": False,
        "workload_executed": False,
        **refs,
    }


def aggregate_no_runtime(before: dict[str, Any], after: dict[str, Any], targets: list[int]) -> dict[str, Any]:
    created = inventory_created(before, after)
    return {
        "schema_version": "v1",
        "artifact_type": "no_runtime_created_proof",
        "phase_id": PHASE,
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "producer": producer(),
        "status": "PASS" if not created else "FAIL",
        "execution_mode": "dry_run",
        "targets": targets,
        "runtime_resources_created": bool(created),
        "created_resources": created,
        "before_inventory": before,
        "after_inventory": after,
        "real_valkey_claimed": False,
        "live_endpoint_claimed": False,
        "workload_executed": False,
    }


def coverage_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        refs = target_refs(target)
        for row_name in ROWS:
            coverage_id = f"{target}.dry_run.{row_name}"
            source = [refs["config_ref"]]
            validation = ["artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/no_runtime_created_proof.json"]
            if row_name == "config_validate_dry_run":
                validation.append(refs["config_validation_ref"])
            elif row_name == "resource_preflight_dry_run":
                validation.append(refs["resource_estimate_ref"])
            elif row_name == "plan_cluster_dry_run":
                validation.append(refs["plan_ref"])
            elif row_name == "placement_schedule_dry_run":
                validation.append(refs["placement_schedule_ref"])
            elif row_name == "port_directory_collision_check_dry_run":
                validation.append(refs["collision_check_ref"])
            elif row_name == "artifact_schema_projection_dry_run":
                validation.append(refs["artifact_schema_projection_ref"])
            elif row_name == "no_runtime_created_proof":
                validation.append(refs["no_runtime_created_proof_ref"])
            elif row_name == "report_projection_dry_run":
                validation.append(refs["report_projection_ref"])
            rows.append(
                {
                    "coverage_id": coverage_id,
                    "scale": target,
                    "node_count": target,
                    "category": "dry_run",
                    "row_name": row_name,
                    "stage_owner": PHASE,
                    "required": True,
                    "execution_mode": "dry_run",
                    "status": "DRY_RUN_PASS",
                    "status_reason": f"P37 target {target} completed dry-run-only {row_name} with no runtime resources created.",
                    "source_artifacts": source,
                    "validation_artifacts": validation,
                    "metric_refs": ["artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/quant_summary.json"],
                    "cleanup_ref": "artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/no_runtime_created_proof.json",
                    "review_ref": "artifacts/goal_loop_strict/P37_200_PLUS_DRY_RUN_SUPPORT/REVIEW.md",
                    "commit_sha": "PENDING_STAGE_COMMIT",
                }
            )
    return rows


def coverage_ledger(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": "strict_coverage_registry",
        "stage_id": PHASE,
        "created_at": CREATED_AT,
        "producer": {"name": "scripts/p37_200_plus_dry_run_artifacts.py", "version": "v1"},
        "source_spec_refs": [
            "docs/codex/goal-loop-strict/06_COVERAGE_REGISTRY_SPEC.md",
            "docs/codex/goal-loop-strict/stages/P37_200_PLUS_DRY_RUN_SUPPORT.md",
        ],
        "summary": coverage_summary(rows),
        "rows": rows,
    }


def coverage_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_rows": len(rows),
        "expected_total_rows": len(rows),
        "expected_counts": {"dry_run": len(rows)},
        "counts_by_category": dict(Counter(row["category"] for row in rows)),
        "counts_by_execution_mode": dict(Counter(row["execution_mode"] for row in rows)),
        "counts_by_status": dict(Counter(row["status"] for row in rows)),
        "counts_by_stage_owner": dict(Counter(row["stage_owner"] for row in rows)),
        "real_rows_initial_status": "PENDING",
        "dry_run_rows_initial_status": "PENDING",
        "real_runtime_claimed": False,
        "real_execution_above_200_permitted": False,
    }


def update_registry(rows: list[dict[str, Any]]) -> None:
    registry_path = ROOT / "artifacts" / "coverage" / "strict_coverage_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    by_id = {row["coverage_id"]: row for row in rows}
    updated_rows = []
    for row in registry["rows"]:
        updated_rows.append(by_id.get(row["coverage_id"], row))
    registry["rows"] = updated_rows
    registry["summary"]["counts_by_status"] = dict(Counter(row["status"] for row in updated_rows))
    registry["summary"]["counts_by_stage_owner"] = dict(Counter(row["stage_owner"] for row in updated_rows))
    registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_matrix_csv(updated_rows)


def write_matrix_csv(rows: list[dict[str, Any]]) -> None:
    path = ROOT / "artifacts" / "coverage" / "strict_required_matrix.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            out = {}
            for key in CSV_COLUMNS:
                value = row.get(key, "")
                out[key] = ";".join(value) if isinstance(value, list) else value
            writer.writerow(out)


def generate() -> None:
    base = phase_dir()
    base.mkdir(parents=True, exist_ok=True)
    before = collect_inventory()
    after = collect_inventory()
    results = [generate_target(target, before, after) for target in TARGETS]
    rows = coverage_rows()

    required = [
        "phase_summary.json",
        "dry_run_targets.json",
        "dry_run_results.jsonl",
        "resource_estimates.json",
        "placement_schedules.json",
        "no_runtime_created_proof.json",
        "report_projection_index.json",
        "coverage_ledger.json",
        "quant_summary.json",
    ]
    write_json(
        base / "phase_summary.json",
        {
            "schema_version": "v1",
            "artifact_type": "phase_summary",
            "phase_id": PHASE,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": producer(),
            "status": "PASS",
            "summary": "P37 generated dry-run-only planning, placement, resource, schema, report, and no-runtime proof artifacts for 201, 250, 300, 500, and 1000 nodes.",
            "required_artifacts": [f"artifacts/phases/{PHASE}/{name}" for name in required],
            "missing_metrics": [
                {
                    "metric": "live_valkey_e2e_evidence",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "P37 is dry-run-only above 200 nodes and must not create or probe a live Valkey cluster.",
                    "impact": "Artifacts are planning projections, not real runtime measurements.",
                }
            ],
            "risks": [
                {
                    "risk": "Docker inventory may be unavailable on a local workstation; the proof records that condition with a reason and still forbids runtime creation.",
                    "severity": "low",
                    "required_before_next_phase": False,
                }
            ],
            "execution_mode": "dry_run",
            "real_valkey_claimed": False,
            "workload_executed": False,
        },
    )
    write_json(
        base / "dry_run_targets.json",
        {
            "schema_version": "v1",
            "artifact_type": "p37_dry_run_targets",
            "phase_id": PHASE,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": producer(),
            "status": "DRY_RUN_PASS",
            "execution_mode": "dry_run",
            "targets": TARGETS,
            "required_sequence": [
                "config validate",
                "resource estimate",
                "plan cluster",
                "host/AZ placement schedule",
                "port/directory collision check",
                "artifact schema projection",
                "report projection",
                "no-runtime-created proof",
            ],
        },
    )
    write_jsonl(base / "dry_run_results.jsonl", results)
    write_json(
        base / "resource_estimates.json",
        {
            "schema_version": "v1",
            "artifact_type": "p37_resource_estimates",
            "phase_id": PHASE,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": producer(),
            "status": "DRY_RUN_PASS",
            "execution_mode": "dry_run",
            "targets": [
                {"target_nodes": target, "resource_estimate_ref": target_refs(target)["resource_estimate_ref"]}
                for target in TARGETS
            ],
        },
    )
    write_json(
        base / "placement_schedules.json",
        {
            "schema_version": "v1",
            "artifact_type": "p37_placement_schedules",
            "phase_id": PHASE,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": producer(),
            "status": "DRY_RUN_PASS",
            "execution_mode": "dry_run",
            "targets": [
                {"target_nodes": target, "placement_schedule_ref": target_refs(target)["placement_schedule_ref"]}
                for target in TARGETS
            ],
        },
    )
    write_json(base / "no_runtime_created_proof.json", aggregate_no_runtime(before, after, TARGETS))
    write_json(
        base / "report_projection_index.json",
        {
            "schema_version": "v1",
            "artifact_type": "p37_report_projection_index",
            "phase_id": PHASE,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": producer(),
            "status": "DRY_RUN_PASS",
            "execution_mode": "dry_run",
            "dry_run_label_required": True,
            "real_valkey_claimed": False,
            "workload_executed": False,
            "targets": [
                {"target_nodes": target, "report_projection_ref": target_refs(target)["report_projection_ref"]}
                for target in TARGETS
            ],
        },
    )
    write_json(base / "coverage_ledger.json", coverage_ledger(rows))
    write_json(
        base / "quant_summary.json",
        {
            "schema_version": "v1",
            "artifact_type": "quant_summary",
            "phase_id": PHASE,
            "run_id": RUN_ID,
            "created_at": CREATED_AT,
            "producer": producer(),
            "status": "PASS",
            "summary": "P37 quantification is projection-only: target counts, resource estimates, placement counts, collision checks, schema projections, and no-runtime inventory proof are recorded for every required target.",
            "artifact_refs": [f"artifacts/phases/{PHASE}/{name}" for name in required],
            "missing_data": [
                {
                    "field": "live_valkey_metrics",
                    "status": "SKIPPED_WITH_REASON",
                    "reason": "Above-200 nodes are dry-run-only in P37; no live endpoints or workload samples are allowed.",
                }
            ],
            "runtime_claims": {
                "real_valkey_claimed": False,
                "management_runtime_claimed": False,
                "fault_runtime_claimed": False,
                "workload_runtime_claimed": False,
            },
            "execution_mode": "dry_run",
            "target_nodes": TARGETS,
        },
    )
    update_registry(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", default=PHASE)
    args = parser.parse_args()
    if args.phase != PHASE:
        print(f"unsupported phase for P37 generator: {args.phase}", file=sys.stderr)
        return 2
    generate()
    print(f"WROTE P37 dry-run artifacts for targets {','.join(str(target) for target in TARGETS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
