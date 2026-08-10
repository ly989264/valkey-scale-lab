"""Verify the pinned native build products a host runs Valkey from.

This is `verify_image`'s counterpart for a backend whose hosts have no image.
Under Docker the pinned binaries arrive inside the runtime image and
`_verify_custom_valkey_image` checks them there; a host that is only a host
receives them as a bundle instead, and this is the check that says whether the
bundle it received is the one the pinned build produced.

Nothing here knows what a host is, how a bundle gets to one, or what installs
it. It answers one question about a directory on this machine, before anything
is shipped: do these files still hash to what their manifest says, and does the
manifest still describe the pinned build? §15 requires digest-verified build
products; that requirement has no transport in it.

The returned mapping is preflight evidence in the shape the run already
consumes. `valkey_server_sha256` is not a convention: `_write_cluster_myslots_
report` reads exactly that key off the preflight result and stamps it on every
observed node, and `scripts/diff_stage_artifacts.py` carries the whole mapping
into the `runtime_start` diff view. A native preflight that named the field
something else would silently drop the digest out of the run's evidence.

`scripts/build_native_bundle.py` produces what this reads.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

BUNDLE_MANIFEST_NAME = "bundle_manifest.json"
BUNDLE_MANIFEST_ARTIFACT_TYPE = "native_build_bundle"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: Every binary a host needs, and the manifest key each one's digest is under.
#: The two Valkey binaries are the run's own; memtier is the Load Lane's, which
#: §8 fixes as the tool, and it runs on a host because the cluster announces
#: addresses the controller may not be able to route.
BUNDLE_BINARY_DIGEST_KEYS = {
    "valkey-server": "valkey_server_sha256",
    "valkey-cli": "valkey_cli_sha256",
    "memtier_benchmark": "memtier_benchmark_sha256",
}

_REQUIRED_MANIFEST_KEYS = (
    "architecture",
    "archive",
    "artifact_type",
    "binaries",
    "memtier_source_sha256",
    "memtier_version",
    "patch_sha256",
    "schema_version",
    "source_sha256",
    "valkey_version",
)


class NativeBundleError(RuntimeError):
    """The bundle is not the pinned build, or is not intact."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NativeBundleError(message)


def _read_manifest(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / BUNDLE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise NativeBundleError(
            f"native bundle {bundle_dir} has no {BUNDLE_MANIFEST_NAME}; "
            "build it with scripts/build_native_bundle.py"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise NativeBundleError(f"{manifest_path} is not readable JSON: {error}") from error
    _require(isinstance(manifest, dict), f"{manifest_path} must contain an object")
    missing = [key for key in _REQUIRED_MANIFEST_KEYS if key not in manifest]
    _require(not missing, f"{manifest_path} is missing {missing}")
    _require(
        manifest["artifact_type"] == BUNDLE_MANIFEST_ARTIFACT_TYPE,
        f"{manifest_path} is a {manifest['artifact_type']!r}, not a {BUNDLE_MANIFEST_ARTIFACT_TYPE!r}",
    )
    return manifest


def verify_native_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Check a built bundle against its manifest and return preflight evidence.

    Raises `NativeBundleError` on any mismatch, missing file or malformed
    digest. It returns only when every recorded digest was recomputed from the
    bytes on disk and matched.
    """
    root = Path(bundle_dir)
    _require(root.is_dir(), f"native bundle directory {root} does not exist")
    manifest = _read_manifest(root)

    binaries = manifest["binaries"]
    _require(isinstance(binaries, dict), "bundle manifest `binaries` must be an object")
    missing = sorted(set(BUNDLE_BINARY_DIGEST_KEYS) - set(binaries))
    _require(not missing, f"bundle manifest does not describe {missing}")

    evidence_digests: dict[str, str] = {}
    for name, digest_key in sorted(BUNDLE_BINARY_DIGEST_KEYS.items()):
        record = binaries[name]
        _require(isinstance(record, dict) and "path" in record and "sha256" in record,
                 f"bundle manifest entry for {name} needs `path` and `sha256`")
        recorded = str(record["sha256"])
        _require(bool(SHA256_RE.fullmatch(recorded)), f"{name} has a malformed sha256 in the bundle manifest")
        member = root / str(record["path"])
        _require(member.is_file(), f"bundle is missing {record['path']}")
        actual = sha256_file(member)
        if actual != recorded:
            raise NativeBundleError(
                f"{name} does not match the pinned build: manifest {recorded}, bundle {actual}"
            )
        evidence_digests[digest_key] = recorded

    archive = manifest["archive"]
    _require(isinstance(archive, dict) and "path" in archive and "sha256" in archive,
             "bundle manifest `archive` needs `path` and `sha256`")
    archive_recorded = str(archive["sha256"])
    _require(bool(SHA256_RE.fullmatch(archive_recorded)), "the archive has a malformed sha256")
    archive_path = root / str(archive["path"])
    _require(archive_path.is_file(), f"bundle is missing its archive {archive['path']}")
    archive_actual = sha256_file(archive_path)
    if archive_actual != archive_recorded:
        raise NativeBundleError(
            f"the bundle archive does not match its manifest: manifest {archive_recorded}, "
            f"bundle {archive_actual}"
        )

    return {
        "bundle": manifest.get("bundle_name", root.name),
        "bundle_dir": root.as_posix(),
        "architecture": manifest["architecture"],
        "valkey_version": manifest["valkey_version"],
        "source_sha256": manifest["source_sha256"],
        "patch_sha256": manifest["patch_sha256"],
        "memtier_version": manifest["memtier_version"],
        "memtier_source_sha256": manifest["memtier_source_sha256"],
        "archive_sha256": archive_recorded,
        "verified": ["archive_sha256", "binary_sha256"],
        # The Docker preflight starts the server and asks it for CLUSTER
        # MYSLOTS. This one cannot: the bundle holds the host platform's
        # binaries and the controller may not be able to execute them. Saying
        # so is the point - a preflight that reported the command verified
        # because its Docker sibling does would be fabricating the one piece of
        # evidence the patched build exists for.
        "not_verified": {
            "cluster_myslots_command": (
                "the bundle carries host-platform binaries the controller need not be able "
                "to run; executing one and asking it for CLUSTER MYSLOTS is a host-side check"
            )
        },
        "status": "PASS",
        **evidence_digests,
    }
