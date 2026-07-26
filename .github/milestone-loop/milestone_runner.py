from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from contracts import ContractError, fixed_milestone_path
from coordinator import (
    CONTROL_LABEL,
    LoopBlocked,
    load_trusted_documents,
    m2_candidate_blockers,
    m2_discovery_eligible,
    parse_control,
    real_readiness_fingerprint,
    render_control,
)
from github_api import GitHubClient, GitHubError, collect_snapshot
from recovery import cleanup_owned_docker


_GATE_DIAGNOSTIC_MAX_CHARS = 3800
_GATE_DIAGNOSTIC_MAX_ROWS = 8
_GATE_DIAGNOSTIC_DETAIL_MAX_CHARS = 400
_GATE_DIAGNOSTIC_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")
_MILESTONE_RESULT_MAX_BYTES = 32_768
_MILESTONE_RESULT_FIELDS = {
    "milestone",
    "entrypoint",
    "tested_sha",
    "lease_sha256",
    "run_id",
    "run_attempt",
    "status",
    "summary",
}
_M2_DISCOVERY_REPORT_NAME = "m2_candidate_discovery.json"
_M2_ADMISSION_REPORT_NAME = "m2_performance_report.json"
_M2_DISCOVERY_RESULT_SCHEMA = "m2-discovery-result-v1"
_M2_DISCOVERY_RESULT_MAX_BYTES = 65_536
_M2_DISCOVERY_REPORT_MAX_BYTES = 256 * 1024 * 1024
_M2_DISCOVERY_EVIDENCE_MAX_FILES = 10_000
_M2_DISCOVERY_EVIDENCE_MAX_BYTES = 10 * 1024 * 1024 * 1024
_M2_DISCOVERY_RESULT_FIELDS = {
    "schema_version",
    "milestone",
    "status",
    "disposition",
    "failure_scope",
    "failure_code",
    "failure_fingerprint",
    "tested_sha",
    "lease_sha256",
    "run_id",
    "run_attempt",
    "invocation_id",
    "run_outcome",
    "cleanup_outcome",
    "report_digest",
    "evidence_digest",
    "summary",
    "result_digest",
}
_M2_DISCOVERY_REPORT_FIELDS = {
    "schema_version",
    "artifact_type",
    "purpose",
    "admission_evidence",
    "campaign_id",
    "invocation_run_id",
    "current_invocation",
    "tested_sha",
    "created_at",
    "producer",
    "status",
    "real_valkey",
    "execution_mode",
    "campaigns",
    "candidate_results",
    "survivors",
    "errors",
    "report_digest",
}


class LeaseConfirmationBlocked(LoopBlocked):
    def __init__(self, message: str, receipt: dict[str, Any]) -> None:
        super().__init__(message)
        self.receipt = dict(receipt)


_M2_DISCOVERY_CAMPAIGN_FIELDS = {
    "campaign_id",
    "invocation_run_id",
    "experiment_kind",
    "status",
    "real_valkey",
    "execution_mode",
    "baseline",
    "candidates",
    "current_defaults",
    "protocol",
    "started_trial_ids",
    "trials",
    "pairs",
    "cells",
    "invalid_samples",
    "source_refs",
    "errors",
}
_M2_DISCOVERY_V2_FORMATION_CAMPAIGN_FIELDS = {
    *_M2_DISCOVERY_CAMPAIGN_FIELDS,
    "candidate_screen_version",
}


def _canonical_digest(value: Mapping[str, Any], *, omit: str = "") -> str:
    payload = dict(value)
    if omit:
        payload.pop(omit, None)
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ContractError(f"M2 discovery JSON is not canonical finite data: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def _read_bounded_object(path: Path, maximum: int, description: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"{description} is missing or is not a regular file")
    try:
        size = path.stat().st_size
        if size > maximum:
            raise ContractError(f"{description} exceeds {maximum} bytes")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {description}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{description} must be a JSON object")
    return value


def _evidence_digest(root: Path) -> str:
    if not root.is_dir() or root.is_symlink():
        raise ContractError("M2 discovery evidence artifact is missing or is not a regular directory")
    files = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    regular = [path for path in files if path.is_file() and not path.is_symlink()]
    if not regular:
        raise ContractError("M2 discovery evidence artifact is empty")
    if len(regular) > _M2_DISCOVERY_EVIDENCE_MAX_FILES:
        raise ContractError("M2 discovery evidence artifact contains too many files")
    if any(path.is_symlink() or (not path.is_file() and not path.is_dir()) for path in files):
        raise ContractError("M2 discovery evidence artifact contains an unsafe entry")
    digest = hashlib.sha256()
    total = 0
    for path in regular:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        file_digest = hashlib.sha256()
        try:
            size = path.stat().st_size
            total += size
            if total > _M2_DISCOVERY_EVIDENCE_MAX_BYTES:
                raise ContractError("M2 discovery evidence artifact is too large")
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    file_digest.update(chunk)
        except OSError as exc:
            raise ContractError(
                f"cannot hash M2 discovery evidence {relative.decode('utf-8')}: {exc}"
            ) from exc
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        digest.update(file_digest.digest())
    return digest.hexdigest()


def _validate_artifact_ref(root: Path, ref: Any) -> tuple[str, str, str]:
    if not isinstance(ref, dict) or set(ref) != {"category", "path", "sha256"}:
        raise ContractError("M2 discovery source reference fields are invalid")
    category = ref.get("category")
    relative = ref.get("path")
    expected = ref.get("sha256")
    if (
        not isinstance(category, str)
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", category) is None
        or not isinstance(relative, str)
        or not relative
        or not isinstance(expected, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected) is None
    ):
        raise ContractError("M2 discovery source reference is malformed")
    relative_path = Path(relative)
    lowered = {part.lower() for part in relative_path.parts}
    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or lowered.intersection({"loop_evidence", "fixture", "fixtures", "historical", "retained"})
    ):
        raise ContractError("M2 discovery source reference is not current-invocation evidence")
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ContractError("M2 discovery source reference escapes its artifact") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise ContractError("M2 discovery source reference is missing or unsafe")
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"cannot hash M2 discovery source reference: {exc}") from exc
    if digest.hexdigest() != expected:
        raise ContractError("M2 discovery source reference digest does not match")
    return category, relative_path.as_posix(), expected


