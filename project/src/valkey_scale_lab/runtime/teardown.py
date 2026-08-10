"""End-of-run cleanup, above any particular runtime.

The Gate's last step and `cli gate cleanup` both land here. What it does is ask
the backend that ran the fleet to release it, and turn what that backend reports
into the `cleanup_report` artifact - the evidence M3's "no managed process or
host resource behind" criterion is measured on.

It lived in `docker_runtime.py` until roadmap item 0.5, where it dispatched on
`state["runtime"]["type"] == "docker_process"` and otherwise ran `docker ps
--filter label=...` directly. A native run's state says neither of those things,
so it took the container path, found nothing owned by that run in Docker - there
being nothing in Docker - and wrote `status: PASS` with every remote process
still running. See `project/docs/seam_completion_slice_map.md` §2.2.

Not in `runtime/lifecycle.py`, though that is where the rest of the sequencing
went at `39e31b1a`: `lifecycle` imports `docker_runtime` at module scope and
`docker_runtime`'s failure handler calls cleanup, so the pair would be an import
cycle. This module imports only `backends` and `node_backend`, which keeps the
dependency one way: `backends` <- `teardown` <- `docker_runtime` <- `lifecycle`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from valkey_scale_lab import __version__
from valkey_scale_lab.runtime.backends import (
    BackendNotImplementedError,
    resolve_backend,
)
from valkey_scale_lab.runtime.node_backend import NodeBackend, RunTeardown


class TeardownError(RuntimeError):
    """Cleanup was asked for something it cannot safely do."""


# A state written before backends were named carries no `backend_id`, and
# `cli gate cleanup` accepts a hand-written one. Both meant the container path
# before this module existed, so both still do. Every state a real run writes
# names its backend - `_runtime_state`, `_process_runtime_state` and
# `execute_scenario` all set it - so no run on a second backend can reach this.
DEFAULT_BACKEND_ID = "docker_container"

# The second-valued keys the artifact has always carried, whether or not the
# backend that released the run had anything to measure for them.
_TIMING_KEYS = (
    "cleanup_terminate_processes_seconds",
    "cleanup_verify_process_exit_seconds",
    "cleanup_verify_nodehost_empty_seconds",
    "cleanup_remove_containers_seconds",
    "cleanup_remove_networks_seconds",
    "cleanup_residual_scan_seconds",
)


def backend_for_state(state: Mapping[str, Any]) -> NodeBackend:
    """The backend that ran this state's fleet, or a stated refusal.

    Fails closed. A backend that is registered but declares no implementation is
    the one case where guessing would silently report a clean teardown for a
    fleet nothing touched.
    """
    backend_id = str(state.get("backend_id") or DEFAULT_BACKEND_ID)
    try:
        spec = resolve_backend(backend_id)
    except BackendNotImplementedError as exc:
        raise TeardownError(str(exc)) from exc
    if spec.node_backend is None:
        raise TeardownError(
            f"backend {backend_id!r} is registered without a node backend, so the "
            "resources of a run it started cannot be released"
        )
    return spec.node_backend()


def cleanup_scenario(
    *,
    state_path: str | Path,
    artifacts_dir: str | Path,
    out_path: str | Path,
) -> dict[str, Any]:
    """Release the run described by `state_path` and write its cleanup report."""
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    runtime = state.get("runtime")
    if not isinstance(runtime, dict) or not runtime.get("run_id"):
        raise TeardownError("cleanup requires runtime ownership with an explicit run_id in state")
    capability_id = str(state.get("capability_id", "cluster_lifecycle"))
    run_id = str(runtime["run_id"])
    artifacts = Path(artifacts_dir)

    # One place resolves `capability_id`, and the backend is handed a state that
    # names it. Otherwise the report's default and the backend's label filter
    # default would be two different strings for the same missing field.
    teardown = backend_for_state(state).release_run({**state, "capability_id": capability_id})

    actions = list(teardown.actions)
    errors = list(teardown.errors)
    resources_remaining = list(teardown.resources_remaining)
    if capability_id == "orchestration":
        actions.append(
            {
                "type": "orchestrator",
                "id": "all-hosts",
                "action": "stop_collect",
                "status": "PASS" if not resources_remaining else "FAIL",
                "idempotent": True,
            }
        )
        _append_orchestration_orchestrator_cleanup(artifacts, resources_remaining)

    timing = dict(teardown.timing)
    for key in _TIMING_KEYS:
        timing.setdefault(key, 0.0)

    report = {
        "schema_version": "v1",
        "artifact_type": "cleanup_report",
        "capability_id": capability_id,
        "run_id": run_id,
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "valkey-scale-lab", "version": __version__},
        # One rule for every backend. It is the stricter of the two this
        # replaces - the process path's - and a no-op on the container path,
        # where every `FAIL` a row can carry already forces `FAIL` through
        # `cleanup_errors` or through `resources_remaining`. Slice map §2.6
        # enumerates that path's action producers; a hermetic test pins it.
        "status": (
            "PASS"
            if not resources_remaining
            and not errors
            and all(action.get("status") != "FAIL" for action in actions)
            else "FAIL"
        ),
        "resources_remaining": resources_remaining,
        "cleanup_errors": errors,
        "cleanup_actions": actions,
        "cleanup_timing": timing,
        "nodehost_density": state.get("nodehost_density", state.get("runtime", {})),
        "artifacts_dir": str(artifacts_dir),
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    out.write_text(serialized, encoding="utf-8")
    scenario = state.get("scenario")
    if scenario:
        (out.parent / f"cleanup_report_{scenario}.json").write_text(serialized, encoding="utf-8")
    return report


def _append_orchestration_orchestrator_cleanup(artifacts_dir: Path, resources_remaining: list[dict[str, Any]]) -> None:
    """Moved verbatim from `docker_runtime.py`, `docker_label_cleanup` and all.

    That `mode` string is a legacy `orchestration`-capability artifact field
    that predates this seam, and `orchestration` runs on `docker_container`
    only. Rewriting it here would be an artifact change riding inside a move, so
    it stays as it is and is named instead.
    """
    report_path = artifacts_dir / "orchestration_report.json"
    if not report_path.exists():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.setdefault("operations", []).append(
        {
            "operation": "stop",
            "status": "PASS" if not resources_remaining else "FAIL",
            "host_id": "all",
            "started_at": "2026-06-28T00:00:00Z",
            "finished_at": "2026-06-28T00:00:00Z",
            "details": {
                "mode": "docker_label_cleanup",
                "idempotent": True,
                "resources_remaining": resources_remaining,
            },
        }
    )
    report["status"] = "PASS" if all(op.get("status") == "PASS" for op in report.get("operations", [])) else "FAIL"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
