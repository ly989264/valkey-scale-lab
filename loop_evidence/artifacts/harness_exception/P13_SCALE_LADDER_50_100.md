# P13 Harness Exception: Real Valkey Membership Guard

## Defect

`scripts/valkey_probe_lib.py` treated a real Valkey scale gate as healthy when at least
`--min-nodes` endpoints responded and any responding endpoint reported `cluster_state=ok`.
That allowed a fragmented scale run to pass when many small Valkey clusters were alive, even
though no endpoint observed the required 50-node or 100-node membership domain.

The same gap existed in the scale rung artifact view: `write_scale_ladder_artifacts()` recorded
`cluster_known_nodes_expected` but did not record or enforce the observed `cluster_known_nodes`
value for each node.

## Patch

The probe guard now requires each counted endpoint to report:

- `status=PASS`
- `cluster_state=ok`
- `cluster_known_nodes >= --min-nodes`
- at least `--min-nodes` entries in `CLUSTER NODES`
- no `fail`, `handshake`, or `noaddr` flags
- connected cluster links

The scale rung artifact now records `cluster_known_nodes_observed`, `cluster_known_nodes_min`,
and `cluster_known_nodes_max`, and marks the rung `FAIL` unless every sampled node observes the
expected node count.

`scripts/valkey_e2e_gate.py` now also carries through process-runtime evidence from the state
file: runtime type, nodehost containers, logical node process metadata, role counts, cluster
snapshots, data-path result, and cleanup report path. This strengthens the real gate by making
the P13 docker-contained process-per-node runtime auditable without relying on artifact presence
alone.

## Before/After Behavior

Before: 100 reachable Valkey endpoints split into 4-node or 6-node clusters could satisfy the
wrapper because all endpoints responded and at least one small cluster reported `ok`.

After: the same fragmented run fails because no endpoint proves full 50-node or 100-node
membership. The artifact view also fails the rung instead of reporting only the expected count.
For the process runtime, a run is only credible when the evidence shows the expected Valkey
process count, primary/replica role counts, clean cluster snapshots, data-path PASS, and cleanup
PASS.

---

# P13 Harness Exception Addendum: Two-Virtual-AZ Scale Templates

## Defect

The locked P13 scale templates, `templates/configs/scale_50.yaml` and
`templates/configs/scale_100.yaml`, declared three virtual AZs. The updated operating
requirement permits only two virtual AZs in multi-AZ mode, with each shard primary and replica
in different AZs.

## Patch

The P13 scale templates now declare only `az-a` and `az-b`. Runtime scale scenarios continue to
use Docker-contained process execution, but now create exactly one owned nodehost container per
virtual AZ. All Valkey processes are started before cluster membership, slot assignment, and
replica binding.

## Before/After Behavior

Before: P13 scale rungs grouped logical nodes across three AZ nodehost containers.

After: P13 scale rungs group logical nodes across two AZ nodehost containers. Primary placement
alternates by shard, and each replica is assigned to the opposite AZ.

## Gate Impact

`codex/gate_lock.json` was updated after this addendum so global precheck and postcheck keep
enforcing the protected template baseline. The new baseline records the two-AZ scale templates
that strengthen the requested safety/placement constraint.

---

# P13 Harness Exception Addendum: Probe Performance and Timing Evidence

## Defect

The locked P13 real Valkey wrapper and probe library produced correct full-membership evidence,
but did so with avoidable scale overhead:

- `scripts/valkey_probe_lib.py` opened one TCP connection per probe command and probed every
  endpoint on every convergence iteration.
- `scripts/valkey_e2e_gate.py` did not emit machine-readable timing breakdowns for runtime
  startup, cluster creation, wrapper proof, data-path proof, and cleanup.

This made P13 50-node and 100-node gates slower and harder to compare without strengthening the
real evidence.

## Patch

The probe library now keeps the full-membership correctness checks but probes representative
endpoints during convergence, performs one final full-node validation for the proof, and collects
full-node diagnostic snapshots on failure. Each endpoint probe uses one TCP connection with a
pipelined `PING`, `INFO server`, `CLUSTER INFO`, and `CLUSTER NODES` sequence.

The P13 wrapper now merges runtime and wrapper timings into
`artifacts/phases/P13_SCALE_LADDER_50_100/p13_timing_breakdown_<scenario>.json`, including:

- `nodehost_start`
- `process_config_prepare`
- `process_start`
- `process_ready_wait`
- `primary_cluster_create`
- `replica_meet`
- `replica_replicate`
- `runtime_representative_probe`
- `runtime_final_full_probe`
- `wrapper_wait_cluster_ok`
- `wrapper_data_path_probe`
- `cleanup`

## Before/After Behavior

Before: wrapper convergence repeatedly issued full-node `CLUSTER NODES` probes and opened
separate TCP connections for each command. Replica configuration in the large process runtime was
serial.

After: wrapper convergence uses representative probes, one full final proof, diagnostic full
snapshots only on failure, and pipelined endpoint probes. Large process-runtime replica
configuration uses bounded parallelism while retaining final role-count and full-membership
validation.

## Gate Impact

`codex/gate_lock.json` is updated after this addendum so precheck and postcheck enforce the new
strengthened wrapper baseline rather than treating the intentional probe and timing changes as
unreviewed harness drift.
