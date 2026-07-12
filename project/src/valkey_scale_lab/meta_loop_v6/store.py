from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - the project runtime contract is Mac/Linux.
    fcntl = None  # type: ignore[assignment]


class StateStoreError(RuntimeError):
    pass


class StateStore:
    """Atomic state store; the event chain lives inside the same transaction."""

    def __init__(self, root: Path):
        self.root = root
        self.state_path = root / "state" / "loop_state.json"
        self.events_path = root / "state" / "events.jsonl"
        self.lock_path = root / "state" / ".controller.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        if fcntl is None:
            raise StateStoreError("meta loop locking requires a Mac/Linux fcntl runtime")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def exists(self) -> bool:
        return self.state_path.exists()

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateStoreError(f"cannot load loop state: {exc}") from exc
        if not isinstance(value, dict):
            raise StateStoreError("loop state must be a JSON object")
        return value

    def save(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")
        events = state.get("events", [])
        event_text = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events if isinstance(event, dict))
        self._atomic_write(self.events_path, event_text)

    def append_event(self, state: dict[str, Any], event: dict[str, Any]) -> str:
        events = state.setdefault("events", [])
        if not isinstance(events, list):
            raise StateStoreError("state events must be a list")
        chained = dict(event)
        chained["previous_event_hash"] = state.get("last_event_hash")
        digest_payload = json.dumps(chained, separators=(",", ":"), sort_keys=True).encode("utf-8")
        event_hash = hashlib.sha256(digest_payload).hexdigest()
        chained["event_hash"] = event_hash
        events.append(chained)
        state["last_event_hash"] = event_hash
        return event_hash

    @staticmethod
    def verify_event_chain(state: dict[str, Any]) -> list[str]:
        events = state.get("events")
        if not isinstance(events, list):
            return ["state events are missing or invalid"]
        errors: list[str] = []
        previous: str | None = None
        for index, original in enumerate(events, start=1):
            if not isinstance(original, dict):
                errors.append(f"event {index} is not an object")
                continue
            event = dict(original)
            claimed_hash = event.pop("event_hash", None)
            if event.get("previous_event_hash") != previous:
                errors.append(f"event {index} previous hash mismatch")
            actual = hashlib.sha256(json.dumps(event, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
            if claimed_hash != actual:
                errors.append(f"event {index} hash mismatch")
            previous = claimed_hash
        if previous != state.get("last_event_hash"):
            errors.append("state last_event_hash does not match its event chain")
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
