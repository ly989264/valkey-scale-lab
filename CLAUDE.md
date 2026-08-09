# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository boundaries

- `project/` is the active, runnable `valkey-scale-lab` product. Run product commands from this directory.
- `.github/milestone-loop/` is the active GitHub automation control plane; it remains separate from the product.
- `loop_evidence/` is an immutable historical archive. Do not modify it or make product code/tests depend on it.
- Product code must not import the verification runner, tests, milestone definitions, or controller state. Tests call product APIs directly; verification and milestones consume the product from outside.

## Setup and common commands

Run these from `project/`:

```bash
# Install the package and development test dependency
python3 -m pip install -e .
python3 -m pip install -r requirements-dev.txt

# Show the executable verification interface
./gate help

# Run one catalog-registered test or suite
./gate test product.unit.cli_contract
./gate suite product.unit
./gate suite repository.all

# Run a pytest module or one test function directly
python3 -m pytest -q tests/unit/test_cli_contract.py
python3 -m pytest -q tests/unit/test_cli_contract.py::test_name

# Run a milestone's registered checks
./gate milestone m1

# Build the pinned Valkey image required for real runs
./scripts/build_valkey_image.sh
```

`catalog.json` is the executable registry: the Gate resolves its registered pytest command, parameters, timeout, and result format. Use `./gate test <test-id> --param NAME=VALUE` for a parameterized Test; suite parameters must be supplied by `--params-file`. Gate writes logs and summaries under `artifacts/gate-runs/`.

There is no dedicated lint configuration in the repository. `pytest==8.4.2` is the pinned development dependency.

Useful product CLI flows:

```bash
python3 -m valkey_scale_lab.cli run init --run-id local-run
python3 -m valkey_scale_lab.cli config validate --config config/example.yaml --out runs/local-run/artifacts/config_validation_report.json
python3 -m valkey_scale_lab.cli analyze --input runs/local-run --out runs/local-run/artifacts/analysis_summary.json
python3 -m valkey_scale_lab.cli report --analysis runs/local-run/artifacts/analysis_summary.json --out-dir runs/local-run/reports --index-out runs/local-run/reports/report_index.json
```

## Product architecture

`src/valkey_scale_lab/` is an importable Python package and CLI. Its main pipeline is:

1. `cli.py` dispatches configuration validation, planning, scenario/gate execution, fault control, analysis, and reporting.
2. `config/`, `planner/`, and `scenarios/` load and validate explicit run configuration and scenario definitions. Scenario definitions live in `scenarios/definitions/`; configuration templates are under `templates/`.
3. `gates/` coordinates a real execution through adapters and the local orchestrator. `runtime/` owns Docker lifecycle, command capture, and setup timing; `fault/` limits injected failures to owned sandboxes/proxies.
4. `observability/` and `observer/` capture cluster, Sentinel, load, failover, stability, and resource observations. `docs/scalable_cluster_observability_design.md` is the authoritative observation and verdict contract—runtime adapters cannot introduce new observation layers or verdict states.
5. `evidence/` builds and validates provenance-bound machine-readable artifacts against `schemas/`. `analysis/` and `report/` consume validated artifacts only, producing derived summaries and reports.

The product's safety and evidence contracts are central: exact requested node scale is preserved (never silently downscaled); real runs above 200 nodes require explicit operator authorization, resource preflight, and cost acknowledgement; started resources must be owned, collision-checked, and deterministically cleaned up. Missing evidence must be represented with a reason, never fabricated.

## Verification and delivery model

- `tests/` contains hermetic product behavior tests. Tests for real Valkey scenarios are separate from ordinary regression checks.
- `verification/` implements the generic Gate engine. It validates the flat `catalog.json` registry, invokes registered checks, and expands milestone checks.
- `milestones/` defines product acceptance criteria. A feature whose criterion becomes executable must register its Test once in `catalog.json` and attach the Test or Suite ID to the criterion. Do not create placeholder catalog entries.
- `schemas/` defines configuration, scenario, and artifact contracts; for changes to machine-readable contracts, inspect and update their direct producers, consumers, validators, and focused tests together.

The control plane's candidate admission runs `./gate suite repository.all`; final milestone acceptance runs `./gate milestone <milestone>` on the merged default branch. For GitHub actions, prefer the connected GitHub Connector; use `gh` only when its coverage is insufficient.

## Current work: lifecycle refactor

