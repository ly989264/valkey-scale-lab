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

## Where the work stands

**The lifecycle refactor is closed and Phase 0 has exited.** Both are history
now, and this section is the reference a later session needs rather than a plan.
Read `project/docs/roadmap_preconditions_exit_report.md` first for the current
state; read on here for how the seam came to be shaped the way it is.

The refactor's goal was to separate the full-flow lifecycle from the Docker
backend so M3 can exist. It succeeded: `execute_scenario` used to reject
`native_multi_ecs` from inside `docker_runtime.py`, so a second backend could not
be written without living in the Docker module or duplicating it, and that
rejection is gone - `runtime/backends.py` is a data registry with
`native_multi_ecs` simply *absent*. M2 stays defined as written but is parked;
the priority is a well-implemented real cluster test at 50/100/200, then M3 and
M4 on top.

Slices 1, 2, 3 and 4 - `runtime_start`, `cluster_form`, `management_matrix` and
`fault_matrix` - are done and accepted, and roadmap item 0.5 added the two §15
operations no stage had needed. `runtime/node_backend.py` holds `NodeBackend`,
the seam every later slice extends; `DockerNodeBackend` in `docker_runtime.py`
is one of its two implementations, now **twenty-four methods** (item 1.3 added
the last). Read the slice maps in `project/docs/` before the next slice: they
carry the accepted seam, the measured result of every bar item, and the
limitations below.

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
worker sessions. **All three are done and the exit gate passed**; the summary is
`project/docs/roadmap_preconditions_exit_report.md` and the detail is below.
**Session A** was roadmap items 0.2 and 0.3.

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

**Session C is done, and with it Phase 0.** Its scope was the approved
`fault/sandbox.py` deletion and then the exit gate.

- `5d260c7e` **item 0.6, the deletion half** - the module, the whole `fault` CLI
  command group, the two `cli_compat` wrappers, `_remove_fault_state_files`,
  three catalog tests and their files. Both memo claims were re-measured against
  HEAD before removing anything: six of seven fault types issue **zero** runtime
  commands against `node_stop`'s four, and importing `gates.real` plus
  `runtime.lifecycle` never loads the module. **`repository.all` is 88 tests,
  not 91.** Declared artifact change: `cleanup_actions` can no longer carry a
  `type: fault_state` row, which moves no diff - no baseline and no exit-gate run
  ever produced one, and `cleanup_report` stays byte-identical.
- **The exit gate passed.** exact-50 **PASS 889.45s** and **PASS 835.35s**,
  exact-200 **PASS 1572.30s**, all three 12/12 checks OK, zero residue, and the
  string `ERROR` in no artifact of any of them. Both exact-50 runs hit every
  stage mark - `runtime_start` 7/7, `cluster_form` 5/5, `management_matrix` 6/8,
  `fault_matrix` 5/6, `cleanup` 2/2 - with both declared deltas at their declared
  shapes and no third. Fault lane 9/12/15 at both scales. RTO 47.87s, 47.62s and
  47.60s.

Read `project/docs/roadmap_preconditions_exit_report.md`. It carries every
item's evidence, what is open, what M3-A inherits, and the session grain for
M3-A.

### M3-A has started. Session M3-A-1 is done: roadmap items 1.0 and 1.1

The operator approved M3 start on 2026-08-10. M3-A-1's scope was the simulated-
host harness and the pinned native build, and both landed. Read
`project/docs/simulated_host_and_native_bundle_map.md`; it carries the
derivation, every measurement, and what was deliberately left to later items.

- **The harness is lab tooling and lives beside the pinned image's build**, not
  in a new directory: `docker/simulated-host/` and three `scripts/` entries. The
  boundary that matters is the import graph - the harness imports nothing from
  `valkey_scale_lab`, and the product imports nothing from `scripts/`. One
  product file exists, `runtime/native_bundle.py`, because verifying build
  products is `verify_image`'s job and therefore product; item 1.2 gives it its
  first caller.
- **The manifest is the only thing that crosses to the product**, and it names
  no container, image or network, and carries no simulated flag - a backend that
  could tell would make every result taken on simulated hosts a fact about the
  harness. `_reject_container_vocabulary` enforces it at the write, and it
  already caught one leak: the private key path is in the manifest, so the state
  directory is `artifacts/host-fleets/`, not `artifacts/simulated-hosts/`.
- **Each host record carries three addresses**, because a host has three roles
  the seam already distinguishes: `control_endpoint` (where the controller runs
  commands), `data_address` (what peers dial), `client_endpoint` (where the
  controller speaks RESP, with a port *range*). Under this harness the last two
  differ because macOS cannot route Docker's network; on a real fleet the
  manifest repeats one address and the field set does not change. Everything a
  real fleet would also have is read **from the host over ssh**, not from
  `docker inspect`.
- **A defect the first bring-up found, which reading could not have**: both
  hosts served one ssh host key fingerprint. Debian's `openssh-server` postinst
  generates host keys during the image build, so the entrypoint's `ssh-keygen -A`
  found them present and did nothing, and they sat in a shared layer. The image
  now deletes them and the build script refuses an image carrying any.
- **The simulated host removes what it inherits.** Derived from the pinned image
  for its OS and libraries, it deletes `valkey-server`, `valkey-cli`,
  `memtier_benchmark` and the build manifest - the run bundle's `start_all.sh`
  invokes bare `valkey-server`, so a host that already had one would make a
  bundle install unfalsifiable. libevent and python3 stay, as a provisioned ECS
  host would have them.
- **The bundle reuses the pinned Dockerfile's existing `binaries` stage** rather
  than compiling anything of its own, and cross-checks every digest against the
  pinned image's build labels before writing. The archive is byte-reproducible
  (two builds, `fe1839de…067d`). `verify_native_bundle` returns preflight
  evidence using the *existing* key names, because `_write_cluster_myslots_report`
  reads `image_preflight["valkey_server_sha256"]` and the `runtime_start` diff
  view carries the whole mapping.
- **It declines to claim the one check it cannot make.** The Docker preflight
  starts the server and asks for `CLUSTER MYSLOTS`; this one hashes bytes on the
  controller, so the evidence carries `not_verified.cluster_myslots_command`
  with a reason. That gap was then closed *as a measurement* on the hosts: the
  bundle installed on both, digests matched, and the patched command answered.
- Proven: `repository.all` **90/90**; two simulated hosts up in 1.07s with ssh
  answering at 1.71s and distinct fingerprints; real `iptables` under NET_ADMIN;
  one byte appended to `valkey-server` fails preflight with both digests named.

**No real gate run was taken and none was needed** - neither item is on a run's
path until item 1.2 exists. **The correct state now is idle**; item 1.2 begins
on operator approval, never as a next step.

### Session M3-A-2 is done: roadmap item 1.2, the native backend

`native_multi_ecs` is registered because the backend exists. Read
`project/docs/native_backend_slice_map.md`; it carries the derivation, the
transport measurement, what the implementation corrected about its own map, and
the one gap it found in the roadmap's sequencing.

- **The seam held.** All twenty-three operations are implemented with their
  declared signatures and return shapes, and nothing in the protocol had to
  change to admit a second implementation. That was not guaranteed: a protocol
  with one implementation is a description of that implementation until a second
  disagrees with it.
- **The transport decision closed, provisionally, on multiplexed SSH**, on
  numbers rather than taste. The budget is the rolling restart's own, taken from
  the frozen baseline's 1,592 command rows: its two backend operations run at 71
  ms and 61 ms median, both the cost of one `docker exec`. Measured the same hour
  on two simulated hosts - `docker exec` **66.4 ms** median, un-multiplexed ssh
  **63.8 ms**, multiplexed ssh **10.8 ms**, and at the run's own parallelism of 8,
  11.9 ms against `docker exec`'s 63.5 ms. So the fallback on-host agent was not
  built. **Simulated numbers are lower bounds**; M3-B (item 1.6) closes this for
  real, and the transport stays behind an interface so the switch stays cheap.
- **Two constraints the spike found that reading could not.** `ControlPath` is
  capped at **104 bytes** by `sockaddr_un` - the first spike run failed outright,
  and pytest's own `tmp_path` on this platform is already 127 - so the mux socket
  cannot live beside a run's artifacts. And sshd's stock `MaxSessions 10` does
  **not** fail past its limit, it queues: measured to parallelism 32 with zero
  failures, median 11.8 → 23.0 ms, throughput flat at ~600/s. No session
  semaphore is needed; it is a latency term.
- **A native run places exactly one nodehost per host, and refuses otherwise.**
  A nodehost is a fault domain - the plan rejects a shard whose primary and
  replica share one, and the actuator suspends or isolates a whole nodehost.
  Under Docker they coincide by construction; on a fleet only if the placement
  makes them. Its consequence is item 1.5's: at 25 logical nodes per nodehost a
  two-host fleet holds exact-50 exactly and **cannot hold exact-200**.
- **Placement is planning, not the backend's**, settled by an artifact rather
  than by taste: `nodehost_density_plan.json` is written before `start_nodehost`
  is called, so a backend that chose the hosts would leave that artifact saying
  `host_id: "local"` about a run that placed them on named hosts.
- **The inventory vocabulary decision is closed: keep `container_*`.** All three
  fields survive translation with their meaning intact - the peer address, the
  run's claim, the run-scoped name - so they are misnamed rather than
  semantically wrong, which is the test the roadmap set. Renaming would move
  `state.json`, `cleanup_report`, the schemas and four of five diff views, and
  turn every frozen baseline red for readability.
- **The partition actuator has one difference it declares rather than hides.**
  Docker reaches the container through the daemon and can sever every network
  path; this actuator reaches the host over the network it is cutting, so the
  control port is spared - and read from the session, not assumed, because the
  manifest's port is the forwarded one (measured: `SSH_CONNECTION` says 22 where
  the manifest says 22200). The `85d5096a` observable contract is unchanged and
  item 1.5's equivalence diff is where it is proven.
- **Three sites above the seam were not backend-neutral and now are.**
  `_execute_runtime` built `DockerNodeBackend()` by name, so the registry's claim
  was true of teardown only. `_process_runtime_state` wrote `backend_id` and
  `runtime.type` as the literal `docker_process` - the same defect `4f54442a`
  found in `cleanup_scenario`, in the sibling function. And the port preflight
  binds on the controller's loopback, which is now a declared backend property.
- **One validation-contract change, reported rather than slipped in.**
  `config/validation.py` refused any `runtime.provider` but `docker`, while
  `execution.BACKENDS` has always declared `native_multi_ecs` with provider
  `ecs`, so no configuration could select this backend. `ecs` is admitted with
  two required fields of its own; `docker` keeps every rule it had.

- **Proven:** `repository.all` **91/91**; 51 hermetic checks against a fake
  transport; and two real exact-50 runs, **PASS 872.72s** and **PASS 872.62s**,
  both 12/12 with zero residue and no `ERROR` in any artifact. Five of this
  item's changes are on a real run's path, so the claim that Docker runs are
  unaffected was measured: both runs hit every stage mark identically -
  `runtime_start` 7/7, `cluster_form` 5/5, `cleanup` 2/2, `management_matrix`
  6/8, `fault_matrix` 5/6 - with both declared deltas at their declared shapes
  (row count +14, `cluster_migrate_keys` 4 → 18, three row kinds changed and
  fourteen unchanged) and no third. Fault lane 9/12/15 in both. RTO 47.995s and
  46.555s, inside the exact-50 band.

**What item 1.2 did not prove, and it is the honest boundary:** no argv in this
backend has run against a host *through the product*. A fake transport proves
what the backend would run, not that the host answers.

**Operator decision 2026-08-11: a native bring-up smoke goes at the front of
item 1.5.** Two simulated hosts, the backend driven directly - claim, install,
start, stop, isolate, rejoin, release - with no Gate run, no cluster and no
scenario, so that a first native exact-30 failure does not have twenty-three
unexercised operations in its search space. It is the ladder's own first rung,
so it is **not a separate item** and the session grain is unchanged: **M3-A-3 is
item 1.3, M3-A-4 is item 1.4, M3-A-5 opens with this smoke.** Slice map §11
names the three argv most worth driving first.

Carried forward untouched and still owned elsewhere: stale-pid teardown (item
1.4 - and note the native backend has **no `docker rm -f` backstop**, which is
why its residue scan measures rather than asserts), and the absent fault-path
ownership check. Node-log collection was item 1.3's and is done; see below.

### Session M3-A-3 is done: roadmap item 1.3, cross-host evidence

The seam is **twenty-four operations**, not twenty-three, and that number is the
one a later reader should use. Read
`project/docs/cross_host_evidence_slice_map.md`; §11 carries every measurement,
§10 the findings it reported rather than fixed, and §8 the simulated-fleet answer
M3-A-1 left open.

- **"Complete and attributable" was made refusable before it was implemented.**
  Attributable = the run names the host a piece of evidence was produced on, in
  the inventory's `host_id`, and the offset between that host's clock and the
  controller's. Complete = every observed node has a journal, every nodehost is
  clocked at both ends, every host-produced surface is claimed by exactly one.
  `host_evidence.json` carries it, is a declared raw artifact so its digest binds
  into the provenance graph, and `validate_raw_sources_by_kind` refuses eleven
  distinct ways of not saying it.
- **Only one of the four evidence surfaces was already attributable**, found by
  reading producers rather than artifact names. Command logs are timed by the
  controller on both backends and carry `target_logical_id`, so they needed
  nothing - which is the honest answer, not an omission. Resource documents are
  attributed only by `sampler_id`; the load lane's 18 files carried **no
  attribution at all**; node journals were never collected.
- **The seam grew by one, argued rather than taken.** §15 names 日志与证据上传 as
  an adapter category whose 日志 half had no implementation on either backend,
  and a host's clock cannot be read from above the seam by construction.
  `load_lane_host` could not carry it: it means "where the Load Lane runs for
  this node", and its native form copies a whole remote directory, so a journal
  fetch through it would drag the dataset back with the log. **The estimator
  stays above the seam**, so a Docker offset and a native offset are the same
  kind of number.
- **An offset is never recorded without its bound, and the validator asks for a
  bound rather than a threshold.** Measured: one exchange has a tail (+26.9 ms
  offset, 57 ms round trip, on hosts whose true offset is zero), three keeping
  the least delayed collapse it to +2.1..+3.2 ms; five buy 0.07 ms. The residual
  +2.3 ms is the exchange's own asymmetry and sits inside round_trip/2. The same
  estimator over `docker exec` is **six times less precise** (+19.7 ms against a
  25.7 ms bound) and both are correct - which is why a threshold that passed on
  ssh would fail on Docker.
- **The argv is part of the contract and was chosen on measurement.** `python3`
  reporting wall and monotonic, not `date` plus `/proc/uptime`: the cheaper arm
  saves 3.5 ms of bound and gives back 10 ms of quantisation on the very value it
  exists to supply (`684.44` against `684.4572976`), and `time.monotonic()` is
  the clock §11.1's sampler stamps with.
- **Journals are pulled once, not at every stage boundary.** The file is
  append-only and cumulative across the run's restarts, so repeated pulls would
  re-transfer the same prefix and leave partial copies to reconcile - the
  spooling the roadmap forbids in the same sentence that asks for the pull. Per
  node, not per host: a directory pull brings `dump.rdb` and `nodes.conf` too.
- **A defect on the acceptance's own line, found at HEAD.**
  `NativeLoadLaneHost.collect_evidence` let `TransportError` out where its Docker
  sibling has always raised `CollectionError`, and `is_collection_failure`
  answers False for anything it cannot place - correctly, since a transport
  failure on a fault path is not a collector's failure. So a native evidence
  transfer that failed reported **`FAIL`**, the claim that the cluster was
  observed and found wanting. Fixed at the two sites that know the file was
  necessary evidence, not by widening the classifier.
- **The simulated-fleet question is answered: a run records which fleet it ran
  on and cannot record what that fleet was.** The manifest is forbidden from
  carrying such a flag and the harness keeps its nature in a sidecar the product
  never reads, so `fleet_id` plus the manifest digest makes it answerable in one
  deterministic hop - by the only thing that knows. Item 1.5 still owes declaring
  it when it freezes a baseline from a simulated run.

