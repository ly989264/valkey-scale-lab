from __future__ import annotations

import binascii
import hashlib
import importlib
import inspect
import json
import multiprocessing
import socket
import socketserver
import sys
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from valkey_scale_lab.observer.failover_timeline import ObserverEndpoint


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
capture = importlib.import_module("m2_performance_capture")


class _FastClient:
    def __init__(self, value: str = "x") -> None:
        self.value = value

    def execute(self, *args: Any) -> SimpleNamespace:
        command = str(args[0]).upper()
        if command == "CLUSTER":
            value = _key_slot(str(args[2]))
        elif command == "SET":
            self.value = str(args[2])
            value = "OK"
        elif command == "GET":
            value = self.value
        else:
            raise AssertionError(f"unexpected command {command}")
        return SimpleNamespace(value=value, moved_count=0, ask_count=0)

    def close(self) -> None:
        return None


def _read_resp_command(stream: Any) -> list[str] | None:
    header = stream.readline()
    if not header:
        return None
    if not header.startswith(b"*"):
        raise ValueError("expected RESP array")
    count = int(header[1:-2])
    values: list[str] = []
    for _index in range(count):
        bulk = stream.readline()
        if not bulk.startswith(b"$"):
            raise ValueError("expected RESP bulk string")
        length = int(bulk[1:-2])
        value = stream.read(length)
        if stream.read(2) != b"\r\n":
            raise ValueError("unterminated RESP bulk string")
        values.append(value.decode("utf-8"))
    return values


class _RespHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        while True:
            command = _read_resp_command(self.rfile)
            if command is None:
                return
            verb = command[0].upper()
            if verb == "CLUSTER" and command[1].upper() == "KEYSLOT":
                response = f":{_key_slot(command[2])}\r\n".encode("ascii")
            elif verb == "SET":
                with self.server.value_lock:
                    self.server.values[command[1]] = command[2]
                response = b"+OK\r\n"
            elif verb == "GET":
                with self.server.value_lock:
                    value = self.server.values.get(command[1], "")
                encoded = value.encode("utf-8")
                response = f"${len(encoded)}\r\n".encode("ascii") + encoded + b"\r\n"
            else:
                response = b"-ERR unsupported command\r\n"
            self.wfile.write(response)
            self.wfile.flush()


class _RespServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _RespHandler)
        self.values: dict[str, str] = {}
        self.value_lock = threading.Lock()


def _serve_resp_until_stopped(port_output: Any, stop: Any) -> None:
    with _RespServer() as server:
        server.timeout = 0.05
        port_output.put(int(server.server_address[1]))
        while not stop.is_set():
            server.handle_request()


def _emit_full_cardinality_samples(
    output: Any,
    probe_specs: list[dict[str, Any]],
    barrier: float,
    samples_per_stream: int,
) -> None:
    output.put(
        {
            "type": "ready",
            "warmups": [
                {
                    "status": "PASS",
                    "shard_id": spec["shard_id"],
                    "affected": spec["affected"],
                }
                for spec in probe_specs
            ],
        }
    )
    probes = [SimpleNamespace(**spec) for spec in probe_specs]
    for sequence in range(samples_per_stream):
        for probe_index, probe in enumerate(probes):
            output.put(
                {
                    "type": "sample",
                    "probe_index": probe_index,
                    "sequence": sequence,
                    "sample": _sample(probe, barrier + sequence * 0.05),
                }
            )
    output.put(
        {
            "type": "done",
            "sample_counts": [samples_per_stream for _spec in probe_specs],
        }
    )


def _key_slot(key: str) -> int:
    start = key.find("{")
    end = key.find("}", start + 1)
    token = key[start + 1 : end] if start >= 0 and end > start + 1 else key
    return binascii.crc_hqx(token.encode("utf-8"), 0) % 16384


def _probe(shard_id: str, *, affected: bool, client: Any = None) -> Any:
    return capture.FaultClientProbe(
        shard_id=shard_id,
        key=f"{{{shard_id}}}:value",
        value="x",
        client=client,
        affected=affected,
    )


