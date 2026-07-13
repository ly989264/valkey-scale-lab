from __future__ import annotations

import threading

import pytest

from test_orchestrator import RecordingAdapters, _plan, _request
from valkey_scale_lab.gates import (
    FaultTargetKind,
    GateService,
    OwnedFaultScope,
    OwnershipCollisionError,
)


def test_gate_service_rejects_nested_active_artifact_roots(tmp_path) -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingOrchestrator:
        def execute(self, plan, request, adapters):
            entered.set()
            assert release.wait(2)
            return "first"

    class ImmediateOrchestrator:
        def execute(self, plan, request, adapters):
            return "second"

    active_root = tmp_path / "evidence"
    first_request = _request(tmp_path, artifact_root=active_root)
    nested_request = _request(
        tmp_path,
        run_id="run-002",
        ownership_id="owner-002",
        provenance_id="capture-002",
        artifact_root=active_root / "nested-run",
        fault_scope=OwnedFaultScope(
            run_id="run-002",
            ownership_id="owner-002",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=("valkey-node-002",),
        ),
    )
    adapters = RecordingAdapters()
    first = GateService(orchestrator=BlockingOrchestrator())
    second = GateService(orchestrator=ImmediateOrchestrator())
    thread = threading.Thread(
        target=lambda: first.execute(_plan(), first_request, adapters.bundle)
    )
    thread.start()
    assert entered.wait(2)

    try:
        with pytest.raises(OwnershipCollisionError, match="artifact_root"):
            second.execute(_plan(), nested_request, adapters.bundle)
    finally:
        release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
