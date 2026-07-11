# 06_STAGE_PROTOCOL.md

## Stage entry

At the beginning of every stage, the main agent must:

1. read the docs listed in `00_INDEX.md`;
2. read current repository evidence manifest, if present;
3. read previous stage context reload and completion artifacts;
4. create `runs/m1-hardening/<stage_id>/handoff/CONTEXT_RELOAD.md`;
5. launch a real design subagent.

## Stage work

The worker agent must implement code and tests. Markdown-only changes cannot satisfy any hardening stage except documentation updates required by gates.

## Stage exit

Before commit, the main agent must run:

```text
python3 scripts/m1h/assert_stage_exit.py --stage <stage_id>
```

The script must verify gate result artifacts, review decision, forbidden shortcut scan, and stage-specific gates.

## Stage result classes

- `PASS`: all stage obligations met.
- `BLOCKED_WITH_REASON`: exact-scale real execution cannot be completed in this environment, and gates explicitly identify missing claims.
- `FAIL`: implementation or gate error.

Blocked stages may not be hidden. The final milestone may be blocked; the hardening loop can still pass if it honestly reports blocking claims.
