# 16_FAILURE_MODES.md

Known Codex shortcut patterns to guard against:

- implementing only fixtures;
- implementing only report rendering;
- adding schema fields without runtime writers;
- adding runtime writers without analysis readers;
- analysis readers accepting missing/skipped core metrics as PASS;
- final acceptance using non-empty checks;
- old real evidence used to satisfy new telemetry requirements;
- marking exact 30/50/100/200 as PASS because a small 6-node smoke passed;
- simulated subagents due to usage limits;
- committing before review PASS;
- letting legacy codex gate `unknown phase` be ignored as PASS.

Every stage file contains stage-specific versions of these failure modes.
