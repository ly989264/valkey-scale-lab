#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from schema_validator import load_json, validate  # noqa: E402


P14_ID = "P14_SCALE_1000_OPTIN_DRYRUN"
P13_ID = "P13_SCALE_LADDER_50_100"
P13_HISTORICAL_COMMAND_MISMATCH = "scale_tests"
LEGACY_GATE_MANIFEST_SHA256ES = {
    "87fa9952002f6f606dd10984fd6700d4eb577c7388cb755ece52e4688c2adad4",
    "5f96e9eb5697dba41d9bf0f1d0d5a585b71b7687b3a51c9fcafdb13b6073d7a8",
    "3e23e6820b6fc067709118fb95a5c931ee4bbf2fc4a9ed923c73d2ea9a64cd38",
    "0f8af416b4c1a779daa0bb636e16aadbed80c32df3a650769d21681c1bb75e1f",
    "1d45d63c5ed75f22180d7bc60a842a6f31dad3e8bd82801adf3590f1dfea3b55",
    "28c522f6130fcac3b24ce98f5018f0478c5f202210a704da6eee1990e110bf6b",
    "86305a8ad7823ef5adbd32e0208fdced9a7d712e32866415e7e2c6c8401b3137",
    "9ff6b434f7d72d2fb4d935a7e02ef093c5a5741535c8ae8bc4fc5f7ea5362382",
    "a3f5da2fbd093f8b42a77ad6065d9777d0e337893b09f81ec33f9bc87473034b",
    "b8b5b03cdd1b72af90ccf8155a0bd8e3a1241938f280fce10ef4ef83f09d2033",
    "f9a1fa5debba9e4b034a5ce7205e736c1e902cbb4097d4f19a461a63c68c8a53",
}
LEGACY_GATE_MANIFEST_PHASES = [
    "P00_REPO_CONTRACT",
    "P01_CONFIG_SCHEMA",
    "P02_PLANNER",
    "P03_LOCAL_DOCKER_VALKEY",
    "P04_CLUSTER_MANAGEMENT_OPS",
    "P05_WORKLOAD_ENGINE",
    "P06_OBSERVABILITY_METRICS",
    "P07_FAULT_INJECTION_SANDBOX",
    "P08_FAILOVER_SPLIT_BRAIN",
    "P09_ANALYSIS_REPORTING",
    "P10_MULTI_HOST_ORCHESTRATION",
    "P11_STABILITY_SOAK",
    "P12_SCALE_LADDER_10_30",
    "P13_SCALE_LADDER_50_100",
]
LEGACY_GATE_MANIFEST_ALLOWLIST = {
    phase_id: {
        "id": "legacy_gate_manifest_sha256",
        "sha256es": LEGACY_GATE_MANIFEST_SHA256ES,
        "rationale": (
            "Committed gate results were produced before later manifest revisions; L01 audits these "
            "historical artifacts without rewriting gate_result.json. Any non-allowlisted manifest "
            "hash mismatch remains a blocking current finding."
        ),
    }
    for phase_id in LEGACY_GATE_MANIFEST_PHASES
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


class Audit:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.findings: list[dict[str, Any]] = []
        self._finding_seq = 0

    def finding(
        self,
        *,
        severity: str,
        category: str,
        classification: str,
        blocking: bool,
        description: str,
        evidence: list[str],
        phase_id: str | None = None,
        path: str | None = None,
    ) -> str:
        self._finding_seq += 1
        finding_id = f"CAF-{self._finding_seq:04d}"
        record: dict[str, Any] = {
            "id": finding_id,
            "severity": severity,
            "category": category,
            "classification": classification,
            "blocking": blocking,
            "description": description,
            "evidence": evidence,
        }
        if phase_id:
            record["phase_id"] = phase_id
        if path:
            record["path"] = path
        self.findings.append(record)
        return finding_id


def schema_required_keys(schema: dict[str, Any]) -> set[str]:
    return set(schema.get("required", []))


def load_json_safe(path: Path) -> tuple[Any | None, str | None]:
    try:
        return load_json(path), None
    except Exception as exc:  # noqa: BLE001 - report exact artifact parse failure.
        return None, str(exc)


def read_jsonl(path: Path) -> tuple[list[Any], list[str]]:
    records: list[Any] = []
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"line {lineno}: invalid JSON: {exc}")
    return records, errors


