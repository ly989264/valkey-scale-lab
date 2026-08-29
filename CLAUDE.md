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

The session-by-session record moved to `SESSION_HISTORY.md` on
2026-08-20, when this file reached 253 KB and was being loaded into every
session's context in full. Nothing was edited in the move. **Read that file for
derivation** - why a decision was taken, what a measurement showed, which claims
a later session corrected. **This section is what is true now.**

Where the two disagree, this file is the later word; where either disagrees with
source, **source wins and you say so**.

### Current state

**M3 is closed.** `./gate milestone m3` is PASS 8/8 with `definition_status:
READY`, on `fast-iter`. **M4 is in progress and its goal is one target, not a
ladder: 256 primaries with 4 replicas each, 1280 valkey-servers.** The
multi-replica prerequisite program (MR-1 through MR-3) is done.

**M4's definition is now `READY` and its acceptance is FAIL, and both are
correct.** Six Criteria, every one with Checks. The four that do not need a fleet
are green - exact-scale compilation and the named exception, the target shape's
placement, and the run's own report rendering. The three that do are the 1280-node
observation, its evidence at that scale, and reclaim on the operator's fleet, and
they are what keeps it red. READY is computed from whether every Criterion has a
Check and says nothing about passing.

**`./gate milestone m4` on a controller with a live manifest spends money.** Two
of its Checks carry `--operator-opt-in` and `--cost-acknowledged` in their own
argv. This is deliberate - the acceptance *is* the run - and it is stated in
`milestones/m4/README.md` and `docs/fleet_operator_runbook.md` §11.

**The procedure is executable rather than remembered, and it is
provider-neutral.** `docs/fleet_operator_runbook.md` is the whole thing for an
operator with no help and no fleet; `scripts/fleet_run.sh preflight|start|watch|abort`
runs it in order and refuses at the first failure. `templates/configs/scale_1280_native_ecs_optin.yaml`
now names a 32-host fleet the operator supplies - three lines are theirs
(`host_inventory_path`, `native_bundle_dir`, `nodehosts_per_az`) and **none of them
is a clause of the guard**, so retargeting a fleet is a data edit and not a code
change. `profile_name` still is the guard and must not be touched.

**The correct state between items is idle.** Each item begins on operator
approval, never as a next step.

**Operator decision, 2026-08-13: there is no merge to
`origin/codex/valkey-scale-lab-loop`; M4 is developed on `fast-iter`.** Do not
re-raise it. M3's acceptance is therefore green on `fast-iter` rather than on a
merged default branch, which is the operator's call and recorded rather than
argued.

**`fast-iter` is pushed to `origin` and tracks it, since 2026-08-29.** The
"nothing is pushed" that used to sit here is no longer true and was removed rather
than reinterpreted. The no-merge half of the decision is untouched: the branch
exists on the remote and is 241 commits ahead of
`origin/codex/valkey-scale-lab-loop`, which is where it stays until the operator
says otherwise.

### The fleets, and what is available

- **The 32-host Huawei fleet is SUSPENDED by the provider for cost.** Assume you
  have **no fleet**. Local Docker is the verification vehicle and is free.
- **Do not propose, prepare or start a paid run without asking first.** Five paid
  1280-node runs were each spent finding one defect. The rule that leaves: state
  the expected number of runs before the first, and when one fails **audit the
  defect's class** rather than relaunching.
- The earlier GCE fleet `gce-m3b` was twelve `c4a-standard-2` (arm64, Ubuntu
  26.04) plus an in-VPC controller. **Run a gate from the in-VPC controller,
  never from a workstation**: transport is 5.1 ms median in-VPC against 110-116 ms
  from a laptop, and a baseline frozen with that in it could never be reproduced.

### What 1280 nodes actually needs, measured

- **A 1280-node cluster forms and is healthy on 32 x (8 vCPU / 16 GB)**:
  `cluster_state ok`, 1280/1280 known, 256 primaries, gossip converged in ~56 s,
  zero OOM. The GCE wall was **107 nodes on 2 vCPU**, not the product.
- **The cluster bus is a full mesh**, so per-host bus sockets are quadratic in
  fleet size and only linear in density - which is why every density experiment
  missed it. 10,800 sockets at N=200/25-per-host against **223,622** at
  N=1280/107-per-host, and 2.80 GiB of kernel TCP memory against 11-58 MiB.
  `ecs_host_verify.sh --nodes-per-host N --fleet-nodes M` now derives the ceiling
  from `2 * N * (M - 1)` sockets at 4 KiB + 4 KiB and **refuses** a host whose
  `net.ipv4.tcp_mem` cannot hold it, so the checklist line that said to read the
  value back by hand is a check rather than a habit. It refuses only when
  `--fleet-nodes` is given, because one host cannot know the fleet.
