# Harness Exception: P13O-00_TIMING_ACCOUNTING

## Defect

`scripts/valkey_e2e_gate.py` is a protected harness wrapper, but its P13 timing artifact did not account for the wrapper wall time. The artifact also merged runtime diagnostic full probes into `runtime_final_full_probe`, so a final PASS could still display a FAIL timing entry.

## Patch Scope

The patch strengthens the wrapper output only:

- add explicit gate accounting fields for setup command wall time, log writes, state loading, cleanup command wall time, artifact writes, total wall time, and unattributed time;
- keep `runtime_final_full_probe` separate from `runtime_diagnostic_full_probe`;
- validate the strengthened artifact in the new P13O post-loop gate.

## Before Behavior

P13 real Valkey gates could pass while the timing breakdown lacked enough fields to explain the observed gate duration. A runtime diagnostic probe failure could be folded into the final proof timing entry.

## After Behavior

P13 real Valkey evidence is unchanged and still produced by `scripts/valkey_e2e_gate.py`. The timing artifact now explains the gate wall time with bounded unattributed seconds, and diagnostic probe attempts are visible without marking the final proof as failed.
