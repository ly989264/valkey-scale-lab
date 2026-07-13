from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Set, Tuple

from valkey_scale_lab.scenarios import GatePlan

from .contracts import AdapterBundle, FaultTargetKind, GateRequest, GateResult
from .orchestrator import GateOrchestrator


class OwnershipCollisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class _OwnershipClaim:
    run_id: str
    ownership_id: str
    artifact_root: Path
    fault_resources: Tuple[Tuple[FaultTargetKind, str], ...]


class _OwnershipRegistry:
    def __init__(self) -> None:
        self._active_ownership_ids: Set[str] = set()
        self._active_run_ids: Set[str] = set()
        self._active_artifact_roots: Set[Path] = set()
        self._active_fault_resources: Set[Tuple[FaultTargetKind, str]] = set()
        self._active_fault_resource_ids: Set[str] = set()
        self._lock = Lock()

    def claim(self, request: GateRequest) -> _OwnershipClaim:
        claim = _OwnershipClaim(
            run_id=request.run_id,
            ownership_id=request.ownership_id,
            artifact_root=request.artifact_root.resolve(),
            fault_resources=tuple(
                (request.fault_scope.kind, resource_id)
                for resource_id in request.fault_scope.resource_ids
            ),
        )
        with self._lock:
            if claim.ownership_id in self._active_ownership_ids:
                raise OwnershipCollisionError(
                    f"ownership_id {claim.ownership_id!r} is already active"
                )
            if claim.run_id in self._active_run_ids:
                raise OwnershipCollisionError(
                    f"run_id {claim.run_id!r} is already active"
                )
            for active_root in self._active_artifact_roots:
                if (
                    claim.artifact_root == active_root
                    or claim.artifact_root.is_relative_to(active_root)
                    or active_root.is_relative_to(claim.artifact_root)
                ):
                    raise OwnershipCollisionError(
                        "artifact_root directory tree is already active: "
                        f"requested={claim.artifact_root}, active={active_root}"
                    )
            for resource in claim.fault_resources:
                kind, resource_id = resource
                if (
                    resource in self._active_fault_resources
                    or resource_id in self._active_fault_resource_ids
                ):
                    raise OwnershipCollisionError(
                        f"fault resource {kind.value}:{resource_id!r} is already active"
                    )
            self._active_ownership_ids.add(claim.ownership_id)
            self._active_run_ids.add(claim.run_id)
            self._active_artifact_roots.add(claim.artifact_root)
            self._active_fault_resources.update(claim.fault_resources)
            self._active_fault_resource_ids.update(
                resource_id for _, resource_id in claim.fault_resources
            )
        return claim

    def release(self, claim: _OwnershipClaim) -> None:
        with self._lock:
            self._active_ownership_ids.discard(claim.ownership_id)
            self._active_run_ids.discard(claim.run_id)
            self._active_artifact_roots.discard(claim.artifact_root)
            self._active_fault_resources.difference_update(claim.fault_resources)
            self._active_fault_resource_ids.difference_update(
                resource_id for _, resource_id in claim.fault_resources
            )


_OWNERSHIP_REGISTRY = _OwnershipRegistry()


@dataclass
class GateService:
    orchestrator: GateOrchestrator = field(default_factory=GateOrchestrator)

    def execute(
        self,
        plan: GatePlan,
        request: GateRequest,
        adapters: AdapterBundle,
    ) -> GateResult:
        claim = _OWNERSHIP_REGISTRY.claim(request)
        try:
            return self.orchestrator.execute(plan, request, adapters)
        finally:
            _OWNERSHIP_REGISTRY.release(claim)