- **`node_memory_limit_mb` is a dataset cap and does not bound the process.** A
  node holds per-peer bus buffers, so RSS grows with **fleet size**: 10.5 MB
  steady per node at 200, peaks of 52-110 MB at 1280.
- **`cluster-link-sendbuf-limit` is back at 1048576 and the knob is not the
  lever.** At 32 KiB both failure modes appeared at once - tens of thousands of
  link frees *and* memory exhaustion - so no value fits 1280 nodes on twelve
  2-vCPU hosts. Its floor is one whole gossip message: 4.25 KiB at 200 nodes,
  **15.20 KiB at 1280**.
- **The gossip cost curve has a knee** at ~150 peers: 5,920 / 8,567 / **30,915**
  bytes per second per node at N=50 / 100 / 200. The `cluster_node_timeout_ms`
  lever is **2.1x, not 4x** - 30 % of gossip is timeout-independent.
- **60 s is the measured ceiling for `cluster_node_timeout_ms` and 120 s breaks
  the fault lane**, because the Sentinel canary recovery deadline is a hardcoded
  **180.0 s**. At 60000 RTO is ~95 s; at 120000 it lands near 190 s and fails.
  The 1280 config takes 60000; every other scale keeps 30000.
- **Aborting a 1280-node run does not relieve the fleet.** The bus is
  peer-to-peer, so unmanaged nodes carry on and the heaviest link-freeing was
  sampled *after* the controller died. The correct sequence is **kill, then
  immediately `cli gate cleanup --state <run>/state.json`** - not kill and observe.

### The frozen baselines, and the delta shape a candidate must match

Docker, on the workstation:
`project/artifacts/baselines/exact-50-6b6f57fd/` (two passing runs, every stage)
and `exact-200-6b6f57fd/` (two runs, both failing downstream, so it covers
`runtime_start` and `cluster_form` only).

Native, frozen at `c58a762a` and living **on the GCE controller** because the
workstation cannot reach that fleet: `real-exact-50-c58a762a/` (97 MB) and
`real-exact-200-c58a762a/` (457 MB). Their invocation requires `ulimit -n 65536`.

**Calibrate before trusting any result.** Diffing the two Docker baseline runs
against each other must report **7/7, 5/5, 8/8, 6/6, 2/2**. A normalisation loose
enough to hide their differences would hide a regression too. Run it with
`./scripts/diff_stage_artifacts.py --stage <stage> BASELINE CANDIDATE`.

**A current Docker exact-50 candidate scores `runtime_start` 6/7, `cluster_form`
5/5, `management_matrix` 6/8, `fault_matrix` 4/6, `cleanup` 2/2.** Check the
*shape*, not equality:

- **`management_matrix` 6/8 has three declared components** since `713d96e8`, and
  a diff showing only some of them is as much a finding as one showing a fourth:
  1. `ded96fac` drains a slot before reassigning it - **+14 rows,
     `cluster_migrate_keys` 4 -> 18**, with matching `command_count` growth
     (1051 -> 1058).
  2. `313cacc9` renamed the record that discards a node's prior state - **exactly
     four rows** change `command_kind` and gain an RDB path in `argv`. A rename
     moves no rows, so the count stays +14.
  3. `713d96e8` migrates with `REPLACE` - **every `cluster_migrate_keys` row
     differs in `argv`**, the four the baseline had as well as the fourteen added.
     The score does not move; the rendering gains 5 `REPLACE` insertion lines.

  Together: **+14 rows, three row kinds changed and fourteen unchanged, and every
  migrate row carrying `REPLACE`.** This supersedes every earlier statement of
  the shape; older documents are accurate records of *their* runs and are not
  edited.
- **`fault_matrix` 4/6** is the pass mark. 5/6 predates the 2026-08-13
  failover work, whose declared addition is one new differing view containing
  exactly the added key `failover_timeline`. Anyone citing 5/6 is quoting a
  pre-2026-08-13 number.
- **`management_matrix` does not self-calibrate on the native baselines** and
  cannot: the health-gate retry record inside `stdout_tail` and
  `errors_observed_during_operation` are genuine per-run observations. Judge a
  candidate on the other views and the field-level delta.
- **A multi-replica run is a new baseline class** and cannot be diffed against
  the one-replica baselines in `nodehost_density_plan`, `state`, the fault
  matrix's targets or `cleanup_report`. At r>=2 `fault_matrix` also cannot
  self-calibrate, because two runs elect different replicas.

**Calibration alone is not enough.** Seed plausible regressions into a copy of a
baseline and require the view that owns each to report it - a normalisation that
calibrated perfectly once hid a probe pointing at the wrong command. And **two
runs agreeing is not proof a field is deterministic**: that has now caught four
fields, most recently `errors_observed_during_operation`.