def _sample(probe: Any, started: float, completed: float | None = None) -> dict[str, Any]:
    completed = started + 0.001 if completed is None else completed
    return {
        "shard_id": probe.shard_id,
        "affected": probe.affected,
        "started_at_monotonic": round(started, 6),
        "completed_at_monotonic": round(completed, 6),
        "set_completed_at_monotonic": round(started + 0.0004, 6),
        "get_completed_at_monotonic": round(started + 0.0008, 6),
        "latency_ms": round((completed - started) * 1000.0, 6),
        "set_succeeded": True,
        "get_succeeded": True,
        "value_matches": True,
        "timed_out": False,
        "error": "",
        "moved_count": 0,
        "ask_count": 0,
        "status": "PASS",
    }


def test_fault_client_loop_directly_runs_affected_and_control_at_internal_cadence() -> None:
    probes = [
        _probe("affected", affected=True, client=_FastClient()),
        _probe("control", affected=False, client=_FastClient()),
    ]
    stop = threading.Event()
    started = [threading.Event(), threading.Event()]
    threads = [
        threading.Thread(
            target=capture._fault_client_loop,
            args=(probe, stop, event, threading.Lock()),
        )
        for probe, event in zip(probes, started)
    ]
    for thread in threads:
        thread.start()
    assert all(event.wait(timeout=1.0) for event in started)
    barrier = capture.shared_monotonic()
    time.sleep(0.38)
    stop.set()
    for thread in threads:
        thread.join(timeout=1.0)
        assert not thread.is_alive()

    cadence = capture._fault_cadence(probes, barrier, 0.3)

    assert cadence["status"] == "PASS"
    assert {row["affected"] for row in cadence["per_shard"]} == {True, False}
    assert all(row["attempt_count"] >= 5 for row in cadence["per_shard"])


def test_fault_client_loop_uses_parent_child_shared_monotonic_clock() -> None:
    assert capture._fault_client_loop.__kwdefaults__["monotonic_clock"] is (
        capture.shared_monotonic
    )


def test_fault_window_defers_single_full_validation_until_all_affected_shards_are_stable() -> None:
    source = inspect.getsource(capture._capture_fault_window)

    assert "_probe_endpoint" not in source
    assert '"CLUSTER", "NODES"' not in source
    assert "AffectedShardObserver" in source
    assert source.count("FullClusterValidator(") == 1
    assert "and not full_validation" in source
    assert "stable_relationships == set(replacement_by_shard)" in source


def test_m2_fault_rate_target_counts_preserve_existing_rounding() -> None:
    assert capture._failed_primary_count(200, "one") == 1
    assert capture._failed_primary_count(200, "10_percent") == 10
    assert capture._failed_primary_count(200, "33_percent") == 33


def test_sampler_process_isolated_from_representative_and_49_node_full_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork context is required for inherited test doubles")
    monkeypatch.setattr(capture, "_make_fault_client", lambda _endpoints: _FastClient())
    probes = [
        _probe("affected", affected=True),
        _probe("control", affected=False),
    ]
    sampler = capture._FaultClientSampler(
        probes,
        [SimpleNamespace()],
        threading.Lock(),
        process_context=multiprocessing.get_context("fork"),
    )
    warmups = sampler.start()
    barrier = capture.shared_monotonic()
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            representative = list(executor.map(lambda value: value, range(3)))
        assert representative == [0, 1, 2]
        sampler.drain()

        previous_switch_interval = sys.getswitchinterval()
        sys.setswitchinterval(0.2)
        try:
            slow_probe_end = time.monotonic() + 0.125
            while time.monotonic() < slow_probe_end:
                pass
        finally:
            sys.setswitchinterval(previous_switch_interval)
        sampler.drain()

        def full_probe(index: int) -> int:
            time.sleep(0.115 if index == 0 else 0.005)
            return index

        full_probe_started = time.monotonic()
        with ThreadPoolExecutor(max_workers=32) as executor:
            full_views = list(executor.map(full_probe, range(49)))
        assert full_views == list(range(49))
        assert time.monotonic() - full_probe_started >= 0.108
        sampler.drain()

        def throwing_probe() -> None:
            raise RuntimeError("observer probe failed")

        with ThreadPoolExecutor(max_workers=1) as executor:
            failed = executor.submit(throwing_probe)
            with pytest.raises(RuntimeError, match="observer probe failed"):
                failed.result()
        sampler.drain()
        remaining = (barrier + 0.8) - capture.shared_monotonic()
        if remaining > 0:
            time.sleep(remaining)
    finally:
        sampler.stop()

    cadence = capture._fault_cadence(probes, barrier, 0.7)
    assert len(warmups) == 2
    assert cadence["status"] == "PASS"
    assert all(row["max_attempt_interval_ms"] <= 100.0 for row in cadence["per_shard"])