def validate_artifact_record(audit: Audit, phase_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
    root = audit.root
    path_text = artifact["path"]
    schema_text = artifact.get("schema", "")
    path = root / path_text
    schema_path = root / schema_text
    required = bool(artifact.get("required", True))
    finding_ids: list[str] = []
    parse_mode = "jsonl" if path.suffix == ".jsonl" else "json"
    result: dict[str, Any] = {
        "phase_id": phase_id,
        "path": path_text,
        "required": required,
        "exists": path.exists(),
        "empty": False,
        "parse_mode": parse_mode if path.exists() else "missing",
        "json_valid": False,
        "schema_path": schema_text,
        "schema_exists": schema_path.exists(),
        "schema_valid": False,
        "sha256": sha256_file(path) if path.exists() else None,
        "metadata": {
            "artifact_type": None,
            "phase_id": None,
            "producer_present": False,
            "producer_required_by_schema": False,
            "run_id_present": False,
            "run_id_required_by_schema": False,
            "status_present": False,
            "status_required_by_schema": False,
            "status": None,
        },
        "finding_ids": finding_ids,
    }
    if not path.exists():
        finding_ids.append(
            audit.finding(
                severity="high",
                category="missing_artifact",
                classification="current",
                blocking=required,
                phase_id=phase_id,
                path=path_text,
                description=f"Required artifact is missing: {path_text}",
                evidence=[path_text],
            )
        )
        return result
    if not schema_path.exists():
        finding_ids.append(
            audit.finding(
                severity="high",
                category="missing_schema",
                classification="current",
                blocking=required,
                phase_id=phase_id,
                path=path_text,
                description=f"Artifact schema is missing: {schema_text}",
                evidence=[schema_text],
            )
        )
        return result
    raw = path.read_text(encoding="utf-8")
    result["empty"] = not raw.strip()
    if result["empty"]:
        finding_ids.append(
            audit.finding(
                severity="high",
                category="empty_artifact",
                classification="current",
                blocking=required,
                phase_id=phase_id,
                path=path_text,
                description=f"Artifact is empty: {path_text}",
                evidence=[path_text],
            )
        )
        return result
    schema = load_json(schema_path)
    required_keys = schema_required_keys(schema)
    result["metadata"]["producer_required_by_schema"] = "producer" in required_keys
    result["metadata"]["run_id_required_by_schema"] = "run_id" in required_keys
    result["metadata"]["status_required_by_schema"] = "status" in required_keys

    records: list[Any]
    if path.suffix == ".jsonl":
        records, parse_errors = read_jsonl(path)
        if parse_errors:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="invalid_jsonl",
                    classification="current",
                    blocking=required,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"JSONL artifact has invalid records: {path_text}",
                    evidence=parse_errors[:5],
                )
            )
            return result
        if not records:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="empty_artifact",
                    classification="current",
                    blocking=required,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"JSONL artifact has no records: {path_text}",
                    evidence=[path_text],
                )
            )
            return result
        result["json_valid"] = True
        schema_errors: list[str] = []
        for idx, record in enumerate(records, start=1):
            schema_errors.extend(validate(record, schema, f"$[line {idx}]"))
        first_record = records[0] if isinstance(records[0], dict) else {}
        metadata_source = first_record if isinstance(first_record, dict) else {}
    else:
        obj, parse_error = load_json_safe(path)
        if parse_error:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="invalid_json",
                    classification="current",
                    blocking=required,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"Artifact is not valid JSON: {path_text}",
                    evidence=[parse_error],
                )
            )
            return result
        result["json_valid"] = True
        if obj == {} or obj == []:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="empty_artifact",
                    classification="current",
                    blocking=required,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"Artifact JSON has empty top-level value: {path_text}",
                    evidence=[json.dumps(obj)],
                )
            )
        schema_errors = validate(obj, schema)
        metadata_source = obj if isinstance(obj, dict) else {}

    result["schema_valid"] = not schema_errors
    if schema_errors:
        finding_ids.append(
            audit.finding(
                severity="high",
                category="schema_invalid",
                classification="current",
                blocking=required,
                phase_id=phase_id,
                path=path_text,
                description=f"Artifact failed schema validation: {path_text}",
                evidence=schema_errors[:10],
            )
        )

    result["metadata"]["artifact_type"] = metadata_source.get("artifact_type")
    result["metadata"]["phase_id"] = metadata_source.get("phase_id")
    result["metadata"]["producer_present"] = "producer" in metadata_source
    result["metadata"]["run_id_present"] = bool(metadata_source.get("run_id"))
    result["metadata"]["status_present"] = "status" in metadata_source
    result["metadata"]["status"] = metadata_source.get("status")
    metadata_checks = [
        ("producer", "producer_present", "producer_required_by_schema"),
        ("run_id", "run_id_present", "run_id_required_by_schema"),
        ("status", "status_present", "status_required_by_schema"),
    ]
    for name, present_key, required_key in metadata_checks:
        if result["metadata"][required_key] and not result["metadata"][present_key]:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category=f"missing_{name}",
                    classification="current",
                    blocking=required,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"Required artifact metadata is missing: {name}",
                    evidence=[f"schema required keys include {name}"],
                )
            )
        elif not result["metadata"][required_key] and not result["metadata"][present_key]:
            finding_ids.append(
                audit.finding(
                    severity="low",
                    category=f"missing_{name}",
                    classification="informational",
                    blocking=False,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"Artifact does not carry optional metadata field: {name}",
                    evidence=[f"{name} is not required by {schema_text}"],
                )
            )
    return result


