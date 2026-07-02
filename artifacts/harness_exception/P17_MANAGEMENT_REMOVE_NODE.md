# P17 Harness Exception

## Defect

`scripts/assert_management_ops_coverage.py` only required P17 operation names, so the phase could have passed with `remove_replica`, `remove_primary_drained`, and `remove_failed_node` rows from one node count only.

## Patch

The assertion now requires the exact P17 matrix rows for 6 and 10 nodes:

- `remove_replica` on 6 and 10 nodes
- `remove_primary_drained` on 6 and 10 nodes
- `remove_failed_node` on 6 and 10 nodes

For each required PASS row it also checks real execution, timing fields, removed-node absence, full slot coverage, expected node-count reduction, removed-resource cleanup, sidecar cleanup, removed node id, and target logical id.

After an intermediate real run exposed a stale before-state view, the patch was tightened further so PASS rows must prove both `cluster_state_before=ok` and `slots_before=16384` before removal, plus `cluster_state_after=ok` and `slots_after=16384` after removal.

## Before/After

Before: a fake or partial P17 matrix could satisfy operation-name coverage without proving 10-node execution.

After: P17 cannot pass unless all six required operation/node-count rows are present and independently verified as real PASS rows that start from and return to a clean full-slot cluster view.
