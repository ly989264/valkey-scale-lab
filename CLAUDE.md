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
`fault_matrix` - are done and accepted, and roadmap item 0.5 added the two §15
operations no stage had needed. `runtime/node_backend.py` holds `NodeBackend`,
the seam every later slice extends; `DockerNodeBackend` in `docker_runtime.py`
is its one implementation, now **twenty-three methods**. Read the five slice
maps in `project/docs/` before the next slice: they carry the accepted seam, the
measured result of every bar item, and the limitations below.

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
capabilities.

Corrected 2026-08-09: this section used to add that `_wait_container_pid_gone`
and `_safe_process_pid` "have no lifecycle caller at all". That is wrong.
`_wait_container_pid_gone` has three - `stop_node` twice and `kill_node` once -
all reached through the seam, and an exact-200 run failed inside it (`4dd0fa1b`).
The claim was derived by reading rather than from a run, which is the same way
the six-node entry below went wrong. Prefer a measurement.

**There is no next extraction slice.** What remains is the open list below.
`fault/sandbox.py` was the other candidate; it is now **decided rather than
open** - the operator approved deleting it and the CLI surface it serves on
2026-08-10, and that deletion is Session C's to execute. See
`project/docs/fault_sandbox_decision_memo.md`.

### Phase 0 progress, 2026-08-10

Phase 0 is the roadmap's (revision 5.1) precondition list, executed as three
worker sessions. **Session A is done**; its scope was roadmap items 0.2 and 0.3.

- `ce0bea2d` **item 0.2** - `_execute_runtime`'s failure handler was the process
  path's, copied onto the container path, and neither `nodehosts` nor `snapshots`
  is bound there. Measured: `NameError` on the first line, swallowed, so every
  container-path failure left an empty artifacts directory. It also could not
  have worked with its names bound, because both state builders read
  `container_id`/`pid` off every node and a fleet that failed partway through
  starting has neither; the state is now built from `started`.
- `3315e6af` **item 0.3, the record half** - `run_exact_gate` now installs a
  `CommandRecorder`, writing to `runtime/command_audit/` beside the run. Two
  fixes were needed before it could answer anything, and both are general.
  **The recorder is a `ContextVar` and a new thread starts with an empty
  context**, so everything inside `_bounded_parallel` went unrecorded - 2686 rows
  against 4194 once fixed, missing almost all of cluster formation.
  **`record_result` rewrote the whole log per row**, measured 1.96 ms/row at 250
  rows and 47.39 at 4000; a real exact-200 records ~13,800 and *failed* at
  1586.80s in `_process_node_snapshots_parallel` because of it, against a control
  PASS at 1578.29s on the parent commit. Recording appends now; `close` still
  writes the file sorted, byte-identical.
- `e04d6ce9` **item 0.3, the remove half** - `_node_response`'s `docker exec`
  transport fallback is gone. Measured before removing: it fired **four times in
  a passing exact-200 and never in four passing exact-50 runs**, all four at one
  site - `start_node`'s readiness poll, first attempt after `valkey-server`
  starts, host path reading an empty RESP reply - and that poll is a 30s loop
  that already catches, sleeps 0.5s and retries. So it bought one early poll,
  not a run. The proof it is gone is the same run before and after:
  `docker exec ... valkey-cli` rows were 624 actuator + 4 `cluster_probe`, and
  are now 624 actuator + 0.

Two operator decisions are still open from Session A's reports: what to do about
`.github/milestone-loop/` working-tree changes left by a mis-popped stash, and
whether the RTO correction above needs anything further. The working-tree
changes are still present and still nobody's - do not commit them.

**Session B is done**; its scope was roadmap item 0.5 and the 0.6 memo.