def test_spawn_context_can_import_the_dynamically_loaded_capture_module() -> None:
    sampler = capture._FaultClientSampler(
        [_probe("affected", affected=True), _probe("control", affected=False)],
        [ObserverEndpoint(logical_id="closed", host="127.0.0.1", port=1)],
        threading.Lock(),
    )

    with pytest.raises(capture.CaptureError, match="process reported an error"):
        sampler.start()


def test_exact_200_fault_rate_sampler_drains_34_client_streams_without_join_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork context is required for inherited test doubles")
    monkeypatch.setattr(capture, "_make_fault_client", lambda _endpoints: _FastClient())
    probes = [
        *[_probe(f"affected-{index:02d}", affected=True) for index in range(33)],
        _probe("control", affected=False),
    ]
    sampler = capture._FaultClientSampler(
        probes,
        [SimpleNamespace()],
        threading.Lock(),
        process_context=multiprocessing.get_context("fork"),
    )
    sampler.start()
    barrier = capture.shared_monotonic()
    time.sleep(0.4)
    sampler.stop()

    cadence = capture._fault_cadence(probes, barrier, 0.3)
    assert cadence["status"] == "PASS"
    assert len(cadence["per_shard"]) == 34


def test_production_spawn_sampler_sustains_34_streams_during_repeated_observer_pressure() -> None:
    with socket.socket() as bind_probe:
        try:
            bind_probe.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            pytest.skip(f"local socket bind unavailable in sandbox: {exc}")
    context = multiprocessing.get_context("spawn")
    server_stop = context.Event()
    server_port = context.Queue()
    server_process = context.Process(
        target=_serve_resp_until_stopped,
        args=(server_port, server_stop),
        name="m2-fault-client-test-server",
    )
    server_process.start()
    port = server_port.get(timeout=5.0)
    probes = [
        *[_probe(f"affected-{index:02d}", affected=True) for index in range(33)],
        _probe("control", affected=False),
    ]
    endpoint = ObserverEndpoint(
        logical_id="spawn-test",
        host="127.0.0.1",
        port=port,
    )
    sampler = capture._FaultClientSampler(probes, [endpoint], threading.Lock())
    running = False
    try:
        warmups = sampler.start()
        running = True
        barrier = capture.shared_monotonic()

        def full_probe(item: tuple[int, float]) -> int:
            index, observer_seconds = item
            time.sleep(observer_seconds if index == 0 else 0.005)
            return index

        for observer_seconds in (0.108, 0.116, 0.125):
            previous_switch_interval = sys.getswitchinterval()
            sys.setswitchinterval(0.2)
            try:
                observer_end = time.monotonic() + observer_seconds
                while time.monotonic() < observer_end:
                    pass
            finally:
                sys.setswitchinterval(previous_switch_interval)

            with ThreadPoolExecutor(max_workers=32) as executor:
                workload = [
                    (index, observer_seconds)
                    for index in range(49)
                ]
                assert list(executor.map(full_probe, workload)) == list(range(49))
            sampler.drain()

        remaining = barrier + 2.2 - capture.shared_monotonic()
        if remaining > 0:
            time.sleep(remaining)
        sampler.stop()
        running = False
    finally:
        if running:
            try:
                sampler.stop()
            except capture.CaptureError:
                pass
        server_stop.set()
        server_process.join(timeout=2.0)
        if server_process.is_alive():
            server_process.terminate()
            server_process.join(timeout=1.0)
        server_port.close()
        server_port.join_thread()

    cadence = capture._fault_cadence(probes, barrier, 2.0)
    assert len(warmups) == 34
    assert sampler._done_counts is not None
    assert sampler._received_counts == sampler._done_counts
    failed_rows = [
        row for row in cadence["per_shard"] if row["status"] != "PASS"
    ]
    assert cadence["status"] == "PASS", failed_rows
    assert len(cadence["per_shard"]) == 34


