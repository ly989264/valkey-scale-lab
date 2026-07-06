# P42_VALKEY_SERVER_PROFILE_GLOBAL_CONFIG - Valkey Server Profile Global Config

## Objective

Make Valkey server profile a repository-wide configuration capability. The stage must add global configuration for `runtime.server_profile`, Valkey `io-threads` behavior, Valkey log format, and per-node memory limits, then route config validation, planning, runtime config generation, resource preflight, evidence artifacts, reports, and harness assertions through the same effective profile.

## Required configuration

`config/valkey_scale_lab_global.yaml` must define:

```yaml
runtime:
  server_profile: correctness | one_b_dev | one_b_perf
  valkey:
    io_threads: <int>
    io_threads_auto: <bool>
    io_threads_max_per_node: <int>
    io_threads_max_total: <int>
    log_format: text | json
cluster:
  node_memory_limit_mb: 64
```

Merge order is:

```text
built-in defaults < global config < scenario config < CLI override
```

The default `one_b_dev` profile must use 64 MB per node and must not blindly set high `io-threads`; it should default to `1` or `2`. `one_b_perf` may allow higher values only within per-node and total thread budgets.

## io-threads requirements

- If effective `io_threads > 1`, generated `valkey.conf` must contain `io-threads <N>`.
- If effective `io_threads == 1` or unset, generated `valkey.conf` must not contain a misleading `io-threads` line, and artifacts must record `effective_io_threads=1`.
- `io_threads_auto` must calculate a safe value from host CPU count, nodehost count, and logical node count.
- `total_valkey_threads <= io_threads_max_total`.
- Invalid or excessive settings must fail closed or degrade to an allowed value with the reason recorded in `config_validation_report`.
- The stage must forbid blind global `io_threads=6` across nodes.

## memory requirements

- Global default `cluster.node_memory_limit_mb` is 64.
- Scale configs without an explicit override must inherit 64 MB from the global config.
- Resource preflight must calculate:
  - `node_count * node_memory_limit_mb`
  - `projected_nodehost_memory_mb`
  - `host_available_memory_mb`
  - `can_run`
- Insufficient memory must be `BLOCKED` or fail closed; it must not silently downscale.
- Runtime must either enforce the memory limit through Docker or Valkey `maxmemory`, or explicitly mark `runtime_memory_limit_enforced=false` without treating that as enforced evidence.

## Evidence requirements

Every real run must emit:

- generated `valkey.conf` artifacts;
- `effective_server_profile.json`;
- `run_state` node entries with `effective_io_threads` and `effective_node_memory_limit_mb`;
- `config_validation_report` fields:
  - `requested_io_threads`
  - `effective_io_threads`
  - `requested_node_memory_limit_mb`
  - `effective_node_memory_limit_mb`
  - `io_thread_budget_status`
  - `memory_budget_status`

## Required coverage

The stage must cover:

- fake/schema tests for parsing, schema, merge order, and budget calculation;
- smoke real Valkey;
- 30, 50, 100, and 200 real Valkey paths;
- greater-than-200 dry-run projection with io-thread and memory budgets, without claiming real evidence;
- scale-generic planner/runtime behavior without hardcoding 200 as a maximum for future real scale.

## Required harness changes

Add or update:

```text
scripts/assert_server_profile_config.py
scripts/assert_io_thread_memory_evidence.py
scripts/assert_no_server_profile_partial_coverage.py
```

Assertions must fail closed when:

- real scale generated configs cannot be traced to the global server profile;
- 30/50/100/200 artifacts lack `effective_io_threads` or `effective_node_memory_limit_mb`;
- `io_threads > 1` is not reflected in generated `valkey.conf`;
- 64 MB memory is not reflected in resource preflight;
- only fake/smoke tests pass while scale coverage is claimed complete;
- only `scale_200` was changed;
- fake artifacts are presented as runtime evidence.

## Test matrix

Tests must cover at least:

- `io_threads=1`;
- `io_threads=2`;
- `node_memory_limit_mb=64`;
- too-large `io_threads` fails closed or degrades with reason;
- insufficient memory is blocked or fail closed;
- smoke real generated config verification;
- 30/50/100/200 plan/artifact schema coverage.

## Forbidden shortcuts

- Do not globally set `io_threads=6`.
- Do not only edit YAML templates.
- Do not only edit runtime without resource preflight.
- Do not only edit reports without real generated config.
- Do not weaken cleanup, real evidence, no-bypass, or gate checks.

## Completion criteria

The stage is complete only when global server profile config is effective across config validation, planning, runtime, resource preflight, evidence, reports, and harness assertions; 64 MB is the default per-node memory; io-thread behavior has budget protection and real config evidence; fake/smoke/30/50/100/200 paths all have evidence; greater-than-200 remains projection-only unless explicitly permitted by policy; review says `Decision: PASS`; postcheck passes; and the stage is marked complete, committed, and pushed.
