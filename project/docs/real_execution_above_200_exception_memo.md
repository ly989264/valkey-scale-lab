# Admitting a real native 1280-node run: what it would take, reported not made

Written 2026-08-16 as part of M4-1. **No code changed and nothing here is
implemented.** By this project's own rule a semantic change to a validation
contract is reported before it is made, and this is the whole safety story of
M4: today nothing above 200 nodes can execute for real, and M4's target is 1280.

Everything below was compiled at HEAD against a configuration derived from
`templates/configs/real_ecs_200.yaml` with `cluster.shards: 256` and
`cluster.replicas_per_shard: 4` - the M4 target shape, on the real fleet, with
no other line changed. It was not run.

## §1 What refuses it today, compiled rather than read

`validate_config_file` returns `FAIL` with **eight** errors, and they are the
whole list:

| code | site | what it asks for |
|---|---|---|
| `REAL_EXECUTION_ABOVE_200_FORBIDDEN` | `config/validation.py:398` | above 200 nodes, `runtime.dry_run: true` |
| `MISSING_200_PLUS_DRY_RUN_PROFILE` | `:400` | a scale-projection profile, or the legacy 1000-node dry-run opt-in |
| `WORKLOAD_ABOVE_200_FORBIDDEN` | `:407` | above 200 nodes, no workload execution |
| `NODE_CAP_EXCEEDED` | `:409` | 1280 nodes is above the default cap of 100 |
| `MISSING_1000_ALLOW` | `:413` | `safety.allow_1000_nodes: true` |
| `MISSING_1000_ENV_GUARD` | `:415` | name `VSLAB_ALLOW_1000_DRYRUN` |
| `MISSING_1000_DRY_RUN` | `:417` | `runtime.dry_run: true` |
| `MISSING_1000_SCALE_PROFILE` | `:419` | `opt_in_1000` and `dry_run_only` |

Three of these are not merely "above 200" rules: 1280 crosses **1000**, so the
whole `total_nodes >= 1000` block fires too, and every clause of it is
dry-run-only by construction. This is the part most easily missed when reasoning
from the ladder: M4 is not one step past exact-200, it is past exact-200 *and*
past the 1000-node block.

The two existing escapes cannot serve it, and neither is a near miss:

- `is_scale_projection_profile` (`:546`) requires `runtime.dry_run: true` and
  `workload.enabled` not true. It exists so a plan above 200 can be *compiled*,
  which is how the M4 density table was produced, and it can never admit a real
  run.
- `is_exact_2000_local_full_flow_profile` (`:565`) is the only exception that
  admits real execution above 200, and it requires `total_nodes == 2000`,
  `profile_name == "scale_2000_local_full_flow_optin"` **and
  `runtime.provider == "docker"`**. So it could not serve the fleet even at its
  own node count.

## §2 What the guards are actually protecting, so a change can stay narrow

Read together, the guards encode three separate promises, and only the first is
in the way:

1. **A real run above the bounded exception is not admitted by accident.** The
   default cap is 100; exact-200 is a *named* exception keyed on
   `profile_name: scale_200` plus a capability/scenario pair; exact-2000 is a
   second named exception. Each names its node count exactly. Nothing is
   admitted by being "less than some maximum".
2. **A large run is authorised, preflighted and costed.**
   `_is_exact_2000_local_full_flow_exception` in both `resource.py:353` and
   `planner/plan.py:305` additionally requires `operator_opt_in` and
   `cost_acknowledged`, which are arguments threaded from
   `runtime/lifecycle.py:64`, not fields a configuration can assert about
   itself. That is the part that makes the exception an operator act rather
   than a file.
3. **Exactness and no silent downscale.** `local_full_flow_v1.json`'s
   `scale_policy` admits `30..2000` with `exact_requested_nodes: true`, so 1280
   is already inside the scenario's declared range and nothing there needs
   changing.

## §3 The proposal: a fourth named exception, in the shape the third already has

**`scale_1280_native_ecs_optin`.** A new profile name, a new predicate, and
nothing widened.

`is_exact_1280_native_ecs_profile(config)` returning true only when **all** of:

```
total_nodes == 1280
profile_name == "scale_1280_native_ecs_optin"
runtime.provider == "ecs"                       # the mirror of 2000's "docker"
runtime.dry_run is False
workload.enabled is True
scale_profile.exact_1280_native_ecs_opt_in is True
scale_profile.target_nodes == 1280
scale_profile.execution_mode == "operator_opt_in"
safety.default_max_nodes == 100
safety.allow_1000_nodes is False
safety.require_sandbox_network is True
safety.forbid_host_network_mutation is True
```