def test_synthetic_spawn_emitter_preserves_queue_cardinality_and_serialization_under_backpressure(
    tmp_path: Path,
) -> None:
    # This synthetic emitter bypasses _fault_client_loop. It verifies only
    # Queue delivery, full-cardinality accounting, and evidence serialization.
    probes = [
        *[_probe(f"affected-{index:02d}", affected=True) for index in range(33)],
        _probe("control", affected=False),
    ]
    sampler = capture._FaultClientSampler(probes, [SimpleNamespace()], threading.Lock())
    barrier = 1000.0
    samples_per_stream = int(120.0 / 0.05) + 1
    context = multiprocessing.get_context("spawn")
    output = context.Queue(maxsize=64)
    emitter = context.Process(
        target=_emit_full_cardinality_samples,
        args=(
            output,
            [
                {
                    "shard_id": probe.shard_id,
                    "affected": probe.affected,
                }
                for probe in probes
            ],
            barrier,
            samples_per_stream,
        ),
        name="m2-full-cardinality-test-emitter",
    )
    emitter.start()
    try:
        while sampler._done_counts is None:
            sampler._accept_message(output.get(timeout=10.0))
        emitter.join(timeout=10.0)
        assert not emitter.is_alive()
        assert emitter.exitcode == 0
        assert sampler._received_counts == sampler._done_counts
    finally:
        if emitter.is_alive():
            emitter.terminate()
            emitter.join(timeout=1.0)
        output.close()
        output.join_thread()
        sampler._close_queue()

    client_series = capture._fault_client_series(
        probes,
        {"sigkill_barrier": barrier},
        120.0,
    )
    forbidden_duplicates = {
        "attempt_started_monotonic",
        "successful_pair_latencies_ms",
        "samples_through_stable_endpoint",
    }
    assert sum(len(row["attempts"]) for row in client_series) == 81_634
    assert all(forbidden_duplicates.isdisjoint(row) for row in client_series)

    evidence_path = tmp_path / "client_series.json"
    capture._write_json(evidence_path, {"client_series": client_series})
    encoded = evidence_path.read_bytes()
    decoded = json.loads(encoded)
    assert sum(
        len(row["attempts"]) for row in decoded["client_series"]
    ) == 81_634
    assert len(encoded) < 32 * 1024 * 1024


def test_sampler_shutdown_preserves_an_active_capture_error() -> None:
    class FailingSampler:
        @staticmethod
        def stop() -> None:
            raise capture.CaptureError("shutdown failure")

    primary = RuntimeError("capture failure")
    capture._stop_fault_sampler(FailingSampler(), primary)

    expected = "persistent fault client shutdown also failed: CaptureError: shutdown failure"
    assert expected in getattr(primary, "__notes__", [getattr(primary, "sampler_shutdown_error", "")])


def test_sampler_shutdown_failure_propagates_without_an_active_capture_error() -> None:
    class FailingSampler:
        @staticmethod
        def stop() -> None:
            raise capture.CaptureError("shutdown failure")

    with pytest.raises(capture.CaptureError, match="shutdown failure"):
        capture._stop_fault_sampler(FailingSampler(), None)