- `4f54442a` **item 0.5** - the seam gained `load_lane_host` and `release_run`,
  the two §15 names it lacked. Read `project/docs/seam_completion_slice_map.md`;
  it carries the derivation, both boundaries' measurements and the two findings
  below. What it settled: **evidence upload had one site outside the seam, not
  several** - the resource sampler already pulls its own samples through the
  object the backend returns, so §15's sampler deployment and the upload of what
  it produced are one member. What was left was memtier's JSON and HDR, copied
  by a `docker cp` inside `observability/load.py`, a module §15 declares
  *invariant*. That module named `docker` three times and now names it zero.
  **End-of-run cleanup was not behind the seam at all**: `cleanup_scenario`
  dispatched on `runtime.type == "docker_process"` and otherwise ran
  `docker ps --filter label=...`, so a native run's state would have taken the
  container path, found nothing owned by that run in Docker, and written
  `status: PASS` with every remote process still running. That is now a stated
  refusal with a test. The report assembly is neutral and lives in
  `runtime/teardown.py` - not `lifecycle.py`, which would be an import cycle.
  `BackendSpec.node_backend`, declared at `39e31b1a` and never called, has its
  first consumer. Proven: 91/91, two consecutive real exact-50 at PASS 909.03s
  and 836.50s, all four diff marks met with both declared deltas at their
  declared shapes, `cleanup_report` byte-identical under the new assembler.
- `ff4e4f21` **item 0.6, the memo** - see below.

Item 0.5 also added two diff views, because neither of its surfaces was covered:
a `cleanup` stage and a `load_lane_evidence` report under `management_matrix`.
Both calibrate identical baseline-to-baseline, eight seeded regressions were
each caught by the view that owns them, and a control that renumbers every pid
correctly stays quiet.

**Session C is next**: the approved `fault/sandbox.py` deletion, then the exit
gate - two consecutive exact-50 plus one exact-200 at exit HEAD, and the
completion report. Then idle; M3-A begins on operator approval, never as Session
C's next step.

### What is left before M3, and what is M3 itself

Worth separating, because it is easy to list M3's contents and call them
prerequisites. Five of M3's six criteria - inventory and placement, the native
runtime, exact-50, exact-200, evidence, cleanup - are M3's *work*, not conditions
for starting it.

The genuine preconditions are:

1. ~~**Close the refactor.**~~ **Done at `39e31b1a`.** The sequencing moved to
   `runtime/lifecycle.py`, backend selection became the data registry in
   `runtime/backends.py` with `native_multi_ecs` *absent* rather than rejected,
   and the Gate's Docker-daemon check became a backend property. Proven a pure
   move by 91/91 plus a real exact-50 at all four diff pass marks; an exact-200
   on the neutral lifecycle followed on 2026-08-10 (PASS 1578.29s, 12/12), which
   that single-exact-50 proof had not included.
2. ~~**Declare the two seam operations §15 names and this seam lacks.**~~
   **Done at `4f54442a`.** `load_lane_host` is evidence upload and `release_run`
   is end-of-run cleanup; `reclaim_run` keeps its pre-run meaning and now says
   so. The protocol a second backend implements is **frozen at twenty-three
   operations** unless a later slice argues otherwise - M3 item 1.2 owes the
   whole of it, and no stale count from an older section applies.
3. ~~**Decide `fault/sandbox.py`.**~~ **Decided 2026-08-10: delete it and the
   `cli fault apply`/`clear` surface it serves** (memo option A). The deletion is
   Session C's work, not done yet. What decided it was not the duplication:
   `apply_fault` accepts seven fault types and **six of them inject nothing and
   record `status: PASS`**. So a second backend owes this nothing.
4. **Confirm the ECS hosts exist.** Five of six criteria need real multi-host
   runs, and the sixth is unverifiable without them. Gates M3-*acceptance*, not
   M3 development.

Also, and easy to miss: **M3 has a registered check on 1 of its 6 criteria, M4 on
1 of 7.** A milestone whose criteria have no attached checks reports `DEFINED`
and can never report `PASS`, so each criterion needs a real Test registered in
`catalog.json` as it becomes executable. No placeholders.

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

