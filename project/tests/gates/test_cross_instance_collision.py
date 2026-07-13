from __future__ import annotations

import threading

import pytest

from test_orchestrator import RecordingAdapters, _plan, _request
from valkey_scale_lab.gates import GateService, OwnershipCollisionError


def test_gate_service_rejects_collisions_across_instances(tmp_path) -> None:
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

    request = _request(tmp_path)
    adapters = RecordingAdapters()
    first = GateService(orchestrator=BlockingOrchestrator())
    second = GateService(orchestrator=ImmediateOrchestrator())
    thread = threading.Thread(
        target=lambda: first.execute(_plan(), request, adapters.bundle)
    )
    thread.start()
    assert entered.wait(2)

    try:
        with pytest.raises(OwnershipCollisionError):
            second.execute(_plan(), request, adapters.bundle)
    finally:
        release.set()
        thread.join(timeout=2)