def _empty_sampler_process(
    _endpoints: list[Any],
    _probe_specs: list[dict[str, Any]],
    _stop: Any,
    _output: Any,
) -> None:
    return None


def _bad_terminal_sampler_process(
    _endpoints: list[Any],
    probe_specs: list[dict[str, Any]],
    stop: Any,
    output: Any,
) -> None:
    output.put(
        {
            "type": "ready",
            "warmups": [
                {
                    "status": "PASS",
                    "shard_id": spec["shard_id"],
                    "affected": spec["affected"],
                }
                for spec in probe_specs
            ],
        }
    )
    stop.wait()
    output.put({"type": "done", "sample_counts": [1, 0]})


def _trailing_after_done_sampler_process(
    _endpoints: list[Any],
    probe_specs: list[dict[str, Any]],
    stop: Any,
    output: Any,
) -> None:
    output.put(
        {
            "type": "ready",
            "warmups": [
                {
                    "status": "PASS",
                    "shard_id": spec["shard_id"],
                    "affected": spec["affected"],
                }
                for spec in probe_specs
            ],
        }
    )
    stop.wait()
    output.put({"type": "done", "sample_counts": [0 for _spec in probe_specs]})
    probe = SimpleNamespace(**probe_specs[0])
    output.put(
        {
            "type": "sample",
            "probe_index": 0,
            "sequence": 0,
            "sample": _sample(probe, capture.shared_monotonic()),
        }
    )
    time.sleep(0.2)


def test_sampler_process_exit_without_terminal_ipc_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork context is required for inherited process target")
    monkeypatch.setattr(capture, "_fault_sampler_process", _empty_sampler_process)
    sampler = capture._FaultClientSampler(
        [_probe("affected", affected=True), _probe("control", affected=False)],
        [SimpleNamespace()],
        threading.Lock(),
        process_context=multiprocessing.get_context("fork"),
    )

    with pytest.raises(capture.CaptureError, match="exited before SIGKILL"):
        sampler.start()


def test_sampler_exit_during_capture_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork context is required for inherited test doubles")
    monkeypatch.setattr(capture, "_make_fault_client", lambda _endpoints: _FastClient())
    sampler = capture._FaultClientSampler(
        [_probe("affected", affected=True), _probe("control", affected=False)],
        [SimpleNamespace()],
        threading.Lock(),
        process_context=multiprocessing.get_context("fork"),
    )
    sampler.start()
    sampler._process.terminate()
    sampler._process.join(timeout=1.0)
    try:
        with pytest.raises(capture.CaptureError, match="exited during capture"):
            sampler.drain()
    finally:
        sampler._close_queue()


def test_sampler_terminal_count_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork context is required for inherited process target")
    monkeypatch.setattr(capture, "_fault_sampler_process", _bad_terminal_sampler_process)
    sampler = capture._FaultClientSampler(
        [_probe("affected", affected=True), _probe("control", affected=False)],
        [SimpleNamespace()],
        threading.Lock(),
        process_context=multiprocessing.get_context("fork"),
    )
    sampler.start()

    with pytest.raises(capture.CaptureError, match="sample counts do not match"):
        sampler.stop()


def test_sampler_rejects_trailing_queue_message_after_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork context is required for inherited process target")
    monkeypatch.setattr(
        capture,
        "_fault_sampler_process",
        _trailing_after_done_sampler_process,
    )
    sampler = capture._FaultClientSampler(
        [_probe("affected", affected=True), _probe("control", affected=False)],
        [SimpleNamespace()],
        threading.Lock(),
        process_context=multiprocessing.get_context("fork"),
    )
    sampler.start()

    with pytest.raises(capture.CaptureError, match="message after.*completion"):
        sampler.stop()


