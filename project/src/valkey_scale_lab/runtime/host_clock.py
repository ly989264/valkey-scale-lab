"""How a host's clock is read, and how a reading becomes a bounded offset.

Both halves live here rather than in either backend, and for the same reason:
two backends that asked a host a different question, or reduced the answer with
a different estimator, would produce two kinds of number that could not be
compared. A Docker offset and a native offset have to mean the same thing.

`project/docs/cross_host_evidence_slice_map.md` §2 carries the measurement that
chose the estimator. In short, on two simulated hosts whose true offset is zero
because they share a kernel: one exchange has a tail (offset to +26.9 ms, round
trip to 57 ms), three exchanges keeping the minimum-delay sample give
+2.1..+3.2 ms and a 9.8 ms worst round trip. The residual is the exchange's own
asymmetry - the outbound leg carries a command through a shell, the return leg
carries a line of text - and it sits inside its bound of round_trip/2.

That is why nothing here reports an offset without its uncertainty. On this
development fleet the uncertainty is larger than everything being measured, and
the same estimator over `docker exec` is six times less precise than over
multiplexed ssh (+19.7 ms against a 25.7 ms bound, both containing zero). An
offset alone would be a number with no meaning.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from valkey_scale_lab.observability.contracts import CollectionError

#: What a host is asked in order to report its own clock. `python3` rather than
#: `date`, for two reasons that are one reason: it reports the wall clock and the
#: monotonic clock in a single exchange, and `time.monotonic()` is the very clock
#: §11.1's resource sampler stamps its samples with - so a host monotonic
#: timestamp elsewhere in the run's evidence is on the same scale as this
#: reading, which is what makes it mappable to controller wall time at all. Both
#: of this project's images already carry python3 because the sampler needs it.
HOST_CLOCK_ARGV: tuple[str, ...] = (
    "python3",
    "-c",
    "import time;print(repr(time.time()),repr(time.monotonic()))",
)

#: Exchanges per reading. Three, on the measurement above: one has a tail that
#: puts a 27 ms offset on a host whose true offset is zero, three collapse the
#: range to about a millisecond, and five buy a further 0.07 ms.
CLOCK_EXCHANGE_COUNT = 3


def parse_host_clock(stdout: str) -> tuple[float, float]:
    """The wall and monotonic seconds a host reported, or a stated refusal."""

    parts = stdout.strip().split()
    if len(parts) != 2:
        raise CollectionError(
            f"host clock reading is not two values: {stdout.strip()[:200]!r}"
        )
    try:
        return float(parts[0]), float(parts[1])
    except ValueError as error:
        raise CollectionError(
            f"host clock reading is not numeric: {stdout.strip()[:200]!r}"
        ) from error


def reduce_clock_exchanges(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One bounded offset from several bracketed readings.

    Keeps the exchange with the smallest round trip - the sample that spent least
    time in flight is the least biased - and reports the offset with the
    half-round-trip that bounds it. The true offset lies within
    `offset_ms ± uncertainty_ms`; the estimate is the midpoint and the bound is
    real rather than nominal.

    `host_monotonic_seconds` travels through unreduced. A monotonic clock is a
    per-boot counter with an arbitrary origin, so there is no offset between two
    machines' to compute and none is claimed; it is recorded beside the wall
    clock so that a host-stamped monotonic timestamp can be resolved to host wall
    time and from there, through the offset, to the controller's.
    """

    if not rows:
        raise CollectionError("a host clock reading needs at least one exchange")
    best = min(rows, key=_round_trip_ms)
    round_trip = _round_trip_ms(best)
    before = float(best["controller_before_unix_ms"])
    after = float(best["controller_after_unix_ms"])
    host = float(best["host_unix_ms"])
    return {
        "controller_unix_ms": round((before + after) / 2.0, 3),
        "host_unix_ms": round(host, 3),
        "host_monotonic_seconds": float(best["host_monotonic_seconds"]),
        "offset_ms": round(host - (before + after) / 2.0, 3),
        "uncertainty_ms": round(round_trip / 2.0, 3),
        "round_trip_ms": round(round_trip, 3),
        "exchanges": len(rows),
    }


def _round_trip_ms(row: Mapping[str, Any]) -> float:
    return max(
        float(row["controller_after_unix_ms"]) - float(row["controller_before_unix_ms"]),
        0.0,
    )
