from __future__ import annotations

import os
import resource
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from valkey_scale_lab.observability.contracts import CollectionError

HOST_INTERVAL_SECONDS = 5.0
PROCESS_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class ProcessSpec:
    logical_id: str
    pid: int


@dataclass(frozen=True)
class ExpectedGoneProcess:
    logical_id: str
    pid: int


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CollectionError(f"cannot read {path}: {exc}") from exc


def _key_values(text: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, rest = line.partition(":")
        if not separator:
            continue
        parts = rest.split()
        if not parts:
            continue
        value = int(parts[0])
        if len(parts) > 1 and parts[1].lower() == "kb":
            value *= 1024
        result[key] = value
    return result


class LocalResourceSampler:
    """Reads local procfs/cgroupfs only; it never issues a Valkey command."""

    def __init__(
        self,
        *,
        sampler_id: str,
        processes: Sequence[ProcessSpec],
        proc_root: Path = Path("/proc"),
        cgroup_root: Path = Path("/sys/fs/cgroup"),
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        expected_gone_processes: Sequence[ExpectedGoneProcess] = (),
        expected_gone_active: Callable[[], bool] | None = None,
    ) -> None:
        self.sampler_id = sampler_id
        self.processes = tuple(processes)
        self.proc_root = proc_root
        self.cgroup_root = cgroup_root
        self._wall = wall_clock
        self._monotonic = monotonic
        self._expected_gone = {
            (process.logical_id, process.pid) for process in expected_gone_processes
        }
        self._expected_gone_active = expected_gone_active or (lambda: False)
        self._process_start_times: dict[tuple[str, int], int] = {}
        self._self_cpu_started = time.process_time()

    def static(self) -> dict[str, Any]:
        meminfo = _key_values(_read(self.proc_root / "meminfo"))
        interfaces = _network_interfaces(_read(self.proc_root / "net" / "dev"))
        return {
            "sampler_id": self.sampler_id,
            "cpu_count": os.cpu_count() or 1,
            "mem_total_bytes": meminfo.get("MemTotal"),
            "swap_total_bytes": meminfo.get("SwapTotal"),
            "cgroup_limits": self._cgroup_limits(),
            "network_interfaces": interfaces,
        }

    def host_sample(self) -> dict[str, Any]:
        started = self._monotonic()
        cpu, scheduler = self._cpu_and_scheduler()
        memory = _key_values(_read(self.proc_root / "meminfo"))
        network = self._network()
        cgroup = self._cgroup_dynamic()
        duration = max(self._monotonic() - started, 0.0)
        return {
            "kind": "host",
            "sampler_id": self.sampler_id,
            "wall_time": self._wall(),
            "monotonic": started,
            "cpu": cpu,
            "scheduler": scheduler,
            "memory": {
                "mem_available_bytes": memory.get("MemAvailable"),
                "swap_used_bytes": max(
                    memory.get("SwapTotal", 0) - memory.get("SwapFree", 0), 0
                ),
            },
            "cgroup": cgroup,
            "network": network,
            "collector": self._collector_metrics(duration),
        }

    def process_sample(self) -> dict[str, Any]:
        started = self._monotonic()
        rows: list[dict[str, Any]] = []
        for process in self.processes:
            stat, error = self._sample_process(process)
            if error is None:
                rows.append(
                    {
                        "logical_id": process.logical_id,
                        "pid": process.pid,
                        "status": "OK",
                        **stat,
                    }
                )
                continue
            key = (process.logical_id, process.pid)
            if key in self._expected_gone and self._expected_gone_active():
                rows.append(
                    {
                        "logical_id": process.logical_id,
                        "pid": process.pid,
                        "status": "EXPECTED_GONE",
                        "reason": str(error),
                    }
                )
                continue
            raise error
        duration = max(self._monotonic() - started, 0.0)
        return {
            "kind": "process",
            "sampler_id": self.sampler_id,
            "wall_time": self._wall(),
            "monotonic": started,
            "processes": rows,
            "collector": self._collector_metrics(duration),
        }

    def _sample_process(
        self, process: ProcessSpec
    ) -> tuple[dict[str, Any], CollectionError | None]:
        try:
            stat = self._process_stat(process)
            key = (process.logical_id, process.pid)
            previous_start = self._process_start_times.setdefault(
                key, int(stat["start_time_ticks"])
            )
            if int(stat["start_time_ticks"]) != previous_start:
                raise CollectionError(
                    f"process identity changed for {process.logical_id} pid {process.pid}"
                )
            fd_count = self._fd_count(process.pid)
            confirmed = self._process_stat(process)
            if confirmed["start_time_ticks"] != stat["start_time_ticks"]:
                raise CollectionError(
                    f"process identity changed while sampling {process.logical_id} "
                    f"pid {process.pid}"
                )
            return {**stat, "fd_count": fd_count}, None
        except CollectionError as exc:
            return {}, exc

    def _cpu_and_scheduler(self) -> tuple[dict[str, int], dict[str, int]]:
        return _cpu_and_scheduler_from_text(_read(self.proc_root / "stat"))

    def _network(self) -> dict[str, dict[str, int]]:
        return _network_from_text(_read(self.proc_root / "net" / "dev"))

    def _process_stat(self, process: ProcessSpec) -> dict[str, Any]:
        raw = _read(self.proc_root / str(process.pid) / "stat").strip()
        return _process_stat_from_text(raw, process)

    def _fd_count(self, pid: int) -> int:
        try:
            with os.scandir(self.proc_root / str(pid) / "fd") as entries:
                return sum(1 for _ in entries)
        except OSError as exc:
            raise CollectionError(f"cannot count fd entries for pid {pid}: {exc}") from exc

    def _cgroup_limits(self) -> dict[str, Any]:
        return {
            "cpu_max": self._optional_cgroup_text("cpu.max"),
            "memory_max": self._optional_cgroup_number("memory.max"),
        }

    def _cgroup_dynamic(self) -> dict[str, Any]:
        return _cgroup_dynamic_from_values(
            cpu_stat=self._optional_cgroup_key_values("cpu.stat"),
            memory_events=self._optional_cgroup_key_values("memory.events"),
            memory_current=self._optional_cgroup_number("memory.current"),
            memory_max=self._optional_cgroup_number("memory.max"),
        )

    def _optional_cgroup_text(self, name: str) -> str | None:
        try:
            return (self.cgroup_root / name).read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def _optional_cgroup_number(self, name: str) -> int | None:
        value = self._optional_cgroup_text(name)
        if value in {None, "max"}:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _optional_cgroup_key_values(self, name: str) -> dict[str, int]:
        return _optional_cgroup_key_values_from_text(self._optional_cgroup_text(name))

    def _collector_metrics(self, duration: float) -> dict[str, Any]:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return {
            "cpu_time_seconds": max(time.process_time() - self._self_cpu_started, 0.0),
            "rss_bytes": int(usage.ru_maxrss)
            * (1024 if os.uname().sysname != "Darwin" else 1),
            "sample_duration_seconds": duration,
            "overrun_seconds": max(duration - HOST_INTERVAL_SECONDS, 0.0),
        }


class NodehostResourceSampler(LocalResourceSampler):
    """Parses one pre-collected nodehost snapshot per resource sample."""

    def __init__(
        self,
        *,
        sampler_id: str,
        processes: Sequence[ProcessSpec],
        static_snapshot: Callable[[], Mapping[str, Any]],
        host_snapshot: Callable[[], Mapping[str, Any]],
        process_snapshot: Callable[[Sequence[ProcessSpec]], Mapping[str, Any]],
        wall_clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        expected_gone_processes: Sequence[ExpectedGoneProcess] = (),
        expected_gone_active: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(
            sampler_id=sampler_id,
            processes=processes,
            wall_clock=wall_clock,
            monotonic=monotonic,
            expected_gone_processes=expected_gone_processes,
            expected_gone_active=expected_gone_active,
        )
        self._static_snapshot = static_snapshot
        self._host_snapshot = host_snapshot
        self._process_snapshot = process_snapshot

    def static(self) -> dict[str, Any]:
        snapshot = self._static_snapshot()
        meminfo = _key_values(_required_text(snapshot, "meminfo"))
        return {
            "sampler_id": self.sampler_id,
            "cpu_count": _positive_int(snapshot.get("cpu_count"), "cpu_count"),
            "mem_total_bytes": meminfo.get("MemTotal"),
            "swap_total_bytes": meminfo.get("SwapTotal"),
            "cgroup_limits": {
                "cpu_max": _optional_text(snapshot.get("cgroup_cpu_max")),
                "memory_max": _optional_number(snapshot.get("cgroup_memory_max")),
            },
            "network_interfaces": _network_interfaces(
                _required_text(snapshot, "net_dev")
            ),
        }

    def host_sample(self) -> dict[str, Any]:
        started = self._monotonic()
        snapshot = self._host_snapshot()
        cpu, scheduler = _cpu_and_scheduler_from_text(
            _required_text(snapshot, "proc_stat")
        )
        memory = _key_values(_required_text(snapshot, "meminfo"))
        network = _network_from_text(_required_text(snapshot, "net_dev"))
        cgroup = _cgroup_dynamic_from_values(
            cpu_stat=_optional_cgroup_key_values_from_text(
                _optional_text(snapshot.get("cgroup_cpu_stat"))
            ),
            memory_events=_optional_cgroup_key_values_from_text(
                _optional_text(snapshot.get("cgroup_memory_events"))
            ),
            memory_current=_optional_number(snapshot.get("cgroup_memory_current")),
            memory_max=_optional_number(snapshot.get("cgroup_memory_max")),
        )
        duration = max(self._monotonic() - started, 0.0)
        return {
            "kind": "host",
            "sampler_id": self.sampler_id,
            "wall_time": self._wall(),
            "monotonic": started,
            "cpu": cpu,
            "scheduler": scheduler,
            "memory": {
                "mem_available_bytes": memory.get("MemAvailable"),
                "swap_used_bytes": max(
                    memory.get("SwapTotal", 0) - memory.get("SwapFree", 0), 0
                ),
            },
            "cgroup": cgroup,
            "network": network,
            "collector": self._collector_metrics(duration),
        }

    def process_sample(self) -> dict[str, Any]:
        started = self._monotonic()
        snapshot = self._process_snapshot(self.processes)
        page_size = _positive_int(snapshot.get("page_size"), "page_size")
        raw_rows = snapshot.get("processes")
        if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
            raise CollectionError("process snapshot did not return process rows")
        by_identity: dict[tuple[str, int], Mapping[str, Any]] = {}
        for raw_row in raw_rows:
            if not isinstance(raw_row, Mapping):
                raise CollectionError("process snapshot row is not a mapping")
            logical_id = str(raw_row.get("logical_id", ""))
            try:
                pid = int(raw_row.get("pid"))
            except (TypeError, ValueError) as exc:
                raise CollectionError("process snapshot row has invalid pid") from exc
            key = (logical_id, pid)
            if key in by_identity:
                raise CollectionError(
                    f"process snapshot returned duplicate row for {logical_id} pid {pid}"
                )
            by_identity[key] = raw_row
        expected = {(process.logical_id, process.pid) for process in self.processes}
        missing = expected.difference(by_identity)
        extras = set(by_identity).difference(expected)
        if missing or extras:
            raise CollectionError(
                "process snapshot coverage mismatch: "
                f"missing={sorted(missing)} extras={sorted(extras)}"
            )
        rows: list[dict[str, Any]] = []
        for process in self.processes:
            raw_row = by_identity[(process.logical_id, process.pid)]
            stat, error = self._sample_snapshot_process(process, raw_row, page_size)
            if error is None:
                rows.append(
                    {
                        "logical_id": process.logical_id,
                        "pid": process.pid,
                        "status": "OK",
                        **stat,
                    }
                )
                continue
            key = (process.logical_id, process.pid)
            if key in self._expected_gone and self._expected_gone_active():
                rows.append(
                    {
                        "logical_id": process.logical_id,
                        "pid": process.pid,
                        "status": "EXPECTED_GONE",
                        "reason": str(error),
                    }
                )
                continue
            raise error
        duration = max(self._monotonic() - started, 0.0)
        return {
            "kind": "process",
            "sampler_id": self.sampler_id,
            "wall_time": self._wall(),
            "monotonic": started,
            "processes": rows,
            "collector": self._collector_metrics(duration),
        }

    def _sample_snapshot_process(
        self, process: ProcessSpec, raw_row: Mapping[str, Any], page_size: int
    ) -> tuple[dict[str, Any], CollectionError | None]:
        try:
            status = str(raw_row.get("status", ""))
            if status != "OK":
                raise CollectionError(
                    str(raw_row.get("error") or f"process {process.logical_id} is unavailable")
                )
            stat = _process_stat_from_text(
                _required_text(raw_row, "stat_before"),
                process,
                page_size=page_size,
            )
            key = (process.logical_id, process.pid)
            previous_start = self._process_start_times.setdefault(
                key, int(stat["start_time_ticks"])
            )
            if int(stat["start_time_ticks"]) != previous_start:
                raise CollectionError(
                    f"process identity changed for {process.logical_id} pid {process.pid}"
                )
            try:
                fd_count = int(raw_row.get("fd_count"))
            except (TypeError, ValueError) as exc:
                raise CollectionError(
                    f"invalid fd count for {process.logical_id} pid {process.pid}"
                ) from exc
            confirmed = _process_stat_from_text(
                _required_text(raw_row, "stat_after"),
                process,
                page_size=page_size,
            )
            if confirmed["start_time_ticks"] != stat["start_time_ticks"]:
                raise CollectionError(
                    f"process identity changed while sampling {process.logical_id} "
                    f"pid {process.pid}"
                )
            return {**stat, "fd_count": fd_count}, None
        except CollectionError as exc:
            return {}, exc


def _network_interfaces(text: str) -> list[str]:
    return [
        line.split(":", 1)[0].strip()
        for line in text.splitlines()
        if ":" in line and line.split(":", 1)[0].strip() != "lo"
    ]


def _cpu_and_scheduler_from_text(text: str) -> tuple[dict[str, int], dict[str, int]]:
    lines = text.splitlines()
    if not lines:
        raise CollectionError("procfs cpu counters are incomplete")
    cpu_parts = lines[0].split()
    if not cpu_parts or cpu_parts[0] != "cpu" or len(cpu_parts) < 9:
        raise CollectionError("procfs cpu counters are incomplete")
    values = [int(value) for value in cpu_parts[1:]]
    scheduler: dict[str, int] = {}
    for line in lines[1:]:
        key, _, value = line.partition(" ")
        if key in {"procs_running", "procs_blocked"}:
            scheduler[key] = int(value.strip())
    return (
        {
            "user": values[0] + values[1],
            "system": values[2] + values[5] + values[6],
            "idle": values[3],
            "iowait": values[4],
            "steal": values[7],
        },
        {
            "running": scheduler.get("procs_running", 0),
            "blocked": scheduler.get("procs_blocked", 0),
        },
    )


def _network_from_text(text: str) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, raw = line.split(":", 1)
        name = name.strip()
        if name == "lo":
            continue
        values = [int(value) for value in raw.split()]
        if len(values) < 16:
            raise CollectionError(f"network counters for {name} are incomplete")
        result[name] = {
            "rx_bytes": values[0],
            "rx_packets": values[1],
            "rx_errors": values[2],
            "rx_drops": values[3],
            "tx_bytes": values[8],
            "tx_packets": values[9],
            "tx_errors": values[10],
            "tx_drops": values[11],
        }
    return result


def _process_stat_from_text(
    raw: str, process: ProcessSpec, *, page_size: int | None = None
) -> dict[str, Any]:
    raw = raw.strip()
    close = raw.rfind(")")
    if close < 0:
        raise CollectionError(f"invalid stat for {process.logical_id}")
    fields = raw[close + 2 :].split()
    if len(fields) < 22:
        raise CollectionError(f"incomplete stat for {process.logical_id}")
    return {
        "state": fields[0],
        "user_cpu_ticks": int(fields[11]),
        "system_cpu_ticks": int(fields[12]),
        "start_time_ticks": int(fields[19]),
        "rss_bytes": int(fields[21]) * (page_size or os.sysconf("SC_PAGE_SIZE")),
    }


def _cgroup_dynamic_from_values(
    *,
    cpu_stat: Mapping[str, int],
    memory_events: Mapping[str, int],
    memory_current: int | None,
    memory_max: int | None,
) -> dict[str, Any]:
    return {
        "cpu_usage_usec": cpu_stat.get("usage_usec"),
        "cpu_throttled_usec": cpu_stat.get("throttled_usec"),
        "memory_current_bytes": memory_current,
        "memory_max_bytes": memory_max,
        "oom_count": memory_events.get("oom"),
        "oom_kill_count": memory_events.get("oom_kill"),
    }


def _optional_cgroup_key_values_from_text(text: str | None) -> dict[str, int]:
    if text is None:
        return {}
    result: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                result[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return result


def _required_text(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or value == "":
        raise CollectionError(f"snapshot is missing {name}")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _optional_number(value: Any) -> int | None:
    text = _optional_text(value)
    if text in {None, "max"}:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _positive_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise CollectionError(f"snapshot has invalid {name}") from exc
    if number <= 0:
        raise CollectionError(f"snapshot has invalid {name}")
    return number


class ResourceSamplerRunner:
    def __init__(
        self,
        sampler: LocalResourceSampler,
        *,
        host_interval: float = HOST_INTERVAL_SECONDS,
        process_interval: float = PROCESS_INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if host_interval != HOST_INTERVAL_SECONDS:
            raise ValueError("host resource interval must be 5 seconds")
        if process_interval != PROCESS_INTERVAL_SECONDS:
            raise ValueError("process resource interval must be 60 seconds")
        self.sampler = sampler
        self.host_interval = host_interval
        self.process_interval = process_interval
        self._sleep = sleep
        self._monotonic = monotonic
        self.static: dict[str, Any] | None = None
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = False
        self._host_thread: threading.Thread | None = None
        self._process_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._started:
            raise RuntimeError("resource sampler is already running")
        self._started = True
        try:
            self.static = self.sampler.static()
        except CollectionError as exc:
            with self._lock:
                self.errors.append(str(exc))
            self._stop.set()
            return
        self._host_thread = threading.Thread(
            target=self._run_host,
            name=f"resource-host-{self.sampler.sampler_id}",
            daemon=True,
        )
        self._process_thread = threading.Thread(
            target=self._run_process,
            name=f"resource-sampler-process-{self.sampler.sampler_id}",
            daemon=True,
        )
        self._host_thread.start()
        self._process_thread.start()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        for thread in (self._host_thread, self._process_thread):
            if thread is not None:
                thread.join(timeout=max(self.host_interval, self.process_interval) * 2)
                if thread.is_alive():
                    raise CollectionError("resource sampler did not stop")
        with self._lock:
            return {
                "static": self.static
                or {"sampler_id": self.sampler.sampler_id, "status": "MISSING"},
                "samples": list(self.samples),
                "errors": list(self.errors),
            }

    def _collect_once(self, operation: Callable[[], dict[str, Any]]) -> None:
        try:
            sample = operation()
            with self._lock:
                self.samples.append(sample)
            return
        except CollectionError as exc:
            last_error = exc
        with self._lock:
            self.errors.append(str(last_error))
        self._stop.set()

    def _run_host(self) -> None:
        next_host = self._monotonic()
        while not self._stop.is_set():
            now = self._monotonic()
            if now >= next_host:
                self._collect_once(self.sampler.host_sample)
                next_host = self._monotonic() + self.host_interval
            delay = next_host - self._monotonic()
            self._stop.wait(max(min(delay, self.host_interval), 0.01))

    def _run_process(self) -> None:
        next_process = self._monotonic()
        while not self._stop.is_set():
            now = self._monotonic()
            if now >= next_process:
                self._collect_once(self.sampler.process_sample)
                next_process = self._monotonic() + self.process_interval
            delay = next_process - self._monotonic()
            self._stop.wait(max(min(delay, self.process_interval), 0.01))


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _deltas(
    samples: Sequence[dict[str, Any]], selector: Callable[[dict[str, Any]], int | None]
) -> list[int]:
    values = [selector(sample) for sample in samples]
    numeric = [value for value in values if value is not None]
    return [
        max(right - left, 0)
        for left, right in zip(numeric, numeric[1:])
    ]


def _timeline_monotonic(event: Mapping[str, Any]) -> float | None:
    value = event.get("monotonic")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    value = event.get("monotonic_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    value = event.get("monotonic_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) / 1000.0
    for key in ("action_start", "signal_or_request_sent", "action_completed"):
        nested = event.get(key)
        if not isinstance(nested, Mapping):
            continue
        nested_value = nested.get("monotonic")
        if isinstance(nested_value, (int, float)) and not isinstance(
            nested_value, bool
        ):
            return float(nested_value)
    return None


def _event_overlaps(
    events: Sequence[Mapping[str, Any]], *, start: float, end: float
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in events:
        monotonic = _timeline_monotonic(event)
        if monotonic is None or monotonic < start or monotonic > end:
            continue
        result.append(
            {
                "event_type": event.get("event_type") or event.get("type"),
                "event_id": event.get("event_id") or event.get("id"),
                "monotonic": monotonic,
            }
        )
    return result


def analyze_resource_samples(
    static: Mapping[str, Any],
    samples: Sequence[dict[str, Any]],
    *,
    timeline_events: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    host = [sample for sample in samples if sample.get("kind") == "host"]
    process_samples = [
        sample for sample in samples if sample.get("kind") == "process"
    ]
    cpu_utilization: list[float] = []
    for left, right in zip(host, host[1:]):
        deltas = {
            key: max(int(right["cpu"][key]) - int(left["cpu"][key]), 0)
            for key in ("user", "system", "idle", "iowait", "steal")
        }
        total = sum(deltas.values())
        if total:
            cpu_utilization.append(
                100.0 * (total - deltas["idle"] - deltas["iowait"]) / total
            )
    memory_available = [
        int(sample["memory"]["mem_available_bytes"])
        for sample in host
        if sample["memory"].get("mem_available_bytes") is not None
    ]
    memory_current = [
        int(sample["cgroup"]["memory_current_bytes"])
        for sample in host
        if sample["cgroup"].get("memory_current_bytes") is not None
    ]
    memory_max = [
        int(sample["cgroup"]["memory_max_bytes"])
        for sample in host
        if sample["cgroup"].get("memory_max_bytes") is not None
    ]
    headroom = [
        limit - current
        for limit, current in zip(memory_max, memory_current)
        if limit >= current
    ]
    throttle_deltas = _deltas(
        host, lambda sample: sample["cgroup"].get("cpu_throttled_usec")
    )
    cpu_usage_deltas = _deltas(
        host, lambda sample: sample["cgroup"].get("cpu_usage_usec")
    )
    oom_deltas = _deltas(
        host, lambda sample: sample["cgroup"].get("oom_count")
    )
    oom_kill_deltas = _deltas(
        host, lambda sample: sample["cgroup"].get("oom_kill_count")
    )
    oom_events: list[dict[str, Any]] = []
    for left, right in zip(host, host[1:]):
        left_oom = left["cgroup"].get("oom_count")
        right_oom = right["cgroup"].get("oom_count")
        left_kill = left["cgroup"].get("oom_kill_count")
        right_kill = right["cgroup"].get("oom_kill_count")
        oom_delta = (
            max(int(right_oom) - int(left_oom), 0)
            if left_oom is not None and right_oom is not None
            else 0
        )
        kill_delta = (
            max(int(right_kill) - int(left_kill), 0)
            if left_kill is not None and right_kill is not None
            else 0
        )
        if oom_delta or kill_delta:
            oom_events.append(
                {
                    "oom_delta": oom_delta,
                    "oom_kill_delta": kill_delta,
                    "wall_time": right.get("wall_time"),
                    "monotonic": right.get("monotonic"),
                    "overlapping_events": _event_overlaps(
                        timeline_events,
                        start=float(left.get("monotonic", 0.0)),
                        end=float(right.get("monotonic", 0.0)),
                    ),
                }
            )
    network_analysis: dict[str, Any] = {}
    for interface in static.get("network_interfaces", []):
        interface_samples = [
            {
                "counters": sample["network"][interface],
                "monotonic": float(sample.get("monotonic", 0.0)),
            }
            for sample in host
            if interface in sample.get("network", {})
        ]
        field_analysis: dict[str, Any] = {}
        for field in (
            "rx_bytes",
            "rx_packets",
            "rx_errors",
            "rx_drops",
            "tx_bytes",
            "tx_packets",
            "tx_errors",
            "tx_drops",
        ):
            intervals: list[dict[str, Any]] = []
            for left, right in zip(interface_samples, interface_samples[1:]):
                duration = max(right["monotonic"] - left["monotonic"], 0.0)
                delta = max(
                    int(right["counters"][field]) - int(left["counters"][field]),
                    0,
                )
                rate = delta / duration if duration > 0 else None
                intervals.append(
                    {
                        "delta": delta,
                        "duration_seconds": duration,
                        "rate_per_second": rate,
                        "start_monotonic": left["monotonic"],
                        "end_monotonic": right["monotonic"],
                        "overlapping_events": (
                            _event_overlaps(
                                timeline_events,
                                start=left["monotonic"],
                                end=right["monotonic"],
                            )
                            if field.endswith("_errors") or field.endswith("_drops")
                            else []
                        ),
                    }
                )
            rates = [
                float(row["rate_per_second"])
                for row in intervals
                if row["rate_per_second"] is not None
            ]
            field_analysis[field] = {
                "delta": sum(row["delta"] for row in intervals),
                "peak_interval_delta": max(
                    (row["delta"] for row in intervals), default=0
                ),
                "throughput_per_second_p95": _percentile(rates, 0.95),
                "throughput_per_second_peak": max(rates, default=None),
                "intervals_with_timeline_overlap": [
                    row
                    for row in intervals
                    if row["delta"] and row["overlapping_events"]
                ],
            }
        network_analysis[interface] = {
            **field_analysis,
            "rx_bytes_throughput_p95": field_analysis["rx_bytes"][
                "throughput_per_second_p95"
            ],
            "tx_bytes_throughput_p95": field_analysis["tx_bytes"][
                "throughput_per_second_p95"
            ],
            "rx_pps_p95": field_analysis["rx_packets"][
                "throughput_per_second_p95"
            ],
            "tx_pps_p95": field_analysis["tx_packets"][
                "throughput_per_second_p95"
            ],
            "rx_bytes_throughput_peak": field_analysis["rx_bytes"][
                "throughput_per_second_peak"
            ],
            "tx_bytes_throughput_peak": field_analysis["tx_bytes"][
                "throughput_per_second_peak"
            ],
            "rx_pps_peak": field_analysis["rx_packets"][
                "throughput_per_second_peak"
            ],
            "tx_pps_peak": field_analysis["tx_packets"][
                "throughput_per_second_peak"
            ],
        }
    process_rows = [
        row
        for sample in process_samples
        for row in sample.get("processes", [])
    ]
    expected_gone_rows = [
        row for row in process_rows if row.get("status") == "EXPECTED_GONE"
    ]
    live_process_rows = [
        row for row in process_rows if row.get("status", "OK") != "EXPECTED_GONE"
    ]
    by_process: dict[str, list[dict[str, Any]]] = {}
    for row in live_process_rows:
        by_process.setdefault(str(row["logical_id"]), []).append(row)
    process_analysis: dict[str, dict[str, Any]] = {}
    for logical_id, rows in by_process.items():
        process_analysis[logical_id] = {
            "states": sorted({str(row["state"]) for row in rows}),
            "start_time_ticks": sorted(
                {int(row["start_time_ticks"]) for row in rows}
            ),
            "cpu_ticks_delta": max(
                (
                    int(rows[-1]["user_cpu_ticks"])
                    + int(rows[-1]["system_cpu_ticks"])
                    - int(rows[0]["user_cpu_ticks"])
                    - int(rows[0]["system_cpu_ticks"])
                ),
                0,
            ),
            "rss_bytes_max": max(int(row["rss_bytes"]) for row in rows),
            "rss_bytes_p95": _percentile(
                [float(row["rss_bytes"]) for row in rows], 0.95
            ),
            "fd_count_max": max(int(row["fd_count"]) for row in rows),
            "fd_count_p95": _percentile(
                [float(row["fd_count"]) for row in rows], 0.95
            ),
        }
    collector_durations = [
        float(sample["collector"]["sample_duration_seconds"])
        for sample in samples
    ]
    collector_cpu = [
        float(sample["collector"]["cpu_time_seconds"]) for sample in samples
    ]
    collector_rss = [int(sample["collector"]["rss_bytes"]) for sample in samples]
    overruns = [
        float(sample["collector"]["overrun_seconds"])
        for sample in host
        if float(sample["collector"]["overrun_seconds"]) > 0
    ]
    warnings = []
    if overruns:
        warnings.append(f"resource sampler overran {len(overruns)} host intervals")
    return {
        "status": "OK",
        "static": dict(static),
        "timestamps": [
            {
                "kind": sample.get("kind"),
                "wall_time": sample.get("wall_time"),
                "monotonic": sample.get("monotonic"),
            }
            for sample in samples
        ],
        "cpu": {
            "utilization_p95": _percentile(cpu_utilization, 0.95),
            "utilization_peak": max(cpu_utilization, default=None),
            "running_peak": max(
                (int(sample["scheduler"]["running"]) for sample in host),
                default=None,
            ),
            "blocked_peak": max(
                (int(sample["scheduler"]["blocked"]) for sample in host),
                default=None,
            ),
            "throttled_usec_delta": sum(throttle_deltas),
            "usage_usec_delta": sum(cpu_usage_deltas),
            "throttling_ratio": (
                sum(throttle_deltas) / sum(cpu_usage_deltas)
                if sum(cpu_usage_deltas)
                else None
            ),
        },
        "memory": {
            "mem_available_min": min(memory_available, default=None),
            "swap_used_peak": max(
                (
                    int(sample["memory"]["swap_used_bytes"])
                    for sample in host
                ),
                default=None,
            ),
            "cgroup_headroom_min": min(headroom, default=None),
            "oom_delta": sum(oom_deltas),
            "oom_kill_delta": sum(oom_kill_deltas),
            "oom_events": oom_events,
        },
        "network": network_analysis,
        "processes": process_analysis,
        "expected_gone_processes": [
            {
                "logical_id": row.get("logical_id"),
                "pid": row.get("pid"),
                "reason": row.get("reason"),
            }
            for row in expected_gone_rows
        ],
        "process_totals": {
            "rss_bytes_max_sum": sum(
                row["rss_bytes_max"] for row in process_analysis.values()
            ),
            "fd_count_max_sum": sum(
                row["fd_count_max"] for row in process_analysis.values()
            ),
            "max_rss_process": max(
                process_analysis,
                key=lambda logical_id: process_analysis[logical_id][
                    "rss_bytes_max"
                ],
                default=None,
            ),
            "max_fd_process": max(
                process_analysis,
                key=lambda logical_id: process_analysis[logical_id][
                    "fd_count_max"
                ],
                default=None,
            ),
        },
        "timeline_correlation": {
            "event_count": len(timeline_events),
            "resource_timestamp_count": len(samples),
            "network_error_or_drop_overlap_count": sum(
                len(metric["intervals_with_timeline_overlap"])
                for interface in network_analysis.values()
                for name, metric in interface.items()
                if isinstance(metric, dict)
                and name
                in {
                    "rx_errors",
                    "rx_drops",
                    "tx_errors",
                    "tx_drops",
                }
            ),
            "oom_event_overlap_count": sum(
                1 for event in oom_events if event["overlapping_events"]
            ),
        },
        "collector": {
            "cpu_time_seconds_peak": max(collector_cpu, default=None),
            "rss_bytes_peak": max(collector_rss, default=None),
            "sample_duration_seconds_p95": _percentile(
                collector_durations, 0.95
            ),
            "sample_duration_seconds_peak": max(
                collector_durations, default=None
            ),
            "overrun_count": len(overruns),
        },
        "warnings": warnings,
    }