Goal: separate the full-flow lifecycle from the Docker backend so M3 can exist.
`execute_scenario` rejects `native_multi_ecs` from inside `docker_runtime.py`, so
a second backend cannot be written without living in the Docker module or
duplicating it. M2 stays defined as written but is parked; the priority is a
well-implemented real cluster test at 50/100/200, then M3 and M4 on top.

Slices 1, 2, 3 and 4 - `runtime_start`, `cluster_form`, `management_matrix` and
`fault_matrix` - are done and accepted. `runtime/node_backend.py` holds
`NodeBackend`, the seam every later slice extends; `DockerNodeBackend` in
`docker_runtime.py` is its one implementation, now twenty-one methods. Read the
four slice maps in `project/docs/` before the next slice: they carry the
accepted seam, the measured result of every bar item, and the limitations below.

Slice 2 settled the open question the way Slice 1 was judged: exact-200 is
stage-scoped, on measurement. It also found that §15 of the observability design
already fixes how far the seam reaches - an adapter replaces inventory and
endpoint discovery, not RESP or the verification logic - so `cluster_form` grew
the seam by two operations rather than moving cluster formation.

Slice 3 grew it by three - `stop_node`, `start_node` and `resource_sampler`,
each named verbatim in §15 - and dissolved three more into inventory the backend
already supplies, the same way `peer_address` dissolved in Slice 2. It also
deleted 215 lines of dead path, two pieces of which were older duplicates of the
code it extracted. `stabilize` would extract nothing: one bounded wait plus the
myslots report, both pure RESP.

Slice 4 grew it by seven - the actuator, which §15 names as adapter surface -
and took `baseline_workload` with it. Four predicted operations dissolved,
including the family that looked most like the answer: the three proxy faults
run an in-process host TCP proxy, touch no Docker at all, and needed only
`client_host`. **No full-flow lifecycle stage names a Docker primitive any
more.** `run_node_cluster_cli` has two callers left, both in other
capabilities; `_wait_container_pid_gone` and `_safe_process_pid` have no
lifecycle caller at all.

**There is no next extraction slice.** What remains is the open list below, and
`fault/sandbox.py` - a second Docker actuator, 490 lines, reached from
`cli.py fault apply`/`clear` and `compat/`, which no run in any acceptance bar
exercises. Decide what M3 needs before opening another slice.

### exact-200 passes end to end again

Between Slice 2 and the next slice, three fixes landed on their own evidence,
each with its own commit. They are not refactor slices; they are what made
exact-200 runnable, which every later slice needs.

- `49b2e3ab` the rolling restart asked all N nodes for shard-scoped answers,
  twice per batch: an O(N²) collection step, which §16 item 3 forbids. Measured
  82 whole-fleet probes and ~16,400 connections in one exact-200 run; ~1M at
  2000 nodes. Now scoped to the batch's shards.
- `eac9b545` the layer-1 light probe opened and closed a TCP connection per node
  per round and every caller builds a fresh probe, so nothing survived a round.
  Measured 165,095 host connections in one run, 97,000 of them from 485
  whole-fleet probes, ending in `[Errno 49] Can't assign requested address` once
  the host's 16,384 ephemeral ports were gone. Connections are now kept per
  endpoint, checked out per observation, retried once on a fresh socket when
  stale. §14 budgets O(N) persistent connections and no churn; §17 leaves the
  RESP client's internals to the implementation.
- `85d5096a` the partition scenarios read the isolated node through
  `_node_command`, whose `docker exec` fallback reaches through the partition.
  Measured: the host path timed out for 33s while the same read answered
  `cluster_state:ok` at t=31.0s. Unreachable is now the observation, and it is
  fail-closed; the validator accepts it only with a recorded reason.

Result: **exact-200 PASS 1520.6s, twelve of twelve steps, 200 of 200 nodes,
`management_matrix` PASS 992.2s including the rolling restart, fault lane 9/9,
zero residue** - the first unaided pass since 2026-07-15. exact-50 passes
consecutively. The three downstream failures the Slice 1 and 2 maps recorded are
gone, so do not plan around them.

### Three more fixes after Slice 3, each found by the one before it

- `c3bd05fc` `_read_resp` raises for a `-ERR`, and `_node_response` caught that
  alongside every transport failure and re-ran the command through `docker exec`.
  Docker exits 0 when the server answers, error or not, so a failed Valkey
  command came back as a successful reply and was recorded `status: PASS` with
  nothing raised. Every management command that legitimately errored ran twice -
  CLUSTER REPLICATE, FAILOVER, FORGET, SETSLOT and MIGRATE all change state when
  they run - and `_management_log_forget_removed_node`'s tolerance for
  `ERR Unknown node` was unreachable code. An error reply is now
  `ValkeyErrorReply` and is not retried.
