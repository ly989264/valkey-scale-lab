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


def test_services_reject_cross_run_fault_resource_collision(tmp_path) -> None:
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

    shared_resource = "shared-valkey-container"
    first_request = _request(
        tmp_path / "first",
        fault_scope=OwnedFaultScope(
            run_id="run-001",
            ownership_id="owner-001",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=(shared_resource,),
        ),
    )
    second_request = _request(
        tmp_path / "second",
        run_id="run-002",
        ownership_id="owner-002",
        provenance_id="capture-002",
        fault_scope=OwnedFaultScope(
            run_id="run-002",
            ownership_id="owner-002",
            kind=FaultTargetKind.CONTAINER,
            resource_ids=(shared_resource,),
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
        with pytest.raises(OwnershipCollisionError):
            second.execute(_plan(), second_request, adapters.bundle)
    finally:
        release.set()
        thread.join(timeout=2)
