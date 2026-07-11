from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_committed_artifacts.py"
P13_ID = "P13_SCALE_LADDER_50_100"
P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"

spec = importlib.util.spec_from_file_location("audit_committed_artifacts", SCRIPT)
audit_committed_artifacts = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(audit_committed_artifacts)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def install_common_schemas(root: Path) -> None:
    schema_dir = root / "schemas" / "artifact"
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "audit_decision.schema.json",
        "audit_report.schema.json",
        "gate_result.schema.json",
        "valkey_e2e_evidence.schema.json",
    ]:
        shutil.copyfile(REPO_ROOT / "schemas" / "artifact" / name, schema_dir / name)
    write_json(
        schema_dir / "minimal_artifact.schema.json",
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["schema_version", "artifact_type", "phase_id", "producer", "run_id", "status"],
            "properties": {
                "schema_version": {"type": "string", "const": "v1"},
                "artifact_type": {"type": "string", "minLength": 1},
                "phase_id": {"type": "string", "minLength": 1},
                "producer": {"type": "object"},
                "run_id": {"type": "string", "minLength": 1},
                "status": {"type": "string", "minLength": 1},
            },
            "additionalProperties": True,
        },
    )


def p14_phase() -> dict[str, Any]:
    return {
        "id": P14_ID,
        "title": "1000 node opt-in dry-run",
        "automatic": False,
        "fake_only_allowed": True,
        "real_valkey_required": False,
        "max_nodes": 1000,
        "objectives": ["Dry-run only"],
        "gates": [
            {
                "name": "planner_1000_dryrun",
                "kind": "planner",
                "command": (
                    "VSLAB_ALLOW_1000_DRYRUN=1 python3 -m valkey_scale_lab.cli plan "
                    "--config templates/configs/scale_1000_dryrun_optin.yaml --dry-run "
                    "--out artifacts/phases/P14_SCALE_1000_OPTIN_DRYRUN/plan.json"
                ),
                "timeout_seconds": 120,
                "required": True,
                "real_valkey": False,
            }
        ],
        "required_artifacts": [],
        "audit": {
            "md_path": "audit/P14_SCALE_1000_OPTIN_DRYRUN/AUDIT.md",
            "decision_json_path": "audit/P14_SCALE_1000_OPTIN_DRYRUN/audit_decision.json",
        },
    }


def phase(
    phase_id: str,
    artifact_path: str,
    *,
    schema: str = "schemas/artifact/minimal_artifact.schema.json",
    gate_name: str = "unit_tests",
    command: str = "python3 -m pytest -q tests/unit",
    real_valkey_required: bool = False,
) -> dict[str, Any]:
    return {
        "id": phase_id,
        "title": phase_id,
        "automatic": True,
        "fake_only_allowed": not real_valkey_required,
        "real_valkey_required": real_valkey_required,
        "max_nodes": 6 if real_valkey_required else 0,
        "objectives": ["fixture"],
        "gates": [
            {
                "name": gate_name,
                "kind": "unit",
                "command": command,
                "timeout_seconds": 120,
                "required": True,
                "real_valkey": real_valkey_required,
            }
        ],
        "required_artifacts": [{"path": artifact_path, "schema": schema, "required": True}],
        "audit": {
            "md_path": f"audit/{phase_id}/AUDIT.md",
            "decision_json_path": f"audit/{phase_id}/audit_decision.json",
        },
    }


def valid_artifact(phase_id: str, artifact_type: str = "phase_summary") -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "artifact_type": artifact_type,
        "phase_id": phase_id,
        "producer": {"name": "fixture", "version": "v1"},
        "run_id": "fixture-run",
        "status": "PASS",
    }


def write_manifest(root: Path, phases: list[dict[str, Any]]) -> str:
    manifest = {
        "version": "v1",
        "project": "valkey-scale-lab",
        "default_max_nodes": 100,
        "valkey_version_required_prefix": "9.1.",
        "automatic_stop_after": phases[-1]["id"],
        "phases": phases + [p14_phase()],
    }
    path = root / "codex" / "phase_manifest.json"
    write_json(path, manifest)
    return sha256_file(path)


