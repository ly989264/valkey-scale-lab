"""How the controller runs commands and moves files on a host it does not own.

The one thing a native backend needs that a Docker backend gets from the daemon.
It is a separate module rather than part of the backend because the roadmap makes
the transport a decision point that closes on real numbers in M3-B: keeping it
behind this interface is what makes a later switch cheap, and it is also what
lets the backend be proven hermetically against a fake.

`project/docs/native_backend_slice_map.md` §2 records the measurement that chose
the implementation below, and §2.4 the two constraints it found. In short, on two
simulated hosts against the rolling restart's measured 60-75 ms per-operation
budget: `docker exec` 66.4 ms median, un-multiplexed ssh 63.8 ms, multiplexed ssh
**10.8 ms**. Simulated numbers are lower bounds and the decision is provisional
until M3-B re-measures it across a VPC.

The interface is three operations, because that is all twenty-three `NodeBackend`
operations turned out to need. Anything a backend wants to know about a host that
is not one of these three is inventory, and inventory arrives in the manifest.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

#: `ControlPath` is a Unix domain socket path and `sockaddr_un` caps it at 104
#: bytes on this platform. Measured: the first spike run failed outright with
#: `ControlPath too long ('/private/tmp/.../scratchpad/mux/cm-sim-host-00' >= 104
#: bytes)`. A run's artifacts directory is nested far deeper than that, so the
#: sockets cannot live beside the run.
CONTROL_PATH_MAX_BYTES = 104


class TransportError(RuntimeError):
    """The transport itself failed - not the command it was asked to carry."""


@dataclass(frozen=True)
class CommandResult:
    """One completed command, with the timing its evidence record needs.

    The transport times the command rather than leaving each call site to do it,
    because "completed-command records with timing" is a property the roadmap
    requires *of the transport*, and a caller that timed it itself would be
    measuring its own scheduling as well.
    """

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    started_at_unix_ms: int
    ended_at_unix_ms: int

    @property
    def duration_ms(self) -> int:
        return self.ended_at_unix_ms - self.started_at_unix_ms


class HostTransport(Protocol):
    """Run a command on a host, put a file there, bring one back."""

    def run(
        self,
        control_endpoint: Mapping[str, Any],
        argv: Sequence[str],
        *,
        timeout: float,
    ) -> CommandResult:
        """Run `argv` on the host and return what it did.

        A non-zero exit is a result, not an exception: every caller records it,
        and several - the fault actuator above all - are required by §9.1 to
        report a failure to act rather than raise it. `TransportError` is for
        the transport failing to carry the command at all.
        """

    def put(
        self,
        control_endpoint: Mapping[str, Any],
        local_path: Path,
        remote_path: str,
        *,
        timeout: float,
    ) -> None:
        """Copy a local file or directory to `remote_path` on the host."""

    def get(
        self,
        control_endpoint: Mapping[str, Any],
        remote_path: str,
        local_path: Path,
        *,
        timeout: float,
    ) -> None:
        """Copy `remote_path` from the host into `local_path`."""

    def close(self) -> None:
        """Release whatever the transport is holding open."""


def _unix_ms() -> int:
    return int(time.time() * 1000)


class MultiplexedSshTransport:
    """One persistent ssh master per host; one session per command.

    The masters are opened lazily and shared, which is the whole of why this
    clears the budget: the handshake is paid once per host (65.3 ms and 57.1 ms
    measured) instead of once per command.

    Past sshd's stock `MaxSessions 10` the client waits rather than failing -
    measured to parallelism 32 with zero failures, latency rising from 11.8 ms to
    23.0 ms and throughput flat at ~600/s - so there is no session semaphore
    here. Adding one would cap concurrency lower than the transport actually
    sustains, on a limit that does not produce errors.
    """

    def __init__(self, *, control_root: str | Path | None = None, connect_timeout: int = 5) -> None:
        self._connect_timeout = connect_timeout
        self._owns_root = control_root is None
        root = Path(control_root) if control_root is not None else Path(
            tempfile.mkdtemp(prefix="vslab-cm-", dir=self._short_tmp())
        )
        root.mkdir(parents=True, exist_ok=True)
        self._root = root
        self._lock = threading.Lock()
        self._masters: dict[str, str] = {}

    @staticmethod
    def _short_tmp() -> str:
        # Not `tempfile.gettempdir()` unconditionally: on macOS that is a
        # per-user path under /var/folders long enough to eat most of the 104
        # byte budget before a socket name is appended.
        for candidate in ("/tmp", tempfile.gettempdir()):
            if Path(candidate).is_dir() and os.access(candidate, os.W_OK):
                return candidate
        raise TransportError("no writable short-path temporary directory for ssh control sockets")

    def _endpoint_key(self, control_endpoint: Mapping[str, Any]) -> str:
        return f"{control_endpoint['user']}@{control_endpoint['address']}:{control_endpoint['port']}"

    def _control_path(self, control_endpoint: Mapping[str, Any]) -> str:
        key = self._endpoint_key(control_endpoint)
        with self._lock:
            existing = self._masters.get(key)
            if existing is not None:
                return existing
            # Numbered rather than named: a host id could be long, and the
            # budget below is hard.
            path = str(self._root / f"m{len(self._masters):03d}")
            if len(path.encode("utf-8")) > CONTROL_PATH_MAX_BYTES:
                raise TransportError(
                    f"ssh control socket path is {len(path.encode('utf-8'))} bytes and the "
                    f"platform limit is {CONTROL_PATH_MAX_BYTES}: {path}"
                )
            self._masters[key] = path
            return path

    def _ssh_argv(self, control_endpoint: Mapping[str, Any]) -> list[str]:
        control_path = self._control_path(control_endpoint)
        return [
            "ssh",
            "-p", str(control_endpoint["port"]),
            "-i", str(control_endpoint["private_key_path"]),
            "-o", f"UserKnownHostsFile={control_endpoint['known_hosts_path']}",
            # The manifest records a host key fingerprint per host, and item 1.0
            # found a fleet serving one key for two hosts. Accepting an unknown
            # key would make that class of mistake invisible again.
            "-o", "StrictHostKeyChecking=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self._connect_timeout}",
            "-o", "ControlMaster=auto",
            "-o", f"ControlPath={control_path}",
            "-o", "ControlPersist=600",
            f"{control_endpoint['user']}@{control_endpoint['address']}",
        ]

    def _scp_argv(self, control_endpoint: Mapping[str, Any]) -> list[str]:
        control_path = self._control_path(control_endpoint)
        return [
            "scp",
            "-P", str(control_endpoint["port"]),
            "-i", str(control_endpoint["private_key_path"]),
            "-o", f"UserKnownHostsFile={control_endpoint['known_hosts_path']}",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes",
            # ControlMaster=no with a ControlPath *uses* an existing master
            # without trying to become one, which is what a second process
            # sharing the connection needs.
            "-o", "ControlMaster=no",
            "-o", f"ControlPath={control_path}",
            "-r",
        ]

    def run(
        self,
        control_endpoint: Mapping[str, Any],
        argv: Sequence[str],
        *,
        timeout: float,
    ) -> CommandResult:
        remote = shlex.join([str(item) for item in argv])
        local_argv = self._ssh_argv(control_endpoint) + [remote]
        started = _unix_ms()
        try:
            completed = subprocess.run(
                local_argv, capture_output=True, text=True, timeout=max(1.0, timeout)
            )
        except subprocess.TimeoutExpired as error:
            raise TransportError(
                f"command timed out after {timeout}s on "
                f"{self._endpoint_key(control_endpoint)}: {remote[:200]}"
            ) from error
        except OSError as error:
            raise TransportError(f"could not run ssh: {error}") from error
        return CommandResult(
            argv=[str(item) for item in argv],
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            started_at_unix_ms=started,
            ended_at_unix_ms=_unix_ms(),
        )

    def put(
        self,
        control_endpoint: Mapping[str, Any],
        local_path: Path,
        remote_path: str,
        *,
        timeout: float,
    ) -> None:
        target = f"{control_endpoint['user']}@{control_endpoint['address']}:{remote_path}"
        self._transfer(
            self._scp_argv(control_endpoint) + [str(local_path), target],
            timeout=timeout,
            what=f"copy {local_path} to {remote_path}",
            endpoint=control_endpoint,
        )

    def get(
        self,
        control_endpoint: Mapping[str, Any],
        remote_path: str,
        local_path: Path,
        *,
        timeout: float,
    ) -> None:
        source = f"{control_endpoint['user']}@{control_endpoint['address']}:{remote_path}"
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._transfer(
            self._scp_argv(control_endpoint) + [source, str(local_path)],
            timeout=timeout,
            what=f"copy {remote_path} to {local_path}",
            endpoint=control_endpoint,
        )

    def _transfer(
        self,
        argv: list[str],
        *,
        timeout: float,
        what: str,
        endpoint: Mapping[str, Any],
    ) -> None:
        try:
            completed = subprocess.run(
                argv, capture_output=True, text=True, timeout=max(1.0, timeout)
            )
        except subprocess.TimeoutExpired as error:
            raise TransportError(
                f"could not {what} on {self._endpoint_key(endpoint)}: timed out after {timeout}s"
            ) from error
        except OSError as error:
            raise TransportError(f"could not run scp: {error}") from error
        if completed.returncode != 0:
            raise TransportError(
                f"could not {what} on {self._endpoint_key(endpoint)}: {completed.stderr.strip()}"
            )

    def close(self) -> None:
        """Close every master, then drop the socket directory if it is ours.

        A master left running holds a connection open past the run that opened
        it, which on a real fleet is a resource the run owns and did not release.
        """
        with self._lock:
            masters = dict(self._masters)
            self._masters.clear()
        for key, control_path in masters.items():
            user_at_host, _, port = key.rpartition(":")
            subprocess.run(
                [
                    "ssh", "-p", port,
                    "-o", f"ControlPath={control_path}",
                    "-O", "exit", user_at_host,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        if self._owns_root:
            shutil.rmtree(self._root, ignore_errors=True)
