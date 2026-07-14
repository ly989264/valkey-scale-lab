# P43_CLUSTER_NODE_TIMEOUT_GLOBAL_PROFILE - Cluster Node Timeout Global Profile

## Objective

Make `cluster-node-timeout` a repository-wide configurable profile instead of a hidden phase-specific hardcode. The default effective timeout for development, correctness, and failover paths is `30000` milliseconds, and every fake, smoke, 30, 50, 100, 200, and greater-than-200 dry-run path must expose the requested value, effective value, and source in machine-readable artifacts.

## Required configuration

`config/valkey_scale_lab_global.yaml` must define:

```yaml
cluster:
  cluster_node_timeout_ms: 30000
fault:
  cluster_node_timeout_matrix_ms: [5000, 10000, 15000, 30000, 60000]
profiles:
  correctness:
    cluster_node_timeout_ms: 30000
  failover_rto:
    cluster_node_timeout_ms: 30000
  management_safe:
    cluster_node_timeout_ms: 30000
    allow_override: true
```

Merge order is:

```text
built-in defaults < global config < selected profile < scenario config < CLI override
```

The effective source must be recorded as `global`, `profile`, `scenario`, or `cli`. Any non-`30000` timeout must have explicit profile, scenario, or CLI source evidence.

## Runtime requirements

- Generated per-node `valkey.conf` files must contain `cluster-node-timeout <effective_ms>`.
- Generated configs must include source provenance for the timeout.
- Every run-state node must include `effective_cluster_node_timeout_ms`, `requested_cluster_node_timeout_ms`, and `cluster_node_timeout_source`.
- `config_validation_report` must include `requested_cluster_node_timeout_ms`, `effective_cluster_node_timeout_ms`, and `cluster_node_timeout_source`.
- Legacy hidden `600000` or `5000` phase overrides must be removed or converted into explicit config/profile evidence.
- Different phases may not silently use different timeouts.

## Timeout matrix requirements

Add a failover RTO timeout-matrix runner that supports explicit timeout selections:

```text
5000 / 10000 / 15000 / 30000 / 60000
```

The runner must not default to all large-scale scenarios. For each real selected run, matrix output must include:

```text
timeout_config_ms
kill_to_pfail_ms
pfail_to_cluster_ok_ms
kill_to_client_recovered_ms
false_pfail_count
false_failover_count
```

If resources are insufficient or a selected run was not executed, the row must be `BLOCKED` or `NOT_RUN_WITH_REASON`; fake values are forbidden.

## Required coverage

The stage must cover:

- fake/schema tests for config merge, schema, and invalid values;
- smoke real Valkey generated config evidence for `30000`;
- 30, 50, 100, and 200 real Valkey paths with timeout evidence;
- greater-than-200 dry-run projection with timeout config only, never real evidence;
- scale-generic code paths without hardcoding 200 as a future real ceiling.

## Required harness changes

Add or update:

```text
scripts/assert_cluster_timeout_config.py
scripts/assert_no_hidden_timeout_override.py
scripts/assert_timeout_matrix_artifacts.py
```

The assertions must fail closed when:

- generated configs lack `cluster-node-timeout` or source provenance;
- default real paths do not use `30000` milliseconds;
- non-`30000` values lack explicit source evidence;
- phase-specific hidden timeout overrides appear in source;
- coverage is fake/smoke-only;
- timeout matrix artifacts are static or forged;
- scale evidence silently downscales.

## Required tests

Tests must cover:

- global config merge and profile override;
- invalid timeout values;
- generated config contains expected timeout and provenance;
- run-state and validation-report timeout fields;
- fake, smoke, 30, 50, 100, 200, and greater-than-200 plan/artifact validator updates.

## Forbidden shortcuts

- Do not only edit `scale_200.yaml`.
- Do not only edit the fault gate.
- Do not weaken cleanup, coverage, no-bypass, or real-evidence gates.
- Do not treat failover skips as final real PASS.
- Do not fabricate timeout matrix data.

## Completion criteria

The stage is complete only when `cluster-node-timeout` is controlled by global/profile/scenario/CLI config, the default effective timeout is `30000` milliseconds, all generated config and run-state artifacts record provenance, 30/50/100/200 real paths have timeout evidence, greater-than-200 remains dry-run projection only, hidden hardcodes are removed or made explicit, timeout matrix artifacts are runnable and verifiable, review says `Decision: PASS`, postcheck passes, and the stage is marked complete, committed, and pushed.
