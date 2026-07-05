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


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")


def test_final_closeout_artifact_ref_fails_closed_on_missing_and_hash_mismatch(tmp_path: Path) -> None:
    closeout = load_script("assert_final_strict_closeout")
    closeout.ROOT = tmp_path
    existing = tmp_path / "artifact.json"
    existing.write_text("{}\n", encoding="utf-8")
    errors: list[str] = []

    closeout.validate_artifact_ref({"path": "missing.json", "sha256": "abc"}, errors, "missing")
    closeout.validate_artifact_ref({"path": "artifact.json", "sha256": "bad"}, errors, "bad_hash")

    assert any("artifact missing" in error for error in errors)
    assert any("sha256 mismatch" in error for error in errors)


def test_final_closeout_registry_rejects_dry_run_without_no_runtime_proof(tmp_path: Path) -> None:
    closeout = load_script("assert_final_strict_closeout")
    closeout.ROOT = tmp_path
    registry = {
        "rows": [
            {
                "coverage_id": "201.dry_run.no_runtime_created_proof",
                "scale": 201,
                "node_count": 201,
                "category": "dry_run",
                "row_name": "no_runtime_created_proof",
                "stage_owner": "P37_200_PLUS_DRY_RUN_SUPPORT",
                "required": True,
                "execution_mode": "dry_run",
                "status": "DRY_RUN_PASS",
                "status_reason": "fixture",
                "source_artifacts": [],
                "validation_artifacts": ["artifacts/phases/P37_200_PLUS_DRY_RUN_SUPPORT/report_projection_201.json"],
                "metric_refs": [],
                "cleanup_ref": "",
                "review_ref": "artifacts/goal_loop_strict/P37_200_PLUS_DRY_RUN_SUPPORT/REVIEW.md",
                "commit_sha": "fixture",
            }
        ]
    }
    write_json(tmp_path / "artifacts" / "coverage" / "strict_coverage_registry.json", registry)
    write_json(tmp_path / "artifacts" / "phases" / "P37_200_PLUS_DRY_RUN_SUPPORT" / "report_projection_201.json", {"status": "PASS"})
    (tmp_path / "artifacts" / "goal_loop_strict" / "P37_200_PLUS_DRY_RUN_SUPPORT").mkdir(parents=True)
    (tmp_path / "artifacts" / "goal_loop_strict" / "P37_200_PLUS_DRY_RUN_SUPPORT" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")
    errors: list[str] = []

    closeout.validate_coverage_registry(errors)

    assert any("requires no-runtime proof" in error for error in errors)


def test_p40_provenance_rejects_raw_log_sources_and_bad_hash(tmp_path: Path) -> None:
    provenance_script = load_script("assert_analysis_provenance")
    provenance_script.ROOT = tmp_path
    source = tmp_path / "codex" / "phase_manifest.json"
    source.parent.mkdir(parents=True)
    source.write_text("{}\n", encoding="utf-8")
    raw_log = tmp_path / "artifacts" / "gates" / "P39_VISUAL_REPORT_QUALITY_GATE" / "stdout" / "report_quality.log"
    raw_log.parent.mkdir(parents=True)
    raw_log.write_text("PASS\n", encoding="utf-8")
    errors: list[str] = []
    provenance = {
        "analysis_only": True,
        "audit_only": True,
        "runtime_started": False,
        "docker_started": False,
        "valkey_gate_started": False,
        "fault_injection_started": False,
        "workload_started": False,
        "unvalidated_logs_read": False,
        "raw_log_sources_present": False,
        "invented_values_present": False,
        "source_artifacts": [
            {"path": "codex/phase_manifest.json", "sha256": "bad"},
            {"path": "artifacts/gates/P39_VISUAL_REPORT_QUALITY_GATE/stdout/report_quality.log", "sha256": provenance_script.sha256_file(raw_log)},
        ],
        "output_artifacts": [],
    }

    provenance_script.assert_p40_provenance(tmp_path / "artifacts" / "phases" / "P40_STRICT_FINAL_AUDIT_CLOSEOUT", provenance, errors)

    assert any("sha256 mismatch" in error for error in errors)
    assert any("raw log/runtime stream" in error for error in errors)
