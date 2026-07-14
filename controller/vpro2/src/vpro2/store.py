from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class StateStoreError(RuntimeError):
    pass


class StateStore:
    """Atomic controller state mirrored by an authenticated event journal."""

    def __init__(self, root: Path, *, seal_key: bytes):
        if not isinstance(seal_key, bytes) or len(seal_key) < 32:
            raise StateStoreError("state seal key must contain at least 32 bytes")
        self.root = Path(root).resolve()
        self._seal_key = seal_key
        self.state_path = self.root / "state" / "loop_state.json"
        self.events_path = self.root / "state" / "events.jsonl"
        self.lock_path = self.root / "state" / ".controller.lock"
        self.contract_path = self.root / "state" / "milestone.seal.json"
        self.terminal_path = self.root / "state" / "terminal.seal.json"

    @property
    def seal_key_id(self) -> str:
        return hashlib.sha256(self._seal_key).hexdigest()

    @contextmanager
    def locked(self) -> Iterator[None]:
        if fcntl is None:
            raise StateStoreError("VPRO2 state locking requires fcntl")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def exists(self) -> bool:
        return self.state_path.is_file()

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateStoreError(f"cannot load VPRO2 state: {exc}") from exc
        if not isinstance(value, dict):
            raise StateStoreError("VPRO2 state must be an object")
        return value

    def save(self, state: dict[str, Any]) -> None:
        events = state.get("events")
        if not isinstance(events, list):
            raise StateStoreError("state events must be a list")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")
        journal = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        self._atomic_write(self.events_path, journal)

    def save_contract(self, value: dict[str, Any]) -> None:
        if self.contract_path.exists():
            raise StateStoreError("sealed milestone already exists")
        self.contract_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.contract_path, json.dumps(value, indent=2, sort_keys=True) + "\n")

    def save_terminal(self, value: dict[str, Any]) -> None:
        if self.terminal_path.exists():
            raise StateStoreError("terminal receipt already exists")
        self.terminal_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.terminal_path, json.dumps(value, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def payload_digest(state: dict[str, Any]) -> str:
        payload = {key: value for key, value in state.items() if key not in {"events", "last_event_hash"}}
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def authentication_tag(self, domain: str, value: Any) -> str:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return hmac.new(self._seal_key, domain.encode() + b"\0" + encoded, hashlib.sha256).hexdigest()

    def append_event(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        events = state.setdefault("events", [])
        if not isinstance(events, list):
            raise StateStoreError("state events must be a list")
        chained = dict(event)
        chained["state_payload_hash"] = self.payload_digest(state)
        chained["previous_event_hash"] = state.get("last_event_hash")
        encoded = json.dumps(chained, separators=(",", ":"), sort_keys=True).encode()
        chained["event_hash"] = hmac.new(
            self._seal_key,
            b"vpro2-event-v1\0" + encoded,
            hashlib.sha256,
        ).hexdigest()
        events.append(chained)
        state["last_event_hash"] = chained["event_hash"]

    def verify(self, state: dict[str, Any]) -> list[str]:
        errors = self._verify_chain(state)
        try:
            journal = [json.loads(line) for line in self.events_path.read_text(encoding="utf-8").splitlines()]
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot load events journal: {exc}")
        else:
            if journal != state.get("events"):
                errors.append("events journal does not match state events")
        return errors

    def _verify_chain(self, state: dict[str, Any]) -> list[str]:
        events = state.get("events")
        if not isinstance(events, list) or not events:
            return ["state has no authenticated event"]
        errors: list[str] = []
        previous: str | None = None
        for index, original in enumerate(events, start=1):
            if not isinstance(original, dict):
                errors.append(f"event {index} is not an object")
                continue
            event = dict(original)
            claimed = event.pop("event_hash", None)
            if event.get("previous_event_hash") != previous:
                errors.append(f"event {index} previous hash mismatch")
            encoded = json.dumps(event, separators=(",", ":"), sort_keys=True).encode()
            expected = hmac.new(self._seal_key, b"vpro2-event-v1\0" + encoded, hashlib.sha256).hexdigest()
            if not isinstance(claimed, str) or not hmac.compare_digest(claimed, expected):
                errors.append(f"event {index} hash mismatch")
            previous = claimed
        if previous != state.get("last_event_hash"):
            errors.append("last_event_hash mismatch")
        latest = events[-1]
        if not isinstance(latest, dict) or latest.get("state_payload_hash") != self.payload_digest(state):
            errors.append("latest event does not seal current state")
        return errors

    @staticmethod
    def _atomic_write(path: Path, payload: str) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f"{path.name}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
