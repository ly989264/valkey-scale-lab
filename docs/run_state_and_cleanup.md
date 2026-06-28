# Run State and Cleanup Contract

P00 defines the lifecycle contract only. Later phases must implement this design before starting real processes or containers.

## Ownership

Every process, container, network, directory, PID file, and state file created by the lab must include deterministic ownership data:

- `project`: `valkey-scale-lab`
- `cluster_id`: run-specific ID recorded in state
- `phase_id`: current phase ID
- `run_id`: deterministic run identifier recorded in artifacts
- `logical_id`: stable node or fault target name when applicable

## State Files

Scenario creation writes a JSON state file through `python3 -m valkey_scale_lab.cli gate scenario --state-out ...`. The state file is the cleanup source of truth and must include live endpoint data sufficient for independent gate probes. Missing optional fields must be omitted or marked with `MISSING` or `SKIPPED_WITH_REASON`; values must not be invented.

## Cleanup

`python3 -m valkey_scale_lab.cli gate cleanup --state ...` must be idempotent. Cleanup may remove only resources that match the recorded ownership fields. It must write a cleanup report listing inspected resources, removed resources, remaining owned resources, and skipped resources with reasons.

## Safety Boundary

Faults and cleanup must stay inside owned Docker/container namespaces, owned containers, or an explicit sandbox proxy layer. Host-level route, firewall, interface, and OS network service changes are outside the project contract.

## P00 Status

P00 does not start Valkey, Docker containers, workload processes, or fault injectors. It only establishes the package, CLI, artifact, and cleanup contract that later phases must satisfy.
