from __future__ import annotations

import json
import uuid
from typing import Any

from .models import CheckDefinition, GoalDefinition, ObjectiveDefinition


class SchedulerError(RuntimeError):
    pass


def new_progress() -> dict[str, Any]:
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


def ready_objective(goal: GoalDefinition, state: dict[str, Any]) -> ObjectiveDefinition | None:
    for objective in goal.objectives:
        progress = state["objectives"][objective.id]
        if progress["status"] in {"COMPLETE", "BLOCKED"}:
            continue
        if all(state["objectives"][dependency]["status"] == "COMPLETE" for dependency in objective.depends_on):
            return objective
    return None


def check_plan(goal: GoalDefinition, objective: ObjectiveDefinition, added: tuple[CheckDefinition, ...]) -> tuple[CheckDefinition, ...]:
    base = (*goal.common_checks, *objective.checks, *added)
    low = sorted((check for check in base if check.level <= 2), key=lambda check: check.level)
    high = sorted((check for check in base if check.level >= 3), key=lambda check: check.level)
    return (*low, *goal.closure_checks, *high)


def issue(state: dict[str, Any], work: dict[str, Any], max_context_bytes: int) -> dict[str, Any]:
    size = len(json.dumps(work, ensure_ascii=True).encode())
    if size > max_context_bytes:
        raise SchedulerError(f"work item context is {size} bytes, over budget")
    state["iteration"] += 1
    state["active_work_item"] = work
    return work


def work_item(kind: str, **values: Any) -> dict[str, Any]:
    return {"type": kind, "work_item_id": uuid.uuid4().hex, **values}