def _validate_discovery_campaign(
    campaign: Any, *, kind: str, invocation_id: str, evidence_root: Path
) -> None:
    if not isinstance(campaign, dict):
        raise ContractError(f"M2 {kind} discovery campaign fields are invalid")
    fields = set(campaign)
    v2_formation = (
        kind == "formation"
        and fields == _M2_DISCOVERY_V2_FORMATION_CAMPAIGN_FIELDS
        and campaign.get("candidate_screen_version") == "v2"
    )
    if fields != _M2_DISCOVERY_CAMPAIGN_FIELDS and not v2_formation:
        raise ContractError(f"M2 {kind} discovery campaign fields are invalid")
    if (
        campaign.get("campaign_id") != invocation_id
        or campaign.get("invocation_run_id") != invocation_id
        or campaign.get("experiment_kind") != kind
        or campaign.get("status") not in {"PASS", "FAIL", "BLOCKED"}
        or not isinstance(campaign.get("baseline"), dict)
        or not isinstance(campaign.get("candidates"), list)
        or not isinstance(campaign.get("current_defaults"), dict)
        or not isinstance(campaign.get("protocol"), dict)
        or not isinstance(campaign.get("started_trial_ids"), list)
        or not isinstance(campaign.get("trials"), list)
        or not isinstance(campaign.get("pairs"), list)
        or not isinstance(campaign.get("cells"), list)
        or not isinstance(campaign.get("invalid_samples"), list)
        or not isinstance(campaign.get("source_refs"), list)
        or not isinstance(campaign.get("errors"), list)
    ):
        raise ContractError(f"M2 {kind} discovery campaign is malformed")
    started = campaign["started_trial_ids"]
    if len(started) != len(set(started)) or any(
        not isinstance(value, str) or not value for value in started
    ):
        raise ContractError(f"M2 {kind} discovery started trials are invalid")
    invalid_samples = campaign["invalid_samples"]
    if campaign.get("status") != "FAIL" and invalid_samples:
        raise ContractError(f"M2 {kind} discovery non-failure contains invalid samples")
    if len(invalid_samples) > 1:
        raise ContractError(f"M2 {kind} discovery contains multiple invalid samples")
    if invalid_samples:
        sample = invalid_samples[0]
        if not isinstance(sample, dict) or set(sample) != {"trial_id", "reason"}:
            raise ContractError(f"M2 {kind} discovery invalid sample fields are malformed")
        trial_id = sample.get("trial_id")
        reason = sample.get("reason")
        if (
            not isinstance(trial_id, str)
            or trial_id not in started
            or re.fullmatch(
                re.escape(invocation_id) + r"-[A-Za-z0-9][A-Za-z0-9._:-]{0,255}",
                trial_id,
            ) is None
            or not isinstance(reason, str)
            or not reason
            or len(reason) > 4000
            or not reason.isprintable()
        ):
            raise ContractError(f"M2 {kind} discovery invalid sample is not current and bounded")
    if started and (
        campaign.get("real_valkey") is not True
        or campaign.get("execution_mode") != "valkey-real"
        or not campaign["source_refs"]
    ):
        raise ContractError(f"M2 {kind} discovery is not bound to real source evidence")
    references = [
        _validate_artifact_ref(evidence_root, ref) for ref in campaign["source_refs"]
    ]
    if len(references) != len(set(references)):
        raise ContractError(f"M2 {kind} discovery source references are duplicated")
    if any(not isinstance(row, dict) for key in ("trials", "pairs", "cells") for row in campaign[key]):
        raise ContractError(f"M2 {kind} discovery observations are malformed")
    protocol = campaign["protocol"]
    if any(
        protocol.get(key) is not False
        for key in (
            "fixture_admission_allowed",
            "historical_admission_allowed",
            "downscale_allowed",
            "takeover_allowed",
        )
    ):
        raise ContractError(f"M2 {kind} discovery protocol permits forbidden evidence")
    cells = campaign["cells"]
    cell_ids = [cell.get("cell_id") for cell in cells]
    if len(cell_ids) != len(set(cell_ids)) or any(
        set(cell) != {
            "cell_id",
            "campaign_step",
            "scale",
            "failure_rate",
            "required_pairs",
            "candidate",
            "status",
        }
        or not isinstance(cell.get("cell_id"), str)
        or cell.get("campaign_step") != "discovery"
        or cell.get("scale") != 50
        or cell.get("failure_rate") != ("none" if kind == "formation" else "one")
        or cell.get("required_pairs") != 1
        or not isinstance(cell.get("candidate"), dict)
        or cell.get("status") not in {"PASS", "FAIL"}
        for cell in cells
    ):
        raise ContractError(f"M2 {kind} discovery cells violate the fixed exact-50 screen")
    trials = campaign["trials"]
    trial_ids = [trial.get("trial_id") for trial in trials]
    if len(trial_ids) != len(set(trial_ids)) or any(
        not isinstance(trial_id, str) or not trial_id for trial_id in trial_ids
    ):
        raise ContractError(f"M2 {kind} discovery trial identities are invalid")
    pairs = campaign["pairs"]
    pair_ids = [pair.get("pair_id") for pair in pairs]
    if len(pair_ids) != len(set(pair_ids)) or any(
        not isinstance(pair_id, str) or not pair_id for pair_id in pair_ids
    ):
        raise ContractError(f"M2 {kind} discovery pair identities are invalid")
    if any(
        pair.get("cell_id") not in cell_ids
        or pair.get("baseline_trial_id") not in trial_ids
        or pair.get("candidate_trial_id") not in trial_ids
        or pair.get("baseline_trial_id") == pair.get("candidate_trial_id")
        for pair in pairs
    ):
        raise ContractError(f"M2 {kind} discovery pair bindings are invalid")
    if any(
        trial_id not in started
        or trial.get("cell_id") not in cell_ids
        or trial.get("pair_id") not in pair_ids
        for trial_id, trial in zip(trial_ids, trials)
    ):
        raise ContractError(f"M2 {kind} discovery trial bindings are invalid")
    if campaign.get("status") == "PASS":
        try:
            candidate_encodings = {
                json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
                for value in campaign["candidates"]
                if isinstance(value, dict)
            }
            cell_candidates = {
                json.dumps(cell["candidate"], sort_keys=True, separators=(",", ":"), allow_nan=False)
                for cell in cells
            }
        except (TypeError, ValueError) as exc:
            raise ContractError(f"M2 {kind} discovery candidates are invalid") from exc
        if (
            campaign.get("errors") != []
            or not cells
            or len(candidate_encodings) != len(campaign["candidates"])
            or cell_candidates != candidate_encodings
            or len(pairs) != len(cells)
            or len(trials) != 2 * len(pairs)
            or set(started) != set(trial_ids)
            or any(sum(pair.get("cell_id") == cell_id for pair in pairs) != 1 for cell_id in cell_ids)
        ):
            raise ContractError(f"M2 {kind} discovery PASS topology is incomplete")


def _github_discovery_identity(run_id: str, run_attempt: str) -> tuple[str, int, str]:
    if re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None:
        raise ContractError("GitHub M2 discovery run id is invalid")
    if re.fullmatch(r"[1-9][0-9]{0,9}", run_attempt) is None:
        raise ContractError("GitHub M2 discovery run attempt is invalid")
    return run_id, int(run_attempt), f"m2-discovery-gh-{run_id}-attempt-{run_attempt}"


