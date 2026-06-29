# P12 Harness Exception: Two-Virtual-AZ Template Requirement

## Defect

The locked scale and local multi-AZ templates still declared three virtual AZs:

- `templates/configs/local_az_3x2.yaml`
- `templates/configs/scale_10.yaml`
- `templates/configs/scale_30.yaml`
- `templates/configs/scale_50.yaml`
- `templates/configs/scale_100.yaml`
- `templates/configs/scale_1000_dryrun_optin.yaml`

The updated operating requirement is stricter: multi-AZ mode may use only two virtual AZs,
with each shard primary and replica in opposite AZs. Keeping the locked three-AZ templates
would preserve a weaker placement model and make the default scale configs invalid under the
new safety rule.

## Patch

The templates now use exactly:

```text
azs: [az-a, az-b]
```

The config validator rejects any multi-AZ config that does not have exactly two virtual AZs.
The planner records two nodehost containers, one per virtual AZ, and marks each shard as
occupying the opposite AZ pair.

## Before/After Behavior

Before: scale templates placed primaries and replicas across a three-AZ rotation. A shard used
two of three AZs, but the cluster as a whole still expected three AZ containers.

After: each scale template uses two virtual AZs. Primaries alternate between `az-a` and `az-b`;
each replica is placed in the other AZ. Scale runtime uses one owned Docker nodehost container
per virtual AZ and runs Valkey nodes as processes inside those containers.

## Gate Impact

`scripts/codex_gate.py precheck` still fails because the lock file records the old template
hashes. This exception intentionally does not update `codex/gate_lock.json`; the lock remains an
audit signal that a protected template changed to satisfy the stronger two-AZ requirement.
