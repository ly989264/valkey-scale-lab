from __future__ import annotations

from pathlib import Path

from test_goal_core import _controller


def test_changing_failure_identity_cannot_reset_objective_retry_budget(tmp_path: Path, monkeypatch) -> None:
    controller, _ = _controller(tmp_path, second=False)
    failures = iter(("failure-a", "failure-b", "failure-a"))

    def fail_with_changing_identity(checks, state, goal):
        check_id = next(failures)
        return [
            {
                "check_id": check_id,
                "level": 1,
                "status": "FAIL",
                "cached": False,
                "returncode": 1,
                "timed_out": False,
                "input_digest": check_id,
                "excerpt": check_id,
            }
        ]

    monkeypatch.setattr(controller, "_run_checks", fail_with_changing_identity)
    for _ in range(3):
        assert controller.next_work_item()["type"] == "WORK"
        assert controller.evaluate_active()["status"] == "FAIL"

    assert controller.next_work_item()["type"] == "REVIEW_REPLAN"