### exact-200 is green again at `216b2f70`, and now for a measured reason

That pass, and one on 2026-08-08 at 1661s, were real but intermittent: two
attempts on 2026-08-09 failed at 397.9s and 291.7s, for two different reasons,
both since fixed. **exact-200 PASS 1568.81s** at `216b2f70` - 200 of 200 nodes,
`run_verdict` twelve of twelve stages OK, `fault_matrix` 9 scenarios / 12 command
rows / 15 windows, cleanup clean, zero residue, and no `ERROR` anywhere in the
run's artifacts.

The two fixes behind it are worth knowing before reading any exact-200 result:

- `4dd0fa1b` `_wait_container_pid_gone` tested `/proc/<pid>/stat` for readability
  and then read it, two syscalls apart. A process exiting in between made `awk`
  fail and the probe exit 70 - the success condition taking the error path, since
  the whole function waits for the process to be *gone*. It needs the timing to
  line up, which is why exact-50 never showed it and exact-200, with far more
  stop and kill traffic, did.
- `216b2f70` the formation convergence bound was a fixed 180s calibrated on
  exact-50. Measured at 200 nodes over five formation-only runs, convergence is a
  serialised queue - one node unhealthy at a time, clearing and handing off - so
  the total is (laggards) x (per-laggard dwell) and **both** factors grow with
  node count. Totals: 83.1s, 102.5s, 137.0s, 152.0s, 205.8s; **one of five past
  the old bound**. exact-30 converged in 26.5s. The wait is now bounded on lack
  of progress - something leaving the pending set - with `240s` sized on the
  longest single dwell (83.1s at 200, 14.3s at 30, 26 dwells, median 23.5s, p90
  51.1s) and a 1800s ceiling as a backstop. `project/docs/convergence_bound_map.md`
  carries the argument.

Two numbers to watch rather than assume. The 240s window is **not scale-free**
and must be re-measured before 500 nodes, and again on any distributed backend,
where gossip crosses a network. And the primary-kill RTO was **53.75s** in this
run against the 45-50s exact-50 band; see the corrected reading below - four
exact-200 runs now span 47.6-53.8s, so this is dispersion, not a shifted band.

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
- **`_spec` sets no `host`, so `_node_command` cannot reach a container-backend
  node.** Only the process path adds `host`; a `docker_container` node carries
  `container_ip` and no `host`, and `_node_host_command` refuses to default one
  by design. Measured 2026-08-10 against both the pre- and post-removal module:
  it raises `KeyError('host')` either way, so this is pre-existing and was never
  masked in a real run - the `docker exec` fallback declined it too, because
  `container_ip` was set. It is moot today only because **`scale_ladder` is
  registered to no backend** (`implements_scenario` is False for both), so no
  real run reaches `write_scale_ladder_artifacts`. Both belong to whoever
  registers that scenario; two hermetic tests in `tests/scale/` used to reach it
  through the fallback and now fake `_node_host_command`.
- **The rolling restart's health gate reads whole-fleet `CLUSTER NODES`.**
  `_management_matrix_wait_rolling_restart_health` falls back to
  `_process_node_snapshots_parallel(nodes)` inside its retry loop, and each
  snapshot is `CLUSTER INFO` + `CLUSTER NODES`. §16 item 1 asks the normal path
  not to run whole-fleet `CLUSTER NODES` periodically; item 3 forbids O(N²)
  normal collection. Distinct from the cadence item above - that one is about
  light-probe frequency, this one is about `CLUSTER NODES`. Found while mapping
  Slice 3; wants its own measurement.
