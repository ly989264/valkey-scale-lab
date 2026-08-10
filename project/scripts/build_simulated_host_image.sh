#!/usr/bin/env bash
# Build the simulated ECS instance image and record what it was derived from.
#
# Lab tooling. See docker/simulated-host/Dockerfile for why the derivation both
# inherits the pinned image's runtime libraries and removes its Valkey binaries.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="${PROJECT_ROOT}/docker/simulated-host/Dockerfile"
PARENT_IMAGE="${PARENT_IMAGE:-valkey-scale-lab/valkey:9.1.0-myslots}"
IMAGE="${IMAGE:-valkey-scale-lab/simulated-host:debian13-sshd}"
DIGEST_FILE="${PROJECT_ROOT}/docker/simulated-host/image-digests.json"

PARENT_DIGEST="$(docker image inspect "${PARENT_IMAGE}" --format '{{.Id}}')"
test -n "${PARENT_DIGEST}"

docker build \
  --file "${DOCKERFILE}" \
  --build-arg "VALKEY_LAB_IMAGE=${PARENT_IMAGE}" \
  --build-arg "VALKEY_LAB_IMAGE_DIGEST=${PARENT_DIGEST}" \
  --tag "${IMAGE}" \
  "${PROJECT_ROOT}"

IMAGE_DIGEST="$(docker image inspect "${IMAGE}" --format '{{.Id}}')"
test -n "${IMAGE_DIGEST}"

# What the image must have, and what it must not. The absences are the point:
# a host that still carried valkey-server would make a bundle install
# unfalsifiable.
docker run --rm --entrypoint sh "${IMAGE}" -c '
set -eu
test -x /usr/sbin/sshd
command -v ssh-keygen >/dev/null
command -v ip >/dev/null
command -v iptables >/dev/null
command -v python3 >/dev/null
if command -v valkey-server >/dev/null 2>&1; then echo "valkey-server must not be present" >&2; exit 1; fi
if command -v valkey-cli >/dev/null 2>&1; then echo "valkey-cli must not be present" >&2; exit 1; fi
if command -v memtier_benchmark >/dev/null 2>&1; then echo "memtier_benchmark must not be present" >&2; exit 1; fi
if [ -e /usr/local/share/valkey-scale-lab ]; then echo "pinned build manifest must not be present" >&2; exit 1; fi
# Baked-in host keys would give every host in a fleet one fingerprint, which is
# how the first fleet came up before this check existed.
if ls /etc/ssh/ssh_host_* >/dev/null 2>&1; then echo "host keys must not be baked into the image" >&2; exit 1; fi
'

SSHD_VERSION="$(docker run --rm --entrypoint sh "${IMAGE}" -c '/usr/sbin/sshd -V 2>&1 | head -1')"
IPTABLES_VERSION="$(docker run --rm --entrypoint iptables "${IMAGE}" --version)"
OS_RELEASE="$(docker run --rm --entrypoint sh "${IMAGE}" -c '. /etc/os-release && echo "$PRETTY_NAME"')"
ARCH="$(docker image inspect "${IMAGE}" --format '{{.Architecture}}')"

python3 - "${DIGEST_FILE}" <<PY
import json
import sys

path = sys.argv[1]
document = {
    "schema_version": "v1",
    "artifact_type": "simulated_host_image_digests",
    "image": "${IMAGE}",
    "image_digest": "${IMAGE_DIGEST}",
    "architecture": "${ARCH}",
    "os": "${OS_RELEASE}",
    "parent_image": "${PARENT_IMAGE}",
    "parent_digest": "${PARENT_DIGEST}",
    "sshd_version": "${SSHD_VERSION}",
    "iptables_version": "${IPTABLES_VERSION}",
    "removed_from_parent": [
        "/usr/local/bin/valkey-server",
        "/usr/local/bin/valkey-cli",
        "/usr/local/bin/memtier_benchmark",
        "/usr/local/share/valkey-scale-lab",
    ],
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(document, handle, indent=2, sort_keys=True)
    handle.write("\n")
print(json.dumps(document, indent=2, sort_keys=True))
PY
