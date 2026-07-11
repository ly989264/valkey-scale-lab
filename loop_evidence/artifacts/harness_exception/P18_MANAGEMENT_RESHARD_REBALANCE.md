# P18 Harness Exception

## Defect

`scripts/assert_management_ops_coverage.py` previously required only P18 operation names. That was not enough to prove the mandatory 6-node and 10-node rows, positive slot movement, moved-key verification, or non-noop rebalance.

## Patch

The assertion now requires all exact P18 operation/node-count rows:

- `reshard_slot_range` on 6 and 10 nodes
- `reshard_with_keys` on 6 and 10 nodes
- `rebalance_after_imbalance` on 6 and 10 nodes

For each required PASS row it also checks clean before/after cluster state, full slot coverage, positive `slots_moved`, post-move writeability, movement IDs, source/target node IDs, moved-key readability for keyed reshard rows, and measurable imbalance reduction for rebalance rows.

It also validates `reshard_slot_movements.jsonl` and `rebalance_summary.json` and rejects empty or no-op movement evidence.

## Before/After

Before: P18 could have passed with operation-name coverage and placeholder/no-op movement evidence.

After: P18 cannot pass unless all required 6-node and 10-node rows prove real slot movement and the rebalance row reduces a measured imbalance.