def _discovery_failure_scope(report: Mapping[str, Any]) -> str:
    campaigns = report.get("campaigns")
    if not isinstance(campaigns, dict):
        return ""
    formation = campaigns.get("formation")
    failover = campaigns.get("failover")
    formation_started = (
        formation.get("started_trial_ids") if isinstance(formation, dict) else None
    )
    failover_started = failover.get("started_trial_ids") if isinstance(failover, dict) else None
    if (
        isinstance(formation, dict)
        and formation.get("status") == "FAIL"
        and isinstance(formation_started, list)
        and bool(formation_started)
        and (
            failover is None
            or (
                isinstance(failover, dict)
                and failover.get("status") == "FAIL"
                and isinstance(failover_started, list)
                and not failover_started
            )
        )
    ):
        return "formation"
    if (
        isinstance(formation, dict)
        and formation.get("status") == "PASS"
        and isinstance(failover, dict)
        and failover.get("status") == "FAIL"
        and isinstance(failover_started, list)
        and bool(failover_started)
    ):
        return "failover"
    return ""


def _validate_discovery_report(
    report: Mapping[str, Any],
    *,
    expected_sha: str,
    invocation_id: str,
    evidence_root: Path,
) -> tuple[str, str, str]:
    if set(report) != _M2_DISCOVERY_REPORT_FIELDS:
        raise ContractError("M2 discovery report fields are incomplete or unexpected")
    if (
        report.get("schema_version") != "m2-candidate-discovery-v1"
        or report.get("artifact_type") != "m2_candidate_discovery"
        or report.get("purpose") != "candidate-selection-only"
        or report.get("admission_evidence") is not False
        or report.get("current_invocation") is not True
        or report.get("tested_sha") != expected_sha
        or report.get("invocation_run_id") != invocation_id
        or report.get("campaign_id") != invocation_id
        or report.get("status") not in {"PASS", "FAIL", "BLOCKED"}
    ):
        raise ContractError("M2 discovery report is not bound to this selection-only invocation")
    report_digest = report.get("report_digest")
    if (
        not isinstance(report_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", report_digest) is None
        or report_digest != _canonical_digest(report, omit="report_digest")
    ):
        raise ContractError("M2 discovery report digest does not match its canonical content")
    status = str(report["status"])
    campaigns = report.get("campaigns")
    candidate_results = report.get("candidate_results")
    survivors = report.get("survivors")
    if not isinstance(campaigns, dict) or set(campaigns) - {"formation", "failover"}:
        raise ContractError("M2 discovery campaigns are invalid")
    if not isinstance(candidate_results, dict) or set(candidate_results) != {
        "formation",
        "failover",
    }:
        raise ContractError("M2 discovery candidate results are invalid")
    if not isinstance(survivors, dict) or set(survivors) != {"formation", "failover"}:
        raise ContractError("M2 discovery survivors are invalid")
    derived_results: dict[str, list[dict[str, Any]]] = {}
    for kind in ("formation", "failover"):
        campaign = campaigns.get(kind)
        if campaign is None:
            derived_results[kind] = []
            continue
        _validate_discovery_campaign(
            campaign,
            kind=kind,
            invocation_id=invocation_id,
            evidence_root=evidence_root,
        )
        derived_results[kind] = [
            {"candidate": dict(cell["candidate"]), "status": str(cell["status"])}
            for cell in campaign["cells"]
            if isinstance(cell, dict)
            and isinstance(cell.get("candidate"), dict)
            and cell.get("status") in {"PASS", "FAIL"}
        ]
    if candidate_results != derived_results:
        raise ContractError("M2 discovery candidate results are not derived from campaign cells")
    derived_survivors = {
        kind: [dict(row["candidate"]) for row in derived_results[kind] if row["status"] == "PASS"]
        for kind in ("formation", "failover")
    }
    if survivors != derived_survivors:
        raise ContractError("M2 discovery survivors are not derived from passing cells")
    errors = report.get("errors")
    if (
        not isinstance(errors, list)
        or len(errors) > 10
        or any(not isinstance(value, str) or len(value) > 4000 for value in errors)
    ):
        raise ContractError("M2 discovery errors are invalid or unbounded")
    if status == "PASS":
        if (
            set(campaigns) != {"formation", "failover"}
            or any(campaigns[kind].get("status") != "PASS" for kind in campaigns)
            or report.get("errors") != []
            or report.get("real_valkey") is not True
            or report.get("execution_mode") != "valkey-real"
        ):
            raise ContractError("M2 discovery PASS is not a completed real selection screen")
        return "CANDIDATE_SELECTION_ONLY", "", ""
    if status == "FAIL" and errors:
        scope = _discovery_failure_scope(report)
        affected = campaigns.get(scope) if scope else None
        if (
            scope
            and isinstance(affected, dict)
            and affected.get("errors") == errors
            and report.get("real_valkey") is True
            and report.get("execution_mode") == "valkey-real"
        ):
            return "REPAIRABLE_IMPLEMENTATION", scope, "discovery-failed"
    return "HUMAN_REQUIRED", "", "non-repairable-result"


def _bounded_summary(value: Any) -> str:
    if not isinstance(value, str):
        return "invalid or missing M2 discovery result"
    safe = "".join(" " if character in "@<>`" or not character.isprintable() else character for character in value)
    safe = re.sub(r"(?<![A-Za-z0-9])/(?:[^\s,;]+)", "[absolute-path]", safe)
    return " ".join(safe.split())[:2000] or "M2 discovery produced no summary"


def _discovery_failure_fingerprint(
    *, tested_sha: str, disposition: str, scope: str, code: str, summary: str, invocation_id: str
) -> str:
    normalized = summary.replace(invocation_id, "[invocation]")
    if disposition in {"CANDIDATE_SELECTION_ONLY", "REPAIRABLE_IMPLEMENTATION"}:
        normalized = ""
    value = {
        "milestone": "m2",
        "tested_sha": tested_sha,
        "disposition": disposition,
        "scope": scope,
        "code": code,
        "summary": normalized,
    }
    return _canonical_digest(value)


def _sealed_discovery_result(
    *,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
    run_outcome: str,
    cleanup_outcome: str,
    status: str,
    disposition: str,
    failure_scope: str,
    failure_code: str,
    report_digest: str,
    evidence_digest: str,
    summary: str,
) -> dict[str, Any]:
    run_id, attempt, invocation_id = _github_discovery_identity(run_id, run_attempt)
    if (
        re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None
        or (
            expected_lease_sha256 != ""
            and re.fullmatch(r"[0-9a-f]{64}", expected_lease_sha256) is None
        )
    ):
        raise ContractError("M2 discovery SHA or Lease binding is invalid")
    bounded_summary = _bounded_summary(summary)
    result: dict[str, Any] = {
        "schema_version": _M2_DISCOVERY_RESULT_SCHEMA,
        "milestone": "m2",
        "status": status,
        "disposition": disposition,
        "failure_scope": failure_scope,
        "failure_code": failure_code,
        "failure_fingerprint": _discovery_failure_fingerprint(
            tested_sha=expected_sha,
            disposition=disposition,
            scope=failure_scope,
            code=failure_code,
            summary=bounded_summary,
            invocation_id=invocation_id,
        ),
        "tested_sha": expected_sha,
        "lease_sha256": expected_lease_sha256,
        "run_id": run_id,
        "run_attempt": attempt,
        "invocation_id": invocation_id,
        "run_outcome": run_outcome,
        "cleanup_outcome": cleanup_outcome,
        "report_digest": report_digest,
        "evidence_digest": evidence_digest,
        "summary": bounded_summary,
        "result_digest": "",
    }
    result["result_digest"] = _canonical_digest(result, omit="result_digest")
    return result


def seal_m2_discovery_result(
    *,
    raw_result_path: Path,
    evidence_root: Path,
    output_path: Path,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
    run_outcome: str,
    cleanup_outcome: str,
) -> dict[str, Any]:
    _run_id, _attempt, invocation_id = _github_discovery_identity(run_id, run_attempt)
    status = "BLOCKED"
    disposition = "HUMAN_REQUIRED"
    scope = ""
    code = "artifact-invalid"
    report_digest = ""
    evidence_digest = ""
    summary = "M2 discovery result or evidence artifact is missing or invalid"
    try:
        if run_outcome != "success":
            raise ContractError(f"M2 discovery command outcome was {run_outcome}")
        raw = _read_bounded_object(
            raw_result_path, _M2_DISCOVERY_RESULT_MAX_BYTES, "raw M2 discovery result"
        )
        validate_real_result_binding(
            raw,
            milestone="m2",
            entrypoint="discovery",
            expected_sha=expected_sha,
            expected_lease_sha256=expected_lease_sha256,
            run_id=run_id,
            run_attempt=run_attempt,
        )
        raw_status = raw.get("status")
        if raw_status not in {"PASS", "FAIL", "BLOCKED"}:
            raise ContractError("raw M2 discovery status is invalid")
        evidence_digest = _evidence_digest(evidence_root)
        if any(path.name == _M2_ADMISSION_REPORT_NAME for path in evidence_root.rglob("*")):
            raise ContractError("M2 discovery evidence contains a forbidden admission report")
        report = _read_bounded_object(
            evidence_root / _M2_DISCOVERY_REPORT_NAME,
            _M2_DISCOVERY_REPORT_MAX_BYTES,
            "M2 discovery report",
        )
        if report.get("status") != raw_status:
            raise ContractError("raw M2 discovery status differs from the report")
        disposition, scope, code = _validate_discovery_report(
            report,
            expected_sha=expected_sha,
            invocation_id=invocation_id,
            evidence_root=evidence_root,
        )
        status = str(raw_status)
        report_digest = str(report["report_digest"])
        if disposition == "CANDIDATE_SELECTION_ONLY":
            summary = "Current-invocation M2 candidate-selection screen completed"
        elif disposition == "REPAIRABLE_IMPLEMENTATION":
            summary = f"Allowlisted {scope} discovery implementation failure ({code})"
        else:
            summary = "M2 discovery result is not safely machine-repairable; inspect the protected artifact"
        if cleanup_outcome != "success":
            status = "BLOCKED"
            disposition = "HUMAN_REQUIRED"
            scope = ""
            code = "cleanup-failed"
            summary = f"M2 discovery cleanup outcome was {cleanup_outcome}"
    except (ContractError, OSError) as exc:
        status = "BLOCKED"
        disposition = "HUMAN_REQUIRED"
        scope = ""
        code = "artifact-invalid"
        summary = f"M2 discovery artifact validation failed: {exc}"
    result = _sealed_discovery_result(
        expected_sha=expected_sha,
        expected_lease_sha256=expected_lease_sha256,
        run_id=run_id,
        run_attempt=run_attempt,
        run_outcome=run_outcome,
        cleanup_outcome=cleanup_outcome,
        status=status,
        disposition=disposition,
        failure_scope=scope,
        failure_code=code,
        report_digest=report_digest,
        evidence_digest=evidence_digest,
        summary=summary,
    )
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def human_required_m2_discovery_result(
    *,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
    summary: str,
) -> dict[str, Any]:
    return _sealed_discovery_result(
        expected_sha=expected_sha,
        expected_lease_sha256=expected_lease_sha256,
        run_id=run_id,
        run_attempt=run_attempt,
        run_outcome="unknown",
        cleanup_outcome="unknown",
        status="BLOCKED",
        disposition="HUMAN_REQUIRED",
        failure_scope="",
        failure_code="record-artifact-invalid",
        report_digest="",
        evidence_digest="",
        summary=summary,
    )


def load_m2_discovery_result(
    *,
    result_path: Path,
    evidence_root: Path,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
) -> dict[str, Any]:
    _run_id, attempt, invocation_id = _github_discovery_identity(run_id, run_attempt)
    result = _read_bounded_object(
        result_path, _M2_DISCOVERY_RESULT_MAX_BYTES, "sealed M2 discovery result"
    )
    if set(result) != _M2_DISCOVERY_RESULT_FIELDS:
        raise ContractError("sealed M2 discovery result fields are incomplete or unexpected")
    if (
        result.get("schema_version") != _M2_DISCOVERY_RESULT_SCHEMA
        or result.get("milestone") != "m2"
        or result.get("tested_sha") != expected_sha
        or result.get("lease_sha256") != expected_lease_sha256
        or result.get("run_id") != run_id
        or result.get("run_attempt") != attempt
        or result.get("invocation_id") != invocation_id
        or result.get("status") not in {"PASS", "FAIL", "BLOCKED"}
        or result.get("disposition")
        not in {"CANDIDATE_SELECTION_ONLY", "REPAIRABLE_IMPLEMENTATION", "HUMAN_REQUIRED"}
        or result.get("cleanup_outcome") not in {"success", "failure", "cancelled", "skipped", "unknown"}
        or result.get("run_outcome") not in {"success", "failure", "cancelled", "skipped", "unknown"}
    ):
        raise ContractError("sealed M2 discovery result identity or status is invalid")
    digest = result.get("result_digest")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or digest != _canonical_digest(result, omit="result_digest")
    ):
        raise ContractError("sealed M2 discovery result digest does not match")
    expected_fingerprint = _discovery_failure_fingerprint(
        tested_sha=expected_sha,
        disposition=str(result["disposition"]),
        scope=str(result.get("failure_scope", "")),
        code=str(result.get("failure_code", "")),
        summary=_bounded_summary(result.get("summary")),
        invocation_id=invocation_id,
    )
    if result.get("failure_fingerprint") != expected_fingerprint:
        raise ContractError("M2 discovery failure fingerprint does not match")

    report_digest = result.get("report_digest")
    evidence_digest = result.get("evidence_digest")
    if not isinstance(report_digest, str) or not isinstance(evidence_digest, str):
        raise ContractError("M2 discovery artifact digests are invalid")
    if report_digest:
        if (
            re.fullmatch(r"[0-9a-f]{64}", report_digest) is None
            or re.fullmatch(r"[0-9a-f]{64}", expected_lease_sha256) is None
        ):
            raise ContractError("M2 discovery report digest is invalid")
        if _evidence_digest(evidence_root) != evidence_digest:
            raise ContractError("M2 discovery evidence digest does not match")
        report = _read_bounded_object(
            evidence_root / _M2_DISCOVERY_REPORT_NAME,
            _M2_DISCOVERY_REPORT_MAX_BYTES,
            "M2 discovery report",
        )
        disposition, scope, code = _validate_discovery_report(
            report,
            expected_sha=expected_sha,
            invocation_id=invocation_id,
            evidence_root=evidence_root,
        )
        if report.get("report_digest") != report_digest:
            raise ContractError("M2 discovery report artifact digest does not match the result")
        if result["cleanup_outcome"] == "success":
            if (
                result.get("status") != report.get("status")
                or result.get("disposition") != disposition
                or result.get("failure_scope") != scope
                or result.get("failure_code") != code
            ):
                raise ContractError("sealed M2 discovery classification differs from its report")
        elif result.get("status") != "BLOCKED" or result.get("disposition") != "HUMAN_REQUIRED":
            raise ContractError("M2 discovery cleanup failure was not fail-closed")
    else:
        if evidence_digest:
            if (
                re.fullmatch(r"[0-9a-f]{64}", evidence_digest) is None
                or _evidence_digest(evidence_root) != evidence_digest
            ):
                raise ContractError("invalid M2 discovery evidence digest does not match")
        if result.get("status") != "BLOCKED" or result.get("disposition") != "HUMAN_REQUIRED":
            raise ContractError("missing M2 discovery report was not fail-closed")
    return result