- **Proven:** `repository.all` **92/92**; 780 pytest checks, 34 of them this
  item's. An induced transfer failure yields **ERROR** twice, staged from outside
  the product by a `docker` shim on `PATH` - the clock arm 13 s in, the journal
  arm 696 s in on a run that had already finished both matrices - each with
  `Status: ERROR`, `summary.json` ERROR, **exit code 0**, `run_verdict` naming
  `runtime_start` ERROR, and zero residue. Two real exact-50, **PASS 868.18s**
  and **PASS 864.61s**, 12/12 both, zero residue, no `ERROR` in any artifact,
  and identical marks: `runtime_start` 7/7, `cluster_form` 5/5, `cleanup` 2/2,
  `management_matrix` 6/8, `fault_matrix` 5/6, both inherited deltas at their
  declared shapes and no third, fault lane 9/12/15, RTO 46.086s and 49.101s.
  50 of 50 journals in both runs, ~155 KB per node, 2.86 s of collection in an
  868 s run.

**Two claims in this file were stale and are corrected above rather than
re-done.** `evidence/validation.py:41` was fixed at `eb4924db` on 2026-08-09 -
`validate_raw_sources_by_kind` already splits the two §12.1 kinds and
`run_exact_gate` already applies §12.2's precedence to them. And node-log
collection is no longer an open finding.

**What item 1.3 did not prove:** no journal has been fetched off a host over ssh
*through the product*. The native `HostEvidence` is hermetic and its Docker
sibling is real; the ssh path from `start_nodehost` to a collected journal has
not run end to end. That belongs to item 1.5's bring-up smoke, which is now the
natural place to drive `host_evidence`'s two verbs alongside the three argv the
native backend map §11 already names.

**What M3-A-4 inherited, verified at that HEAD rather than remembered.** *(All
four are now closed or dispositioned; see the M3-A-4 section below for what each
turned into. Kept because the derivation reads from them.)* Item 1.4
owns "no managed process or host resource behind", and the roadmap names three
kinds of ownership mark - processes, state dirs, and *any network rules the
actuator creates*. Four facts were checked while handing over, and each is an
observation for that item to derive from rather than a decision taken for it:

1. **`release_run` terminates by the pids in `state.json`, and by cleanup time
   none of them is alive.** Measured on both frozen exact-50 baselines: 12-13
   live `valkey-server` per nodehost, **zero overlap** with state's pids, because
   state is last written before the management matrix and the rolling restart
   plus the fault matrix replace every process. Under Docker `docker rm -f` is
   the backstop that actually stops the fleet; **the native backend has none**,
   which is why its residue scan measures rather than asserts. This is the
   finding the operator carried here on 2026-08-10.
2. **Pre-run reclaim and end-of-run release disagree about where the truth is.**
   `reclaim_run` kills by reading each `*/valkey.pid` **on the host**, which is
   current; `release_run` kills by `state.json`, which is not. Two cleanup paths
   in one backend with different notions of what is running.
3. **No cleanup path touches iptables.** `isolate_nodehost` creates a chain
   `VSLAB-<NODEHOST-ID>` and inserts `INPUT`/`OUTPUT` jumps; only
   `rejoin_nodehost` removes it. A run that aborts while a host is isolated
   leaves kernel-level state behind, and neither `reclaim_run` nor `release_run`
   scans for it or removes it. This is verbatim the roadmap's "the residue check
   covers rule-level state".
4. **Two host resources are outside every ownership mark.**
   `RESOURCE_AGENT_ROOT` is `/tmp/vslab-resource-agent` - not run-scoped, holding
   a copy of the whole `valkey_scale_lab` package and a directory per sampler -
   and `_release_remove_state` removes only the run root and the bundle dir. And
   **`HostTransport.close()` has no caller anywhere in the product**, so a native
   run leaves its ssh masters running under `ControlPersist=600`; the transport's
   own docstring already calls that "a resource the run owns and did not
   release".

**Reported, not fixed** (slice map §10): the resource-to-timeline correlation
§11.4 requires compares two unrelated monotonic clocks. `_event_overlaps` tests a
controller-stamped event's monotonic against a host-stamped sample interval, and
a monotonic clock is a per-boot counter with an arbitrary origin. Measured in one
baseline run: samples 1847.93-1967.98, events 478.70-~600. They cannot overlap,
so that run's `network_error_or_drop_overlap_count: 0` does not mean no overlap
was observed - it means none is expressible. Fixing it changes a diff-view
surface and needs the offsets this item introduces, so it is its own change with
its own evidence, and it is **not** item 1.4's or 1.5's.

### Session M3-A-4 is done: roadmap item 1.4, distributed cleanup

The seam is still **twenty-four operations** - this item needed no
twenty-fifth - and `repository.all` is still **92**, because its twelve new
checks joined a module the catalog already registers. Read
`project/docs/distributed_cleanup_slice_map.md`; §1 is what a native run
actually leaves on a host, §2 the ownership mark derived from it, §8 what was
reported rather than fixed.

- **The defect nobody handed over, and reading could not have found it: the
  residue scan could not see a running node.** It matched
  `ps -eo args= | grep -F "$root"`, and Valkey rewrites its process title - a
  live node's argv is `valkey-server 0.0.0.0:31000 [cluster]` and the config
  path is gone. Measured with two of the run's nodes live: **one row, for the
  directory, and none for them.** The operation whose docstring says it measures
  rather than asserts was asserting, which is the very defect item 0.5 existed
  to prevent, in the operation item 0.5 created.
- **The mark for a process is its working directory.** The config sets
  `dir <data_dir>` and Valkey chdirs there, so `/proc/<pid>/cwd` still names the
  run root after a restart and after the proctitle rewrite. Compared with a
  trailing separator on both sides, because without one `run-alpha` claimed
  `run-alpha-2`'s node - measured. `/proc/<pid>/exe` is recorded and never used
  to filter: filtering would drop exactly the process a reader most needs to
  hear about, something unexpected running out of the run's own tree.
- **The pidfile is not the answer either**, which the handover's item 2 had not
  established. Measured: a SIGKILLed node leaves a pidfile holding a **dead
  pid**, so killing by it risks an unrelated process; a cleanly stopped node
  removes its own. Neither necessary nor sufficient. So `reclaim_run` and
  `release_run` now share one enumeration and neither uses a pid it was told
  about - what state believed survives only as `state_pid_count` beside
  `pid_count`, because the gap between them is the evidence.
- **A firewall rule cannot carry the run in its chain name.** Measured:
  `iptables` accepts a 28-character chain name and refuses 29; a run id is 42.
  The same shape of constraint as M3-A-2's 104-byte `ControlPath`. So the chain
  keeps its readable nodehost-derived name as a *handle*, and the two jumps
  carry `vslab-run=<run_id>` in a **comment**, which holds 256 and which
  `iptables -S` prints. Both cleanup paths find and remove rules by it; the
  residue scan asks for rules still carrying the mark *and* for chains this run
  created, because a chain outlives its mark once its jumps are gone.
- **Teardown sends CONT before TERM.** A process the actuator suspended cannot
  act on TERM, so an abort with a nodehost paused would sit out the whole
  termination wait and be killed at the end of it.
- **The resource agent moved under the run root**, package copy and all: its old
  root was named by `sampler_id`, which is the `nodehost_id` and names no run.
  The root was this backend's own constant and no part of the seam, so moving it
  was the backend's to make. **The Load Lane's remote directory did not move**
  and is the item's one open residue: `LoadLaneHost`'s protocol says in as many
  words that `remote_dir` is the lane's choice, and `_output_prefix` has already
  written it into memtier's argv. Slice map §8.4 carries both candidate fixes and
  why each is item 1.5's rather than this one's. **Closed in item 1.5**: the
  root is run-scoped and the lane removes what it created; the argv change was
  measured to move no diff view. An aborted run still leaves it, now under a
  path that says whose it is.
- **`HostTransport.close()` has its first caller.** `release_run` closes a
  transport this backend opened for itself - never one it was handed, which
  belongs to whoever handed it over. `reclaim_run` deliberately does not: on a
  run's own path it runs before `create_network` and the run keeps using that
  transport.

- **Proven:** `repository.all` **92/92**, 788 pytest checks, vocabulary contract
  clean. On the two-host simulated fleet, with residue placed by the backend's
  own operations - `start_nodehost` installing the pinned bundle, real
  `valkey-server` processes under the lifecycle's config shape, and
  `isolate_nodehost` installing the rules itself - **fifteen pieces of residue,
  and managed residue 13 → 0 twice**: once through `release_run`, once through
  `reclaim_run` after the controller was **SIGKILLed** mid-flight while a host
  was isolated. Open control channels 2 → 0 on the passing path. Re-run it with
  `python3 scripts/native_cleanup_proof.py release|abort --fleet-id sim-a`.

**What item 1.4 did not close, and it is the honest boundary:** an *aborted*
controller's ssh masters. They survive `SIGKILL` (they are daemonised, not
children), leave one `sshd-session` per host, and cannot be reclaimed by anything
that runs afterwards - nothing on a host says which run a session belongs to and
nothing on the controller says which `mkdtemp`-named socket directory does, so
claiming them would mean closing another run's channel. Bounded by
`ControlPersist=600`. Slice map §8.2 records the candidate fix and why it is its
own change.

**Deliberately not done, and named so a later session does not adopt them:** the
fault actuator still suspends and resumes by pidfile (slice map §8.3 - narrower
there, because a pidfile *is* current for a node that is running, and changing it
is a fault-lane change belonging to the item whose ladder exercises the fault
lane) - **item 1.5 measured that argument false and changed it**: with a kill
placed before the pause, 2 pidfiles against 1 live process, so the actuator
attempted a signal to a pid it no longer owned; and no fault path checks
ownership, which stays the accepted absence below
- the run mark on the actuator's rules records *whose* a rule is and does not
make `isolate_nodehost` refuse a host that is not this run's.

**What M3-A-5 inherits, verified at this HEAD rather than remembered.** *(Read
the M3-A-5 section below before acting on any of the seven. Two are now known
wrong — item 2's fleet arithmetic is out by a factor of two at exact-30 and
exact-50, and item 4's cleanup row count with it — and items 3, 5 and 6 are
closed. Kept because the derivation reads from them.)* Item 1.5
is the simulated ladder, with the operator's bring-up smoke at its front
(2026-08-11): two simulated hosts, the backend driven directly - claim, install,
start, stop, isolate, rejoin, release - no Gate run, no cluster, no scenario.
Seven facts were checked while handing over.

1. **Five seam operations have now run against a real host through the product,
   and the smoke does not need to re-prove them.** `scripts/native_cleanup_proof.py`
   drives `verify_image`, `reclaim_run`, `start_nodehost` (which is claim *and*
   bundle install), `isolate_nodehost` and `release_run` on live simulated hosts.
   **What is still unexercised on a host is the rest**, and it is the smoke's
   list: `send_bundle`, `install_bundle`, `start_node_processes`, `start_node`,
   `stop_node`, `kill_node`, `wait_nodes_ready`, `collect_node_pids`,
   `run_cluster_admin`, `client_host`, `pause_*`/`resume_*`,
   `rejoin_nodehost` *on the success path* (item 1.4 reaches it only from
   `isolate`'s failure branch), `resource_sampler`, `load_lane_host`, and
   `host_evidence`'s two verbs.
2. **The fleet arithmetic, so a run is not planned against a fleet that cannot
   hold it.** `max_logical_nodes_per_nodehost` defaults to **25** and a native
   run places exactly one nodehost per host, so: exact-30 and exact-50 need
   **2 hosts**, and **exact-200 needs 8**. The harness publishes **60 client
   ports per host** by default, which covers 25, and publishes **no cluster-bus
   ports** - correctly, because peers reach each other on the fleet network by
   `data_address` and only the controller uses the published range.
3. **No native run configuration exists anywhere in the repository.** Nothing
   under `templates/configs/` names `ecs` or `host_inventory_path`. Item 1.2
   admitted `runtime.provider: ecs` with two required fields
   (`host_inventory_path`, `native_bundle_dir`); writing the first configuration
   that uses them is item 1.5's, and it is the first thing the smoke needs.
4. **The `cleanup` equivalence delta, measured on both sides rather than
   predicted.** The frozen Docker exact-50 baseline emits **21 `cleanup_actions`
   rows in six kinds** - `terminate` ×4, `verify_exit` ×4,
   `verify_no_valkey_processes` ×4, `container stop` ×4, `container remove` ×4,
   `network remove` ×1. The native backend emits **five rows per nodehost in four
   kinds** - `terminate`, `verify_exit`, `remove` (firewall), `remove` (run
   state), `scan` - so **ten rows at exact-50**. `cleanup_timing` also differs:
   both carry the six second-valued keys `teardown.py` fills, and native adds
   `cleanup_remove_firewall_rules_seconds` and
   `cleanup_remove_run_state_seconds`. This is a *vocabulary* delta of the kind
   item 1.5 is required to declare in advance, not drift.
5. **The first native full-flow run will leave residue, and it is known which.**
   `/tmp/vslab-load-lane/<label>/` - see the M3-A-4 section and slice map §8.4.
   Item 1.4's residue scan deliberately does not report it, because nothing on
   the host attributes it to a run. Item 1.5 is where the Load Lane first runs
   natively and so where the decision lands.
6. **`host_evidence`'s ssh path is still unproven end to end**, carried
   unchanged from item 1.3: no journal has been fetched off a host over ssh
   *through the product*. The smoke is the natural place, alongside the argv
   `native_backend_slice_map.md` §11 names.
7. **The abort proof is reusable rather than one-off.**
   `python3 scripts/native_cleanup_proof.py release|abort|stubborn --fleet-id sim-a`
   places real residue and checks the hosts over its own ssh. M3-B's real-host
   reclaim proof is the same harness against a real manifest.

### Session M3-A-5: roadmap item 1.5's smoke and first rung

**Item 1.5 was two sessions and this was the first; M3-A-6 finished it - read
that section below before acting on anything here, because rung 2 corrected two
of this one's claims.** Read
`project/docs/simulated_ladder_slice_map.md`; §1 is the harness defect that
blocked every rung, §6 the equivalence deltas declared in advance, §7 the two
decision points, §11 the smoke, §12 rung 1 and the four defects it found.
M3-A-6's scope is rung 2 (native exact-50 ×2 and the equivalence diff) and
rung 3 (native exact-200 on eight hosts).

- **Two inherited numbers were wrong and are corrected.** `nodehosts_per_az` is
  **2** in the global config and `requested_for_az = max(nodehosts_per_az,
  ceil(n/25))`, so density is not the binding term at small scale:
  **exact-30 and exact-50 plan four nodehosts and need four hosts**, not two;
  exact-200 needs eight. The frozen Docker baseline's 21 cleanup rows say the
  same thing. The handover's "ten cleanup rows at exact-50" is therefore
  **twenty**, which is what both native runs emitted.
- **The harness could not serve any native run**, measured on a live fleet.
  Client ports are assigned globally *before* nodehosts exist and nodes are then
  strided across nodehosts, so each nodehost's ports span the whole run window
  and no contiguous per-host block can cover them. Docker never met this because
  a nodehost container is created *after* the plan. Fixed in the harness: each
  host has its **own client address** (`127.0.0.2` upward, never `127.0.0.1`,
  which a Docker gate run uses) and **all hosts declare one shared range** - a
  real fleet's shape. The addresses are loopback aliases the operator creates
  once per boot (`sudo ifconfig lo0 alias 127.0.0.N up`); the harness checks and
  refuses with the command rather than calling `sudo`. **Eight hosts need
  `127.0.0.9`, which does not exist yet.**
- **Four defects that only a real run could find**, three of them from rung 1's
  three failed attempts. **The backend was never chosen from the
  configuration** - `provider: ecs` validated, manifest read, placement correct,
  and then four Docker containers started for four named fleet hosts; the
  configuration now decides, and a `--backend` contradicting it is refused both
  ways. **`ResourceSampler` under-declared its contract** - the observation layer
  also reads `.sampler`, which only the Docker agent had, so the native agent
  satisfied the protocol as written and died 340 s in. **`state.json` could not
  say where a nodehost was**, so cleanup could not reach a fleet host - and that
  was the serialiser, not the failure path, so a *passing* run would have failed
  its cleanup identically. Plus the resource preflight correctly refusing a
  leftover network from the killed first attempt.
- **§7.2 decided on measurement, which reversed item 1.4's reasoning.** The
  actuator paused by pidfile on the argument that a pidfile is current for a
  running node. Measured on hosts with a kill placed first: **2 pidfiles, 1 live
  process**, so it attempted a signal to a pid it no longer owned. It now uses
  the same `/proc`-by-working-directory walk both cleanup paths use. Native
  only; no frozen baseline moves. **A run's artifacts cannot answer this** - the
  fault record keeps the action string, not the `signalled` count.
- **§7.1 decided and cheaper than 1.4 §8.4 predicted.** The Load Lane's remote
  root is run-scoped and the lane now removes what it created (leaf with
  `rm -rf`, run-scoped parent with `rmdir`, so the last label to finish takes
  it). Measured against the frozen baseline first: memtier's argv is in **no
  diffed view and no reported line**, so it moves nothing - confirmed by two
  real Docker exact-50.
- **Proven.** `repository.all` **92/92** throughout; the pytest tree **798**, up
  from 788. The bring-up smoke **32/32** on two hosts - every seam operation has
  now run against a live host through the product, which closes item 1.3's
  "no journal fetched off a host over ssh through the product". Two Docker
  exact-50, **PASS 905.93s and 908.01s**, both 7/7, 5/5, 6/8, 5/6, 2/2 with both
  inherited deltas at their declared shapes and no third, fault lane 9/12/15,
  RTO 49.07s and 48.10s. Two native exact-30, **PASS 737.29s and 729.05s**,
  12/12 both, fault lane **9/12/15** identical to Docker, cleanup 20 rows in
  four kinds exactly as declared in advance, **zero residue on all four hosts**,
  no `ERROR` in any artifact, RTO 47.26s and 46.45s.

**What M3-A-6 inherits, verified at this HEAD rather than remembered.** Two of
the seven facts the *previous* handover carried were wrong, so each of these was
re-checked by compiling or running it at `69ad92a2`, not by recalling it.

1. **The rung arithmetic, compiled at HEAD.** Each configuration resolves
   `provider: ecs` to `native_multi_ecs` and plans:

   | configuration | nodes | nodehosts | **hosts** | client ports | fleet command |
   |---|---|---|---|---|---|
   | `native_30` | 30 | 4 | **4** | 31000-31029 | `--hosts 4 --client-ports 60` |
   | `native_50` | 50 | 4 | **4** | 31000-31049 | `--hosts 4 --client-ports 60` |
   | `native_200` | 200 | 8 | **8** | 31000-31199 | `--hosts 8 --client-ports 200` |

   All three name fleet `sim-l5`:
   `python3 scripts/simulated_hosts.py up --fleet-id sim-l5 --hosts N --client-ports P`.
2. **`native_200.yaml` carries `profile_name: scale_200`, deliberately, and it
   must keep it.** `_is_exact_200_bounded_exception` is the safety guard that
   admits a real run above the default cap of 100, and it keys on that exact
   name plus `runtime.dry_run: false`. Measured: with `native_200` as the name
   the planner refuses - `node count exceeds default cap without 1000 opt-in` -
   and rung 3 would have discovered it after bringing eight hosts up. The name
   is the *scale* profile and the runtime is named by `runtime.provider`, so
   this is the same profile on a different runtime; widening the guard instead
   would be a change to a safety contract and is the operator's call, not a
   session's.
3. **The eighth host needs one more loopback alias**, `127.0.0.9`
   (`sudo ifconfig lo0 alias 127.0.0.9 up`). Hosts map to `127.0.0.<index+2>`,
   so eight need `.2`-`.9` and only `.2`-`.8` exist. Aliases do not survive a
   reboot; the harness checks and refuses with the command rather than failing
   obscurely. Publishing 200 ports on each of 8 hosts was measured at 41 s to
   start and slow to tear down - a per-fleet cost, paid once.
4. **The equivalence diff's baseline and its calibration.**
   `artifacts/baselines/exact-50-6b6f57fd/`, artifact root
   `<run>/001-real.local.full-flow/runtime` - the run directory alone gives
   "6 unavailable" and is the wrong path. Calibrated baseline-to-baseline at
   this HEAD: **7/7, 5/5, 8/8, 6/6, 2/2**.
5. **The deltas are declared in slice map §6 and must not grow.** The two
   inherited Docker ones (`management_matrix` 6/8 at +14 rows with
   `cluster_migrate_keys` 4 → 18, three kinds changed and fourteen unchanged;
   `fault_matrix` 5/6 at reachable ×3, reason ×3, one `true→false`) are pinned
   by two real Docker exact-50 this session. The native ones are §6.3's, and
   **`cleanup` is already confirmed on a real native run** - 20 rows in four
   kinds, no network row, two extra timing keys. §6.3 predicts *no* vocabulary
   delta in `cluster_form`, `management_matrix` or `fault_matrix` beyond the
   inherited pair; that is the prediction rung 2 tests and the one most likely
   to be wrong.
6. **Rung 1 is not an equivalence result.** No frozen 30-node baseline exists.
   Its value is that the lifecycle runs natively at all, plus the fault lane's
   9/12/15 holding across a change of runtime.
7. **Do not freeze native baselines.** The roadmap is explicit that they come
   from the real fleet in M3-B, because a baseline should encode the environment
   acceptance runs in.

Still open and **not** M3-A-6's: the aborted controller's ssh masters (1.4 map
§8.2), the resource-to-timeline monotonic correlation (1.3 map §10.1), a failing
run collecting no journals and writing no lifecycle timeline (1.3 map §10.2),
`_check_ports_free`'s loopback bind (M3-B's), and the absent fault-path
ownership check (accepted 2026-08-10). Two smaller ones this session added:
a run's artifacts record the pause *action string* but not the `signalled`
count, so no run can answer slice map §7.2 from its own evidence; and
`SamplerSpec` in `node_backend.py` duplicates the Docker backend's private
`_AgentSamplerSpec`, whose collapse is a change on a real Docker run's path.