def validate_gate_record(audit: Audit, phase: dict[str, Any], current_manifest_sha: str) -> dict[str, Any]:
    root = audit.root
    phase_id = phase["id"]
    path_text = f"artifacts/gates/{phase_id}/gate_result.json"
    path = root / path_text
    finding_ids: list[str] = []
    result: dict[str, Any] = {
        "phase_id": phase_id,
        "path": path_text,
        "exists": path.exists(),
        "schema_valid": False,
        "status": "MISSING",
        "manifest_sha256": None,
        "expected_manifest_sha256": current_manifest_sha,
        "command_mismatches": [],
        "historical_drift": [],
        "finding_ids": finding_ids,
    }
    if not path.exists():
        finding_ids.append(
            audit.finding(
                severity="high",
                category="missing_gate_result",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=path_text,
                description=f"Gate result is missing for automatic phase {phase_id}",
                evidence=[path_text],
            )
        )
        return result
    gate_result, parse_error = load_json_safe(path)
    if parse_error or not isinstance(gate_result, dict):
        finding_ids.append(
            audit.finding(
                severity="high",
                category="invalid_gate_result",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=path_text,
                description=f"Gate result is invalid JSON for {phase_id}",
                evidence=[parse_error or "not an object"],
            )
        )
        return result
    schema_path = root / "schemas" / "artifact" / "gate_result.schema.json"
    schema_errors = validate(gate_result, load_json(schema_path))
    result["schema_valid"] = not schema_errors
    result["status"] = gate_result.get("status", "MISSING")
    result["manifest_sha256"] = gate_result.get("manifest_sha256")
    if schema_errors:
        finding_ids.append(
            audit.finding(
                severity="high",
                category="gate_schema_invalid",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=path_text,
                description=f"Gate result failed schema validation for {phase_id}",
                evidence=schema_errors[:10],
            )
        )
    if gate_result.get("phase_id") != phase_id:
        finding_ids.append(
            audit.finding(
                severity="high",
                category="gate_phase_mismatch",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=path_text,
                description=f"Gate result phase_id does not match {phase_id}",
                evidence=[str(gate_result.get("phase_id"))],
            )
        )
    if gate_result.get("status") != "PASS":
        finding_ids.append(
            audit.finding(
                severity="high",
                category="gate_status",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=path_text,
                description=f"Gate result status is not PASS for {phase_id}",
                evidence=[str(gate_result.get("status"))],
            )
        )
    if gate_result.get("manifest_sha256") != current_manifest_sha:
        allowance = LEGACY_GATE_MANIFEST_ALLOWLIST.get(phase_id)
        if allowance is None and gate_result.get("manifest_sha256") in LEGACY_GATE_MANIFEST_SHA256ES:
            allowance = {
                "id": "legacy_gate_manifest_sha256",
                "sha256es": LEGACY_GATE_MANIFEST_SHA256ES,
                "rationale": (
                    "Committed gate result predates the current manifest; the exact historical "
                    "manifest hash is explicitly allowlisted for audit compatibility."
                ),
            }
        allowed_sha256es = allowance.get("sha256es", set()) if allowance else set()
        allowlisted = bool(allowance and gate_result.get("manifest_sha256") in allowed_sha256es)
        result["historical_drift"].append("manifest_sha256")
        finding_ids.append(
            audit.finding(
                severity="medium" if allowlisted else "high",
                category="manifest_sha256_mismatch",
                classification="historical" if allowlisted else "current",
                blocking=not allowlisted,
                phase_id=phase_id,
                path=path_text,
                description=f"Gate result manifest_sha256 does not match current manifest for {phase_id}",
                evidence=[
                    f"observed={gate_result.get('manifest_sha256')}",
                    f"current={current_manifest_sha}",
                    (
                        f"allowlist={allowance['id']}; rationale={allowance['rationale']}"
                        if allowlisted
                        else "allowlist=none"
                    ),
                ],
            )
        )
    expected = {gate["name"]: gate for gate in phase.get("gates", [])}
    observed = {gate.get("name"): gate for gate in gate_result.get("gates", [])}
    if set(expected) != set(observed):
        finding_ids.append(
            audit.finding(
                severity="high",
                category="gate_set_mismatch",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=path_text,
                description=f"Gate set mismatch for {phase_id}",
                evidence=[f"expected={sorted(expected)}", f"observed={sorted(observed)}"],
            )
        )
    for name, exp in expected.items():
        obs = observed.get(name)
        if not obs:
            continue
        if obs.get("command") != exp.get("command"):
            result["command_mismatches"].append(
                {"gate": name, "expected": exp.get("command"), "observed": obs.get("command")}
            )
            historical = phase_id == P13_ID and name == P13_HISTORICAL_COMMAND_MISMATCH
            finding_ids.append(
                audit.finding(
                    severity="medium" if historical else "high",
                    category="gate_command_mismatch",
                    classification="historical" if historical else "current",
                    blocking=not historical,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"Gate command mismatch for {phase_id}/{name}",
                    evidence=[f"expected={exp.get('command')}", f"observed={obs.get('command')}"],
                )
            )
        if exp.get("required", True) and obs.get("status") != "PASS":
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="required_gate_failed",
                    classification="current",
                    blocking=True,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"Required gate did not PASS: {phase_id}/{name}",
                    evidence=[str(obs.get("status"))],
                )
            )
        if exp.get("required", True) and obs.get("exit_code") != 0:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="required_gate_exit_code",
                    classification="current",
                    blocking=True,
                    phase_id=phase_id,
                    path=path_text,
                    description=f"Required gate exit_code is not 0: {phase_id}/{name}",
                    evidence=[str(obs.get("exit_code"))],
                )
            )
        for key in ["stdout_path", "stderr_path"]:
            log_path = root / obs.get(key, "")
            if not log_path.exists():
                finding_ids.append(
                    audit.finding(
                        severity="high",
                        category="gate_log_missing",
                        classification="current",
                        blocking=True,
                        phase_id=phase_id,
                        path=path_text,
                        description=f"Gate log is missing: {phase_id}/{name}/{key}",
                        evidence=[obs.get(key, "")],
                    )
                )
                continue
            sha_key = key.replace("_path", "_sha256")
            actual_sha = sha256_file(log_path)
            if actual_sha != obs.get(sha_key):
                finding_ids.append(
                    audit.finding(
                        severity="high",
                        category="gate_log_checksum",
                        classification="current",
                        blocking=True,
                        phase_id=phase_id,
                        path=path_text,
                        description=f"Gate log checksum mismatch: {phase_id}/{name}/{key}",
                        evidence=[f"expected={obs.get(sha_key)}", f"actual={actual_sha}"],
                    )
                )
    return result


