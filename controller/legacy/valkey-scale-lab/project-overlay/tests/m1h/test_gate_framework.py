from __future__ import annotations

import json
import sys
from pathlib import Path

M1H = Path(__file__).resolve().parents[2] / "scripts" / "m1h"
sys.path.insert(0, str(M1H))

from assert_evidence_taxonomy import validate_manifest
from assert_no_fixture_fallback import scan_fixture_fallbacks
from assert_no_legacy_m1_pass import validate_current_acceptance, validate_no_legacy_pass
from assert_no_simulated_subagents import scan_stage_artifacts
from assert_setup_core_metrics import evaluate_setup_core_metrics
from assert_final_milestone1_hardened import evaluate_final
from assert_stage_exit import H00_REQUIRED_GATE_RESULTS, H01_REQUIRED_GATE_RESULTS, H02_REQUIRED_GATE_RESULTS, H03_REQUIRED_GATE_RESULTS, H04_REQUIRED_GATE_RESULTS, H05_REQUIRED_GATE_RESULTS, H06_REQUIRED_GATE_RESULTS, H07_REQUIRED_GATE_RESULTS, H08_REQUIRED_GATE_RESULTS, REQUIRED_SCRIPTS, validate_stage_exit
from assert_fault_timeline_real import evaluate_fault_timeline_real
from assert_system_metrics_real_windows import evaluate_system_metrics_real_windows
from build_acceptance_reset import build_acceptance_reset, validate_acceptance_report
from capability_gate import evaluate_capability
from assert_command_audit_real import evaluate_command_audit_real
from assert_management_exact_scale import evaluate_management_exact_scale
from assert_workload_benchmark_strength import evaluate_workload_benchmark_strength
from common import gate_result_path, write_gate_result, write_json
from manifest import C06_SETUP_CORE_METRICS, C07_REQUIRED_COMMAND_KINDS, H05_REQUIRED_MANAGEMENT_OPERATIONS, H06_REQUIRED_METRIC_ROW_COUNT, H06_REQUIRED_WORKLOAD_METRICS, H06_REQUIRED_WORKLOAD_PROFILES, H06_REQUIRED_WORKLOAD_WINDOWS, H07_REQUIRED_FAULT_TYPES, H07_REQUIRED_TIMELINE_EVENTS, H07_REQUIRED_TIMELINE_METRICS, H08_HIGH_VALUE_METRIC_GROUPS, REQUIRED_CLAIMS, build_manifest, claim_id


def test_write_gate_result_shape(tmp_path: Path) -> None:
    result = write_gate_result(
        root=tmp_path,
        stage_id="H00_BOOTSTRAP_HARD_GATES",
        gate_name="sample_gate",
        status="PASS",
        inputs=["input.json"],
    )
    path = gate_result_path(tmp_path, "H00_BOOTSTRAP_HARD_GATES", "sample_gate")
    assert path.exists()
    assert result["schema_version"] == "v1"
    assert result["artifact_type"] == "m1h_gate_result"
    assert result["status"] == "PASS"
    assert isinstance(result["source_commit"], str)


