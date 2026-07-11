# Codex App Goal-Mode Start Prompt

Use this repository's `META_M1_START.md` control loop to complete Milestone 1.
Continue automatically until the controller returns `DONE` or a genuine
`BLOCKED` result.

For every iteration:

1. Run `PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop next`.
2. For `WORK`, read only its contract clauses, context paths, and last program
   failure. Use your own engineering judgment to inspect and implement the best
   solution. You may add focused tests and refactor within the objective. Do not
   edit controller state or weaken a check. Run focused cheap diagnostics as
   useful, then run `PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop evaluate`.
3. For `REVIEW_ACCEPTANCE`, launch a fresh reviewer with the work item, frozen
   clauses, relevant diff, and program log paths. Ask only whether an in-scope
   requirement is not checked by the program. It must return `NO_GAP`, or one
   concrete `GAP` with an exact clause and a failing level 0-2 check. It may add
   one test-only reproduction when necessary, but must not implement the fix.
   Store its JSON report outside historical evidence and submit it with
   `PYTHONPATH=src python3 -m valkey_scale_lab.meta_loop review --report <path>`.
4. For `REVIEW_REPLAN`, launch a fresh reviewer to diagnose the repeated failure
   from code and logs. It must return `diagnosis` and a non-empty
   `recommended_focus`; it must not implement or expand scope. Submit the JSON.
5. For `DONE`, stop and summarize admitted checks and evidence paths. For
   `BLOCKED`, stop and report the exact exhausted objective and external action
   needed. Never convert resource failure into success.

Keep context lean: do not reread historical stage packs, paste full logs, or
recap completed objectives. Use paths and the controller's bounded excerpts.
Never launch real 30, 50, 100, 200, or above-200 runs outside controller-owned
checks. The required real gates are exactly 50 and 200; 30 and 100 are supported
capabilities, not completion gates. Real execution above 200 needs explicit
human opt-in, preflight, and cost acknowledgement.

Acceptance review JSON:

```json
{"work_item_id":"...","decision":"NO_GAP"}
```

or:

```json
{
  "work_item_id":"...",
  "decision":"GAP",
  "contract_clause":"exact clause from the work item",
  "finding":"observable unmet behavior",
  "program_check":{
    "id":"unique-check-id",
    "level":1,
    "command":["python3","-m","pytest","-q","tests/path/test_gap.py"],
    "timeout_seconds":1200,
    "inputs":["src/relevant","tests/path/test_gap.py"]
  }
}
```

Replan review JSON:

```json
{"work_item_id":"...","diagnosis":"root cause","recommended_focus":["different approach"]}
```