Every clause is copied from `is_exact_2000_local_full_flow_profile` except the
node count, the profile name and the provider. `allow_1000_nodes` stays
**false**: the 1000-node opt-in is a *dry-run* mechanism and this exception must
not be reachable through it.

### §3.1 Exactly which guards it touches

It is admitted at the same eight codes and no others. In
`config/validation.py`, the new predicate joins `exact_2000_local_full_flow` in
the four `not exact_2000_local_full_flow` disjunctions at `:398`, `:400`, `:407`
and `:409`, and in the `total_nodes >= 1000` guard at `:411`. In
`resource.py:389`, the `allowed_codes` set already lists those seven codes for
exact-2000; the new exception filters the same seven.

**Nothing else is relaxed.** In particular:

- The default cap stays 100 and the `DEFAULT_NODE_CAP` check at `:381` is
  untouched, so no configuration can raise it.
- `_validate_replica_count`, `SANDBOX_REQUIRED`, `HOST_NETWORK_FORBIDDEN` and
  the `ecs` provider's two required fields all still apply.
- The `scale_projection` and `legacy_1000_dry_run` paths are untouched, so the
  dry-run compiles this project already relies on keep behaving identically.
- `is_exact_2000_local_full_flow_profile` is untouched, so exact-2000 on Docker
  keeps every rule it had.

### §3.2 What must move with it, and it is not only validation

Four further sites, each mirroring what exact-2000 already has:

1. `planner/plan.py` - an `_is_exact_1280_native_ecs_exception` beside
   `_is_exact_2000_local_full_flow_exception` at `:305`, taking `operator_opt_in`
   and `cost_acknowledged`.
2. `resource.py` - the same predicate at `:353`, so the resource preflight
   admits it and still runs. The preflight is the point: at 1280 on eight hosts
   it is what checks 160 nodes per host against 7900 MiB, and the M4 density
   calibration already found that `node_memory_limit_mb` must drop 64 → 32
   there.
3. `execution.py` - an `ExecutionProfile("exact-1280", 1280, ...)` beside
   `exact-2000` at `:62`, plus an `EXACT_1280_SCENARIOS` frozenset and an
   `exact_1280_selection_allowed`, because the predicate keys on the
   capability/scenario pair as well as on the file.
4. `catalog.json` - `real.ecs.full-flow` declares `nodes` with
   `"maximum": 200`. That is the executable boundary and no configuration can
   cross it. Either that maximum moves, or M4 gets its own `real.ecs.*` entry.
   **A separate entry is the narrower move** and keeps every existing exact-200
   acceptance run refusing 1280 by its own schema. Registering one moves three
   counts: `repository.all`, the catalog's 99 and the M1 plan's 91.

### §3.3 What this does not decide

- **Whether 1280 nodes on eight hosts is the right run at all.** That is
  `m4_density_calibration.md`'s question and its answer is "defensible, at an
  extrapolation of 1.6x beyond what was measured".
- **The second changed variable.** 32 MiB per node instead of 64 is forced by
  the eight-host shape and is a declared delta M4 owns, not this exception's.
- **Whether the exception should name 1280 at all.** It could instead name a
  *shape* - 256 shards at 4 replicas - which is what M4 is really about. Naming
  the node count is what the two existing exceptions do and is the more
  conservative reading; naming the shape would let the replica count move
  without a new exception, which is precisely the flexibility a bounded
  exception is supposed to withhold. **Recommended: name the node count.**

## §4 The one thing worth arguing about before implementing

The exact-2000 exception is Docker-only and local. This one would admit, for the
first time, a **real run above 200 nodes on hardware that is not the
controller** - 1280 processes across eight machines that a failed run can leave
running. The ownership and reclaim machinery for exactly that already exists and
has been proved on this fleet three ways (`native_cleanup_proof.py
release|abort|stubborn`, 43 → 0 residue on eight real hosts), and a SIGKILLed
50-node run has been recovered from its `state.json`. What has *not* been
proved is that at 1280.

So the honest sequencing is: **the exception and the first 1280-node run are
not the same decision.** A reasonable order is to admit the exception, run the
existing cleanup-ownership proof at the new density first, and only then take a
full-flow run. That costs one extra fleet exercise and removes the case where a
two-hour run fails at 90 minutes and leaves 1280 processes across eight hosts
with no measured reclaim behind it.

**This memo asks for a decision on §3, not for permission to implement it.**