def gate_min_nodes_for_artifact(phase: dict[str, Any], artifact_path: str) -> int:
    for gate in phase.get("gates", []):
        command = gate.get("command", "")
        if artifact_path in command and "--min-nodes" in command:
            parts = shlex.split(command)
            try:
                return int(parts[parts.index("--min-nodes") + 1])
            except (ValueError, IndexError):
                return 1
    return 1


def audit_real_evidence(audit: Audit, phase: dict[str, Any], artifact_result: dict[str, Any]) -> int:
    path_text = artifact_result["path"]
    if "valkey_e2e_evidence" not in path_text or not artifact_result["exists"] or not artifact_result["json_valid"]:
        return 0
    data, error = load_json_safe(audit.root / path_text)
    if error or not isinstance(data, dict):
        return 0
    phase_id = phase["id"]
    finding_ids = artifact_result["finding_ids"]
    existing_finding_ids = set(finding_ids)
    count = 0
    min_nodes = gate_min_nodes_for_artifact(phase, path_text)
    checks = [
        (data.get("real_valkey") is True, "real_valkey", "real_valkey must be true"),
        (data.get("probe_result") == "PASS", "probe_result", "probe_result must be PASS"),
        (
            data.get("valkey_version_prefix_required") == "9.1.",
            "valkey_version",
            "valkey_version_prefix_required must be 9.1.",
        ),
        (int(data.get("nodes_observed", 0)) >= min_nodes, "nodes_observed", f"nodes_observed must be >= {min_nodes}"),
    ]
    if "--require-data-path" in " ".join(g.get("command", "") for g in phase.get("gates", [])):
        checks.append((data.get("data_path_result") == "PASS", "data_path", "data_path_result must be PASS"))
    versions = data.get("valkey_versions") or []
    checks.append(
        (
            bool(versions) and all(str(version).startswith("9.1.") for version in versions),
            "valkey_versions",
            f"valkey_versions must contain observed 9.1.x versions: {versions}",
        )
    )
    cleanup = data.get("cleanup") if isinstance(data.get("cleanup"), dict) else {}
    checks.append((cleanup.get("status") == "PASS", "cleanup", "cleanup.status must be PASS"))
    for ok, category, description in checks:
        if not ok:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category=f"real_evidence_{category}",
                    classification="current",
                    blocking=True,
                    phase_id=phase_id,
                    path=path_text,
                    description=description,
                    evidence=[path_text],
                )
            )
    new_finding_ids = set(finding_ids) - existing_finding_ids
    if not any(f["id"] in new_finding_ids and f["blocking"] for f in audit.findings):
        count = 1
    return count


