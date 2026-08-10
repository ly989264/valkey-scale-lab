#!/usr/bin/env python3
"""Build the pinned native bundle: the binaries a host runs, and their digests.

Lab tooling. It reuses the pinned image's own `binaries` build stage rather than
compiling anything of its own - that stage already exists, is what the pinned
image is built from, and pins the Valkey source, the CLUSTER MYSLOTS patch and
the memtier source by sha256. Building the bundle any other way would create a
second definition of "the pinned build", which is the one thing a provenance
artifact must not have.

The bundle's digests are cross-checked against the pinned image's build labels
before anything is written. That is the anchor: a manifest verified only against
its own tarball would accept a bundle and a manifest that were corrupted
together, whereas the image's labels were recorded by a build the product
already trusts and preflights on every Docker run.

`valkey_scale_lab.runtime.native_bundle.verify_native_bundle` reads what this
writes, and this script ends by calling it - a builder that cannot produce
something its verifier accepts has not built anything.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from valkey_scale_lab.runtime.native_bundle import (  # noqa: E402
    BUNDLE_BINARY_DIGEST_KEYS,
    BUNDLE_MANIFEST_ARTIFACT_TYPE,
    BUNDLE_MANIFEST_NAME,
    NativeBundleError,
    sha256_file,
    verify_native_bundle,
)

DOCKERFILE = PROJECT_ROOT / "docker" / "valkey-custom" / "Dockerfile"
PINNED_IMAGE = "valkey-scale-lab/valkey:9.1.0-myslots"
LABEL_PREFIX = "org.valkey-scale-lab"
DEFAULT_OUT = PROJECT_ROOT / "artifacts" / "native-bundles"

# A fixed timestamp and owner, so two builds of identical binaries produce an
# identical archive. Without it the archive digest would change every build and
# say nothing about the bytes inside it.
ARCHIVE_MTIME = 0


def _run(argv: list[str], *, timeout: float = 3600.0) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise SystemExit(f"{' '.join(argv[:4])} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def _pinned_image_labels() -> dict[str, str]:
    listed = _run(["docker", "image", "inspect", PINNED_IMAGE, "--format", "{{json .Config.Labels}}"], timeout=120)
    labels = json.loads(listed)
    if not isinstance(labels, dict):
        raise SystemExit(f"{PINNED_IMAGE} carries no build labels; build it with scripts/build_valkey_image.sh")
    return {str(key): str(value) for key, value in labels.items()}


def _parse_build_manifest(text: str) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in text.strip().splitlines() if "=" in line
    )


def _export_binaries(destination: Path) -> None:
    _run(
        [
            "docker",
            "build",
            "--file",
            str(DOCKERFILE),
            "--target",
            "binaries",
            "--output",
            f"type=local,dest={destination}",
            str(PROJECT_ROOT),
        ]
    )


def _reproducible_member(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = ARCHIVE_MTIME
    return info


def build(out_root: Path) -> Path:
    labels = _pinned_image_labels()
    architecture = _run(
        ["docker", "image", "inspect", PINNED_IMAGE, "--format", "{{.Architecture}}"], timeout=120
    ).strip()

    with tempfile.TemporaryDirectory() as staging_name:
        staging = Path(staging_name)
        _export_binaries(staging)
        build_manifest_text = (staging / "build-manifest.txt").read_text(encoding="utf-8")
        build_manifest = _parse_build_manifest(build_manifest_text)

        # The cross-check. A binary whose digest differs from the pinned image's
        # label is not the pinned build, whatever its own manifest says.
        label_by_name = {
            "valkey-server": f"{LABEL_PREFIX}.valkey.server.sha256",
            "valkey-cli": f"{LABEL_PREFIX}.valkey.cli.sha256",
            "memtier_benchmark": f"{LABEL_PREFIX}.memtier.benchmark.sha256",
        }
        digests: dict[str, str] = {}
        for name, label in sorted(label_by_name.items()):
            actual = sha256_file(staging / name)
            expected = labels.get(label)
            if expected != actual:
                raise SystemExit(
                    f"{name} does not match the pinned image: image label {expected}, built {actual}. "
                    "Rebuild the image and the bundle from the same source."
                )
            digests[name] = actual

        version = build_manifest["valkey_version"]
        bundle_name = f"valkey-{version}-memtier-{build_manifest['memtier_version']}-{architecture}"
        bundle_dir = out_root / bundle_name
        bundle_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"{bundle_name}.tar.gz"
        archive_path = bundle_dir / archive_name

        # gzip's own header carries an mtime, so the stream is written with
        # mtime=0 rather than through tarfile's convenience mode.
        with archive_path.open("wb") as raw, gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0
        ) as gz:
            with tarfile.open(fileobj=gz, mode="w") as archive:
                for name in sorted(BUNDLE_BINARY_DIGEST_KEYS):
                    archive.add(staging / name, arcname=f"bin/{name}", filter=_reproducible_member)
                archive.add(
                    staging / "build-manifest.txt",
                    arcname="build-manifest.txt",
                    filter=_reproducible_member,
                )

        for name in BUNDLE_BINARY_DIGEST_KEYS:
            target = bundle_dir / "bin" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((staging / name).read_bytes())
            target.chmod(0o755)
        (bundle_dir / "build-manifest.txt").write_text(build_manifest_text, encoding="utf-8")

    manifest: dict[str, Any] = {
        "schema_version": "v1",
        "artifact_type": BUNDLE_MANIFEST_ARTIFACT_TYPE,
        "bundle_name": bundle_name,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "architecture": architecture,
        "valkey_version": version,
        "source_sha256": build_manifest["source_sha256"],
        "patch_sha256": build_manifest["patch_sha256"],
        "memtier_version": build_manifest["memtier_version"],
        "memtier_source_sha256": build_manifest["memtier_source_sha256"],
        "pinned_image": PINNED_IMAGE,
        "binaries": {
            name: {"path": f"bin/{name}", "sha256": digests[name], "mode": "0755"}
            for name in sorted(BUNDLE_BINARY_DIGEST_KEYS)
        },
        "archive": {
            "path": archive_name,
            "sha256": sha256_file(archive_path),
            "size_bytes": archive_path.stat().st_size,
            "members": ["bin/memtier_benchmark", "bin/valkey-cli", "bin/valkey-server", "build-manifest.txt"],
        },
    }
    (bundle_dir / BUNDLE_MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    evidence = verify_native_bundle(bundle_dir)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print(f"bundle: {bundle_dir}")
    return bundle_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where bundles are written")
    parser.add_argument(
        "--verify-only",
        type=Path,
        default=None,
        help="verify an existing bundle directory instead of building one",
    )
    args = parser.parse_args(argv)
    try:
        if args.verify_only is not None:
            print(json.dumps(verify_native_bundle(args.verify_only), indent=2, sort_keys=True))
            return 0
        build(args.out)
    except NativeBundleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