### Session M3-A-6 is done, and with it roadmap item 1.5

Rungs 2 and 3. Read `project/docs/simulated_ladder_slice_map.md` §14 (rung 2, the
delta measured to the field, and the four rows §6 did not declare), §15 (rung 3,
transport and evidence volume at fleet width, and the dwell datum), and §15.5,
which falsifies a claim §14.6 made - the rung's own correction of the rung before
it.

**The item's hard stop is met.** Two consecutive native exact-50, **PASS 832.32s
and 871.47s**, and a native exact-200, **PASS 1544.44s on the first attempt**,
all 12/12 steps with `run_verdict` 12/12 OK, equivalence-diffed against the
frozen Docker baselines with every delta accounted for. Fault lane **9 / 12 / 15**
at both scales with all nine `REAL_PASS` - the three scale-fixed numbers now hold
across two runtimes and three scales. Zero residue on four and then eight hosts,
checked from outside the product over ssh as well as in `cleanup_report`. No
`ERROR` in any artifact of any run. `repository.all` **92/92** throughout; the
pytest tree **802**, measured at this HEAD, of which two are this item's - the
**798** the section above records does not reproduce here and was not
re-derived, so prefer the measured number.

- **The equivalence result.** Calibrated 7/7, 5/5, 8/8, 6/6, 2/2 first. Both
  accepted native exact-50 runs score **`runtime_start` 5/7, `cluster_form` 5/5,
  `management_matrix` 6/8, `fault_matrix` 4/6, `cleanup` 1/2** and are identical
  to each other in every view and every field. Both inherited Docker deltas are
  at their declared shapes - +14 rows all `cluster_migrate_keys` 4 → 18 with
  three kinds changed and fourteen unchanged, and the three partition scenarios'
  isolated side - and there is no third.
- **§6.3's central prediction is false, and it is the honest headline.** It said
  the views "compare `command_kind`, not argv". They compare the whole row, so
  **`argv` is the entire difference in `fault_command_log`** - 17 rows, and
  nothing else at all - and 212 of 1592 rows in `management_command_log`, with
  the other 1380 identical. `fault_sequence.details.actions[]` ×14 and
  `proxy_snapshot.target_host` ×3 are the same class. **Declare it, do not
  normalise it**: two backends cannot issue the same argv by construction, and a
  view that collapsed argv would stop seeing the wrong command being run.
- **A defect the artifacts could not report, found by asking the hosts.** A
  PASSing native run left `/tmp/vslab-bundle-<run_id>-<nodehost_id>/` on every
  host - 84-88 KB - under a `cleanup_report` saying `found: 0`. Two halves:
  `_release_remove_state` read `remote_bundle_dir` from `state.json` and
  `_state_nodehost` drops it (rung 1 §12.3's shape in the sibling field), and
  `_scan_run_residue` never asked about bundles, so `found: 0` was truthful
  about what it scanned and silent about the rest. The path is derived from the
  run id now - `reclaim_run`'s own expression - so the two cleanup paths agree
  and neither depends on being told. Native only; no frozen baseline moves.
- **One delta was this map's own arithmetic and is gone rather than declared.**
  `native_50.yaml` said `port_base: 31000` where `scale_50.yaml` says 7400, while
  its header claimed to be identical to it - which alone differed in
  `nodehost_density_plan.ports`, `state`'s two port fields and **all 50
  `node_configs`**. The harness publishes whatever range it is told. Aligned:
  `node_configs` SAME at exact-50 (50 of 50) **and at exact-200 (200 of 200)**.
  `native_30` is deliberately left at 31000, because rung 1's runs were taken
  with it and no 30-node baseline exists.
- **The delta does not grow with fleet width.** Against the frozen exact-200
  baseline (which covers two stages, both its runs failing downstream),
  `cluster_form` is **4/4 identical** and `runtime_start` differs in the same two
  views and the same fields as at exact-50, scaled 4 → 8 nodehosts and 50 → 200
  nodes. **No field appears at 200 that did not appear at 50.**
- **Transport at fleet width, which the roadmap left open.** From the two runs'
  own command audits, native exact-200 against Docker exact-200: the backend's
  own `runtime_command` rows cost **25.7 s across eight hosts against `docker
  exec`'s 276.6 s on one**, in 3037 rows against 4853, medians within a
  millisecond and p90 12 ms against 105 ms. **Lower bounds** - these hosts share
  a kernel - but nothing about eight hosts broke M3-A-2's choice, and M3-B still
  owns the real-network number.
- **Evidence volume is not linear in node count.** 200 of 200 journals,
  **86.8 MB**, against 7.9 MB for 50 - 4× the nodes, 11× the bytes, 158 KB per
  node at exact-50 against 434 KB at exact-200, because a node's log is
  dominated by gossip about peers. The whole run's artifacts grew 37.3 MB →
  192.6 MB. Journal volume is a property of the cluster and not the runtime:
  7.9 MB native against 8.0 MB Docker for the same 50 nodes.
- **The dwell datum, recorded and not argued from.** Native `cluster_form` at 200
  is **60.9 s**, against four passing Docker exact-200 at 59.4-104.9 s and the
  five formation-only runs at 83.1-205.8 s; at exact-50, native 19.7-52.1 s
  against Docker 43.0-122.6 s. Native sits at the low end of the Docker spread
  and inside it at both scales - not a different regime, and a quarter of the
  240 s window. This **supports** §7.3's deferral rather than merely leaving it:
  a simulated dwell is a lower bound and it measured near one. Only M3-B's real
  network can narrow the bound.

**What rung 3 corrected about rung 2, and what one further run then settled.**
§14.6 reported that the rolling restart's health gate escalates to a whole-fleet
diagnostic round on every native run and on no Docker run - 0 in each of six
Docker exact-50, against 6, 4, 3 and 5 of 44 gates natively. At exact-200 the
native run escalated **zero times in 80 gates**, and so did four Docker
exact-200; `native_200.yaml` inherits `scale_200`'s far lighter workload (50 qps
and pipeline 1 against 800 and 8), so rung 3 alone could not say whether the
cause was the runtime or the load.

**The operator authorised one targeted run and it settles it: the runtime.**
Native exact-50 with `scale_200`'s workload block substituted and nothing else
changed - `uniform_qps` 800 → 50, `hotspot_qps` 150 → 10, `pipeline` 8 → 1 -
**PASS 893.60s, 12/12, fault lane 9/12/15, RTO 47.57s, zero residue, no `ERROR`,
and 5 escalations of 44 gates**, squarely inside the heavy-workload range of 6,
4, 3 and 5. Sixteen times less offered load changed nothing. Read slice map §16.
**Not a rung, not a gate, not an acceptance criterion; no correctness failure, so
M3-A stays closed**, and the configuration was written outside version control on
purpose - the result is recorded and the file is not.

So §14.6 is reinstated as an explanation at exact-30 and exact-50, and §15.5
survives only in the narrower form it was entitled to: "and never on Docker"
cannot be extended to exact-200, where neither runtime escalates. **The open
variable is now scale, and it moves the wrong way** - four times the nodes and
the escalation disappears, where more nodes should mean more chances for a
representative round to find something unhealthy. What co-varies with scale to
invert it is written down as a question in slice map §16.2 and deliberately not
pursued: the verdict is unaffected in every run - `status`, `cluster_state`,
`known_nodes` and `slots_assigned` are all compared and all identical - and it is
a later item's to take up, if any.

**Two fields the frozen baselines agree on by coincidence**, reported rather than
excluded because their views already differ for declared reasons: the
health-gate retry record inside `stdout_tail` (`PROBE_COUNT_FIELDS` excludes
those names but the exclusion does not descend into a serialised summary, and
`sample_scope` is not in the set at all), and
`management_sequence...errors_observed_during_operation`, which both baselines
record as `T,T` and the four native runs record as `F,F`, `T,F`, `T,F`, `F,F`.
That is the third and fourth instance of CLAUDE.md's warning that two runs
agreeing is not proof a field is deterministic.

**One number outside its prior spread**: primary-kill RTO at exact-200 was
**41.28 s**, where every prior exact-200 measurement is 47.6-53.8 s and the
exact-50 band is 45-50 s. Recorded, not treated as a finding - a faster recovery
is not a failure and the rule fires on a shifted spread, not one run. A second
native exact-200 below 45 s would make it one.

**What M3-A-6 leaves.** Item 1.5 is closed; **M3-A-7 is roadmap item 1.6 or 1.7,
on operator approval, and the correct state now is idle.** Do not freeze native
baselines - they come from the real fleet in M3-B, because a baseline should
encode the environment acceptance runs in. Three things this session added to the
open list, none of them its own to close: why the health-gate escalation inverts
with scale (slice map §16.2 - the workload half of that question is answered);
`_state_nodehost` still drops `remote_bundle_dir`, which nothing needs now that
the path is derived; and the diff tool compares a health gate's retry record
through `stdout_tail` while excluding the same fields structurally.

**Operator decision, 2026-08-11: the equivalence diff keeps raw `argv`.** A
cross-backend command-log delta confined to `argv` is an expected runtime
difference and is read as one; it is not normalised away, because a view that
collapsed `argv` would keep scoring green while the wrong command ran. The
distinction lives in `scripts/diff_stage_artifacts.py`'s own docstring, so it
reaches whoever runs the tool, and slice map §14.5 carries the measurement.

Carried forward untouched: the aborted controller's ssh masters (1.4 map §8.2),
the resource-to-timeline monotonic correlation (1.3 map §10.1), a failing run
collecting no journals and writing no lifecycle timeline (1.3 map §10.2),
the absent fault-path ownership
check (accepted 2026-08-10), the missing `signalled` count in a run's own
evidence, and `SamplerSpec`'s duplication of `_AgentSamplerSpec`.
`_check_ports_free`'s loopback bind is **off this list**: resolved at HEAD, the
native backend declares `publishes_node_ports_on_controller=False` and the bind
never runs there - see the M3-B handover's item 5.

**Fleet commands, compiled at this HEAD.**

| configuration | nodes | nodehosts | hosts | client ports | fleet command |
|---|---|---|---|---|---|
| `native_30` | 30 | 4 | 4 | 31000-31029 | `--hosts 4 --client-port-base 31000 --client-ports 60` |
| `native_50` | 50 | 4 | 4 | 7400-7449 | `--hosts 4 --client-port-base 7400 --client-ports 60` |
| `native_200` | 200 | 8 | 8 | 7800-7999 | `--hosts 8 --client-port-base 7800 --client-ports 200` |

Eight hosts need loopback aliases `127.0.0.2`-`127.0.0.9`, which do not survive a
reboot; the harness checks and refuses with the command. Bringing eight hosts up
with 200 published ports each took 41.4 s, a per-fleet cost paid once.

### What M3-B-1 inherits, verified at this HEAD rather than remembered

M3-A is closed. **M3-B begins only on operator approval and additionally requires
roadmap item 0.7** - the operator-confirmed real fleet. Every fact below was
compiled, resolved or run at `94f08f33`; two of the seven M3-A-5 was handed were
wrong, so apply the same rule to these.

