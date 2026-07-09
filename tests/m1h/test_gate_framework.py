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
from assert_stage_exit import H00_REQUIRED_GATE_RESULTS, H01_REQUIRED_GATE_RESULTS, H02_REQUIRED_GATE_RESULTS, H03_REQUIRED_GATE_RESULTS, H04_REQUIRED_GATE_RESULTS, REQUIRED_SCRIPTS, validate_stage_exit
from build_acceptance_reset import build_acceptance_reset, validate_acceptance_report
from capability_gate import evaluate_capability
from assert_command_audit_real import evaluate_command_audit_real
from common import gate_result_path, write_gate_result, write_json
from manifest import C06_SETUP_CORE_METRICS, C07_REQUIRED_COMMAND_KINDS, REQUIRED_CLAIMS, build_manifest, claim_id


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
        "management_matrix": ["management_matrix_present", "operation_semantics_present", "workload_telemetry_present"],
        "workload_benchmark": ["workload_windows_present", "qps_latency_error_metrics_present"],
        "fault_timeline": ["fault_timeline_present", "real_fault_events_present", "fake_or_partial_not_promoted"],
        "system_metrics": ["system_windows_present", "core_metrics_present"],
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