def test_build_manifest_emits_all_required_claims_blocked_not_false_pass(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    claim_ids = {claim["claim_id"] for claim in manifest["claims"]}
    assert claim_ids == {claim_id(capability, scale) for capability, scale in REQUIRED_CLAIMS}
    assert all(claim["status"] == "BLOCKED_WITH_REASON" for claim in manifest["claims"])
    assert all(claim["evidence_kind"] == "BLOCKED_WITH_REASON" for claim in manifest["claims"])


def test_taxonomy_rejects_required_fixture_pass(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "x.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}", encoding="utf-8")
    manifest = {
        "schema_version": "v1",
        "artifact_type": "m1h_evidence_manifest",
        "claims": [
            {
                "claim_id": "management_matrix.real_exact.50",
                "stage_id": "M1H",
                "capability": "management_matrix",
                "scale": 50,
                "evidence_kind": "FIXTURE_ONLY",
                "required_for_milestone_pass": True,
                "source_artifacts": ["tests/fixtures/x.json"],
                "semantic_checks": {"operation_semantics_present": True},
                "status": "PASS",
            }
        ],
    }
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    violations, _blocked = validate_manifest(tmp_path, path)
    codes = {item["code"] for item in violations}
    assert "required_pass_disallowed_kind" in codes


def test_fixture_fallback_scanner_reports_file_and_line(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "assert_milestone1_acceptance.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        "\n".join(
            [
                "def check(root):",
                "    matrix = {}",
                "    if not matrix:",
                "        matrix = root / 'tests/fixtures/management_matrix/success.json'",
                "    return 'PASS' if matrix else 'FAIL'",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "m1h").mkdir(parents=True)
    violations = scan_fixture_fallbacks(tmp_path)
    assert violations
    assert violations[0]["path"] == "scripts/assert_milestone1_acceptance.py"
    assert violations[0]["line"] == 4


def test_legacy_pass_gate_rejects_nonpromotable_required_pass(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    acceptance_path = tmp_path / "acceptance.json"
    write_json(
        manifest_path,
        {
            "claims": [
                {
                    "claim_id": "fault_timeline.real_exact.50",
                    "required_for_milestone_pass": True,
                    "evidence_kind": "LEGACY_EVIDENCE_ONLY",
                    "status": "PASS",
                }
            ]
        },
    )
    write_json(acceptance_path, _minimal_acceptance_reset(tmp_path, blocked_reason="blocked"))
    violations, _blocked, _extra = validate_no_legacy_pass(manifest_path, acceptance_path)
    assert "legacy_or_nonpromotable_pass" in {item["code"] for item in violations}


def test_acceptance_reset_blocks_all_claims_from_manifest(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest_path = tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json"
    write_json(manifest_path, manifest)
    report, violations = build_acceptance_reset(
        tmp_path,
        manifest_path,
        stage_id="H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET",
    )
    assert not violations
    assert report["artifact_type"] == "milestone1_acceptance_reset"
    assert report["hardening_loop_status"] == "PASS"
    assert report["milestone1_status"] == "BLOCKED_WITH_REASON"
    assert report["false_pass_prevented"] is True
    assert report["required_claim_count"] == len(REQUIRED_CLAIMS)
    assert report["passed_claim_count"] == 0
    assert report["blocked_claim_count"] == len(REQUIRED_CLAIMS)
    assert all(claim["acceptance_status"] == "BLOCKED_WITH_REASON" for claim in report["claims"])
    assert all(claim["reason"] for claim in report["claims"])


def test_final_hardened_gate_passes_honest_blocked_acceptance(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest_path = tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json"
    out_path = tmp_path / "runs" / "m1-hardening" / "H02_ACCEPTANCE_GATE_FAIL_CLOSED" / "artifacts" / "milestone1_acceptance_report.json"
    write_json(manifest_path, manifest)
    status, violations, blocked, extra = evaluate_final(
        tmp_path,
        manifest_path,
        out_path,
        stage_id="H02_ACCEPTANCE_GATE_FAIL_CLOSED",
        historical_acceptance_report=None,
    )
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert status == "PASS"
    assert not violations
    assert blocked
    assert extra["hardening_loop_status"] == "PASS"
    assert report["artifact_type"] == "milestone1_acceptance_report"
    assert report["milestone1_status"] == "BLOCKED_WITH_REASON"
    assert report["passed_claim_count"] == 0
    assert report["blocked_claim_count"] == len(REQUIRED_CLAIMS)


def test_acceptance_reset_rejects_fixture_or_legacy_pass_count(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["claims"][0].update(
        {
            "status": "PASS",
            "evidence_kind": "FIXTURE_ONLY",
            "source_artifacts": ["tests/fixtures/example.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True},
        }
    )
    manifest["claims"][1].update(
        {
            "status": "PASS",
            "evidence_kind": "LEGACY_EVIDENCE_ONLY",
            "source_artifacts": ["artifacts/phases/legacy.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True},
        }
    )
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    report, violations = build_acceptance_reset(tmp_path, manifest_path, stage_id="H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET")
    assert report["passed_claim_count"] == 0
    assert report["failed_claim_count"] == 2
    assert "nonpromotable_required_pass" in {item["code"] for item in violations}


def test_acceptance_rejects_pass_without_exact_scale_and_required_semantics(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    manifest["claims"][0].update(
        {
            "status": "PASS",
            "evidence_kind": "REAL_EXACT_SCALE",
            "source_artifacts": ["artifacts/phases/P12_SCALE_LADDER_10_30/setup_telemetry.json"],
            "semantic_checks": {
                "m1_format_fields_complete": True,
                "hardening_stage_accepted": True,
                "exact_scale_observed": False,
                "real_valkey_verified": True,
                "valkey_9_1_verified": True,
                "setup_core_metrics_numeric": "SKIPPED_WITH_REASON",
            },
        }
    )
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    report, violations = build_acceptance_reset(tmp_path, manifest_path, stage_id="H02_ACCEPTANCE_GATE_FAIL_CLOSED", artifact_type="milestone1_acceptance_report")
    assert report["passed_claim_count"] == 0
    assert report["failed_claim_count"] == 1
    details = [item.get("details", {}) for item in violations if item["code"] == "required_pass_failed_semantics"]
    assert any(item.get("check") == "exact_scale_observed" for item in details)
    assert any(item.get("check") == "setup_core_metrics_numeric" for item in details)


def test_current_acceptance_rejects_fixture_backed_pass(tmp_path: Path) -> None:
    report = _minimal_acceptance_reset(tmp_path, blocked_reason="blocked")
    first = report["claims"][0]
    first.update(
        {
            "acceptance_status": "PASS",
            "evidence_kind": "REAL_EXACT_SCALE",
            "source_artifacts": ["tests/fixtures/unsafe.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True},
        }
    )
    report["passed_claim_count"] = 1
    report["blocked_claim_count"] = len(REQUIRED_CLAIMS) - 1
    path = tmp_path / "acceptance.json"
    violations, _blocked = validate_current_acceptance(report, path)
    assert "acceptance_fixture_pass" in {item["code"] for item in violations}


def test_c03_acceptance_validator_rejects_false_milestone_passes(tmp_path: Path) -> None:
    for bad_kind in ["LEGACY_EVIDENCE_ONLY", "FIXTURE_ONLY", "DRY_RUN_ONLY", "REAL_SMALL_SMOKE", "INVALID", "BLOCKED_WITH_REASON"]:
        report = _minimal_acceptance_reset(tmp_path, blocked_reason="blocked", stage_id="H02_ACCEPTANCE_GATE_FAIL_CLOSED")
        first = report["claims"][0]
        first.update(
            {
                "acceptance_status": "PASS",
                "source_status": "PASS",
                "evidence_kind": bad_kind,
                "source_artifacts": ["artifacts/phases/x.json"],
                "semantic_checks": _passing_semantic_checks(str(first["claim_id"])),
            }
        )
        report["milestone1_status"] = "PASS"
        report["false_pass_prevented"] = False
        report["passed_claim_count"] = 1
        report["blocked_claim_count"] = len(REQUIRED_CLAIMS) - 1
        violations, _blocked = validate_acceptance_report(
            tmp_path,
            report,
            report_path=tmp_path / f"{bad_kind}.json",
            expected_stage_id="H02_ACCEPTANCE_GATE_FAIL_CLOSED",
        )
        codes = {item["code"] for item in violations}
        assert "acceptance_nonpromotable_pass" in codes
        assert "acceptance_false_pass" in codes


def test_historical_m1_pass_is_allowed_only_when_superseded(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    acceptance_path = tmp_path / "acceptance.json"
    historical_path = tmp_path / "runs" / "m1-s09-local" / "artifacts" / "goal_loop" / "M1-S09" / "milestone1_acceptance_report.json"
    write_json(manifest_path, build_manifest(tmp_path))
    reset = _minimal_acceptance_reset(tmp_path, blocked_reason="blocked")
    reset["supersedes"] = [historical_path.as_posix()]
    write_json(acceptance_path, reset)
    write_json(
        historical_path,
        {
            "milestone1_status": "PASS",
            "source_artifacts": [{"path": "tests/fixtures/unsafe.json"}],
            "heavy_real_rungs": [{"status": "PASS", "metrics": "SKIPPED_WITH_REASON", "report": "SKIPPED_WITH_REASON"}],
        },
    )
    violations, _blocked, extra = validate_no_legacy_pass(manifest_path, acceptance_path, historical_acceptance_path=historical_path)
    assert not violations
    assert extra["superseded_inputs"][0]["path"] == historical_path.as_posix()

    reset.pop("supersedes")
    write_json(acceptance_path, reset)
    violations, _blocked, _extra = validate_no_legacy_pass(manifest_path, acceptance_path, historical_acceptance_path=historical_path)
    assert "legacy_acceptance_fixture_pass" in {item["code"] for item in violations}


def test_current_acceptance_rejects_missing_blocked_reason(tmp_path: Path) -> None:
    report = _minimal_acceptance_reset(tmp_path, blocked_reason="blocked")
    report["claims"][0]["reason"] = ""
    violations, _blocked = validate_current_acceptance(report, tmp_path / "acceptance.json")
    assert "acceptance_blocked_reason_missing" in {item["code"] for item in violations}


def test_no_simulated_subagent_valid_and_forbidden_paths(tmp_path: Path) -> None:
    stage = tmp_path / "runs" / "m1-hardening" / "H00_BOOTSTRAP_HARD_GATES"
    (stage / "agents").mkdir(parents=True)
    (stage / "handoff").mkdir()
    valid = "role: design\nagent_invocation: real_subagent\nstage_id: H00_BOOTSTRAP_HARD_GATES\nsource_commit_before: abc\n"
    (stage / "agents" / "design.md").write_text(valid, encoding="utf-8")
    (stage / "handoff" / "DESIGN_BRIEF.md").write_text(valid, encoding="utf-8")
    violations, blocked = scan_stage_artifacts(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert not violations
    assert not blocked
    (stage / "agents" / "worker.md").write_text(
        "role: worker\nagent_invocation: real_subagent\nstage_id: H00_BOOTSTRAP_HARD_GATES\nsource_commit_before: abc\nsimulated worker subagent\n",
        encoding="utf-8",
    )
    violations, _blocked = scan_stage_artifacts(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert any(item["code"] == "forbidden_subagent_phrase" and item["line"] == 5 for item in violations)


def test_stage_exit_blocks_missing_artifacts_and_passes_complete_stage(tmp_path: Path) -> None:
    violations, blocked = validate_stage_exit(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert violations
    assert blocked
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", {"claims": []})
    for gate in H00_REQUIRED_GATE_RESULTS:
        write_json(
            tmp_path / "runs" / "m1-hardening" / "H00_BOOTSTRAP_HARD_GATES" / "artifacts" / "gates" / f"{gate}.json",
            {
                "schema_version": "v1",
                "artifact_type": "m1h_gate_result",
                "stage_id": "H00_BOOTSTRAP_HARD_GATES",
                "gate_name": gate,
                "status": "PASS",
                "checked_at": "2026-01-01T00:00:00Z",
                "inputs": [],
                "violations": [],
                "blocked_reasons": [],
                "source_commit": "abc",
            },
        )
    stage = tmp_path / "runs" / "m1-hardening" / "H00_BOOTSTRAP_HARD_GATES"
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")
    violations, blocked = validate_stage_exit(tmp_path, "H00_BOOTSTRAP_HARD_GATES")
    assert not violations
    assert not blocked


def test_h01_stage_exit_requires_reset_gate_and_artifact(tmp_path: Path) -> None:
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", {"claims": []})
    stage_id = "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET"
    stage = tmp_path / "runs" / "m1-hardening" / stage_id
    for gate in H01_REQUIRED_GATE_RESULTS:
        if gate == "build_acceptance_reset":
            continue
        write_json(
            stage / "artifacts" / "gates" / f"{gate}.json",
            _gate_payload(stage_id, gate),
        )
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")
    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert any("build_acceptance_reset.json is missing" in item for item in blocked)
    assert any("milestone1_acceptance_reset.json is missing" in item for item in blocked)

    write_json(stage / "artifacts" / "gates" / "build_acceptance_reset.json", _gate_payload(stage_id, "build_acceptance_reset"))
    write_json(stage / "artifacts" / "milestone1_acceptance_reset.json", _minimal_acceptance_reset(tmp_path, blocked_reason="blocked", stage_id=stage_id))
    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert not violations
    assert not blocked


def test_h02_stage_exit_requires_final_gate_and_acceptance_artifact(tmp_path: Path) -> None:
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", {"claims": []})
    stage_id = "H02_ACCEPTANCE_GATE_FAIL_CLOSED"
    stage = tmp_path / "runs" / "m1-hardening" / stage_id
    for gate in H02_REQUIRED_GATE_RESULTS:
        if gate == "assert_final_milestone1_hardened":
            continue
        write_json(stage / "artifacts" / "gates" / f"{gate}.json", _gate_payload(stage_id, gate))
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")
    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert any("assert_final_milestone1_hardened.json is missing" in item for item in blocked)
    assert any("milestone1_acceptance_report.json is missing" in item for item in blocked)

    write_json(stage / "artifacts" / "gates" / "assert_final_milestone1_hardened.json", _gate_payload(stage_id, "assert_final_milestone1_hardened"))
    write_json(stage / "artifacts" / "milestone1_acceptance_report.json", _minimal_acceptance_reset(tmp_path, blocked_reason="blocked", stage_id=stage_id, artifact_type="milestone1_acceptance_report"))
    violations, blocked = validate_stage_exit(tmp_path, stage_id)
    assert not violations
    assert not blocked


def test_capability_gate_pass_and_blocked(tmp_path: Path) -> None:
    pass_claim = {
        "claim_id": "management_matrix.real_exact.50",
        "capability": "management_matrix",
        "scale": 50,
        "evidence_kind": "REAL_EXACT_SCALE",
        "status": "PASS",
        "semantic_checks": {
            "exact_scale_observed": True,
            "management_matrix_present": True,
            "operation_semantics_present": True,
            "workload_telemetry_present": True,
            "m1_format_fields_complete": True,
            "hardening_stage_accepted": True,
        },
    }
    blocked_claim = {
        "claim_id": "management_matrix.real_exact.100",
        "capability": "management_matrix",
        "scale": 100,
        "evidence_kind": "BLOCKED_WITH_REASON",
        "status": "BLOCKED_WITH_REASON",
        "semantic_checks": {"exact_scale_observed": False},
        "reason": "missing",
    }
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, {"claims": [pass_claim, blocked_claim]})
    status, violations, blocked, extra = evaluate_capability(tmp_path, manifest_path, "management_matrix", {50})
    assert status == "PASS"
    assert not violations
    assert extra["passed_claims"] == ["management_matrix.real_exact.50"]
    status, violations, blocked, _extra = evaluate_capability(tmp_path, manifest_path, "management_matrix", {50, 100})
    assert status == "BLOCKED_WITH_REASON"
    assert not violations
    assert blocked


def test_setup_telemetry_valid_exact_scale_can_pass_after_c06_hardening(tmp_path: Path) -> None:
    _write_setup_exact_scale_evidence(tmp_path, 30)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "setup_telemetry.real_exact.30")
    assert claim["status"] == "PASS"
    assert claim["evidence_kind"] == "REAL_EXACT_SCALE"
    semantic = claim["semantic_checks"]
    assert semantic["setup_core_metrics_numeric"] is True
    assert semantic["setup_per_node_samples_complete"] is True
    assert semantic["hardening_stage_accepted"] is True

    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_setup_core_metrics(manifest_path)
    assert not violations
    assert extra["passed_claims"] == ["setup_telemetry.real_exact.30"]
    assert any("setup_telemetry.real_exact.50" in item for item in blocked)


def test_setup_telemetry_skipped_c06_metric_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_setup_exact_scale_evidence(
        tmp_path,
        30,
        metric_overrides={"cleanup_ms": {"status": "SKIPPED_WITH_REASON", "reason": "cleanup was not run"}},
    )
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "setup_telemetry.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["setup_core_metrics_numeric"] is False
    assert "cleanup_ms is SKIPPED_WITH_REASON" in claim["reason"]
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, _blocked, extra = evaluate_setup_core_metrics(manifest_path)
    assert not violations
    assert extra["setup_claim_status"] == "BLOCKED_WITH_REASON"


def test_setup_telemetry_missing_per_node_fields_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_setup_exact_scale_evidence(tmp_path, 30, sample_overrides={0: {"node_pid": None}})
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "setup_telemetry.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["setup_per_node_samples_complete"] is False
    assert "per_node_samples[0].pid" in claim["reason"]


def test_setup_telemetry_legacy_timing_plus_real_e2e_stays_blocked(tmp_path: Path) -> None:
    phase = tmp_path / "artifacts" / "phases" / "P30_MANAGEMENT_MATRIX_50_REAL"
    write_json(phase / "runtime_timing_breakdown_50.json", {"artifact_type": "p13_setup_exhaustive_timeline", "node_count": 50})
    _write_valkey_e2e(phase, 50)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "setup_telemetry.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["evidence_kind"] == "LEGACY_EVIDENCE_ONLY"
    assert claim["semantic_checks"]["setup_telemetry_artifact_present"] is False
    assert "runtime_timing_breakdown artifacts are legacy timing evidence only" in claim["reason"]


def test_setup_telemetry_fixture_never_satisfies_exact_scale_claim(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "setup_telemetry" / "scale_30"
    write_json(fixture / "setup_telemetry.json", _setup_telemetry_payload(30))
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "setup_telemetry.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["evidence_kind"] == "FIXTURE_ONLY"
    assert claim["semantic_checks"]["setup_telemetry_artifact_present"] is False
    assert "fixture" in claim["reason"]


def test_h03_stage_exit_requires_setup_core_metrics_gate(tmp_path: Path) -> None:
    _seed_stage_exit_base(tmp_path, "H03_SETUP_TELEMETRY_REAL_PATH_HARDENING", H03_REQUIRED_GATE_RESULTS)
    gate = tmp_path / "runs" / "m1-hardening" / "H03_SETUP_TELEMETRY_REAL_PATH_HARDENING" / "artifacts" / "gates" / "assert_setup_core_metrics.json"
    gate.unlink()
    violations, blocked = validate_stage_exit(tmp_path, "H03_SETUP_TELEMETRY_REAL_PATH_HARDENING")
    assert not violations
    assert any("assert_setup_core_metrics.json is missing" in item for item in blocked)

    write_json(gate, _gate_payload("H03_SETUP_TELEMETRY_REAL_PATH_HARDENING", "assert_setup_core_metrics"))
    violations, blocked = validate_stage_exit(tmp_path, "H03_SETUP_TELEMETRY_REAL_PATH_HARDENING")
    assert not violations
    assert not blocked


def test_command_audit_valid_exact_scale_can_pass_after_c07_hardening(tmp_path: Path) -> None:
    _write_command_audit_exact_scale_evidence(tmp_path, 50)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "PASS"
    assert claim["evidence_kind"] == "REAL_EXACT_SCALE"
    semantic = claim["semantic_checks"]
    assert semantic["command_log_schema_valid"] is True
    assert semantic["required_command_kinds_present"] is True
    assert semantic["operation_traceability_present"] is True
    assert semantic["hardening_stage_accepted"] is True

    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_command_audit_real(manifest_path)
    assert not violations
    assert extra["passed_claims"] == ["command_audit.real_exact.50"]
    assert any("command_audit.real_exact.100" in item for item in blocked)


def test_command_audit_empty_log_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_command_audit_exact_scale_evidence(tmp_path, 50, rows=[])
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_log_non_empty"] is False
    assert "has no command rows" in claim["reason"]


def test_command_audit_placeholder_command_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = _command_rows(50)
    rows[0]["argv"] = ["valkey-cli", "cluster", "create_cluster"]
    manifest = _manifest_with_command_rows(tmp_path, 50, rows)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["no_placeholder_commands"] is False
    assert "placeholder command" in claim["reason"]


def test_command_audit_missing_required_kind_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = [row for row in _command_rows(50) if row["command_kind"] != "cluster_replicate"]
    manifest = _manifest_with_command_rows(tmp_path, 50, rows)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["required_command_kinds_present"] is False
    assert "cluster_replicate" in claim["reason"]


def test_command_audit_missing_row_value_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = _command_rows(50)
    rows[0]["host_id"] = "MISSING"
    manifest = _manifest_with_command_rows(tmp_path, 50, rows)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_log_schema_valid"] is False
    assert "required field host_id is MISSING" in claim["reason"]


def test_command_audit_empty_management_sidecar_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_command_audit_exact_scale_evidence(tmp_path, 50)
    phase = tmp_path / "artifacts" / "phases" / "P30_MANAGEMENT_MATRIX_50_REAL"
    (phase / "management_command_log.jsonl").write_text("", encoding="utf-8")
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["empty_legacy_management_log_absent"] is False
    assert "empty management command log" in claim["reason"]


def test_command_audit_summary_missing_or_skipped_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = _command_rows(50)
    _write_command_audit_exact_scale_evidence(tmp_path, 50, rows=rows)
    phase = tmp_path / "artifacts" / "phases" / "P30_MANAGEMENT_MATRIX_50_REAL"
    summary = _command_summary(rows)
    summary["missing_or_skipped"] = [{"metric": "command_log.total_commands", "status": "SKIPPED_WITH_REASON", "reason": "probe"}]
    write_json(phase / "command_audit_summary.json", summary)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["summary_missing_or_skipped_empty"] is False
    assert "missing_or_skipped must be empty" in claim["reason"]


def test_command_audit_summary_schema_error_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = _command_rows(50)
    _write_command_audit_exact_scale_evidence(tmp_path, 50, rows=rows)
    phase = tmp_path / "artifacts" / "phases" / "P30_MANAGEMENT_MATRIX_50_REAL"
    summary = _command_summary(rows)
    summary.pop("operation_traceability")
    write_json(phase / "command_audit_summary.json", summary)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_audit_summary_schema_valid"] is False
    assert "missing required key 'operation_traceability'" in claim["reason"]


def test_command_audit_kind_argv_mismatch_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = _command_rows(50)
    rows[0]["argv"] = ["bash", "-lc", "true"]
    manifest = _manifest_with_command_rows(tmp_path, 50, rows)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_kind_argv_consistent"] is False
    assert "is not supported by argv shape" in claim["reason"]


def test_command_audit_inconsistent_timing_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = _command_rows(50)
    rows[0]["ended_at_unix_ms"] = 1
    manifest = _manifest_with_command_rows(tmp_path, 50, rows)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_log_schema_valid"] is False
    assert "ended_at_unix_ms is earlier than started_at_unix_ms" in claim["reason"]


def test_command_audit_failed_row_must_be_summarized(tmp_path: Path) -> None:
    rows = _command_rows(50)
    rows[0]["status"] = "FAIL"
    rows[0]["exit_code"] = 1
    summary = _command_summary(rows)
    summary["failed_commands"] = []
    phase = tmp_path / "artifacts" / "phases" / "P30_MANAGEMENT_MATRIX_50_REAL"
    _write_jsonl(phase / "command_log.jsonl", rows)
    write_json(phase / "command_audit_summary.json", summary)
    _write_command_output_logs(tmp_path, rows)
    _write_valkey_e2e(phase, 50)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["failure_timeout_retry_rows_summarized"] is False
    assert "failed_commands is missing command ids" in claim["reason"]


def test_command_audit_output_hash_mismatch_blocks_exact_scale_pass(tmp_path: Path) -> None:
    rows = _command_rows(50)
    rows[0]["stdout_sha256"] = "1" * 64
    manifest = _manifest_with_command_rows(tmp_path, 50, rows)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["output_hashes_verified"] is False
    assert "stdout_sha256 does not match" in claim["reason"]


def test_command_audit_malformed_jsonl_line_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_command_audit_exact_scale_evidence(tmp_path, 50)
    phase = tmp_path / "artifacts" / "phases" / "P30_MANAGEMENT_MATRIX_50_REAL"
    with (phase / "command_log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not-json\n")
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_log_schema_valid"] is False
    assert "line 6 is invalid JSON" in claim["reason"]


def test_command_audit_legacy_management_log_stays_blocked(tmp_path: Path) -> None:
    phase = tmp_path / "artifacts" / "phases" / "P30_MANAGEMENT_MATRIX_50_REAL"
    write_json(
        phase / "valkey_e2e_evidence.json",
        {
            "schema_version": "v1",
            "artifact_type": "valkey_e2e_evidence",
            "status": "PASS",
            "real_valkey": True,
            "nodes_observed": 50,
            "valkey_versions": ["9.1.0"],
        },
    )
    legacy_row = {
        "schema_version": "v1",
        "phase_id": "P30_MANAGEMENT_MATRIX_50_REAL",
        "run_id": "legacy",
        "operation_id": "legacy",
        "command_id": "p30-legacy-cmd-0001",
        "command_kind": "cluster_setslot_node",
        "argv": ["CLUSTER", "SETSLOT", "1", "NODE", "abc"],
        "started_at_unix_ms": 1,
        "ended_at_unix_ms": 2,
        "status": "PASS",
    }
    _write_jsonl(phase / "management_command_log.jsonl", [legacy_row])
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["evidence_kind"] == "LEGACY_EVIDENCE_ONLY"
    assert claim["semantic_checks"]["command_log_schema_valid"] is False
    assert "command_audit_summary.json is missing" in claim["reason"]


def test_command_audit_fixture_never_satisfies_exact_scale_claim(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "command_log" / "scale_50"
    rows = _command_rows(50)
    _write_jsonl(fixture / "command_log.jsonl", rows)
    write_json(fixture / "command_audit_summary.json", _command_summary(rows))
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "command_audit.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["evidence_kind"] == "FIXTURE_ONLY"
    assert claim["semantic_checks"]["command_log_present"] is False
    assert "fixture" in claim["reason"]


def test_h04_stage_exit_requires_command_audit_gate(tmp_path: Path) -> None:
    _seed_stage_exit_base(tmp_path, "H04_COMMAND_AUDIT_REAL_PATH_HARDENING", H04_REQUIRED_GATE_RESULTS)
    gate = tmp_path / "runs" / "m1-hardening" / "H04_COMMAND_AUDIT_REAL_PATH_HARDENING" / "artifacts" / "gates" / "assert_command_audit_real.json"
    gate.unlink()
    violations, blocked = validate_stage_exit(tmp_path, "H04_COMMAND_AUDIT_REAL_PATH_HARDENING")
    assert not violations
    assert any("assert_command_audit_real.json is missing" in item for item in blocked)

    write_json(gate, _gate_payload("H04_COMMAND_AUDIT_REAL_PATH_HARDENING", "assert_command_audit_real"))
    violations, blocked = validate_stage_exit(tmp_path, "H04_COMMAND_AUDIT_REAL_PATH_HARDENING")
    assert not violations
    assert not blocked


def test_management_matrix_valid_exact_scale_can_pass_after_h05_hardening(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "PASS"
    assert claim["evidence_kind"] == "REAL_EXACT_SCALE"
    assert claim["semantic_checks"]["command_refs_resolve"] is True
    assert claim["semantic_checks"]["command_refs_c07_valid"] is True
    assert claim["semantic_checks"]["command_refs_operation_traceable"] is True
    assert claim["semantic_checks"]["topology_exact_health"] is True
    assert claim["semantic_checks"]["workload_metrics_numeric"] is True
    assert claim["semantic_checks"]["hardening_stage_accepted"] is True
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_management_exact_scale(manifest_path)
    assert not violations
    assert extra["passed_claims"] == ["management_matrix.real_exact.50"]
    assert any("management_matrix.real_exact.100" in item for item in blocked)


def test_management_matrix_file_level_command_refs_block_exact_scale_pass(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50, command_ref_mode="file")
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_refs_resolve"] is False
    assert "file-level only" in claim["reason"]


def test_management_matrix_command_ref_wrong_operation_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50, wrong_command_operation=True)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_refs_operation_traceable"] is False
    assert "points to operation_id" in claim["reason"]


def test_management_matrix_command_output_hash_mismatch_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50, bad_command_hash=True)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["command_refs_c07_valid"] is False
    assert "stdout_sha256 does not match" in claim["reason"]


def test_management_matrix_bad_matrix_topology_diff_ref_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50, bad_matrix_topology_diff_ref=True)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["topology_diff_refs_resolve"] is False
    assert "topology_diff_ref" in claim["reason"]


def test_management_matrix_missing_topology_slots_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50, omit_topology_slots=True)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["topology_exact_health"] is False
    assert "slots is not 16384" in claim["reason"]


def test_management_matrix_string_workload_counts_block_exact_scale_pass(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50, string_workload_counts=True)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["workload_metrics_numeric"] is False
    assert "timeout_count is missing or non-numeric" in claim["reason"]


def test_management_matrix_missing_workload_ref_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_management_exact_scale_evidence(tmp_path, 50, omit_workload_window=True)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["workload_refs_resolve"] is False
    assert "workload_window_ref" in claim["reason"]


def test_management_matrix_fixture_never_satisfies_exact_scale_claim(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "management_matrix" / "scale_50"
    _write_management_exact_scale_evidence(tmp_path, 50, base=fixture)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "management_matrix.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["evidence_kind"] == "FIXTURE_ONLY"
    assert claim["semantic_checks"]["no_fixture_management_artifacts"] is False
    assert "Fixture management artifacts" in claim["reason"]


def test_h05_stage_exit_requires_management_exact_gate(tmp_path: Path) -> None:
    _seed_stage_exit_base(tmp_path, "H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING", H05_REQUIRED_GATE_RESULTS)
    gate = tmp_path / "runs" / "m1-hardening" / "H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING" / "artifacts" / "gates" / "assert_management_exact_scale.json"
    gate.unlink()
    violations, blocked = validate_stage_exit(tmp_path, "H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING")
    assert not violations
    assert any("assert_management_exact_scale.json is missing" in item for item in blocked)
    write_json(gate, _gate_payload("H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING", "assert_management_exact_scale"))
    violations, blocked = validate_stage_exit(tmp_path, "H05_MANAGEMENT_MATRIX_EXACT_SCALE_HARDENING")
    assert not violations
    assert not blocked


def test_workload_benchmark_valid_exact_scale_can_pass_after_h06_hardening(tmp_path: Path) -> None:
    _write_workload_benchmark_exact_scale_evidence(tmp_path, 30)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "workload_benchmark.real_exact.30")
    assert claim["status"] == "PASS"
    assert claim["evidence_kind"] == "REAL_EXACT_SCALE"
    semantic = claim["semantic_checks"]
    assert semantic["metrics_row_count_sufficient"] is True
    assert semantic["metrics_rows_cover_required_matrix"] is True
    assert semantic["connection_evidence_observed"] is True
    assert semantic["pipeline_evidence_observed"] is True
    assert semantic["full_slot_coverage_non_smoke"] is True
    assert semantic["hardening_stage_accepted"] is True
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_workload_benchmark_strength(manifest_path)
    assert not violations
    assert extra["passed_claims"] == ["workload_benchmark.real_exact.30"]
    assert any("workload_benchmark.real_exact.50" in item for item in blocked)


def test_workload_benchmark_missing_profile_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_workload_benchmark_exact_scale_evidence(tmp_path, 30, omit_profile="read_heavy")
    claim = _claim(build_manifest(tmp_path), "workload_benchmark.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["workload_profiles_complete"] is False
    assert "read_heavy" in claim["reason"]


def test_workload_benchmark_missing_window_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_workload_benchmark_exact_scale_evidence(tmp_path, 30, omit_window=("uniform", "event"))
    claim = _claim(build_manifest(tmp_path), "workload_benchmark.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["workload_windows_complete"] is False
    assert "uniform:event" in claim["reason"]


def test_workload_benchmark_shallow_metric_rows_block_exact_scale_pass(tmp_path: Path) -> None:
    _write_workload_benchmark_exact_scale_evidence(tmp_path, 30, shallow_metric_rows=True)
    claim = _claim(build_manifest(tmp_path), "workload_benchmark.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["metrics_row_count_sufficient"] is False
    assert str(H06_REQUIRED_METRIC_ROW_COUNT) in claim["reason"]


def test_workload_benchmark_missing_string_or_skipped_metric_blocks_exact_scale_pass(tmp_path: Path) -> None:
    for mode in ["missing", "string", "skipped"]:
        root = tmp_path / mode
        _write_workload_benchmark_exact_scale_evidence(root, 30, metric_defect=mode)
        claim = _claim(build_manifest(root), "workload_benchmark.real_exact.30")
        assert claim["status"] == "BLOCKED_WITH_REASON"
        assert claim["semantic_checks"]["workload_required_metrics_numeric"] is False
        assert "latency_p99_ms" in claim["reason"]


def test_workload_benchmark_low_ops_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_workload_benchmark_exact_scale_evidence(tmp_path, 30, low_ops=True)
    claim = _claim(build_manifest(tmp_path), "workload_benchmark.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["operations_per_window_sufficient"] is False
    assert "below H06 minimum" in claim["reason"]


def test_workload_benchmark_missing_connection_or_pipeline_evidence_blocks_exact_scale_pass(tmp_path: Path) -> None:
    for mode, check in [("connection", "connection_evidence_observed"), ("pipeline", "pipeline_evidence_observed")]:
        root = tmp_path / mode
        _write_workload_benchmark_exact_scale_evidence(root, 30, omit_connection_evidence=mode == "connection", omit_pipeline_evidence=mode == "pipeline")
        claim = _claim(build_manifest(root), "workload_benchmark.real_exact.30")
        assert claim["status"] == "BLOCKED_WITH_REASON"
        assert claim["semantic_checks"][check] is False
        assert mode in claim["reason"]


def test_workload_benchmark_missing_full_slot_or_fixed_hash_tag_blocks_exact_scale_pass(tmp_path: Path) -> None:
    for mode in ["missing_full_slot", "fixed_hash_tag"]:
        root = tmp_path / mode
        _write_workload_benchmark_exact_scale_evidence(root, 30, full_slot_defect=mode)
        claim = _claim(build_manifest(root), "workload_benchmark.real_exact.30")
        assert claim["status"] == "BLOCKED_WITH_REASON"
        assert claim["semantic_checks"]["full_slot_coverage_non_smoke"] is False
        assert "full-slot coverage" in claim["reason"]


def test_workload_benchmark_fixture_never_satisfies_exact_scale_claim(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "workload_benchmark" / "scale_30"
    _write_workload_benchmark_exact_scale_evidence(tmp_path, 30, base=fixture)
    claim = _claim(build_manifest(tmp_path), "workload_benchmark.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["evidence_kind"] == "FIXTURE_ONLY"
    assert claim["semantic_checks"]["no_fixture_workload_artifacts"] is False
    assert "fixtures cannot satisfy" in claim["reason"]


def test_workload_benchmark_fake_or_partial_artifact_blocks_exact_scale_pass(tmp_path: Path) -> None:
    phase = _write_workload_benchmark_exact_scale_evidence(tmp_path, 30)
    workload = json.loads((phase / "workload_windows.json").read_text(encoding="utf-8"))
    workload["evidence_kind"] = "PARTIAL"
    write_json(phase / "workload_windows.json", workload)
    claim = _claim(build_manifest(tmp_path), "workload_benchmark.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["fake_or_partial_not_promoted"] is False
    assert "partial evidence cannot promote" in claim["reason"]


def test_workload_benchmark_split_directory_artifacts_cannot_be_spliced(tmp_path: Path) -> None:
    phase = _write_workload_benchmark_exact_scale_evidence(tmp_path, 30)
    split = phase / "split"
    split.mkdir(parents=True)
    (split / "metrics_timeseries.jsonl").write_text((phase / "metrics_timeseries.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    (split / "valkey_e2e_evidence.json").write_text((phase / "valkey_e2e_evidence.json").read_text(encoding="utf-8"), encoding="utf-8")
    (phase / "metrics_timeseries.jsonl").unlink()
    (phase / "valkey_e2e_evidence.json").unlink()
    claim = _claim(build_manifest(tmp_path), "workload_benchmark.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["metrics_timeseries_present"] is False or claim["semantic_checks"]["workload_windows_present"] is False
    assert "same directory" in claim["reason"]


def test_h06_stage_exit_requires_workload_benchmark_gate(tmp_path: Path) -> None:
    _seed_stage_exit_base(tmp_path, "H06_WORKLOAD_BENCHMARK_HARDENING", H06_REQUIRED_GATE_RESULTS)
    gate = tmp_path / "runs" / "m1-hardening" / "H06_WORKLOAD_BENCHMARK_HARDENING" / "artifacts" / "gates" / "assert_workload_benchmark_strength.json"
    gate.unlink()
    violations, blocked = validate_stage_exit(tmp_path, "H06_WORKLOAD_BENCHMARK_HARDENING")
    assert not violations
    assert any("assert_workload_benchmark_strength.json is missing" in item for item in blocked)
    write_json(gate, _gate_payload("H06_WORKLOAD_BENCHMARK_HARDENING", "assert_workload_benchmark_strength"))
    violations, blocked = validate_stage_exit(tmp_path, "H06_WORKLOAD_BENCHMARK_HARDENING")
    assert not violations
    assert not blocked


def test_fault_timeline_valid_exact_scale_can_pass_after_h07_hardening(tmp_path: Path) -> None:
    _write_fault_timeline_exact_scale_evidence(tmp_path, 50)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "fault_timeline.real_exact.50")
    assert claim["status"] == "PASS"
    assert claim["evidence_kind"] == "REAL_EXACT_SCALE"
    semantic = claim["semantic_checks"]
    assert semantic["fault_required_types_present"] is True
    assert semantic["fault_required_events_present"] is True
    assert semantic["fault_required_metrics_numeric"] is True
    assert semantic["workload_h06_dependency_accepted"] is True
    assert semantic["cleanup_refs_resolve"] is True
    assert semantic["clean_cluster_evidence"] is True
    assert semantic["hardening_stage_accepted"] is True

    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_fault_timeline_real(manifest_path)
    assert not violations
    assert extra["passed_claims"] == ["fault_timeline.real_exact.50"]
    assert any("fault_timeline.real_exact.100" in item for item in blocked)


def test_fault_timeline_missing_report_events_or_samples_blocks_exact_scale_pass(tmp_path: Path) -> None:
    for missing_name, check in [
        ("fault_timeline_report.json", "fault_timeline_report_present"),
        ("fault_timeline_events.jsonl", "fault_timeline_events_present"),
        ("failover_latency_samples.jsonl", "failover_latency_samples_present"),
    ]:
        root = tmp_path / missing_name
        phase = _write_fault_timeline_exact_scale_evidence(root, 50)
        (phase / missing_name).unlink()
        claim = _claim(build_manifest(root), "fault_timeline.real_exact.50")
        assert claim["status"] == "BLOCKED_WITH_REASON"
        assert claim["semantic_checks"][check] is False
        assert missing_name in claim["reason"]


def test_fault_timeline_missing_fault_type_or_lifecycle_event_blocks_exact_scale_pass(tmp_path: Path) -> None:
    phase = _write_fault_timeline_exact_scale_evidence(tmp_path / "missing_fault", 50, omit_fault_type="network_loss")
    claim = _claim(build_manifest(tmp_path / "missing_fault"), "fault_timeline.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["fault_required_types_present"] is False
    assert "network_loss" in claim["reason"]

    root = tmp_path / "missing_event"
    phase = _write_fault_timeline_exact_scale_evidence(root, 50, omit_event=("primary_stop_failover", "promotion_observed"))
    claim = _claim(build_manifest(root), "fault_timeline.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["fault_required_events_present"] is False
    assert "promotion_observed" in claim["reason"]


def test_fault_timeline_bad_metric_blocks_exact_scale_pass(tmp_path: Path) -> None:
    for mode in ["missing", "string", "skipped", "bool", "null"]:
        root = tmp_path / mode
        _write_fault_timeline_exact_scale_evidence(root, 50, metric_defect=mode)
        claim = _claim(build_manifest(root), "fault_timeline.real_exact.50")
        assert claim["status"] == "BLOCKED_WITH_REASON"
        assert claim["semantic_checks"]["fault_required_metrics_numeric"] is False
        assert "failover_latency_ms" in claim["reason"]


def test_fault_timeline_partial_fake_or_non_real_status_blocks_exact_scale_pass(tmp_path: Path) -> None:
    for mode, check in [
        ("report_partial", "fault_timeline_report_status_pass"),
        ("row_partial", "fault_rows_status_pass"),
        ("event_fake", "fault_execution_mode_real"),
        ("row_non_real", "fault_rows_real_valkey"),
    ]:
        root = tmp_path / mode
        _write_fault_timeline_exact_scale_evidence(root, 50, mode=mode)
        claim = _claim(build_manifest(root), "fault_timeline.real_exact.50")
        assert claim["status"] == "BLOCKED_WITH_REASON"
        assert claim["semantic_checks"][check] is False


def test_fault_timeline_scale_or_version_mismatch_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_fault_timeline_exact_scale_evidence(tmp_path / "scale", 50, valkey_nodes=49)
    claim = _claim(build_manifest(tmp_path / "scale"), "fault_timeline.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["exact_scale_observed"] is False

    _write_fault_timeline_exact_scale_evidence(tmp_path / "version", 50, valkey_versions=["9.0.9"])
    claim = _claim(build_manifest(tmp_path / "version"), "fault_timeline.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["valkey_9_1_verified"] is False


def test_fault_timeline_missing_workload_or_cleanup_refs_blocks_exact_scale_pass(tmp_path: Path) -> None:
    for mode, check in [("missing_workload_ref", "workload_refs_resolve"), ("missing_cleanup_ref", "cleanup_refs_resolve"), ("dirty_cleanup", "clean_cluster_evidence")]:
        root = tmp_path / mode
        _write_fault_timeline_exact_scale_evidence(root, 50, mode=mode)
        claim = _claim(build_manifest(root), "fault_timeline.real_exact.50")
        assert claim["status"] == "BLOCKED_WITH_REASON"
        assert claim["semantic_checks"][check] is False


def test_fault_timeline_h06_blocked_workload_dependency_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_fault_timeline_exact_scale_evidence(tmp_path, 50, h06_workload_defect=True)
    claim = _claim(build_manifest(tmp_path), "fault_timeline.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["workload_h06_dependency_accepted"] is False
    assert "H06 workload benchmark dependency" in claim["reason"]


def test_fault_timeline_legacy_samples_not_accepted(tmp_path: Path) -> None:
    phase = _write_fault_timeline_exact_scale_evidence(tmp_path, 50, mode="legacy_sample")
    (phase / "fault_timeline_report.json").unlink()
    (phase / "fault_timeline_events.jsonl").unlink()
    claim = _claim(build_manifest(tmp_path), "fault_timeline.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["fault_timeline_report_present"] is False
    assert claim["semantic_checks"]["no_legacy_fault_promotion"] is False


def test_fault_timeline_split_directory_artifacts_cannot_be_spliced(tmp_path: Path) -> None:
    phase = _write_fault_timeline_exact_scale_evidence(tmp_path, 50)
    split = phase / "split"
    split.mkdir(parents=True)
    for name in ["fault_timeline_events.jsonl", "failover_latency_samples.jsonl", "workload_windows.json", "metrics_timeseries.jsonl", "cleanup_report.json", "valkey_e2e_evidence.json"]:
        (split / name).write_text((phase / name).read_text(encoding="utf-8"), encoding="utf-8")
        (phase / name).unlink()
    claim = _claim(build_manifest(tmp_path), "fault_timeline.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["same_directory_bundle"] is False
    assert "same directory" in claim["reason"]


def test_fault_timeline_dedicated_gate_rejects_unsafe_pass_and_accepts_honest_blocked(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    fault = _claim(manifest, "fault_timeline.real_exact.50")
    fault.update(
        {
            "status": "PASS",
            "evidence_kind": "REAL_EXACT_SCALE",
            "source_artifacts": ["artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_timeline_report.json"],
            "semantic_checks": {"m1_format_fields_complete": True, "hardening_stage_accepted": True, "exact_scale_observed": True},
        }
    )
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, _blocked, _extra = evaluate_fault_timeline_real(manifest_path)
    assert "fault_pass_missing_artifact" in {item["code"] for item in violations}

    manifest = build_manifest(tmp_path)
    fault = _claim(manifest, "fault_timeline.real_exact.50")
    fault.update(
        {
            "status": "PASS",
            "evidence_kind": "REAL_EXACT_SCALE",
            "source_artifacts": [
                "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_timeline_report.json",
                "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/fault_timeline_events.jsonl",
                "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/failover_latency_samples.jsonl",
                "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/workload_windows.json",
                "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/metrics_timeseries.jsonl",
                "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/cleanup_report.json",
                "artifacts/phases/P33_FAULT_FAILOVER_MATRIX_50_REAL/valkey_e2e_evidence.json",
            ],
            "semantic_checks": _passing_semantic_checks("fault_timeline.real_exact.50"),
            "diagnostics": {},
        }
    )
    write_json(manifest_path, manifest)
    violations, _blocked, _extra = evaluate_fault_timeline_real(manifest_path)
    assert "fault_pass_h07_not_accepted" in {item["code"] for item in violations}

    manifest = build_manifest(tmp_path)
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_fault_timeline_real(manifest_path)
    assert not violations
    assert extra["fault_claim_status"] == "BLOCKED_WITH_REASON"
    assert len(blocked) == 3


def test_h07_stage_exit_requires_fault_timeline_gate(tmp_path: Path) -> None:
    _seed_stage_exit_base(tmp_path, "H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING", H07_REQUIRED_GATE_RESULTS)
    gate = tmp_path / "runs" / "m1-hardening" / "H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING" / "artifacts" / "gates" / "assert_fault_timeline_real.json"
    gate.unlink()
    violations, blocked = validate_stage_exit(tmp_path, "H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING")
    assert not violations
    assert any("assert_fault_timeline_real.json is missing" in item for item in blocked)
    write_json(gate, _gate_payload("H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING", "assert_fault_timeline_real"))
    violations, blocked = validate_stage_exit(tmp_path, "H07_FAULT_FAILOVER_TIMELINE_REAL_PATH_HARDENING")
    assert not violations
    assert not blocked


def test_system_metrics_valid_exact_scale_can_pass_after_h08_hardening(tmp_path: Path) -> None:
    _write_system_metrics_exact_scale_evidence(tmp_path, 30)
    manifest = build_manifest(tmp_path)
    claim = _claim(manifest, "system_metrics.real_exact.30")
    assert claim["status"] == "PASS"
    assert claim["evidence_kind"] == "REAL_EXACT_SCALE"
    semantic = claim["semantic_checks"]
    assert semantic["lifecycle_windows_present"] is True
    assert semantic["node_coverage_complete"] is True
    assert semantic["high_value_numeric_coverage"] is True
    assert semantic["high_value_window_coverage"] is True
    assert semantic["system_metrics_report_semantics_valid"] is True
    assert semantic["hardening_stage_accepted"] is True

    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_system_metrics_real_windows(manifest_path)
    assert not violations
    assert extra["passed_claims"] == ["system_metrics.real_exact.30"]
    assert any("system_metrics.real_exact.50" in item for item in blocked)


def test_system_metrics_generic_metrics_timeseries_never_satisfies_h08(tmp_path: Path) -> None:
    _write_workload_benchmark_exact_scale_evidence(tmp_path, 30)
    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["system_metrics_timeseries_present"] is False
    assert "generic metrics_timeseries.jsonl cannot satisfy C10" in claim["reason"]


def test_system_metrics_missing_lifecycle_window_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_system_metrics_exact_scale_evidence(tmp_path, 50, omit_window="fault_or_failover")
    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.50")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["lifecycle_windows_present"] is False
    assert "fault_or_failover" in claim["reason"]


def test_system_metrics_missing_required_row_fields_block_exact_scale_pass(tmp_path: Path) -> None:
    _write_system_metrics_exact_scale_evidence(tmp_path, 30, row_defect="missing_timestamp")
    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["system_metrics_timeseries_schema_valid"] is False
    assert "timestamp_unix_ms" in claim["reason"]


def test_system_metrics_accepts_runtime_label_node_and_window_fields(tmp_path: Path) -> None:
    _write_system_metrics_exact_scale_evidence(tmp_path, 30, row_defect="labels_only_node_window")
    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.30")
    assert claim["status"] == "PASS"
    assert claim["semantic_checks"]["lifecycle_windows_present"] is True
    assert claim["semantic_checks"]["node_coverage_complete"] is True


def test_system_metrics_bad_report_cross_checks_block_exact_scale_pass(tmp_path: Path) -> None:
    phase = _write_system_metrics_exact_scale_evidence(tmp_path, 30)
    report_path = phase / "system_metrics_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["sample_count"] = 0
    report["lifecycle_windows"] = ["setup"]
    report["coverage"]["rows_by_window"] = {"setup": 1}
    report["coverage"]["rows_by_node"] = {"node-0000": 1}
    write_json(report_path, report)

    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["system_metrics_report_semantics_valid"] is False
    assert claim["semantic_checks"]["hardening_stage_accepted"] is False
    assert "sample_count" in claim["reason"]
    assert "lifecycle_windows" in claim["reason"]


def test_system_metrics_report_count_mismatch_blocks_exact_scale_pass(tmp_path: Path) -> None:
    phase = _write_system_metrics_exact_scale_evidence(tmp_path, 30)
    report_path = phase / "system_metrics_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["coverage"]["rows_by_window"] = {"setup": 1, "workload": 1, "cleanup": 1}
    report["coverage"]["rows_by_node"] = {f"node-{index:04d}": 1 for index in range(30)}
    write_json(report_path, report)

    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["system_metrics_report_semantics_valid"] is False
    assert "rows_by_window" in claim["reason"]
    assert "rows_by_node" in claim["reason"]


def test_system_metrics_extra_node_coverage_blocks_exact_scale_pass(tmp_path: Path) -> None:
    phase = _write_system_metrics_exact_scale_evidence(tmp_path, 30, extra_node=True)
    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["node_coverage_complete"] is False
    assert "exact-scale H08 requires exactly 30" in claim["reason"]


def test_system_metrics_skipped_high_value_group_blocks_exact_scale_pass(tmp_path: Path) -> None:
    _write_system_metrics_exact_scale_evidence(tmp_path, 30, row_defect="skip_valkey_info")
    claim = _claim(build_manifest(tmp_path), "system_metrics.real_exact.30")
    assert claim["status"] == "BLOCKED_WITH_REASON"
    assert claim["semantic_checks"]["high_value_numeric_coverage"] is False
    assert "valkey_info" in claim["reason"]


def test_system_metrics_missing_node_coverage_or_wrong_valkey_version_blocks(tmp_path: Path) -> None:
    _write_system_metrics_exact_scale_evidence(tmp_path / "node", 30, omit_node_index=29)
    node_claim = _claim(build_manifest(tmp_path / "node"), "system_metrics.real_exact.30")
    assert node_claim["status"] == "BLOCKED_WITH_REASON"
    assert node_claim["semantic_checks"]["node_coverage_complete"] is False

    _write_system_metrics_exact_scale_evidence(tmp_path / "version", 30, valkey_versions=["9.0.9"])
    version_claim = _claim(build_manifest(tmp_path / "version"), "system_metrics.real_exact.30")
    assert version_claim["status"] == "BLOCKED_WITH_REASON"
    assert version_claim["semantic_checks"]["valkey_9_1_verified"] is False


def test_system_metrics_dedicated_gate_rejects_unsafe_pass_and_accepts_honest_blocked(tmp_path: Path) -> None:
    manifest = build_manifest(tmp_path)
    system = _claim(manifest, "system_metrics.real_exact.30")
    system.update(
        {
            "status": "PASS",
            "evidence_kind": "REAL_EXACT_SCALE",
            "source_artifacts": [
                "artifacts/phases/P12_SCALE_LADDER_10_30/system_metrics_report.json",
                "artifacts/phases/P12_SCALE_LADDER_10_30/system_metrics_timeseries.jsonl",
                "artifacts/phases/P12_SCALE_LADDER_10_30/valkey_e2e_evidence.json",
            ],
            "semantic_checks": _passing_semantic_checks("system_metrics.real_exact.30"),
            "diagnostics": {},
        }
    )
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    violations, _blocked, _extra = evaluate_system_metrics_real_windows(manifest_path)
    assert "system_metrics_pass_h08_not_accepted" in {item["code"] for item in violations}

    manifest = build_manifest(tmp_path)
    write_json(manifest_path, manifest)
    violations, blocked, extra = evaluate_system_metrics_real_windows(manifest_path)
    assert not violations
    assert extra["system_metrics_claim_status"] == "BLOCKED_WITH_REASON"
    assert extra["passed_claims"] == []
    assert len(blocked) == 4


def test_h08_stage_exit_requires_system_metrics_gate(tmp_path: Path) -> None:
    _seed_stage_exit_base(tmp_path, "H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING", H08_REQUIRED_GATE_RESULTS)
    gate = tmp_path / "runs" / "m1-hardening" / "H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING" / "artifacts" / "gates" / "assert_system_metrics_real_windows.json"
    gate.unlink()
    violations, blocked = validate_stage_exit(tmp_path, "H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING")
    assert not violations
    assert any("assert_system_metrics_real_windows.json is missing" in item for item in blocked)
    write_json(gate, _gate_payload("H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING", "assert_system_metrics_real_windows"))
    violations, blocked = validate_stage_exit(tmp_path, "H08_SYSTEM_METRICS_REAL_WINDOW_HARDENING")
    assert not violations
    assert not blocked


def _write_fault_timeline_exact_scale_evidence(
    tmp_path: Path,
    scale: int,
    *,
    omit_fault_type: str | None = None,
    omit_event: tuple[str, str] | None = None,
    metric_defect: str | None = None,
    mode: str | None = None,
    valkey_nodes: int | None = None,
    valkey_versions: list[str] | None = None,
    h06_workload_defect: bool = False,
) -> Path:
    phase_by_scale = {
        50: "P33_FAULT_FAILOVER_MATRIX_50_REAL",
        100: "P34_FAULT_FAILOVER_MATRIX_100_REAL",
        200: "P35_FAULT_FAILOVER_MATRIX_200_REAL",
    }
    phase = tmp_path / "artifacts" / "phases" / phase_by_scale[scale]
    _write_workload_benchmark_exact_scale_evidence(
        tmp_path,
        scale,
        base=phase,
        metric_defect="string" if h06_workload_defect else None,
    )
    if valkey_nodes is not None or valkey_versions is not None:
        _write_valkey_e2e_custom(phase, valkey_nodes if valkey_nodes is not None else scale, valkey_versions or ["9.1.0"])
    cleanup_resources = [{"kind": "container", "name": "leftover"}] if mode == "dirty_cleanup" else []
    write_json(
        phase / "cleanup_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "cleanup_report",
            "phase_id": phase_by_scale[scale],
            "run_id": f"h07-{scale}",
            "created_at": "2026-01-01T00:00:00Z",
            "producer": {"name": "test", "version": "v1"},
            "status": "FAIL" if cleanup_resources else "PASS",
            "resources_remaining": cleanup_resources,
            "cleanup_actions": [{"action": "cleanup", "status": "PASS"}],
        },
    )
    events: list[dict[str, object]] = []
    rows: list[dict[str, object]] = []
    samples: list[dict[str, object]] = []
    fault_types = [fault for fault in H07_REQUIRED_FAULT_TYPES if fault != omit_fault_type]
    for fault_index, fault_type in enumerate(fault_types, start=1):
        sample_id = f"h07-{scale}-{fault_type}"
        fault_id = f"fault-{fault_index:02d}"
        for event_index, event_name in enumerate(H07_REQUIRED_TIMELINE_EVENTS, start=1):
            if omit_event == (fault_type, event_name):
                continue
            events.append(
                {
                    "schema_version": "v1",
                    "artifact_type": "fault_timeline_event",
                    "phase_id": phase_by_scale[scale],
                    "run_id": f"h07-{scale}",
                    "scenario_name": f"fault-{scale}",
                    "sample_id": sample_id,
                    "fault_id": fault_id,
                    "fault_type": fault_type,
                    "node_count": scale,
                    "scale_rung": str(scale),
                    "event_name": event_name,
                    "event_status": "OBSERVED",
                    "timestamp_unix_ms": 100000 + fault_index * 1000 + event_index,
                    "monotonic_ms": float(fault_index * 1000 + event_index),
                    "source": "test",
                    "subject_type": "cluster",
                    "subject_id": "cluster",
                    "real_valkey": True,
                    "execution_mode": "fake" if mode == "event_fake" and fault_index == 1 else "real_docker_valkey",
                    "reason": "",
                }
            )
        metrics: dict[str, object] = {metric: float(fault_index) for metric in H07_REQUIRED_TIMELINE_METRICS}
        if metric_defect and fault_index == 1:
            if metric_defect == "missing":
                metrics.pop("failover_latency_ms")
            elif metric_defect == "string":
                metrics["failover_latency_ms"] = "1.0"
            elif metric_defect == "skipped":
                metrics["failover_latency_ms"] = {"status": "SKIPPED_WITH_REASON", "reason": "test"}
            elif metric_defect == "bool":
                metrics["failover_latency_ms"] = True
            elif metric_defect == "null":
                metrics["failover_latency_ms"] = None
        workload_refs: list[str] = [] if mode == "missing_workload_ref" and fault_index == 1 else ["workload_windows.json"]
        cleanup_ref = "missing_cleanup_report.json" if mode == "missing_cleanup_ref" and fault_index == 1 else "cleanup_report.json"
        rows.append(
            {
                "schema_version": "v1",
                "phase_id": phase_by_scale[scale],
                "run_id": f"h07-{scale}",
                "scenario_name": f"fault-{scale}",
                "sample_id": sample_id,
                "fault_id": fault_id,
                "fault_type": fault_type,
                "node_count": scale,
                "scale_rung": str(scale),
                "status": "PARTIAL" if mode == "row_partial" and fault_index == 1 else "PASS",
                "execution_mode": "real_docker_valkey",
                "real_valkey": False if mode == "row_non_real" and fault_index == 1 else True,
                "timeline_status": "PARTIAL" if mode == "row_partial" and fault_index == 1 else "PASS",
                "timeline_event_refs": [f"fault_timeline_events.jsonl#{sample_id}:{event}" for event in H07_REQUIRED_TIMELINE_EVENTS],
                "metrics": metrics,
                "metric_sources": {metric: "fault_timeline_events.jsonl+workload_windows.json" for metric in H07_REQUIRED_TIMELINE_METRICS},
                "workload_window_refs": workload_refs,
                "cleanup_ref": cleanup_ref,
                "valkey_e2e_evidence_ref": "valkey_e2e_evidence.json",
                "clean_cluster_evidence": {"status": "PASS", "ref": cleanup_ref},
                "host_network_mutation": False,
            }
        )
        samples.append(
            {
                "schema_version": "v1",
                "phase_id": phase_by_scale[scale],
                "node_count": scale,
                "sample_id": sample_id,
                "target_primary_logical_id": "node-0000",
                "fault_injected_at_ms": 1000,
                "replica_promoted_at_ms": 1010,
                "slot_coverage_ok_at_ms": 1020,
                "first_successful_read_at_ms": 1030,
                "first_successful_write_at_ms": 1040,
                "promotion_latency_ms": 10.0,
                "cluster_recovery_latency_ms": 20.0,
                "read_unavailability_ms": 30.0,
                "write_unavailability_ms": 40.0,
                "workload_impact_ref": "workload_windows.json",
                "timeline_ref": f"fault_timeline_events.jsonl#{sample_id}",
                "fault_type": fault_type,
                "fault_id": fault_id,
                "source_event_start": "failover_started",
                "source_event_end": "cluster_recovered",
                "derived_from_timeline": False if mode == "legacy_sample" and fault_index == 1 else True,
                "workload_recovery_ref": "workload_windows.json",
            }
        )
    _write_jsonl(phase / "fault_timeline_events.jsonl", events)
    _write_jsonl(phase / "failover_latency_samples.jsonl", samples)
    write_json(
        phase / "fault_timeline_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "fault_timeline_report",
            "phase_id": phase_by_scale[scale],
            "run_id": f"h07-{scale}",
            "status": "PARTIAL" if mode == "report_partial" else "PASS",
            "required_fault_types": H07_REQUIRED_FAULT_TYPES,
            "observed_fault_types": sorted(fault_types),
            "required_scale_rungs": ["small", "30", "50", "100", "200"],
            "observed_scale_rungs": [str(scale)],
            "timeline_events_ref": "fault_timeline_events.jsonl",
            "failover_latency_samples_ref": "failover_latency_samples.jsonl",
            "fault_workload_impact_ref": "workload_windows.json",
            "fault_rows": rows,
            "missing_metrics": [],
        },
    )
    return phase


def _write_valkey_e2e_custom(phase: Path, nodes_observed: int, versions: list[str]) -> None:
    write_json(
        phase / "valkey_e2e_evidence.json",
        {
            "schema_version": "v1",
            "artifact_type": "valkey_e2e_evidence",
            "status": "PASS",
            "real_valkey": True,
            "nodes_requested": nodes_observed,
            "nodes_observed": nodes_observed,
            "cluster_state_observed": "ok",
            "valkey_versions": versions,
        },
    )


def _claim(manifest: dict[str, object], cid: str) -> dict[str, object]:
    for claim in manifest["claims"]:  # type: ignore[index]
        if isinstance(claim, dict) and claim.get("claim_id") == cid:
            return claim
    raise AssertionError(f"claim {cid} missing")


def _write_setup_exact_scale_evidence(
    tmp_path: Path,
    scale: int,
    *,
    metric_overrides: dict[str, object] | None = None,
    sample_overrides: dict[int, dict[str, object]] | None = None,
) -> None:
    phase_by_scale = {
        30: "P12_SCALE_LADDER_10_30",
        50: "P30_MANAGEMENT_MATRIX_50_REAL",
        100: "P31_MANAGEMENT_MATRIX_100_REAL",
        200: "P32_MANAGEMENT_MATRIX_200_REAL",
    }
    phase = tmp_path / "artifacts" / "phases" / phase_by_scale[scale]
    write_json(phase / "setup_telemetry.json", _setup_telemetry_payload(scale, metric_overrides=metric_overrides, sample_overrides=sample_overrides))
    _write_valkey_e2e(phase, scale)


def _setup_telemetry_payload(
    scale: int,
    *,
    metric_overrides: dict[str, object] | None = None,
    sample_overrides: dict[int, dict[str, object]] | None = None,
) -> dict[str, object]:
    metrics: dict[str, object] = {metric: 10.0 for metric in C06_SETUP_CORE_METRICS}
    metrics.update(
        {
            "config_parse_ms": 1.0,
            "config_validate_ms": 1.0,
            "resource_preflight_ms": 1.0,
            "plan_build_ms": 1.0,
            "port_check_ms": 1.0,
        }
    )
    if metric_overrides:
        metrics.update(metric_overrides)
    samples: list[dict[str, object]] = []
    for index in range(scale):
        sample = {
            "logical_id": f"node-{index:04d}",
            "nodehost_id": f"nodehost-{index % 2}",
            "node_ready_ms": float(index + 1),
            "node_ping_ready_ms": float(index + 1),
            "node_cluster_known_nodes": scale,
            "node_cluster_state": "ok",
            "node_role": "primary" if index % 2 == 0 else "replica",
            "node_pid": 1000 + index,
        }
        if sample_overrides and index in sample_overrides:
            sample.update(sample_overrides[index])
        samples.append(sample)
    return {
        "schema_version": "v1",
        "artifact_type": "setup_telemetry",
        "phase_id": "test",
        "run_id": "test",
        "scenario": "test",
        "created_at": "2026-01-01T00:00:00Z",
        "producer": {"name": "test", "version": "v1"},
        "status": "PASS",
        "node_count": scale,
        "same_schema_scale_rungs": [30, 50, 100, 200],
        "metrics": metrics,
        "per_node_samples": samples,
        "per_nodehost_samples": [
            {
                "nodehost_id": "nodehost-0",
                "az_id": "az-a",
                "host_id": "local",
                "container_name": "nodehost-0",
                "nodehost_start_ms": 10.0,
                "nodehost_process_count": scale,
            }
        ],
        "slowest_nodes_topN": samples[:1],
        "slowest_replica_replicate_topN": samples[1:2] or samples[:1],
        "cleanup": {"status": "PASS", "cleanup_ms": 10.0, "resources_remaining": []},
        "missing_metrics": [],
        "source_artifacts": [],
    }


def _write_valkey_e2e(phase: Path, scale: int) -> None:
    write_json(
        phase / "valkey_e2e_evidence.json",
        {
            "schema_version": "v1",
            "artifact_type": "valkey_e2e_evidence",
            "status": "PASS",
            "real_valkey": True,
            "nodes_requested": scale,
            "nodes_observed": scale,
            "cluster_state_observed": "ok",
            "valkey_versions": ["9.1.0"],
        },
    )


def _write_system_metrics_exact_scale_evidence(
    tmp_path: Path,
    scale: int,
    *,
    omit_window: str | None = None,
    row_defect: str | None = None,
    omit_node_index: int | None = None,
    valkey_versions: list[str] | None = None,
    extra_node: bool = False,
) -> Path:
    phase_by_scale = {
        30: "P12_SCALE_LADDER_10_30",
        50: "P30_MANAGEMENT_MATRIX_50_REAL",
        100: "P31_MANAGEMENT_MATRIX_100_REAL",
        200: "P32_MANAGEMENT_MATRIX_200_REAL",
    }
    phase = tmp_path / "artifacts" / "phases" / phase_by_scale[scale]
    windows = ["setup", "workload", "cleanup"] if scale == 30 else ["setup", "management", "workload", "fault_or_failover", "cleanup"]
    windows = [window for window in windows if window != omit_window]
    metric_templates = [
        ("docker_stats", "cpu_percent", "percent"),
        ("docker_stats", "memory_rss_bytes", "bytes"),
        ("system_network", "rx_bytes", "bytes"),
        ("valkey_info", "connected_clients", "count"),
        ("cluster_info", "cluster_known_nodes", "count"),
    ]
    rows: list[dict[str, object]] = []
    for node_index in range(scale):
        if node_index == omit_node_index:
            continue
        for window in windows:
            for metric_index, (source_type, metric_name, unit) in enumerate(metric_templates, start=1):
                value: object = float(node_index + metric_index)
                missing_reason = ""
                if row_defect == "skip_valkey_info" and source_type == "valkey_info":
                    value = "SKIPPED_WITH_REASON"
                    missing_reason = "test deliberately skipped valkey info group"
                row: dict[str, object] = {
                    "schema_version": "v1",
                    "phase_id": phase_by_scale[scale],
                    "run_id": f"h08-{scale}",
                    "scenario_name": f"system-metrics-{scale}",
                    "sample_id": f"node-{node_index:04d}-{window}-{metric_name}",
                    "node_count": scale,
                    "node_id": f"node-{node_index:04d}",
                    "lifecycle_window": window,
                    "timestamp_unix_ms": 100000 + node_index,
                    "monotonic_ms": float(1000 + node_index),
                    "source_type": source_type,
                    "source_id": f"node-{node_index:04d}",
                    "metric_name": metric_name,
                    "metric_value": value,
                    "metric_unit": unit,
                    "labels": {
                        "window": window,
                        "lifecycle_window": window,
                        "stage_window": window,
                        "logical_node_id": f"node-{node_index:04d}",
                    },
                    "missing_reason": missing_reason,
                }
                if row_defect == "missing_timestamp" and not rows:
                    row.pop("timestamp_unix_ms")
                if row_defect == "labels_only_node_window":
                    row.pop("node_id")
                    row.pop("lifecycle_window")
                rows.append(row)
    if extra_node:
        extra_rows = []
        for row in rows[: len(metric_templates) * len(windows)]:
            copied = dict(row)
            copied["node_id"] = f"node-{scale:04d}"
            copied["source_id"] = f"node-{scale:04d}"
            copied["sample_id"] = f"node-{scale:04d}-{copied.get('lifecycle_window')}-{copied.get('metric_name')}"
            labels = dict(copied.get("labels", {})) if isinstance(copied.get("labels"), dict) else {}
            labels["logical_node_id"] = f"node-{scale:04d}"
            labels["node_id"] = f"node-{scale:04d}"
            copied["labels"] = labels
            extra_rows.append(copied)
        rows.extend(extra_rows)
    _write_jsonl(phase / "system_metrics_timeseries.jsonl", rows)
    if valkey_versions is None:
        _write_valkey_e2e(phase, scale)
    else:
        _write_valkey_e2e_custom(phase, scale, valkey_versions)
    rows_by_window = {
        window: sum(
            1
            for row in rows
            if (row.get("lifecycle_window") or (row.get("labels", {}) if isinstance(row.get("labels"), dict) else {}).get("lifecycle_window")) == window
        )
        for window in windows
    }
    rows_by_node: dict[str, int] = {}
    for row in rows:
        labels = row.get("labels", {}) if isinstance(row.get("labels"), dict) else {}
        node_id = str(row.get("node_id") or labels.get("logical_node_id") or labels.get("node_id"))
        rows_by_node[node_id] = rows_by_node.get(node_id, 0) + 1
    missing_metrics = [
        {
            "node_id": str(row.get("node_id")),
            "metric": str(row.get("metric_name")),
            "status": str(row.get("metric_value")),
            "reason": str(row.get("missing_reason")),
            "window": str(row.get("lifecycle_window")),
        }
        for row in rows
        if row.get("metric_value") == "SKIPPED_WITH_REASON"
    ]
    write_json(
        phase / "system_metrics_report.json",
        {
            "schema_version": "v1",
            "artifact_type": "system_metrics_report",
            "phase_id": phase_by_scale[scale],
            "run_id": f"h08-{scale}",
            "scenario_name": f"system-metrics-{scale}",
            "status": "PASS",
            "node_count": scale,
            "sample_count": len(rows),
            "lifecycle_windows": windows,
            "coverage": {
                "required_metrics": [metric for _source, metric, _unit in metric_templates],
                "observed_metrics": [metric for _source, metric, _unit in metric_templates],
                "missing_required_metrics": [],
                "rows_by_window": rows_by_window,
                "rows_by_node": rows_by_node,
            },
            "missing_metric_count": len(missing_metrics),
            "missing_metrics": missing_metrics,
            "source_refs": {
                "system_metrics_timeseries": "system_metrics_timeseries.jsonl",
                "valkey_e2e_evidence": "valkey_e2e_evidence.json",
            },
        },
    )
    return phase


def _manifest_with_command_rows(tmp_path: Path, scale: int, rows: list[dict[str, object]]) -> dict[str, object]:
    _write_command_audit_exact_scale_evidence(tmp_path, scale, rows=rows)
    return build_manifest(tmp_path)


def _write_command_audit_exact_scale_evidence(
    tmp_path: Path,
    scale: int,
    *,
    rows: list[dict[str, object]] | None = None,
) -> None:
    phase_by_scale = {
        50: "P30_MANAGEMENT_MATRIX_50_REAL",
        100: "P31_MANAGEMENT_MATRIX_100_REAL",
        200: "P32_MANAGEMENT_MATRIX_200_REAL",
    }
    phase = tmp_path / "artifacts" / "phases" / phase_by_scale[scale]
    rows = _command_rows(scale) if rows is None else rows
    _write_jsonl(phase / "command_log.jsonl", rows)
    write_json(phase / "command_audit_summary.json", _command_summary(rows))
    _write_command_output_logs(tmp_path, rows)
    _write_valkey_e2e(phase, scale)


def _command_rows(scale: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    commands = [
        ("cluster_meet", ["valkey-cli", "-p", "7000", "CLUSTER", "MEET", "127.0.0.1", "7001"]),
        ("cluster_addslots", ["valkey-cli", "-p", "7000", "CLUSTER", "ADDSLOTS", "0", "1"]),
        ("cluster_replicate", ["valkey-cli", "-p", "7001", "CLUSTER", "REPLICATE", "abc"]),
        ("cluster_probe", ["valkey-cli", "-p", "7000", "CLUSTER", "INFO"]),
        ("cleanup", ["docker", "rm", "-f", "vslab-nodehost-0"]),
    ]
    for index, (kind, argv) in enumerate(commands, start=1):
        rows.append(
            {
                "schema_version": "v1",
                "artifact_type": "runtime_command_log_entry",
                "phase_id": f"test-{scale}",
                "run_id": f"test-{scale}",
                "scenario": f"scale-{scale}",
                "sequence": index,
                "operation_id": "cluster_setup" if kind != "cleanup" else "cleanup",
                "step_id": kind,
                "command_id": f"cmd-{index:06d}",
                "command_kind": kind,
                "command_scope": "owned_docker_or_local_valkey_client",
                "host_id": "local",
                "node_logical_id": "node-0",
                "nodehost_id": "nh-0",
                "container_name": "vslab-nodehost-0",
                "client_port": 7000,
                "argv": argv,
                "started_at_unix_ms": 1000 + index,
                "ended_at_unix_ms": 1010 + index,
                "duration_ms": 10,
                "exit_code": 0,
                "stdout_path": f"logs/cmd-{index:06d}.stdout.log",
                "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "stderr_path": f"logs/cmd-{index:06d}.stderr.log",
                "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "retry_index": 0,
                "attempt_count": 1,
                "timeout_ms": 30000,
                "status": "PASS",
                "error_type": "",
                "host_network_mutated": False,
                "global_firewall_mutated": False,
                "trace_refs": [],
            }
        )
    assert {str(row["command_kind"]) for row in rows} == C07_REQUIRED_COMMAND_KINDS
    return rows


def _command_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    by_kind: dict[str, int] = {}
    operations: dict[str, list[str]] = {}
    for row in rows:
        by_kind[str(row.get("command_kind"))] = by_kind.get(str(row.get("command_kind")), 0) + 1
        operations.setdefault(str(row.get("operation_id")), []).append(str(row.get("command_id")))
    return {
        "schema_version": "v1",
        "artifact_type": "command_audit_summary",
        "phase_id": "test",
        "run_id": "test",
        "scenario": "test",
        "status": "PASS",
        "command_log_ref": "command_log.jsonl",
        "total_commands": len(rows),
        "pass_count": sum(1 for row in rows if row.get("status") == "PASS"),
        "failure_count": sum(1 for row in rows if row.get("status") == "FAIL"),
        "timeout_count": sum(1 for row in rows if row.get("status") == "TIMEOUT"),
        "retry_count": sum(1 for row in rows if int(row.get("retry_index", 0) or 0) > 0 or row.get("status") == "RETRY"),
        "by_command_kind": by_kind,
        "slowest_commands_topN": [
            {
                "command_id": row.get("command_id"),
                "operation_id": row.get("operation_id"),
                "step_id": row.get("step_id"),
                "command_kind": row.get("command_kind"),
                "duration_ms": row.get("duration_ms"),
                "status": row.get("status"),
                "exit_code": row.get("exit_code"),
                "retry_index": row.get("retry_index"),
                "error_type": row.get("error_type"),
            }
            for row in rows[:5]
        ],
        "failed_commands": [
            {
                "command_id": row.get("command_id"),
                "operation_id": row.get("operation_id"),
                "step_id": row.get("step_id"),
                "command_kind": row.get("command_kind"),
                "duration_ms": row.get("duration_ms"),
                "status": row.get("status"),
                "exit_code": row.get("exit_code"),
                "retry_index": row.get("retry_index"),
                "error_type": row.get("error_type"),
            }
            for row in rows
            if row.get("status") == "FAIL"
        ],
        "timeout_commands": [],
        "retry_commands": [],
        "operation_traceability": [
            {"operation_id": operation_id, "command_log_refs": [f"command_log.jsonl#{command_id}" for command_id in command_ids], "status": "PASS"}
            for operation_id, command_ids in sorted(operations.items())
        ],
        "coverage": {"required_command_kinds": sorted(C07_REQUIRED_COMMAND_KINDS), "observed_command_kinds": sorted(by_kind)},
        "missing_or_skipped": [],
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _write_command_output_logs(tmp_path: Path, rows: list[dict[str, object]]) -> None:
    for row in rows:
        for key in ["stdout_path", "stderr_path"]:
            path_value = row.get(key)
            assert isinstance(path_value, str)
            output = tmp_path / path_value
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("", encoding="utf-8")


def _write_management_exact_scale_evidence(
    tmp_path: Path,
    scale: int,
    *,
    base: Path | None = None,
    command_ref_mode: str = "fragment",
    omit_workload_window: bool = False,
    wrong_command_operation: bool = False,
    bad_command_hash: bool = False,
    bad_matrix_topology_diff_ref: bool = False,
    omit_topology_slots: bool = False,
    string_workload_counts: bool = False,
) -> None:
    phase_by_scale = {
        50: "P30_MANAGEMENT_MATRIX_50_REAL",
        100: "P31_MANAGEMENT_MATRIX_100_REAL",
        200: "P32_MANAGEMENT_MATRIX_200_REAL",
    }
    phase = base or tmp_path / "artifacts" / "phases" / phase_by_scale[scale]
    command_rows: list[dict[str, object]] = []
    matrix_ops: list[dict[str, object]] = []
    result_rows: list[dict[str, object]] = []
    topology_rows: list[dict[str, object]] = []
    topology_diff_rows: list[dict[str, object]] = []
    impact_ops: list[dict[str, object]] = []
    windows: list[dict[str, object]] = []
    for index, op in enumerate(sorted(H05_REQUIRED_MANAGEMENT_OPERATIONS), start=1):
        command_id = f"cmd-{index:06d}"
        command_rows.append(
            {
                "schema_version": "v1",
                "artifact_type": "runtime_command_log_entry",
                "phase_id": f"test-{scale}",
                "run_id": f"test-{scale}",
                "scenario": f"management-{scale}",
                "sequence": index,
                "operation_id": "wrong-operation" if wrong_command_operation and index == 1 else f"h05-{op}-{scale}",
                "step_id": "cluster_probe",
                "command_id": command_id,
                "command_kind": "cluster_probe",
                "command_scope": "owned_docker_or_local_valkey_client",
                "host_id": "local",
                "node_logical_id": "node-0",
                "nodehost_id": "nh-0",
                "container_name": "vslab-nodehost-0",
                "client_port": 7000,
                "argv": ["valkey-cli", "-p", "7000", "CLUSTER", "INFO"],
                "started_at_unix_ms": 1000 + index,
                "ended_at_unix_ms": 1010 + index,
                "duration_ms": 10,
                "exit_code": 0,
                "stdout_path": f"logs/management-{command_id}.stdout.log",
                "stdout_sha256": "1" * 64 if bad_command_hash and index == 1 else "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "stderr_path": f"logs/management-{command_id}.stderr.log",
                "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "retry_index": 0,
                "attempt_count": 1,
                "timeout_ms": 30000,
                "status": "PASS",
                "error_type": "",
                "host_network_mutated": False,
                "global_firewall_mutated": False,
                "trace_refs": [],
            }
        )
        command_ref = f"management_command_log.jsonl#{command_id}" if command_ref_mode == "fragment" else "management_command_log.jsonl"
        op_id = f"h05-{op}-{scale}"
        window_id = f"{op_id}:event"
        before = f"{op_id}-before"
        after = f"{op_id}-after"
        topology_diff_ref = f"management_topology_diffs.jsonl#{op_id}"
        topology_rows.extend(
            [
                {"label": before, "operation_id": op_id, **({} if omit_topology_slots and index == 1 else {"slots": 16384}), "nodes": _topology_nodes(scale)},
                {"label": after, "operation_id": op_id, **({} if omit_topology_slots and index == 1 else {"slots": 16384}), "nodes": _topology_nodes(scale)},
            ]
        )
        if not omit_workload_window:
            windows.append(
                {
                    "id": window_id,
                    "window_id": window_id,
                    "operation_id": op_id,
                    "window_name": "event",
                    "start_event_id": f"{op_id}-start",
                    "end_event_id": f"{op_id}-end",
                    "status": "PASS",
                    "metrics": {
                        "requested_qps": 100.0,
                        "achieved_qps": 100.0,
                        "throughput_ratio": 1.0,
                        "ok_ops": 100,
                        "error_ops": 0,
                        "error_rate": 0.0,
                        "latency_p50_ms": 1.0,
                        "latency_p90_ms": 1.5,
                        "latency_p95_ms": 2.0,
                        "latency_p99_ms": 2.5,
                        "latency_p999_ms": 3.0,
                        "timeout_count": "0" if string_workload_counts and index == 1 else 0,
                        "connection_error_count": 0,
                        "moved_count": "0" if string_workload_counts and index == 1 else 0,
                        "ask_count": "0" if string_workload_counts and index == 1 else 0,
                        "cluster_down_count": 0,
                        "readonly_count": 0,
                        "tryagain_count": 0,
                    },
                }
            )
        impact_ops.append({"operation_id": op_id, "operation_name": op, "coverage_id": f"{scale}.management.{op}", "window_refs": [window_id]})
        topology_diff_rows.append(
            {
                "schema_version": "v1",
                "artifact_type": "management_topology_diff",
                "phase_id": phase_by_scale[scale],
                "run_id": f"test-{scale}",
                "operation_id": op_id,
                "before_snapshot_ref": before,
                "after_snapshot_ref": after,
                "slot_diff": {"status": "PASS"},
                "role_diff": {"status": "PASS"},
                "known_nodes_delta": 0,
                "fail_pfail_handshake_delta": {"fail": 0, "pfail": 0, "handshake": 0},
                "changed_nodes": [],
                "moved_slots": [],
                "status": "PASS",
            }
        )
        common = {
            "coverage_id": f"{scale}.management.{op}",
            "operation_id": op_id,
            "operation_name": op,
            "node_count": scale,
            "operation_status": "PASS",
            "real_execution_verified": True,
            "command_log_ref": command_ref,
            "workload_window_ref": window_id,
        }
        matrix_ops.append(
            {
                **common,
                "scale": scale,
                "operation_result_ref": f"management_operation_results.jsonl#{op_id}",
                "before_topology_snapshot_ref": before,
                "after_topology_snapshot_ref": after,
                "topology_diff_ref": "management_topology_diffs.jsonl#bogus" if bad_matrix_topology_diff_ref and index == 1 else topology_diff_ref,
                "command_count": 1,
                "command_log_refs": [command_ref],
                "workload_impact_ref": f"management_workload_impact.json#{op_id}",
                "cleanup_ref": "cleanup_report.json",
                "topology_refs": [before, after],
            }
        )
        result_rows.append(
            {
                **common,
                "schema_version": "v1",
                "artifact_type": "management_operation_result",
                "phase_id": phase_by_scale[scale],
                "run_id": f"test-{scale}",
                "scenario": f"management-{scale}",
                "scale": scale,
                "started_at_unix_ms": 1000 + index,
                "ended_at_unix_ms": 2000 + index,
                "duration_ms": 100.0,
                "operation_duration_ms": 100.0,
                "wall_ms": 100.0,
                "prepare_ms": 0.0,
                "command_ms": 10.0,
                "convergence_ms": 1.0,
                "cleanup_ms": 0.0,
                "status_reason": "test pass",
                "before_topology_snapshot": {"ref": before},
                "after_topology_snapshot": {"ref": after},
                "before_topology_snapshot_ref": before,
                "after_topology_snapshot_ref": after,
                "topology_diff": {"ref": topology_diff_ref},
                "topology_diff_ref": topology_diff_ref,
                "slot_diff": {"status": "PASS"},
                "role_diff": {"status": "PASS"},
                "cluster_state_before": "ok",
                "cluster_state_after": "ok",
                "known_nodes_before": scale,
                "known_nodes_after": scale,
                "fail_pfail_handshake_before": {"fail": 0, "pfail": 0, "handshake": 0},
                "fail_pfail_handshake_after": {"fail": 0, "pfail": 0, "handshake": 0},
                "command_count": 1,
                "retry_count": 0,
                "error_count": 0,
                "command_log_refs": [command_ref],
                "workload_impact_ref": f"management_workload_impact.json#{op_id}",
                "cleanup_ref": "cleanup_report.json",
                "cluster_known_nodes_before": scale,
                "cluster_known_nodes_after": scale,
                "slots_before": 16384,
                "slots_after": 16384,
                "topology_before_ref": before,
                "topology_after_ref": after,
                "source_evidence_refs": ["management_operation_results.jsonl", "management_command_log.jsonl"],
                "missing_fields": [],
            }
        )
    write_json(
        phase / "management_ops_matrix.json",
        {
            "schema_version": "v1",
            "artifact_type": "management_ops_matrix",
            "phase_id": phase_by_scale[scale],
            "run_id": f"test-{scale}",
            "scenario": f"management-{scale}",
            "status": "PASS",
            "required_operations": sorted(H05_REQUIRED_MANAGEMENT_OPERATIONS),
            "operations": matrix_ops,
        },
    )
    _write_jsonl(phase / "management_operation_results.jsonl", result_rows)
    _write_jsonl(phase / "management_topology_snapshots.jsonl", topology_rows)
    _write_jsonl(phase / "management_topology_diffs.jsonl", topology_diff_rows)
    _write_jsonl(phase / "management_command_log.jsonl", command_rows)
    _write_command_output_logs(tmp_path, command_rows)
    write_json(phase / "management_workload_impact.json", {"schema_version": "v1", "artifact_type": "workload_impact_report", "phase_id": phase_by_scale[scale], "run_id": f"test-{scale}", "status": "PASS", "windows": windows, "comparisons": [], "operations": impact_ops})
    write_json(phase / "workload_windows.json", {"schema_version": "v1", "artifact_type": "workload_windows", "phase_id": phase_by_scale[scale], "run_id": f"test-{scale}", "status": "PASS", "windows": windows})
    _write_valkey_e2e(phase, scale)


def _write_workload_benchmark_exact_scale_evidence(
    tmp_path: Path,
    scale: int,
    *,
    base: Path | None = None,
    omit_profile: str | None = None,
    omit_window: tuple[str, str] | None = None,
    shallow_metric_rows: bool = False,
    metric_defect: str | None = None,
    low_ops: bool = False,
    omit_connection_evidence: bool = False,
    omit_pipeline_evidence: bool = False,
    full_slot_defect: str | None = None,
) -> Path:
    phase_by_scale = {
        30: "P12_SCALE_LADDER_10_30",
        50: "P30_MANAGEMENT_MATRIX_50_REAL",
        100: "P31_MANAGEMENT_MATRIX_100_REAL",
        200: "P32_MANAGEMENT_MATRIX_200_REAL",
    }
    phase = base or tmp_path / "artifacts" / "phases" / phase_by_scale[scale]
    profiles = [profile for profile in H06_REQUIRED_WORKLOAD_PROFILES if profile != omit_profile]
    coverage = {profile: _workload_slot_coverage(full=True) for profile in profiles}
    if full_slot_defect and "uniform" in coverage:
        coverage["uniform"] = _workload_slot_coverage(full=False, fixed=full_slot_defect == "fixed_hash_tag")
    windows: list[dict[str, object]] = []
    metric_rows: list[dict[str, object]] = []
    for profile in profiles:
        for window_name in H06_REQUIRED_WORKLOAD_WINDOWS:
            if omit_window == (profile, window_name):
                continue
            metrics = _h06_workload_metrics()
            if low_ops and profile == "uniform" and window_name == "event":
                metrics["ok_ops"] = 1
                metrics["error_ops"] = 0
            if metric_defect and profile == "uniform" and window_name == "event":
                if metric_defect == "missing":
                    metrics.pop("latency_p99_ms")
                elif metric_defect == "string":
                    metrics["latency_p99_ms"] = "4"
                elif metric_defect == "skipped":
                    metrics["latency_p99_ms"] = {"status": "SKIPPED_WITH_REASON", "reason": "test"}
            slot_coverage = coverage.get(profile, _workload_slot_coverage(full=True))
            windows.append(
                {
                    "window_name": window_name,
                    "profile": profile,
                    "workload_mode": "smoke" if profile == "smoke" else "benchmark",
                    "status": "PASS",
                    "start_event_id": f"evt-start-{profile}-{window_name}",
                    "end_event_id": f"evt-end-{profile}-{window_name}",
                    "key_slot_coverage": slot_coverage,
                    "config": {"target_qps": 100, "connections": 8, "pipeline": 4},
                    "metrics": metrics,
                }
            )
            for metric_name in H06_REQUIRED_WORKLOAD_METRICS:
                if shallow_metric_rows and metric_rows:
                    continue
                metric_rows.append(
                    {
                        "schema_version": "v1",
                        "run_id": f"h06-{scale}",
                        "phase_id": phase_by_scale[scale],
                        "scenario_name": f"workload-{scale}",
                        "sample_id": f"{profile}-{window_name}-{metric_name}",
                        "timestamp_unix_ms": 1000,
                        "monotonic_ms": 1000.0,
                        "source_type": "workload",
                        "source_id": f"{profile}:{window_name}",
                        "metric_name": metric_name,
                        "metric_value": metrics.get(metric_name, 1.0),
                        "metric_unit": "count" if metric_name.endswith("_count") or metric_name.endswith("_ops") else "ms" if metric_name.startswith("latency_") else "ratio" if metric_name == "error_rate" else "ops_per_second" if metric_name.endswith("qps") else "value",
                        "labels": {"profile": profile, "window_name": window_name},
                        "missing_reason": "",
                    }
                )
    workload: dict[str, object] = {
        "schema_version": "v1",
        "artifact_type": "workload_windows",
        "phase_id": phase_by_scale[scale],
        "run_id": f"h06-{scale}",
        "status": "PASS",
        "workload_mode": "benchmark",
        "profiles_covered": profiles,
        "hash_slot_coverage": coverage,
        "windows": windows,
    }
    if not omit_connection_evidence:
        workload["connection_evidence"] = {"status": "PASS", "observed": True, "observed_connections": 8, "source": "client_probe"}
    if not omit_pipeline_evidence:
        workload["pipeline_evidence"] = {"status": "PASS", "observed": True, "observed_pipeline": 4, "source": "client_probe"}
    write_json(phase / "workload_windows.json", workload)
    _write_jsonl(phase / "metrics_timeseries.jsonl", metric_rows)
    _write_valkey_e2e(phase, scale)
    return phase


def _h06_workload_metrics() -> dict[str, object]:
    return {
        "requested_qps": 100.0,
        "achieved_qps": 96.0,
        "throughput_ratio": 0.96,
        "ok_ops": 6,
        "error_ops": 0,
        "error_rate": 0.0,
        "latency_p50_ms": 1.0,
        "latency_p90_ms": 2.0,
        "latency_p95_ms": 3.0,
        "latency_p99_ms": 4.0,
        "latency_p999_ms": 5.0,
        "timeout_count": 0,
        "connection_error_count": 0,
        "moved_count": 0,
        "ask_count": 0,
        "cluster_down_count": 0,
        "readonly_count": 0,
        "tryagain_count": 0,
    }


def _workload_slot_coverage(*, full: bool, fixed: bool = False) -> dict[str, object]:
    return {
        "hash_slot_distribution": "single_tag" if fixed else "full_slot",
        "slot_count_observed": 1 if fixed else 100 if not full else 16384,
        "slot_sample": [0] if fixed else [0, 1],
        "full_slot_requested": True,
        "full_slot_covered": full and not fixed,
        "fixed_hash_tag_only": fixed,
    }


def _topology_nodes(scale: int) -> list[dict[str, object]]:
    return [
        {
            "logical_id": f"node-{index:04d}",
            "node_id": f"{index:040x}"[-40:],
            "role": "primary" if index % 2 == 0 else "replica",
            "flags": ["master"] if index % 2 == 0 else ["slave"],
            "link_state": "connected",
            "slots": [index] if index % 2 == 0 else [],
        }
        for index in range(scale)
    ]


def _seed_stage_exit_base(tmp_path: Path, stage_id: str, required_gates: list[str]) -> None:
    for script in REQUIRED_SCRIPTS:
        path = tmp_path / "scripts" / "m1h" / script
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# script\n", encoding="utf-8")
    write_json(tmp_path / "runs" / "m1-hardening" / "evidence_manifest.json", {"claims": []})
    stage = tmp_path / "runs" / "m1-hardening" / stage_id
    for gate in required_gates:
        write_json(stage / "artifacts" / "gates" / f"{gate}.json", _gate_payload(stage_id, gate))
    for rel in ["agents/design.md", "agents/worker.md", "agents/review.md", "handoff/DESIGN_BRIEF.md", "handoff/WORKER_SUMMARY.md"]:
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    (stage / "handoff" / "REVIEW.md").write_text("Decision: PASS\n", encoding="utf-8")


def _minimal_acceptance_reset(
    tmp_path: Path,
    *,
    blocked_reason: str,
    stage_id: str = "H01_EVIDENCE_TAXONOMY_AND_FALSE_PASS_RESET",
    artifact_type: str = "milestone1_acceptance_reset",
) -> dict[str, object]:
    claims = [
        {
            "claim_id": claim_id(capability, scale),
            "capability": capability,
            "scale": scale,
            "required_for_milestone_pass": True,
            "evidence_kind": "BLOCKED_WITH_REASON",
            "source_status": "BLOCKED_WITH_REASON",
            "acceptance_status": "BLOCKED_WITH_REASON",
            "reason": blocked_reason,
            "semantic_checks": {"exact_scale_observed": False},
            "source_artifacts": [],
        }
        for capability, scale in REQUIRED_CLAIMS
    ]
    return {
        "schema_version": "v1",
        "artifact_type": artifact_type,
        "stage_id": stage_id,
        "hardening_loop_status": "PASS",
        "milestone1_status": "BLOCKED_WITH_REASON",
        "false_pass_prevented": True,
        "required_claim_count": len(REQUIRED_CLAIMS),
        "passed_claim_count": 0,
        "blocked_claim_count": len(REQUIRED_CLAIMS),
        "failed_claim_count": 0,
        "claims": claims,
        "missing_claims": [claim["claim_id"] for claim in claims],
        "blocked_reasons": [blocked_reason],
        "source_manifest": "runs/m1-hardening/evidence_manifest.json",
    }


def _passing_semantic_checks(claim: str) -> dict[str, object]:
    capability = claim.split(".real_exact.", 1)[0]
    base: dict[str, object] = {
        "m1_format_fields_complete": True,
        "hardening_stage_accepted": True,
        "exact_scale_observed": True,
    }
    required = {
        "setup_telemetry": [
            "real_valkey_verified",
            "valkey_9_1_verified",
            "setup_telemetry_artifact_present",
            "setup_telemetry_exact_scale",
            "setup_telemetry_status_pass",
            "setup_core_metrics_numeric",
            "setup_per_node_samples_complete",
        ],
        "command_audit": [
            "real_valkey_verified",
            "valkey_9_1_verified",
            "command_audit_summary_present",
            "command_audit_summary_schema_valid",
            "command_log_present",
            "command_log_non_empty",
            "command_log_schema_valid",
            "required_command_kinds_present",
            "no_placeholder_commands",
            "command_kind_argv_consistent",
            "command_output_refs_present",
            "output_hashes_verified",
            "retry_failure_timeout_summary_present",
            "operation_traceability_present",
            "failure_timeout_retry_rows_summarized",
            "summary_missing_or_skipped_empty",
            "empty_legacy_management_log_absent",
        ],
        "management_matrix": [
            "real_valkey_verified",
            "valkey_9_1_verified",
            "management_matrix_present",
            "management_matrix_schema_valid",
            "management_matrix_status_pass",
            "management_required_operations_present",
            "operation_results_present",
            "operation_results_schema_valid",
            "operation_results_exact_scale",
            "operation_semantics_present",
            "topology_refs_resolve",
            "topology_diff_present",
            "topology_diff_schema_valid",
            "topology_diff_refs_resolve",
            "workload_telemetry_present",
            "workload_artifacts_schema_valid",
            "workload_metrics_numeric",
            "workload_refs_resolve",
            "command_refs_resolve",
            "command_refs_c07_valid",
            "command_refs_operation_traceable",
            "topology_exact_health",
            "no_fixture_management_artifacts",
        ],
        "workload_benchmark": [
            "real_valkey_verified",
            "valkey_9_1_verified",
            "workload_windows_present",
            "workload_windows_schema_valid",
            "workload_windows_status_pass",
            "workload_profiles_complete",
            "workload_windows_complete",
            "workload_required_metrics_numeric",
            "metrics_timeseries_present",
            "metrics_timeseries_schema_valid",
            "metrics_row_count_sufficient",
            "metrics_rows_cover_required_matrix",
            "metrics_core_values_numeric",
            "operations_per_window_sufficient",
            "connection_evidence_observed",
            "pipeline_evidence_observed",
            "full_slot_coverage_non_smoke",
            "fake_or_partial_not_promoted",
            "no_fixture_workload_artifacts",
        ],
        "fault_timeline": [
            "real_valkey_verified",
            "valkey_9_1_verified",
            "same_directory_bundle",
            "fault_timeline_report_present",
            "fault_timeline_report_schema_valid",
            "fault_timeline_report_status_pass",
            "fault_timeline_events_present",
            "fault_timeline_events_schema_valid",
            "failover_latency_samples_present",
            "failover_latency_samples_schema_valid",
            "fault_required_types_present",
            "fault_required_events_present",
            "fault_required_metrics_numeric",
            "fault_rows_status_pass",
            "fault_rows_exact_scale",
            "fault_rows_real_valkey",
            "fault_execution_mode_real",
            "workload_refs_resolve",
            "workload_h06_dependency_accepted",
            "cleanup_refs_resolve",
            "clean_cluster_evidence",
            "no_fixture_fault_artifacts",
            "fake_or_partial_not_promoted",
            "no_legacy_fault_promotion",
        ],
        "system_metrics": [
            "real_valkey_verified",
            "valkey_9_1_verified",
            "same_directory_bundle",
            "system_metrics_report_present",
            "system_metrics_report_schema_valid",
            "system_metrics_report_status_pass",
            "system_metrics_report_semantics_valid",
            "system_metrics_timeseries_present",
            "system_metrics_timeseries_schema_valid",
            "system_rows_exact_scale",
            "lifecycle_windows_present",
            "node_coverage_complete",
            "high_value_numeric_coverage",
            "high_value_window_coverage",
            "missing_values_structured",
            "source_refs_resolve",
            "fake_or_partial_not_promoted",
            "no_fixture_system_artifacts",
        ],
        "report": ["report_index_present", "accepted_inputs_only"],
        "cleanup": ["cleanup_report_clean"],
    }
    for name in required.get(capability, []):
        base[name] = True
    return base


def _gate_payload(stage_id: str, gate_name: str) -> dict[str, object]:
    return {
        "schema_version": "v1",
        "artifact_type": "m1h_gate_result",
        "stage_id": stage_id,
        "gate_name": gate_name,
        "status": "PASS",
        "checked_at": "2026-01-01T00:00:00Z",
        "inputs": [],
        "violations": [],
        "blocked_reasons": [],
        "source_commit": "abc",
    }