**The scope, from roadmap revision 5.1 rather than from memory.** *Item 1.6* -
the same ladder on the operator's fleet: re-measure transport per-operation
overhead (this closes the transport decision point for real, because simulated
numbers are lower bounds), record real clock offsets, verify auth/kernel/
conntrack reality, then native exact-50 ×2 and exact-200 through the Gate;
repeat the ownership/reclaim proof on real hosts - abort a run mid-flight,
reclaim, zero managed process/state/network-rule residue; **freeze the native
baselines from *these* runs, not the simulated ones**; record formation-dwell
statistics and re-argue the 240s window if they move. *Item 1.7* - register
`real.ecs.*` gate tests in json-result form like their local siblings, attach
executable checks to all six M3 criteria (the milestone's own no-placeholder
rule), and `./gate milestone m3` green on the merged default branch.

1. **The fleet the product will actually demand, compiled at HEAD - and it
   disagrees with roadmap item 0.7.** 0.7 sizes the fleet as "200 processes over
   a few small-spec instances is 50-70 per host". The product will not do that at
   its shipped defaults. A native run places **exactly one nodehost per host and
   refuses otherwise**, `nodehosts_per_az: 2` over two AZs is a floor of four,
   and `max_logical_nodes_per_nodehost` is 25. Compiled against `native_200.yaml`:

   | `max_logical_nodes_per_nodehost` | nodehosts | **hosts** | processes per host |
   |---|---|---|---|
   | **25 (shipped default)** | 8 | **8** | 25 |
   | 34 | 6 | 6 | 33-34 |
   | 50 | 4 | **4** | 50 |
   | 100 | 4 | 4 | 50 - the AZ floor binds, not the density |

   So **exact-200 needs eight hosts as configured today, and four is the floor at
   any density**; exact-50 needs **four**, not the roadmap's "≥2". Reaching 50 per
   host means raising the density knob, and that is not free: it moves
   `nodehost_density_plan`, every node's `nodehost_id`, the fault matrix's targets
   and the cleanup row count, so the real baselines 1.6 freezes would differ
   *structurally* from every simulated run they are meant to be comparable with.
   **This is an operator decision before provisioning, and by the roadmap's own
   deviation rule it should be reported rather than improvised around.**

2. **What a real manifest must contain**, from `runtime/host_inventory.py`, the
   only module that knows the field names. Per host: `host_id`,
   `availability_zone`, `data_address`, `control_endpoint` (`address`, `port`,
   `user`, `private_key_path`, `known_hosts_path`) and `client_endpoint`
   (`address` plus `port_range.first`/`.last`). On a real fleet `data_address` and
   `client_endpoint.address` usually **coincide** and the manifest carries the
   same address twice - the field set does not change, which is the property that
   made the harness worth having. The manifest must carry no container, image or
   network vocabulary and **no flag saying the fleet is real or simulated**;
   `host_inventory.py` must never grow such a branch, because a backend that could
   tell would make every simulated result a fact about the harness.

3. **How a run is pointed at a fleet, and what does not exist.**
   `runtime.host_inventory_path` and `runtime.native_bundle_dir`, both required
   for `provider: ecs` by `config/validation.py`. All three `native_*.yaml`
   hardcode `artifacts/host-fleets/sim-l5/inventory.json`, and **there is no CLI
   override** - `--param config=` is the only lever. M3-B therefore needs its own
   configurations, and they are what 1.7's `real.ecs.*` entries will name.

4. **The two proof harnesses are fleet-id-shaped, not manifest-path-shaped.**
   `native_cleanup_proof.py` and `native_bringup_smoke.py` both resolve
   `artifacts/host-fleets/<fleet-id>/inventory.json`. Dropping the real manifest
   at that path under its own fleet id needs no code change and is the smaller
   move; giving them an `--inventory` argument is the other. Not pre-decided.

5. **`_check_ports_free`'s loopback bind is already handled and is no longer
   M3-B's.** Resolved at HEAD: `native_multi_ecs` carries
   `publishes_node_ports_on_controller=False` against `docker_process` and
   `docker_container`'s `True`, and `_execute_runtime` builds an **empty** port
   list when it is false, so the `127.0.0.1` bind never runs natively. The check
   that matters on a fleet is the placement's - that a host's declared client
   range covers what the run asked for - and that already refuses. Note a passing
   native run cannot prove this either way, since the controller's loopback is
   free at those ports anyway; the evidence is the registry entry and the guard.

6. **The transport is behind one interface, as the decision point requires.**
   `HostTransport` is a Protocol at `runtime/host_transport.py:68` and
   `MultiplexedSshTransport` its only implementation at :114, so switching to an
   on-host agent replaces one class. The budget to measure against is the rolling
   restart's own, from the frozen baseline: **71 ms and 61 ms median** for its two
   backend operations. Simulated numbers, which are lower bounds and must not be
   quoted as fleet numbers: `docker exec` 66.4 ms against multiplexed ssh 10.8 ms
   on the M3-A-2 spike, and inside a real 200-node run, 3037 `runtime_command`
   rows costing **25.7 s across eight hosts** against `docker exec`'s 276.6 s on
   one, p90 12 ms against 105 ms.

7. **Clock offsets are recorded as a bound, not against a threshold**, which is
   what should let them survive real skew. `runtime/host_clock.py` keeps the least
   delayed of several bracketed readings and records `offset_ms`,
   `uncertainty_ms` (= `round_trip_ms / 2`) and `round_trip_ms`; the validator
   asks for a bound because a threshold that passed on ssh would fail on Docker -
   measured, the same estimator over `docker exec` is six times less precise.
   Simulated hosts share a kernel, so true offset is ≈ 0 and the measurements
   were +4.7 to +7.9 ms inside a 15-21 ms bound. **Real skew is 1.6's first real
   test of this**, and it is the one place a bound rather than a threshold is
   expected to pay for itself.

8. **The dwell constants, read at HEAD**: `CONVERGENCE_NO_PROGRESS_SECONDS =
   240.0` and `CONVERGENCE_TIMEOUT_SECONDS = 1800.0`, both at
   `observability/cluster.py:57` and `:61`. The simulated datum 1.6 compares
   against: native `cluster_form` **60.9 s at 200**, inside the four passing
   Docker exact-200 runs' 59.4-104.9 s and a quarter of the window.

9. **M3's milestone coverage, measured**: six criteria, and exactly one carries a
   check - `distributed.inventory-and-placement` → the **suite**
   `product.orchestrator`, which resolves to one test,
   `product.orchestrator.local_orchestrator`. The roadmap calls that the stale
   shim 1.7 supersedes by pointing the criterion at the real inventory contract
   item 1.2 built. **No `real.ecs.*` id exists in the catalog.** M4 is 1 of 7,
   with four registered tests on `scale.definition-and-preflight`.

10. **The counts registering a Test moves**: `repository.all` **92**, catalog
    **96**, M1 plan **91** (the last two pinned by
    `verification/tests/test_contracts.py:79` and `:344`, read rather than run -
    **do not run `./gate milestone m1` to check a count**, it executes the real
    runs), and the pytest tree **802**. 1.7 registers several tests, so it moves
    all of them.

11. **What is simulated-only and must be re-measured, not carried**: every
    transport number above; clock offsets, which are ≈ 0 here by construction;
    transport-failure classification across a VPC, which the roadmap keeps open
    precisely because shared-kernel hosts cannot produce the ambiguity; and
    auth/kernel/conntrack reality. Also the health-gate escalation of slice map
    §16 - it is a native-runtime behaviour at exact-30 and exact-50 that vanishes
    at exact-200, and nobody knows what inverts it.

### Host preparation is done, 2026-08-12. Roadmap item 0.7's fleet exists

**Not roadmap item 1.6 and no product code changed.** The operator's fleet is
provisioned, prepared and verified, so M3-B-1 starts against real hosts rather
than against a provisioning problem. Read
`project/docs/ecs_host_preparation_report.md`; it carries the derivation, every
measurement, the Console runbook and what still cannot be validated.

- **The fleet is eight `c4a-standard-2` GCE hosts, arm64, Ubuntu 26.04 LTS**,
  four in each of two zones of `asia-southeast1`, plus a `c4-standard-4`
  controller in the same subnet. **All eight report `READY`, every required
  check passed, zero advised**, verified with `--bundle` and `--package` so the
  pinned binaries and the resource agent were exercised on each.
- **arm64 was chosen to keep M3-B to one changed variable.** Every M3-A
  measurement and both frozen Docker baselines are arm64, and `architecture` is
  a field in `bundle_manifest.json`, in `verify_native_bundle`'s preflight
  evidence and in the `runtime_start` diff view.
- **The pinned bundle runs unmodified.** On a stock image `valkey-server` and
  `valkey-cli` link and execute with nothing installed - glibc 2.43 against the
  bundle's 2.38 requirement - and only memtier needed the four libevent
  packages. **`CLUSTER MYSLOTS` answers on a host**, which closes
  `verify_native_bundle`'s `not_verified.cluster_myslots_command`: under Docker
  the preflight starts a server and asks it, while a bundle verifier can only
  hash bytes on the controller.
- **A CentOS 8.2.2004 base was tried first and abandoned**, on measurement: glibc
  2.28 could not run the bundle at all, and OpenSSH 8.0p1's sftp-server lacks
  `expand-path@openssh.com`, so `scp -r` from an OpenSSH ≥ 9 controller cannot
  create a remote directory - which is `send_bundle` and the resource agent's
  package copy. Both are absent on Ubuntu 26.04.
- **The manifest user must be root.** `sudo` appears nowhere in `runtime/`, so
  the backend runs every command as the manifest user directly and those commands
  write under `/opt`, install iptables chains and read `/proc/<pid>/cwd` for
  processes they do not own. A sudo account would need the product to prepend
  `sudo`, changing the argv the equivalence diff compares field by field.
- **`google-guest-agent` de-provisions the accounts it manages**, keys and sudo
  together - measured twice, its journal saying `Removing user ...` after the
  console's short-lived metadata keys expired. The fleet key therefore lives in
  a root-owned `AuthorizedKeysFile` the agent does not rewrite, proven by
  emptying `~/.ssh/authorized_keys` completely and logging in again.
- **Delivery is a startup script, not an image.** GCE machine images do not
  support Hyperdisk Balanced, which is the only boot disk C4A takes; and the
  objection to per-host preparation measured zero - two hosts prepared
  independently came out with all six managed files byte-identical and the same
  package set. `scripts/ecs_host_startup_metadata.sh` embeds
  `ecs_host_prepare.sh` verbatim, so there is still one definition.

**Two numbers M3-B-1 should use, and one correction.**

- **Transport is 5.1 ms median fleet-wide** from the in-VPC controller (p90 6.3,
  per-host 4.4-5.4, 200 commands), against the rolling restart's own 71 ms and
  61 ms budget. Across an exact-200's 3037 `runtime_command` rows that is
  **15.5 s**. **Run the gate from the controller, never from a workstation**: the
  same measurement from a laptop is 110-116 ms, about 5.6 minutes of round trip,
  and a baseline frozen with that in it could never be reproduced.
- **Clock offsets are -0.05 to -0.88 ms inside ±7 ms bounds** on all eight - the
  first time real inter-host skew has been visible. From the laptop the same
  estimator gave +39 ms inside ±60 ms, which said nothing.
- **M3-A-2's "simulated numbers are lower bounds" is wrong in its direction.**
  That spike measured multiplexed ssh at 10.8 ms on the simulated fleet and
  assumed a real network would be slower; it is *faster*, because the simulated
  hosts were containers contending for one laptop's CPU. Do not quote simulated
  numbers as fleet numbers - but do not assume they are optimistic either.

**One evidence-shape delta to declare before freezing real baselines.**
`LocalResourceSampler.host_sample()` populates **2 of 6 cgroup fields** on a VM -
`cpu_usage_usec` and `cpu_throttled_usec` yes, the four memory ones null - because
a container is a delegated child cgroup while a VM's sampler reads the root one.
Every simulated baseline carries six. That is a vocabulary delta of the kind
`simulated_ladder_slice_map.md` §6 requires to be declared in advance, not drift.

**What host preparation did not do, and it is the honest boundary:** no Valkey
cluster has been formed on these hosts. Formation dwell, RTO, the fault lane's
9/12/15 and the health-gate escalation of slice map §16 are all untouched.
`scripts/native_bringup_smoke.py` against `fleet_id: gce-m3b` is the natural
first step and belongs to item 1.6. *(All of that is now done - see below.)*

### Session M3-B-1 is done, and with it roadmap item 1.6

Read `project/docs/real_fleet_ladder_slice_map.md`. §2 is the five defects the
runs found, §3 auth/kernel/conntrack reality at fleet width, §4 transport, §7 the
equivalence result, §9 the ownership proof, §9a the health-gate correction, §10
what is open and what 1.7 inherits.

**The item's hard stop is met.** Two consecutive native exact-50, **PASS 861.46s
and 869.18s**, and two native exact-200, **PASS 1462.73s and 1454.44s**, all four
12/12 steps with `run_verdict` 12/12 OK, on eight real `c4a-standard-2` GCE hosts
driven from an in-VPC controller. 50/50 and 200/200 nodes, fault lane **9
scenarios / 12 command rows / 15 windows** with nine `REAL_PASS` at both scales,
cleanup 20 and 40 rows in four kinds with `found: 0` everywhere, no `ERROR` in
any artifact, and zero residue on all eight hosts checked from outside the
product over ssh. `repository.all` **92/92** on the Mac throughout.

- **The equivalence result, and it is stronger than a score.** Scores summarise,
  so the comparison was made on the delta itself: every diffed view reduced to
  the set of generalised JSON paths that differ. The real fleet's delta against
  the frozen Docker exact-50 baseline is **the simulated fleet's delta, path for
  path** - 111 paths either way, empty set difference in both directions - and
  **22 paths either way at exact-200, with no path appearing at 200 that did not
  appear at 50**. Both real exact-50 runs score `runtime_start` 5/7,
  `cluster_form` 5/5, `management_matrix` 6/8, `fault_matrix` 4/6, `cleanup` 1/2,
  the same marks the accepted simulated pair scored, and are identical to each
  other in every view and every field. Calibration was re-taken first: the two
  frozen Docker runs give 7/7, 5/5, 8/8, 6/6, 2/2.
- **Five defects, every one found by running rather than by reading**, and four
  of them only reachable from a controller that is not a development laptop: a
  test that measured pytest's `tmp_path` instead of the 104-byte socket limit
  (`735ee11b`); the preflight demanding a Docker daemon of a run that uses none
  (`956cfa33`); the memory budget asking the controller about memory spent on
  eight other machines (`aaa024ca`); a `SKIPPED_WITH_REASON` reason placed where
  §12.1's validator cannot see it, which refused an otherwise perfect 860 s run
  (`0147a946`); and the preflight having no fleet to read because
  **`_prepare_runtime` preflights the profile's canonical template, not the
  configuration the run uses** (`c58a762a`).
- **Two operator decisions, both reported before the change**: `can_run` widened
  to accept `SKIPPED_WITH_REASON`, and the memory budget comparing each nodehost
  against the host it is placed on, read from that host, fail-closed.
- **Transport is closed for real, on real-network numbers.** Through the
  product's own `MultiplexedSshTransport`: **5.3 ms** median at parallelism 1,
  **8.6 ms** at the run's own 8 (p90 12.5), 26.9 ms at 32, per-host 7.4-8.9 ms,
  against the rolling restart's own 71/61 ms budget. **`simulated_ladder_slice_map.md`
  §15.2 is corrected**: its `runtime_command` rows are the RESP path on the
  native backend, not the seam's transport - a native run's command audit records
  **no ssh at all**, where a Docker run records every `docker` call under the same
  kind.
- **Real clock skew is visible for the first time and inside its bound.** The
  eight hosts agree with each other to within 0.7 ms; the common term is the
  *controller's* drift and moved between -4.8 ms and +5.7 ms across the day,
  against bounds of ±6.5-7.5 ms. A threshold calibrated on either other
  environment would have been wrong here.
- **conntrack is not consumed by this product**: module loaded, max 1048576,
  count **0 before, during and after** a partition installed by the backend's own
  `isolate_nodehost`; its rules carry `-m comment` and no state match. Rules
  0 → 6 → 0.
- **Transport-failure classification, which the roadmap kept open, is answered
  and reported rather than changed.** `put`/`get` raise `TransportError` for
  every failure; **`run` returns every ssh failure as `CommandResult` rc 255**,
  including a host that cannot be reached at all. Harmless at every site that can
  be named, and changing it moves what `is_collection_failure` sees for a whole
  class of failures - a verdict contract, so it is its own change.
