# P14 Harness Exception: Two-Virtual-AZ 1000-Node Dry Run Template

## Defect

`templates/configs/scale_1000_dryrun_optin.yaml` was locked with three virtual AZs, while the
updated requirement allows only two virtual AZs for multi-AZ operation. A three-AZ 1000-node
dry-run plan no longer represents the intended startup model of one Docker nodehost per
virtual AZ with primaries and replicas split across the two AZs.

## Patch

The 1000-node dry-run template now declares:

```text
azs: [az-a, az-b]
```

The profile remains dry-run only and still requires the existing 1000-node opt-in guard.
Generated dry-run plans show two nodehost containers with 500 logical Valkey processes each.

## Before/After Behavior

Before: the dry-run plan distributed 1000 logical nodes across three virtual AZs.

After: the dry-run plan distributes 1000 logical nodes across two virtual AZs, with every
primary/replica pair occupying opposite AZs and no process/container execution by default.

## Gate Impact

`scripts/codex_gate.py precheck` continues to report a lock mismatch for the template. This
exception documents the intentional strengthening change without editing `codex/gate_lock.json`.
