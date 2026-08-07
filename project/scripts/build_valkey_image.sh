#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="${PROJECT_ROOT}/docker/valkey-custom/Dockerfile"
IMAGE="valkey-scale-lab/valkey:9.1.0-myslots"
OUTPUT_DIR="$(mktemp -d)"
trap 'rm -rf "${OUTPUT_DIR}"' EXIT

docker build \
  --file "${DOCKERFILE}" \
  --target binaries \
  --output "type=local,dest=${OUTPUT_DIR}" \
  "${PROJECT_ROOT}"

SERVER_SHA256="$(sed -n 's/^valkey_server_sha256=//p' "${OUTPUT_DIR}/build-manifest.txt")"
CLI_SHA256="$(sed -n 's/^valkey_cli_sha256=//p' "${OUTPUT_DIR}/build-manifest.txt")"
MEMTIER_SHA256="$(sed -n 's/^memtier_benchmark_sha256=//p' "${OUTPUT_DIR}/build-manifest.txt")"
test -n "${SERVER_SHA256}"
test -n "${CLI_SHA256}"
test -n "${MEMTIER_SHA256}"

docker build \
  --file "${DOCKERFILE}" \
  --target runtime \
  --build-arg "VALKEY_SERVER_SHA256=${SERVER_SHA256}" \
  --build-arg "VALKEY_CLI_SHA256=${CLI_SHA256}" \
  --build-arg "MEMTIER_BENCHMARK_SHA256=${MEMTIER_SHA256}" \
  --tag "${IMAGE}" \
  "${PROJECT_ROOT}"

docker image inspect "${IMAGE}" >/dev/null
docker run --rm "${IMAGE}" valkey-server --version
docker run --rm --entrypoint memtier_benchmark "${IMAGE}" --version
