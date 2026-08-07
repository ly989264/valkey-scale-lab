# Slice 1 map: `runtime_start`

Written before moving any code, so the seam is agreed from evidence rather than
from a reading of the god module's size.

## Why this stage first

The deliverable of the refactor is the backend interface, because that is what
makes M3 possible: `execute_scenario` currently rejects `native_multi_ecs` from
inside `docker_runtime.py`, so a second backend cannot exist without either
living in the Docker module or duplicating it.

An interface takes the shape of whatever stage it is derived from.
`runtime_start` is the stage that exercises the real primitives - process start,
node inspection, ownership registration, cleanup binding - so deriving it here
means deriving it from the hardest case rather than the most convenient one.

## Where the stage begins and ends

The boundary is already a contract. `REQUIRED_SETUP_SEGMENTS` in
`runtime/setup_timeline.py` fixes the segment order, and the measured lifecycle
attributes segments to stages. `runtime_start` runs from `setup_entry` through
`state_write_before_cluster`; `cluster_form` begins at `primary_cluster_create`.

Observed in the green exact-50 baseline (`lifecycle_timeline.json`,
`runtime_start`, 1896.9 ms, PASS):

    setup_entry                     config_parse_and_validate
    node_spec_generation            port_preflight_check
    custom_valkey_image_preflight   resource_preflight
    pre_cleanup_by_label            docker_network_create
    nodehost_plan                   nodehost_start
    node_config_local_generate      nodehost_bundle_write
    docker_cp_bundle                nodehost_bundle_install
    nodehost_start_all              pidfile_collect
    process_ready_wait              state_write_before_cluster

These names are evidence consumed downstream. The extraction must keep them and
their order identical; the artifact diff in the acceptance bar checks exactly
that.

## Where the code lives today

| Segments | Location |
| --- | --- |
| `setup_entry` .. `custom_valkey_image_preflight` | `_execute_runtime()` |
| `resource_preflight` .. `nodehost_start` | `_create_process_scenario()` |
| `node_config_local_generate` .. `nodehost_bundle_install` | `_prepare_process_nodehost_bundles()` |
| `nodehost_start_all` .. `process_ready_wait` | `_start_process_nodes_batched()` |
| `state_write_before_cluster` | `_create_process_scenario()` |

The stage is therefore already factored into four helpers plus the sequencing
around them. The sequencing, the timeline segments and the state write belong to
the lifecycle; the four helpers are the backend.

## The backend operations this stage needs

Derived by enumerating what the regions above actually call, not designed ahead
of use:

- verify the pinned runtime image
- clean up anything this run owns from a previous attempt
- create the run's network
- start a nodehost and report its address
- install a prepared bundle onto a nodehost
- start the node processes on a nodehost and report their pids
- wait until the started processes answer

Planning which nodes live on which nodehost is not I/O and stays in the
lifecycle. `native_multi_ecs` replaces the seven operations above and nothing
else.

Two of the seven are a pair of calls rather than one, observed while extracting
them. The lifecycle sends every bundle before installing any, and starts every
nodehost before collecting any pid; those barriers are exactly what the
`docker_cp_bundle` / `nodehost_bundle_install` and `nodehost_start_all` /
`pidfile_collect` segments measure. Fusing either pair inside a backend would
erase evidence the acceptance diff checks, so `NodeBackend` in
`runtime/node_backend.py` states them as nine methods for the seven operations.

## What the slice changed

`runtime/node_backend.py` holds `NodeBackend` and `NodehostAddress` and depends
on nothing. `DockerNodeBackend` in `docker_runtime.py` is the one implementation;
it absorbed `_start_nodehost`, the bundle copy and install helpers, the two
inline `docker exec` closures of the process start, and the ready-wait loop, so
none of those survive as a second path.

The lifecycle sequencing stays in `_create_process_scenario` for now. The same
function still runs `cluster_form` and everything after it, and those stages
still call Docker directly, so moving the file before they are converted would
split one function across two modules. What this slice fixes is the direction of
the dependency inside the stage: `runtime_start` no longer names a Docker
primitive, and a hermetic test drives it with a recording backend while
`run_docker` raises.

## Blast radius

One test file imports the four helpers
(`tests/integration/test_docker_runtime_contract.py`). Direct Docker calls
inside the stage regions reduce to `_verify_custom_valkey_image`,
`cleanup_by_label`, `_start_nodehost` and `_container_ip`; everything else is
already behind the helpers.

## Acceptance for this slice

Per the agreed bar: hermetic tests and targeted tests pass; a real six-node
smoke; real exact-50 with normalised stage-owned artifacts diffed against
`artifacts/baselines/exact-50-6b6f57fd` ignoring timestamps, durations, run ids
and temporary paths; exact-200 as well, because `runtime_start` is one of the
three stages that requires it; and the old path proven removed, with no
fallback and no duplicate implementation.

Stage-owned artifacts for the diff: the `runtime_start` entry of
`lifecycle_timeline.json`, the `nodehost_start` / `process_config_prepare` /
`process_start` / `process_ready_wait` rows of
`runtime_timing_breakdown_local_full_flow.json`, `nodehost_density_plan.json`,
`generated_valkey_configs_manifest.json`, the nodehost bundle manifests, and
`state.json` as written before cluster formation.