- **A failing `docker_process` run still leaves only a bare `reclaim_run`.**
  `_create_process_scenario`'s handler in `runtime/lifecycle.py` reclaims and
  re-raises: no state file, no `setup_error`, no cleanup report. Unlike the
  container path's handler (fixed in `ce0bea2d`) this is not a defect - it was
  written that way - but M3's cleanup criterion may want the richer record, and
  the two paths now differ. Decide deliberately rather than by drift.
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
  and no acceptance bar exercises it. **No longer open: approved for deletion
  2026-08-10, Session C executes it.** Two things the memo measured that this
  entry did not know - six of the seven fault types inject nothing, and
  `clear_fault`'s `container_stop` branch is unreachable from `apply_fault` -
  and one consequence it did not name:
  `runtime/teardown.py::_remove_fault_state_files` goes with it, because
  `apply_fault` is the only producer of `fault_state_*.json` anywhere.
  **M1 needs no edit** - measured 2026-08-10 and decided then. `product.fault`
  goes 3 tests to 1 and survives on `product.fault.network_proxy`, so no
  criterion loses its checks; `local.operations-and-recovery` covers six
  behaviours across four suites and only one of them is touched. An earlier
  version of this entry said that check list needed a decision. It does not, and
  removing the criterion would drop failover, observability and stability
  coverage that has nothing to do with this module.
- **No fault path will check ownership once `fault/sandbox.py` is gone.**
  Measured 2026-08-10 while pricing that deletion: `_require_owned_container`
  inspects a container's labels and refuses if they are not this run's, and it
  is the only such check on any fault path - the seam's own actuator has none.
  `kill_node` reads `nodehost_container_name` off the node and execs. So the one
  test of M1's phrase "confined to project-owned resources" goes with the module.
  Operator decision: **accept the loss, change nothing in M1.** Giving the
  actuator its own ownership check is a *candidate*, deliberately not done - it
  is new behaviour, it needs its own evidence, and a second backend would
  inherit it, so it belongs to whoever writes one rather than to a deletion.
- **End-of-run cleanup terminates by stale pid.** Measured on both frozen
  exact-50 baselines: at cleanup each nodehost has 12-13 live `valkey-server`
  processes and **zero of them is a pid recorded in `state.json`** - the state
  is last written before the management matrix, and the rolling restart plus the
  fault matrix replace every process. So `terminate` signals fifty pids that no
  longer exist, `verify_exit` truthfully confirms they are gone, all four
  `verify_no_valkey_processes` rows come back `SKIPPED_WITH_REASON` with the
  live list, and `docker rm -f` is what actually stops the fleet. Correct under
  Docker; **a backend with no container to remove has no such backstop**.
  Deliberately not fixed in item 0.5 - extraction preserved it faithfully - and
  deliberately **not** a Session C item either. Operator decision 2026-08-10:
  **carry it into M3-A item 1.4**, where the native backend must clean the
  processes actually alive at teardown rather than assume `state.json`'s pid is
  current.
- **No node log is ever collected.** Every node is configured with
  `logfile <data_dir>/valkey.log`, the path is recorded in the bundle manifest
  and in `state.json`, and nothing reads it; the files die with their
  containers. §15 names 日志与证据上传 and item 0.5 gave 证据 a boundary, so the
  日志 half has no implementation on either backend. Operator decision
  2026-08-10: **carry it into M3-A item 1.3**, and decide there what artifact
  satisfies the existing *process journals* requirement. **Do not pre-decide the
  mechanism.**
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
200) - still exactly so at `216b2f70`, exact-200 included. The fourth has moved:
the primary-kill RTO landed between 45s and 50s in every run until 2026-08-09,
when exact-200 measured **53.75s**. That rule said a second exact-200 above 50s
would make it a finding. It fired, and the finding is **dispersion, not a
shifted band**: four exact-200 runs measured **53.75s, 53.15s, 49.75s and
47.62s** (2026-08-09 and 2026-08-10), two of them inside the exact-50 band,
while five exact-50 runs the same day measured 45.6-49.4s. So 45-50s is the
exact-50 band, exact-200 is wider and overlaps it, and **one exact-200 above 50s
is not a regression signal** - a shift in the whole spread would be. Any change
to the first three is still a finding.

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
