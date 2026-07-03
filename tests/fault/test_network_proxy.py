from __future__ import annotations

import socket
import threading
import time
from contextlib import closing

import pytest

from valkey_scale_lab.fault.network_proxy import ProxyRule, SandboxNetworkProxy


class EchoServer:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen()
        self._sock.settimeout(0.2)
        self.port = int(self._sock.getsockname()[1])
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._sock.close()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                client, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    @staticmethod
    def _handle(client: socket.socket) -> None:
        with closing(client):
            data = client.recv(4096)
            if data:
                client.sendall(data)


def request(port: int, payload: bytes = b"ping") -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
        sock.settimeout(2.0)
        sock.sendall(payload)
        return sock.recv(4096)


def test_sandbox_proxy_forwards_and_records_delay() -> None:
    try:
        server = EchoServer()
    except PermissionError as exc:
        pytest.skip(f"local socket bind unavailable in sandbox: {exc}")
    server.start()
    proxy = SandboxNetworkProxy(target_host="127.0.0.1", target_port=server.port, rule=ProxyRule("network_delay", delay_ms=20))
    proxy.start()
    try:
        started = time.monotonic()
        assert request(proxy.address[1]) == b"ping"
        elapsed_ms = (time.monotonic() - started) * 1000
        stats = proxy.snapshot()
        assert elapsed_ms >= 20
        assert stats["accepted_connections"] == 1
        assert stats["delay_injections"] >= 1
        assert stats["host_network_mutated"] is False
    finally:
        proxy.close()
        server.close()


def test_sandbox_proxy_drops_deterministic_loss_connections() -> None:
    try:
        server = EchoServer()
    except PermissionError as exc:
        pytest.skip(f"local socket bind unavailable in sandbox: {exc}")
    server.start()
    proxy = SandboxNetworkProxy(target_host="127.0.0.1", target_port=server.port, rule=ProxyRule("network_loss", loss_percent=50.0))
    proxy.start()
    try:
        results: list[bytes | str] = []
        for _ in range(4):
            try:
                results.append(request(proxy.address[1]))
            except OSError as exc:
                results.append(type(exc).__name__)
        stats = proxy.snapshot()
        assert stats["accepted_connections"] == 4
        assert stats["dropped_connections"] >= 2
        assert any(item != b"ping" for item in results)
    finally:
        proxy.close()
        server.close()
