from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_p13_p14_scale.py"
spec = importlib.util.spec_from_file_location("audit_p13_p14_scale", SCRIPT)
audit_p13_p14_scale = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit_p13_p14_scale)


def copy_repo_fixture(root: Path) -> None:
    paths = [
        "codex/phase_manifest.json",
        "templates/configs/scale_1000_dryrun_optin.yaml",
        "schemas/artifact",
        "artifacts/phases/P13_SCALE_LADDER_50_100",
        "artifacts/phases/P13O_CLUSTER_CREATE_AB",
        "artifacts/phases/P13O_REPLICA_REPLICATE_BREAKDOWN",
        "artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json",
        "artifacts/gates/P13_SCALE_LADDER_50_100",
        "audit/P13_SCALE_LADDER_50_100",
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


def finding_categories(report: dict) -> set[str]:
    return {finding["category"] for finding in report["findings"]}


def test_current_p13_p14_scale_audit_passes_with_historical_findings() -> None:
    report = audit_p13_p14_scale.build_report(REPO_ROOT)

    assert report["status"] == "PASS"
    assert report["summary"]["blocking_findings_count"] == 0
    assert report["summary"]["p13_canonical_node_counts"] == [50, 100]
    assert report["summary"]["p13_real_evidence_count"] == 2
    assert [rung["node_count"] for rung in report["p13"]["rungs"]] == [50, 100]
    assert report["p14_boundary"]["status"] == "SKIPPED_WITH_REASON"
    assert report["p14_boundary"]["real_evidence_count"] == 0
    assert report["p14_boundary"]["dry_run_only"] is True
    assert report["p14_boundary"]["max_nodes"] == 1000

    historical = [finding for finding in report["findings"] if finding["classification"] == "historical"]
    assert {finding["category"] for finding in historical} == {
        "p13_historical_manifest_drift",
        "p13_historical_command_drift",
    }
    assert all(finding["blocking"] is False for finding in historical)

    p13o = report["p13"]["optimization_artifacts"]
    assert p13o["classified_separately"] is True
    assert any("P13O_CLUSTER_CREATE_AB" in path for path in p13o["paths"])
    assert any("P13O_REPLICA_REPLICATE_BREAKDOWN" in path for path in p13o["paths"])
    assert p13o["canonical_evidence_paths"] == [
        "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_100.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json",
    ]


def test_invalid_p13_evidence_node_count_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    evidence_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json"
    evidence = read_json(evidence_path)
    evidence["nodes_observed"] = 49
    write_json(evidence_path, evidence)

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "invalid_p13_real_evidence" in finding_categories(report)


def test_missing_p13_timing_category_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    timing_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json"
    timing = read_json(timing_path)
    timing["timings"] = [entry for entry in timing["timings"] if entry.get("name") != "primary_cluster_create"]
    write_json(timing_path, timing)

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "missing_timing_category" in finding_categories(report)


def test_invalid_p13_timing_metadata_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    timing_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_scale_50.json"
    timing = read_json(timing_path)
    timing["status"] = "FAIL"
    timing["node_count"] = 999
    timing["scenario"] = "scale_100"
    write_json(timing_path, timing)

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "invalid_timing_artifact" in finding_categories(report)


def test_wrong_p13_cleanup_reference_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    evidence_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/valkey_e2e_evidence_50.json"
    evidence = read_json(evidence_path)
    evidence["cleanup"]["path"] = "artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_50.json"
    write_json(evidence_path, evidence)

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "p13_cross_artifact_mismatch" in finding_categories(report)


def test_cleanup_residue_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    cleanup_path = tmp_path / "artifacts/phases/P13_SCALE_LADDER_50_100/cleanup_report_scale_50.json"
    cleanup = read_json(cleanup_path)
    cleanup["resources_remaining"] = [{"kind": "container", "id": "leftover-scale-50"}]
    write_json(cleanup_path, cleanup)

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "cleanup_residue" in finding_categories(report)


def test_p14_real_evidence_artifact_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    p14_dir = tmp_path / "artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN"
    p14_dir.mkdir(parents=True)
    (p14_dir / "valkey_e2e_evidence_fake.json").write_text("{}\n", encoding="utf-8")

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "p14_real_evidence_present" in finding_categories(report)


def test_p14_manifest_max_nodes_drift_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    manifest_path = tmp_path / "codex/phase_manifest.json"
    manifest = read_json(manifest_path)
    for phase in manifest["phases"]:
        if phase["id"] == "P14_SCALE_1000_OPTIN_DRYRUN":
            phase["max_nodes"] = 100
            break
    write_json(manifest_path, manifest)

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "p14_boundary_violation" in finding_categories(report)


def test_missing_p14_optin_config_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    (tmp_path / "templates/configs/scale_1000_dryrun_optin.yaml").unlink()

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "p14_config_missing" in finding_categories(report)


def test_invalid_1000_dryrun_plan_is_blocking(tmp_path: Path) -> None:
    copy_repo_fixture(tmp_path)
    plan_path = tmp_path / "artifacts/phases/P02_PLANNER/scale_1000_dryrun_plan.json"
    plan = read_json(plan_path)
    plan["constraints"]["dry_run"] = False
    write_json(plan_path, plan)

    report = audit_p13_p14_scale.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "invalid_1000_dryrun_plan" in finding_categories(report)