def write_gate_result(
    root: Path,
    phase_data: dict[str, Any],
    manifest_sha: str,
    observed_commands: dict[str, str] | None = None,
    manifest_sha_override: str | None = None,
) -> Path:
    phase_id = phase_data["id"]
    gate_records = []
    for gate in phase_data["gates"]:
        stdout_path = root / "artifacts" / "gates" / phase_id / f"{gate['name']}.stdout.log"
        stderr_path = root / "artifacts" / "gates" / phase_id / f"{gate['name']}.stderr.log"
        write_text(stdout_path, "ok\n")
        write_text(stderr_path, "")
        gate_records.append(
            {
                "name": gate["name"],
                "kind": gate["kind"],
                "command": (observed_commands or {}).get(gate["name"], gate["command"]),
                "required": gate["required"],
                "status": "PASS",
                "exit_code": 0,
                "started_at": "2026-06-30T00:00:00Z",
                "finished_at": "2026-06-30T00:00:01Z",
                "duration_seconds": 1.0,
                "stdout_path": rel(root, stdout_path),
                "stderr_path": rel(root, stderr_path),
                "stdout_sha256": sha256_file(stdout_path),
                "stderr_sha256": sha256_file(stderr_path),
            }
        )
    gate_path = root / "artifacts" / "gates" / phase_id / "gate_result.json"
    write_json(
        gate_path,
        {
            "schema_version": "v1",
            "artifact_type": "gate_result",
            "phase_id": phase_id,
            "created_at": "2026-06-30T00:00:01Z",
            "runner": "scripts/codex_gate.py",
            "manifest_sha256": manifest_sha_override or manifest_sha,
            "status": "PASS",
            "gates": gate_records,
        },
    )
    return gate_path


def write_audit_decision(root: Path, phase_data: dict[str, Any], gate_path: Path) -> None:
    phase_id = phase_data["id"]
    write_json(
        root / phase_data["audit"]["decision_json_path"],
        {
            "schema_version": "v1",
            "artifact_type": "audit_decision",
            "phase_id": phase_id,
            "decision": "PASS",
            "fresh_context": True,
            "auditor": "fixture",
            "created_at": "2026-06-30T00:00:02Z",
            "gate_result_path": rel(root, gate_path),
            "gate_result_sha256": sha256_file(gate_path),
            "artifact_paths": [artifact["path"] for artifact in phase_data["required_artifacts"]],
            "risks": [],
            "rationale": "fixture pass",
        },
    )


def write_fixture(
    root: Path,
    phase_data: dict[str, Any],
    artifact_payload: Any | None,
    *,
    observed_commands: dict[str, str] | None = None,
    manifest_sha_override: str | None = None,
) -> None:
    install_common_schemas(root)
    artifact_path = root / phase_data["required_artifacts"][0]["path"]
    if artifact_payload is not None:
        if isinstance(artifact_payload, str):
            write_text(artifact_path, artifact_payload)
        else:
            write_json(artifact_path, artifact_payload)
    manifest_sha = write_manifest(root, [phase_data])
    gate_path = write_gate_result(root, phase_data, manifest_sha, observed_commands, manifest_sha_override)
    write_audit_decision(root, phase_data, gate_path)


def blocking_categories(report: dict[str, Any]) -> set[str]:
    return {finding["category"] for finding in report["findings"] if finding["blocking"]}


def test_fixture_detects_empty_json_and_required_metadata(tmp_path: Path) -> None:
    phase_data = phase("P00_TEST", "artifacts/phases/P00_TEST/empty.json")
    write_fixture(tmp_path, phase_data, {})

    report = audit_committed_artifacts.build_report(tmp_path)

    assert report["status"] == "FAIL"
    categories = blocking_categories(report)
    assert "empty_artifact" in categories
    assert {"missing_producer", "missing_run_id", "missing_status"} <= categories


def test_fixture_detects_missing_required_artifact(tmp_path: Path) -> None:
    phase_data = phase("P00_TEST", "artifacts/phases/P00_TEST/missing.json")
    write_fixture(tmp_path, phase_data, None)

    report = audit_committed_artifacts.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "missing_artifact" in blocking_categories(report)


def test_fixture_detects_invalid_jsonl_artifact(tmp_path: Path) -> None:
    phase_data = phase("P00_TEST", "artifacts/phases/P00_TEST/events.jsonl")
    write_fixture(tmp_path, phase_data, '{"schema_version": "v1"}\nnot-json\n')

    report = audit_committed_artifacts.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "invalid_jsonl" in blocking_categories(report)


def test_fixture_p13_command_mismatch_is_historical_nonblocking(tmp_path: Path) -> None:
    expected = "python3 -m pytest -q tests/scale -m 'not slow and not perf'"
    observed = "python3 -m pytest -q tests/scale"
    artifact = f"artifacts/phases/{P13_ID}/phase_summary.json"
    phase_data = phase(P13_ID, artifact, gate_name="scale_tests", command=expected)
    write_fixture(tmp_path, phase_data, valid_artifact(P13_ID), observed_commands={"scale_tests": observed})

    report = audit_committed_artifacts.build_report(tmp_path)

    mismatch = [
        finding
        for finding in report["findings"]
        if finding["category"] == "gate_command_mismatch" and finding.get("phase_id") == P13_ID
    ]
    assert report["status"] == "PASS"
    assert len(mismatch) == 1
    assert mismatch[0]["classification"] == "historical"
    assert mismatch[0]["blocking"] is False


