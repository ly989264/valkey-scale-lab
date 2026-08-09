from __future__ import annotations

import errno
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


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
