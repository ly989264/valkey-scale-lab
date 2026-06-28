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