**Do not re-baseline after a change**, or drift accumulates one change at a time
with no single diff ever showing it.

### Numbers that hold across runs, and what would make one a finding

- **The fault lane emits 9 scenarios / 12 command rows / 15 workload windows at
  every scale** - 30, 50, 200, 1280 - on both backends and at every replica
  count. Any change to these three is a finding.
- **Primary-kill RTO**: exact-50 **45-50 s**, exact-200 **47.6-53.8 s** and
  overlapping it, so one exact-200 above 50 s is dispersion rather than
  regression - a shift in the whole spread would be the finding. All measured at
  `cluster_node_timeout_ms: 30000`; **at 60000 the band is ~95 s** and no prior
  number transfers.
- **Rank on the split, never the aggregate.** Detection is flat in node count
  while the control-plane term grows with it. Measured on one workstation
  afternoon: exact-200 RTO 51.05 s against exact-50's 47.82 s (**+6.7 %**) while
  `promotion_latency` was **10.19 s against 1.53 s (~7x)**. One run per rung
  cannot separate cluster sizes; budget several.
- **Formation dwell** is bounded by a 240 s no-progress window with an 1800 s
  ceiling. It is **not scale-free** and must be re-measured before 500 nodes and
  on any new backend. exact-200 has formed in 10.9-205.8 s across environments.
- **Counts**: `repository.all` **92**, catalog **100**, M1 plan **91**, pytest
  tree **957**. Two contract tests pin the first three, so **registering a test
  in `catalog.json` moves three numbers, not one**; adding tests to a module the
  catalog already registers moves none - which is why M4's placement work and its
  milestone rewrite moved only the tree, and attaching an already-registered entry
  to a Criterion moves nothing at all. **Those same two contract tests also pin
  each milestone's `definition_status` and the exact ordered list its Criteria
  expand to**, so changing a milestone's composition fails `gate.contracts`
  without moving any of the three counts - which is how M4's rewrite was caught. `repository.all` is **90-91/92 on the
  in-VPC controller** - the absent Docker daemon, and a checker that can fail by
  chance on run output.

### Traps that have each cost a session

- **A six-node smoke cannot reach `management_matrix` or `fault_matrix`**, for
  three independent reasons: the Gate declares `minimum: 30`, the scenario
  declares `min_nodes: 30`, and `fault_matrix`'s AZ selection raises a bare
  `StopIteration` at six. **exact-30 is the smallest real run that exercises
  either stage.** Do not plan a failure case around exact-6.
- **The GCE fleet boots from instance metadata, not the committed script.** The
  startup script rewrites `/etc/sysctl.d/90-valkey-scale-lab.conf` nine seconds
  after every boot, so editing `ecs_host_prepare.sh` does not reach a running
  host and any hand-applied tuning is reverted by the next reboot.
- **`scripts/ecs_gate.py` `execv`s into the CLI**, so nothing matches
  `ecs_gate.py` once a run starts - watch for `valkey_scale_lab.cli gate execute`.
  A remotely launched run needs `setsid nohup ... < /dev/null &`, or it dies with
  its ssh session mid-flight.
- **The execution-axis contract forbids the bare word "phase"** anywhere under
  `docs/`, `src/`, `scripts/`, `tests/` and the other scanned roots, and rejects
  a **filename** matching a milestone and stage number joined by a separator.
  Both cost a full-suite run to discover. Check a new doc's *name* as well as its
  text.
- **`repository.all` is dominated by one check scanning generated output**:
  `artifacts/` holds ~627k files against ~698 in every source root, and
  `assert_execution_axis_contract.py` scans it - about 12 minutes of every
  20-minute cycle, growing with every run taken on the machine. It can also fail
  **by chance** on a base64 histogram in run output, so `repository.all` is not
  deterministic on a machine that has taken a run. Narrowing it is a
  validation-contract change and the operator's call.
- **Ad-hoc python needs `PYTHONPATH=src`**; an import failure there is a path
  problem, not a code one.

### The report a run produces

A gate run now **renders its own report in every language it knows**, one
directory each: `<run>/runtime/report/` is Chinese and `<run>/runtime/report-en/`
is English. Each is 40 files: `index.html`, `report.md`, 22 CSVs, 11 SVGs,
`report_index.json` and `renderable_analysis.json`. Both are entirely offline and
generated by this project's scripts; `scripts/assert_zh_offline_report_contract.py`
rejects any external URL, CDN reference or bare `//` **in either** - it takes
`--lang` and reads its required section list from the message catalog rather than
keeping a second copy. Reproduce one with `cli report --kind full-flow --lang en`.