def _diagnostic_identifier(value: Any) -> str:
    if isinstance(value, str) and _GATE_DIAGNOSTIC_ID_RE.fullmatch(value):
        return value
    return "invalid"


def _m2_discovery_run_id() -> str:
    github_run_id = os.environ.get("GITHUB_RUN_ID", "")
    github_run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if not github_run_id and not github_run_attempt:
        return f"m2-discovery-local-{uuid.uuid4().hex}"
    if (
        re.fullmatch(r"[1-9][0-9]{0,19}", github_run_id) is None
        or re.fullmatch(r"[1-9][0-9]{0,9}", github_run_attempt) is None
    ):
        raise ContractError("GitHub M2 discovery run identity is invalid")
    return f"m2-discovery-gh-{github_run_id}-attempt-{github_run_attempt}"


def bind_real_result(
    result: dict[str, Any],
    *,
    milestone: str,
    entrypoint: str,
    expected_sha: str,
    expected_lease_sha256: str,
) -> dict[str, Any]:
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if (
        re.fullmatch(r"m[1-4]", milestone) is None
        or entrypoint not in {"milestone", "discovery"}
        or (entrypoint == "discovery" and milestone != "m2")
        or re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None
        or re.fullmatch(r"[0-9a-f]{64}", expected_lease_sha256) is None
        or re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None
        or re.fullmatch(r"[1-9][0-9]{0,9}", run_attempt) is None
    ):
        raise ContractError("real result invocation binding is invalid")
    return {
        **result,
        "milestone": milestone,
        "entrypoint": entrypoint,
        "tested_sha": expected_sha,
        "lease_sha256": expected_lease_sha256,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }


