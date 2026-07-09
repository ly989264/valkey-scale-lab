# 08_CONTEXT_TRANSFER_PROTOCOL.md

## Required handoff files

Every stage must produce:

```text
runs/m1-hardening/<stage_id>/handoff/CONTEXT_RELOAD.md
runs/m1-hardening/<stage_id>/handoff/DESIGN_BRIEF.md
runs/m1-hardening/<stage_id>/handoff/WORKER_SUMMARY.md
runs/m1-hardening/<stage_id>/handoff/REVIEW.md
runs/m1-hardening/<stage_id>/handoff/COMPLETION.md
runs/m1-hardening/<stage_id>/handoff/NEXT_STAGE_INPUT.md
```

These are not acceptance proof; they are context persistence. The proof is the gate artifacts.

## Required content

Each handoff must record:

- stage id;
- exact commit before and after;
- gate commands executed;
- gate artifact paths;
- evidence claims added/changed;
- blocked claims, if any;
- known risks for the next stage.

## Compact safety

The next stage must not rely on chat history. It must reload these files from the repository.
