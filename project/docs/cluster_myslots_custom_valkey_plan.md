# CLUSTER MYSLOTS Custom Valkey Implementation Plan

## Status

Implemented and accepted on 2026-07-27.

- Patched Valkey tests: 11 passed.
- Project pytest: 729 passed, 4 skipped.
- Repository Gate: 90/90 passed with no skips.
- Real 50-node full-flow Gate: passed with 25 primary/replica shards,
  complete 16,384-slot coverage, matching replica bitmaps, and no cleanup
  residuals.

## Objective

Replace the product's default `valkey/valkey:9.1.0` runtime image with a
repository-built Valkey 9.1.0 image that adds `CLUSTER MYSLOTS`.

The work is complete only after the custom image passes focused tests and one
real, exact 50-node local full-flow run. Fixtures, dry runs, and smaller
clusters do not satisfy the final acceptance requirement.

## Fixed Decisions

- Command name: `CLUSTER MYSLOTS`.
- The command is a normal, read-only `CLUSTER` subcommand with no arguments.
- The response describes the shard containing the contacted node.
- The slot bitmap is exactly 16,384 bits / 2,048 bytes.
- Slot `N` maps to `bitmap[N >> 3] & (1 << (N & 7))` (`lsb0`).
- A primary returns its own slot bitmap.
- A replica returns the bitmap of its locally known `replicaof` primary.
- A disconnected replica may return its local cluster view.
- A replica with `replicaof == NULL` returns an error, never a zero bitmap.
- RESP2 and RESP3 are both supported.
- Version 1 does not include a global topology digest.
- No A/B performance experiment is required.

## Response Contract

The logical response contains exactly these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `node-id` | 40-byte string | ID of the contacted node |
| `shard-id` | 40-byte string | ID of the node's shard |
| `role` | string | `primary` or `replica` |
| `slot-owner-id` | 40-byte string | ID of the shard primary supplying the bitmap |
| `slot-count` | integer | Number of set bits in the bitmap |
| `bitmap-encoding` | string | Always `lsb0` |
| `slot-bitmap` | binary bulk string | Exactly 2,048 bytes |

RESP3 returns a map. RESP2 returns an ordered, alternating key/value array with
the same logical fields. The bitmap remains a binary-safe bulk string in both
protocol versions.

The command registration follows the neighboring cluster introspection
commands:

- arity: `2`
- complexity: `O(1)` because the response size is fixed
- flags: `LOADING`, `STALE`
- command tip: `NONDETERMINISTIC_OUTPUT`
- ACL category: `SLOW`

## Repository Deliverables

Add the following product-owned build inputs:

```text
project/patches/valkey/0001-add-cluster-myslots.patch
project/docker/valkey-custom/Dockerfile
project/scripts/build_valkey_image.sh
```

The patch contains the Valkey source changes and upstream-style Valkey tests.
The Dockerfile is the only build recipe. The script is a short, deterministic
wrapper around `docker build`.

Update every runnable config template under `project/templates/configs/` from:

```text
valkey/valkey:9.1.0
```

to:

```text
valkey-scale-lab/valkey:9.1.0-myslots
```

Do not add the Valkey source tree to this repository.

## Docker Build

Use a multi-stage Dockerfile with three targets.

### `builder`

1. Download the fixed Valkey 9.1.0 release archive over HTTPS.
2. Verify its pinned SHA-256 before extraction.
3. Copy the repository patch into the build.
4. Apply it with fuzz disabled so source drift fails the build.
5. Compile `valkey-server` and `valkey-cli`.
6. Run a binary/version smoke check.
7. Record the source, patch, and binary digests in a build manifest.

### `runtime`

Start from the compatible official Valkey 9.1.0 runtime image, replace
`valkey-server` and `valkey-cli` with the patched binaries, and attach OCI
labels containing:

- upstream Valkey version
- upstream source SHA-256
- patch SHA-256
- `valkey-server` SHA-256
- `valkey-cli` SHA-256

The resulting local image is:

```text
valkey-scale-lab/valkey:9.1.0-myslots
```

### `binaries`

Expose the same compiled binaries and manifest as a BuildKit local-output
target. This is preparation for the later native multi-ECS runtime; it does
not implement ECS distribution now.

## Runtime Integration

Real execution must perform a preflight before creating any cluster resource:

1. Inspect the configured image locally.
2. Fail with an actionable build command if the custom image is missing.
3. Verify the expected build labels and binary digest.
4. Verify that `CLUSTER MYSLOTS` is registered.
5. Never compile during `gate execute`.
6. Never silently fall back to `valkey/valkey:9.1.0`.

The operator explicitly builds once:

```bash
./project/scripts/build_valkey_image.sh
```

Subsequent runs reuse the verified image.

## Valkey Source Work

The patch should make the smallest upstream-shaped change:

1. Add `src/commands/cluster-myslots.json`.
2. Add the command handler and `CLUSTER` dispatch in the appropriate cluster
   implementation file.
3. Select `myself` for a primary or `myself->replicaof` for a replica.
4. Reject a replica without a known primary.
5. Emit metadata and copy exactly `CLUSTER_SLOTS / 8` bitmap bytes.
6. Preserve a single point-in-time local view while constructing the response.
7. Add Valkey cluster tests for command registration, bit mapping, roles,
   replica behavior, RESP2, RESP3, and error handling.

## Verification Ladder

Run checks in this order and stop on the first failure:

1. Patch applies cleanly with zero fuzz.
2. Valkey compilation succeeds.
3. Patched Valkey command and cluster tests pass.
4. Custom image reports the expected Valkey version and digests.
5. Scale Lab configuration, unit, and Docker contract tests pass.
6. A small real smoke cluster proves the image can form a cluster.
7. The exact real 50-node acceptance run passes.

## Required Real 50-Node Acceptance

The final acceptance command is the registered real gate:

```bash
cd project
./gate test real.local.full-flow \
  --param nodes=50 \
  --param config=templates/configs/scale_50.yaml
```

The run has 25 primary/replica shards and must use only the custom image. In
addition to the existing full-flow contract, capture and validate a
`CLUSTER MYSLOTS` report with these conditions:

1. Exactly 50 real Valkey processes are independently observed.
2. Every process reports the patched Valkey binary digest.
3. Every `slot-bitmap` is exactly 2,048 bytes.
4. Every `slot-count` equals the bitmap population count.
5. Each replica bitmap exactly matches its shard primary bitmap.
6. Each replica reports its own `node-id` and its primary's
   `slot-owner-id`.
7. The 25 primary bitmaps are pairwise disjoint.
8. The union of the 25 primary bitmaps covers all 16,384 slots exactly once.
9. Existing cluster health, workload, fault, recovery, evidence, and
   provenance checks remain successful.
10. Cleanup removes every owned container, process, network, and run resource.

A test is not accepted if it downscales, uses a fixture, uses the official
unpatched image, skips the MYSLOTS checks, or leaves cleanup residuals.

## Future Native Multi-ECS Use

The future master/worker ECS controller will consume the Dockerfile's
`binaries` output:

```text
build once
-> package binaries plus manifest
-> publish immutable artifact by digest
-> master dispatches artifact URI and digest
-> workers download, verify, cache, and start native processes
```

Workers must not download Valkey source or compile per run. The transport
choice (for example S3 pull versus controller upload) belongs to the M3
native-multi-ECS implementation and remains unresolved here.

## Risks

- The release archive and runtime base must be ABI compatible.
- The source archive SHA-256 must come from an authoritative release source.
- A Valkey version upgrade requires rebasing and revalidating the patch.
- Binary RESP output requires length-aware tests; string-based assertions are
  insufficient.
- A missing local image must fail before resource creation rather than trigger
  an accidental registry fallback.

## Definition of Done

All repository deliverables exist, the custom image is the default runtime,
all focused checks pass, and the registered exact real 50-node gate completes
with validated MYSLOTS evidence and deterministic cleanup.