def audit_decision(audit: Audit, phase: dict[str, Any], gate_path: str) -> list[str]:
    phase_id = phase["id"]
    finding_ids: list[str] = []
    decision_path_text = phase.get("audit", {}).get("decision_json_path", "")
    decision_path = audit.root / decision_path_text
    if not decision_path.exists():
        finding_ids.append(
            audit.finding(
                severity="high",
                category="audit_decision_missing",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=decision_path_text,
                description=f"Audit decision JSON is missing for {phase_id}",
                evidence=[decision_path_text],
            )
        )
        return finding_ids
    decision, error = load_json_safe(decision_path)
    if error or not isinstance(decision, dict):
        finding_ids.append(
            audit.finding(
                severity="high",
                category="audit_decision_invalid",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=decision_path_text,
                description=f"Audit decision JSON is invalid for {phase_id}",
                evidence=[error or "not an object"],
            )
        )
        return finding_ids
    schema_errors = validate(decision, load_json(audit.root / "schemas/artifact/audit_decision.schema.json"))
    if schema_errors:
        finding_ids.append(
            audit.finding(
                severity="high",
                category="audit_decision_schema",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=decision_path_text,
                description=f"Audit decision failed schema validation for {phase_id}",
                evidence=schema_errors[:10],
            )
        )
    gate_result_path = audit.root / gate_path
    if decision.get("decision") != "PASS":
        finding_ids.append(
            audit.finding(
                severity="high",
                category="audit_decision_status",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=decision_path_text,
                description=f"Audit decision is not PASS for {phase_id}",
                evidence=[str(decision.get("decision"))],
            )
        )
    if decision.get("fresh_context") is not True:
        finding_ids.append(
            audit.finding(
                severity="high",
                category="audit_decision_fresh_context",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=decision_path_text,
                description=f"Audit decision fresh_context is not true for {phase_id}",
                evidence=[str(decision.get("fresh_context"))],
            )
        )
    if decision.get("gate_result_path") != gate_path:
        finding_ids.append(
            audit.finding(
                severity="high",
                category="audit_decision_gate_path",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=decision_path_text,
                description=f"Audit decision gate_result_path mismatch for {phase_id}",
                evidence=[str(decision.get("gate_result_path")), gate_path],
            )
        )
    if gate_result_path.exists() and decision.get("gate_result_sha256") != sha256_file(gate_result_path):
        finding_ids.append(
            audit.finding(
                severity="high",
                category="audit_decision_gate_sha",
                classification="current",
                blocking=True,
                phase_id=phase_id,
                path=decision_path_text,
                description=f"Audit decision gate_result_sha256 mismatch for {phase_id}",
                evidence=[str(decision.get("gate_result_sha256"))],
            )
        )
    declared = set(decision.get("artifact_paths", []))
    for artifact in phase.get("required_artifacts", []):
        if artifact.get("required", True) and artifact["path"] not in declared:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="audit_decision_artifact_path",
                    classification="current",
                    blocking=True,
                    phase_id=phase_id,
                    path=decision_path_text,
                    description=f"Audit decision does not cite required artifact for {phase_id}",
                    evidence=[artifact["path"]],
                )
            )
    return finding_ids