- `ded96fac` that fix immediately failed a run at 191s, on a real defect it had
  been hiding: there is no `CLUSTER GETKEYSINSLOT` in the product, so a reshard
  migrated only the keys it planted itself and never drained the slot. The
  workload writes into whatever slots its hash tags land in, and slot 0 is moved
  three times a run. Now drains per the documented protocol. Latent, not chronic:
  950 of 950 `SETSLOT NODE` returned OK in both baselines.
- `e4bc8e55` the drain's extra rows shifted every later command id, and the diff
  compared `command_ref` literally, so unrelated views went red. A command id is
  its position in the log - the class of value this tool already names. Now
  resolved to the kind of command it points at.

Two consecutive exact-50 after all three: **PASS 847.54s and PASS 909.73s**,
6/8 as described below, `cluster_form` 5/5, `runtime_start` 7/7, zero residue,
and the delta identical in both runs.

### `c3bd05fc` has now unmasked a third defect

`313cacc9`, found by the `ERROR` verdict's own acceptance runs rather than by
looking for it. A real exact-50 failed at 397.64s, one run after passing:
`cluster_replicate_restored_node ... ValkeyErrorReply('ERR To set a master the
node must be empty and without assigned slots.')`

`start_node(fresh_cluster_identity=True)` removed only `nodes.conf`. The
generated config sets `appendonly no` and **no `save` directive at all**, so
Valkey's built-in default save policy is active: the workload writes keys, a
background save lands a `dump.rdb` in `dir`, and `SHUTDOWN NOSAVE` does not
remove one already written. The node came back with a fresh cluster identity and a
populated dataset, and `CLUSTER REPLICATE` refuses a node holding keys. Whether an
RDB exists for that node when it is stopped depends on the save thresholds being
crossed, which is what made it look intermittent rather than broken.

`docs/management_matrix_slice_map.md:598` records this exact message at this exact
site on this exact node with `status: PASS`, because the `docker exec` fallback
re-executed the command and `docker exec` exits 0. So the sequence is: masked by
the fallback, unmasked by `c3bd05fc`, then fixed. If another intermittent real
failure appears at a site that fallback used to cover, suspect the same shape
before suspecting the change in front of you.

### What is still open, and deliberately not done

The `ERROR` verdict is **done and accepted**; read
`project/docs/error_verdict_map.md`, which carries the measurement it was argued
from and a closing section on what landed and what the work corrected about its
own map. Six commits, `5b359f00` through `313cacc9`. What it settled:

- `real.local.full-flow` declares `result: json` and takes `--result-path`; the
  run writes `{status, summary}` and exits 0 whenever it wrote a verdict, because
  a non-zero exit makes the Gate report `FAIL` without reading the file. It was
  the catalog's only `exit_code` test out of 95, and its three `real.local.m2-*`
  siblings already worked this way.
- `_read_json_result` accepts `ERROR`; `_overall_status` applies §12.2's
  precedence for a test or suite selection - any `FAIL` wins, then any `ERROR`.
  `BLOCKED` and `TIMEOUT` are untouched.
- `_exception_failure` records which §12.1 kind a step failure was
  (`STEP_TOOL_ERROR` against `STEP_EXCEPTION`), and `run_exact_gate` re-raises a
  tool error as `CollectionError`. `GateStatus` stays `PASS/FAIL/BLOCKED`: a
  collector that broke mid-run is not a fourth lifecycle outcome.
- `is_collection_failure` in `observability/contracts.py` is where the §12.1
  split now lives. It answers `True` only for a `CollectionError` or a
  local-resource errno, and `False` for anything it cannot place, because calling
  a confirmed cluster failure a tool error is the direction that loses a finding.
  A refused connection or a timeout is a *semantic* observation per §12.1.
- §16 items 13 and 14 are met at the run level: `Status: ERROR` measured on a
  real gate invocation, `summary.json` overall `ERROR`, exit code 0. Before this,
  `ERROR` appeared **zero times** across all 168 artifact files in the four
  frozen baselines.

