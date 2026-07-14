#!/usr/bin/env python3
"""Admit current structured verification results for all declared suites."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Mapping

from _common import EvaluationError, canonical_digest, file_digest, load_json, safe_file
from _schema import validate as validate_schema


def _suite_ids(milestone: Mapping[str, Any]) -> list[str]:
    return sorted(
        {
            suite_id
            for condition in milestone.get("success_conditions", [])
            if isinstance(condition, Mapping)
            for suite_id in condition.get("suite_ids", [])
            if isinstance(suite_id, str)
        }
    )


def evaluate(
    *,
    milestone_path: Path,
    catalog_path: Path,
    results_schema_path: Path,
    evidence_root: Path,
    run_id: str,
    product_digest: str,
    now_unix: int | None = None,
    max_age_seconds: int = 86400,
) -> list[dict[str, Any]]:
    milestone = load_json(milestone_path)
    catalog = load_json(catalog_path)
    schema = load_json(results_schema_path)
    current = int(time.time()) if now_unix is None else now_unix
    suite_ids = _suite_ids(milestone)
    suites = {
        item.get("id"): item
        for item in catalog.get("suites", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    bundle_path = safe_file(evidence_root, "verification/results.json")
    bundle: dict[str, Any] = {}
    global_errors: list[str] = []
    if bundle_path is None:
        global_errors.append("verification result bundle is missing")
    else:
        bundle = load_json(bundle_path)
        global_errors.extend(
            f"result schema: {error}" for error in validate_schema(bundle, schema)
        )
    expected = {
        "schema_version": "verification-results-v1",
        "run_id": run_id,
        "product_digest": product_digest,
        "milestone_digest": canonical_digest(milestone),
        "catalog_digest": canonical_digest(catalog),
    }
    for field, value in expected.items():
        if bundle.get(field) != value:
            global_errors.append(f"verification results have invalid {field}")
    generated = bundle.get("generated_at_unix")
    if not isinstance(generated, int) or generated > current + 60 or current - generated > max_age_seconds:
        global_errors.append("verification result bundle is stale")
    unsigned_bundle = dict(bundle)
    claimed_bundle = unsigned_bundle.pop("bundle_digest", None)
    if claimed_bundle != canonical_digest(unsigned_bundle):
        global_errors.append("verification result bundle digest mismatch")
    rows = bundle.get("results")
    by_id: dict[str, dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("suite_id"), str):
                global_errors.append("invalid verification result row")
                continue
            if row["suite_id"] in by_id:
                global_errors.append(f"duplicate verification result for {row['suite_id']}")
            by_id[row["suite_id"]] = row
    else:
        global_errors.append("verification results must be an array")
    if set(by_id) != set(suite_ids):
        global_errors.append("verification result set does not match the Milestone suites")

    results: list[dict[str, Any]] = []
    for suite_id in suite_ids:
        errors = list(global_errors)
        suite = suites.get(suite_id)
        row = by_id.get(suite_id, {})
        expected_row = {
            "suite_definition_digest": canonical_digest(suite) if isinstance(suite, dict) else None,
            "status": "PASS",
            "run_id": run_id,
            "product_digest": product_digest,
            "exit_code": 0,
            "skipped": 0,
        }
        if not isinstance(suite, dict) or suite.get("status") != "READY":
            errors.append(f"suite {suite_id} is unavailable")
        for field, value in expected_row.items():
            if row.get(field) != value:
                errors.append(f"suite {suite_id} has invalid {field}")
        started = row.get("started_at_unix")
        captured = row.get("captured_at_unix")
        if (
            not isinstance(started, int)
            or not isinstance(captured, int)
            or started > captured
            or captured > current + 60
            or current - captured > max_age_seconds
        ):
            errors.append(f"suite {suite_id} result is stale or has invalid timing")
        for field in ("log", "structured_result"):
            reference = row.get(field)
            path = safe_file(evidence_root, reference.get("path")) if isinstance(reference, Mapping) else None
            if path is None or reference.get("sha256") != file_digest(path):
                errors.append(f"suite {suite_id} {field} is missing or has the wrong digest")
        unsigned_row = dict(row)
        claimed_row = unsigned_row.pop("result_digest", None)
        if claimed_row != canonical_digest(unsigned_row):
            errors.append(f"suite {suite_id} result digest mismatch")
        results.append(
            {
                "requirement_id": f"verification.{suite_id}",
                "status": "PASS" if not errors else "STALE",
                "artifact": "verification/results.json" if bundle_path is not None else "",
                "capture_class": "OTHER",
                "provenance": {"suite_id": suite_id, "errors": errors},
                "captured_at_unix": captured if isinstance(captured, int) else 0,
                "run_id": run_id,
                "product_digest": product_digest,
                "substituted": False,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--results-schema", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--product-digest", required=True)
    args = parser.parse_args()
    try:
        value = evaluate(
            milestone_path=args.milestone,
            catalog_path=args.catalog,
            results_schema_path=args.results_schema,
            evidence_root=args.evidence_root,
            run_id=args.run_id,
            product_digest=args.product_digest,
        )
        print(__import__("json").dumps(value, indent=2, sort_keys=True))
        return 0 if all(item["status"] == "PASS" for item in value) else 1
    except (EvaluationError, OSError, ValueError) as exc:
        print(f"ERROR: verification admission: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
