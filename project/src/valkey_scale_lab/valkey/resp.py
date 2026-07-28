from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import Any, BinaryIO, Iterable, Sequence


class RespProtocolError(RuntimeError):
    pass


class RespCommandError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int


def encode_command(command: Sequence[Any]) -> bytes:
    parts = [f"*{len(command)}\r\n".encode("ascii")]
    for arg in command:
        data = arg if isinstance(arg, bytes) else str(arg).encode("utf-8")
        parts.extend((f"${len(data)}\r\n".encode("ascii"), data, b"\r\n"))
    return b"".join(parts)


def _line(fp: BinaryIO) -> bytes:
    line = fp.readline()
    if not line.endswith(b"\r\n"):
        raise RespProtocolError("truncated RESP line")
    return line[:-2]


def read_response(fp: BinaryIO) -> Any:
    prefix = fp.read(1)
    if not prefix:
        raise EOFError("Valkey connection closed")
    if prefix == b"+":
        return _line(fp).decode("utf-8", errors="replace")
    if prefix in {b"-", b"!"}:
        if prefix == b"!":
            size = int(_line(fp))
            message = fp.read(size)
            if fp.read(2) != b"\r\n":
                raise RespProtocolError("invalid RESP blob error")
        else:
            message = _line(fp)
        raise RespCommandError(message.decode("utf-8", errors="replace"))
    if prefix == b":":
        return int(_line(fp))
    if prefix == b",":
        return float(_line(fp))
    if prefix == b"#":
        value = _line(fp)
        if value not in {b"t", b"f"}:
            raise RespProtocolError("invalid RESP boolean")
        return value == b"t"
    if prefix == b"_":
        if _line(fp):
            raise RespProtocolError("invalid RESP null")
        return None
    if prefix in {b"$", b"="}:
        size = int(_line(fp))
        if size == -1:
            return None
        data = fp.read(size)
        if len(data) != size or fp.read(2) != b"\r\n":
            raise RespProtocolError("truncated RESP bulk string")
        return data
    if prefix in {b"*", b"~", b">"}:
        size = int(_line(fp))
        if size == -1:
            return None
        return [read_response(fp) for _ in range(size)]
    if prefix in {b"%", b"|"}:
        size = int(_line(fp))
        result: dict[Any, Any] = {}
        for _ in range(size):
            key = read_response(fp)
            value = read_response(fp)
            result[key] = value
        if prefix == b"|":
            return {"attributes": result, "value": read_response(fp)}
        return result
    if prefix == b"(":
        return int(_line(fp))
    raise RespProtocolError(f"unsupported RESP prefix {prefix!r}")


class RespConnection:
    """Small persistent RESP2/RESP3 connection with serialized commands."""

    def __init__(self, endpoint: Endpoint, *, timeout: float = 2.0) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self) -> None:
        if self._socket is not None:
            return
        sock = socket.create_connection(
            (self.endpoint.host, self.endpoint.port),
            timeout=self.timeout,
        )
        sock.settimeout(self.timeout)
        self._socket = sock
        self._reader = sock.makefile("rb")

    def close(self) -> None:
        reader, sock = self._reader, self._socket
        self._reader = None
        self._socket = None
        if reader is not None:
            reader.close()
        if sock is not None:
            sock.close()

    def execute(self, *command: Any) -> Any:
        return self.execute_many([command])[0]

    def execute_many(self, commands: Iterable[Sequence[Any]]) -> list[Any]:
        rows = list(commands)
        with self._lock:
            self.connect()
            assert self._socket is not None and self._reader is not None
            try:
                self._socket.sendall(b"".join(encode_command(row) for row in rows))
                return [read_response(self._reader) for _ in rows]
            except Exception:
                self.close()
                raise

    def __enter__(self) -> "RespConnection":
        self.connect()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