def test_sampler_rejects_missing_or_duplicate_ipc_sequence() -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork context is required for a local multiprocessing queue")
    probe = _probe("affected", affected=True)
    sampler = capture._FaultClientSampler(
        [probe],
        [SimpleNamespace()],
        threading.Lock(),
        process_context=multiprocessing.get_context("fork"),
    )
    try:
        with pytest.raises(capture.CaptureError, match="sequence is missing or out of order"):
            sampler._accept_message(
                {
                    "type": "sample",
                    "probe_index": 0,
                    "sequence": 1,
                    "sample": _sample(probe, 10.0),
                }
            )
        sampler._accept_message(
            {
                "type": "sample",
                "probe_index": 0,
                "sequence": 0,
                "sample": _sample(probe, 10.0),
            }
        )
        with pytest.raises(capture.CaptureError, match="sequence is missing or out of order"):
            sampler._accept_message(
                {
                    "type": "sample",
                    "probe_index": 0,
                    "sequence": 0,
                    "sample": _sample(probe, 10.05),
                }
            )
    finally:
        sampler._close_queue()


@pytest.mark.parametrize("defect", ["missing", "out_of_order", "duplicate", "trailing_gap"])
def test_fault_cadence_rejects_incomplete_or_non_monotonic_raw_timestamps(
    defect: str,
) -> None:
    affected = _probe("affected", affected=True)
    control = _probe("control", affected=False)
    timestamps: list[Any] = [10.0, 10.05, 10.1, 10.15, 10.2]
    if defect == "missing":
        timestamps[2] = None
    elif defect == "out_of_order":
        timestamps[1], timestamps[2] = timestamps[2], timestamps[1]
    elif defect == "duplicate":
        timestamps[2] = timestamps[1]
    elif defect == "trailing_gap":
        timestamps = [10.0, 10.05, 10.09]
    affected.samples = [{"started_at_monotonic": value} for value in timestamps]
    control.samples = [
        {"started_at_monotonic": value}
        for value in [10.0, 10.05, 10.1, 10.15, 10.2]
    ]

    cadence = capture._fault_cadence([affected, control], 10.0, 0.2)

    assert cadence["status"] == "FAIL"
    assert next(row for row in cadence["per_shard"] if row["affected"])["status"] == "FAIL"


def test_fault_cadence_includes_exact_boundaries_and_preserves_outside_samples() -> None:
    probes = [
        _probe("affected", affected=True),
        _probe("control", affected=False),
    ]
    timestamps = [9.99, 10.0, 10.05, 10.1, 10.15, 10.2, 10.21]
    for probe in probes:
        probe.samples = [{"started_at_monotonic": value} for value in timestamps]

    cadence = capture._fault_cadence(probes, 10.0, 0.2)

    assert cadence["status"] == "PASS"
    assert all(row["attempt_count"] == 5 for row in cadence["per_shard"])
    assert all(row["max_attempt_interval_ms"] == 50.0 for row in cadence["per_shard"])
    assert all(len(probe.samples) == 7 for probe in probes)


def test_fault_cadence_clips_cross_boundary_intervals_and_retains_raw_samples() -> None:
    probes = [
        _probe("affected", affected=True),
        _probe("control", affected=False),
    ]
    timestamps = [
        9.91,
        10.02,
        10.04,
        10.06,
        10.08,
        10.10,
        10.12,
        10.14,
        10.16,
        10.18,
        10.29,
    ]
    for probe in probes:
        probe.samples = [_sample(probe, value) for value in timestamps]

    cadence = capture._fault_cadence(probes, 10.0, 0.2)
    series = capture._fault_client_series(
        probes,
        {"sigkill_barrier": 10.0},
        0.2,
    )

    assert timestamps[1] - timestamps[0] == pytest.approx(0.11)
    assert timestamps[-1] - timestamps[-2] == pytest.approx(0.11)
    assert cadence["status"] == "PASS"
    assert all(row["attempt_count"] == 9 for row in cadence["per_shard"])
    assert all(row["max_attempt_interval_ms"] == 20.0 for row in cadence["per_shard"])
    assert all(len(row["attempts"]) == 11 for row in series)
    assert all(row["attempt_count"] == 9 for row in series)
    assert all(len(probe.samples) == 11 for probe in probes)


