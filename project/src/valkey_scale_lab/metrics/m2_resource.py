from __future__ import annotations

import ipaddress
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable


LABEL_PREFIX = "org.valkey-scale-lab"
PROJECT = "valkey-scale-lab"
MISSING = "MISSING"
MAX_SCHEDULE_LAG_SECONDS = 0.5
MAX_SCHEDULE_LAG_FRACTION = 0.1
_CLUSTER_NODE_FLAGS = frozenset(
    {"myself", "master", "slave", "fail?", "fail", "handshake", "noaddr", "nofailover", "noflags"}
)
_CLUSTER_ROLE_FLAGS = frozenset({"master", "slave"})


class M2ResourceMeasurementError(ValueError):
    pass


@dataclass(frozen=True)
class _Target:
    nodehost_id: str
    container_id: str
    container_name: str
    ownership_id: str
    pids: tuple[int, ...]
    logical_ids: tuple[str, ...]
    client_ports: tuple[int, ...]


_ProcessIdentity = tuple[str, str, int]


_PROC_BATCH_SCRIPT = r"""
clk_tck=$(getconf CLK_TCK 2>/dev/null) || exit 70
page_size=$(getconf PAGESIZE 2>/dev/null) || exit 71
printf 'META\t%s\t%s\n' "$clk_tck" "$page_size"
expected_gone_ports=$1
shift
failed=0
for owned_process in "$@"; do
  pid=${owned_process%%:*}
  port=${owned_process#*:}
  stat_path="/proc/$pid/stat"
  statm_path="/proc/$pid/statm"
  fd_path="/proc/$pid/fd"
  if [ ! -r "$stat_path" ] || [ ! -r "$statm_path" ] || [ ! -d "$fd_path" ]; then
    printf 'GONE\t%s\t%s\n' "$pid" "$port"
    continue
  fi
  stat_line=$(cat "$stat_path" 2>/dev/null) || { printf 'ERROR\t%s\tstat_unreadable\n' "$pid"; failed=1; continue; }
  stat_tail=${stat_line##*) }
  set -- $stat_tail
  utime=${12}
  stime=${13}
  set -- $(cat "$statm_path" 2>/dev/null) || { printf 'ERROR\t%s\tstatm_unreadable\n' "$pid"; failed=1; continue; }
  rss_pages=$2
  fd_count=0
  socket_count=0
  for fd in "$fd_path"/*; do
    [ -e "$fd" ] || [ -L "$fd" ] || continue
    fd_count=$((fd_count + 1))
    target=$(readlink "$fd" 2>/dev/null || true)
    case "$target" in socket:\[*\]) socket_count=$((socket_count + 1));; esac
  done
  printf 'PID\t%s\t%s\t%s\t%s\t%s\t%s\n' "$pid" "$utime" "$stime" "$rss_pages" "$fd_count" "$socket_count"
  if ! cluster_info=$(valkey-cli --raw -p "$port" CLUSTER INFO 2>/dev/null); then
    printf 'ERROR\t%s\tcluster_info_unreadable\n' "$pid"
    failed=1
    continue
  fi
  if ! cluster_values=$(printf '%s\n' "$cluster_info" | awk -F: '
    $1 == "cluster_stats_bytes_sent" { sent_bytes=$2 }
    $1 == "cluster_stats_bytes_received" { received_bytes=$2 }
    $1 == "cluster_stats_messages_sent" { sent_messages=$2 }
    $1 == "cluster_stats_messages_received" { received_messages=$2 }
    $1 == "total_cluster_links_buffer_limit_exceeded" { buffer_exceeded=$2 }
    END {
      gsub(/\r/, "", sent_bytes); gsub(/\r/, "", received_bytes)
      gsub(/\r/, "", sent_messages); gsub(/\r/, "", received_messages)
      gsub(/\r/, "", buffer_exceeded)
      if (sent_bytes !~ /^[0-9]+$/ || received_bytes !~ /^[0-9]+$/ ||
          sent_messages !~ /^[0-9]+$/ || received_messages !~ /^[0-9]+$/ ||
          buffer_exceeded !~ /^[0-9]+$/) exit 2
      printf "%s %s %s %s %s", sent_bytes, received_bytes, sent_messages, received_messages, buffer_exceeded
    }
  '); then
    printf 'ERROR\t%s\tcluster_info_counters_missing\n' "$pid"
    failed=1
    continue
  fi
  set -- $cluster_values
  sent_bytes=$1
  received_bytes=$2
  sent_messages=$3
  received_messages=$4
  buffer_exceeded=$5
  if ! cluster_nodes=$(valkey-cli --raw -p "$port" CLUSTER NODES 2>/dev/null); then
    printf 'ERROR\t%s\tcluster_nodes_unreadable\n' "$pid"
    failed=1
    continue
  fi
  if ! link_values=$(printf '%s\n' "$cluster_nodes" | awk -v expected_gone_ports="$expected_gone_ports" '
    NF {
      links += 1
      split($2, address_at, "@")
      count = split(address_at[1], host_port, ":")
      port = host_port[count]
      expected = index("," expected_gone_ports ",", "," port ",") > 0
      pending_handshake = ($1 != "" && $2 != "" && $3 == "handshake" && $4 == "-" && $8 == "disconnected")
      if ($8 != "connected") {
        non_connected += 1
        if (!expected && !pending_handshake) errors += 1
      }
    }
    END { if (links < 1) exit 2; printf "%s %s %s", links, errors + 0, non_connected + 0 }
  '); then
    printf 'ERROR\t%s\tcluster_nodes_links_missing\n' "$pid"
    failed=1
    continue
  fi
  set -- $link_values
  printf 'CLUSTER\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$pid" "$port" "$sent_bytes" "$received_bytes" "$sent_messages" "$received_messages" \
    "$buffer_exceeded" "$1" "$2" "$3"
  if ! printf '%s\n' "$cluster_nodes" | awk -v pid="$pid" '
    NF && $8 != "connected" {
      printf "LINK\t%s\t%s\t%s\t%s\t%s\t%s\n", pid, $1, $2, $3, $4, $8
    }
  '; then
    printf 'ERROR\t%s\tcluster_nodes_raw_unreadable\n' "$pid"
    failed=1
    continue
  fi
done
rx=0
tx=0
while IFS=: read -r iface data; do
  case "$iface" in *Inter-*|*face*|'') continue;; esac
  set -- $data
  [ "$#" -ge 9 ] || { failed=1; continue; }
  rx=$((rx + $1))
  tx=$((tx + $9))
done < /proc/net/dev
printf 'NET\t%s\t%s\n' "$rx" "$tx"
exit "$failed"
""".strip()


