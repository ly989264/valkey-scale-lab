# P41_NODEHOST_DENSITY_GLOBAL_CONFIG — Global Nodehost Density Configuration

## Purpose

Make nodehost / Docker container density a repository-level global runtime configuration used by fake, smoke, 30/50/100/200 real-Valkey, and >200 dry-run planning paths. The stage closes the regression where 200 logical Valkey nodes were concentrated into two Docker nodehost containers.

## Required behavior

Configuration merge order is:

```text
built-in defaults < config/valkey_scale_lab_global.yaml < scenario config < CLI override
```

All legacy template configs must continue to parse. If a scenario config omits nodehost density fields, the global config supplies them. No phase may hardcode nodehost count.

## Required runtime fields

The effective config, cluster plan, run state, resource preflight, cleanup report, nodehost density plan, phase summary, coverage ledger/matrix, analysis summary, and report indexes must record:

```text
nodehost_strategy
max_nodehosts
nodehosts_per_az
max_logical_nodes_per_nodehost
actual_nodehost_count
logical_nodes_per_nodehost
nodehost_distribution
```

`runtime.nodehost_strategy=density_limited` with `runtime.nodehost_distribution=round_robin_by_az` must split 100/200 node profiles by `max_logical_nodes_per_nodehost`, for example 200 logical nodes and max 25 logical nodes per nodehost produce 8 nodehosts, not 2.

## Required safety and preflight

Preflight must fail closed when:

```text
requested nodehost count > max_nodehosts
total port count is invalid
estimated file descriptors are insufficient
estimated memory is insufficient
any nodehost exceeds max_logical_nodes_per_nodehost
```

Silent downscale, 200-to-100 fallback, dry-run substitution for real runtime, and fake evidence as real evidence are forbidden.

## Required coverage

The same nodehost density implementation must cover:

```text
fake/schema/unit tests
small smoke real Valkey path (6/10)
30 real Valkey
50 real Valkey
100 real Valkey
200 real Valkey
>200 dry-run projection only
future >200 real path remains scale-generic and resource-policy gated
```

## Required assertion scripts

```text
scripts/assert_nodehost_density_config.py
scripts/assert_no_nodehost_partial_coverage.py
scripts/assert_runtime_nodehost_distribution.py
```

The assertions must fail closed for missing global config, missing artifact evidence, partial scale coverage, over-limit nodehost density, mismatched actual nodehost count, or >200 dry-run artifacts claiming real runtime evidence.

## Required artifacts

```text
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/phase_summary.json
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/nodehost_density_plan.json
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/resource_preflight.json
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/run_state.json
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/cluster_plan.json
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/coverage_ledger.json
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/analysis_summary.json
artifacts/phases/P41_NODEHOST_DENSITY_GLOBAL_CONFIG/report_index.json
```

## Required tests and gates

Unit tests must cover global config merge, density planning, and resource preflight. Integration tests must cover fake/smoke config paths. Validator tests must prove partial implementation fails. At least one small real smoke gate should run when local Docker resources are available; larger 30/50/100/200 gates may run only when preflight passes and must not be faked.

## Blocking conditions

The stage is blocked if the implementation only changes `scale_200.yaml`, only changes one phase, only writes JSON artifacts without changing runtime behavior, labels >200 dry-run as real, weakens cleanup/evidence/coverage gates, or removes fail-closed preflight checks.