@pytest.mark.parametrize("edge", ["start", "end"])
def test_fault_cadence_rejects_a_boundary_gap_over_100_ms(edge: str) -> None:
    affected = _probe("affected", affected=True)
    control = _probe("control", affected=False)
    valid = [10.0, 10.05, 10.1, 10.15, 10.2]
    affected_starts = list(valid)
    if edge == "start":
        affected_starts = [9.99, 10.100001, 10.15, 10.2]
    else:
        affected_starts = [10.0, 10.05, 10.099999, 10.21]
    affected.samples = [
        {"started_at_monotonic": value}
        for value in affected_starts
    ]
    control.samples = [
        {"started_at_monotonic": value}
        for value in valid
    ]

    cadence = capture._fault_cadence([affected, control], 10.0, 0.2)

    affected_row = next(row for row in cadence["per_shard"] if row["affected"])
    assert cadence["status"] == "FAIL"
    assert affected_row["status"] == "FAIL"
    assert affected_row["max_attempt_interval_ms"] == 100.001


def test_run_29997723777_cadence_gap_replay_remains_a_failure() -> None:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "m2_regressions"
    manifest = json.loads(
        (fixture_dir / "historical_gate_replays.json").read_text(encoding="utf-8")
    )
    case = next(
        row
        for row in manifest["runs"]
        if row["source_run_id"] == "29997723777"
    )
    archive_path = fixture_dir / case["fixture"]["file"]
    compressed = archive_path.read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == case["fixture"]["sha256"]
    with tarfile.open(archive_path, mode="r:gz") as archive:
        sources = {}
        for name in ("workload", "fault"):
            source = case["failure_sources"][name]
            member = archive.extractfile(source["path"])
            assert member is not None
            raw = member.read()
            assert hashlib.sha256(raw).hexdigest() == source["sha256"]
            sources[name] = json.loads(raw)

    workload = sources["workload"]
    fault = sources["fault"]
    affected = _probe("affected", affected=True)
    control = _probe("control", affected=False)
    by_affected = {
        series["affected"]: series["attempt_started_monotonic"]
        for series in workload["client_series"]
    }
    affected.samples = [
        {"started_at_monotonic": value} for value in by_affected[True]
    ]
    control.samples = [
        {"started_at_monotonic": value} for value in by_affected[False]
    ]

    cadence = capture._fault_cadence(
        [affected, control],
        fault["barrier_monotonic"],
        workload["duration_seconds"],
    )

    assert cadence["status"] == "FAIL"
    rows = {row["affected"]: row for row in cadence["per_shard"]}
    for is_affected in (True, False):
        timestamps = by_affected[is_affected]
        raw_max_ms = max(
            (right - left) * 1000.0
            for left, right in zip(timestamps, timestamps[1:])
        )
        assert rows[is_affected]["max_attempt_interval_ms"] == pytest.approx(
            raw_max_ms,
            abs=1e-3,
        )
        assert raw_max_ms > 100.0
    probe = fault["every_node_convergence_probe"]
    assert probe["at_monotonic"] - probe["probe_started_at_monotonic"] == pytest.approx(
        probe["probe_duration_ms"] / 1000.0,
        abs=1e-6,
    )


def test_fault_measurement_errors_keep_producer_error_count_raw_derived() -> None:
    workload = {
        "status": "PASS",
        "errors": ["SET TimeoutError: timed out"],
        "error_count": 1,
    }

    capture._apply_fault_measurement_errors(
        workload,
        ["affected/control SET/GET attempt cadence exceeded 100 ms or was incomplete"],
    )

    assert workload["status"] == "FAIL"
    assert workload["error_count"] == len(workload["errors"]) == 2
