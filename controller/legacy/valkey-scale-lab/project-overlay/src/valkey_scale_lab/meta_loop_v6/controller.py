from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .contracts import _check_errors, load_json, sha256_file, validate_control_block
from .digests import files_digest, product_tree_digest, repair_scope_digest, tree_digest
from .runner import ProgramRunner
from .store import StateStore


class MetaLoopError(RuntimeError):
    pass


class MetaLoopController:
    """V6 scheduler: immutable kernel, versioned evaluator, gap-scoped budgets."""

    def __init__(self, project_root: Path, control_path: Path, state_root: Path, workspace_root: Path):
        self.project_root = project_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.control_path = control_path.resolve()
        self.state_root = state_root.resolve()
        self.store = StateStore(self.state_root)

    def doctor(self) -> dict[str, Any]:
        control = self._control()
        errors: list[str] = []
        notices: list[str] = []
        if self.store.exists():
            state = self.store.load()
            if state.get("control_digest") != sha256_file(self.control_path):
                errors.append("control block changed after bootstrap")
            if state.get("kernel_digest") != self._kernel_digest():
                errors.append("controller kernel changed after bootstrap")
            evaluator_changed = state.get("evaluator_digest") != self._evaluator_digest()
            active = state.get("active_work_item")
            if evaluator_changed and isinstance(active, dict) and active.get("type") == "EVALUATOR_REPAIR":
                notices.append("evaluator differs as expected during an active controlled repair")
            elif evaluator_changed:
                errors.append("evaluator changed outside an active controlled repair")
            errors.extend(self._review_check_anchor_errors(state, control))
            errors.extend(self.store.verify_event_chain(state))
            errors.extend(self._state_seal_errors(state))
        return {
            "status": "PASS" if not errors else "FAIL",
            "goal_id": control["goal_id"],
            "objective_count": len(control["objectives"]),
            "errors": errors,
            "notices": notices,
        }

    def bootstrap(self) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            if self.store.exists():
                return self._status_view(self._state(), control)
            state = self._new_state(control)
            state["migration"] = {"status": "PASS", "source_run": None, "attempts": 0, "last_result": None}
            self._event(state, "BOOTSTRAP", {"goal_id": control["goal_id"]})
            self.store.save(state)
            return self._status_view(state, control)

    def migrate_v2(self, receipt_path: Path) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            if self.store.exists():
                return self._status_view(self._state(), control)
            receipt = load_json(receipt_path.resolve())
            if receipt.get("schema_version") != "meta-m1-v3-migration-receipt-v1":
                raise MetaLoopError("unsupported migration receipt")
            if receipt.get("source_run") != "milestone1-v2":
                raise MetaLoopError("migration receipt is not for milestone1-v2")
            source_state_path = Path(str(receipt.get("source_state_path", ""))).resolve()
            if not source_state_path.is_file() or sha256_file(source_state_path) != receipt.get("source_state_sha256"):
                raise MetaLoopError("v2 state does not match the migration receipt")
            manifest_path = Path(str(receipt.get("scale50_manifest_path", ""))).resolve()
            if not manifest_path.is_file() or sha256_file(manifest_path) != receipt.get("scale50_manifest_sha256"):
                raise MetaLoopError("v2 scale-50 manifest does not match the migration receipt")
            source = load_json(source_state_path)
            if source.get("last_event_hash") != receipt.get("source_last_event_hash"):
                raise MetaLoopError("v2 last event hash does not match the migration receipt")
            if StateStore.verify_event_chain(source):
                raise MetaLoopError("v2 event chain is invalid")
            if source.get("goal_id") != "milestone1-local-complete-v2":
                raise MetaLoopError("migration source is not the blocked v2 Milestone 1 run")
            if source.get("control_digest") != receipt.get("source_control_digest"):
                raise MetaLoopError("v2 control digest does not match the migration receipt")
            if source.get("harness_digest") != receipt.get("source_harness_digest"):
                raise MetaLoopError("v2 harness digest does not match the migration receipt")
            if source.get("iteration") != receipt.get("source_iteration"):
                raise MetaLoopError("v2 iteration does not match the migration receipt")
            expected_statuses = {
                **{oid: "COMPLETE" for oid in (
                    "O1_TRIGGER_AND_SAFETY",
                    "O2_LIFECYCLE_AND_TELEMETRY",
                    "O3_MANAGEMENT_AND_STABILITY",
                    "O4_FAULT_FAILOVER_AND_RECOVERY",
                )},
                "O5_EVIDENCE_REPORT_AND_SCALE_50": "BLOCKED",
                "O6_SCALE_200_AND_FINAL": "PENDING",
            }
            actual_statuses = {
                oid: source.get("objectives", {}).get(oid, {}).get("status")
                for oid in expected_statuses
            }
            if actual_statuses != expected_statuses:
                raise MetaLoopError("v2 objective statuses do not match the reviewed blocked-run snapshot")

            state = self._new_state(control)
            superseded = {
                "exact-50-report-required-surfaces",
                "exact-scale-machine-readable-report-admission",
            }
            for objective in control["objectives"]:
                oid = objective["id"]
                old = source.get("objectives", {}).get(oid, {})
                progress = state["objectives"][oid]
                progress["added_checks"] = [
                    check for check in old.get("added_checks", [])
                    if isinstance(check, dict) and check.get("id") not in superseded
                ]
                progress["check_anchors"] = {
                    check["id"]: self._review_check_anchor(check, control)
                    for check in progress["added_checks"]
                }
                progress["review_rounds"] = int(old.get("review_rounds", 0))
                progress["migration_notes"] = {
                    "source_status": old.get("status"),
                    "superseded_checks": sorted(
                        check.get("id") for check in old.get("added_checks", [])
                        if isinstance(check, dict) and check.get("id") in superseded
                    ),
                }
                if oid in {"O1_TRIGGER_AND_SAFETY", "O2_LIFECYCLE_AND_TELEMETRY", "O3_MANAGEMENT_AND_STABILITY", "O4_FAULT_FAILOVER_AND_RECOVERY"}:
                    progress["status"] = "COMPLETE"
                    progress["completion_reason"] = "MIGRATED_PROVISIONAL_PENDING_GLOBAL_REGRESSION"
                else:
                    progress["status"] = "PENDING"
                    progress["attempts"] = 0
                    progress["replans"] = 0
                    # Reopened v3 work receives fresh review under the strengthened evaluator.
                    progress["review_rounds"] = 0

            state["migration"] = {
                "status": "PENDING_REGRESSION",
                "source_run": "milestone1-v2",
                "source_state_sha256": receipt["source_state_sha256"],
                "source_last_event_hash": receipt["source_last_event_hash"],
                "receipt_path": str(receipt_path.resolve()),
                "receipt_sha256": sha256_file(receipt_path.resolve()),
                "scale50_admission_status": "QUARANTINED_RAW_CAPTURE",
                "scale50_admission_sha256": receipt.get("scale50_admission_sha256"),
                "attempts": 0,
                "last_result": None,
            }
            self._event(
                state,
                "MIGRATED_FROM_V2",
                {
                    "source_state_sha256": receipt["source_state_sha256"],
                    "source_last_event_hash": receipt["source_last_event_hash"],
                    "scale50_status": "QUARANTINED_RAW_CAPTURE",
                },
            )
            self.store.save(state)
            return self._status_view(state, control)

    def migrate_v5(self, source_state_path: Path) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            if self.store.exists():
                return self._status_view(self._state(), control)
            source_state_path = source_state_path.resolve()
            expected_path = (
                self.workspace_root
                / "loop_evidence"
                / "meta_runs"
                / "milestone1-v5"
                / "state"
                / "loop_state.json"
            ).resolve()
            if source_state_path != expected_path or not source_state_path.is_file():
                raise MetaLoopError("v5 migration source must be the canonical milestone1-v5 state")
            source = load_json(source_state_path)
            if source.get("schema_version") != "v5" or source.get("goal_id") != "milestone1-local-complete-v5":
                raise MetaLoopError("migration source is not a v5 Milestone 1 run")
            if source.get("active_work_item") is not None:
                raise MetaLoopError("v5 migration requires no active work item")
            chain_errors = StateStore.verify_event_chain(source)
            if chain_errors:
                raise MetaLoopError("v5 event chain is invalid: " + "; ".join(chain_errors))
            claimed_seal = source.get("events", [{}])[-1].get("state_payload_hash")
            if claimed_seal != self._state_payload_digest(source):
                raise MetaLoopError("v5 source state payload seal is invalid")
            expected_statuses = {
                **{
                    oid: "COMPLETE"
                    for oid in (
                        "O1_TRIGGER_AND_SAFETY",
                        "O2_LIFECYCLE_AND_TELEMETRY",
                        "O3_MANAGEMENT_AND_STABILITY",
                        "O4_FAULT_FAILOVER_AND_RECOVERY",
                    )
                },
                "O5_EVIDENCE_REPORT_AND_SCALE_50": "PENDING",
                "O6_SCALE_200_AND_FINAL": "PENDING",
            }
            actual_statuses = {
                oid: source.get("objectives", {}).get(oid, {}).get("status")
                for oid in expected_statuses
            }
            if actual_statuses != expected_statuses:
                raise MetaLoopError("v5 objective statuses do not match the reviewed migration point")

            capture = next(
                (
                    item
                    for item in source.get("cache", {}).values()
                    if isinstance(item, dict)
                    and item.get("check_id") == "exact-real-50-capture"
                    and item.get("status") == "PASS"
                ),
                None,
            )
            if capture is None:
                raise MetaLoopError("v5 migration requires a successful exact-real-50 capture result")
            evidence_dir = expected_path.parents[1] / "evidence" / "scale-50"
            admission_path = evidence_dir / "admission.json"
            admission = load_json(admission_path)
            if admission.get("status") != "PASS" or admission.get("requested_nodes") != 50 or admission.get("observed_nodes") != 50:
                raise MetaLoopError("v5 scale-50 admission envelope does not describe a successful exact capture")
            if admission.get("product_digest") != product_tree_digest(self.project_root):
                raise MetaLoopError("v5 scale-50 capture product digest is not current")
            for artifact in admission.get("artifacts", []):
                if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
                    raise MetaLoopError("v5 scale-50 capture has an invalid artifact manifest")
                artifact_path = (evidence_dir / artifact["path"]).resolve()
                if not artifact_path.is_relative_to(evidence_dir.resolve()) or not artifact_path.is_file():
                    raise MetaLoopError("v5 scale-50 capture artifact is missing or escapes its evidence root")
                if artifact.get("sha256") != sha256_file(artifact_path):
                    raise MetaLoopError("v5 scale-50 capture artifact hash mismatch")

            state = self._new_state(control)
            for objective in control["objectives"]:
                oid = objective["id"]
                old = source["objectives"][oid]
                progress = state["objectives"][oid]
                progress["added_checks"] = [dict(check) for check in old.get("added_checks", []) if isinstance(check, dict)]
                progress["check_anchors"] = {
                    check["id"]: self._review_check_anchor(check, control)
                    for check in progress["added_checks"]
                }
                progress["review_rounds"] = int(old.get("review_rounds", 0))
                progress["migration_notes"] = {"source_status": old.get("status")}
                if expected_statuses[oid] == "COMPLETE":
                    progress["status"] = "COMPLETE"
                    progress["completion_reason"] = "MIGRATED_FROM_V5_REVIEWED_COMPLETE"

            state["migration"] = {
                "status": "PASS",
                "source_run": "milestone1-v5",
                "source_state_path": str(source_state_path),
                "source_state_sha256": sha256_file(source_state_path),
                "source_last_event_hash": source.get("last_event_hash"),
                "scale50_capture_cache_key": capture.get("cache_key"),
                "scale50_evidence_path": str(evidence_dir),
                "scale50_evidence_digest": tree_digest(evidence_dir),
                "attempts": 0,
                "last_result": None,
            }
            self._event(
                state,
                "MIGRATED_FROM_V5",
                {
                    "source_state_sha256": state["migration"]["source_state_sha256"],
                    "source_last_event_hash": source.get("last_event_hash"),
                    "scale50_evidence_digest": state["migration"]["scale50_evidence_digest"],
                    "source_cache_status": "NOT_IMPORTED",
                },
            )
            self.store.save(state)
            return self._status_view(state, control)

    def status(self) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            return self._status_view(self._state(), control)

    def next_work_item(self) -> dict[str, Any]:
        control = self._control()
        policy = control["controller_policy"]
        with self.store.locked():
            state = self._state()
            active = state.get("active_work_item")
            if isinstance(active, dict):
                return active

            migration = state.get("migration", {})
            if migration.get("status") != "PASS":
                if migration.get("status") == "BLOCKED":
                    return {"type": "BLOCKED", "reason": "migration regression budget exhausted", "migration": migration}
                if int(migration.get("attempts", 0)) >= policy["max_attempts_per_objective"]:
                    migration["status"] = "BLOCKED"
                    self._event(state, "MIGRATION_BLOCKED", {"reason": "migration regression budget exhausted"})
                    self.store.save(state)
                    return {"type": "BLOCKED", "reason": "migration regression budget exhausted", "migration": migration}
                migration["attempts"] = int(migration.get("attempts", 0)) + 1
                work = {
                    "type": "RECOVERY_WORK",
                    "work_item_id": uuid.uuid4().hex,
                    "attempt": migration["attempts"],
                    "instruction": "Fix the reported non-real regression only, then run evaluate. Do not edit v2 evidence or controller state.",
                    "last_program_result": self._compact_result(migration.get("last_result")),
                }
                return self._issue(state, work, policy)

            while True:
                objective = self._next_ready_objective(state, control)
                if objective is None:
                    if all(item["status"] == "COMPLETE" for item in state["objectives"].values()):
                        return {"type": "DONE", "goal_id": control["goal_id"], "summary": self._compact_summary(state, control)}
                    return {"type": "BLOCKED", "reason": "No objective is ready; inspect blocked dependencies.", "summary": self._compact_summary(state, control)}

                oid = objective["id"]
                progress = state["objectives"][oid]
                if progress["status"] == "EVALUATOR_REPAIR_REQUIRED":
                    if progress["attempts"] >= policy["max_attempts_per_objective"]:
                        progress["status"] = "BLOCKED"
                        self._event(state, "OBJECTIVE_BLOCKED", {"objective_id": oid, "reason": "evaluator repair budget exhausted"})
                        self.store.save(state)
                        continue
                    progress["attempts"] += 1
                    work = {
                        "type": "EVALUATOR_REPAIR",
                        "work_item_id": uuid.uuid4().hex,
                        "objective_id": oid,
                        "attempt": progress["attempts"],
                        "allowed_paths": progress["active_gap"]["allowed_repair_paths"],
                        "baseline_product_digest": progress["active_gap"]["baseline_product_digest"],
                        "program_check": progress["active_gap"]["program_check"],
                        "instruction": "Strengthen only the evaluator and hermetic evaluator tests. Then run accept-evaluator-repair; do not run normal evaluate.",
                    }
                    return self._issue(state, work, policy)

                if progress["status"] == "REVERIFY":
                    work = {
                        "type": "VERIFY",
                        "work_item_id": uuid.uuid4().hex,
                        "objective_id": oid,
                        "instruction": "Evaluator repair was accepted. Do not edit files; run evaluate to re-admit the objective under the new evaluator.",
                    }
                    return self._issue(state, work, policy)

                if progress["status"] == "PROGRAM_PASS":
                    if not self._program_inputs_current(control, objective, progress):
                        progress["status"] = "PENDING"
                        progress["attempts"] = max(0, progress["attempts"] - 1)
                        progress["last_result"] = {"status": "STALE", "reason": "program inputs changed after PASS"}
                        self._event(state, "PROGRAM_RESULT_STALE", {"objective_id": oid})
                        self.store.save(state)
                        continue
                    if progress["review_rounds"] >= policy["max_review_rounds_per_objective"]:
                        progress["status"] = "COMPLETE"
                        progress["completion_reason"] = "PROGRAM_PASS_AND_REVIEW_NOVELTY_BUDGET_EXHAUSTED"
                        self._event(state, "OBJECTIVE_COMPLETE", {"objective_id": oid, "reason": progress["completion_reason"]})
                        self.store.save(state)
                        continue
                    return self._issue(state, self._review_item(objective, progress, "ACCEPTANCE", policy), policy)

                cached_stagnation = self._last_failure_cached(progress) and progress["stagnant_attempts"] >= 1
                exhausted = progress["attempts"] >= policy["max_attempts_per_objective"]
                stagnant = progress["stagnant_attempts"] >= policy["stagnation_limit"] or cached_stagnation
                if exhausted or stagnant:
                    if progress["replans"] >= policy["max_replans_per_objective"]:
                        progress["status"] = "BLOCKED"
                        self._event(state, "OBJECTIVE_BLOCKED", {"objective_id": oid, "reason": "current gap budget exhausted"})
                        self.store.save(state)
                        continue
                    return self._issue(state, self._review_item(objective, progress, "REPLAN", policy), policy)

                progress["attempts"] += 1
                progress["status"] = "WORKING"
                work = {
                    "type": "WORK",
                    "work_item_id": uuid.uuid4().hex,
                    "objective_id": oid,
                    "title": objective["title"],
                    "attempt": progress["attempts"],
                    "attempts_remaining_after_this": policy["max_attempts_per_objective"] - progress["attempts"],
                    "contract_clauses": objective["clauses"],
                    "context_paths": objective["context_paths"],
                    "gap": progress.get("active_gap"),
                    "last_program_result": self._compact_result(progress["last_result"]),
                    "instruction": "Choose the best implementation approach for this product gap, then run evaluate. Do not edit controller state or weaken checks.",
                }
                return self._issue(state, work, policy)

    def evaluate_active(self) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            state = self._state()
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") not in {"WORK", "VERIFY", "RECOVERY_WORK"}:
                raise MetaLoopError("evaluate requires an active WORK, VERIFY, or RECOVERY_WORK item")
            if work["type"] == "RECOVERY_WORK":
                results = self._run_checks(control["closure_checks"], state, control)
                passed = len(results) == len(control["closure_checks"]) and all(item["status"] == "PASS" for item in results)
                report = self._evaluation_report("RECOVERY_REGRESSION", results, len(control["closure_checks"]), passed)
                migration = state["migration"]
                migration["last_result"] = report
                migration["status"] = "PASS" if passed else "FAILED_REGRESSION"
                state["active_work_item"] = None
                self._event(state, "MIGRATION_REGRESSION", {"status": report["status"], "failed_check": self._failed_check_id(report)})
                self.store.save(state)
                return self._compact_evaluation(report)

            objective = self._objective(control, work["objective_id"])
            progress = state["objectives"][objective["id"]]
            checks = self._objective_check_plan(control, objective, progress)
            results = self._run_checks(checks, state, control)
            passed = len(results) == len(checks) and all(item["status"] == "PASS" for item in results)
            report = self._evaluation_report(objective["id"], results, len(checks), passed)
            failed = next((item for item in results if item["status"] == "FAIL"), None)
            if failed is not None:
                # A code edit must not manufacture a fresh retry budget. Budget the
                # failing gate; moving to another gate or a novel reviewer check is
                # what establishes a new gap.
                fingerprint = hashlib.sha256(str(failed["check_id"]).encode()).hexdigest()
                if fingerprint != progress.get("failure_fingerprint"):
                    progress["failure_fingerprint"] = fingerprint
                    progress["attempts"] = 1
                    progress["replans"] = 0
                    progress["stagnant_attempts"] = 0
                    progress["best_score"] = report["score"]
                    if not isinstance(progress.get("active_gap"), dict) or progress["active_gap"].get("kind") != "EVALUATOR_GAP":
                        progress["active_gap"] = {"kind": "PRODUCT_GAP", "failure_fingerprint": fingerprint, "failed_check": failed["check_id"]}
                elif report["score"] > progress["best_score"]:
                    progress["best_score"] = report["score"]
                    progress["stagnant_attempts"] = 0
                else:
                    progress["stagnant_attempts"] += 1
            else:
                progress["failure_fingerprint"] = None
                progress["stagnant_attempts"] = 0
                progress["best_score"] = report["score"]
                progress["active_gap"] = None
            progress["last_result"] = report
            progress["status"] = "PROGRAM_PASS" if passed else "PENDING"
            state["active_work_item"] = None
            self._event(state, "PROGRAM_EVALUATED", {"objective_id": objective["id"], "status": report["status"], "score": report["score"], "failed_check": self._failed_check_id(report)})
            self.store.save(state)
            return self._compact_evaluation(report)

    def submit_review(self, report: dict[str, Any]) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            state = self._state()
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") not in {"REVIEW_ACCEPTANCE", "REVIEW_REPLAN"}:
                raise MetaLoopError("review requires an active reviewer item")
            if report.get("work_item_id") != work["work_item_id"]:
                raise MetaLoopError("review work_item_id does not match")
            objective = self._objective(control, work["objective_id"])
            progress = state["objectives"][objective["id"]]

            if work["type"] == "REVIEW_REPLAN":
                diagnosis = report.get("diagnosis")
                focus = report.get("recommended_focus")
                if not isinstance(diagnosis, str) or not diagnosis.strip() or not isinstance(focus, list) or not focus:
                    raise MetaLoopError("replan requires diagnosis and recommended_focus")
                progress["replans"] += 1
                progress["attempts"] = 0
                progress["stagnant_attempts"] = 0
                progress["best_score"] = -1
                progress["status"] = "PENDING"
                progress["last_result"] = {"status": "REPLAN", "diagnosis": diagnosis, "recommended_focus": focus}
                event = {"objective_id": objective["id"], "decision": "REPLAN"}
            else:
                decision = report.get("decision")
                if decision not in {"NO_GAP", "GAP"}:
                    raise MetaLoopError("acceptance decision must be NO_GAP or GAP")
                progress["review_rounds"] += 1
                if decision == "NO_GAP":
                    if not self._program_inputs_current(control, objective, progress):
                        progress["review_rounds"] -= 1
                        progress["status"] = "PENDING"
                        progress["attempts"] = 0
                        progress["last_result"] = {"status": "STALE", "reason": "program inputs changed after PASS"}
                        state["active_work_item"] = None
                        self._event(state, "PROGRAM_RESULT_STALE", {"objective_id": objective["id"]})
                        self.store.save(state)
                        return {"status": "STALE_PROGRAM_RESULT", "action": "run next and evaluate"}
                    progress["status"] = "COMPLETE"
                    progress["completion_reason"] = "PROGRAM_PASS_AND_REVIEW_FOUND_NO_UNCHECKED_GAP"
                    event = {"objective_id": objective["id"], "decision": "NO_GAP"}
                else:
                    gap_kind = report.get("gap_kind")
                    if gap_kind not in {"PRODUCT_GAP", "EVALUATOR_GAP"}:
                        raise MetaLoopError("review GAP requires gap_kind PRODUCT_GAP or EVALUATOR_GAP")
                    check = self._validate_review_gap(report, objective)
                    reproduction = self._runner(control).run(check, state["cache"])
                    if reproduction["status"] != "FAIL":
                        raise MetaLoopError("review gap was not reproduced")
                    if any(existing["id"] == check["id"] for existing in self._all_checks(control, objective, progress)):
                        raise MetaLoopError("review check id is not novel")
                    evaluator_inputs = {"scripts/meta_m1_evidence_gate.py", "scripts/meta_m1_product_gate_contract.py"}
                    if gap_kind == "EVALUATOR_GAP" and evaluator_inputs.isdisjoint(check["inputs"]):
                        raise MetaLoopError("EVALUATOR_GAP must directly cover a versioned evaluator")
                    if gap_kind == "PRODUCT_GAP" and not evaluator_inputs.isdisjoint(check["inputs"]):
                        raise MetaLoopError("a check covering the versioned evaluator must be classified EVALUATOR_GAP")
                    progress["added_checks"].append(check)
                    progress["check_anchors"][check["id"]] = self._review_check_anchor(check, control)
                    progress["attempts"] = 0
                    progress["replans"] = 0
                    progress["stagnant_attempts"] = 0
                    progress["best_score"] = -1
                    progress["failure_fingerprint"] = hashlib.sha256(str(check["id"]).encode()).hexdigest()
                    allowed_repair_paths = [
                        "scripts/meta_m1_evidence_gate.py",
                        "scripts/meta_m1_product_gate_contract.py",
                    ]
                    progress["active_gap"] = {
                        "kind": gap_kind,
                        "finding": report.get("finding"),
                        "contract_clause": report.get("contract_clause"),
                        "program_check": check,
                        "baseline_product_digest": product_tree_digest(self.project_root),
                        "baseline_evaluator_digest": self._evaluator_digest(),
                        "allowed_repair_paths": allowed_repair_paths,
                        "baseline_repair_scope_digest": repair_scope_digest(self.project_root, allowed_repair_paths),
                    }
                    progress["status"] = "EVALUATOR_REPAIR_REQUIRED" if gap_kind == "EVALUATOR_GAP" else "PENDING"
                    progress["last_result"] = {"status": "REVIEW_GAP", "finding": report.get("finding"), "reproduction": reproduction, "gap_kind": gap_kind}
                    event = {"objective_id": objective["id"], "decision": "GAP", "gap_kind": gap_kind, "check_id": check["id"]}

            state["active_work_item"] = None
            self._event(state, "REVIEW_SUBMITTED", event)
            self.store.save(state)
            return self._status_view(state, control)

    def accept_evaluator_repair(self) -> dict[str, Any]:
        control = self._control()
        with self.store.locked():
            state = self._state(allow_evaluator_change=True)
            work = state.get("active_work_item")
            if not isinstance(work, dict) or work.get("type") != "EVALUATOR_REPAIR":
                raise MetaLoopError("accept-evaluator-repair requires an active EVALUATOR_REPAIR item")
            objective = self._objective(control, work["objective_id"])
            progress = state["objectives"][objective["id"]]
            gap = progress.get("active_gap")
            if not isinstance(gap, dict) or gap.get("kind") != "EVALUATOR_GAP":
                raise MetaLoopError("active evaluator gap is missing")
            if product_tree_digest(self.project_root) != gap.get("baseline_product_digest"):
                raise MetaLoopError("product inputs changed during evaluator-only repair")
            if repair_scope_digest(self.project_root, gap["allowed_repair_paths"]) != gap.get("baseline_repair_scope_digest"):
                raise MetaLoopError("files outside the evaluator repair allowlist changed")
            checks = [gap["program_check"], *control["evaluator_guard_checks"]]
            results = self._run_checks(checks, state, control)
            passed = len(results) == len(checks) and all(item["status"] == "PASS" for item in results)
            report = self._evaluation_report(objective["id"], results, len(checks), passed)
            if passed:
                state["active_work_item"] = None
                state["evaluator_digest"] = self._evaluator_digest()
                progress["status"] = "REVERIFY"
                progress["attempts"] = 0
                progress["replans"] = 0
                progress["stagnant_attempts"] = 0
                progress["best_score"] = -1
                progress["last_result"] = {"status": "EVALUATOR_REPAIRED", "results": results}
                progress["active_gap"] = None
                self._event(state, "EVALUATOR_REPAIR_ACCEPTED", {"objective_id": objective["id"], "evaluator_digest": state["evaluator_digest"]})
            else:
                progress["status"] = "EVALUATOR_REPAIR_REQUIRED"
                progress["last_result"] = report
                gap["repair_failures"] = int(gap.get("repair_failures", 0)) + 1
                self._event(state, "EVALUATOR_REPAIR_REJECTED", {"objective_id": objective["id"], "failed_check": self._failed_check_id(report)})
            self.store.save(state)
            return self._compact_evaluation(report)

    def _new_state(self, control: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "v6",
            "goal_id": control["goal_id"],
            "control_digest": sha256_file(self.control_path),
            "kernel_digest": self._kernel_digest(),
            "evaluator_digest": self._evaluator_digest(),
            "created_at_unix": int(time.time()),
            "iteration": 0,
            "active_work_item": None,
            "last_event_hash": None,
            "events": [],
            "cache": {},
            "objectives": {objective["id"]: self._new_progress() for objective in control["objectives"]},
        }

    @staticmethod
    def _new_progress() -> dict[str, Any]:
        return {
            "status": "PENDING",
            "attempts": 0,
            "replans": 0,
            "review_rounds": 0,
            "added_checks": [],
            "check_anchors": {},
            "best_score": -1,
            "stagnant_attempts": 0,
            "failure_fingerprint": None,
            "active_gap": None,
            "last_result": None,
            "completion_reason": None,
        }

    def _control(self) -> dict[str, Any]:
        control = load_json(self.control_path)
        validate_control_block(control)
        return control

    def _state(self, *, allow_evaluator_change: bool = False) -> dict[str, Any]:
        if not self.store.exists():
            raise MetaLoopError("v6 loop is not bootstrapped")
        state = self.store.load()
        if state.get("schema_version") != "v6":
            raise MetaLoopError("state is not v6")
        if state.get("control_digest") != sha256_file(self.control_path):
            raise MetaLoopError("control block changed after bootstrap")
        if state.get("kernel_digest") != self._kernel_digest():
            raise MetaLoopError("controller kernel changed after bootstrap")
        if not allow_evaluator_change and state.get("evaluator_digest") != self._evaluator_digest():
            raise MetaLoopError("evaluator changed outside controlled repair")
        errors = self.store.verify_event_chain(state)
        if errors:
            raise MetaLoopError("state/event integrity failure: " + "; ".join(errors))
        seal_errors = self._state_seal_errors(state)
        if seal_errors:
            raise MetaLoopError("state payload integrity failure: " + "; ".join(seal_errors))
        anchor_errors = self._review_check_anchor_errors(state, self._control())
        if anchor_errors:
            raise MetaLoopError("review check integrity failure: " + "; ".join(anchor_errors))
        return state

    def _kernel_digest(self) -> str:
        paths = sorted(Path(__file__).resolve().parent.glob("*.py"))
        paths.append(self.project_root / "scripts" / "meta_m1_real_gate_v6.py")
        return files_digest(paths, label_root=self.project_root)

    def _evaluator_digest(self) -> str:
        return files_digest(
            [
                self.project_root / "scripts" / "meta_m1_evidence_gate.py",
                self.project_root / "scripts" / "meta_m1_product_gate_contract.py",
            ],
            label_root=self.project_root,
        )

    def _runner(self, control: dict[str, Any]) -> ProgramRunner:
        return ProgramRunner(self.project_root, self.workspace_root, self.state_root / "logs", int(control["controller_policy"]["failure_excerpt_bytes"]))

    @staticmethod
    def _review_check_targets(check: dict[str, Any]) -> list[str]:
        return sorted(value.split("::", 1)[0] for value in check["command"][3:] if value.startswith("tests/"))

    def _review_check_anchor(self, check: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
        targets = self._review_check_targets(check)
        if not targets:
            raise MetaLoopError(f"review check {check.get('id')} has no test target to anchor")
        return {"targets": targets, "digest": self._runner(control).input_digest(targets)}

    def _review_check_anchor_errors(self, state: dict[str, Any], control: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        runner = self._runner(control)
        for objective_id, progress in state.get("objectives", {}).items():
            checks = {check.get("id"): check for check in progress.get("added_checks", []) if isinstance(check, dict)}
            anchors = progress.get("check_anchors")
            if not isinstance(anchors, dict) or set(anchors) != set(checks):
                errors.append(f"{objective_id} reviewer check anchors do not match added checks")
                continue
            for check_id, check in checks.items():
                anchor = anchors.get(check_id)
                targets = self._review_check_targets(check)
                if not isinstance(anchor, dict) or anchor.get("targets") != targets:
                    errors.append(f"{objective_id}/{check_id} reviewer target anchor mismatch")
                    continue
                if anchor.get("digest") != runner.input_digest(targets):
                    errors.append(f"{objective_id}/{check_id} reviewer test content changed")
        return errors

    def _run_checks(self, checks: list[dict[str, Any]], state: dict[str, Any], control: dict[str, Any]) -> list[dict[str, Any]]:
        runner = self._runner(control)
        results: list[dict[str, Any]] = []
        for check in checks:
            result = runner.run(check, state["cache"])
            results.append(result)
            if result["status"] != "PASS":
                break
        return results

    def _objective_check_plan(self, control: dict[str, Any], objective: dict[str, Any], progress: dict[str, Any]) -> list[dict[str, Any]]:
        base = [*control["common_checks"], *objective["checks"], *progress["added_checks"]]
        low = sorted((check for check in base if check["level"] <= 2), key=lambda item: item["level"])
        high = sorted((check for check in base if check["level"] >= 3), key=lambda item: item["level"])
        return [*low, *control["closure_checks"], *high]

    def _all_checks(self, control: dict[str, Any], objective: dict[str, Any], progress: dict[str, Any]) -> list[dict[str, Any]]:
        return [*control["common_checks"], *control["closure_checks"], *objective["checks"], *progress["added_checks"]]

    def _program_inputs_current(self, control: dict[str, Any], objective: dict[str, Any], progress: dict[str, Any]) -> bool:
        report = progress.get("last_result")
        if not isinstance(report, dict) or report.get("status") != "PASS":
            return False
        results = report.get("results")
        if not isinstance(results, list):
            return False
        checks = self._objective_check_plan(control, objective, progress)
        by_id = {item.get("check_id"): item for item in results if isinstance(item, dict)}
        runner = self._runner(control)
        return len(results) == len(checks) and all(
            check["id"] in by_id and by_id[check["id"]].get("input_digest") == runner.check_input_digest(check)
            for check in checks
        )

    def _issue(self, state: dict[str, Any], work: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
        state["iteration"] += 1
        state["active_work_item"] = work
        self._enforce_context_budget(work, policy)
        self._event(state, "WORK_ISSUED", {"type": work["type"], "objective_id": work.get("objective_id"), "work_item_id": work["work_item_id"]})
        self.store.save(state)
        return work

    @staticmethod
    def _objective(control: dict[str, Any], objective_id: str) -> dict[str, Any]:
        for objective in control["objectives"]:
            if objective["id"] == objective_id:
                return objective
        raise MetaLoopError(f"unknown objective: {objective_id}")

    @staticmethod
    def _next_ready_objective(state: dict[str, Any], control: dict[str, Any]) -> dict[str, Any] | None:
        for objective in control["objectives"]:
            progress = state["objectives"][objective["id"]]
            if progress["status"] in {"COMPLETE", "BLOCKED"}:
                continue
            if all(state["objectives"][dep]["status"] == "COMPLETE" for dep in objective["depends_on"]):
                return objective
        return None

    @staticmethod
    def _review_item(objective: dict[str, Any], progress: dict[str, Any], purpose: str, policy: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": f"REVIEW_{purpose}",
            "work_item_id": uuid.uuid4().hex,
            "objective_id": objective["id"],
            "title": objective["title"],
            "contract_clauses": objective["clauses"],
            "review_round": progress["review_rounds"] + 1,
            "review_rounds_remaining_after_this": max(0, policy["max_review_rounds_per_objective"] - progress["review_rounds"] - 1),
            "last_program_result": MetaLoopController._compact_result(progress["last_result"]),
            "instruction": (
                "Fresh reviewer: return NO_GAP or one demonstrated GAP classified as PRODUCT_GAP or EVALUATOR_GAP. Do not broaden scope."
                if purpose == "ACCEPTANCE"
                else "Fresh reviewer: diagnose the current failure fingerprint and recommend a materially different approach."
            ),
        }

    @staticmethod
    def _validate_review_gap(report: dict[str, Any], objective: dict[str, Any]) -> dict[str, Any]:
        if report.get("contract_clause") not in objective["clauses"]:
            raise MetaLoopError("review gap must cite an exact frozen clause")
        if not isinstance(report.get("finding"), str) or not report["finding"].strip():
            raise MetaLoopError("review gap requires a concrete finding")
        check = report.get("program_check")
        if not isinstance(check, dict):
            raise MetaLoopError("review gap requires program_check")
        errors = _check_errors(check, "review.program_check")
        if errors:
            raise MetaLoopError("invalid review check: " + "; ".join(errors))
        if check["level"] > 2:
            raise MetaLoopError("review-created checks must be level 0-2")
        targets = MetaLoopController._review_check_targets(check)
        if check["command"][:3] != ["python3", "-m", "pytest"] or not targets:
            raise MetaLoopError("review-created checks must be focused pytest commands under tests/")
        if any(not any(target == raw or target.startswith(raw.rstrip("/") + "/") for raw in check["inputs"]) for target in targets):
            raise MetaLoopError("review check inputs must cover every pytest target for cache correctness")
        if any("../loop_evidence" in value for value in check["inputs"]):
            raise MetaLoopError("review repository checks must be hermetic; current-run evidence checks belong in the evaluator")
        return check

    @staticmethod
    def _evaluation_report(objective_id: str, results: list[dict[str, Any]], total: int, passed: bool) -> dict[str, Any]:
        highest = max((item["level"] for item in results if item["status"] == "PASS"), default=-1)
        failed_count = sum(item["status"] != "PASS" for item in results)
        return {
            "status": "PASS" if passed else "FAIL",
            "objective_id": objective_id,
            "score": (highest + 1) * 100 - failed_count,
            "highest_level_passed": highest,
            "checks_run": len(results),
            "checks_total": total,
            "results": results,
        }

    @staticmethod
    def _last_failure_cached(progress: dict[str, Any]) -> bool:
        report = progress.get("last_result")
        if not isinstance(report, dict):
            return False
        return any(item.get("status") == "FAIL" and item.get("cached") is True for item in report.get("results", []) if isinstance(item, dict))

    def _event(self, state: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
        self.store.append_event(
            state,
            {
                "schema_version": "v6",
                "event": kind,
                "iteration": state["iteration"],
                "at_unix": int(time.time()),
                "state_payload_hash": self._state_payload_digest(state),
                **payload,
            },
        )

    @staticmethod
    def _state_payload_digest(state: dict[str, Any]) -> str:
        payload = {key: value for key, value in state.items() if key not in {"events", "last_event_hash"}}
        return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).hexdigest()

    @classmethod
    def _state_seal_errors(cls, state: dict[str, Any]) -> list[str]:
        events = state.get("events")
        if not isinstance(events, list) or not events:
            return ["v6 state has no sealing event"]
        claimed = events[-1].get("state_payload_hash") if isinstance(events[-1], dict) else None
        actual = cls._state_payload_digest(state)
        return [] if claimed == actual else ["latest event does not seal the current controller state"]

    @staticmethod
    def _failed_check_id(report: dict[str, Any]) -> str | None:
        for result in report.get("results", []):
            if result.get("status") == "FAIL":
                return str(result.get("check_id"))
        return None

    @staticmethod
    def _compact_result(result: Any) -> Any:
        if not isinstance(result, dict):
            return result
        if result.get("status") in {"REPLAN", "STALE", "EVALUATOR_REPAIRED"}:
            return result
        if result.get("status") == "REVIEW_GAP":
            reproduction = result.get("reproduction", {})
            return {"status": "REVIEW_GAP", "gap_kind": result.get("gap_kind"), "finding": result.get("finding"), "failed_check": reproduction.get("check_id"), "excerpt": reproduction.get("excerpt")}
        return MetaLoopController._compact_evaluation(result)

    @staticmethod
    def _compact_evaluation(report: dict[str, Any]) -> dict[str, Any]:
        failed = next((item for item in report.get("results", []) if item.get("status") == "FAIL"), None)
        return {"status": report.get("status"), "objective_id": report.get("objective_id"), "score": report.get("score"), "highest_level_passed": report.get("highest_level_passed"), "checks_run": report.get("checks_run"), "checks_total": report.get("checks_total"), "failed_check": failed}

    @staticmethod
    def _compact_summary(state: dict[str, Any], control: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"id": objective["id"], "status": state["objectives"][objective["id"]]["status"], "attempts": state["objectives"][objective["id"]]["attempts"], "replans": state["objectives"][objective["id"]]["replans"], "review_rounds": state["objectives"][objective["id"]]["review_rounds"]} for objective in control["objectives"]]

    def _status_view(self, state: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
        summary = self._compact_summary(state, control)
        completed = sum(item["status"] == "COMPLETE" for item in summary)
        migration = state.get("migration", {})
        if migration.get("status") == "BLOCKED" or any(item["status"] == "BLOCKED" for item in summary):
            overall = "BLOCKED"
        elif completed == len(summary) and migration.get("status") == "PASS":
            overall = "COMPLETE"
        else:
            overall = "ACTIVE"
        return {"goal_id": control["goal_id"], "status": overall, "progress": {"completed": completed, "total": len(summary)}, "migration": migration, "active_work_item": state.get("active_work_item"), "objectives": summary}

    @staticmethod
    def _enforce_context_budget(work: dict[str, Any], policy: dict[str, Any]) -> None:
        size = len(json.dumps(work, ensure_ascii=True).encode())
        if size > policy["max_context_bytes"]:
            raise MetaLoopError(f"work item context is {size} bytes, over budget")