**What the `ERROR` work did not finish**, and is the largest remaining piece of
§12.2: the run still fails fast at the first raise, so within one run there is
never both a `FAIL` and an `ERROR` to aggregate. §12.2's precedence is exercised
at the Gate across tests and inside the stability lane across checks, not across
stages. Recording a failed stage at all needs `lifecycle_timeline.json` to
outlive a failure, which it does not - it is written only after a passing gate,
with literal `PASS` on the artifact and on all twelve step rows. Every artifact a
failing run leaves says `PASS` or is absent; the only thing that says otherwise
is the Gate's own `summary.json`.

Three smaller sites from the map are also still open: the bounded waits
(`_wait_process_light_clean`, `_run_timed_step`) label a `CollectionError` `FAIL`
in a sticky timing row; `evidence/validation.py:41` turns an unreadable artifact
into a `FAIL` where §12.1 says 必要证据无法写入 is `ERROR`, and fixing it needs
`validate_raw_sources` to return the two kinds separately so precedence can
apply; and the Sentinel fault-window samples label a transient `FAIL` where the
sibling `AffectedShardObserver` already records `TRANSIENT` for the same class of
error in the same window. The last is a label defect, not a verdict defect - the
lane's own verdict is correctly `OK` - and the sample counts are not stable
(443 and 455 in the two baselines), so it moves no diff view.

- **Whole-fleet cadence.** Pooling removed the socket cost, not the query cost.
  `_management_wait_clean_cluster` still probes every node at 1 Hz and
  `FullClusterValidator` at 0.5 Hz (`CONVERGENCE_POLL_SECONDS = 2.0`), against a
  design that sanctions one whole-fleet light round per 60s (§4.4) and 3-5
  observer nodes for full topology (§6.1). At 2000 nodes that is 2,000 and 1,000
  queries per second from one centralized process. See
  `project/docs/observability_connection_scale.md`.
- **`_node_response`'s `docker exec` fallback, for transport failures only.**
  `c3bd05fc` stopped it retrying a `-ERR`; being unable to reach a node still
  falls back, and §16.2 says it should not. A test pins that boundary so it
  reads as a decision. Whether the fallback ever legitimately saves a run is
  unmeasured - and it is invisible, because `run_exact_gate` installs no
  `CommandRecorder`, so nothing records these `docker exec` calls.
- **The rolling restart's health gate reads whole-fleet `CLUSTER NODES`.**
  `_management_matrix_wait_rolling_restart_health` falls back to
  `_process_node_snapshots_parallel(nodes)` inside its retry loop, and each
  snapshot is `CLUSTER INFO` + `CLUSTER NODES`. §16 item 1 asks the normal path
  not to run whole-fleet `CLUSTER NODES` periodically; item 3 forbids O(N²)
  normal collection. Distinct from the cadence item above - that one is about
  light-probe frequency, this one is about `CLUSTER NODES`. Found while mapping
  Slice 3; wants its own measurement.
- **`_execute_runtime`'s exception handler reads unbound names.** `nodehosts`
  and `snapshots` are never bound in that scope, so the failure path raises
  `NameError` and falls through to the bare cleanup branch. Pre-existing at the
  pre-refactor commit. Belongs to `runtime_start`'s error path.
- **Did the pre-drain reshard strand keys?** `ded96fac` migrates key batches the
  old code left in place. In the frozen baselines those slots moved with only 4
  migrations and all 950 `SETSLOT NODE` returned OK, which suggests those runs
  finished with keys on a node that no longer owned their slot. Unconfirmed -
  the artifacts record no per-node key counts. A bigger claim than "SETSLOT
  sometimes fails", so do not repeat it without evidence.
- The `<=30` branch of `_configure_process_cluster` has a flaky replica attach
  (the frozen baseline failed both six-node attempts). Its own change, its own
  evidence.
- The standalone `management_matrix` capability (`write_management_matrix_artifacts`)
  drives the same operation core through a different frame, has no registered
  real gate test, and no baseline covers its artifacts.
- **`fault/sandbox.py` is a second Docker actuator** - 490 lines importing
  `run_docker`, implementing fault apply/clear (kill, container stop, restart,
  pid-file removal, PING probe), reached from `cli.py fault apply`/`fault clear`
  and `compat/phase_aliases.py`. §15 makes the actuator the one thing an adapter
  replaces, so after Slice 4 there are two. Nothing in the lifecycle calls it
  and no acceptance bar exercises it.
