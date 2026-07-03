# 10_SCALE_EXECUTION_POLICY.md — Scale, Resource, and Dry-Run Policy

## Default policy

The project default remains capped at 100 nodes. The strict loop adds user-required bounded real 200-node stages. This does not permit arbitrary real execution above 200.

## Real-scale policy

The strict real scales are:

```text
50
100
200
```

Exact node count is mandatory. A real 200-node stage that runs 100 nodes is a failure, not a partial pass.

## Resource preflight

Before any real 50/100/200 stage, resource preflight must record:

```text
host OS and architecture
Docker availability and version
available memory
available disk
CPU count
container runtime limits
port range availability
estimated memory per Valkey node
estimated disk per Valkey node
estimated workload client overhead
estimated metrics overhead
estimated node distribution per host
result: can_run true/false
```

If preflight says `can_run=false`, the stage is blocked and cannot pass. Do not fabricate artifacts to continue.

## 200-node bounded exception

P32, P35, and P36 may run exactly 200 nodes because the user explicitly requires real 200-node coverage.

Rules:

```text
200-node stages are automatic after P27 enables them
resource preflight must pass before execution
workload QPS may be reduced to a non-zero probe workload with reason recorded
node count must be exactly 200
no downshift to 100
no fake Valkey
no dry-run substitution
cleanup must pass
```

## >200 dry-run-only policy

P37 must support dry-run targets above 200, including at least:

```text
201
250
300
500
1000
```

Rules:

```text
execution_mode=dry_run
no containers started
no Valkey endpoints probed as live >200 cluster
no workload executed
resource estimates and placement plans are allowed
report projections are allowed only when clearly marked dry_run
```

P37 must provide no-runtime proof by recording runtime inventory before and after the dry-run and showing no owned runtime resources were created.

## Safe degradation

Allowed only when recorded:

```text
lower workload QPS for 100/200 real stages
longer convergence timeout for 100/200 real stages
sandbox_proxy fallback instead of container_netns_tc
multi-host distribution when configured
```

Not allowed:

```text
using fake Valkey for real stages
downshifting node count
omitting workload impact
omitting cleanup
using host-level network mutation
passing required rows as skipped
real execution above 200
```