def build_p14_boundary(audit: Audit, manifest: dict[str, Any]) -> dict[str, Any]:
    phase = next((p for p in manifest.get("phases", []) if p.get("id") == P14_ID), None)
    if not phase:
        fid = audit.finding(
            severity="high",
            category="p14_missing",
            classification="current",
            blocking=True,
            phase_id=P14_ID,
            description="P14 phase is missing from the manifest",
            evidence=[P14_ID],
        )
        return {
            "phase_id": P14_ID,
            "automatic": True,
            "opt_in_required": False,
            "dry_run_only": False,
            "not_required_for_automatic_completion": False,
            "real_valkey_coverage": True,
            "real_evidence_count": 0,
            "status": "FAIL",
            "reason": "P14 missing from manifest",
            "finding_ids": [fid],
        }
    opt_in_required = "VSLAB_ALLOW_1000_DRYRUN" in json.dumps(phase, sort_keys=True)
    dry_run_only = all(not gate.get("real_valkey") for gate in phase.get("gates", [])) and any(
        "--dry-run" in gate.get("command", "") for gate in phase.get("gates", [])
    )
    real_evidence_paths = list((audit.root / "artifacts" / "phases" / P14_ID).glob("*valkey_e2e_evidence*.json"))
    finding_ids: list[str] = []
    checks = [
        (phase.get("automatic") is False, "P14 must remain automatic=false"),
        (phase.get("real_valkey_required") is False, "P14 must not require real Valkey by default"),
        (opt_in_required, "P14 must retain opt-in environment guard"),
        (dry_run_only, "P14 gates must remain dry-run/resource/planner scoped"),
        (not real_evidence_paths, "P14 must not have default real Valkey evidence artifacts"),
    ]
    for ok, description in checks:
        if not ok:
            finding_ids.append(
                audit.finding(
                    severity="high",
                    category="p14_boundary",
                    classification="current",
                    blocking=True,
                    phase_id=P14_ID,
                    description=description,
                    evidence=[json.dumps(phase, sort_keys=True)[:500]],
                )
            )
    return {
        "phase_id": P14_ID,
        "automatic": bool(phase.get("automatic", True)),
        "opt_in_required": opt_in_required,
        "dry_run_only": dry_run_only,
        "not_required_for_automatic_completion": phase.get("automatic") is False,
        "real_valkey_coverage": False,
        "real_evidence_count": len(real_evidence_paths),
        "status": "FAIL" if finding_ids else "SKIPPED_WITH_REASON",
        "reason": "P14 is opt-in dry-run only and was not executed by L01.",
        "finding_ids": finding_ids,
    }


