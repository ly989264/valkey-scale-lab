# P24_PARTITION_SPLIT_BRAIN_MATRIX — Partition and Split-Brain Matrix

## Stage objective

Implement minority/majority partition scenarios and split-brain-window measurement.

## Required rows

```text
network_partition_minority
network_partition_majority
split_brain_window_detection
```

## Worker implementation requirements

Implement:

- partition group planner based on live topology, roles, slots, AZs, and hosts;
- traffic block between groups while preserving traffic within groups;
- probes from both sides when feasible;
- majority/minority availability measurement;
- split-brain detectors from `08_FAULT_MATRIX_SPEC.md`;
- workload windows on reachable sides;
- partition clear and recovery timing;
- cleanup verification.

## Required artifacts

```text
partition_report.json
split_brain_report.json
fault_results.jsonl
fault_topology_snapshots.jsonl
workload_impact_report.json
events.jsonl
metrics_timeseries.jsonl
quant_summary.json
```

## Required assertions

- partition groups are explicit;
- detector list is explicit;
- `split_brain_window_ms=0` only if detectors ran;
- missing detectors have reasons;
- workload impact exists;
- cleanup passes.

## Review focus

Reject split-brain reports that simply assume zero. Confirm probes compare divergent cluster views and conflicting slot ownership indicators.
