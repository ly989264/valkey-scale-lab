from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProxyRule:
    fault_type: str
    delay_ms: int = 0
    jitter_ms: int = 0
    loss_percent: float = 0.0
    flap_up_ms: int = 0
    flap_down_ms: int = 0
    flap_iterations: int = 0


class SandboxNetworkProxy:
    """Project-owned TCP proxy used for sandboxed Valkey network faults."""

    def __init__(
        self,
        *,
        target_host: str,
        target_port: int,
        rule: ProxyRule,
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
        connect_timeout: float = 2.0,
    ) -> None:
        self.target_host = target_host
        self.target_port = int(target_port)
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.rule = rule
        self.connect_timeout = connect_timeout
        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._started_at = 0.0
        self._accepted = 0
        self._proxied = 0
        self._dropped = 0
        self._flap_rejections = 0
        self._relay_errors = 0
        self._bytes_client_to_target = 0
        self._bytes_target_to_client = 0
        self._delay_injections = 0
        self._total_delay_ms = 0
        self._connections: list[socket.socket] = []

    @property
    def address(self) -> tuple[str, int]:
        return self.listen_host, self.listen_port

    def start(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.listen_host, self.listen_port))
        listener.listen()
        listener.settimeout(0.2)
        self.listen_port = int(listener.getsockname()[1])
        self._listener = listener
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._accept_loop, name=f"p23-sandbox-proxy-{self.listen_port}", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._lock:
            sockets = list(self._connections)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "implementation_path": "sandbox_proxy",
                "listen_host": self.listen_host,
                "listen_port": self.listen_port,
                "target_host": self.target_host,
                "target_port": self.target_port,
                "accepted_connections": self._accepted,
                "proxied_connections": self._proxied,
                "dropped_connections": self._dropped,
                "flap_rejections": self._flap_rejections,
                "relay_errors": self._relay_errors,
                "bytes_client_to_target": self._bytes_client_to_target,
                "bytes_target_to_client": self._bytes_target_to_client,
                "delay_injections": self._delay_injections,
                "total_delay_ms": self._total_delay_ms,
                "host_network_mutated": False,
            }

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                assert self._listener is not None
                client, _addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._lock:
                self._accepted += 1
                index = self._accepted
                self._connections.append(client)
            if self._should_reject(index):
                self._safe_close(client)
                continue
            thread = threading.Thread(target=self._handle_client, args=(client,), daemon=True)
            thread.start()

    def _should_reject(self, index: int) -> bool:
        if self.rule.fault_type == "network_loss" and self.rule.loss_percent > 0:
            threshold = max(1, round(100.0 / min(self.rule.loss_percent, 100.0)))
            if index % threshold == 0:
                with self._lock:
                    self._dropped += 1
                return True
        if self.rule.fault_type == "network_flap" and self.rule.flap_down_ms > 0:
            elapsed_ms = int((time.monotonic() - self._started_at) * 1000)
            cycle_ms = max(self.rule.flap_up_ms + self.rule.flap_down_ms, 1)
            iteration = elapsed_ms // cycle_ms
            if self.rule.flap_iterations <= 0 or iteration < self.rule.flap_iterations:
                if elapsed_ms % cycle_ms >= self.rule.flap_up_ms:
                    with self._lock:
                        self._flap_rejections += 1
                    return True
        return False

    def _handle_client(self, client: socket.socket) -> None:
        target: socket.socket | None = None
        try:
            target = socket.create_connection((self.target_host, self.target_port), timeout=self.connect_timeout)
            target.settimeout(0.5)
            client.settimeout(0.5)
            with self._lock:
                self._proxied += 1
                self._connections.append(target)
            left = threading.Thread(target=self._relay, args=(client, target, "client_to_target"), daemon=True)
            right = threading.Thread(target=self._relay, args=(target, client, "target_to_client"), daemon=True)
            left.start()
            right.start()
            left.join()
            right.join()
        except OSError:
            with self._lock:
                self._relay_errors += 1
        finally:
            self._safe_close(client)
            if target is not None:
                self._safe_close(target)

    def _relay(self, source: socket.socket, dest: socket.socket, direction: str) -> None:
        while not self._stop.is_set():
            try:
                data = source.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            self._maybe_delay()
            try:
                dest.sendall(data)
            except OSError:
                with self._lock:
                    self._relay_errors += 1
                break
            with self._lock:
                if direction == "client_to_target":
                    self._bytes_client_to_target += len(data)
                else:
                    self._bytes_target_to_client += len(data)

    def _maybe_delay(self) -> None:
        if self.rule.fault_type != "network_delay":
            return
        delay_ms = max(0, int(self.rule.delay_ms))
        if self.rule.jitter_ms:
            sign = -1 if self._delay_injections % 2 else 1
            delay_ms = max(0, delay_ms + sign * int(self.rule.jitter_ms))
        if delay_ms <= 0:
            return
        time.sleep(delay_ms / 1000.0)
        with self._lock:
            self._delay_injections += 1
            self._total_delay_ms += delay_ms

    def _safe_close(self, sock: socket.socket) -> None:
        try:
            sock.close()
        except OSError:
            pass
        with self._lock:
            self._connections = [item for item in self._connections if item is not sock]
