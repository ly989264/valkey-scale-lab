"""The pinned native bundle's preflight: what it accepts, and what it refuses.

Hermetic. Every bundle here is synthesised from bytes written in the test, so
nothing depends on a build having run. The real build's evidence lives in
`docs/simulated_host_and_native_bundle_map.md`.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from valkey_scale_lab.runtime.native_bundle import (
    BUNDLE_BINARY_DIGEST_KEYS,
    BUNDLE_MANIFEST_ARTIFACT_TYPE,
    BUNDLE_MANIFEST_NAME,
    NativeBundleError,
    verify_native_bundle,
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _make_bundle(root: Path) -> dict[str, object]:
    """A structurally complete bundle whose digests are all correct."""
    payloads = {name: f"{name} bytes".encode("ascii") for name in BUNDLE_BINARY_DIGEST_KEYS}
    (root / "bin").mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (root / "bin" / name).write_bytes(payload)

    archive_path = root / "bundle.tar.gz"
    with archive_path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for name in sorted(payloads):
                archive.add(root / "bin" / name, arcname=f"bin/{name}")

    manifest = {
        "schema_version": "v1",
        "artifact_type": BUNDLE_MANIFEST_ARTIFACT_TYPE,
        "bundle_name": "valkey-9.9.9-test",
        "architecture": "arm64",
        "valkey_version": "9.9.9",
        "source_sha256": "a" * 64,
        "patch_sha256": "b" * 64,
        "memtier_version": "2.5.1",
        "memtier_source_sha256": "c" * 64,
        "binaries": {
            name: {"path": f"bin/{name}", "sha256": _sha256(payload), "mode": "0755"}
            for name, payload in sorted(payloads.items())
        },
        "archive": {"path": "bundle.tar.gz", "sha256": _sha256(archive_path.read_bytes())},
    }
    (root / BUNDLE_MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _rewrite_manifest(root: Path, mutate) -> None:
    manifest = json.loads((root / BUNDLE_MANIFEST_NAME).read_text(encoding="utf-8"))
    mutate(manifest)
    (root / BUNDLE_MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def test_intact_bundle_verifies_and_reports_every_digest(tmp_path: Path) -> None:
    _make_bundle(tmp_path)

    evidence = verify_native_bundle(tmp_path)

    assert evidence["status"] == "PASS"
    assert evidence["valkey_version"] == "9.9.9"
    assert evidence["architecture"] == "arm64"
    for digest_key in BUNDLE_BINARY_DIGEST_KEYS.values():
        assert len(evidence[digest_key]) == 64


def test_preflight_evidence_carries_the_key_the_myslots_report_stamps(tmp_path: Path) -> None:
    """`_write_cluster_myslots_report` reads `valkey_server_sha256` off the
    preflight result and records it on every observed node. A native preflight
    that named it anything else would drop the digest out of the evidence."""
    manifest = _make_bundle(tmp_path)

    evidence = verify_native_bundle(tmp_path)

    assert evidence["valkey_server_sha256"] == manifest["binaries"]["valkey-server"]["sha256"]


def test_preflight_does_not_claim_the_command_check_it_cannot_make(tmp_path: Path) -> None:
    """The Docker preflight starts the server and asks it for CLUSTER MYSLOTS.
    This one hashes bytes on the controller, so the absence is recorded with a
    reason rather than left to look like a pass."""
    _make_bundle(tmp_path)

    evidence = verify_native_bundle(tmp_path)

    assert "cluster_myslots_command" in evidence["not_verified"]
    assert evidence["not_verified"]["cluster_myslots_command"]


def test_a_changed_binary_fails_preflight(tmp_path: Path) -> None:
    _make_bundle(tmp_path)
    target = tmp_path / "bin" / "valkey-server"
    target.write_bytes(target.read_bytes() + b"x")

    with pytest.raises(NativeBundleError, match="valkey-server does not match the pinned build"):
        verify_native_bundle(tmp_path)


def test_a_changed_archive_fails_preflight(tmp_path: Path) -> None:
    _make_bundle(tmp_path)
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(archive.read_bytes() + b"x")

    with pytest.raises(NativeBundleError, match="archive does not match its manifest"):
        verify_native_bundle(tmp_path)


def test_a_missing_binary_fails_preflight(tmp_path: Path) -> None:
    _make_bundle(tmp_path)
    (tmp_path / "bin" / "memtier_benchmark").unlink()

    with pytest.raises(NativeBundleError, match="bundle is missing bin/memtier_benchmark"):
        verify_native_bundle(tmp_path)


def test_a_bundle_that_omits_memtier_fails_preflight(tmp_path: Path) -> None:
    """§8 fixes memtier as the Load Lane's tool, and the lane runs on a host."""
    _make_bundle(tmp_path)
    _rewrite_manifest(tmp_path, lambda manifest: manifest["binaries"].pop("memtier_benchmark"))

    with pytest.raises(NativeBundleError, match="does not describe"):
        verify_native_bundle(tmp_path)


def test_a_malformed_digest_fails_preflight(tmp_path: Path) -> None:
    _make_bundle(tmp_path)
    _rewrite_manifest(tmp_path, lambda manifest: manifest["binaries"]["valkey-cli"].update({"sha256": "not-a-digest"}))

    with pytest.raises(NativeBundleError, match="malformed sha256"):
        verify_native_bundle(tmp_path)


def test_a_missing_manifest_names_the_builder(tmp_path: Path) -> None:
    _make_bundle(tmp_path)
    (tmp_path / BUNDLE_MANIFEST_NAME).unlink()

    with pytest.raises(NativeBundleError, match="build_native_bundle.py"):
        verify_native_bundle(tmp_path)


def test_a_manifest_of_another_kind_is_refused(tmp_path: Path) -> None:
    _make_bundle(tmp_path)
    _rewrite_manifest(tmp_path, lambda manifest: manifest.update({"artifact_type": "host_inventory"}))

    with pytest.raises(NativeBundleError, match="not a 'native_build_bundle'"):
        verify_native_bundle(tmp_path)


def test_an_absent_bundle_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(NativeBundleError, match="does not exist"):
        verify_native_bundle(tmp_path / "never-built")
