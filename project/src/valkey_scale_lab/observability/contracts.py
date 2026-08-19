from __future__ import annotations

import errno
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from ..valkey.resp import RespCommandError, RespProtocolError


class CheckStatus(str, Enum):
    OK = "OK"
    FAIL = "FAIL"
    ERROR = "ERROR"


class CollectionError(RuntimeError):
    """The checker itself could not obtain or persist required evidence."""


class SemanticFailure(RuntimeError):
    """A successful observation did not match the current check expectation."""


class ConvergenceFailure(SemanticFailure):
    """A node is still converging and the same check may hold once it settles.

    Reserved for states a healthy cluster leaves on its own - a replica whose
    link is still connecting, or one an observer has not yet learned is online.
    Every other semantic failure is permanent: a role, slot, identity or
    coverage mismatch does not resolve by observing it again.

    `pending` names what has not settled yet, when the raising check knows. A
    caller waiting for convergence can then tell a queue that is moving from one
    that is stuck, which the message alone cannot express: measured at 200 nodes,
    a healthy cluster clears its laggards one at a time and holds a single node
    unhealthy for up to 83 seconds while doing it.
    """

    def __init__(self, *args: Any, pending: Iterable[str] = ()) -> None:
        super().__init__(*args)
        self.pending: frozenset[str] = frozenset(pending)


_LOCAL_RESOURCE_ERRNOS = frozenset(
    {
        errno.EADDRNOTAVAIL,  # measured at 200 nodes: 16,384 ephemeral ports gone
        errno.EMFILE,
        errno.ENFILE,
        errno.ENOBUFS,
        errno.ENOMEM,
    }
)


def is_collection_failure(exc: BaseException) -> bool:
    """Whether an observation failure was the collector's own, per §12.1.

    §12.1 puts Valkey refusing a connection, timing out, returning a wrong value
    or a wrong role on the *semantic* side: each of those is a successful
    observation of a cluster that is not healthy. The collector's own side is
    local - a code error, a parser fault, evidence that cannot be written, and
    running out of local sockets or file descriptors, which is the case that
    actually happened here (`[Errno 49] Can't assign requested address`, once the
    host's 16,384 ephemeral ports were gone).

    Answers False for anything it cannot place. Calling a confirmed cluster
    failure a tool error is the dangerous direction: it turns a `FAIL` the design
    says is final into an `ERROR`, and §12.2 keeps `FAIL` ahead of `ERROR`
    precisely so that cannot happen by accident.
    """

    if isinstance(exc, SemanticFailure):
        return False
    if isinstance(exc, CollectionError):
        return True
    if isinstance(exc, OSError) and exc.errno in _LOCAL_RESOURCE_ERRNOS:
        return True
    return False


