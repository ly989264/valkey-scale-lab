# Harness Exception - P22_FAULT_REPLICA_HOST_AZ_STOP

## Defect

The P22 manifest already required real evidence for `replica_stop`, `node_host_stop`, and `az_stop`, but the locked `scripts/fault_safety_gate.py` still executed only a single network-delay sandbox smoke path. The locked assertion scripts also accepted generic fault rows without proving P22 target role selection, logical host/AZ containment, workload windows per fault sample, event/metric coverage, or the required 6/10 plus conditional 30+ policy.

## Patch

- Strengthened `scripts/fault_safety_gate.py` with a P22 controller that runs P22-only configs through real owned Valkey scenario setup, applies `node_stop` through the project fault API, records workload/topology/quant artifacts, refreshes owned process PIDs after clear, and aggregates cleanup.
- Strengthened `scripts/assert_fault_matrix_coverage.py` to fail wrong replica roles, host/AZ target leakage, unsafe implementation paths, 200-node leakage, missing mandatory 6/10 rows, and invalid 30+ skip policy.
- Strengthened `scripts/assert_workload_impact.py` to require all canonical windows and comparisons for every real P22 fault sample.
- Strengthened `scripts/assert_quant_artifacts.py` to require P22 event, metric, topology, evidence, and quant-count coverage for every real fault sample.

## Before/After Behavior

- Before: P22 could pass a non-P22 network-delay smoke artifact and generic rows.
- After: P22 must produce row-specific real Valkey evidence for replica, logical host, and virtual AZ stops, or fail closed. 30+ evidence is allowed to skip only with resource preflight evidence and `SKIPPED_WITH_REASON`.

## Safety

The patch does not add host firewall, route, interface, OS service, sudo, physical host, or physical AZ mutation. Logical host and virtual AZ stops are topology labels over owned Valkey processes/containers only.
