# Harness Exception: CML13_FINAL_FULL_CHAIN_AUDIT_AND_PUSH

## Defect

The capability-matrix harness allowed false-positive `PASS` statuses:

- `split_brain_indicators_*` could be promoted to `PASS` even when the evidence only showed that conflicting primaries were not observed.
- `cluster_management_scale_*` used cluster-create evidence to cover lifecycle operations such as remove, add, reshard, rebalance, and rolling restart.
- `network_az_faults_*` could be satisfied by `network_delay` evidence even though `network_partition` was not executed.

## Patch

The harness now distinguishes executed capabilities from missing or absence-only evidence:

- Split-brain absence uses `PASS_ABSENCE_OBSERVED` or `UNSUPPORTED_WITH_EVIDENCE`, never ordinary `PASS`.
- Cluster management is split into `cluster_create_ops_*` and `lifecycle_ops_*`; lifecycle gaps require structured `partial_reasons`.
- Network delay evidence is recorded separately as `network_delay_faults_*`; `network_az_faults_*` cannot pass without explicit `network_partition` evidence.
- Negative cases were added for `network_delay_as_partition_pass`, `split_brain_missing_as_pass`, and `cluster_create_as_reshard_pass`.

## Before/After Behavior

Before: final capability artifacts could show ordinary `PASS` for capability rows whose evidence did not execute the named capability.

After: ordinary `PASS` is reserved for executed capabilities. Partial rows include machine-readable reasons, and absence-only or unsupported evidence uses distinct statuses.