def is_transient_transport_error(exc: BaseException) -> bool:
    """Whether a failure is worth *retrying*, which is a different axis to §12.1.

    This answers "may the caller try again", and nothing else. It is for retry
    and redundancy layers only. It does **not** decide a verdict: a run's
    `failure_kind` still comes from `is_collection_failure`, and §12.2 still
    puts `FAIL` ahead of `ERROR`. Both stay exactly as they were, deliberately -
    a transport timeout remains a *semantic* observation of a cluster that did
    not answer, because calling a confirmed cluster failure a tool error is the
    direction that loses a finding. The two predicates disagree on a timeout on
    purpose, and that is not an inconsistency: one asks what happened, the other
    asks whether asking again is reasonable.

    It exists because deciding which failures to retry *is* classification, and
    this codebase has already run the alternative experiment: an ad-hoc
    `except (DockerRuntimeError, TypeError, ValueError)` was a local and slightly
    wrong transient-detector that shipped, omitting `OSError` - which
    `TimeoutError` subclasses - so a retry loop retried error *replies* and let
    transport failures through. One named predicate or N ad-hoc ones; this is the
    one.

    True for a transport failure - the socket timed out, was refused, was reset,
    or the byte stream did not parse. False for an error *reply*: a node
    answering `-ERR` was reached, so the observation succeeded and the answer
    will not change on a second ask.

    Every `RespProtocolError` counts, not only the truncation forms. Each member
    of that class means this socket's stream did not parse - truncated, desynced,
    or an unknown prefix - and none of them is an observation of cluster state;
    the connection is unusable either way and the only useful response is a fresh
    one. Every caller's retry is bounded, so a stream that is permanently
    unparseable costs a few attempts rather than a run. Naming only the two
    truncation sites was available and would also have been safe - an additive
    `RespProtocolError` subclass, since nothing in the product catches that class
    at all - and it was not taken because the wider set needs no new type and
    excludes nothing that belongs.

    Two exclusions are decisions rather than omissions, and both are narrow on
    purpose:

    - **`EHOSTUNREACH` / `ENETUNREACH`** are not here. A partition installed by
      this product's own actuator uses `DROP`, which produces a timeout, so
      in-product faults are covered; a real network answering "no route" is
      classified non-transient. That is the safe direction - it fails a gate
      rather than retrying into a partition - but it does mean one physical
      event can classify two ways depending on how the path was cut. Adding
      them is a decision to take on its own evidence.
    - **`subprocess.TimeoutExpired`** is not here, because it is a Docker CLI
      transport failure rather than a RESP one. Any caller narrowed from a broad
      `except` to this predicate loses that coverage, so check the caller's
      transport before narrowing it.

    On the pool-timeout confusion, verified in source rather than assumed: on
    Python 3.11+ `concurrent.futures.TimeoutError` *is* the builtin
    `TimeoutError`, so matching `TimeoutError` here would also match a thread
    pool's budget being blown - which is the confusion that killed a real
    1280-node run at 448s.

    **That exclusion is a property of the call sites, not of the type**, and on
    3.11+ it is not expressible as a type at all. Two producers exist and
    neither reaches a retry: `_bounded_parallel` is the only site that passes a
    timeout to `as_completed` and it converts what that raises into a
    `DockerRuntimeError` first, and `Future.result(timeout=...)` appears once,
    in a management teardown that is not retried. Both are pinned by an AST
    sweep over the whole package rather than by this docstring, because the
    guarantee is that no *third* producer appears.

    `socket.timeout` is named alongside `TimeoutError` because they are the same
    class only from Python 3.10. The workstation is 3.9 and the controller 3.12,
    so on the workstation that second name is doing real work and on the
    controller it is redundant.
    """

    # An allowlist, so anything unrecognised is not retried. `RespCommandError`,
    # `ValkeyErrorReply` and `SemanticFailure` are excluded by that default
    # rather than by a branch of their own: each is a plain `RuntimeError` here,
    # so an explicit early `return False` for them would be unreachable in
    # effect and would read as a guard that was doing work. Verified: no
    # exception class in this product mixes `SemanticFailure` with `OSError`.
    return isinstance(
        exc,
        (
            TimeoutError,
            socket.timeout,
            ConnectionRefusedError,
            ConnectionResetError,
            BrokenPipeError,
            EOFError,
            RespProtocolError,
        ),
    )


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    evidence: Any = None
    reason: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    attempts: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "reason": self.reason,
            "warnings": list(self.warnings),
            "attempts": self.attempts,
            "evidence": self.evidence,
        }


def run_check(name: str, operation: Callable[[], Any]) -> CheckResult:
    """Run one fixed check, retrying only technical collection failure once."""

    last_collection_error: str | None = None
    for attempt in (1, 2):
        try:
            evidence = operation()
            return CheckResult(name=name, status=CheckStatus.OK, evidence=evidence, attempts=attempt)
        except SemanticFailure as exc:
            return CheckResult(
                name=name,
                status=CheckStatus.FAIL,
                reason=str(exc),
                attempts=attempt,
            )
        except CollectionError as exc:
            last_collection_error = str(exc)
            if attempt == 2:
                return CheckResult(
                    name=name,
                    status=CheckStatus.ERROR,
                    reason=str(exc),
                    attempts=attempt,
                )
        except Exception as exc:  # noqa: BLE001
            last_collection_error = f"{type(exc).__name__}: {exc}"
            if attempt == 2:
                return CheckResult(
                    name=name,
                    status=CheckStatus.ERROR,
                    reason=last_collection_error,
                    attempts=attempt,
                )
    if last_collection_error is not None:
        return CheckResult(
            name=name,
            status=CheckStatus.ERROR,
            reason=last_collection_error,
            attempts=2,
        )
    raise AssertionError("unreachable")


def final_verdict(results: Iterable[CheckResult]) -> dict[str, Any]:
    rows = list(results)
    failures = [row for row in rows if row.status is CheckStatus.FAIL]
    errors = [row for row in rows if row.status is CheckStatus.ERROR]
    if failures:
        status = "FAIL"
    elif errors:
        status = "ERROR"
    else:
        status = "PASS"
    return {
        "status": status,
        "checks": [row.as_dict() for row in rows],
        "warnings": [warning for row in rows for warning in row.warnings],
        "tool_errors": [row.name for row in errors] if errors else [],
    }
