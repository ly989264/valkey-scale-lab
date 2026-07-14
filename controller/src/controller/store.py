from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class StateStore:
    """A normal replaceable status file; it is not an authorization record."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Controller status must be an object")
        return value

    def save(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=f"{self.path.name}-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
