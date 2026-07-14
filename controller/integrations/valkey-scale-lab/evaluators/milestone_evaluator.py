#!/usr/bin/env python3
"""Evaluate sealed milestone structure and prerequisite completion authority."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Sequence

from _common import EvaluationError, environment_bindings, load_json, write_result
from _prerequisite import load_completion


def evaluate(
    *,
    milestone_path: Path,
    catalog_path: Path,
    prerequisite_paths: Sequence[Path],
) -> list[dict[str, Any]]:
    milestone = load_json(milestone_path)
    catalog = load_json(catalog_path)
    if milestone.get("schema_version") != "valkey-milestone-v1":
        raise EvaluationError("unsupported milestone schema")
    if catalog.get("schema_version") != "verification-catalog-v1":
        raise EvaluationError("unsupported catalog schema")
    prerequisite_ids = milestone.get("prerequisite_milestone_ids")
    if not isinstance(prerequisite_ids, list) or len(prerequisite_ids) != len(
        prerequisite_paths
    ):
        raise EvaluationError("sealed prerequisite inputs do not match the milestone")
    prerequisite_failures: list[str] = []
    for prerequisite_id, path in zip(prerequisite_ids, prerequisite_paths):
        try:
            load_completion(Path(path), prerequisite_id)
        except EvaluationError as exc:
            prerequisite_failures.append(str(exc))
    catalog_rows = catalog.get("suites")
    if not isinstance(catalog_rows, list):
        raise EvaluationError("catalog suites must be an array")
    catalog_by_id = {
        row.get("id"): row for row in catalog_rows if isinstance(row, dict)
    }
    condition_results: list[dict[str, Any]] = []
    conditions = milestone.get("success_conditions")
    if not isinstance(conditions, list):
        raise EvaluationError("milestone success_conditions must be an array")
    for condition in conditions:
        if not isinstance(condition, dict) or not isinstance(condition.get("id"), str):
            raise EvaluationError("milestone contains an invalid success condition")
        failures = list(prerequisite_failures)
        suite_ids = condition.get("suite_ids")
        if not isinstance(suite_ids, list):
            failures.append("condition suite_ids is invalid")
            suite_ids = []
        for suite_id in suite_ids:
            suite = catalog_by_id.get(suite_id)
            if not isinstance(suite, dict):
                failures.append(f"unknown suite {suite_id}")
            elif suite.get("status") != "READY":
                failures.append(f"suite {suite_id} is {suite.get('status')}")
        condition_results.append(
            {
                "condition_id": condition["id"],
                "status": "PASS" if not failures else "FAIL",
                "summary": (
                    "sealed milestone, catalog, and prerequisite authority are valid"
                    if not failures
                    else "; ".join(failures)
                ),
            }
        )
    return condition_results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--prerequisite", action="append", type=Path, default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    evaluator_id, run_id, product_digest, input_digest, result_path, _ = environment_bindings()
    conditions = evaluate(
        milestone_path=args.milestone,
        catalog_path=args.catalog,
        prerequisite_paths=args.prerequisite,
    )
    return write_result(
        evaluator_id=evaluator_id,
        run_id=run_id,
        product_digest=product_digest,
        input_digest=input_digest,
        result_path=result_path,
        condition_results=conditions,
        evidence_results=[],
    )


if __name__ == "__main__":
    raise SystemExit(main())