**The language chooses sentences and nothing else.** `report/messages.py` is the
only place either language is written; the `zh` side is copied verbatim from what
the renderer used to emit, so a Chinese report is **byte-identical** to what every
frozen run carries - checked against a real one, 35 of 35 files. Same file names,
same figures, byte-identical data-only CSVs across the two.

**`lang` reaches the adapter as well as the renderer**, because the reason an
absence states is written in `full_flow.py` and is prose a person reads. The
analysis records `language`, and rendering one language's analysis in the other is
**refused** rather than producing a half-translated page; an analysis from before
that field still renders.

The renderer is a **reader, not a second analyzer**: every number is lifted from
an artifact the run already validated, because a report that recomputed its own
figures could disagree with the evidence it summarises. **An absent source states
its reason** - never a zero, never an estimate.

Two absences are structural and appear in every report: **per-node ready times**
(the lifecycle records no per-node timestamp) and **per-node resource ranking**
(resource observation aggregates per sampler). Do not "fix" either by
approximating from a stage total. `git_sha` and `valkey_version` are likewise
recorded nowhere a full-flow run can reach.

**One thing to check when reading a fault report**: the nine scenarios each
report their own duration and their client-outage fields say `MISSING` with a
reason. `failover_details` is a *single* measurement from the primary-kill lane,
and an earlier draft copied it onto all nine rows. **If a report ever shows nine
identical outage values, that regression is back.**

### What is still open

None of these is anyone's current item; each needs its own evidence.

**Reporting and evidence**
- The report's `run_id` is configuration-derived and **identical in every run**,
  so two reports cannot be told apart by it - only `artifact_root` distinguishes
  them. Changing it moves a field every frozen baseline carries.
- The analysis summary's retry counters derive from `retry_index` over
  `command_log.jsonl` - the command *audit* - so a management or fault re-issue
  is **invisible** to them.
- Neither backend records its observation volume in its own evidence, and a
  native run's command audit records **no ssh at all**, which is an
  evidence-parity gap between two backends meant to be comparable.
- Nothing in a run's evidence records process RSS or kernel socket memory, which
  is why every measurement of the 1280-node wall came from outside the product.
- A failing run collects **no node journals** and writes no lifecycle timeline.
  The failures it would help most are cluster-formation ones, which is the class
  M4 produces.
- No run can answer whether the fault actuator signalled anything: the record
  keeps the action string, not the `signalled` count.

**Retry and classification**
- `_retry_read` still catches a broad `except Exception`, so it retries error
  replies - now inconsistent with the mutation chokepoint beside it, which makes
  the distinction.
- `HostTransport.run` returns every ssh failure as `CommandResult` rc 255,
  including an unreachable host, so a transport failure is not classified there.
- `MIGRATE` retry meets `-BUSYKEY` in the dual-residence sub-case and still
  raises; `REPLACE` is issued but that reply is an answer, not a transport
  failure.

**Runtime and cleanup**
- An **aborted controller's ssh masters** survive `SIGKILL` and cannot be
  reclaimed by anything afterwards - nothing on either side says which run a
  session belongs to. Bounded by `ControlPersist=600`.
- **No fault path checks ownership.** Accepted by the operator 2026-08-10; the
  run mark on the actuator's rules records whose a rule is without making
  `isolate_nodehost` refuse a host that is not this run's.
- The Docker backend still terminates by pids from `state.json`, which are stale
  by cleanup time; `docker rm -f` is the real backstop. Correct there, and the
  native backend was fixed instead.
- `_state_nodehost` drops `remote_bundle_dir`; nothing needs it now that the path
  is derived.
- `SamplerSpec` in `node_backend.py` duplicates the Docker backend's private
  `_AgentSamplerSpec`.

**Observation and analysis**
- The resource-to-timeline correlation compares two unrelated monotonic clocks,
  so a run's `network_error_or_drop_overlap_count: 0` means no overlap is
  *expressible*, not that none was observed.
- **Why the rolling-restart health-gate escalation inverts with scale** is
  unexplained: it fires at exact-30 and exact-50 and never at exact-200, where
  more nodes should mean more chances to find something unhealthy.
- Topology propagation is **not measured at all**, and `first_fail` is declared
  unmeasurable rather than fixed - both need a second vantage point.
- The rolling-restart handoff path assigns one value to both
  `promotion_latency_ms` and `cluster_recovery_latency_ms`.
- Whether the preflight should validate the document the run uses rather than the
  profile's template - a safety guard reads that document, so it is the
  operator's call.
- The 92/92 suite does not reach `_process_runtime_state`'s call site with its
  real signature: a wrong keyword there passed the whole hermetic suite and was
  caught by three real runs in ten seconds each.

**Placement, at r>=2 only**
- The planner and the runtime order nodes differently, so they assign different
  ports to the same logical node. Unobservable at one replica; the validator is
  the one that matches the runtime.

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