- **A six-node smoke cannot reach `management_matrix` or `fault_matrix`, and
  there are three separate reasons, only one of which was recorded here before.**
  The *gate* refuses six (`real.local.full-flow` declares `minimum: 30`). The
  **scenario definition also refuses six**: `local_full_flow_v1.json` declares
  `scale_policy.min_nodes: 30`, so `gate execute` rejects it at plan compilation -
  measured 2026-08-09, `requested_nodes must be in the exact supported range
  30..2000, got 6`. Only *`_full_flow_profile`* is permissive, resolving six to
  `small-real`; that is what the earlier note meant by "the product does not",
  and reading it as "reachable through the CLI" is wrong. Third, if the first two
  were bypassed, `fault_matrix`'s own target selection would stop it -
  `single_mac_6node.yaml` declares `virtual_az_mode: single`, so every node is in
  `az-local`, and `az_stop` selects a survivor *outside* the target AZ, raising a
  bare `StopIteration`. Measured: six nodes give two nodehosts, both `az-local`.
  **exact-30 is the smallest real run that exercises either stage**
  (`management_matrix` PASS 728s / 60 rolling-restart rows; `fault_matrix` PASS
  ~214s / 9 scenarios). Do not plan a clean-room failure case around exact-6:
  the `error_verdict_map` did, and it does not exist.

Slice 4's four fixed numbers are worth keeping: `fault_matrix` emits **9 fault
scenarios, 12 command rows and 15 workload windows at every scale** (30, 50 and
200), and the primary-kill RTO has landed between 45s and 50s in every run at
every scale. Any change to those four is a finding.

Per-slice acceptance bar: existing catalog tests plus targeted hermetic tests
pass; a real small-scale smoke of the modified stage - six nodes where the stage
is reachable at six, exact-30 where it is not; real exact-50 with normalised
stage-owned artifacts diffed against the baseline, ignoring only timestamps,
durations, run ids and temporary paths; exact-200 as well for `runtime_start`,
`cluster_form` and `stabilize`; the old path proven removed with no fallback and
no duplicate implementation. Then stop and report. Do not start the next slice
without approval. If preflight cannot pass, stop before modifying code.

Run the diff with `./scripts/diff_stage_artifacts.py --stage <stage> BASELINE
CANDIDATE`, adding the stage's views from its slice map. Calibrate it first by
diffing the two baseline runs against each other and requiring every view
identical; a normalisation loose enough to hide their differences would hide a
regression too. Both baselines stay frozen at the pre-refactor commit for every
slice. Do not re-baseline after a slice, or drift accumulates one slice at a
time with no single diff ever showing it.

Calibration alone is not enough, and Slice 3 proved both halves of that.
**Check the views detect a defect, not only that they agree**: seed a handful of
plausible regressions into a copy of a baseline run and require the view that
owns each one to report it. That caught a normalisation of mine that resolved
every command reference to the same `<cmd:UNKNOWN>` token - it calibrated
perfectly and would have hidden a probe pointing at the wrong command.
And **two runs agreeing is not proof a field is deterministic**: the frozen
baselines happened to record identical rolling-restart probe counts, so
calibration could not reveal they were retry counters, and a third run differed.
When a field turns out to move, report it beside the diff rather than comparing
it - and draw the boundary once, by what the field *is*, instead of adding
exclusions one run at a time until the diff goes green.

- `project/artifacts/baselines/exact-50-6b6f57fd/` - two passing runs. Carries
  every stage's artifacts including `management_matrix`'s
  (`rolling_restart_plan.json`, `rolling_restart_results.jsonl`,
  `management_sequence.json`, `management_command_log.jsonl`).

  **`management_matrix` diffs 6/8 against it now, and 6/8 is the pass mark** -
  but the delta has **two declared components** since `313cacc9`, and a diff that
  shows only one of them is as much a finding as one that shows a third:

  1. `ded96fac` drains a slot's keys before reassigning it; the frozen baseline
     encodes the code that did not, so a correct run legitimately emits extra
     `cluster_migrate_keys` rows. Measured in four runs across three commits as
     **exactly +14 rows, `cluster_migrate_keys` 4 → 18** in
     `management_command_log`, with the matching `command_count` and
     `command_log_refs` growth in `management_sequence` (1051 → 1058).
  2. `313cacc9` renamed the command record that discards a node's prior state,
     because it now removes the dataset as well as `nodes.conf`. Measured in two
     runs as **exactly four rows**, one each in `add_replica`, `remove_replica`,
     `remove_failed_node` and `remove_primary_drained_or_safe_replaced`, changing
     `command_kind` from `owned_valkey_process_remove_nodes_conf` to
     `owned_valkey_process_discard_prior_state` and gaining the RDB path in
     `argv`. A rename moves no rows, so the row count stays +14.

  Together: **row count +14, three row kinds changed and 14 unchanged.** Check
  that shape, not equality. The other six views must still be identical, and
  `runtime_start` 7/7 and `cluster_form` 5/5 are unaffected. Both are intentional
  behaviour fixes, not drift, which is why the baseline stays frozen anyway.

  **`fault_matrix` diffs 5/6 against it, and 5/6 is the pass mark**, for the
  same kind of reason: the baseline predates `85d5096a`, so its partition
  scenarios read the isolated node through the `docker exec` fallback and saw
  it answer. Measured identically in four runs across two commits, the delta is
  confined to `fault_sequence` and to the three partition scenarios' isolated
  side - `isolated_reachable_from_this_side` and `isolated_unreachable_reason`
  added (×3), `isolated_cluster_info` no longer observed (×3),
  `isolated_cluster_state_ok` true→false (×1, the one scenario where the
  baseline had it true), and that side's `client_observations` row flipping to
  unreachable. Check that shape, not equality; the other five views must be
  identical.