- **Ownership proved twice.** `native_cleanup_proof.py release|abort|stubborn
  --fleet-id gce-m3b`: **43 → 0** managed residue on eight real hosts in all
  three modes. And the roadmap's literal ask: a real 50-node gate run was formed,
  allowed into the management matrix, and its controller `SIGKILL`ed, leaving 50
  live `valkey-server` plus four run trees and four bundles - then `cli gate
  cleanup` from its `state.json` took every host to zero, checked from outside.
- **Formation dwell recorded, the 240 s window not re-argued.** exact-200 forms
  in **52.0 s and 72.1 s**, the first the lowest 200-node formation ever measured
  here; exact-50 in 47.4 and 53.4 s. Total formation bounds every single dwell,
  so the worst real dwell is at most 87 % of the 83.1 s the window was sized on.
- **§15.6's watch item did not fire**: both real exact-200 RTOs are 52.55 s and
  51.57 s, inside the 47.6-53.8 s spread, so the simulated 41.28 s stays a single
  outlier. exact-50 RTO 49.54 s and 48.54 s, inside the 45-50 s band.
- **§14.6/§16.1 refined, and a counting error corrected.** §14.6 counts
  `sample_scope: all_nodes_diagnostic`; the real fleet escalates under the
  *representative* label, so that counter reads zero for every real run and this
  was nearly written up backwards. Counted on `full_probe_count`, the real fleet
  escalates 3-6 of 44 gates at exact-50 and never at exact-200 - so §14.6's
  finding and §16.2's inversion with scale both hold - but **never once reaches
  the diagnostic round**, which the simulated fleet did 3-5 times per run. §16.1's
  "the runtime is the variable" is right about the retry and wrong about the
  severity; the harness is the surviving candidate and is not proven.

**The native baselines are frozen, and they live on the controller.**
`artifacts/baselines/real-exact-50-c58a762a/` (97 MB) and
`real-exact-200-c58a762a/` (457 MB), both at `c58a762a`, each with a
`BASELINE.md` recording the commit, the fleet and its manifest digest, the hosts,
and the invocation - which **requires `ulimit -n 65536`**, because
`runtime_fd_limit` asks for 1856 at exact-200 and Debian's default is 1024. They
are not on the workstation on purpose: it cannot reach the fleet, so every diff
against them runs where they are.

**Read their calibration limits before using them.** `management_matrix` does not
self-calibrate and cannot - §14.6's retry record inside `stdout_tail` and §14.7's
`errors_observed_during_operation` are genuine per-run observations - so a
candidate is judged on the other views and on the field-level delta, not on that
view's score. One normalisation gap *was* real and is fixed (`b1c1a507`):
`_cleanup_scrub` had lost `scrub`'s `pid` rule and never saw the native residue
rows' process records, so `cleanup` self-calibrated 1/2; the list is now sorted
with pids scrubbed and is deliberately not reduced to a count, because `cwd` is
item 1.4's ownership mark and `exe` exists so a reader hears about something
unexpected. Proven by seeding three regressions, not by calibrating.

**The declared evidence-shape delta held:** `LocalResourceSampler.host_sample()`
populates 2 of 6 cgroup fields on a VM, and the four absent ones carry a
`MISSING` object with its own reason rather than a null. It moves no diffed view.

**Two configurations were added and one key differs from their siblings**:
`real_ecs_50.yaml` and `real_ecs_200.yaml` are `native_50`/`native_200` with
`runtime.host_inventory_path` naming `gce-m3b`. `real_ecs_200.yaml` keeps
`profile_name: scale_200`, because `_is_exact_200_bounded_exception` keys on it.

**M3-B-2 is roadmap item 1.7, on operator approval, and the correct state now is
idle.** Do not re-freeze the baselines. What 1.7 inherits is slice map §10.1: no
`real.ecs.*` id exists in `catalog.json`, the two configurations above are what
those entries will name, registering a Test moves `repository.all` 92, catalog 96
and the M1 plan 91, and M3 still has a registered check on 1 of its 6 criteria -
this item produced the evidence for four of them and attached a check to none,
because that is 1.7's work. *(Item 1.7 is now done; the counts it actually moved
are catalog 96 to 99, with `repository.all` and the M1 plan unchanged.)*