def collect_m2_resource_window(
    runtime_state: dict[str, Any],
    *,
    window_name: str,
    duration_seconds: float,
    interval_seconds: float,
    command: Callable[..., Any],
    monotonic_clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    command_timeout_seconds: int = 30,
    expected_gone_processes: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
    expected_gone_pids: set[int] | list[int] | tuple[int, ...] | None = None,
    first_complete_sample_event: Any | None = None,
    window_start_event: Any | None = None,
) -> dict[str, Any]:
    """Measure an explicitly requested M2 resource window.

    The callback receives Docker argument lists and the same ``timeout`` and
    ``check`` keyword arguments as ``runtime.docker_runtime.run_docker``. This
    function is never called from the M1 runtime path.
    """
    errors: list[str] = []
    targets: list[_Target] = []
    allowed_gone_processes: set[_ProcessIdentity] = set()
    expected_samples = 0
    window_samples = 0
    try:
        duration, interval, window_samples = _window_contract(duration_seconds, interval_seconds)
        normalized_window_name = _required_text(window_name, "window_name")
        targets, capability_id, run_id = _targets_from_state(runtime_state)
        allowed_gone_processes = _normalize_expected_gone_processes(
            expected_gone_processes,
            unsafe_pid_only_value=expected_gone_pids,
            targets=targets,
        )
        if first_complete_sample_event is not None and not callable(
            getattr(first_complete_sample_event, "set", None)
        ):
            raise M2ResourceMeasurementError("first_complete_sample_event must provide set()")
        if window_start_event is not None and not callable(getattr(window_start_event, "wait", None)):
            raise M2ResourceMeasurementError("window_start_event must provide wait()")
        expected_samples = window_samples + (1 if window_start_event is not None else 0)
        _verify_owned_targets(
            targets,
            capability_id=capability_id,
            run_id=run_id,
            command=command,
            timeout=command_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - a missing measurement must become evidence, not PASS
        errors.append(str(exc))
        return _resource_report(
            status="FAIL",
            summary="M2 resource window preflight failed",
            window_name=window_name,
            duration_seconds=duration_seconds,
            interval_seconds=interval_seconds,
            expected_samples=expected_samples,
            targets=targets,
            samples=[],
            errors=errors,
            expected_gone_processes=allowed_gone_processes,
        )

    samples: list[dict[str, Any]] = []
    captured_processes: set[_ProcessIdentity] = set()
    observed_gone_processes: set[_ProcessIdentity] = set()

    def capture_sample(sample_index: int, scheduled_offset: float, scheduled: float) -> dict[str, Any]:
        delay = scheduled - float(monotonic_clock())
        if delay > 0:
            sleep(delay)
        sample_started = float(monotonic_clock())
        wall_unix_ms = int(float(wall_clock()) * 1000.0)
        nodehost_rows: list[dict[str, Any]] = []
        sample_errors: list[str] = []
        for target in targets:
            try:
                expected_gone_ports = ",".join(
                    str(port)
                    for owned_target in targets
                    for pid, port in zip(owned_target.pids, owned_target.client_ports)
                    if _process_identity(owned_target, pid) in allowed_gone_processes
                )
                output = _run_command(
                    command,
                    [
                        "exec",
                        target.container_name,
                        "sh",
                        "-c",
                        _PROC_BATCH_SCRIPT,
                        "m2-resource",
                        expected_gone_ports,
                        *[f"{pid}:{port}" for pid, port in zip(target.pids, target.client_ports)],
                    ],
                    timeout=command_timeout_seconds,
                )
                row = _parse_batch(
                    output,
                    target,
                    expected_gone_processes=allowed_gone_processes,
                    previously_captured_processes=captured_processes,
                    previously_gone_processes=observed_gone_processes,
                )
                nodehost_rows.append(row)
                captured_processes.update(
                    _process_identity(target, process["pid"])
                    for process in row["processes"]
                )
                observed_gone_processes.update(
                    _process_identity(target, pid) for pid in row["gone_pids"]
                )
            except Exception as exc:  # noqa: BLE001 - preserve a fail-closed report for the caller
                sample_errors.append(f"{target.nodehost_id}: {exc}")
        sample_ended = float(monotonic_clock())
        if sample_ended < sample_started:
            sample_errors.append("monotonic clock moved backwards during sampling")
        sample = {
            "sample_index": sample_index,
            "scheduled_offset_seconds": round(scheduled_offset, 6),
            "scheduled_at_monotonic_seconds": round(scheduled, 6),
            "timestamp_unix_ms": wall_unix_ms,
            "started_at_monotonic_seconds": round(sample_started, 6),
            "ended_at_monotonic_seconds": round(sample_ended, 6),
            "schedule_lag_seconds": round(max(sample_started - scheduled, 0.0), 6),
            "nodehosts": nodehost_rows,
            "status": "PASS" if not sample_errors and len(nodehost_rows) == len(targets) else "FAIL",
            "errors": sample_errors,
        }
        errors.extend(f"sample {sample_index}: {message}" for message in sample_errors)
        return sample

    next_sample_index = 0
    if window_start_event is not None:
        pre_barrier = capture_sample(0, 0.0, float(monotonic_clock()))
        pre_barrier["sample_phase"] = "pre_barrier"
        samples.append(pre_barrier)
        next_sample_index = 1
        if pre_barrier["status"] == "PASS":
            if first_complete_sample_event is not None:
                try:
                    first_complete_sample_event.set()
                except Exception as exc:  # noqa: BLE001 - event failure invalidates fault evidence
                    pre_barrier["status"] = "FAIL"
                    message = f"cannot signal first complete resource sample: {exc}"
                    pre_barrier["errors"].append(message)
                    errors.append(f"sample 0: {message}")
            if pre_barrier["status"] == "PASS":
                try:
                    window_started = window_start_event.wait(timeout=command_timeout_seconds)
                except Exception as exc:  # noqa: BLE001 - event failure invalidates fault evidence
                    window_started = False
                    errors.append(f"cannot wait for resource window start: {exc}")
                if window_started is not True:
                    errors.append("timed out waiting for resource window start")
        if errors:
            window_samples = 0

    started = float(monotonic_clock())
    if samples:
        samples[0]["scheduled_offset_seconds"] = round(
            float(samples[0]["started_at_monotonic_seconds"]) - started,
            6,
        )
    for window_index in range(window_samples):
        scheduled_offset = window_index * interval
        sample = capture_sample(
            next_sample_index + window_index,
            scheduled_offset,
            started + scheduled_offset,
        )
        if window_start_event is not None:
            sample["sample_phase"] = "window"
        samples.append(sample)
        if (
            first_complete_sample_event is not None
            and window_start_event is None
            and window_index == 0
            and sample["status"] == "PASS"
        ):
            try:
                first_complete_sample_event.set()
            except Exception as exc:  # noqa: BLE001 - event failure invalidates measurement evidence
                sample["status"] = "FAIL"
                message = f"cannot signal first complete resource sample: {exc}"
                sample["errors"].append(message)
                errors.append(f"sample {sample['sample_index']}: {message}")

    fixed_window_samples = samples[1:] if window_start_event is not None else samples
    errors.extend(_fixed_window_timing_errors(fixed_window_samples, duration, interval))
    complete = (
        not errors
        and len(samples) == expected_samples
        and all(sample["status"] == "PASS" for sample in samples)
        and all(len(sample["nodehosts"]) == len(targets) for sample in samples)
        and observed_gone_processes == allowed_gone_processes
    )
    if observed_gone_processes != allowed_gone_processes:
        errors.append(
            "expected-gone process identity set does not match observed disappearance: "
            f"expected={_identity_rows(allowed_gone_processes)} "
            f"observed={_identity_rows(observed_gone_processes)}"
        )
    if not complete:
        errors.append("resource sampling coverage is incomplete")
    return _resource_report(
        status="PASS" if complete else "FAIL",
        summary=(
            f"collected {expected_samples} complete M2 resource samples"
            if complete
            else "M2 resource window is incomplete"
        ),
        window_name=normalized_window_name,
        duration_seconds=duration,
        interval_seconds=interval,
        expected_samples=expected_samples,
        targets=targets,
        samples=samples,
        errors=errors,
        expected_gone_processes=allowed_gone_processes,
        captured_processes=captured_processes,
        observed_gone_processes=observed_gone_processes,
    )


def validate_and_aggregate_m2_resource_samples(report: dict[str, Any]) -> dict[str, Any]:
    """Recompute an M2 resource window from its raw samples, failing closed."""
    missing_metrics: dict[str, int | float | str] = {
        "peak_rss_bytes": MISSING,
        "cpu_time_seconds": MISSING,
        "fd_count": MISSING,
        "connection_count": MISSING,
        "cluster_bus_bytes": MISSING,
        "cluster_link_errors": MISSING,
        "buffer_overflows": MISSING,
    }
    missing_diagnostics: dict[str, int | str] = {
        "cluster_bus_messages": MISSING,
        "namespace_network_bytes": MISSING,
    }
    errors: list[str] = []
    if not isinstance(report, dict):
        return {
            "status": "FAIL",
            "errors": ["resource report must be an object"],
            "coverage": {"complete": False},
            "metrics": missing_metrics,
            "diagnostics": missing_diagnostics,
        }

    coverage = report.get("coverage")
    ownership = report.get("ownership")
    fault_capture = report.get("fault_target_capture")
    samples = report.get("samples")
    if not isinstance(coverage, dict):
        errors.append("resource coverage must be an object")
        coverage = {}
    if not isinstance(ownership, dict):
        errors.append("resource ownership must be an object")
        ownership = {}
    if not isinstance(fault_capture, dict):
        errors.append("fault_target_capture must be an object")
        fault_capture = {}
    if not isinstance(samples, list):
        errors.append("resource samples must be an array")
        samples = []

    duration: float | None = None
    interval: float | None = None
    expected_window_samples: int | None = None
    try:
        duration, interval, expected_window_samples = _window_contract(
            report.get("duration_seconds"),
            report.get("interval_seconds"),
        )
    except M2ResourceMeasurementError as exc:
        errors.append(str(exc))

    expected_sample_count = _positive_claim(coverage.get("expected_sample_count"), "expected sample count", errors)
    expected_nodehost_count = _positive_claim(coverage.get("nodehost_count"), "nodehost count", errors)
    expected_process_count = _positive_claim(coverage.get("process_count"), "process count", errors)
    owned_pids = _positive_int_list(ownership.get("pids"), "ownership pids", errors, unique=False)
    owned_ports = _positive_int_list(ownership.get("client_ports"), "ownership client_ports", errors, unique=False)
    owned_container_ids = _text_list(ownership.get("container_ids"), "ownership container_ids", errors)
    owned_ownership_ids = _text_list(ownership.get("ownership_ids"), "ownership ownership_ids", errors)
    expected_gone_processes = _process_identity_list(
        fault_capture.get("expected_gone_processes"),
        "expected_gone_processes",
        errors,
    )
    claimed_observed_gone = _process_identity_list(
        fault_capture.get("observed_gone_processes"),
        "observed_gone_processes",
        errors,
    )
    claimed_captured_before_gone = _process_identity_list(
        fault_capture.get("captured_before_gone_processes"),
        "captured_before_gone_processes",
        errors,
    )
    fault_bindings = fault_capture.get("bindings")
    if not isinstance(fault_bindings, list):
        errors.append("fault target bindings must be an array")
        fault_bindings = []

    if coverage.get("complete") is not True:
        errors.append("resource coverage is not complete")
    if expected_sample_count is not None and len(samples) != expected_sample_count:
        errors.append(
            f"resource sample count is not exact: expected={expected_sample_count} observed={len(samples)}"
        )
    if coverage.get("observed_sample_count") != len(samples):
        errors.append("observed sample count does not match raw samples")
    if expected_process_count is not None and len(owned_pids) != expected_process_count:
        errors.append("ownership PID count does not match process coverage")
    if len(owned_ports) != len(owned_pids):
        errors.append("ownership client ports do not match ownership PIDs")
    if expected_nodehost_count is not None and len(owned_container_ids) != expected_nodehost_count:
        errors.append("ownership containers do not match nodehost coverage")

    barrier_mode = bool(samples) and isinstance(samples[0], dict) and samples[0].get("sample_phase") == "pre_barrier"
    if expected_window_samples is not None:
        raw_expected = expected_window_samples + (1 if barrier_mode else 0)
        if expected_sample_count != raw_expected:
            errors.append("expected sample count does not match duration, interval, and barrier mode")
    window_samples = samples[1:] if barrier_mode else samples
    expected_offsets = (
        [round(index * interval, 6) for index in range(expected_window_samples)]
        if interval is not None and expected_window_samples is not None
        else []
    )
    observed_offsets = [
        sample.get("scheduled_offset_seconds") if isinstance(sample, dict) else None
        for sample in window_samples
    ]
    if observed_offsets != expected_offsets:
        errors.append("raw resource sample schedule does not cover the fixed window")
    if barrier_mode and any(
        not isinstance(sample, dict) or sample.get("sample_phase") != "window"
        for sample in window_samples
    ):
        errors.append("barrier resource samples do not identify the complete post-barrier window")
    raw_scheduled = [
        sample.get("scheduled_at_monotonic_seconds") if isinstance(sample, dict) else None
        for sample in window_samples
    ]
    raw_starts = [
        sample.get("started_at_monotonic_seconds") if isinstance(sample, dict) else None
        for sample in window_samples
    ]
    raw_ends = [
        sample.get("ended_at_monotonic_seconds") if isinstance(sample, dict) else None
        for sample in window_samples
    ]
    numeric_bounds = all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        for value in [*raw_scheduled, *raw_starts, *raw_ends]
    )
    if not numeric_bounds or any(float(end) < float(start) for start, end in zip(raw_starts, raw_ends)):
        errors.append("raw resource samples lack valid monotonic bounds")
    elif any(float(right) < float(left) for left, right in zip(raw_starts, raw_starts[1:])):
        errors.append("raw resource sample starts are not monotonic")
    elif duration is not None and interval is not None:
        lag_limit = _schedule_lag_limit(interval)
        expected_scheduled = [float(raw_scheduled[0]) + offset for offset in expected_offsets] if raw_scheduled else []
        if any(
            not math.isclose(float(observed), expected, rel_tol=0.0, abs_tol=1e-6)
            for observed, expected in zip(raw_scheduled, expected_scheduled)
        ):
            errors.append("raw resource sample monotonic schedule is not fixed")
        recomputed_lags = [max(float(start) - float(scheduled), 0.0) for scheduled, start in zip(raw_scheduled, raw_starts)]
        claimed_lags = [sample.get("schedule_lag_seconds") for sample in window_samples]
        if any(
            isinstance(claimed, bool)
            or not isinstance(claimed, (int, float))
            or not math.isfinite(float(claimed))
            or not math.isclose(float(claimed), lag, rel_tol=0.0, abs_tol=1e-6)
            for claimed, lag in zip(claimed_lags, recomputed_lags)
        ):
            errors.append("raw resource schedule lag does not match monotonic bounds")
        if recomputed_lags and max(recomputed_lags) > lag_limit + 1e-6:
            errors.append(
                f"raw resource schedule lag exceeds fixed-window limit {round(lag_limit, 6)} seconds"
            )
        sample_durations = [float(end) - float(start) for start, end in zip(raw_starts, raw_ends)]
        if sample_durations and max(sample_durations) > interval + 1e-6:
            errors.append("raw resource sample collection overran its fixed interval")
        actual_span = float(raw_starts[-1]) - float(raw_starts[0]) if raw_starts else -1.0
        if not math.isclose(actual_span, duration, rel_tol=0.0, abs_tol=lag_limit + 1e-6):
            errors.append("raw resource sample starts do not span the complete fixed window")
    if barrier_mode and numeric_bounds:
        pre_start = samples[0].get("started_at_monotonic_seconds")
        pre_end = samples[0].get("ended_at_monotonic_seconds")
        if (
            not isinstance(pre_start, (int, float))
            or isinstance(pre_start, bool)
            or not isinstance(pre_end, (int, float))
            or isinstance(pre_end, bool)
            or float(pre_end) < float(pre_start)
            or not raw_starts
            or float(pre_end) > float(raw_starts[0]) + 1e-3
        ):
            errors.append("pre-barrier resource sample does not precede the fixed window")
    if coverage.get("sample_monotonic_seconds") != [
        sample.get("started_at_monotonic_seconds") if isinstance(sample, dict) else None
        for sample in samples
    ] or coverage.get("scheduled_offsets_seconds") != [
        sample.get("scheduled_offset_seconds") if isinstance(sample, dict) else None
        for sample in samples
    ]:
        errors.append("resource coverage bounds do not match raw samples")
    recomputed_window_bounds = _window_bounds(window_samples)
    if any(
        not _same_number(coverage.get(field), value)
        for field, value in recomputed_window_bounds.items()
    ):
        errors.append("resource actual window bounds do not match raw samples")

    first_nodehost_keys: set[tuple[str, str, str, str]] | None = None
    first_process_keys: set[_ProcessIdentity] | None = None
    process_identity: dict[_ProcessIdentity, dict[str, Any]] = {}
    gone_process_keys: set[_ProcessIdentity] = set()
    observed_gone_processes: set[_ProcessIdentity] = set()
    captured_before_gone_processes: set[_ProcessIdentity] = set()
    for sample_position, sample in enumerate(samples):
        if not isinstance(sample, dict):
            errors.append(f"sample {sample_position} must be an object")
            continue
        if sample.get("sample_index") != sample_position:
            errors.append(f"sample index is not exact at position {sample_position}")
        if sample.get("status") != "PASS" or sample.get("errors") != []:
            errors.append(f"sample {sample_position} is not a clean PASS")
        nodehosts = sample.get("nodehosts")
        if not isinstance(nodehosts, list):
            errors.append(f"sample {sample_position} nodehosts must be an array")
            continue
        if expected_nodehost_count is not None and len(nodehosts) != expected_nodehost_count:
            errors.append(f"sample {sample_position} nodehost coverage is not exact")
        sample_nodehost_keys: set[tuple[str, str, str, str]] = set()
        sample_nodehost_ids: set[str] = set()
        sample_container_ids: set[str] = set()
        sample_container_names: set[str] = set()
        sample_process_keys: set[_ProcessIdentity] = set()
        sample_logical_ids: set[str] = set()
        sample_pid_values: list[int] = []
        sample_gone_keys: set[_ProcessIdentity] = set()
        for nodehost_position, nodehost in enumerate(nodehosts):
            if not isinstance(nodehost, dict):
                errors.append(f"sample {sample_position} nodehost {nodehost_position} must be an object")
                continue
            nodehost_id = nodehost.get("nodehost_id")
            container_id = nodehost.get("container_id")
            container_name = nodehost.get("container_name")
            ownership_id = nodehost.get("ownership_id")
            if not all(isinstance(value, str) and value for value in (nodehost_id, container_id, container_name, ownership_id)):
                errors.append(f"sample {sample_position} has incomplete nodehost identity")
                continue
            nodehost_key = (nodehost_id, container_id, container_name, ownership_id)
            if (
                nodehost_id in sample_nodehost_ids
                or container_id in sample_container_ids
                or container_name in sample_container_names
            ):
                errors.append(f"sample {sample_position} has duplicate nodehost {nodehost_id}")
            sample_nodehost_keys.add(nodehost_key)
            sample_nodehost_ids.add(nodehost_id)
            sample_container_ids.add(container_id)
            sample_container_names.add(container_name)
            if container_id not in owned_container_ids or ownership_id not in owned_ownership_ids:
                errors.append(f"sample {sample_position} nodehost {nodehost_id} is not owned")
            if not _valid_positive_int(nodehost.get("clock_ticks_per_second")) or not _valid_positive_int(
                nodehost.get("page_size_bytes")
            ):
                errors.append(f"sample {sample_position} nodehost {nodehost_id} has invalid proc metadata")
            namespace_network = nodehost.get("namespace_network")
            if not isinstance(namespace_network, dict) or not all(
                _valid_nonnegative_int(namespace_network.get(field)) for field in ("rx_bytes", "tx_bytes")
            ):
                errors.append(f"sample {sample_position} nodehost {nodehost_id} has invalid network counters")
            processes = nodehost.get("processes")
            gone_pids = nodehost.get("gone_pids")
            if not isinstance(processes, list) or not isinstance(gone_pids, list):
                errors.append(f"sample {sample_position} nodehost {nodehost_id} has invalid process arrays")
                continue
            local_pids: set[int] = set()
            for process_position, process in enumerate(processes):
                if not isinstance(process, dict):
                    errors.append(
                        f"sample {sample_position} nodehost {nodehost_id} process {process_position} must be an object"
                    )
                    continue
                pid = process.get("pid")
                logical_id = process.get("logical_id")
                if not _valid_positive_int(pid) or not isinstance(logical_id, str) or not logical_id:
                    errors.append(f"sample {sample_position} nodehost {nodehost_id} has invalid process identity")
                    continue
                process_key = (nodehost_id, container_id, pid)
                if pid in local_pids or process_key in sample_process_keys or logical_id in sample_logical_ids:
                    errors.append(f"sample {sample_position} has duplicate owned process identity")
                local_pids.add(pid)
                sample_process_keys.add(process_key)
                sample_logical_ids.add(logical_id)
                sample_pid_values.append(pid)
                if process_key in gone_process_keys:
                    errors.append(f"sample {sample_position} process {process_key} reappeared after disappearance")
                if not _valid_resource_process(process):
                    errors.append(f"sample {sample_position} process {process_key} has invalid counters")
                identity = {
                    "pid": pid,
                    "logical_id": logical_id,
                    "client_port": process.get("client_port"),
                    "nodehost_id": nodehost_id,
                    "container_id": container_id,
                    "ownership_id": ownership_id,
                }
                if process_key in process_identity and process_identity[process_key] != identity:
                    errors.append(f"sample {sample_position} process {process_key} changed identity")
                process_identity.setdefault(process_key, identity)
            for gone_pid in gone_pids:
                if not _valid_positive_int(gone_pid):
                    errors.append(f"sample {sample_position} nodehost {nodehost_id} has invalid gone PID")
                    continue
                gone_key = (nodehost_id, container_id, gone_pid)
                if gone_pid in local_pids or gone_key in sample_gone_keys:
                    errors.append(f"sample {sample_position} has duplicate or live gone PID {gone_key}")
                sample_gone_keys.add(gone_key)
                sample_pid_values.append(gone_pid)
                observed_gone_processes.add(gone_key)
            if sample_position == 0 and sample_gone_keys:
                errors.append("first resource sample did not capture every owned process before fault injection")
        if sorted(sample_pid_values) != sorted(owned_pids):
            errors.append(f"sample {sample_position} does not contain the exact owned PID union")
        if first_nodehost_keys is None:
            first_nodehost_keys = sample_nodehost_keys
            first_process_keys = sample_process_keys
        elif sample_nodehost_keys != first_nodehost_keys:
            errors.append(f"sample {sample_position} nodehost identity set changed")
        if first_process_keys is not None:
            expected_live_or_gone = sample_process_keys | sample_gone_keys
            if expected_live_or_gone != first_process_keys:
                errors.append(f"sample {sample_position} process ownership set changed")
        unexpected_gone = sample_gone_keys - set(expected_gone_processes)
        if unexpected_gone:
            errors.append(
                f"sample {sample_position} contains unexpected gone process identities "
                f"{_identity_rows(unexpected_gone)}"
            )
        gone_process_keys.update(sample_gone_keys)

    if first_nodehost_keys is not None:
        if {container_id for _, container_id, _, _ in first_nodehost_keys} != set(owned_container_ids):
            errors.append("raw nodehost containers do not match ownership")
    if sorted(process.get("client_port") for process in process_identity.values()) != sorted(owned_ports):
        errors.append("raw process client ports do not match ownership")
    if set(expected_gone_processes) != observed_gone_processes:
        errors.append("raw samples do not observe every and only expected-gone process identity")
    for process_key in expected_gone_processes:
        owner = process_identity.get(process_key)
        if owner is not None and process_key in observed_gone_processes:
            captured_before_gone_processes.add(process_key)
        else:
            errors.append(
                "expected-gone process identity is not bound to one captured owned process: "
                f"{_identity_row(process_key)}"
            )

    binding_by_process: dict[_ProcessIdentity, dict[str, Any]] = {}
    for binding in fault_bindings:
        binding_errors: list[str] = []
        binding_keys = _process_identity_list([binding], "fault target binding", binding_errors)
        if binding_errors or not binding_keys:
            errors.extend(binding_errors or ["fault target binding must contain a process identity"])
            continue
        process_key = binding_keys[0]
        if process_key in binding_by_process:
            errors.append(f"duplicate fault target binding for process {_identity_row(process_key)}")
        binding_by_process[process_key] = binding
    if set(binding_by_process) != set(expected_gone_processes):
        errors.append("fault target bindings do not exactly match expected-gone process identities")
    for process_key, binding in binding_by_process.items():
        owner = process_identity.get(process_key)
        if owner is None or any(binding.get(field) != owner[field] for field in owner):
            errors.append(
                "fault target binding does not match raw process identity: "
                f"{_identity_row(process_key)}"
            )
    if (
        set(claimed_observed_gone) != observed_gone_processes
        or set(claimed_captured_before_gone) != captured_before_gone_processes
        or fault_capture.get("binding_status") != "PASS"
    ):
        errors.append("fault target capture claims do not match raw samples")
    expected_gone_client_ports = {
        binding["client_port"]
        for process_key, binding in binding_by_process.items()
        if process_key in set(expected_gone_processes) and _valid_positive_int(binding.get("client_port"))
    }

    metrics = missing_metrics
    diagnostics = missing_diagnostics
    if not errors:
        try:
            metrics, diagnostics = _aggregate_samples(
                samples,
                expected_gone_client_ports=expected_gone_client_ports,
                allow_initial_membership_transitions=(
                    report.get("window_name") == "m2-formation-bootstrap"
                ),
            )
        except (KeyError, TypeError, M2ResourceMeasurementError) as exc:
            errors.append(f"cannot aggregate raw resource samples: {exc}")
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "coverage": {
            "complete": not errors,
            "expected_sample_count": expected_sample_count if expected_sample_count is not None else MISSING,
            "observed_sample_count": len(samples),
            "nodehost_count": len(first_nodehost_keys or set()),
            "process_count": len(first_process_keys or set()),
            **_window_bounds(window_samples),
        },
        "metrics": metrics,
        "diagnostics": diagnostics,
        "fault_target_capture": {
            "expected_gone_processes": _identity_rows(expected_gone_processes),
            "observed_gone_processes": _identity_rows(observed_gone_processes),
            "captured_before_gone_processes": _identity_rows(captured_before_gone_processes),
            "binding_status": "PASS" if not errors else "FAIL",
        },
    }


