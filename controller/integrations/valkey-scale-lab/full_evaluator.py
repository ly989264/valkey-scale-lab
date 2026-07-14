#!/usr/bin/env python3
"""Run complete Valkey acceptance and return one Controller evaluation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from controller import EnvironmentBlocked, Milestone, load_milestone


ROOT = Path(__file__).resolve().parent
EVALUATORS = ROOT / "evaluators"
TOOLS = ROOT / "tools"


def _load(name: str, path: Path, import_root: Path | None = None):
    if import_root is not None:
        sys.path.insert(0, str(import_root))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if import_root is not None:
            sys.path.pop(0)


VERIFICATION_RUNNER = _load("valkey_verification_runner", TOOLS / "run_verification.py")
VERIFICATION_ADMISSION = _load(
    "valkey_verification_admission", EVALUATORS / "verification_admission.py", EVALUATORS
)
EVIDENCE_ADMISSION = _load(
    "valkey_evidence_admission", EVALUATORS / "evidence_admission.py", EVALUATORS
)
PREREQUISITE = _load(
    "valkey_prerequisite", EVALUATORS / "_prerequisite.py", EVALUATORS
)


class ValkeyEvaluator:
    """Callable complete Evaluator for the minimal Controller."""

    def __init__(
        self,
        *,
        evidence_root: Path,
        run_id: str,
        python: Path = Path(sys.executable),
        prerequisite_paths: Sequence[Path] = (),
    ):
        self.evidence_root = Path(evidence_root).resolve()
        self.run_id = run_id
        self.python = Path(python).resolve()
        self.prerequisite_paths = tuple(Path(path).resolve() for path in prerequisite_paths)

    def __call__(self, milestone: Milestone, project_root: Path) -> dict[str, Any]:
        project = Path(project_root).resolve()
        source_milestone_path = project / "milestones" / milestone.id / "milestone.json"
        catalog_path = project / "verification/catalog.json"
        try:
            source = json.loads(source_milestone_path.read_text(encoding="utf-8"))
            prerequisite_ids = source.get("prerequisite_milestone_ids", [])
            if not isinstance(prerequisite_ids, list) or len(prerequisite_ids) != len(
                self.prerequisite_paths
            ):
                return self._blocked(milestone, "required prerequisite result is unavailable")
            for prerequisite_id, path in zip(prerequisite_ids, self.prerequisite_paths):
                PREREQUISITE.load_completion(path, prerequisite_id)

            product_digest = VERIFICATION_RUNNER.product_tree_digest(project)
            bundle = VERIFICATION_RUNNER.produce(
                python=self.python,
                workspace_root=project.parent,
                product_relative=project.name,
                milestone_id=milestone.id,
                run_id=self.run_id,
                expected_product_digest=product_digest,
                evidence_root=self.evidence_root,
            )
            freshness = min(
                (item.freshness_seconds for item in milestone.evidence_requirements),
                default=86400,
            )
            verification = VERIFICATION_ADMISSION.evaluate(
                milestone_path=source_milestone_path,
                catalog_path=catalog_path,
                results_schema_path=ROOT / "schemas/verification_results.schema.json",
                evidence_root=self.evidence_root,
                run_id=self.run_id,
                product_digest=product_digest,
                max_age_seconds=freshness,
            )
            real = []
            if any(item.kind == "REAL" for item in milestone.evidence_requirements):
                real = EVIDENCE_ADMISSION.evaluate(
                    milestone_path=source_milestone_path,
                    evidence_root=self.evidence_root,
                    product_root=project,
                    candidate_schema_path=project
                    / "schemas/artifact/evidence_admission_candidate.schema.json",
                    prerequisite_paths=self.prerequisite_paths,
                    run_id=self.run_id,
                    product_digest=product_digest,
                    max_age_seconds=freshness,
                )
        except Exception as exc:
            raise EnvironmentBlocked(f"Valkey full evaluation could not complete: {exc}") from exc

        suite_status = {
            f"verification.{row['suite_id']}": row["status"] for row in bundle["results"]
        }
        evidence_results = [
            self._adapt_evidence(item, suite_status=suite_status)
            for item in (*verification, *real)
        ]
        by_id = {item["id"]: item for item in evidence_results}
        expected_ids = {item.id for item in milestone.evidence_requirements}
        if set(by_id) != expected_ids:
            raise EnvironmentBlocked(
                "Valkey full evaluator result set differs from the compiled Milestone"
            )
        conditions: list[dict[str, str]] = []
        for condition in milestone.success_conditions:
            linked = [by_id[item] for item in condition.evidence_requirement_ids]
            if linked and all(item["status"] == "PASS" for item in linked):
                status = "PASS"
                summary = "all linked acceptance evidence passes"
            elif any(item["status"] == "BLOCKED_ENV" for item in linked):
                status = "BLOCKED_ENV"
                summary = "linked acceptance evidence is blocked by the environment"
            else:
                status = "FAIL"
                summary = "linked acceptance evidence does not pass"
            conditions.append({"id": condition.id, "status": status, "summary": summary})
        return {
            "condition_results": conditions,
            "evidence_results": [by_id[item.id] for item in milestone.evidence_requirements],
        }

    @staticmethod
    def _adapt_evidence(
        item: dict[str, Any], *, suite_status: dict[str, str]
    ) -> dict[str, Any]:
        requirement_id = item["requirement_id"]
        status = item["status"]
        if suite_status.get(requirement_id) == "BLOCKED":
            status = "BLOCKED_ENV"
        elif suite_status.get(requirement_id) == "FAIL":
            status = "FAIL"
        provenance = item.get("provenance")
        errors = provenance.get("errors", []) if isinstance(provenance, dict) else []
        complete_provenance = dict(provenance) if isinstance(provenance, dict) else {}
        complete_provenance.update(
            {
                "captured_at_unix": item.get("captured_at_unix"),
                "run_id": item.get("run_id"),
                "product_digest": item.get("product_digest"),
                "capture_class": item.get("capture_class"),
                "substituted": item.get("substituted"),
            }
        )
        return {
            "id": requirement_id,
            "status": status,
            "summary": "; ".join(str(error) for error in errors)
            or "acceptance evidence passes",
            "artifact": item.get("artifact"),
            "provenance": complete_provenance,
        }

    @staticmethod
    def _blocked(milestone: Milestone, summary: str) -> dict[str, Any]:
        return {
            "condition_results": [
                {"id": item.id, "status": "BLOCKED_ENV", "summary": summary}
                for item in milestone.success_conditions
            ],
            "evidence_results": [
                {"id": item.id, "status": "BLOCKED_ENV", "summary": summary}
                for item in milestone.evidence_requirements
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prerequisite", action="append", type=Path, default=[])
    args = parser.parse_args()
    evaluator = ValkeyEvaluator(
        evidence_root=args.evidence_root,
        run_id=args.run_id,
        prerequisite_paths=args.prerequisite,
    )
    value = evaluator(load_milestone(args.milestone), args.project_root)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
