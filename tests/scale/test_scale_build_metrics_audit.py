from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_scale_build_metrics.py"
spec = importlib.util.spec_from_file_location("audit_scale_build_metrics", SCRIPT)
audit_scale_build_metrics = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit_scale_build_metrics)


def copy_repo_fixture(root: Path) -> None:
    paths = [
        "codex/phase_manifest.json",
        "schemas/artifact",
        "artifacts/phases/P12_SCALE_LADDER_10_30",
        "artifacts/phases/P13_SCALE_LADDER_50_100",
        "artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json",
    ]
    for rel_path in paths:
        src = REPO_ROOT / rel_path
        dst = root / rel_path
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def categories(report: dict) -> set[str]:
    return {finding["category"] for finding in report["findings"]}


def test_current_scale_build_metrics_audit_passes_with_explicit_30_node_gaps() -> None:
    report = audit_scale_build_metrics.build_report(REPO_ROOT)

    assert report["status"] == "PASS"
    assert report["summary"]["canonical_node_counts"] == [30, 50, 100]
    assert report["summary"]["real_valkey_rung_count"] == 3
    assert report["summary"]["blocking_findings_count"] == 0
    assert report["p14_boundary"]["real_valkey_coverage"] is False

    scale_30 = next(rung for rung in report["canonical_rungs"] if rung["node_count"] == 30)
    missing = [metric for metric in scale_30["metric_records"] if metric["status"] == "MISSING"]
    assert missing
    assert all(metric["reason"] for metric in missing)
    assert any(metric["name"] == "process_startup.nodehost_start_seconds" for metric in missing)

    scale_50 = next(rung for rung in report["canonical_rungs"] if rung["node_count"] == 50)
    assert all(metric["status"] == "MEASURED" for metric in scale_50["metric_records"])


def test_failed_preflight_blocks_scale_build_audit(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    preflight_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_50.json"
    preflight = read_json(preflight_path)
    preflight["status"] = "FAIL"
    preflight["can_run"] = False
    write_json(preflight_path, preflight)

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "resource_preflight_blocked" in categories(report)


def test_bad_real_evidence_data_path_blocks_scale_build_audit(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    evidence_path = tmp_path / "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence_30.json"
    evidence = read_json(evidence_path)
    evidence["data_path_result"] = "SKIPPED_WITH_REASON"
    write_json(evidence_path, evidence)

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "invalid_real_evidence" in categories(report)


def test_missing_p13_timing_metric_blocks_50_100(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    timing_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json"
    timing = read_json(timing_path)
    timing["timings"] = [entry for entry in timing["timings"] if entry.get("name") != "primary_cluster_create"]
    write_json(timing_path, timing)

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "missing_required_scale_build_metric" in categories(report)


def test_cleanup_residue_blocks_scale_build_audit(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    cleanup_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_100.json"
    cleanup = read_json(cleanup_path)
    cleanup["resources_remaining"] = [{"kind": "container", "id": "leftover"}]
    write_json(cleanup_path, cleanup)

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "cleanup_residue" in categories(report)


def test_p14_real_evidence_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    p14_dir = tmp_path / "artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN"
    p14_dir.mkdir(parents=True)
    (p14_dir / "valkey_e2e_evidence_1000.json").write_text("{}\n", encoding="utf-8")

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "p14_real_artifact_present" in categories(report)


def test_p14_real_scale_rung_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    p14_dir = tmp_path / "artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN"
    p14_dir.mkdir(parents=True)
    write_json(
        p14_dir / "scale_rung_1000.json",
        {
            "artifact_type": "scale_rung_summary",
            "status": "PASS",
            "node_count": 1000,
            "scenario": "scale_1000",
            "real_valkey": True
        },
    )

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "p14_real_artifact_present" in categories(report)


def test_p14_scale_ladder_real_rung_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    p14_dir = tmp_path / "artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN"
    p14_dir.mkdir(parents=True)
    write_json(
        p14_dir / "scale_ladder_report.json",
        {
            "artifact_type": "scale_ladder_report",
            "status": "PASS",
            "rungs": [
                {
                    "node_count": 1000,
                    "scenario": "scale_1000",
                    "evidence_path": "artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN/valkey_e2e_evidence_1000.json"
                }
            ]
        },
    )

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "p14_real_artifact_present" in categories(report)


def test_p14_dryrun_plan_is_allowed_metadata(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    p14_dir = tmp_path / "artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN"
    p14_dir.mkdir(parents=True)
    write_json(
        p14_dir / "scale_1000_dryrun_plan.json",
        {
            "artifact_type": "cluster_plan",
            "status": "PASS",
            "node_count": 1000,
            "scenario": "scale_1000_dryrun",
            "constraints": {
                "dry_run": True,
                "no_execution": True
            }
        },
    )

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "PASS"
    assert "p14_real_artifact_present" not in categories(report)
    assert report["p14_boundary"]["real_valkey_coverage"] is False


def test_p14_dryrun_resource_preflight_is_allowed_metadata(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    p14_dir = tmp_path / "artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN"
    p14_dir.mkdir(parents=True)
    write_json(
        p14_dir / "resource_preflight_1000.json",
        {
            "artifact_type": "resource_preflight",
            "status": "PASS",
            "node_count": 1000,
            "can_run": True,
            "dry_run": True,
            "real_valkey": False,
            "checks": []
        },
    )

    report = audit_scale_build_metrics.build_report(tmp_path)

    assert report["status"] == "PASS"
    assert "p14_real_artifact_present" not in categories(report)
    assert report["p14_boundary"]["real_valkey_coverage"] is False
