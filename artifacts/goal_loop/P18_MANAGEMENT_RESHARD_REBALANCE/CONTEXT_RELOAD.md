# CONTEXT_RELOAD — P18_MANAGEMENT_RESHARD_REBALANCE

Date: 2026-07-02T17:00:00Z
Branch: codex/valkey-scale-lab-loop

## Current stage

`python3 scripts/codex_gate.py next` returns `P18_MANAGEMENT_RESHARD_REBALANCE`.

P15, P16, and P17 are complete. P17 was committed and pushed as `d854837 P17_MANAGEMENT_REMOVE_NODE: add real remove-node matrix`.

## Required P18 rows

- `reshard_slot_range` on 6 nodes
- `reshard_slot_range` on 10 nodes
- `reshard_with_keys` on 6 nodes
- `reshard_with_keys` on 10 nodes
- `rebalance_after_imbalance` on 6 nodes
- `rebalance_after_imbalance` on 10 nodes

## P17 reusable foundation

P17 added a P17-only management matrix runner in `src/valkey_scale_lab/runtime/docker_runtime.py` with sidecar 6-node and 10-node real Valkey runs, command logs, topology snapshots, workload windows, quant summary, cleanup summaries, and strengthened `scripts/assert_management_ops_coverage.py`.

For P18, reuse the P17 pattern where appropriate, but do not claim no-op rebalance as PASS. P18 must prove positive slot movement, moved-slot key readability/writability, complete slot coverage after convergence, measurable imbalance reduction, workload impact rows, and cleanup.

## Latest verification before P18

- P17 gate: `artifacts/gates/P17_MANAGEMENT_REMOVE_NODE/gate_result.json` status PASS.
- P17 review: `artifacts/goal_loop/P17_MANAGEMENT_REMOVE_NODE/REVIEW.md` contains `Decision: PASS`.
- P17 postcheck and mark-complete passed.
- Current working tree was clean and synced with origin before this P18 context file was created.

## Safety reminders

- Do not use host network/firewall/routing/interface mutation.
- Use owned Docker/container resources only.
- Do not downscope required 10-node rows.
- If 10-node real execution is blocked by resources, write `BLOCKED.md` and stop rather than passing.