def manifest_sha(root: Path) -> str:
    return sha256_file(root / "codex" / "phase_manifest.json")


def build_report(root: Path) -> dict[str, Any]:
    audit = Audit(root)
    manifest = load_json(root / "codex" / "phase_manifest.json")
    current_manifest_sha = manifest_sha(root)
    automatic_phases = [phase for phase in manifest.get("phases", []) if phase.get("automatic", True)]
    optional_phases = [phase for phase in manifest.get("phases", []) if not phase.get("automatic", True)]
    phase_results: list[dict[str, Any]] = []
    artifact_results: list[dict[str, Any]] = []
    gate_results: list[dict[str, Any]] = []
    real_evidence_count = 0
    for phase in automatic_phases:
        phase_id = phase["id"]
        phase_finding_ids: list[str] = []
        gate_record = validate_gate_record(audit, phase, current_manifest_sha)
        gate_results.append(gate_record)
        phase_finding_ids.extend(gate_record["finding_ids"])
        phase_artifact_results = [
            validate_artifact_record(audit, phase_id, artifact)
            for artifact in phase.get("required_artifacts", [])
            if artifact.get("required", True)
        ]
        for artifact_record in phase_artifact_results:
            artifact_results.append(artifact_record)
            phase_finding_ids.extend(artifact_record["finding_ids"])
            if phase.get("real_valkey_required"):
                real_evidence_count += audit_real_evidence(audit, phase, artifact_record)
        phase_finding_ids.extend(audit_decision(audit, phase, gate_record["path"]))
        phase_findings = [finding for finding in audit.findings if finding["id"] in set(phase_finding_ids)]
        phase_blocking = sum(1 for finding in phase_findings if finding["blocking"])
        phase_historical = sum(1 for finding in phase_findings if finding["classification"] == "historical")
        phase_results.append(
            {
                "phase_id": phase_id,
                "automatic": True,
                "status": "FAIL" if phase_blocking else "PASS",
                "required_artifacts_checked": len(phase_artifact_results),
                "gate_result_checked": gate_record["exists"],
                "real_evidence_checked": bool(phase.get("real_valkey_required")),
                "blocking_findings": phase_blocking,
                "historical_findings": phase_historical,
                "finding_ids": sorted(set(phase_finding_ids)),
            }
        )

    p14_boundary = build_p14_boundary(audit, manifest)
    blocking_findings = [finding for finding in audit.findings if finding["blocking"]]
    historical_findings = [finding for finding in audit.findings if finding["classification"] == "historical"]
    status = "PASS" if not blocking_findings else "FAIL"
    return {
        "schema_version": "v1",
        "artifact_type": "audit_report",
        "created_at": utc_now(),
        "producer": {"name": "scripts/audit_committed_artifacts.py", "version": "v1"},
        "status": status,
        "audit_scope": {
            "automatic_phase_ids": [phase["id"] for phase in automatic_phases],
            "optional_phase_ids": [phase["id"] for phase in optional_phases],
            "required_artifact_count": sum(
                1
                for phase in automatic_phases
                for artifact in phase.get("required_artifacts", [])
                if artifact.get("required", True)
            ),
        },
        "manifest_summary": {
            "default_max_nodes": manifest.get("default_max_nodes"),
            "automatic_stop_after": manifest.get("automatic_stop_after"),
            "valkey_version_required_prefix": manifest.get("valkey_version_required_prefix"),
            "manifest_sha256": current_manifest_sha,
        },
        "summary": {
            "phase_count": len(automatic_phases),
            "artifact_count": len(artifact_results),
            "gate_result_count": len(gate_results),
            "blocking_findings_count": len(blocking_findings),
            "historical_findings_count": len(historical_findings),
            "real_evidence_count": real_evidence_count,
        },
        "phase_results": phase_results,
        "artifact_results": artifact_results,
        "gate_results": gate_results,
        "p14_boundary": p14_boundary,
        "findings": audit.findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit committed valkey-scale-lab artifacts")
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    report = build_report(root)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"{report['status']} audit_report {rel(root, out_path)}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
