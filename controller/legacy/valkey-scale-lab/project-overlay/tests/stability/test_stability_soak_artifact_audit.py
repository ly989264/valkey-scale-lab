from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_stability_soak_metrics.py"

spec = importlib.util.spec_from_file_location("audit_stability_soak_metrics", SCRIPT)
audit_stability_soak_metrics = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit_stability_soak_metrics)


def copy_audit_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for path in [
        "schemas/artifact/stability_report.schema.json",
        "schemas/artifact/stability_timeseries_sample.schema.json",
        "schemas/artifact/valkey_e2e_evidence.schema.json",
        "artifacts/loop_engineering/stages/L09_STABILITY_SOAK_MULTI_STAGE_METRICS/resource_aware_profile_deferral.json",
        "artifacts/phases/P11_STABILITY_SOAK",
        "artifacts/phases/P12_SCALE_LADDER_10_30/resource_preflight_30.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_50.json",
        "artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_100.json",
    ]:
        source = REPO_ROOT / path
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return root


def test_stability_soak_audit_builds_required_profiles() -> None:
    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(REPO_ROOT, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "PASS"
    assert report["summary"]["required_node_counts"] == [6, 30, 50, 100]
    assert report["summary"]["profile_count"] == 4
    assert {profile["node_count"] for profile in report["profiles"]} == {6, 30, 50, 100}
    assert report["p14_boundary"]["real_valkey_coverage"] is False
    large = [profile for profile in report["profiles"] if profile["node_count"] in {30, 50, 100}]
    assert all(profile["status"] == "SKIPPED_WITH_REASON" for profile in large)
    assert all(profile["real_valkey_coverage"] is False for profile in large)


def test_stability_soak_audit_rejects_missing_window(tmp_path: Path) -> None:
    root = copy_audit_fixture(tmp_path)
    report_path = root / "artifacts/phases/P11_STABILITY_SOAK/stability_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["summary"]["windows"].pop("fault", None)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(root, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "stability_report_schema" for finding in report["findings"])


def test_stability_soak_audit_rejects_unordered_latency(tmp_path: Path) -> None:
    root = copy_audit_fixture(tmp_path)
    report_path = root / "artifacts/phases/P11_STABILITY_SOAK/stability_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["summary"]["windows"]["steady"]["workload"]["latency_ms"]["p99"] = -1
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(root, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "latency_percentile_order" for finding in report["findings"])


def test_stability_soak_audit_rejects_missing_measured_latency_percentile(tmp_path: Path) -> None:
    root = copy_audit_fixture(tmp_path)
    report_path = root / "artifacts/phases/P11_STABILITY_SOAK/stability_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["summary"]["windows"]["steady"]["workload"]["latency_ms"].pop("p95", None)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(root, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "stability_report_schema" for finding in report["findings"])
    assert any(finding["category"] == "missing_window_metric" for finding in report["findings"])


def test_stability_soak_audit_reports_missing_resource_preflight(tmp_path: Path) -> None:
    root = copy_audit_fixture(tmp_path)
    preflight_path = root / "artifacts/phases/P13_SCALE_LADDER_50_100/resource_preflight_100.json"
    preflight_path.unlink()

    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(root, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "resource_preflight_missing" for finding in report["findings"])
    profile = next(item for item in report["profiles"] if item["node_count"] == 100)
    assert profile["status"] == "SKIPPED_WITH_REASON"
    assert profile["real_valkey_coverage"] is False
    assert profile["source_hashes"][0]["exists"] is False


def test_stability_soak_audit_rejects_wrong_valkey_version(tmp_path: Path) -> None:
    root = copy_audit_fixture(tmp_path)
    evidence_path = root / "artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["valkey_versions"] = ["8.0.0"]
    evidence_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(root, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "real_evidence_valkey_version" for finding in report["findings"])
    profile = next(item for item in report["profiles"] if item["node_count"] == 6)
    assert profile["real_valkey_coverage"] is False


def test_stability_soak_audit_rejects_failed_cluster_state(tmp_path: Path) -> None:
    root = copy_audit_fixture(tmp_path)
    evidence_path = root / "artifacts/phases/P11_STABILITY_SOAK/valkey_e2e_evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["cluster_state_observed"] = "fail"
    evidence_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(root, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "real_evidence_cluster_state" for finding in report["findings"])


def test_stability_soak_audit_requires_deferral_when_preflight_passes(tmp_path: Path) -> None:
    root = copy_audit_fixture(tmp_path)
    (root / "artifacts/loop_engineering/stages/L09_STABILITY_SOAK_MULTI_STAGE_METRICS/resource_aware_profile_deferral.json").unlink()

    auditor = audit_stability_soak_metrics.StabilitySoakAuditor(root, [6, 30, 50, 100])
    report = auditor.build()

    assert report["status"] == "FAIL"
    assert any(finding["category"] == "resource_preflight_passed_without_measurement" for finding in report["findings"])