- `project/artifacts/baselines/exact-200-6b6f57fd/` - captured 2026-08-08, two
  runs, both failing downstream as every exact-200 run at that commit does.
  Calibrated: `runtime_start` 6/6 comparable views identical, `cluster_form`
  4/4, `lifecycle_timeline:<stage>` unavailable in both because a failing run
  never produces it. It took four attempts: two died before
  `cluster_myslots_report.json` was written and could not supply the views that
  name a node id. Read its `BASELINE.md`. **No exact-200 run at 6b6f57fd reaches
  the management lane**, so this baseline cannot cover `management_matrix`'s own
  artifacts - exact-50 carries those.

## Working rules

- `project/docs/scalable_cluster_observability_design.md` is authoritative. Read
  the relevant section before changing anything under `observability/`. §11.1
  forbids a docker exec per resource sample; §15 makes endpoint discovery the
  runtime adapter's job; §16.2 forbids docker exec for Valkey protocol checks;
  §8 fixes the Load Lane tool and parameters.
- Measure before hypothesising. Bring up a live cluster and look, rather than
  reasoning from code. Several confident diagnoses were wrong and only real
  observation settled them.
- Make the smallest correct change at the site that is actually wrong. Do not
  broaden a fix, patch sibling call sites pre-emptively, add abstraction for
  hypothetical needs, or soften a contract to make a symptom disappear.
- Report before any semantic change to a validation contract. When a new failure
  appears, report its exact stage and semantics rather than assuming it needs the
  refactor.
- Commit each distinct fix separately, saying what was observed. Keep
  `./gate suite repository.all` at 91/91 before committing, and run two
  consecutive real exact-50 runs after.
- Do not build a custom load generator. The Load Lane is scoped to steady state
  by decision; the Sentinel canaries own fault-window continuity and RTO.

## Environment facts

- The macOS host cannot route Docker's `172.18.0.0/16`. The cluster announces
  those addresses, so anything following MOVED must run on that network or
  resolve endpoints through the runtime adapter.
- There is no `/proc` on Darwin. The resource sampler runs as a long-lived agent
  inside each nodehost container.
- The host has 16,384 ephemeral ports (49152-65535) and `net.inet.tcp.msl=15000`,
  and the macOS allocator does not exploit destination diversity: exhaustion was
  measured at 16,349 concurrent TIME_WAIT across 200 distinct destinations, and
  it surfaces as `[Errno 49] Can't assign requested address`. A whole-fleet probe
  on a one-second control loop is what reaches that ceiling. Linux moves the
  ceiling but not the shape - see `project/docs/observability_connection_scale.md`.
- A partition made with `docker network disconnect` severs the published-port
  path too: the isolated node is unreachable from the host, measured as a 33s
  timeout. Only `docker exec` reaches it, which is why the partition probe must
  not use a helper that falls back to `docker exec`.
- The pinned image carries memtier 2.5.1 and python3, both digest-verified.
  Rebuild with `project/scripts/build_valkey_image.sh`.
- There is no `kill` binary in the image, only the shell builtin.
- `project/.dockerignore` exists because the build context reached 763 MB and
  stalled a build for 53 minutes. Do not remove it.
- Docker Desktop wedges occasionally. If `docker network create` returns an id
  that `docker network ls` does not show, it needs a restart; that is not a bug
  in this repo.
- The milestone-loop controller is disabled on purpose
  (`.github/workflows/milestone-loop.yml.disabled`). Leave it off.