def validate_equal_m2_resource_windows(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed unless both arms have complete, equal resource windows."""
    errors: list[str] = []
    required_metrics = {
        "peak_rss_bytes",
        "cpu_time_seconds",
        "fd_count",
        "connection_count",
        "cluster_bus_bytes",
        "cluster_link_errors",
        "buffer_overflows",
    }
    recomputed_by_arm: dict[str, dict[str, Any]] = {}
    for arm_name, report in (("baseline", baseline), ("candidate", candidate)):
        if not isinstance(report, dict) or report.get("status") != "PASS":
            errors.append(f"{arm_name} resource window is not PASS")
            continue
        recomputed = validate_and_aggregate_m2_resource_samples(report)
        recomputed_by_arm[arm_name] = recomputed
        if recomputed.get("status") != "PASS":
            errors.append(f"{arm_name} raw resource window is incomplete or invalid")
            continue
        coverage = report.get("coverage")
        if not isinstance(coverage, dict) or coverage.get("complete") is not True:
            errors.append(f"{arm_name} resource window coverage is incomplete")
        metrics = report.get("metrics")
        if not isinstance(metrics, dict):
            errors.append(f"{arm_name} resource metrics are missing")
            continue
        recomputed_metrics = recomputed.get("metrics")
        if not isinstance(recomputed_metrics, dict):
            errors.append(f"{arm_name} raw-derived resource metrics are missing")
            continue
        for name in sorted(required_metrics):
            value = metrics.get(name, MISSING)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                errors.append(f"{arm_name} metric {name} is missing or non-numeric")
            elif not _same_number(value, recomputed_metrics.get(name)):
                errors.append(f"{arm_name} metric {name} does not match raw samples")
        for name in ("cluster_link_errors", "buffer_overflows"):
            if metrics.get(name) != 0:
                errors.append(f"{arm_name} metric {name} must be zero")

    contract_fields = ("duration_seconds", "interval_seconds")
    for field in contract_fields:
        left = baseline.get(field) if isinstance(baseline, dict) else MISSING
        right = candidate.get(field) if isinstance(candidate, dict) else MISSING
        if not _same_number(left, right):
            errors.append(f"resource windows have unequal {field}: baseline={left!r} candidate={right!r}")
    for field in ("expected_sample_count", "observed_sample_count", "nodehost_count", "process_count"):
        left = baseline.get("coverage", {}).get(field, MISSING) if isinstance(baseline, dict) else MISSING
        right = candidate.get("coverage", {}).get(field, MISSING) if isinstance(candidate, dict) else MISSING
        if left != right:
            errors.append(f"resource windows have unequal coverage {field}: baseline={left!r} candidate={right!r}")

    baseline_coverage = recomputed_by_arm.get("baseline", {}).get("coverage", {})
    candidate_coverage = recomputed_by_arm.get("candidate", {}).get("coverage", {})
    interval = baseline.get("interval_seconds") if isinstance(baseline, dict) else None
    if (
        isinstance(interval, (int, float))
        and not isinstance(interval, bool)
        and math.isfinite(float(interval))
        and float(interval) > 0
    ):
        equality_tolerance = _schedule_lag_limit(float(interval))
    else:
        equality_tolerance = 0.0
    for field in (
        "actual_window_span_seconds",
        "sampling_envelope_span_seconds",
        "max_schedule_lag_seconds",
        "max_sample_collection_seconds",
    ):
        left = baseline_coverage.get(field, MISSING)
        right = candidate_coverage.get(field, MISSING)
        if (
            not isinstance(left, (int, float))
            or isinstance(left, bool)
            or not isinstance(right, (int, float))
            or isinstance(right, bool)
            or not math.isfinite(float(left))
            or not math.isfinite(float(right))
            or abs(float(left) - float(right)) > equality_tolerance + 1e-6
        ):
            errors.append(
                f"resource windows have unequal {field}: baseline={left!r} candidate={right!r}"
            )

    return {
        "status": "PASS" if not errors else "FAIL",
        "summary": "baseline and candidate resource windows are equal and complete" if not errors else "resource windows are not equal and complete",
        "errors": errors,
        "window_contract": {
            "duration_seconds": baseline.get("duration_seconds", MISSING) if isinstance(baseline, dict) else MISSING,
            "interval_seconds": baseline.get("interval_seconds", MISSING) if isinstance(baseline, dict) else MISSING,
            "comparison_basis": "equal_declared_and_raw_derived_actual_fixed_windows",
            "actual_baseline": baseline_coverage,
            "actual_candidate": candidate_coverage,
            "actual_equality_tolerance_seconds": round(equality_tolerance, 6),
        },
    }


def _window_contract(duration_seconds: float, interval_seconds: float) -> tuple[float, float, int]:
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)):
        raise M2ResourceMeasurementError("duration_seconds must be a finite number")
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float)):
        raise M2ResourceMeasurementError("interval_seconds must be a finite number")
    duration = float(duration_seconds)
    interval = float(interval_seconds)
    if not math.isfinite(duration) or duration <= 0:
        raise M2ResourceMeasurementError("duration_seconds must be greater than zero")
    if not math.isfinite(interval) or interval <= 0:
        raise M2ResourceMeasurementError("interval_seconds must be greater than zero")
    intervals = duration / interval
    rounded = round(intervals)
    if not math.isclose(intervals, rounded, rel_tol=0.0, abs_tol=1e-9):
        raise M2ResourceMeasurementError("duration_seconds must be an exact multiple of interval_seconds")
    return duration, interval, int(rounded) + 1


def _targets_from_state(runtime_state: dict[str, Any]) -> tuple[list[_Target], str, str]:
    if not isinstance(runtime_state, dict):
        raise M2ResourceMeasurementError("runtime state must be an object")
    capability_id = _required_text(runtime_state.get("capability_id"), "runtime state capability_id")
    runtime = runtime_state.get("runtime")
    if not isinstance(runtime, dict):
        raise M2ResourceMeasurementError("runtime state runtime must be an object")
    run_id = _required_text(runtime.get("run_id"), "runtime state runtime.run_id")
    nodes = runtime_state.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise M2ResourceMeasurementError("runtime state requires at least one owned process node")

    raw_nodehosts = runtime_state.get("nodehosts")
    if isinstance(raw_nodehosts, list) and raw_nodehosts:
        nodehost_rows = raw_nodehosts
    else:
        nodehost_rows = []
        seen_containers: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                raise M2ResourceMeasurementError("runtime state nodes must contain objects")
            container_name = _required_text(
                node.get("nodehost_container_name") or node.get("container_name"),
                "node container_name",
            )
            if container_name in seen_containers:
                continue
            seen_containers.add(container_name)
            nodehost_rows.append(
                {
                    "nodehost_id": node.get("nodehost_id") or node.get("logical_id"),
                    "container_id": node.get("container_id"),
                    "container_name": container_name,
                }
            )

    nodehost_by_id: dict[str, dict[str, Any]] = {}
    container_to_id: dict[str, str] = {}
    for row in nodehost_rows:
        if not isinstance(row, dict):
            raise M2ResourceMeasurementError("runtime state nodehosts must contain objects")
        nodehost_id = _required_text(row.get("nodehost_id"), "nodehost_id")
        container_id = _required_text(row.get("container_id"), f"{nodehost_id} container_id")
        container_name = _required_text(row.get("container_name"), f"{nodehost_id} container_name")
        if nodehost_id in nodehost_by_id or container_name in container_to_id:
            raise M2ResourceMeasurementError(f"duplicate nodehost ownership target {nodehost_id}/{container_name}")
        nodehost_by_id[nodehost_id] = {
            "container_id": container_id,
            "container_name": container_name,
            "pids": [],
            "logical_ids": [],
            "client_ports": [],
        }
        container_to_id[container_name] = nodehost_id

    seen_pid_targets: set[tuple[str, int]] = set()
    seen_port_targets: set[tuple[str, int]] = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise M2ResourceMeasurementError("runtime state nodes must contain objects")
        logical_id = _required_text(node.get("logical_id"), "node logical_id")
        pid = node.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise M2ResourceMeasurementError(f"{logical_id} requires a positive numeric owned pid")
        client_port = node.get("client_port")
        if isinstance(client_port, bool) or not isinstance(client_port, int) or not 0 < client_port <= 65535:
            raise M2ResourceMeasurementError(f"{logical_id} requires a valid owned client_port")
        nodehost_id_value = node.get("nodehost_id")
        if nodehost_id_value is None:
            container_name = _required_text(
                node.get("nodehost_container_name") or node.get("container_name"),
                f"{logical_id} container_name",
            )
            nodehost_id = container_to_id.get(container_name, "")
        else:
            nodehost_id = str(nodehost_id_value)
        if nodehost_id not in nodehost_by_id:
            raise M2ResourceMeasurementError(f"{logical_id} references unowned nodehost {nodehost_id!r}")
        target = nodehost_by_id[nodehost_id]
        node_container = node.get("nodehost_container_name") or node.get("container_name")
        if node_container and str(node_container) != target["container_name"]:
            raise M2ResourceMeasurementError(f"{logical_id} container does not match its owned nodehost")
        node_container_id = node.get("container_id")
        if node_container_id and not _same_container_id(str(node_container_id), target["container_id"]):
            raise M2ResourceMeasurementError(f"{logical_id} container id does not match its owned nodehost")
        pid_key = (target["container_name"], pid)
        if pid_key in seen_pid_targets:
            raise M2ResourceMeasurementError(f"duplicate owned pid {pid} in {target['container_name']}")
        port_key = (target["container_name"], client_port)
        if port_key in seen_port_targets:
            raise M2ResourceMeasurementError(f"duplicate owned client_port {client_port} in {target['container_name']}")
        seen_pid_targets.add(pid_key)
        seen_port_targets.add(port_key)
        target["pids"].append(pid)
        target["logical_ids"].append(logical_id)
        target["client_ports"].append(client_port)

    targets: list[_Target] = []
    for nodehost_id in sorted(nodehost_by_id):
        row = nodehost_by_id[nodehost_id]
        if not row["pids"]:
            raise M2ResourceMeasurementError(f"owned nodehost {nodehost_id} has no explicit process pids")
        ordered = sorted(zip(row["pids"], row["logical_ids"], row["client_ports"]), key=lambda item: item[0])
        targets.append(
            _Target(
                nodehost_id=nodehost_id,
                container_id=row["container_id"],
                container_name=row["container_name"],
                ownership_id=run_id,
                pids=tuple(item[0] for item in ordered),
                logical_ids=tuple(item[1] for item in ordered),
                client_ports=tuple(item[2] for item in ordered),
            )
        )
    return targets, capability_id, run_id


def _verify_owned_targets(
    targets: list[_Target],
    *,
    capability_id: str,
    run_id: str,
    command: Callable[..., Any],
    timeout: int,
) -> None:
    expected_labels = {
        f"{LABEL_PREFIX}.project": PROJECT,
        f"{LABEL_PREFIX}.capability_id": capability_id,
        f"{LABEL_PREFIX}.run_id": run_id,
    }
    for target in targets:
        output = _run_command(command, ["inspect", target.container_name], timeout=timeout)
        try:
            raw = json.loads(output)
        except (TypeError, json.JSONDecodeError) as exc:
            raise M2ResourceMeasurementError(f"cannot parse ownership inspection for {target.container_name}") from exc
        inspected = raw[0] if isinstance(raw, list) and len(raw) == 1 else raw
        if not isinstance(inspected, dict):
            raise M2ResourceMeasurementError(f"ownership inspection for {target.container_name} must contain one object")
        actual_id = inspected.get("Id")
        labels = inspected.get("Config", {}).get("Labels") if isinstance(inspected.get("Config"), dict) else None
        if not isinstance(actual_id, str) or not _same_container_id(actual_id, target.container_id):
            raise M2ResourceMeasurementError(f"container id ownership mismatch for {target.container_name}")
        if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected_labels.items()):
            raise M2ResourceMeasurementError(
                f"container {target.container_name} is not owned by capability_id {capability_id} and run_id {run_id}"
            )


def _normalize_expected_gone_processes(
    value: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None,
    *,
    unsafe_pid_only_value: set[int] | list[int] | tuple[int, ...] | None,
    targets: list[_Target],
) -> set[_ProcessIdentity]:
    if unsafe_pid_only_value:
        raise M2ResourceMeasurementError(
            "expected_gone_pids is unsafe across PID namespaces; use nodehost_id, container_id, and pid identities"
        )
    if value is None:
        return set()
    if not isinstance(value, (list, tuple)):
        raise M2ResourceMeasurementError("expected_gone_processes must be an explicit process identity array")
    target_by_nodehost = {target.nodehost_id: target for target in targets}
    normalized: set[_ProcessIdentity] = set()
    for position, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise M2ResourceMeasurementError(
                f"expected_gone_processes[{position}] must contain nodehost_id, container_id, and pid"
            )
        nodehost_id = _required_text(raw.get("nodehost_id"), f"expected_gone_processes[{position}].nodehost_id")
        container_id = _required_text(raw.get("container_id"), f"expected_gone_processes[{position}].container_id")
        pid = raw.get("pid")
        if not _valid_positive_int(pid):
            raise M2ResourceMeasurementError(f"expected_gone_processes[{position}].pid must be positive")
        target = target_by_nodehost.get(nodehost_id)
        if (
            target is None
            or pid not in target.pids
            or not _same_container_id(container_id, target.container_id)
        ):
            raise M2ResourceMeasurementError(
                "expected-gone process identity is not bound to an owned fault target: "
                f"{ {'nodehost_id': nodehost_id, 'container_id': container_id, 'pid': pid} }"
            )
        identity = _process_identity(target, pid)
        if identity in normalized:
            raise M2ResourceMeasurementError(
                f"expected_gone_processes contains duplicate identity {_identity_row(identity)}"
            )
        normalized.add(identity)
    return normalized


def _run_command(command: Callable[..., Any], args: list[str], *, timeout: int) -> str:
    result = command(args, timeout=timeout, check=False)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        returncode = result.get("returncode", MISSING)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
    else:
        returncode = getattr(result, "returncode", MISSING)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
    if isinstance(returncode, bool) or not isinstance(returncode, int):
        raise M2ResourceMeasurementError("measurement command did not return a numeric returncode")
    if returncode != 0:
        raise M2ResourceMeasurementError(f"measurement command failed exit={returncode}: {str(stderr).strip()}")
    if not isinstance(stdout, str) or not stdout.strip():
        raise M2ResourceMeasurementError("measurement command returned empty output")
    return stdout


def _parse_batch(
    output: str,
    target: _Target,
    *,
    expected_gone_processes: set[_ProcessIdentity],
    previously_captured_processes: set[_ProcessIdentity],
    previously_gone_processes: set[_ProcessIdentity],
) -> dict[str, Any]:
    clock_ticks = 0
    page_size = 0
    processes: dict[int, dict[str, int]] = {}
    cluster_counters: dict[int, dict[str, int]] = {}
    non_connected_cluster_links: dict[int, list[dict[str, Any]]] = {}
    gone_pids: set[int] = set()
    rx_bytes: int | None = None
    tx_bytes: int | None = None
    errors: list[str] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        if parts[0] == "META" and len(parts) == 3:
            clock_ticks = _positive_int(parts[1], "CLK_TCK")
            page_size = _positive_int(parts[2], "PAGESIZE")
        elif parts[0] == "PID" and len(parts) == 7:
            pid = _positive_int(parts[1], "pid")
            if pid in processes:
                raise M2ResourceMeasurementError(f"duplicate proc sample for pid {pid}")
            values = [_nonnegative_int(value, f"pid {pid} proc field") for value in parts[2:]]
            processes[pid] = {
                "cpu_ticks": values[0] + values[1],
                "rss_pages": values[2],
                "fd_count": values[3],
                "connection_count": values[4],
            }
        elif parts[0] == "CLUSTER" and len(parts) == 11:
            pid = _positive_int(parts[1], "cluster pid")
            if pid in cluster_counters:
                raise M2ResourceMeasurementError(f"duplicate cluster sample for pid {pid}")
            values = [_nonnegative_int(value, f"pid {pid} cluster field") for value in parts[2:]]
            cluster_counters[pid] = {
                "client_port": values[0],
                "bytes_sent": values[1],
                "bytes_received": values[2],
                "messages_sent": values[3],
                "messages_received": values[4],
                "buffer_overflows": values[5],
                "cluster_link_count": values[6],
                "cluster_link_errors": values[7],
                "non_connected_cluster_link_count": values[8],
            }
        elif parts[0] == "LINK" and len(parts) == 7:
            pid = _positive_int(parts[1], "cluster link pid")
            non_connected_cluster_links.setdefault(pid, []).append(
                {
                    "node_id": parts[2],
                    "address": parts[3],
                    "flags": parts[4].split(",") if parts[4] else [],
                    "master_id": parts[5],
                    "link_state": parts[6],
                }
            )
        elif parts[0] == "GONE" and len(parts) == 3:
            pid = _positive_int(parts[1], "gone pid")
            port = _positive_int(parts[2], "gone client_port")
            process_identity = _process_identity(target, pid)
            if pid in gone_pids:
                errors.append(f"duplicate gone sample for pid {pid}")
            elif process_identity not in expected_gone_processes:
                errors.append(f"unexpected owned process {_identity_row(process_identity)} disappeared")
            elif process_identity not in previously_captured_processes:
                errors.append(
                    f"expected-gone process {_identity_row(process_identity)} disappeared before its first resource sample"
                )
            elif port != dict(zip(target.pids, target.client_ports)).get(pid):
                errors.append(f"gone sample for pid {pid} used an unowned client_port")
            gone_pids.add(pid)
        elif parts[0] == "NET" and len(parts) == 3:
            if rx_bytes is not None:
                raise M2ResourceMeasurementError("duplicate namespace network sample")
            rx_bytes = _nonnegative_int(parts[1], "namespace rx bytes")
            tx_bytes = _nonnegative_int(parts[2], "namespace tx bytes")
        elif parts[0] == "ERROR" and len(parts) >= 3:
            errors.append(" ".join(parts[1:]))
        else:
            errors.append(f"unrecognized batch output line {line!r}")
    expected = set(target.pids)
    observed = set(processes) | gone_pids
    if observed != expected or set(processes) & gone_pids:
        errors.append(f"proc sample pids do not match explicit target: expected={sorted(expected)} observed={sorted(observed)}")
    if set(cluster_counters) != set(processes):
        errors.append(
            f"cluster samples do not match live proc targets: expected={sorted(processes)} observed={sorted(cluster_counters)}"
        )
    if set(non_connected_cluster_links) - set(processes):
        errors.append(
            "cluster link observations are not bound to live proc targets: "
            f"{sorted(set(non_connected_cluster_links) - set(processes))}"
        )
    reappeared = {
        _process_identity(target, pid)
        for pid in processes
        if _process_identity(target, pid) in previously_gone_processes
    }
    if reappeared:
        errors.append(
            "expected-gone owned processes reappeared after disappearance: "
            f"{_identity_rows(reappeared)}"
        )
    expected_ports = dict(zip(target.pids, target.client_ports))
    for pid, counters in cluster_counters.items():
        if counters["client_port"] != expected_ports.get(pid):
            errors.append(f"cluster sample for pid {pid} used an unowned client_port")
        if counters["cluster_link_count"] < 1:
            errors.append(f"cluster sample for pid {pid} did not observe any CLUSTER NODES links")
    if clock_ticks <= 0 or page_size <= 0:
        errors.append("batch sample is missing clock tick or page size metadata")
    if rx_bytes is None or tx_bytes is None:
        errors.append("batch sample is missing namespace network counters")
    if errors:
        raise M2ResourceMeasurementError("; ".join(errors))

    logical_by_pid = dict(zip(target.pids, target.logical_ids))
    return {
        "nodehost_id": target.nodehost_id,
        "container_id": target.container_id,
        "container_name": target.container_name,
        "ownership_id": target.ownership_id,
        "clock_ticks_per_second": clock_ticks,
        "page_size_bytes": page_size,
        "processes": [
            {
                "logical_id": logical_by_pid[pid],
                "pid": pid,
                "cpu_ticks": processes[pid]["cpu_ticks"],
                "rss_bytes": processes[pid]["rss_pages"] * page_size,
                "fd_count": processes[pid]["fd_count"],
                "connection_count": processes[pid]["connection_count"],
                "client_port": cluster_counters[pid]["client_port"],
                "cluster_stats_bytes_sent": cluster_counters[pid]["bytes_sent"],
                "cluster_stats_bytes_received": cluster_counters[pid]["bytes_received"],
                "cluster_stats_messages_sent": cluster_counters[pid]["messages_sent"],
                "cluster_stats_messages_received": cluster_counters[pid]["messages_received"],
                "total_cluster_links_buffer_limit_exceeded": cluster_counters[pid]["buffer_overflows"],
                "cluster_link_count": cluster_counters[pid]["cluster_link_count"],
                "cluster_link_errors": cluster_counters[pid]["cluster_link_errors"],
                "non_connected_cluster_link_count": cluster_counters[pid]["non_connected_cluster_link_count"],
                "non_connected_cluster_links": non_connected_cluster_links.get(pid, []),
            }
            for pid in target.pids
            if pid in processes
        ],
        "gone_pids": sorted(gone_pids),
        "namespace_network": {
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "scope": "controlled-window container namespace",
        },
    }


def _cluster_link_errors_from_raw(
    process: Mapping[str, Any],
    *,
    expected_gone_client_ports: set[int],
    previous_process: Mapping[str, Any] | None = None,
    next_process: Mapping[str, Any] | None = None,
    allow_initial_membership_transition: bool = False,
) -> int:
    logical_id = process.get("logical_id", MISSING)
    observations = process.get("non_connected_cluster_links")
    if not isinstance(observations, list):
        raise M2ResourceMeasurementError(
            f"cluster sample for {logical_id} is missing raw non-connected CLUSTER NODES rows"
        )
    observed_count = process.get("non_connected_cluster_link_count")
    if not _valid_nonnegative_int(observed_count) or observed_count != len(observations):
        raise M2ResourceMeasurementError(
            f"cluster sample for {logical_id} non-connected link count does not match raw links: "
            f"claimed={observed_count!r} observed={len(observations)}"
        )
    errors = 0
    claimed_errors = 0
    for position, observation in enumerate(observations):
        if not isinstance(observation, dict):
            raise M2ResourceMeasurementError(
                f"cluster sample for {logical_id} raw link {position} must be an object"
            )
        node_id = observation.get("node_id")
        address = observation.get("address")
        flags = observation.get("flags")
        master_id = observation.get("master_id")
        link_state = observation.get("link_state")
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(address, str)
            or not address
            or not isinstance(flags, list)
            or not flags
            or any(not isinstance(flag, str) or not flag for flag in flags)
            or len(set(flags)) != len(flags)
            or not isinstance(master_id, str)
            or not master_id
            or not isinstance(link_state, str)
            or not link_state
        ):
            raise M2ResourceMeasurementError(
                f"cluster sample for {logical_id} raw link {position} is incomplete"
            )
        if link_state == "connected":
            raise M2ResourceMeasurementError(
                f"cluster sample for {logical_id} raw non-connected link {position} is connected"
            )
        flag_set = set(flags)
        client_port = _cluster_link_client_port(address)
        valid_node_id = _valid_cluster_node_id(node_id)
        recognized_disconnected = (
            link_state == "disconnected"
            and flag_set <= _CLUSTER_NODE_FLAGS
            and "noaddr" not in flag_set
            and not ("noflags" in flag_set and len(flag_set) != 1)
            and valid_node_id
            and (master_id == "-" or _valid_cluster_node_id(master_id))
            and client_port is not None
        )
        if not recognized_disconnected:
            claimed_errors += 1
            errors += 1
            continue
        role_flags = flag_set & _CLUSTER_ROLE_FLAGS
        primary_link = role_flags == {"master"} and master_id == "-"
        replica_link = role_flags == {"slave"} and _valid_cluster_node_id(master_id)
        expected_gone_link = (
            client_port in expected_gone_client_ports
            and (primary_link or replica_link)
            and not flag_set.intersection({"myself", "handshake", "noflags"})
            and not {"fail?", "fail"} <= flag_set
            and ("nofailover" not in flag_set or replica_link)
        )
        if expected_gone_link:
            continue
        # HANDSHAKE is self-contained proof; role rows need cross-sample topology proof below.
        pending_handshake = (
            flag_set == {"handshake"}
            and master_id == "-"
        )
        if pending_handshake:
            continue
        claimed_errors += 1
        previous_link_count = (
            previous_process.get("cluster_link_count")
            if isinstance(previous_process, Mapping)
            else None
        )
        next_observations = (
            next_process.get("non_connected_cluster_links")
            if isinstance(next_process, Mapping)
            else None
        )
        initial_membership_transition = (
            allow_initial_membership_transition
            and previous_link_count == 1
            and previous_process.get("non_connected_cluster_link_count") == 0
            and previous_process.get("non_connected_cluster_links") == []
            and _valid_positive_int(process.get("cluster_link_count"))
            and process["cluster_link_count"] > previous_link_count
            and (primary_link or replica_link)
            and (flag_set == {"master"} or flag_set == {"slave"})
            and isinstance(next_process, Mapping)
            and next_process.get("pid") == process.get("pid")
            and isinstance(next_observations, list)
            and all(
                isinstance(next_observation, Mapping)
                and next_observation.get("node_id") != node_id
                for next_observation in next_observations
            )
        )
        if not initial_membership_transition:
            errors += 1
    claimed = process.get("cluster_link_errors")
    if not _valid_nonnegative_int(claimed) or claimed != claimed_errors:
        raise M2ResourceMeasurementError(
            f"cluster sample for {logical_id} cluster_link_errors does not match raw links: "
            f"claimed={claimed!r} recomputed={claimed_errors}"
        )
    return errors


def _cluster_link_client_port(address: str) -> int | None:
    client_address, separator, bus_address = address.partition("@")
    if not separator or ":" not in client_address:
        return None
    host_text, port_text = client_address.rsplit(":", 1)
    bus_port_text = bus_address.split(",", 1)[0]
    if not port_text.isdigit() or not bus_port_text.isdigit():
        return None
    try:
        ipaddress.ip_address(host_text)
    except ValueError:
        return None
    port = int(port_text)
    bus_port = int(bus_port_text)
    return port if 0 < port <= 65535 and 0 < bus_port <= 65535 else None


def _valid_cluster_node_id(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value.lower())


def _resource_report(
    *,
    status: str,
    summary: str,
    window_name: str,
    duration_seconds: Any,
    interval_seconds: Any,
    expected_samples: int,
    targets: list[_Target],
    samples: list[dict[str, Any]],
    errors: list[str],
    expected_gone_processes: set[_ProcessIdentity] | None = None,
    captured_processes: set[_ProcessIdentity] | None = None,
    observed_gone_processes: set[_ProcessIdentity] | None = None,
) -> dict[str, Any]:
    expected_gone = expected_gone_processes or set()
    captured = captured_processes or set()
    observed_gone = observed_gone_processes or set()
    expected_gone_client_ports = {
        port
        for target in targets
        for pid, port in zip(target.pids, target.client_ports)
        if _process_identity(target, pid) in expected_gone
    }
    complete_samples = [sample for sample in samples if sample.get("status") == "PASS"]
    complete = status == "PASS" and len(complete_samples) == expected_samples and expected_samples > 0
    metrics: dict[str, int | float | str] = {
        "peak_rss_bytes": MISSING,
        "cpu_time_seconds": MISSING,
        "fd_count": MISSING,
        "connection_count": MISSING,
        "cluster_bus_bytes": MISSING,
        "cluster_link_errors": MISSING,
        "buffer_overflows": MISSING,
    }
    diagnostics: dict[str, int | str] = {
        "cluster_bus_messages": MISSING,
        "namespace_network_bytes": MISSING,
    }
    if complete:
        try:
            metrics, diagnostics = _aggregate_samples(
                complete_samples,
                expected_gone_client_ports=expected_gone_client_ports,
                allow_initial_membership_transitions=(
                    window_name == "m2-formation-bootstrap"
                ),
            )
        except M2ResourceMeasurementError as exc:
            status = "FAIL"
            complete = False
            errors.append(str(exc))
    return {
        "schema_version": "v1",
        "artifact_type": "m2_resource_window",
        "status": status,
        "summary": summary if status == "PASS" else "M2 resource window is incomplete or invalid",
        "window_name": _required_text(window_name, "window_name") if isinstance(window_name, str) and window_name.strip() else MISSING,
        "duration_seconds": _finite_number_or_missing(duration_seconds),
        "interval_seconds": _finite_number_or_missing(interval_seconds),
        "clock_source": "injected_wall_unix_ms_and_monotonic_seconds",
        "ownership": {
            "project": PROJECT,
            "ownership_ids": sorted({target.ownership_id for target in targets}),
            "container_ids": [target.container_id for target in targets],
            "pids": [pid for target in targets for pid in target.pids],
            "client_ports": [port for target in targets for port in target.client_ports],
        },
        "fault_target_capture": {
            "expected_gone_processes": _identity_rows(expected_gone),
            "observed_gone_processes": _identity_rows(observed_gone),
            "captured_before_gone_processes": _identity_rows(expected_gone & captured & observed_gone),
            "binding_status": (
                "PASS"
                if expected_gone <= {
                    _process_identity(target, pid) for target in targets for pid in target.pids
                }
                else "FAIL"
            ),
            "bindings": [
                {
                    "pid": pid,
                    "logical_id": logical_id,
                    "client_port": port,
                    "nodehost_id": target.nodehost_id,
                    "container_id": target.container_id,
                    "ownership_id": target.ownership_id,
                }
                for target in targets
                for pid, logical_id, port in zip(target.pids, target.logical_ids, target.client_ports)
                if _process_identity(target, pid) in expected_gone
            ],
        },
        "coverage": {
            "complete": complete,
            "expected_sample_count": expected_samples,
            "observed_sample_count": len(complete_samples),
            "nodehost_count": len(targets),
            "process_count": sum(len(target.pids) for target in targets),
            "sample_timestamps_unix_ms": [sample["timestamp_unix_ms"] for sample in samples],
            "sample_monotonic_seconds": [sample["started_at_monotonic_seconds"] for sample in samples],
            "scheduled_offsets_seconds": [sample["scheduled_offset_seconds"] for sample in samples],
            **_window_bounds(
                samples[1:]
                if samples and samples[0].get("sample_phase") == "pre_barrier"
                else samples
            ),
        },
        "metrics": metrics,
        "diagnostics": diagnostics,
        "metric_provenance": {
            "peak_rss_bytes": "peak sum of explicit owned PID /proc/<pid>/statm RSS",
            "cpu_time_seconds": "sum of explicit owned PID /proc/<pid>/stat utime+stime deltas divided by CLK_TCK",
            "fd_count": "peak count of explicit owned PID /proc/<pid>/fd entries",
            "connection_count": "peak count of socket symlinks in explicit owned PID /proc/<pid>/fd",
            "cluster_bus_bytes": "exact Valkey 9.1 per-node CLUSTER INFO cluster_stats_bytes_sent plus cluster_stats_bytes_received counter deltas; no namespace-traffic fallback",
            "cluster_link_errors": "maximum raw-derived unexpected disconnected-link count after excluding well-formed pre-establishment handshake rows, the first role-row topology expansion from a singleton observer when the peer is absent from the next complete formation-bootstrap sample, and explicitly PID-bound expected fault-target client ports",
            "buffer_overflows": "exact per-node CLUSTER INFO total_cluster_links_buffer_limit_exceeded counter deltas",
        },
        "diagnostic_provenance": {
            "cluster_bus_messages": "exact per-node CLUSTER INFO messages sent plus received counter deltas",
            "namespace_network_bytes": "controlled-window namespace /proc/net/dev byte delta; diagnostic only, never cluster-bus admission evidence",
        },
        "samples": samples,
        "errors": errors,
    }


def _aggregate_samples(
    samples: list[dict[str, Any]],
    *,
    expected_gone_client_ports: set[int],
    allow_initial_membership_transitions: bool = False,
) -> tuple[dict[str, int | float], dict[str, int]]:
    rss_totals: list[int] = []
    fd_totals: list[int] = []
    connection_totals: list[int] = []
    network_totals: list[int] = []
    link_error_totals: list[int] = []
    process_history: dict[str, list[tuple[dict[str, Any], int]]] = {}
    previous_processes: dict[str, dict[str, Any]] = {}
    for sample_index, sample in enumerate(samples):
        next_processes = (
            {
                process["logical_id"]: process
                for nodehost in samples[sample_index + 1]["nodehosts"]
                for process in nodehost["processes"]
            }
            if sample_index + 1 < len(samples)
            else {}
        )
        rss = 0
        fds = 0
        connections = 0
        network = 0
        link_errors = 0
        for nodehost in sample["nodehosts"]:
            hz = nodehost["clock_ticks_per_second"]
            if hz <= 0:
                raise M2ResourceMeasurementError("clock tick metadata must be positive")
            for process in nodehost["processes"]:
                rss += process["rss_bytes"]
                fds += process["fd_count"]
                connections += process["connection_count"]
                logical_id = process["logical_id"]
                prior_history = process_history.setdefault(logical_id, [])
                if prior_history and prior_history[-1][0]["pid"] != process["pid"]:
                    raise M2ResourceMeasurementError(f"owned pid changed for {logical_id} inside the resource window")
                link_errors += _cluster_link_errors_from_raw(
                    process,
                    expected_gone_client_ports=expected_gone_client_ports,
                    previous_process=previous_processes.get(logical_id),
                    next_process=next_processes.get(logical_id),
                    allow_initial_membership_transition=(
                        allow_initial_membership_transitions
                        and bool(prior_history)
                        and all(
                            prior_process.get("cluster_link_count") == 1
                            for prior_process, _ in prior_history
                        )
                    ),
                )
                prior_history.append((process, hz))
                previous_processes[logical_id] = process
            network += nodehost["namespace_network"]["rx_bytes"] + nodehost["namespace_network"]["tx_bytes"]
        rss_totals.append(rss)
        fd_totals.append(fds)
        connection_totals.append(connections)
        network_totals.append(network)
        link_error_totals.append(link_errors)
    network_delta = network_totals[-1] - network_totals[0]
    if network_delta < 0:
        raise M2ResourceMeasurementError("namespace network counters decreased inside the resource window")
    if not process_history:
        raise M2ResourceMeasurementError("resource window has no captured owned PID counters")
    counter_fields = (
        "cpu_ticks",
        "cluster_stats_bytes_sent",
        "cluster_stats_bytes_received",
        "cluster_stats_messages_sent",
        "cluster_stats_messages_received",
        "total_cluster_links_buffer_limit_exceeded",
    )
    cpu_time_seconds = 0.0
    cluster_bus_bytes = 0
    cluster_bus_messages = 0
    buffer_overflows = 0
    for logical_id, observations in sorted(process_history.items()):
        if any(hz != observations[0][1] for _, hz in observations):
            raise M2ResourceMeasurementError(f"clock tick metadata changed for {logical_id}")
        for field in counter_fields:
            values = [process[field] for process, _ in observations]
            if any(current < previous for previous, current in zip(values, values[1:])):
                raise M2ResourceMeasurementError(f"{logical_id} counter {field} decreased inside the resource window")
        first = observations[0][0]
        last = observations[-1][0]
        cpu_time_seconds += (last["cpu_ticks"] - first["cpu_ticks"]) / observations[0][1]
        cluster_bus_bytes += (last["cluster_stats_bytes_sent"] - first["cluster_stats_bytes_sent"]) + (
            last["cluster_stats_bytes_received"] - first["cluster_stats_bytes_received"]
        )
        cluster_bus_messages += (last["cluster_stats_messages_sent"] - first["cluster_stats_messages_sent"]) + (
            last["cluster_stats_messages_received"] - first["cluster_stats_messages_received"]
        )
        buffer_overflows += last["total_cluster_links_buffer_limit_exceeded"] - first[
            "total_cluster_links_buffer_limit_exceeded"
        ]
    return (
        {
            "peak_rss_bytes": max(rss_totals),
            "cpu_time_seconds": round(cpu_time_seconds, 6),
            "fd_count": max(fd_totals),
            "connection_count": max(connection_totals),
            "cluster_bus_bytes": cluster_bus_bytes,
            "cluster_link_errors": max(link_error_totals),
            "buffer_overflows": buffer_overflows,
        },
        {
            "cluster_bus_messages": cluster_bus_messages,
            "namespace_network_bytes": network_delta,
        },
    )


def _schedule_lag_limit(interval_seconds: float) -> float:
    return min(MAX_SCHEDULE_LAG_SECONDS, max(0.001, interval_seconds * MAX_SCHEDULE_LAG_FRACTION))


def _fixed_window_timing_errors(
    samples: list[dict[str, Any]],
    duration_seconds: float,
    interval_seconds: float,
) -> list[str]:
    if not samples:
        return ["fixed resource window has no samples"]
    timing_errors: list[str] = []
    lag_limit = _schedule_lag_limit(interval_seconds)
    try:
        scheduled = [float(sample["scheduled_at_monotonic_seconds"]) for sample in samples]
        starts = [float(sample["started_at_monotonic_seconds"]) for sample in samples]
        ends = [float(sample["ended_at_monotonic_seconds"]) for sample in samples]
        lags = [float(sample["schedule_lag_seconds"]) for sample in samples]
    except (KeyError, TypeError, ValueError):
        return ["fixed resource window has incomplete monotonic timing"]
    if any(not math.isfinite(value) for value in [*scheduled, *starts, *ends, *lags]):
        return ["fixed resource window has non-finite monotonic timing"]
    if max(lags) > lag_limit + 1e-6:
        timing_errors.append(
            f"resource schedule lag exceeds fixed-window limit {round(lag_limit, 6)} seconds"
        )
    if max(end - start for start, end in zip(starts, ends)) > interval_seconds + 1e-6:
        timing_errors.append("resource sample collection overran its fixed interval")
    actual_span = starts[-1] - starts[0]
    if not math.isclose(actual_span, duration_seconds, rel_tol=0.0, abs_tol=lag_limit + 1e-6):
        timing_errors.append("resource sample starts do not span the complete fixed window")
    return timing_errors


def _window_bounds(samples: list[dict[str, Any]]) -> dict[str, int | float | str]:
    fields = (
        "actual_window_start_monotonic_seconds",
        "actual_window_end_monotonic_seconds",
        "actual_window_span_seconds",
        "sampling_envelope_end_monotonic_seconds",
        "sampling_envelope_span_seconds",
        "max_schedule_lag_seconds",
        "max_sample_collection_seconds",
    )
    if not samples or any(not isinstance(sample, dict) for sample in samples):
        return {field: MISSING for field in fields}
    starts = [sample.get("started_at_monotonic_seconds") for sample in samples]
    ends = [sample.get("ended_at_monotonic_seconds") for sample in samples]
    lags = [sample.get("schedule_lag_seconds") for sample in samples]
    values = [*starts, *ends, *lags]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in values
    ):
        return {field: MISSING for field in fields}
    start = float(starts[0])
    endpoint = float(starts[-1])
    envelope_end = float(ends[-1])
    durations = [float(end) - float(sample_start) for sample_start, end in zip(starts, ends)]
    return {
        "actual_window_start_monotonic_seconds": round(start, 6),
        "actual_window_end_monotonic_seconds": round(endpoint, 6),
        "actual_window_span_seconds": round(endpoint - start, 6),
        "sampling_envelope_end_monotonic_seconds": round(envelope_end, 6),
        "sampling_envelope_span_seconds": round(envelope_end - start, 6),
        "max_schedule_lag_seconds": round(max(float(value) for value in lags), 6),
        "max_sample_collection_seconds": round(max(durations), 6),
    }


def _process_identity(target: _Target, pid: int) -> _ProcessIdentity:
    return target.nodehost_id, target.container_id, pid


def _identity_row(identity: _ProcessIdentity) -> dict[str, Any]:
    nodehost_id, container_id, pid = identity
    return {"nodehost_id": nodehost_id, "container_id": container_id, "pid": pid}


def _identity_rows(identities: Any) -> list[dict[str, Any]]:
    return [_identity_row(identity) for identity in sorted(identities)]


def _process_identity_list(value: Any, label: str, errors: list[str]) -> list[_ProcessIdentity]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    identities: list[_ProcessIdentity] = []
    for position, row in enumerate(value):
        if not isinstance(row, dict):
            errors.append(f"{label}[{position}] must be an object")
            continue
        nodehost_id = row.get("nodehost_id")
        container_id = row.get("container_id")
        pid = row.get("pid")
        if (
            not isinstance(nodehost_id, str)
            or not nodehost_id
            or not isinstance(container_id, str)
            or not container_id
            or not _valid_positive_int(pid)
        ):
            errors.append(f"{label}[{position}] must contain nodehost_id, container_id, and positive pid")
            continue
        identities.append((nodehost_id, container_id, pid))
    if len(set(identities)) != len(identities):
        errors.append(f"{label} must not contain duplicate process identities")
    return identities


def _positive_claim(value: Any, label: str, errors: list[str]) -> int | None:
    if not _valid_positive_int(value):
        errors.append(f"{label} must be a positive integer")
        return None
    return value


def _positive_int_list(
    value: Any,
    label: str,
    errors: list[str],
    *,
    unique: bool = True,
) -> list[int]:
    if not isinstance(value, list):
        errors.append(f"{label} must be an array")
        return []
    if any(not _valid_positive_int(item) for item in value):
        errors.append(f"{label} must contain positive integers")
        return []
    if unique and len(set(value)) != len(value):
        errors.append(f"{label} must not contain duplicates")
    return list(value)


def _text_list(value: Any, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        errors.append(f"{label} must be a non-empty text array")
        return []
    if len(set(value)) != len(value):
        errors.append(f"{label} must not contain duplicates")
    return list(value)


def _valid_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _valid_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_resource_process(process: dict[str, Any]) -> bool:
    if (
        not _valid_positive_int(process.get("client_port"))
        or not _valid_positive_int(process.get("cluster_link_count"))
        or not _valid_nonnegative_int(process.get("non_connected_cluster_link_count"))
        or not isinstance(process.get("non_connected_cluster_links"), list)
    ):
        return False
    return all(
        _valid_nonnegative_int(process.get(field))
        for field in (
            "cpu_ticks",
            "rss_bytes",
            "fd_count",
            "connection_count",
            "cluster_stats_bytes_sent",
            "cluster_stats_bytes_received",
            "cluster_stats_messages_sent",
            "cluster_stats_messages_received",
            "total_cluster_links_buffer_limit_exceeded",
            "cluster_link_errors",
        )
    )


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value in {MISSING, "SKIPPED_WITH_REASON", "UNSUPPORTED_WITH_REASON"}:
        raise M2ResourceMeasurementError(f"{label} must be present")
    return value.strip()


def _positive_int(value: str, label: str) -> int:
    parsed = _nonnegative_int(value, label)
    if parsed <= 0:
        raise M2ResourceMeasurementError(f"{label} must be positive")
    return parsed


def _nonnegative_int(value: str, label: str) -> int:
    if not value.isdigit():
        raise M2ResourceMeasurementError(f"{label} must be a non-negative integer")
    return int(value)


def _same_container_id(left: str, right: str) -> bool:
    return bool(left and right and (left.startswith(right) or right.startswith(left)))


def _same_number(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    return math.isfinite(float(left)) and math.isfinite(float(right)) and math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=1e-9
    )


def _finite_number_or_missing(value: Any) -> int | float | str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return MISSING
    return value