def test_fixture_unallowlisted_manifest_sha_mismatch_blocks(tmp_path: Path) -> None:
    phase_data = phase("P00_TEST", "artifacts/phases/P00_TEST/phase_summary.json")
    write_fixture(tmp_path, phase_data, valid_artifact("P00_TEST"), manifest_sha_override="0" * 64)

    report = audit_committed_artifacts.build_report(tmp_path)
    manifest_findings = [
        finding for finding in report["findings"] if finding["category"] == "manifest_sha256_mismatch"
    ]

    assert report["status"] == "FAIL"
    assert len(manifest_findings) == 1
    assert manifest_findings[0]["classification"] == "current"
    assert manifest_findings[0]["blocking"] is True
    assert "allowlist=none" in manifest_findings[0]["evidence"]


def test_fixture_p14_boundary_is_dryrun_not_real(tmp_path: Path) -> None:
    phase_data = phase("P00_TEST", "artifacts/phases/P00_TEST/phase_summary.json")
    write_fixture(tmp_path, phase_data, valid_artifact("P00_TEST"))

    report = audit_committed_artifacts.build_report(tmp_path)

    assert report["p14_boundary"]["status"] == "SKIPPED_WITH_REASON"
    assert report["p14_boundary"]["automatic"] is False
    assert report["p14_boundary"]["opt_in_required"] is True
    assert report["p14_boundary"]["dry_run_only"] is True
    assert report["p14_boundary"]["real_evidence_count"] == 0


def test_fixture_real_evidence_failures_are_blocking(tmp_path: Path) -> None:
    artifact = "artifacts/phases/P03_TEST/valkey_e2e_evidence.json"
    command = (
        "python3 scripts/valkey_e2e_gate.py --phase P03_TEST --config fixture.yaml "
        "--scenario cluster_smoke --out artifacts/phases/P03_TEST/valkey_e2e_evidence.json "
        "--min-nodes 6 --require-data-path"
    )
    phase_data = phase(
        "P03_TEST",
        artifact,
        schema="schemas/artifact/valkey_e2e_evidence.schema.json",
        gate_name="real_valkey_e2e",
        command=command,
        real_valkey_required=True,
    )
    payload = {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": "P03_TEST",
        "run_id": "fixture-run",
        "created_at": "2026-06-30T00:00:00Z",
        "producer": {"name": "fixture", "version": "v1"},
        "status": "PASS",
        "real_valkey": False,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS",
        "nodes_observed": 1,
        "cluster_state_observed": "ok",
        "data_path_result": "FAIL",
        "valkey_versions": ["9.1.0"],
        "probes": [{"logical_id": "node-0", "host": "127.0.0.1", "port": 7000, "status": "PASS"}],
        "cleanup": {"status": "PASS"},
    }
    write_fixture(tmp_path, phase_data, payload)

    report = audit_committed_artifacts.build_report(tmp_path)

    categories = blocking_categories(report)
    assert report["status"] == "FAIL"
    assert "real_evidence_real_valkey" in categories
    assert "real_evidence_nodes_observed" in categories
    assert "real_evidence_data_path" in categories


def test_fixture_real_evidence_requires_observed_version_data(tmp_path: Path) -> None:
    artifact = "artifacts/phases/P03_TEST/valkey_e2e_evidence.json"
    command = (
        "python3 scripts/valkey_e2e_gate.py --phase P03_TEST --config fixture.yaml "
        "--scenario cluster_smoke --out artifacts/phases/P03_TEST/valkey_e2e_evidence.json "
        "--min-nodes 6 --require-data-path"
    )
    phase_data = phase(
        "P03_TEST",
        artifact,
        schema="schemas/artifact/valkey_e2e_evidence.schema.json",
        gate_name="real_valkey_e2e",
        command=command,
        real_valkey_required=True,
    )
    payload = {
        "schema_version": "v1",
        "artifact_type": "valkey_e2e_evidence",
        "phase_id": "P03_TEST",
        "run_id": "fixture-run",
        "created_at": "2026-06-30T00:00:00Z",
        "producer": {"name": "fixture", "version": "v1"},
        "status": "PASS",
        "real_valkey": True,
        "valkey_version_prefix_required": "9.1.",
        "probe_result": "PASS",
        "nodes_observed": 6,
        "cluster_state_observed": "ok",
        "data_path_result": "PASS",
        "probes": [
            {
                "logical_id": f"node-{idx}",
                "host": "127.0.0.1",
                "port": 7000 + idx,
                "status": "PASS",
                "cluster_state": "ok",
            }
            for idx in range(6)
        ],
        "cleanup": {"status": "PASS"},
    }
    write_fixture(tmp_path, phase_data, payload)

    report = audit_committed_artifacts.build_report(tmp_path)

    assert report["status"] == "FAIL"
    assert "real_evidence_valkey_versions" in blocking_categories(report)
