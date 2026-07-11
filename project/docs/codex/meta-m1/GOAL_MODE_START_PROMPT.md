# Codex App Goal-Mode Start Prompt

Resume Milestone 1 through the v3 controller. Continue automatically until it
returns `DONE` or a genuine external `BLOCKED` result.

Start from `project/`:

```bash
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop doctor
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop migrate-v2 --receipt ../loop_evidence/meta_runs/milestone1-v3/migration/v2_snapshot_receipt.json
PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop next
```

For every iteration:

1. `WORK`: solve the current product gap with your own engineering judgment,
   run useful focused diagnostics, then run `... meta_loop evaluate`.
2. `RECOVERY_WORK`: fix only the reported regression, then run `evaluate`.
3. `EVALUATOR_REPAIR`: change only the returned evaluator allowlist. Do not
   modify the already-failing Reviewer test or guard tests. Do
   not change product inputs. Run `... meta_loop accept-evaluator-repair`.
4. `REVIEW_ACCEPTANCE`: launch a fresh reviewer. It returns `NO_GAP`, or one
   in-scope `GAP` with `gap_kind` equal to `PRODUCT_GAP` or `EVALUATOR_GAP`, an
   exact frozen clause, a concrete finding, and one failing Level 0-2 check.
   Repository checks must construct their own fixtures and must not read the
   current loop evidence directory. Submit the JSON with `review --report`.
5. `REVIEW_REPLAN`: use a fresh reviewer for a root-cause diagnosis and a
   materially different `recommended_focus`, then submit it.
6. Repeat `next`. Stop only on `DONE` or `BLOCKED`.

Never edit state, event journals, the Goal Contract, or Controller Kernel.
Never weaken a check. Do not manually repeat 50/200-node runs. Do not modify
historical evidence. Keep full logs on disk and prompts bounded to failure
excerpts and paths.

GAP report example:

```json
{
  "work_item_id": "...",
  "decision": "GAP",
  "gap_kind": "PRODUCT_GAP",
  "contract_clause": "exact clause from the work item",
  "finding": "observable unmet behavior",
  "program_check": {
    "id": "unique-check",
    "level": 1,
    "command": ["python3", "-m", "pytest", "-q", "tests/path/test_gap.py"],
    "timeout_seconds": 1200,
    "inputs": ["src/relevant", "tests/path/test_gap.py"]
  }
}
```