def validate_real_result_binding(
    result: Any,
    *,
    milestone: str,
    entrypoint: str,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
) -> None:
    expected = {
        "milestone": milestone,
        "entrypoint": entrypoint,
        "tested_sha": expected_sha,
        "lease_sha256": expected_lease_sha256,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }
    if (
        not isinstance(result, dict)
        or re.fullmatch(r"m[1-4]", milestone) is None
        or entrypoint not in {"milestone", "discovery"}
        or (entrypoint == "discovery" and milestone != "m2")
        or re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None
        or re.fullmatch(r"[0-9a-f]{64}", expected_lease_sha256) is None
        or re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None
        or re.fullmatch(r"[1-9][0-9]{0,9}", run_attempt) is None
        or result.get("status") not in {"PASS", "FAIL", "BLOCKED"}
        or not isinstance(result.get("summary"), str)
        or len(result["summary"]) > 4000
        or any(result.get(field) != value for field, value in expected.items())
    ):
        raise ContractError("real result artifact does not match this approved invocation")


def _milestone_result(
    *,
    milestone: str,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
    status: str,
    summary: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "milestone": milestone,
        "entrypoint": "milestone",
        "tested_sha": expected_sha,
        "lease_sha256": expected_lease_sha256,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "status": status,
        "summary": summary,
    }
    validate_real_result_binding(
        result,
        milestone=milestone,
        entrypoint="milestone",
        expected_sha=expected_sha,
        expected_lease_sha256=expected_lease_sha256,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    return result


def seal_milestone_result(
    *,
    raw_result_path: Path,
    output_path: Path,
    milestone: str,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
    gate_outcome: str,
    pre_cleanup_outcome: str,
    cleanup_outcome: str,
    evidence_outcome: str,
) -> dict[str, Any]:
    outcomes = (
        ("pre-Gate cleanup", pre_cleanup_outcome),
        ("gate", gate_outcome),
        ("final cleanup", cleanup_outcome),
        ("evidence upload", evidence_outcome),
    )
    allowed_outcomes = {"success", "failure", "cancelled", "skipped"}
    status = "BLOCKED"
    summary = "Milestone result artifact is missing or invalid"
    try:
        invalid = [name for name, value in outcomes if value not in allowed_outcomes]
        if invalid:
            raise ContractError("invalid workflow outcome for " + ", ".join(invalid))
        non_pass = next(
            ((name, value) for name, value in outcomes if value != "success"),
            None,
        )
        if non_pass is not None:
            summary = f"Milestone {non_pass[0]} outcome was {non_pass[1]}"
        else:
            raw = _read_bounded_object(
                raw_result_path,
                _MILESTONE_RESULT_MAX_BYTES,
                "raw Milestone result",
            )
            validate_real_result_binding(
                raw,
                milestone=milestone,
                entrypoint="milestone",
                expected_sha=expected_sha,
                expected_lease_sha256=expected_lease_sha256,
                run_id=run_id,
                run_attempt=run_attempt,
            )
            status = str(raw["status"])
            summary = str(raw["summary"])
    except (ContractError, OSError) as exc:
        status = "BLOCKED"
        summary = f"Milestone result validation failed: {exc}"
    result = _milestone_result(
        milestone=milestone,
        expected_sha=expected_sha,
        expected_lease_sha256=expected_lease_sha256,
        run_id=run_id,
        run_attempt=run_attempt,
        status=status,
        summary=summary,
    )
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def blocked_milestone_result(
    *,
    milestone: str,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
    summary: str,
) -> dict[str, Any]:
    return _milestone_result(
        milestone=milestone,
        expected_sha=expected_sha,
        expected_lease_sha256=expected_lease_sha256,
        run_id=run_id,
        run_attempt=run_attempt,
        status="BLOCKED",
        summary=summary,
    )


def load_milestone_result(
    *,
    result_path: Path,
    milestone: str,
    expected_sha: str,
    expected_lease_sha256: str,
    run_id: str,
    run_attempt: str,
) -> dict[str, Any]:
    result = _read_bounded_object(
        result_path, _MILESTONE_RESULT_MAX_BYTES, "sealed Milestone result"
    )
    if set(result) != _MILESTONE_RESULT_FIELDS:
        raise ContractError("sealed Milestone result fields are incomplete or unexpected")
    validate_real_result_binding(
        result,
        milestone=milestone,
        entrypoint="milestone",
        expected_sha=expected_sha,
        expected_lease_sha256=expected_lease_sha256,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    return result


def _diagnostic_detail(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    safe = "".join(
        " " if character in "@<>`" or not character.isprintable() else character
        for character in value
    )
    safe = re.sub(r"(?<![A-Za-z0-9])/(?:[^\s,;]+)", "[absolute-path]", safe)
    return " ".join(safe.split())[:_GATE_DIAGNOSTIC_DETAIL_MAX_CHARS]


def _gate_result_summary(
    *,
    milestone: str,
    gate_status: str,
    summary: dict[str, Any],
    exit_code: int,
    expected_sha: str,
    invocation_id: str,
) -> str:
    raw_status = summary.get("status")
    result = f"Gate exit={exit_code}; summary status={raw_status}"
    if milestone != "m2" or gate_status != "FAIL":
        return result

    tests = summary.get("tests")
    non_pass = []
    if isinstance(tests, list):
        non_pass = [
            row
            for row in tests
            if isinstance(row, dict) and row.get("status") != "PASS"
        ]
    diagnostic: dict[str, Any] = {
        "diagnostic_only": True,
        "tested_sha": (
            expected_sha
            if re.fullmatch(r"[0-9a-f]{40}", expected_sha)
            else "invalid"
        ),
        "invocation_id": _diagnostic_identifier(invocation_id),
        "non_pass_total": len(non_pass),
        "failures": [],
    }
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    if (
        re.fullmatch(r"[1-9][0-9]{0,19}", run_id)
        and re.fullmatch(r"[1-9][0-9]{0,9}", run_attempt)
    ):
        diagnostic["evidence_artifact"] = f"milestone-evidence-{run_id}-{run_attempt}"
        diagnostic["evidence_summary"] = "summary.json"

    prefix = result + "; diagnostic only, not Criterion or admission evidence: "
    for row in non_pass[:_GATE_DIAGNOSTIC_MAX_ROWS]:
        failure: dict[str, Any] = {
            "instance_id": _diagnostic_identifier(row.get("instance_id")),
            "criterion_id": _diagnostic_identifier(row.get("criterion_id")),
            "check_id": _diagnostic_identifier(row.get("check_id")),
            "test_id": _diagnostic_identifier(row.get("test_id")),
            "status": _diagnostic_identifier(row.get("status")),
        }
        if isinstance(row.get("exit_code"), int):
            failure["exit_code"] = row["exit_code"]
        detail = _diagnostic_detail(row.get("detail"))
        if detail:
            failure["detail"] = detail
        diagnostic["failures"].append(failure)
        diagnostic["omitted_non_pass"] = len(non_pass) - len(diagnostic["failures"])
        rendered = prefix + json.dumps(
            diagnostic, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if len(rendered) > _GATE_DIAGNOSTIC_MAX_CHARS:
            diagnostic["failures"].pop()
            break

    diagnostic["omitted_non_pass"] = len(non_pass) - len(diagnostic["failures"])
    return prefix + json.dumps(
        diagnostic, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _control_state(snapshot: dict[str, Any], milestone: str) -> Any:
    controls = [
        issue
        for issue in snapshot.get("issues", [])
        if CONTROL_LABEL in issue.get("labels", [])
    ]
    if len(controls) != 1:
        raise LoopBlocked("Milestone must retain exactly one Control Issue")
    return parse_control(controls[0], milestone)


def _validate_real_workflow_run(
    client: GitHubClient,
    snapshot: dict[str, Any],
    *,
    entrypoint: str,
    expected_sha: str,
    run_id: str,
    run_attempt: str,
) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or os.environ.get("GITHUB_RUN_ID") != run_id
        or os.environ.get("GITHUB_RUN_ATTEMPT") != run_attempt
        or os.environ.get("GITHUB_JOB")
        != ("m2-discovery" if entrypoint == "discovery" else "milestone")
        or os.environ.get("GITHUB_SHA") != expected_sha
        or os.environ.get("GITHUB_REF") != f"refs/heads/{snapshot.get('default_branch')}"
    ):
        raise LoopBlocked("real authorization is not bound to this workflow invocation")
    environment = client.api("environments/valkey-real")
    rules = environment.get("protection_rules") if isinstance(environment, dict) else None
    reviewer_rules = [
        rule
        for rule in rules or []
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers"
    ]
    reviewers = reviewer_rules[0].get("reviewers") if len(reviewer_rules) == 1 else None
    if (
        not isinstance(environment, dict)
        or environment.get("name") != "valkey-real"
        or not isinstance(rules, list)
        or len(rules) > 10
        or not isinstance(reviewers, list)
        or not 1 <= len(reviewers) <= 6
        or any(
            not isinstance(reviewer, dict)
            or reviewer.get("type") not in {"User", "Team"}
            or not isinstance(reviewer.get("reviewer"), dict)
            for reviewer in reviewers
        )
    ):
        raise LoopBlocked("valkey-real does not retain a required human reviewer")
    run = client.api(f"actions/runs/{run_id}")
    if not isinstance(run, dict):
        raise LoopBlocked("live workflow run is unavailable for real authorization")
    workflow_path = ".github/workflows/milestone-loop.yml"
    allowed_paths = {workflow_path, f"{workflow_path}@{snapshot.get('default_branch')}"}
    if (
        str(run.get("id")) != run_id
        or str(run.get("run_attempt")) != run_attempt
        or run.get("event") != "workflow_dispatch"
        or run.get("status") != "in_progress"
        or run.get("head_sha") != expected_sha
        or run.get("head_branch") != snapshot.get("default_branch")
        or run.get("path") not in allowed_paths
    ):
        raise LoopBlocked("live workflow run does not match the approved real invocation")


def _real_entrypoint(repo_root: Path, milestone: str) -> str:
    milestone_document, _catalog_document = load_trusted_documents(repo_root, milestone)
    if milestone != "m2":
        return "milestone"
    candidate_blockers = m2_candidate_blockers(milestone_document, milestone)
    if m2_discovery_eligible(milestone_document, milestone):
        return "discovery"
    if candidate_blockers:
        raise LoopBlocked(
            "M2 candidate is not ready for real authorization: "
            + ", ".join(candidate_blockers)
        )
    return "milestone"


def authorize_real_invocation(
    client: GitHubClient,
    repo_root: Path,
    *,
    milestone: str,
    entrypoint: str,
    expected_sha: str,
    expected_readiness_sha256: str,
    run_id: str,
    run_attempt: str,
) -> dict[str, Any]:
    fixed_milestone_path(repo_root, milestone)
    if entrypoint not in {"milestone", "discovery"} or (
        entrypoint == "discovery" and milestone != "m2"
    ):
        raise ContractError("real authorization entrypoint is invalid")
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise ContractError("real authorization SHA is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", expected_readiness_sha256) is None:
        raise ContractError("real authorization readiness binding is invalid")
    if (
        re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is None
        or re.fullmatch(r"[1-9][0-9]{0,9}", run_attempt) is None
    ):
        raise ContractError("real authorization run identity is invalid")

    snapshot = collect_snapshot(client, milestone)
    if (
        snapshot.get("milestone") != milestone
        or snapshot.get("default_sha") != expected_sha
        or real_readiness_fingerprint(snapshot) != expected_readiness_sha256
    ):
        raise LoopBlocked("live Milestone readiness changed before real authorization")
    _validate_real_workflow_run(
        client,
        snapshot,
        entrypoint=entrypoint,
        expected_sha=expected_sha,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if actual.returncode != 0 or actual.stdout.strip() != expected_sha:
        raise LoopBlocked("valkey-real authorization checkout does not match the default SHA")
    if _real_entrypoint(repo_root, milestone) != entrypoint:
        raise LoopBlocked("real entrypoint changed before authorization")

    state = _control_state(snapshot, milestone)
    nonce_prefix = f"{milestone}-gh-{run_id}-attempt-{run_attempt}-"
    if str(state.lease.get("nonce", "")).startswith(nonce_prefix):
        raise LoopBlocked("this real workflow invocation already consumed its authorization")
    if state.lease.get("status") not in {"empty", "exhausted"} or state.lease.get("remaining") != 0:
        raise LoopBlocked("pre-existing Authorization Lease is not safely replaceable")

    active_lease = {
        "version": 2,
        "milestone": milestone,
        "status": "active",
        "nonce": f"{nonce_prefix}{entrypoint}-{expected_sha[:12]}",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "remaining": 1,
        "entrypoint": entrypoint,
        "default_sha": expected_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }
    consumed_lease = {**active_lease, "status": "exhausted", "remaining": 0}
    receipt = {
        "milestone": milestone,
        "default_sha": expected_sha,
        "lease_nonce": consumed_lease["nonce"],
        "lease_sha256": _lease_fingerprint(consumed_lease),
        "entrypoint": entrypoint,
        "run_id": run_id,
        "run_attempt": run_attempt,
    }

    live = collect_snapshot(client, milestone)
    if (
        live.get("milestone") != milestone
        or live.get("default_sha") != expected_sha
        or real_readiness_fingerprint(live) != expected_readiness_sha256
    ):
        raise LoopBlocked("live Milestone readiness changed before Lease consumption")
    _validate_real_workflow_run(
        client,
        live,
        entrypoint=entrypoint,
        expected_sha=expected_sha,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    live_state = _control_state(live, milestone)
    if (
        dict(live_state.lease) != dict(state.lease)
        or live_state.no_progress_count != state.no_progress_count
    ):
        raise LoopBlocked("Control Issue changed before Lease consumption")
    try:
        client.update_issue(
            state.issue_number,
            body=render_control(consumed_lease, state.no_progress_count),
        )
        confirmed_issue = client.api(f"issues/{state.issue_number}")
        if not isinstance(confirmed_issue, dict):
            raise LoopBlocked("consumed Authorization Lease cannot be confirmed")
        confirmed = parse_control(confirmed_issue, milestone)
        if (
            dict(confirmed.lease) != consumed_lease
            or confirmed.no_progress_count != state.no_progress_count
        ):
            raise LoopBlocked("Authorization Lease consumption was not atomic")
    except (ContractError, GitHubError, LoopBlocked, OSError) as exc:
        raise LeaseConfirmationBlocked(
            "Authorization Lease consumption could not be confirmed",
            {"authorized": False, **receipt},
        ) from exc
    return {"authorized": True, **receipt}


def _lease_fingerprint(lease: Any) -> str:
    return hashlib.sha256(
        json.dumps(lease, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_consumed_lease(
    snapshot: dict[str, Any],
    expected_sha256: str,
    *,
    milestone: str,
    entrypoint: str,
    expected_sha: str,
) -> None:
    controls = [
        issue
        for issue in snapshot.get("issues", [])
        if CONTROL_LABEL in issue.get("labels", [])
    ]
    if len(controls) != 1:
        raise LoopBlocked("Milestone must retain exactly one Control Issue")
    state = parse_control(controls[0], milestone)
    if _lease_fingerprint(state.lease) != expected_sha256:
        raise LoopBlocked("Authorization Lease changed after consumption")
    if (
        state.lease.get("version") != 2
        or state.lease.get("status") != "exhausted"
        or state.lease.get("remaining") != 0
        or state.lease.get("milestone") != milestone
        or state.lease.get("entrypoint") != entrypoint
        or state.lease.get("default_sha") != expected_sha
        or state.lease.get("run_id") != os.environ.get("GITHUB_RUN_ID")
        or state.lease.get("run_attempt") != os.environ.get("GITHUB_RUN_ATTEMPT")
    ):
        raise LoopBlocked("consumed Authorization Lease is not bound to this invocation")
    try:
        expires = datetime.fromisoformat(str(state.lease["expires_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise LoopBlocked("consumed Authorization Lease expiration is invalid") from exc
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise LoopBlocked("consumed Authorization Lease expired before the real Gate started")


def _gate_environment(milestone: str) -> dict[str, str]:
    blocked = ("GH_", "GITHUB_", "CODEX_", "OPENAI_", "MILESTONE_LOOP_")
    result = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(blocked)
    }
    result["NO_COLOR"] = "1"
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result.pop("VSLAB_M2_REAL_AUTHORIZATION", None)
    if milestone == "m2":
        result["VSLAB_M2_REAL_AUTHORIZATION"] = "1"
    return result


def run_m2_discovery(
    *,
    client: GitHubClient,
    repo_root: Path,
    expected_sha: str,
    expected_lease_sha256: str,
) -> dict[str, Any]:
    fixed_milestone_path(repo_root, "m2")
    snapshot = collect_snapshot(client, "m2")
    if re.fullmatch(r"[0-9a-f]{40}", expected_sha) is None:
        raise ContractError("authorized M2 discovery SHA is invalid")
    if re.fullmatch(r"[0-9a-f]{64}", expected_lease_sha256) is None:
        raise ContractError("consumed Authorization Lease fingerprint is invalid")
    _validate_consumed_lease(
        snapshot,
        expected_lease_sha256,
        milestone="m2",
        entrypoint="discovery",
        expected_sha=expected_sha,
    )
    if snapshot.get("milestone") != "m2" or snapshot.get("default_sha") != expected_sha:
        raise LoopBlocked("default branch changed after M2 discovery authorization")
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if actual.returncode != 0 or actual.stdout.strip() != expected_sha:
        raise LoopBlocked("valkey-real discovery checkout does not match the authorized default SHA")
    milestone_document, _catalog_document = load_trusted_documents(repo_root, "m2")
    if not m2_discovery_eligible(milestone_document, "m2"):
        raise LoopBlocked("M2 candidate bindings are not the canonical unresolved discovery state")

    runner_temp = Path(os.environ.get("RUNNER_TEMP", "/tmp")).resolve()
    artifacts = runner_temp / "m2-discovery-evidence"
    command_result = runner_temp / "m2-discovery-command-result.json"
    bounded_result = runner_temp / "m2-discovery-result.json"
    fallback_log = runner_temp / "m2-discovery-control.log"
    report_path = artifacts / _M2_DISCOVERY_REPORT_NAME
    for path in (artifacts, command_result, bounded_result, fallback_log):
        if path.exists():
            raise LoopBlocked(f"refusing pre-existing M2 discovery output: {path.name}")
    script = repo_root / "project" / "scripts" / "m2_candidate_discovery.py"
    if not script.is_file() or script.is_symlink():
        raise ContractError("fixed M2 candidate discovery producer is missing or is a symlink")

    run_id = _m2_discovery_run_id()
    environment = _gate_environment("m2")
    environment["PYTHONPATH"] = str(repo_root / "project" / "src")
    cleanup_owned_docker()
    try:
        process = subprocess.run(
            [
                "python3",
                "scripts/m2_candidate_discovery.py",
                "--run-id",
                run_id,
                "--artifacts-dir",
                str(artifacts),
                "--result-path",
                str(command_result),
                "--tested-sha",
                expected_sha,
            ],
            cwd=repo_root / "project",
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        fallback_log.write_text(process.stdout, encoding="utf-8")
        if artifacts.is_symlink() or (artifacts.exists() and not artifacts.is_dir()):
            return {
                "status": "FAIL",
                "summary": "M2 discovery evidence root is not a regular directory",
                "exit_code": process.returncode,
                "artifacts": str(fallback_log),
            }
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "control-plane.log").write_text(process.stdout, encoding="utf-8")
        if any(path.name == _M2_ADMISSION_REPORT_NAME for path in artifacts.rglob("*")):
            return {
                "status": "FAIL",
                "summary": "M2 discovery produced a forbidden admission report",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if not command_result.is_file() or command_result.is_symlink():
            return {
                "status": "FAIL",
                "summary": "M2 discovery did not produce its bounded command result",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if not report_path.is_file() or report_path.is_symlink():
            return {
                "status": "FAIL",
                "summary": f"M2 discovery did not produce {_M2_DISCOVERY_REPORT_NAME}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        try:
            command = _read_bounded_object(
                command_result,
                16_384,
                "M2 discovery command result",
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (ContractError, OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                "status": "FAIL",
                "summary": f"M2 discovery output is unreadable: {exc}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        command_status = command.get("status") if isinstance(command, dict) else None
        summary = command.get("summary") if isinstance(command, dict) else None
        if (
            not isinstance(command, dict)
            or set(command) != {"status", "summary"}
            or command_status not in {"PASS", "FAIL", "BLOCKED"}
            or not isinstance(summary, str)
            or len(summary) > 4000
        ):
            return {
                "status": "FAIL",
                "summary": "M2 discovery command result violates its bounded contract",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        report_valid = (
            isinstance(report, dict)
            and report.get("schema_version") == "m2-candidate-discovery-v1"
            and report.get("artifact_type") == "m2_candidate_discovery"
            and report.get("purpose") == "candidate-selection-only"
            and report.get("admission_evidence") is False
            and report.get("current_invocation") is True
            and report.get("tested_sha") == expected_sha
            and report.get("invocation_run_id") == run_id
            and report.get("campaign_id") == run_id
            and report.get("status") == command_status
            and "criterion_results" not in report
            and "selected_candidate" not in report
            and isinstance(report.get("report_digest"), str)
            and re.fullmatch(r"[0-9a-f]{64}", report["report_digest"]) is not None
        )
        if not report_valid:
            return {
                "status": "FAIL",
                "summary": "M2 discovery report is not the authorized selection-only artifact",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if process.returncode != 0:
            return {
                "status": "FAIL",
                "summary": f"M2 discovery producer exited {process.returncode}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        return {
            "status": command_status,
            "summary": " ".join(summary.split())[:2000],
            "exit_code": process.returncode,
            "artifacts": str(artifacts),
            "report": str(report_path),
        }
    finally:
        cleanup_owned_docker()


def run_gate(
    *,
    client: GitHubClient,
    repo_root: Path,
    milestone: str,
    expected_sha: str,
    expected_lease_sha256: str,
) -> dict[str, Any]:
    fixed_milestone_path(repo_root, milestone)
    snapshot = collect_snapshot(client, milestone)
    if len(expected_lease_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in expected_lease_sha256
    ):
        raise ContractError("consumed Authorization Lease fingerprint is invalid")
    _validate_consumed_lease(
        snapshot,
        expected_lease_sha256,
        milestone=milestone,
        entrypoint="milestone",
        expected_sha=expected_sha,
    )
    if snapshot["default_sha"] != expected_sha:
        raise LoopBlocked("default branch changed after Authorization Lease consumption")
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if actual.returncode != 0 or actual.stdout.strip() != expected_sha:
        raise LoopBlocked("valkey-real checkout does not match the authorized default SHA")
    cleanup_owned_docker()
    gate_runs = repo_root / "project" / "artifacts" / "gate-runs"
    before = {path.name for path in gate_runs.iterdir()} if gate_runs.is_dir() else set()
    log_path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "milestone-gate.log"
    try:
        process = subprocess.run(
            ["./gate", "milestone", milestone],
            cwd=repo_root / "project",
            env=_gate_environment(milestone),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_path.write_text(process.stdout, encoding="utf-8")
        after = {path.name for path in gate_runs.iterdir()} if gate_runs.is_dir() else set()
        created = sorted(after - before)
        if len(created) != 1:
            return {
                "status": "BLOCKED",
                "summary": f"Gate created {len(created)} invocation directories; expected exactly one",
                "exit_code": process.returncode,
                "artifacts": str(log_path),
            }
        artifacts = gate_runs / created[0]
        summary_path = artifacts / "summary.json"
        if not summary_path.is_file():
            return {
                "status": "BLOCKED",
                "summary": "Gate did not produce its required summary.json",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        try:
            summary: Any = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {
                "status": "BLOCKED",
                "summary": f"Gate summary is invalid JSON: {exc}",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        if (
            not isinstance(summary, dict)
            or summary.get("schema_version") != "gate-summary-v1"
            or summary.get("selection") != {"kind": "milestone", "id": milestone}
        ):
            return {
                "status": "BLOCKED",
                "summary": "Gate summary does not identify the fixed Milestone invocation",
                "exit_code": process.returncode,
                "artifacts": str(artifacts),
            }
        status = summary.get("status") if isinstance(summary, dict) else None
        if status not in {"PASS", "FAIL", "BLOCKED"}:
            status = "BLOCKED"
        if (status == "PASS") != (process.returncode == 0):
            status = "BLOCKED"
        return {
            "status": status,
            "summary": _gate_result_summary(
                milestone=milestone,
                gate_status=status,
                summary=summary,
                exit_code=process.returncode,
                expected_sha=expected_sha,
                invocation_id=artifacts.name,
            ),
            "exit_code": process.returncode,
            "artifacts": str(artifacts),
        }
    finally:
        cleanup_owned_docker()
