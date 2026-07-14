from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


AUTHORITY_SCHEMA = "vpro2-authority-envelope-v1"
AUTHORITY_DOMAIN = b"vpro2-authority-envelope-v1\0"


class Authority(str, Enum):
    CONTROLLER = "CONTROLLER"
    WORKER = "WORKER"
    REVIEWER = "REVIEWER"
    EVALUATOR = "EVALUATOR"
    OPERATOR = "OPERATOR"


class AuthorityError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedEnvelope:
    role: Authority
    action: str
    nonce: str
    payload: dict[str, Any]
    key_id: str


class AuthorityVerifier:
    """Verify role-bound messages without exposing a signing operation."""

    def __init__(self, keys: Mapping[Authority | str, bytes]):
        normalized: dict[Authority, bytes] = {}
        for raw_role, key in keys.items():
            try:
                role = Authority(raw_role)
            except ValueError as exc:
                raise AuthorityError(f"unknown authority role {raw_role!r}") from exc
            if not isinstance(key, bytes) or len(key) < 32:
                raise AuthorityError(f"{role.value} authority key must contain at least 32 bytes")
            normalized[role] = key
        missing = [role.value for role in Authority if role not in normalized]
        if missing:
            raise AuthorityError(f"missing authority keys: {missing}")
        fingerprints = [hashlib.sha256(key).hexdigest() for key in normalized.values()]
        if len(fingerprints) != len(set(fingerprints)):
            raise AuthorityError("each authority must use a distinct key")
        self._keys = normalized

    @property
    def key_ids(self) -> dict[str, str]:
        return {
            role.value: hashlib.sha256(key).hexdigest()
            for role, key in self._keys.items()
        }

    def verify(
        self,
        envelope: Mapping[str, Any],
        *,
        run_id: str,
        expected_role: Authority,
        expected_action: str,
        now: int | None = None,
    ) -> VerifiedEnvelope:
        required = {
            "schema_version",
            "run_id",
            "role",
            "action",
            "nonce",
            "issued_at_unix",
            "expires_at_unix",
            "payload",
            "hmac_sha256",
        }
        if set(envelope) != required:
            missing = sorted(required - set(envelope))
            extra = sorted(set(envelope) - required)
            raise AuthorityError(f"invalid authority envelope fields: missing={missing}, extra={extra}")
        if envelope["schema_version"] != AUTHORITY_SCHEMA:
            raise AuthorityError("unsupported authority envelope schema")
        if envelope["run_id"] != run_id:
            raise AuthorityError("authority envelope is bound to another run")
        if envelope["role"] != expected_role.value:
            raise AuthorityError(f"{expected_role.value} authority is required")
        if envelope["action"] != expected_action:
            raise AuthorityError("authority envelope is bound to another action")
        nonce = envelope["nonce"]
        if not isinstance(nonce, str) or not nonce or len(nonce) > 256:
            raise AuthorityError("authority envelope nonce is invalid")
        issued = envelope["issued_at_unix"]
        expires = envelope["expires_at_unix"]
        if not isinstance(issued, int) or isinstance(issued, bool):
            raise AuthorityError("issued_at_unix must be an integer")
        if not isinstance(expires, int) or isinstance(expires, bool) or expires <= issued:
            raise AuthorityError("expires_at_unix must be later than issued_at_unix")
        current = int(time.time()) if now is None else now
        if issued > current + 60:
            raise AuthorityError("authority envelope was issued in the future")
        if current >= expires:
            raise AuthorityError("authority envelope has expired")
        payload = envelope["payload"]
        if not isinstance(payload, dict):
            raise AuthorityError("authority envelope payload must be an object")
        claimed = envelope["hmac_sha256"]
        if not isinstance(claimed, str) or len(claimed) != 64:
            raise AuthorityError("authority envelope tag is invalid")
        unsigned = {key: value for key, value in envelope.items() if key != "hmac_sha256"}
        encoded = json.dumps(unsigned, separators=(",", ":"), sort_keys=True).encode()
        key = self._keys[expected_role]
        expected = hmac.new(key, AUTHORITY_DOMAIN + encoded, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(claimed, expected):
            raise AuthorityError("authority envelope authentication failed")
        return VerifiedEnvelope(
            role=expected_role,
            action=expected_action,
            nonce=nonce,
            payload=dict(payload),
            key_id=hashlib.sha256(key).hexdigest(),
        )


def unsigned_envelope(
    *,
    run_id: str,
    role: Authority,
    action: str,
    nonce: str,
    payload: Mapping[str, Any],
    issued_at_unix: int,
    expires_at_unix: int,
) -> dict[str, Any]:
    """Build canonical unsigned material for an external authority signer."""

    return {
        "schema_version": AUTHORITY_SCHEMA,
        "run_id": run_id,
        "role": role.value,
        "action": action,
        "nonce": nonce,
        "issued_at_unix": issued_at_unix,
        "expires_at_unix": expires_at_unix,
        "payload": dict(payload),
    }
