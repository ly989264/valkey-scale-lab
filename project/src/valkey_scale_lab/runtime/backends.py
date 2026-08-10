"""Which runtime backends exist, and what each one implements.

Backend selection used to be a chain of `if backend.backend_id == ...` inside
`docker_runtime.py`, which is why a second backend could not be written without
living in the Docker module or duplicating it - the stated reason M3 could not
exist. The chain was pure data: a set of profiles and a set of scenarios per
backend, plus a rejection for the one declared backend with no implementation.

That data lives here now, and `native_multi_ecs` is absent rather than rejected.
A backend that is not registered is not implemented, which is the same fact
stated once, in a module that knows nothing about Docker. Registering a second
backend is then an entry here plus a `NodeBackend`, and touches neither the
Docker module nor the lifecycle.

This module deliberately holds no runtime code. It says what is implemented, not
how; `execute_scenario` still asks the implementation to run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


class BackendNotImplementedError(RuntimeError):
    """A declared execution backend has no registered implementation."""


@dataclass(frozen=True)
class BackendSpec:
    """What one backend implements, and how to obtain it.

    `profiles` and `scenarios` are the guards the dispatch chain used to state
    inline. `profile_prefixes` carries the one guard that was not a plain
    membership test - `docker_process` accepts every `exact-*` profile - so that
    it stays data rather than becoming a special case in the caller.
    """

    backend_id: str
    scenarios: frozenset[str]
    profiles: frozenset[str] = frozenset()
    profile_prefixes: tuple[str, ...] = ()
    # Two ways to obtain the same backend, because two callers need it for
    # different reasons. `node_backend` takes nothing and is what teardown uses:
    # `cli gate cleanup` is given a state file and no configuration, and a state
    # written by a run carries whatever the backend needs to release it.
    # `node_backend_for_run` is given the run's `runtime` configuration, which a
    # backend whose hosts are described by a manifest cannot do without - it has
    # to know which fleet and which pinned build. A backend that needs neither
    # leaves it unset and both callers get the same object.
    node_backend: Callable[[], Any] | None = None
    node_backend_for_run: Callable[[Mapping[str, Any]], Any] | None = None
    # A local Docker daemon is the Docker backends' precondition, not the Gate's.
    # Declared here so the Gate checks it when it applies rather than always.
    requires_local_docker_daemon: bool = False
    # Whether a node's client port is bound on the machine the run drives from.
    # It is under Docker, which publishes every hosted port on loopback, and the
    # run therefore preflights those ports locally. It is not on a fleet the run
    # does not own: the ports are on the hosts, the controller's loopback says
    # nothing about them, and the check that matters there is the placement's -
    # that a host's declared client port range covers what the run asked for.
    publishes_node_ports_on_controller: bool = False

    def implements_profile(self, profile_id: str) -> bool:
        if profile_id in self.profiles:
            return True
        return any(profile_id.startswith(prefix) for prefix in self.profile_prefixes)

    def implements_scenario(self, scenario_id: str) -> bool:
        return scenario_id in self.scenarios

    def build_for_run(self, runtime_config: Mapping[str, Any]) -> Any:
        """The backend a run should use, configured from `runtime_config`."""
        if self.node_backend_for_run is not None:
            return self.node_backend_for_run(runtime_config)
        if self.node_backend is not None:
            return self.node_backend()
        raise BackendNotImplementedError(
            f"backend {self.backend_id!r} is registered without a node backend, so it cannot run"
        )

_REGISTRY: dict[str, BackendSpec] = {}


def register_backend(spec: BackendSpec) -> BackendSpec:
    """Register one backend. Re-registering the same id replaces it, which is
    what a test double needs and what a second implementation of an existing id
    would mean."""

    _REGISTRY[spec.backend_id] = spec
    return spec


def registered_backend_ids() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def resolve_backend(backend_id: str) -> BackendSpec:
    """The spec for `backend_id`, or a stated absence.

    The error names what is registered, because "not implemented" and "spelled
    wrong" look identical to a caller otherwise.
    """

    spec = _REGISTRY.get(backend_id)
    if spec is None:
        raise BackendNotImplementedError(
            f"no runtime backend is registered for {backend_id!r}; "
            f"registered: {', '.join(registered_backend_ids()) or 'none'}"
        )
    return spec


def require_implemented(backend_id: str, *, profile_id: str, scenario_id: str) -> BackendSpec:
    """Resolve a backend and check it implements this profile and scenario.

    The three failures stay distinct - unregistered backend, unimplemented
    profile, unimplemented scenario - because they were distinct in the chain
    this replaces and each says something different about what to do next.
    """

    spec = resolve_backend(backend_id)
    if not spec.implements_profile(profile_id):
        raise BackendNotImplementedError(
            f"{backend_id} runtime has no implementation for profile {profile_id!r}"
        )
    if not spec.implements_scenario(scenario_id):
        raise BackendNotImplementedError(
            f"{backend_id} does not implement scenario {scenario_id!r}"
        )
    return spec
