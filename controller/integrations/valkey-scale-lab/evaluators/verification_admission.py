#!/usr/bin/env python3
"""Admit operator-produced capability-suite receipts from dynamic evidence."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Mapping

from _common import (
    EvaluationError,
    canonical_digest,
    environment_bindings,
    file_digest,
    load_json,
    safe_file,
    write_result,
)
from _schema import validate as validate_schema


def _suite_ids(milestone: Mapping[str, Any]) -> list[str]:
    values: set[str] = set()
    for condition in milestone.get("success_conditions", []):
        if isinstance(condition, Mapping):
            values.update(
                value for value in condition.get("suite_ids", []) if isinstance(value, str)
            )
    return sorted(values)


def evaluate(
    *,
    milestone_path: Path,
    catalog_path: Path,
    receipts_schema_path: Path,
    verification_policy_path: Path,
    verification_policy_schema_path: Path,
    producer_path: Path,
    evidence_root: Path,
    run_id: str,
    product_digest: str,
    now_unix: int | None = None,
    max_age_seconds: int = 86400,
) -> list[dict[str, Any]]:
    milestone = load_json(milestone_path)
    catalog = load_json(catalog_path)
    if milestone.get("schema_version") != "valkey-milestone-v2":
        raise EvaluationError("unsupported milestone schema")
    schema = load_json(receipts_schema_path)
    policy = load_json(verification_policy_path)
    policy_schema = load_json(verification_policy_schema_path)
    current = int(time.time()) if now_unix is None else now_unix
    suite_ids = _suite_ids(milestone)
    catalog_by_id = {
        row.get("id"): row
        for row in catalog.get("suites", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    artifact = "verification/receipts.json"
    receipt_path = safe_file(evidence_root, artifact)
    envelope: dict[str, Any] = {}
    global_errors = [
        f"verification policy schema: {error}"
        for error in validate_schema(policy, policy_schema)
    ]
    if receipt_path is None:
        global_errors.append("verification receipt envelope is missing")
    else:
        envelope = load_json(receipt_path)
        global_errors.extend(f"receipt schema: {error}" for error in validate_schema(envelope, schema))
    expected_bindings = {
        "schema_version": "verification-receipts-v2",
        "run_id": run_id,
        "product_digest": product_digest,
        "milestone_digest": canonical_digest(milestone),
        "catalog_digest": canonical_digest(catalog),
        "producer_digest": file_digest(producer_path),
        "toolchain_digest": policy.get("toolchain_digest"),
    }
    for field, expected in expected_bindings.items():
        if envelope.get(field) != expected:
            global_errors.append(f"verification receipts have stale or false {field}")
    generated = envelope.get("generated_at_unix")
    if not isinstance(generated, int) or generated > current + 60 or current - generated > max_age_seconds:
        global_errors.append("verification receipt envelope is stale")
    unsigned_envelope = dict(envelope)
    claimed_envelope = unsigned_envelope.pop("envelope_digest", None)
    if claimed_envelope != canonical_digest(unsigned_envelope):
        global_errors.append("verification receipt envelope digest mismatch")
    receipt_rows = envelope.get("receipts")
    receipt_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(receipt_rows, list):
        for row in receipt_rows:
            if not isinstance(row, dict) or not isinstance(row.get("suite_id"), str):
                global_errors.append("verification receipt row is invalid")
                continue
            if row["suite_id"] in receipt_by_id:
                global_errors.append(f"duplicate receipt for suite {row['suite_id']}")
            receipt_by_id[row["suite_id"]] = row
    else:
        global_errors.append("verification receipts must be an array")
    if set(receipt_by_id) != set(suite_ids):
        global_errors.append("verification receipt set does not match milestone capability suites")

    results: list[dict[str, Any]] = []
    for suite_id in suite_ids:
        errors = list(global_errors)
        suite = catalog_by_id.get(suite_id)
        receipt = receipt_by_id.get(suite_id, {})
        if not isinstance(suite, dict):
            errors.append(f"unknown suite {suite_id}")
        elif suite.get("status") != "READY":
            errors.append(f"suite {suite_id} is {suite.get('status')}")
        expected_row = {
            "suite_definition_digest": canonical_digest(suite) if isinstance(suite, dict) else None,
            "status": "PASS",
            "run_id": run_id,
            "product_digest": product_digest,
            "exit_code": 0,
            "skipped": 0,
            "command_digest": canonical_digest(suite.get("argv")) if isinstance(suite, dict) else None,
            "producer_digest": expected_bindings["producer_digest"],
            "toolchain_digest": expected_bindings["toolchain_digest"],
        }
        for field, expected in expected_row.items():
            if receipt.get(field) != expected:
                errors.append(f"suite {suite_id} has invalid {field}")
        started = receipt.get("started_at_unix")
        captured = receipt.get("captured_at_unix")
        if (
            not isinstance(started, int)
            or not isinstance(captured, int)
            or started > captured
            or captured > current + 60
            or current - captured > max_age_seconds
        ):
            errors.append(f"suite {suite_id} receipt is stale or has invalid timing")
            captured = 0
        log = receipt.get("log")
        log_path = safe_file(evidence_root, log.get("path")) if isinstance(log, Mapping) else None
        if log_path is None or log.get("sha256") != file_digest(log_path):
            errors.append(f"suite {suite_id} log is missing or has the wrong digest")
        suite_result_ref = receipt.get("suite_result")
        suite_result_path = (
            safe_file(evidence_root, suite_result_ref.get("path"))
            if isinstance(suite_result_ref, Mapping)
            else None
        )
        if (
            suite_result_path is None
            or suite_result_ref.get("sha256") != file_digest(suite_result_path)
        ):
            errors.append(f"suite {suite_id} structured result is missing or has the wrong digest")
        else:
            suite_result = load_json(suite_result_path)
            expected_result = {
                "schema_version": "verification-suite-result-v1",
                "suite_id": suite_id,
                "status": receipt.get("status"),
                "exit_code": receipt.get("exit_code"),
                "skipped": receipt.get("skipped"),
                "started_at_unix": receipt.get("started_at_unix"),
                "captured_at_unix": receipt.get("captured_at_unix"),
            }
            if suite_result != expected_result:
                errors.append(f"suite {suite_id} receipt does not match its structured result")
        unsigned_receipt = dict(receipt)
        claimed_receipt = unsigned_receipt.pop("receipt_digest", None)
        if claimed_receipt != canonical_digest(unsigned_receipt):
            errors.append(f"suite {suite_id} receipt digest mismatch")
        status = "PASS" if not errors else "MISSING" if receipt_path is None else "STALE" if any(
            "stale" in error for error in errors
        ) else "UNTRUSTED"
        results.append(
            {
                "requirement_id": f"verification.{suite_id}",
                "status": status,
                "artifact": artifact if receipt_path is not None else "",
                "capture_class": "OTHER",
                "provenance": (
                    {
                        "receipt_digest": claimed_receipt,
                        "envelope_digest": claimed_envelope,
                        "log_digest": log.get("sha256") if isinstance(log, Mapping) else None,
                        "suite_result_digest": suite_result_ref.get("sha256")
                        if isinstance(suite_result_ref, Mapping)
                        else None,
                        "producer_digest": expected_bindings["producer_digest"],
                        "toolchain_digest": expected_bindings["toolchain_digest"],
                    }
                    if not errors
                    else {"errors": errors}
                ),
                "captured_at_unix": captured,
                "run_id": run_id,
                "product_digest": product_digest,
                "substituted": False,
            }
        )
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--receipts-schema", type=Path, required=True)
    parser.add_argument("--verification-policy", type=Path, required=True)
    parser.add_argument("--verification-policy-schema", type=Path, required=True)
    parser.add_argument("--producer", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    evaluator_id, run_id, product_digest, input_digest, result_path, evidence_root = environment_bindings()
    evidence = evaluate(
        milestone_path=args.milestone,
        catalog_path=args.catalog,
        receipts_schema_path=args.receipts_schema,
        verification_policy_path=args.verification_policy,
        verification_policy_schema_path=args.verification_policy_schema,
        producer_path=args.producer,
        evidence_root=evidence_root,
        run_id=run_id,
        product_digest=product_digest,
    )
    return write_result(
        evaluator_id=evaluator_id,
        run_id=run_id,
        product_digest=product_digest,
        input_digest=input_digest,
        result_path=result_path,
        condition_results=[],
        evidence_results=evidence,
    )


if __name__ == "__main__":
    raise SystemExit(main())
