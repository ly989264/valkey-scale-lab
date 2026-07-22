#!/usr/bin/env python3
"""Run the authorized M2 exact-50 screens for candidate selection only."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    import m2_performance_capture as capture
    import m2_performance_gate as admission
except ModuleNotFoundError:  # Imported as scripts.m2_candidate_discovery in tests.
    from scripts import m2_performance_capture as capture
    from scripts import m2_performance_gate as admission


REPORT_NAME = "m2_candidate_discovery.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--result-path", type=Path, required=True)
    parser.add_argument("--tested-sha", required=True)
    return parser


def _write_result(path: Path, status: str, summary: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"status": status, "summary": summary}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _authorized(run_id: str) -> bool:
    value = os.environ.get(admission.AUTHORIZATION_ENV, "").strip()
    return value in {"1", run_id}


def _forbidden_path(path: Path) -> bool:
    return bool(
        {part.lower() for part in path.resolve().parts}.intersection(
            capture.FORBIDDEN_EVIDENCE_PATH_PARTS
        )
    )


def _checkout_sha() -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        return ""
    return process.stdout.strip()


def _context(
    args: argparse.Namespace,
    *,
    mode: str,
    product_digest: str,
    environment_facts: dict[str, Any],
    environment_digest: str,
) -> capture.CaptureContext:
    context_args = SimpleNamespace(
        mode=mode,
        run_id=args.run_id,
        artifacts_dir=args.artifacts_dir,
    )
    return capture.CaptureContext(
        args=context_args,
        artifacts_dir=args.artifacts_dir,
        report_path=args.artifacts_dir / REPORT_NAME,
        product_digest=product_digest,
        environment_facts=environment_facts,
        environment_digest=environment_digest,
    )


def _campaign(
    context: capture.CaptureContext,
    *,
    baseline: dict[str, Any],
    candidates: list[dict[str, Any]],
    status: str,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "campaign_id": str(context.args.run_id),
        "invocation_run_id": str(context.args.run_id),
        "experiment_kind": str(context.args.mode),
        "status": status,
        "real_valkey": bool(context.started),
        "execution_mode": "valkey-real" if context.started else "not-run",
        "baseline": baseline,
        "candidates": candidates,
        "current_defaults": {
            "cluster_create_strategy": capture._current_strategy_default(),
            "cluster_node_timeout_ms": capture._current_timeout_default(),
        },
        "protocol": capture._protocol(),
        "started_trial_ids": list(context.started_trial_ids),
        "trials": list(context.trials),
        "pairs": list(context.pairs),
        "cells": list(context.cells),
        "invalid_samples": list(context.invalid_samples),
        "source_refs": capture._unique_refs(context.source_refs),
        "errors": errors,
    }


def _candidate_results(campaigns: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        kind: [
            {"candidate": dict(cell["candidate"]), "status": str(cell["status"])}
            for cell in campaign.get("cells", [])
            if isinstance(cell, dict)
            and isinstance(cell.get("candidate"), dict)
            and cell.get("status") in {"PASS", "FAIL"}
        ]
        for kind, campaign in campaigns.items()
    }


def _build_report(
    args: argparse.Namespace,
    *,
    status: str,
    campaigns: dict[str, dict[str, Any]],
    survivors: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": "m2-candidate-discovery-v1",
        "artifact_type": "m2_candidate_discovery",
        "purpose": "candidate-selection-only",
        "admission_evidence": False,
        "campaign_id": str(args.run_id),
        "invocation_run_id": str(args.run_id),
        "current_invocation": True,
        "tested_sha": str(args.tested_sha),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "producer": {"name": "valkey-scale-lab", "version": capture._product_version()},
        "status": status,
        "real_valkey": any(campaign.get("real_valkey") is True for campaign in campaigns.values()),
        "execution_mode": "valkey-real" if any(campaign.get("real_valkey") is True for campaign in campaigns.values()) else "not-run",
        "campaigns": campaigns,
        "candidate_results": _candidate_results(campaigns),
        "survivors": survivors,
        "errors": errors,
        "report_digest": "",
    }
    report["report_digest"] = admission.report_digest(report)
    return report


def validate_discovery_report(
    report: Mapping[str, Any],
    *,
    artifacts_dir: Path,
    expected_run_id: str,
    expected_sha: str,
) -> list[str]:
    errors: list[str] = []
    required = {
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
    if set(report) != required:
        errors.append("discovery report fields are incomplete or unexpected")
    if report.get("schema_version") != "m2-candidate-discovery-v1":
        errors.append("discovery schema version is invalid")
    if report.get("artifact_type") != "m2_candidate_discovery":
        errors.append("discovery artifact type is invalid")
    if report.get("purpose") != "candidate-selection-only":
        errors.append("discovery purpose is not candidate selection only")
    if report.get("admission_evidence") is not False:
        errors.append("discovery cannot claim admission evidence")
    if report.get("campaign_id") != expected_run_id or report.get("invocation_run_id") != expected_run_id:
        errors.append("discovery report does not match this invocation")
    if report.get("current_invocation") is not True:
        errors.append("discovery report is not current invocation evidence")
    if report.get("tested_sha") != expected_sha or SHA_RE.fullmatch(expected_sha) is None:
        errors.append("discovery report tested SHA is invalid")
    if report.get("status") != "PASS" or report.get("errors") != []:
        errors.append("completed discovery report did not PASS cleanly")
    if report.get("real_valkey") is not True or report.get("execution_mode") != "valkey-real":
        errors.append("completed discovery report is not real Valkey")
    if "criterion_results" in report or "selected_candidate" in report:
        errors.append("discovery report contains admission-only fields")
    try:
        expected_digest = admission.report_digest(report)
    except (TypeError, ValueError):
        expected_digest = ""
        errors.append("discovery report is not canonical finite JSON")
    if report.get("report_digest") != expected_digest:
        errors.append("discovery report digest does not match")

    campaigns = report.get("campaigns")
    if not isinstance(campaigns, dict) or set(campaigns) != {"formation", "failover"}:
        errors.append("discovery report must contain formation and failover campaigns")
        return list(dict.fromkeys(errors))
    for kind in ("formation", "failover"):
        campaign = campaigns.get(kind)
        if not isinstance(campaign, dict):
            errors.append(f"{kind} discovery campaign is invalid")
            continue
        errors.extend(
            admission.validate_discovery_campaign(
                campaign,
                expected_kind=kind,
                expected_invocation_run_id=expected_run_id,
            )
        )
        errors.extend(
            admission.validate_current_invocation_sources(
                campaign,
                artifacts_dir=artifacts_dir,
                allow_discovery_safety_rejections=True,
            )
        )

    expected_results = _candidate_results(campaigns)
    if report.get("candidate_results") != expected_results:
        errors.append("discovery candidate results are not derived from campaign cells")
    expected_survivors = {
        kind: [dict(row["candidate"]) for row in expected_results[kind] if row["status"] == "PASS"]
        for kind in ("formation", "failover")
    }
    if report.get("survivors") != expected_survivors:
        errors.append("discovery survivors are not derived from passing candidate cells")
    return list(dict.fromkeys(errors))


def _clear_context(context: capture.CaptureContext) -> None:
    context.started_trial_ids.clear()
    context.trials.clear()
    context.pairs.clear()
    context.cells.clear()
    context.invalid_samples.clear()
    context.source_refs.clear()


def _capture(args: argparse.Namespace) -> tuple[str, str]:
    artifacts_dir = args.artifacts_dir.resolve()
    args.artifacts_dir = artifacts_dir
    report_path = artifacts_dir / REPORT_NAME
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / capture.TRIALS_DIR).mkdir()

    formation_baseline = {
        "kind": "cluster_create_strategy",
        "value": capture.BASELINE_STRATEGY,
    }
    formation_candidates = capture._formation_candidates()
    failover_baseline = capture._timeout_treatment(capture.BASELINE_TIMEOUT_MS)
    failover_candidates = [capture._timeout_treatment(value) for value in (5000, 10000, 15000)]
    campaigns: dict[str, dict[str, Any]] = {}
    survivors: dict[str, list[dict[str, Any]]] = {"formation": [], "failover": []}
    contexts: dict[str, capture.CaptureContext] = {}

    try:
        product_digest = capture._product_digest()
        environment_facts = capture._environment_facts()
        environment_digest = capture._digest(environment_facts)
        contexts = {
            kind: _context(
                args,
                mode=kind,
                product_digest=product_digest,
                environment_facts=environment_facts,
                environment_digest=environment_digest,
            )
            for kind in ("formation", "failover")
        }
        formation_survivors = capture.capture_formation_discovery(
            contexts["formation"],
            baseline=formation_baseline,
            candidates=formation_candidates,
        )
        survivors["formation"] = [dict(candidate) for candidate, _duration in formation_survivors]
        campaigns["formation"] = _campaign(
            contexts["formation"],
            baseline=formation_baseline,
            candidates=formation_candidates,
            status="PASS",
            errors=[],
        )
        formation_errors = admission.validate_discovery_campaign(
            campaigns["formation"],
            expected_kind="formation",
            expected_invocation_run_id=args.run_id,
        )
        formation_errors.extend(
            admission.validate_current_invocation_sources(
                campaigns["formation"],
                artifacts_dir=artifacts_dir,
                allow_discovery_safety_rejections=True,
            )
        )
        if formation_errors:
            raise capture.CaptureError("; ".join(dict.fromkeys(formation_errors)))

        failover_survivors = capture.capture_failover_discovery(
            contexts["failover"],
            baseline=failover_baseline,
            candidates=failover_candidates,
        )
        survivors["failover"] = [dict(candidate) for candidate in failover_survivors]
        campaigns["failover"] = _campaign(
            contexts["failover"],
            baseline=failover_baseline,
            candidates=failover_candidates,
            status="PASS",
            errors=[],
        )
        failover_errors = admission.validate_discovery_campaign(
            campaigns["failover"],
            expected_kind="failover",
            expected_invocation_run_id=args.run_id,
        )
        failover_errors.extend(
            admission.validate_current_invocation_sources(
                campaigns["failover"],
                artifacts_dir=artifacts_dir,
                allow_discovery_safety_rejections=True,
            )
        )
        if failover_errors:
            raise capture.CaptureError("; ".join(dict.fromkeys(failover_errors)))
    except capture.EnvironmentBlocked as exc:
        started = any(context.started for context in contexts.values())
        status = "FAIL" if started else "BLOCKED"
        reason = f"{'ENVIRONMENT_AFTER_START' if started else 'ENVIRONMENT_BLOCKED'}: {exc}"
        if not started:
            for context in contexts.values():
                _clear_context(context)
            campaigns = {}
        else:
            for kind, context in contexts.items():
                campaigns.setdefault(
                    kind,
                    _campaign(
                        context,
                        baseline=formation_baseline if kind == "formation" else failover_baseline,
                        candidates=formation_candidates if kind == "formation" else failover_candidates,
                        status="FAIL",
                        errors=[reason],
                    ),
                )
        report = _build_report(
            args,
            status=status,
            campaigns=campaigns,
            survivors=survivors,
            errors=[reason],
        )
        capture._write_report(report_path, report)
        return status, str(exc)
    except Exception as exc:  # noqa: BLE001 - partial real evidence must close as FAIL
        reason = f"DISCOVERY_FAILED: {type(exc).__name__}: {exc}"
        for kind, context in contexts.items():
            campaigns.setdefault(
                kind,
                _campaign(
                    context,
                    baseline=formation_baseline if kind == "formation" else failover_baseline,
                    candidates=formation_candidates if kind == "formation" else failover_candidates,
                    status="FAIL",
                    errors=[reason],
                ),
            )
        report = _build_report(
            args,
            status="FAIL",
            campaigns=campaigns,
            survivors=survivors,
            errors=[reason],
        )
        capture._write_report(report_path, report)
        return "FAIL", str(exc)

    report = _build_report(
        args,
        status="PASS",
        campaigns=campaigns,
        survivors=survivors,
        errors=[],
    )
    validation_errors = validate_discovery_report(
        report,
        artifacts_dir=artifacts_dir,
        expected_run_id=args.run_id,
        expected_sha=args.tested_sha,
    )
    if validation_errors:
        report = _build_report(
            args,
            status="FAIL",
            campaigns=campaigns,
            survivors=survivors,
            errors=validation_errors,
        )
        capture._write_report(report_path, report)
        return "FAIL", "; ".join(validation_errors[:8])
    capture._write_report(report_path, report)
    return "PASS", (
        f"validated {len(campaigns['formation']['trials'])} formation and "
        f"{len(campaigns['failover']['trials'])} failover discovery trials"
    )


def run(args: argparse.Namespace) -> tuple[str, str]:
    if _forbidden_path(args.artifacts_dir):
        return "FAIL", "M2 discovery artifacts directory names forbidden non-current evidence"
    if not _authorized(args.run_id):
        return (
            "BLOCKED",
            f"real M2 discovery requires explicit {admission.AUTHORIZATION_ENV}=1 (or this run id); no trial was started",
        )
    if SHA_RE.fullmatch(str(args.tested_sha)) is None:
        return "BLOCKED", "M2 discovery tested SHA must be a full lowercase Git SHA"
    if _checkout_sha() != args.tested_sha:
        return "BLOCKED", "M2 discovery checkout does not match the authorized tested SHA"
    if not capture.RUN_ID_RE.fullmatch(str(args.run_id)):
        return "FAIL", "M2 discovery run id is not a safe current-invocation identifier"
    artifacts_dir = args.artifacts_dir.resolve()
    if artifacts_dir.exists() and any(artifacts_dir.iterdir()):
        return "FAIL", "refusing pre-existing M2 discovery artifacts"
    return _capture(args)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if _forbidden_path(args.result_path):
        return 2
    try:
        status, summary = run(args)
    except Exception as exc:  # noqa: BLE001 - result must remain machine-readable
        status, summary = "FAIL", f"M2 discovery raised {type(exc).__name__}: {exc}"
    _write_result(args.result_path, status, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
