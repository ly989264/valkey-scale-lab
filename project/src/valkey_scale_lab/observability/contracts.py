from __future__ import annotations

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
        "tool_errors": [row.name for row in errors] if failures else [],
    }