Added to the open list, none of them this item's to close: `run` not classifying
a transport failure; a native run's command audit recording no ssh, which is an
evidence-parity gap between two backends meant to be comparable; whether the
preflight should validate the document the run uses rather than the profile's
template (a safety guard reads that document, so it is the operator's call); and
that the 92/92 suite does not reach `_process_runtime_state`'s call site with its
real signature - a wrong keyword there passed the whole hermetic suite and was
caught by three real runs in ten seconds each.

### Session M3-B-2 is done, and with it roadmap item 1.7 and M3-B

`./gate milestone m3` is **PASS, 8/8, `definition_status: READY`, on the first
attempt** - invocation `gate-20260813T015536Z-551fcacf` at `2a30563b`, 53 minutes
from the in-VPC controller. Read `project/docs/m3_acceptance_registration_map.md`;
§1 is the item (what a native run already asserts about itself, which is what
decided the shape), §2 the attachment map and its cost, §3 the fd limit, §5 the
acceptance and §5.1 the one thing that survived on a host.

- **Most of this item was deciding, not building.** `run_exact_gate` ends in
  `validate_raw_sources_by_kind` and `build_admission_from_sources`, both
  fail-closed, and between them a run already refuses itself unless its plan is
  exact, `run_state` carries exactly N unique nodes, the independent probe reports
  `cluster_state: ok` with `known_nodes == N` and 16384 slots, `cleanup_report`
  has no `resources_remaining` and no `cleanup_errors`, and `host_evidence`
  accounts for every nodehost with a `host_id`, two clock readings each with a
  measured bound, and one digested journal per observed node. So **`exact.50`,
  `exact.200` and `evidence` needed no new assertion** - the run is the check,
  as M1's `local.exact.50` already uses `real.local.full-flow`.
- **Two things a passing run does not say**, and they are why this was not only
  catalog editing. **Nothing anywhere names `native_multi_ecs`** - grep over
  `evidence/`, `analysis/` and `gates/` returns nothing - so "a real multi-ECS
  run" would have been asserted by a configuration's *file name*. `--backend
  native_multi_ecs` in the entry's argv fixes it with existing mechanism:
  `backend_for_provider` refuses it for a `docker` provider, measured both ways.
  And **the abort path is not on a passing run's path**, so
  `safety-and-cleanup` gets the real-fleet proof item 1.4 built and item 1.6 ran.
- **`ulimit -n 65536` now lives in `scripts/ecs_gate.py`**, which raises
  `RLIMIT_NOFILE` toward 65536 (never above the hard limit), prints what it got,
  and `execv`s the CLI. The operator chose this over configuring the controller
  so the milestone states its own requirement. The preflight is not weakened:
  exact-200's `runtime_fd_limit` records `required_min: 1856` against
  `soft: 65536`, in the run's own evidence.
- **`product.orchestrator` is stale in a measurable way** - it tests
  `orchestrator.local.validate_inventory`, imported by `docker_runtime.py` and
  nothing else, while a native run reads `runtime/host_inventory.py`. The
  criterion now carries `product.unit.native_backend` as well, plus a new test
  for the duplicate-host refusal, which the real module has and nothing covered.
  **Reported, not decided:** the statement's "explicit local endpoints" clause is
  the shim's vocabulary, so the shim is *kept beside* the real contract rather
  than dropped; narrowing the statement is the operator's call.
- **Three `real.ecs.*` entries**, all `{"type": "command", "result": "json"}`:
  `real.ecs.full-flow` (`nodes`, `config`), `real.ecs.bringup` (`fleet_id`) and
  `real.ecs.cleanup-ownership` (`fleet_id`, `mode`), plus a `real.ecs.full-suite`.
  The last two are the harnesses item 1.4/1.5 built; each gained a
  `--result-path` and nothing else. `fleet_id` is a `string` and not a `path`
  because the manifest lives under gitignored `project/artifacts/`, and a `path`
  parameter is checked for existence at plan time.
- **Counts: catalog 96 → 99, `repository.all` still 92, M1 plan still 91.**
  Two further contract assertions moved with it - M3's `definition_status`
  DEFINED → READY, and M3's expansion, which is now eight checks in order.
  `repository.all` is 92/92 on the Mac and 91/92 on the controller, the missing
  one being `product.integration.docker_runtime_contract` for the absent daemon.
- **Proven:** three real full-flow runs inside the milestone - exact-50 876.75 s,
  exact-200 1430.26 s, exact-50 886.73 s - all `native_multi_ecs`, 50→50, 200→200
  and 50→50 on 4, 8 and 4 distinct hosts, `run_verdict` 12/12 OK each, cleanup 20
  / 40 / 20 rows with `resources_remaining` empty and every residual scan
  `found: 0`, 50 / 200 / 50 journals, and the string `ERROR` in no artifact of
  any of them. Fault lane **9 / 12 / 15 with nine `REAL_PASS`** in all three.
  RTO 46.02 s and 49.00 s at exact-50, 53.38 s at exact-200 - all inside their
  bands, so `simulated_ladder_slice_map.md` §15.6's watch item does not fire.
- **All eight hosts were also asked directly over ssh**, outside the product:
  zero `valkey-server` and zero `vslab` firewall rules on all eight. One host
  holds `/tmp/vslab-load-lane`, **empty** - the fixed root above the run-scoped
  parent item 1.5 made the lane remove. Nothing on the host attributes it to a
  run, which is why the residue scan does not report it and why `found: 0` is
  truthful rather than convenient. See map §5.1.

**Operator decision, 2026-08-13: there is no merge to
`origin/codex/valkey-scale-lab-loop`, and M4 is developed on `fast-iter`.** The
branch is 144 commits ahead, zero behind, and a clean fast-forward whenever that
changes, but it is deliberately not taken - do not re-raise it as a next step.
Nothing is pushed. Note the consequence for M3's acceptance: the roadmap words
1.7 as `./gate milestone m3` green *on the merged default branch*, and it is
green on `fast-iter` instead. That is the operator's call and is recorded here
rather than argued.

**Nothing is stranded on the controller, and this was measured** on 2026-08-13,
not assumed: identical HEAD, zero commits unique to it, and its only tracked
difference is the not-mine `.github/milestone-loop/README.md`, byte-identical to
the Mac's. That is structural - the working loop only ever flows Mac to
controller, and the controller authors nothing. What lives there and cannot
travel is the gitignored `project/artifacts/`: the two frozen native baselines
(457 MB + 97 MB) and the fleet manifest. Losing the VM would cost ~50 minutes of
re-running, not code.

### After item 1.7, in the same session: a refused run now says so

Not a roadmap item and not part of 1.7. Read the corrected §12.2 paragraph in
"What is still open" below - it carries the measurement, the fix and its proof.
In one line: a run whose twelve stages passed and whose evidence was then refused
wrote `PASS` in every artifact it owns, which matters because freezing a baseline
copies a run directory. Admission is now a **check** in `run_verdict.json`.
Proven by two hermetic tests that fail without it and by a second
`./gate milestone m3` PASS 8/8 whose three runs' verdicts are identical to the
three before the change.

**Operator update, 2026-08-14: M4's goal is one target, not a ladder — 256
primaries with 4 replicas each, 1280 valkey-servers total.** The 500/1000/2000
paragraph below is superseded and kept because it documents the knobs. Compiled
at HEAD the same day, from a dry-run scale-projection config derived from
`real_ecs_200.yaml` with `cluster.shards: 256`, `cluster.replicas_per_shard: 4`
(no new config vocabulary needed):

- **The plan compiles at shipped knobs.** 1280 nodes, 640 per AZ, **52
  nodehosts (26 per AZ), 24-25 logical nodes each**, inside `max_nodehosts: 64`
  — so the exact-2000 plan-time refusal below does not apply to 1280 and M4 is
  no longer blocked on the density arithmetic. One nodehost per host means
  **52 ECS hosts** against today's 8, which is the provisioning decision.
- **What actually blocks a real 1280 run is the safety contract, three ways**,
  all in `config/validation.py`: `REAL_EXECUTION_ABOVE_200_FORBIDDEN` (above
  200 must be dry-run), `WORKLOAD_ABOVE_200_FORBIDDEN`, and the ≥1000 block
  (`MISSING_1000_*`), which is dry-run-only by construction. The only
  real-execution exceptions are exact-200 (`scale_200`'s bounded exception) and
  exact-2000 — and the 2000 one requires `provider: docker`, so it could not
  serve the fleet even at its own node count. Admitting a real native
  exact-1280 is a semantic change to a validation contract; a bounded-exception
  profile in the shape `scale_200` already has is the natural form, and by the
  working rules it is reported before it is made.
- **Placement, measured on the compiled plan:** no shard places two members on
  one nodehost (0 of 256), and `_replica_az` puts **all four replicas in the AZ
  opposite their primary** — every shard splits 1/4, so losing one AZ leaves
  half the shards with a promoted replica and the other half with a primary and
  zero surviving replicas. At `replicas_per_shard: 1` the same rule is just the
  cross-AZ pair; whether 1/4 is acceptable at four replicas is an operator
  question the old ladder never posed.
- **`milestones/m4/milestone.json` still names 500/1000/2000** in its goal and
  three `scale.exact.*` criteria; rewriting it to the 1280 goal is the first
  piece of M4 definition work, not done conversationally.
- Every fault-lane constant (9/12/15), RTO band and formation-dwell number was
  measured at `replicas_per_shard: 1`; none of them transfers to 5-member
  shards by assumption.

**The multi-replica prerequisite is explored and designed; read
`project/docs/multi_replica_support_map.md` before implementing any of it.**
Written 2026-08-14 from four independent code sweeps plus real planner
compiles, no code changed. In one paragraph: two hard `node_count // 2` breaks
(`_management_matrix_clean_health` at `docker_runtime.py:11785` and
`_local_full_flow_wait_clean_cluster_snapshot` at `:9713`) fail every r≥2 run;
the runtime's `_node_specs` AZ formula contradicts the planner's at r≥2 (map
§2.3/§7.1 — **decided 2026-08-14 by the operator's own requirement: a shard's
members evenly distributed across all AZs (3/2 at five members over two) AND
the fleet's per-AZ totals even**, which the runtime's alternating formula
produces exactly (computed against the operator's own 6-shard example,
15/15); the plan constraint is renamed to assert per-shard AZ balance, and
§7.1 carries both properties as MR-1's acceptance criteria); the absent
`cluster-migration-barrier`/`cluster-allow-replica-migration` directives let
Valkey auto-migrate replicas into a permanent `SemanticFailure` at r≥2 (§2.4);
the two M2 lanes hardcode the promotion winner and are proposed deferred
(§2.5/§7.4); odd shard counts are refused at r≥3 (§2.6). The fault lane's
9/12/15 is invariant under replica count **by design**; the rolling-restart
batcher, `redundancy_recovery`, the affected-shard observer, schemas, evidence
and the actuator are already r-generic. Declared deltas for r≥2 runs are map
§5 (management rows ≈980 at 10×4 by a closed-form law checked against both
frozen baselines; canary count = shard count; r=4 RTO is a new band with no
prior). The run ladder is §8: MR-1 fixes + r=1 no-op proof, MR-2 Docker
10×4-50 with a same-commit 25×1 control, MR-3 native on the existing 8-host
fleet (10×4-50 ×2, then 40×4-200 at shipped knobs). Every rung fits gce-m3b as
provisioned; only M4 itself provisions.

### M4's fleet problem is solved by measurement, not by quota, 2026-08-15

**Not a roadmap item.** Google Cloud refused the quota increase M4's plan assumed
- CPUs, disks *and* GCE instance counts, on a new project - so `gce-m3b`'s eight
`c4a-standard-2` can neither grow nor be resized. Read
`project/docs/m4_density_calibration.md`; §1 is the arithmetic, §3 the result,
§5 what M4 should plan for.

- **The 52-host figure was never a requirement.** It is what falls out of leaving
  `max_logical_nodes_per_nodehost` at 25. Compiled at HEAD through validation,
  the planner *and* the run path against a manifest of this fleet's shape, 1280
  nodes plan cleanly at **8, 16, 26 and 52 hosts** - 0 of 256 shards colliding,
  every shard 3/2, fleet 640/640 at all of them. Host counts must be **even**
  (13 refuses), and at 8 hosts `node_memory_limit_mb` must drop 64 → 32, because
  160 × 64 MiB exceeds 7900.
- **So the real question was whether 160 nodes per host still measures the
  cluster or the CPU.** Every prior real-host number is 25 nodes/host = 12.5
  valkey-servers per vCPU; the eight-host M4 plan is **80 per vCPU**. That is the
  M3-A-2 trap again - simulated numbers assumed to be lower bounds turned out to
  be the opposite because those hosts contended for one laptop's CPU.
- **Measured, at the largest lever the 200-node cap allows.**
  `templates/configs/real_ecs_200_2host.yaml` is `real_ecs_200.yaml` with two
  lines changed, packing the same 200 nodes onto **2 hosts = 100/host = 50 per
  vCPU, 4×** the measured density. Three runs at one commit on one afternoon:
  dense **PASS 2055.87 s** and **PASS 2086.26 s**, 8-host control **PASS
  1302.90 s**.
- **Nothing that carries a verdict moved.** All three: `run_verdict` 12/12 OK,
  fault lane **9/12/15** with nine `REAL_PASS`, zero residue on all eight hosts
  asked over ssh from outside, 200/200 journals, no `ERROR` in any artifact.
  Detection is flat in density as well as in node count (42.55 / 43.55 / 43.04 s),
  and the Sentinel probe's cadence is indistinguishable with **zero overruns in
  all three** - the measurement most likely to degrade under contention, and it
  did not. The lever did pull: load average on the 2-vCPU dense host was sampled
  at **5.73, 4.21, 0.78, 0.43, 4.13**, bursting to ~3× the core count.
- **What moved, and it is bounded.** Formation dwell 85.88 s and 46.95 s against
  the control's 10.93 s - but the control is the *fastest* 200-node formation
  ever recorded here and the frozen pair is 52.0/72.1 s, so both dense values sit
  **inside** the historical range; the 240 s window was never approached.
  PFAIL → promotion 4.00/3.00 s against 1.00 s, both still far below the frozen
  pair's 8.00/19.03 s, so density moves it less than ordinary run-to-run
  variance does. The management matrix is 1.7× slower and that is **batch
  geometry, not contention**: restart parallelism is capped by nodehost count, so
  2 nodehosts give 100 batches at max concurrent 2 where 8 give 26 at max 8.
- **The answer: M4 on the existing eight hosts is defensible and needs no
  quota.** Narrowly: this is 50 nodes/vCPU against M4's 80, an extrapolation
  across a further 1.6× and the most the 200-node cap permits; M4 raises node
  count *and* density together; and it is two runs a side.
- **What M4 should plan for**, compiled rather than guessed: **322 batches at max
  concurrent 8** for 1280 nodes on 8 nodehosts, which at the control's measured
  17.4 s/batch is **≈93 minutes of management matrix**, so **an M4 run is about
  two hours** - inside the 14400 s timeout, but it makes "several runs per rung"
  a real scheduling cost. Journals should be ~500 MB per run. 32 MiB/node is a
  declared second variable.
- **Untouched by any of this**, and still the actual blockers:
  `REAL_EXECUTION_ABOVE_200_FORBIDDEN` refuses every real run above 200 nodes and
  is a validation-contract decision, not a quota one - compiling §1's table
  needed a sanctioned scale-projection profile because of it; and the whole-fleet
  probe cadence on the open list becomes 1280 queries/second from a 4-vCPU
  controller at M4's size. A 200-node run reaches neither.

### Stage MR-3 is done, 2026-08-14, and with it the multi-replica prerequisite program. M4 needs operator approval and the correct state now is idle

Three commits: `26613317` (the two configurations), `f9b10814` (a defect in the
acceptance instrument that the control found) and the map. Read
`project/docs/multi_replica_mr3_slice_map.md`: §3 is that defect, §5.2 the
support-map hazard being met for the first time, §6.2 the founding claim of
MR-2's that does *not* transfer, §7.1 a prior claim the frozen baselines
correct, §8.2 the fleet-width result and §10 what M4 inherits.

**Four runs, four passes, no failed attempt**, all from the in-VPC controller:
25×1-50 control **PASS 889.15 s**, two 10×4-50 **PASS 701.21 s** and
**718.49 s**, and 40×4-200 **PASS 1146.58 s**. Every one: `run_verdict` 12/12
OK, `tool_errors` empty, fault lane **9/12/15** with nine `REAL_PASS`,
`resources_remaining` and `cleanup_errors` empty, every residual scan `found: 0`,
journals **50/50** and **200/200**, `host_evidence` PASS with a `host_id` and two
clock readings per nodehost, and the string `ERROR` in **no** artifact. All eight
hosts asked over ssh from outside the product afterwards: **zero** valkey
processes, `vslab` rules, `VSLAB` chains, run trees and bundles. **No baseline
was frozen** - that stays M4's.

- **The control earned its place twice.** It proved nothing drifted in the many
  commits since `c58a762a` - `runtime_start` 7/7, `cluster_form` 5/5,
  `management_matrix` 6/8, `fault_matrix` 4/6, `cleanup` 2/2, with the two
  `fault_matrix` views being the 2026-08-13 failover work's declared pair and no
  third - and it found the defect below, which would otherwise have been read as
  a rung-A finding.
- **`diff_stage_artifacts.py` did not scrub the Gate's own test directory**, so
  the control scored `runtime_start` **3/7** and `cleanup` **1/2** against a
  baseline that calibrates 7/7 and 2/2. The entire difference in both was one
  string: the baselines were frozen through `real.local.full-flow` and every
  acceptance run since item 1.7 is taken through `real.ecs.full-flow`. Measured
  by rewriting the name in a copy before changing anything. Fixed, with four
  seeded regressions each caught by the view that owns it - including an
  `artifacts_dir` pointing outside the run's own test directory, which is the one
  the change could have broken.
- **Every declared quantity hit.** 10×4-50: **958** management rows against the
  law's 956 (the same two-row miss MR-2 measured on Docker), **10 batches / max
  concurrent 8**, canary **10**, the §2.4 pin in **50 of 50** node configs.
  40×4-200: **3456** rows against ~3480, **26 batches / max 8**, canary **40**,
  pin in **200 of 200**. **One inherited prediction was the handover's and was
  corrected before running**: `cleanup_actions` is `5×nodehosts` on a native run,
  not `5×nodehosts+1` - the `+1` is Docker's network row - so **40** at eight
  nodehosts, which both rungs measured and both frozen native baselines already
  said.
- **Support map §3.1 was exercised for the first time and did not fire.** At
  four replicas the down-window full validation ran over **49 nodes** with three
  siblings re-attaching to the newly promoted primary, and returned OK in both
  candidates; at one replica it is vacuous. Not a disproof of an intermittent
  hazard, but the first evidence of any kind - MR-2 never reached the check.
- **§3.2 fires on the real fleet too**: `replacement_logical_id` predicted
  `replica-00` while the observed winners were `replica-01`, `replica-02` and
  `replica-00`. Three of four multi-replica runs across two runtimes now name the
  wrong promoted node with nothing failing. Untouched by instruction.
- **MR-2's founding claim does not transfer, and the reason is variance.** MR-2
  read PFAIL → promotion as "four candidates elect faster than one" (1.5-5.1 s
  at r=4 against 18.2 s at r=1). Against r=1 numbers re-derived from the frozen
  baselines' own retained rounds, the direction **reverses with scale**: at
  exact-50 r=1 is 2.50/3.00/6.50 s and r=4 is **6.02/10.55 s**; at exact-200 r=1
  is 8.00/19.03 s and r=4 is **5.02 s**. MR-2's comparator was a workstation
  number with no counterpart here. **The replica count's effect on election time
  is not established** - the r=1 spread at each scale is wider than any gap to
  the r=4 points. Two runs of one configuration gave 6.02 s and 10.55 s inside
  RTOs 0.3 % apart, which is the failover work's own warning to M4 arriving
  early: rank on the split, and budget several runs per rung.
- **Nothing undeclared, measured as a vocabulary comparison** over 38 artifacts,
  ~3,920 paths. Control against candidate 2: **one** differing path. And the
  result that settles what that family is - **the two identical-configuration
  candidates differ in sixteen**, more than the control differs from a candidate.
  Every differing path is a `cluster_stats_messages_*` counter or
  `sentinel_fault_probe.samples[].errors.control`, both MR-2 §5.3's, now
  confirmed on a second runtime. **The replica count moved values, not shapes.**
- **The delta does not grow with fleet width.** Against the frozen 100×1-200
  baseline, rung B's differing paths fall in exactly three groups and the replica
  count is none of them: the failover work's `failover_timeline` and refs, MR-1's
  declared `primary_replica_distinct_az` → `shard_az_balanced` rename, and
  nothing else. **Four replicas add no path at 200 that the one-replica 200-node
  baseline lacks.**
- **`fault_matrix` does not self-calibrate at r≥2, and on this fleet
  `management_matrix` does not either.** Candidate against candidate: 7/7, 5/5,
  **6/8**, **3/6**, 2/2. The whole `fault_command_log` delta is a single token,
  the promoted node in the `CLUSTER REPLICATE` that restores the killed primary.
  The `management_matrix` delta is exactly the two fields `BASELINE.md` already
  names at r=1. Both are properties M4 inherits, not regressions.
- **A prior claim is corrected by the frozen baselines themselves** (map §7.1).
  `real_fleet_ladder_slice_map.md` §9a says the real fleet escalates its
  rolling-restart health gate but "never once reaches the diagnostic round".
  That counter reads `stdout_tail.sample_scope`, which names the *last* attempt's
  scope; read in `probe_summary.attempts[]`, the frozen baselines reach
  `all_nodes_diagnostic` **2 and 4 times**. The escalation's inversion with scale
  holds (50 yes, 200 never) and **the replica count is not a variable in it**.
  Not MR-3's to close.
- **Proven:** `repository.all` **92/92** on the Mac; **catalog stays 99, the M1
  plan 91 and the pytest tree 849** - nothing was registered, because
  `real.ecs.full-flow` takes `nodes` and `config` and admits 30..200.
- **One acceptance criterion was not met and is reported rather than cleared**
  (map §9.4): the controller is **90/92**, not 91/92. The extra failure is
  `product.scenarios.execution_axis_contract`, whose single finding is inside
  candidate 1's **base64-compressed HDR histogram** in
  `load_lane/memtier_formal.json` - the auditor's identifier pattern matched an
  upper-case P and two digits inside a compressed byte stream, because
  `SCAN_ROOTS` includes `artifacts`. (Described rather than quoted: `docs` is
  scanned too, so the map's first draft quoted the literal and failed the check
  it was reporting - see map §9.4.)
  Nothing this session touched the checker or its test, the same suite was
  91/92 on the same controller hours earlier, the file is gitignored run output,
  and it fired on one of four runs because it depends on that run's latency
  bytes. **So a real run can fail a repository contract check by chance, and
  `repository.all` is not deterministic on a machine that has taken one.**
  Narrowing what a contract check scans is a semantic change to a validation
  contract and needs its own evidence, so it is the operator's call. The run
  artifacts were deliberately not deleted to make the suite green.

**Do not read a passing native run as evidence about MR-2's announced-address
fix.** `data_address` and `client_endpoint.address` coincide on gce-m3b, so the
old broken comparison would have held there; the evidence for that fix stays
MR-2's Docker runs and its four mutation-checked tests.

**Two measuring instruments moved into `scripts/` at `92e05fcc`**, because the
map cites results that could not otherwise be reproduced and MR-2 had already
hand-rolled one of them once: `diff_artifact_vocabulary.py` (what stays
comparable when the *shape* changes, since the view scores stop carrying
information) and `reconstruct_failover_timeline.py` (a pre-`failover_timeline`
run's stage terms, from rounds the lane always retained). Both are checked
against **MR-2's published numbers** rather than the scratchpad they came from,
using its three Docker runs, which are still on the workstation.

**The controller went unreachable at the end of the session** - `34.142.156.225`
port 22 stopped answering after the runs and the commits were done, which is the
recorded behaviour of a stopped instance (its external IP is ephemeral; ask the
operator for the new address and check the host key rather than trusting one).
Nothing is lost: it authors nothing, its `project/` tree was clean and synced at
`b1dde527`, and everything committed after that point is workstation-only docs
and scripts. But **it is behind by every commit after `b1dde527`, so rsync
before running anything there**, and MR-3's four run directories (~350 MB) exist
only on that disk.

### Stage MR-2 is done, 2026-08-14

Two commits, `c8021123` (the configuration) and `2972b736` (the defect the runs
found). Read `project/docs/multi_replica_mr2_slice_map.md`: §3 is the defect and
why reading could not have found it, §5 the declared deltas measured, §6 the
founding data, §7 the determinism result and the one place it does not hold, §8
what MR-3 inherits.

**`templates/configs/local_10x4_50.yaml` is the first multi-replica
configuration in the repository**, at `nodehosts_per_az: 4` giving **8
nodehosts** - stated in the file rather than implied. The shape also plans clean
at the shipped 2 with 6 nodehosts; 4 was taken because it is the nodehost count
MR-3's native 10×4-50 and 40×4-200 both land on against gce-m3b as provisioned,
so every multi-replica rung stays diffable against every other in the four views
the knob moves. Compiled through the run path: 8 nodehosts holding 7,7,6,6,6,6,
6,6, **zero of ten shards colliding**, every shard **3/2** across the AZs and
the fleet **25/25** - the §7.1 policy observed at four replicas for the first
time.

- **The first 10×4 run failed, and the cause is deterministic rather than the
  intermittent one that was predicted.** `AffectedShardObserver._relationship`
  asked whether a surviving replica names the promoted node as its primary by
  comparing the replica's `ROLE` reply against **the observer's own dial
  address**. A replica reports the address its primary *announced*; under Docker
  that is the nodehost's network address while the observer dials a published
  port on `127.0.0.1`, so the comparison could never hold. Measured from the
  passing control's own artifacts: every `primary_host` anywhere in that run is
  `172.18.0.x`, and `shard-0000-replica-00` records
  `{"primary_host": "172.18.0.5", "primary_port": 7400}` against a primary whose
  `container_ip` is 172.18.0.5, `client_port` 7400 and `host` 127.0.0.1 - **the
  announced port coincides, the host does not**. At r=1 the affected shard has
  one survivor, which promotes, so the branch is unreachable: 95 rounds in the
  control, never entered. `NodeEndpoint` now carries `announced_host` from
  `container_ip`, which is the peer address on **both** backends, so no backend
  branch was needed; the lookup is off the survivor set rather than the row, so
  **no artifact key was added and no r=1 diff view moves**.
- **Support map §3.1 is still unobserved and remains live.** It predicted the
  down-window full validation refusing three resyncing siblings; what happened
  is one level earlier and `full_validation` was **never called**. The two are
  told apart by which message appears, and the map records both. Both candidates
  then passed that validation with three resyncing siblings - not a disproof of
  an intermittent hazard, and the native rung with real latency is the likelier
  place for it.
- **Support map §5.2 is wrong.** The `safe_path` it predicts
  (`"40_replicas_observed_replicating_for_10_primaries"`) appears in no run: its
  f-string is reached only for `create_cluster` and `meet_nodes`, and
  `add_replica` hardcodes a method name instead. That dict entry is dead code.
  Reported, not fixed.
- **Every other declared delta hit**: `management_command_log` **958** rows
  against the row law's 956, rolling restart **10 batches / max concurrent 8**
  (compiled in advance through the real batcher), `cleanup_actions` **41** rows,
  Sentinel `canary_count` **10**, the §2.4 topology pin in **50 of 50** node
  configs against 0 at r=1, fault lane **9/12/15** unchanged.
- **Nothing undeclared, measured as a vocabulary comparison** rather than a
  score, because 22 of 25 views differ when the shape differs. Every artifact
  reduced to its generalised key-path set: **control against candidate 1 is
  identical, zero paths either way**, across 18 artifacts. Two fields vary and
  neither is a shape change - `cluster_stats_messages_update_*`, which Valkey
  emits only after UPDATE gossip and which flaps **per run, not with replica
  count** (absent, present, present, absent across the four runs, and it moves
  no diff view); and two `TRANSIENT` `CLUSTERDOWN` samples on the Sentinel
  *control* canary, which is fleet-wide while any shard's slots have no owner.
- **A multi-replica run is not deterministic in `fault_matrix`, and cannot be.**
  The two candidates elected different replicas, so `fault_matrix` scores
  **3/6** candidate-to-candidate where the other four stages are 7/7, 5/5, 8/8,
  2/2 identical. All three differing views trace to that one cause: the tool's
  `fault_command_log` diff is **a single token**, the promoted node's name in the
  `CLUSTER REPLICATE` that restores the killed primary. At r=1 the lane was
  deterministic *by construction* - one survivor, one possible winner. **So a
  multi-replica baseline cannot be calibrated candidate-to-candidate in
  `fault_matrix`**, the same shape as M3-B's `management_matrix` finding, and
  MR-3 must plan its acceptance around that before running.
- **Support map §3.2 is now observed rather than predicted**: both runs write
  `replacement_logical_id: shard-0001-replica-00` while the observed winner was
  `replica-01` in one of them, with nothing failing. Left untouched by
  instruction.
- **Founding data, no prior and compared against nothing.** r=4 primary-kill RTO
  **45.793 s** and **44.341 s** (r=1 control 48.303 s); formation dwell under
  4-way sync fan-in **21.74 s** and **19.01 s** against the control's 73.20 s,
  so **dwell is dominated by shard count, not node count**, and the 240 s
  no-progress window was never approached. Note the aggregate hides its parts:
  PFAIL → promotion is **1.5-5.1 s at four replicas against 18.2 s at one**
  while RTO moves under 10% - the 2026-08-13 lesson recurring under replica
  count, and a reason for M4 to rank on the split rather than on RTO.
- **Proven:** `repository.all` **92/92** (`gate-20260814T103600Z-9f2bc703`),
  catalog still **99**, M1 plan still **91**, pytest tree **845 → 849**. Four
  mutations each reverted and watched to fail - and the first version of the
  refusal test strayed only in the port and stayed green when the host
  comparison was deleted, so it is now two tests straying in one field each.
  Four real Docker exact-50, all PASS 12/12 with zero residue and no `ERROR`:
  controls **873.69 s** and 846.17 s, candidates **768.80 s** and **718.56 s**.
  The two controls sit either side of the fix and are **identical in every view
  of every stage** (7/7, 5/5, 8/8, 6/6, 2/2), which is the r=1 no-op proof. The
  control scores 7/7, 5/5, 6/8, 4/6, 2/2 against the frozen baseline with both
  inherited deltas at their declared shapes and no third, fault lane 9/12/15,
  RTO 48.303 s.

**No native run was taken and no baseline was frozen** - both are MR-3's.
Neither frozen baseline nor any existing `templates/configs/` file was touched.

**The codebase already stated the distinction the observer ignored**, at three
sites, checked after the fix: `docker_runtime.py:1758` writes
`cluster-announce-ip {nodehost['container_ip']}` and
`cluster-announce-port {node['client_port']}` for **both** backends, so the
announced address is exactly the pair `announced_host` reads; `:1797` sets the
node's dial address with the comment "the peer address the cluster announces is
nodehost_container_ip below, **and they differ**"; and
`_advertised_endpoint_resolver` (`:8149`) already does this mapping for the
Sentinel lane. The fix follows an existing sanctioned pattern rather than
inventing one.

**And it would not have fired on the real fleet**, which decides how nearly it
escaped: the dial and announced addresses differ under Docker and on the
*simulated* fleet, but coincide on gce-m3b (`native_backend.py:819` - the
manifest repeats one address). Had MR-2 been run on the fleet instead of on
Docker, the defect would have passed through MR-3 untouched and waited for M4.
A passing native run is therefore **not** evidence about this fix.

**What MR-3 inherited, compiled at `3b399469`.** *(MR-3 is done - see its
section above. Its arithmetic held exactly; only the `cleanup_actions` row count
was wrong, being the Docker law rather than the native one. Kept because the
derivation reads from it.)* MR-3 is support map §8's third
rung - two native **10×4-50** on gce-m3b, then one native **40×4-200** - and it
needs operator approval. Read `project/docs/multi_replica_mr2_slice_map.md` §8;
the ten items there are the handover. The arithmetic, compiled through
validation, `build_cluster_plan` *and* the run path against a manifest of
gce-m3b's shape (the `ecs` run path reads the fleet manifest, so **these numbers
cannot be reproduced without one**):

| shape | knob | nodehosts = hosts | per nodehost | colliding | shard AZ split |
|---|---|---|---|---|---|
| **native 10×4-50** | `nodehosts_per_az: 4` | **8** | 7,7,6,6,6,6,6,6 | 0/10 | 3/2 |
| native 10×4-50 | shipped (2) | 6 | 9,9,8,8,8,8 | 0/10 | 3/2 |
| **native 40×4-200** | shipped | **8** | 25 × 8 | 0/40 | 3/2 |

**Rung A at 4/AZ reproduces MR-2's Docker layout exactly**, which is what the
knob was chosen for and is now measured on both providers. MR-3 writes the first
two native multi-replica configurations; **the 200 must keep
`profile_name: scale_200`**, because `_is_exact_200_bounded_exception` keys on
that name and carries no shard-shape term. No catalog entry is needed -
`real.ecs.full-flow` takes `nodes` and `config` and admits 30..200 - so catalog
stays **99**, `repository.all` **92** and the M1 plan **91**.

### Stage MR-1 is done, 2026-08-14. MR-2 needs approval and the correct state now is idle

Nine commits, `c72dd986` through `7d239597`, each with its own observation and
each leaving `repository.all` green. Read
`project/docs/multi_replica_mr1_slice_map.md`: §1 is the map's own arithmetic
being wrong and how running it said so, §3 each change, §4 the hermetic proof,
§5 the two real Docker exact-50 runs and §5.1 the mark that is not what the
brief expected, §6 what MR-2 inherits.

- **The map's central arithmetic was wrong, and it would have blocked MR-2's
  first rung at plan time.** §1 says 10×4 needs `nodehosts_per_az: 4` and gets
  0/10 colliding shards, with a caveat that its compiles went through the
  planner's AZ assignment and that "the knob conclusion holds under both
  formulas". Measured over `nodehosts_per_az` 1 to 16: under the decided §7.1
  policy the **run path collides at every value**, at 10×4 and at 40×4, so more
  fault domains never help. The cause is not the AZ formula alone - within an AZ
  the nodehost assignment strided by position in the ordinal-sorted list, and
  `_node_specs`, the semantic validator and the resource preflight all place
  every primary before every replica, so a shard's primary sits in the leading
  block and its same-AZ replicas in the tail. The planner interleaves instead,
  which is why its compiles were clean and a run's would not have been.
  `4f02c36e` walks an AZ a shard at a time where striding would collide, and
  after it the safe threshold is exactly `ceil((replicas+1)/AZs)` for both
  orderings - so §7.5's minimum is **sufficient as well as necessary**, which it
  was not. §7.1's "implemented by unifying on that formula, not by writing a new
  placement algorithm" is therefore false, and this was reported rather than
  improvised around.
- **`placement.py` is the one AZ decision now.** Four modules answered it
  independently, not the three the map named - `resource.py`'s
  `_preflight_replica_az` was a fourth copy. P1 (per-shard balance) and P2
  (global balance) hold **by construction**: a shard takes `replicas+1`
  consecutive AZ indices from its own, and consecutive residues cannot differ in
  frequency by more than one. That dissolves map §2.6 structurally rather than
  needing a better message.
- **`primary_replica_distinct_az` is renamed `shard_az_balanced`**, asserting
  P1. The precondition §7.1 set was checked first: `cluster_plan.json` appears
  in **no** view of `scripts/diff_stage_artifacts.py`. `cluster_plan.schema.json`,
  `scripts/assert_plan_constraints.py` and the planner tests moved with it.
- **§7.1's spot-check is wrong at three AZs.** The unified and old formulas
  diverge from shard 3 onward. It moves nothing - `_validate_network` admits
  exactly one AZ or exactly two - and it is pinned by its own test rather than
  left in prose. MR-1 was told to prove that identity with a test instead of
  carrying it, and the test is what found it.
- **The topology pin and the replica bound landed as designed.**
  `cluster-allow-replica-migration no` at `replicas_per_shard >= 2` only;
  `REPLICAS_PER_SHARD_ABOVE_MAX` unconditional and `REPLICAS_PER_SHARD_BELOW_MIN`
  only for real execution, naming the two replica-free shapes that still ship.
- **Map §4's "already r-generic" parts are now exercised** at four replicas -
  `redundancy_recovery` (which had zero tests), the affected-shard observer at
  four survivors, and formation at 6×4 and 10×4. Nothing there needed fixing;
  "already correct" was simply a claim nobody could check.

- **Proven:** `./gate suite repository.all` **92/92** at final HEAD
  (`gate-20260814T090309Z-f0d2240a`); catalog still **99**, M1 plan still **91**,
  pytest tree **824 → 845**. Every regression test mutation-checked - twelve
  mutations, each reverted and watched to fail. Two r=1 no-op proofs taken
  against the frozen baselines themselves rather than a second copy of the code:
  `_node_specs` plus `_process_nodehosts` reproduce both frozen runs'
  node-to-nodehost map exactly (**50 of 50**, **200 of 200**), and
  `_process_config_text` reproduces the frozen exact-50's
  `node_configs/shard-0000-primary.conf` **byte for byte**. Two consecutive real
  Docker exact-50, **PASS 894.81s** and **PASS 841.09s**: `run_verdict` 12/12 OK,
  `tool_errors` empty, cleanup 21 rows with `resources_remaining` empty, no
  `ERROR` in any artifact, zero residue asked of Docker from outside, fault lane
  **9/12/15**, RTO **48.96s** and **47.20s**. Marks `runtime_start` 7/7,
  `cluster_form` 5/5, `management_matrix` 6/8 with both inherited deltas at their
  declared shapes (+14 rows, `cluster_migrate_keys` 4 → 18, three kinds changed
  and fourteen unchanged) and no third, `cleanup` 2/2 - and **the two runs are
  identical to each other in every view of every stage**. `nodehost_density_plan`
  byte-identical to the baseline in both, and the topology pin in zero of the 100
  node configs.

**`fault_matrix` scores 4/6, not the 5/6 the task named, and that is not a
regression.** 5/6 predates the 2026-08-13 failover/RTO work in this branch, whose
own record above declares `fault_matrix` **4/6**, one new differing view.
Verified at field level rather than assumed: the second differing view differs by
**exactly one added key, `failover_timeline`**, that work's own declared
addition. Anyone citing 5/6 for a Docker exact-50 is quoting a pre-2026-08-13
number.

**What MR-2 inherits, compiled at this HEAD rather than remembered.** MR-2 is
map §8's second rung - one Docker **25×1-50 control** and two Docker **10×4-50**
candidates at the same commit, the three-way diff being the design. It needs
operator approval.

**MR-2 runs on Docker on the workstation, not on the GCE fleet, and the reason
is not only the one-variable-per-rung rule.** Its control *is* a Docker run, and
the in-VPC controller has no Docker daemon - that is exactly why
`repository.all` is 92/92 here and 91/92 there, the missing test being
`product.integration.docker_runtime_contract`. The baseline the control is
diffed against, `artifacts/baselines/exact-50-6b6f57fd/`, is a Docker run and
lives here; the native baselines are a different environment and live on the
controller. Running candidates on the fleet would split one three-way diff
across two machines and two baseline classes, which is what the design exists to
avoid. MR-2 changes the replica count and MR-3 changes the runtime; doing both
at once would leave any failure with two candidate causes, the same argument
that made M3-A-1 pick arm64. The failure MR-2 is watching for (map §3.1) is on
the backend-neutral failover path, so Docker surfaces it - and surfaces it in
~880s with no ssh, no eight-host residue check and no fd-limit wrapper, which
matters because it is the rung most likely to need re-running.

1. **The fleet arithmetic changed and the map's table is superseded.** Compiled
   through `validate_semantics`, `build_cluster_plan` *and* `_node_specs` plus
   `_process_nodehosts`, so the plan and the run agree:

   | shape | knob | nodehosts (plan = run) | per-AZ nodes | shards colliding |
   |---|---|---|---|---|
   | 25×1-50 control | shipped | 4 | 25/25 | 0 of 25 |
   | 10×4-50 | shipped (`nodehosts_per_az: 2`) | **6** | 25/25 | 0 of 10 |
   | 10×4-50 | `nodehosts_per_az: 4` | 8 | 25/25 | 0 of 10 |

   Both 10×4 forms validate clean and plan clean. The map's §1 row assumed 4/AZ
   was **required**; it is not. Which one MR-2 uses must be stated in its
   configuration rather than inferred, because it moves `nodehost_density_plan`,
   every `nodehost_id`, the fault matrix's targets and the cleanup row count.
2. **No multi-replica configuration exists anywhere.** Nothing under
   `templates/configs/` has `replicas_per_shard` other than 1, and MR-1
   deliberately wrote none - the first one is MR-2's. `real.local.full-flow`
   takes `nodes` and `config` and admits 30..200, so a 50-node multi-replica
   config needs no new catalog entry and no exception profile.
3. **The declared deltas, with the batch geometry now compiled rather than
   predicted.** The method reproduces the frozen baseline exactly (14 batches,
   max concurrent 4), so these are trustworthy:

   | quantity | 25×1-50 | 10×4-50 (6 nodehosts) | 10×4-50 (8 nodehosts) |
   |---|---|---|---|
   | rolling-restart batches, each operation | 14 | **13** | **10** |
   | max concurrent restarts | 4 | **6** | **8** |
   | `management_command_log` rows by map §5.1's law | 1602 (actual 1592) | **≈968** | **≈956** |
   | `cleanup_actions` rows (5×nodehosts+1) | 21 (measured) | **31** | **41** |
   | Sentinel `canary_count` = shard count | 25 (measured) | **10** | **10** |

   `add_replica`'s verify row `safe_path` becomes
   `"40_replicas_observed_replicating_for_10_primaries"` (map §5.2). r=4 RTO is
   a **new band with no prior**, and formation dwell under 4-way sync fan-in is
   measured against nothing.
4. **Map §3.1 is still the predicted intermittent failure and MR-1 did not touch
   it**, deliberately: the down-window full validation runs with
   `require_replica_connected=True` and `convergence_timeout=0.0`, exempting only
   the killed node. It is vacuous at one replica and meets three resyncing
   siblings at four. It is verdict-adjacent, so it belongs to the rung that can
   observe it - watch it first.
5. **Map §3.2's promotion-winner artifact is untouched and its §6 test was
   deliberately not written**, because it asserts a fix outside MR-1's scope: at
   four replicas `replacement_logical_id` names the predicted winner rather than
   the observed one about three times in four, with nothing failing.
6. **The planner and the runtime still order nodes differently** - the planner
   interleaves each primary with its replicas, the other three models block every
   primary first - so they assign different ordinals, and therefore different
   `client_port`s, to the same logical node. Pre-existing, predating all of this,
   and unobservable at one replica. Worth knowing because it is what made the
   map's compiles disagree with a run's, and because **the validator is the one
   that matches the runtime**, so where the two disagree about fault-domain
   safety the validator is right. Making them agree would move
   `cluster_plan.json`'s ports at one replica and is nobody's yet.
7. **Neither frozen baseline nor any `templates/configs/` file was touched**, and
   multi-replica runs are a **new baseline class** - not diffable against the
   one-replica baselines in `nodehost_density_plan`, `state`, the fault matrix's
   targets or `cleanup_report`. That is why MR-2's control run exists.

**The prerequisite the operator named on 2026-08-14: no one-primary-multi-
replica cluster has ever been run, local or native.** Every shipped config is
`replicas_per_shard: 1`. Measured the same day: a 10-shard ×4-replica exact-50
config is **refused at plan time** at shipped knobs -
`NODEHOST_DENSITY_PLAN: primary and replica for at least one shard share a
nodehost fault domain` - because 2 nodehosts per AZ cannot hold a shard's four
same-AZ replicas. The predicate (`_primary_replica_nodehost_safe`) is stricter
than its message: *every* member of a shard must be on a distinct nodehost.
With `runtime.nodehosts_per_az: 4` the same config validates and plans - 8
nodehosts, 6-7 nodes each, 0 of 10 shards colliding - so the smallest native
multi-replica exact-50 needs **8 hosts, exactly the gce-m3b fleet as
provisioned**, and its Docker form runs locally with 8 nodehost containers. 50
nodes is under the 100 cap, so no exception profile is needed on either
provider, and the existing `real.local.full-flow`/`real.ecs.full-flow` entries
take the config as a parameter. A **40×4 = 200** shape also plans at shipped
knobs in the Gate's own capability context (measured through
`build_cluster_plan` with `local_full_flow`/`local_full_flow`, since the bare
`cli plan` refuses every 200-node config including the unmodified `scale_200` -
the bounded exception only applies in that context): 8 nodehosts, exactly 25
nodes each, 0 of 40 shards colliding, and `_is_exact_200_bounded_exception`
carries no shard-shape term - so the existing eight-host fleet holds a
multi-replica exact-200 with no knob change. Two cautions: the changed knob moves
`nodehost_density_plan`, every `nodehost_id`, the fault matrix's targets and
the cleanup row count, so multi-replica runs are a **new baseline class**, not
diffable against the frozen 1-replica baselines in those views; and while
nothing is known to hardcode one replica (`redundancy_recovery` and the
failover observer compute `expected_replicas_per_shard` from the shard's own
membership), nothing has ever exercised more than one, and this project's
record is that only runs find the defects.

*(Superseded 2026-08-14, kept for the knobs and the deviation-rule shape.)*
Compiled at HEAD against `real_ecs_200.yaml`'s
shipped knobs (`nodehosts_per_az: 2`, `max_logical_nodes_per_nodehost: 25`,
`max_nodehosts: 64`), one nodehost per host:

| nodes | nodehosts = ECS hosts | per host |
|---|---|---|
| 500 | **20** | 25 |
| 1000 | **40** | 25 |
| 2000 | **refused** - 80 nodehosts exceeds `max_nodehosts: 64` | - |

So **exact-2000 cannot be planned at all today**, and it fails at plan time
rather than at run time. Raising the density knob is the obvious escape and is
not free: it moves `nodehost_density_plan`, every node's `nodehost_id`, the fault
matrix's targets and the cleanup row count, so M4's baselines would differ
*structurally* from every M3 baseline they would be compared with. **This is an
operator decision before provisioning 20 to 80 hosts**, and by the roadmap's own
deviation rule it should be reported rather than improvised around - the same
shape as item 0.7's finding, which is why it is written down before M4 starts
rather than discovered inside it.

M4 also has a registered check on 1 of its 7 criteria; the question §1 of
`m3_acceptance_registration_map.md` answers for M3 has to be answered again
there, and its answer will be different, because no M4 run exists to be the
check.

**The recommended next piece, if a small one is wanted first:** node journals on
a mid-lifecycle failure (`cross_host_evidence_slice_map.md` §10.2). It is the
half of the failing-run item that was deliberately deferred on 2026-08-13, the
failures it helps most are cluster-formation ones, and that is precisely the
class M4 will produce. It needs an induced real failure to prove, so it is its
own item with its own evidence.

Carried forward untouched from item 1.6 and earlier, none of it this item's:
`run` not classifying a transport failure, a native run's command audit recording
no ssh, whether the preflight should validate the document the run uses, the
92/92 suite not reaching `_process_runtime_state`'s call site, the aborted
controller's ssh masters, the resource-to-timeline monotonic correlation, a
failing run collecting no journals, the absent fault-path ownership check, the
missing `signalled` count, `SamplerSpec`'s duplication, `_state_nodehost`
dropping `remote_bundle_dir`, and why the health-gate escalation inverts with
scale. Note "a failing run collecting no journals" is now the *only* remaining
half of that item, and it is better characterised than it was - see the §12.2
paragraph below.

### Failover/RTO observability was made M4-ready, 2026-08-13

**Not a roadmap item**, taken before M4 on the operator's instruction. Three
commits, `5c8d3cb0` through `85a841de`, each verified in its own worktree so the
series bisects. Read `project/docs/failover_timeline_slice_map.md`: §1 is why the
observation points a reader expects are not the ones a real run uses, §5 the
conformance defect, §5.2 the correction that matters, §7 the metric definitions,
§9 the deltas declared in advance, §10 the proof.

**The reason this existed at all.** M3 reported one number per run - RTO ~52.5s -
and that number cannot rank cluster sizes. Reconstructed over **74 retained
runs**, detection is flat in node count (median 44.07s / 44.16s / 43.02s at
30 / 50 / 200) while the control-plane term grows with it (2.53s / 3.80s /
8.05s), and detection *jitter* alone (30.4-46.0s) is wider than the whole
control-plane term. On the real fleet the same split from the frozen baselines:
**aggregate RTO moves about 6% between exact-50 and exact-200 while
PFAIL→promotion moves up to 7.6x** (2.50-6.50s against 8.00-19.03s).

- **The eight observation points a reader will find by grepping are the wrong
  ones.** `observer/failover_timeline.py`'s `REQUIRED_TIMESTAMPS` is M2 machinery
  driven by two `scripts/` entries and **never runs on a real full-flow run** -
  `analysis/summary.py` imports three constants from it and derives no timestamp,
  and none of those names appears in a real run's `analysis_summary.json`. The
  real path is `_run_scalable_primary_kill_failover`, backend-neutral, identical
  on both backends.
- **Nothing new is collected.** Every affected-shard round already carried its
  full `CLUSTER INFO`; the timeline was always reconstructible and simply never
  derived. Which is why the frozen baselines could be re-read retroactively - and
  should be, before any M4 comparison, rather than re-run.
- **Two emitted pairs were each one number twice.** `promotion_latency_ms` was the
  round §9.3's two-round rule completed, measured to overstate first observed
  promotion by **0.501-0.519s, median 0.508s, never zero, in all 74 runs**, and
  was byte-identical to `cluster_recovery_latency_ms`. `write_unavailability_ms`
  was the read canary's number under a write name.
- **The Sentinel probe violated three design statements**, so fixing it needed no
  approval. §7.6 budgets it at ~20 GET/s "与集群节点数无关", §14 at O(1), §16 item
  8 at a 100ms period; `ClusterRouter.get` walked every primary, costing one
  connect and one GET each - measured 1000/999 per lookup at 1000 primaries. Now
  **2 connects and 3 commands at every size**.
- **The cadence loss is environment-dependent, and the first reading of it was
  wrong.** 194ms at exact-200 is Docker on a laptop. On the fleet the median was
  always ~100ms; the **tail** was the defect - p99 **1098ms**, 9-11 rounds per run
  over 125ms, which is the 1.0s connect timeout reached because the dead node was
  dialled ~100 times per lookup. Candidate exact-200: p99 100.18ms, max 100.21ms,
  **zero** rounds over 125ms. That tail *was* the RTO's quantisation error.
- **Two points are declared unmeasurable rather than omitted.** `first_fail` is
  circular - `cluster_nodes_fail` is read from the surviving replica, which sets
  it as it promotes itself, and the two land in the same 500ms round in **72 of
  74 runs**. `first_cluster_ok` never transitions from this vantage. Neither is a
  cadence problem; both need a primary-side observer, which §7.6 and §9.2 do not
  give this lane.
- **Two decisions were settled by the design, not by taste.** The 500ms
  affected-shard period stays: §9.2 mandates it and §16 acceptance item 9 pins it,
  so `pfail_to_promotion_ms` is bounded at ±1000ms and says so in `precision_ms`.
  No write probe: §7.3 forbids Sentinel writes inside the formal window outright.
- **`failure_to_client_recovered_ms` equals the legacy `rto_ms` in 74 of 74
  runs**, so M3's frozen results stay comparable with M4's.

- **Proven:** `repository.all` **92/92** (91/92 on the controller, the absent
  Docker daemon); pytest **824** measured at this HEAD, of which 9 are this
  work's - they joined a module the catalog already registers, so **catalog stays
  99 and the M1 plan 91**. Two Docker exact-50, **PASS 868.82s and 944.98s**, and
  native **exact-50 PASS 839.72s** and **exact-200 PASS 1510.33s** on the eight
  GCE hosts. All four: `run_verdict` 12/12 OK, `tool_errors` empty, fault lane
  **9/12/15** with nine `REAL_PASS`, no `ERROR` in any artifact, cleanup with
  `resources_remaining` empty, 200/200 journals at exact-200, and zero residue on
  all eight hosts asked over ssh from outside the product. The declared delta held
  exactly at both scales on both backends - `fault_matrix` **4/6**, one new
  differing view, nothing else moved - and the two Docker runs are **identical to
  each other in every view**, including both that differ from the baseline.
  Behaviour did not move: Docker RTO **47090.555ms against the baseline's
  47093.83ms**; native control plane 4.00s and 9.01s, inside baseline ranges.
  **The baselines were not re-frozen.**

**Three defects this work's own runs found in this work's own code**, none
visible to reading: a rounding comparison that made a round precede itself and
reported 511ms of topology recovery that never happened; an overrun counter that
fired on 438 of 438 intervals because a healthy probe sleeps off its period; and
a doc line tripping the execution-axis contract, which forbids the bare word
"phase" outside the compatibility boundary. **A mutation check then found the
test for the first one did not detect it** - reverting the fix left the suite
green, because the synthetic fixture used offsets where rounding never shifts the
comparison. All three mutations are detected now. Run the mutation check, not
only the suite.

**What this leaves for M4, and it is planning rather than code.** exact-200's
control-plane spread is **8.0-19.0s against exact-50's 2.5-6.5s**, so **one run
per rung cannot separate 500 from 1000** - budget several per rung or the
comparison will not survive its own variance. This is independent of, and
additional to, the `max_nodehosts: 64` arithmetic below.

Added to the open list, none of it this work's to close: topology propagation is
**not measured at all** (it needs the second vantage point that was out of
scope); `first_fail` is declared unmeasurable rather than fixed; sharpening
`pfail_to_promotion_ms` below ±1000ms needs a **design amendment to §9.2**, which
is the operator's call and not a session's; and the rolling-restart handoff path
at `docker_runtime.py:11377` still assigns one value to both
`promotion_latency_ms` and `cluster_recovery_latency_ms` - reported rather than
fixed, because it is a different scenario and the rule is not to broaden a fix.

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
   so. The protocol was frozen at twenty-three operations for item 1.2, which
   implemented the whole of it; item 1.3 then argued it to **twenty-four**, and
   twenty-four is the current count. A later slice may argue it further, with its
   own evidence - no stale count from an older section applies.
3. ~~**Decide `fault/sandbox.py`.**~~ **Decided 2026-08-10 and deleted the same
   day.** What decided it was not the duplication: `apply_fault` accepts seven
   fault types and **six of them inject nothing and record `status: PASS`** -
   re-measured before the deletion at 0 runtime commands each, against
   `node_stop`'s four. So a second backend owes this nothing. The module, the
   `cli fault apply`/`clear` surface, `_remove_fault_state_files` and three
   catalog tests are gone; `docs/fault_sandbox_decision_memo.md` §7 is the
   record. **`repository.all` is 88 tests, not 91**, from this commit on.
4. ~~**Confirm the ECS hosts exist.**~~ **Done 2026-08-12**: eight
   `c4a-standard-2` GCE hosts plus an in-VPC controller, and item 1.6 has run the
   whole ladder on them. ~~Five of six criteria have their evidence; none has a
   registered check yet, which is item 1.7's.~~ **All six carry executable checks
   as of item 1.7, and `./gate milestone m3` is PASS.**

Also, and easy to miss: **M3 had a registered check on 1 of its 6 criteria and
now has one on all six; M4 still has 1 of 7.** A milestone whose criteria have no
attached checks reports `DEFINED` and can never report `PASS`, so each criterion
needs a real Test registered in `catalog.json` as it becomes executable. No
placeholders - and see the M3-B-2 section for what "no placeholders" cost to
honour, which was a measurement rather than a rule.

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
with literal `PASS` on the artifact and on all twelve step rows.

**"Every artifact a failing run leaves says `PASS` or is absent" was measured
again on 2026-08-13, against six real failed runs from item 1.6, and it is now
wrong in one direction and was right for a reason it did not state.** A run that
dies *in* the lifecycle is not silent: `run_verdict.json` is written before the
raise and carries `FAIL`/`BLOCKED` plus a `stages_not_run` row per skipped stage
with the real message, e.g. `fail-fast after runtime_start:
_process_runtime_state() got an unexpected keyword argument 'fleet_hosts'`. What
that run still lacks is node journals (zero, on a run whose nodes had logs on
their hosts - `cross_host_evidence_slice_map.md` §10.2) and the timeline above.

The sentence was exactly right for a different case, which nobody had named: a
run whose twelve stages **passed** and whose evidence was then **refused**.
Measured on `gate-20260812T101014Z-c2bccc21` - Gate `FAIL`, and inside the run
`run_verdict.json` PASS 12/12 OK, `lifecycle_timeline.json` PASS 12 steps,
`cleanup_report.json` PASS. That mattered more than the missing journals because
**freezing a baseline copies a run directory**, so such a run is
indistinguishable from a passing one from the inside and could be frozen. Fixed:
admission is now recorded as a **check** in `run_verdict.json`, so `final_verdict`
decides the aggregate with the precedence it already implements - semantic
refusal `FAIL`, unreadable evidence `ERROR` - while the stage checks keep their
own results, because those stages did pass. `lifecycle_timeline.json` is
deliberately left alone for the same reason. Two hermetic tests, both measured
to fail without the change with exactly the wrong symptom, `PASS` where
`FAIL`/`ERROR` is expected.

The change is on every real run's path, so it was proven there too:
`repository.all` 92/92 and **`./gate milestone m3` PASS 8/8 again** at
`940efa13` - exact-50 836.01s, exact-200 1414.44s, exact-50 862.69s. All three
runs' `run_verdict.json` are **identical to the three taken before the change**:
`status` PASS, `gate_status` PASS, checks 12/12 OK, **no `admission` check**,
`tool_errors` empty. Fault lane 9/12/15 with nine `REAL_PASS` in all three, no
`ERROR` in any artifact, and zero processes and zero `vslab` firewall rules on
all eight hosts asked from outside. A passing run passes no extra checks, so the
new code path is a no-op there - argued from `checks.extend(())` and then
measured on three real runs rather than left as reading.

Two smaller sites from the map are also still open: the bounded waits
(`_wait_process_light_clean`, `_run_timed_step`) label a `CollectionError` `FAIL`
in a sticky timing row; and the Sentinel fault-window samples label a transient `FAIL` where the
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
- **No fault path checks ownership.** Measured 2026-08-10 while pricing the
  `fault/sandbox.py` deletion, and true since it landed: `_require_owned_container`
  inspected a container's labels and refused if they were not this run's, and it
  was the only such check on any fault path - the seam's own actuator has none.
  `kill_node` reads `nodehost_container_name` off the node and execs. So the one
  test of M1's phrase "confined to project-owned resources" went with the module.
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
  current. **Done for the native backend in item 1.4**, which terminates what
  `/proc` says is running out of the run's tree and never a pid it was told
  about. **Still true of the Docker backend, and still correct there**, because
  `docker rm -f` is the backstop; it was not changed, which is why item 1.4
  moved no diff view. A later session that makes the two paths agree should know
  it would be changing `cleanup_report` on the Docker path, with the artifact
  evidence that implies.
- ~~**No node log is ever collected.**~~ **Done in item 1.3.** Every node's
  `valkey.log` is now pulled once, at the last boundary where it is complete and
  still on its host, into `runtime/node_journals/<host_id>/<logical_id>.log`.
  Measured at exact-50: 50 of 50, ~155 KB per node, ~7.8 MB and ~1.1 s per run.
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
  `./gate suite repository.all` green at its current count before committing -
  **92 as of M3-A-3**, 91 after M3-A-2, 90 after M3-A-1, 88 before it - and run two consecutive
  real exact-50 runs after any change a real run reaches. Two of the Gate's own
  contract tests pin the catalog and M1 plan counts
  (`verification/tests/test_contracts.py`), so registering a test moves three
  numbers, not one: the catalog is **99** (96 before M3-B-2's three `real.ecs.*`
  entries) and the M1 plan **91**. Adding checks to a module the catalog already
  registers moves none of them, which is how M3-A-4's twelve and this failover
  work's nine landed.
- Run the mutation check, not only the suite. A new test that passes proves
  nothing until the fix it guards is reverted and the test is watched to fail:
  the 2026-08-13 failover work wrote a regression test for a rounding defect
  whose fixture could not express the defect, and only the reverted-fix run
  exposed that.
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
- **`scripts/ecs_gate.py` `execv`s into the CLI**, so once a run starts nothing on
  the controller matches `ecs_gate.py` any more - watch for
  `valkey_scale_lab.cli gate execute` instead. A watcher that greps the wrapper
  name reports "finished" immediately. Measured 2026-08-13, and it is also why a
  remotely launched run needs `setsid nohup ... < /dev/null &`: a run started
  without it was killed when its ssh session went away, mid-flight, leaving 25
  `valkey-server` per host. `cli gate cleanup --state <run>/state.json` took all
  eight hosts back to zero processes and zero `vslab` rules.
- The execution-axis contract (`scripts/assert_execution_axis_contract.py`)
  forbids the bare word **"phase"** anywhere under `docs/`, `src/`, `scripts/`,
  `tests/` and the other scanned roots, outside a named compatibility list. It is
  easy to trip in prose; it costs a full-suite run to discover.
