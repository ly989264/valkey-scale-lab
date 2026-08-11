# Roadmap preconditions: completion report

Roadmap revision 5.1's precondition list — items 0.2, 0.3, 0.5 and 0.6 — is
complete, and this is the report its exit gate asks for. Exit HEAD is
`5d260c7e`.

A naming note, because the mismatch is otherwise confusing: the roadmap calls
this block of work by a word that `scripts/assert_execution_axis_contract.py`
rejects anywhere under `docs/`. This file says "the precondition list" instead.
Same thing.

The list executed as three worker sessions with fixed boundaries. Sessions A and
B are recorded in CLAUDE.md and in `seam_completion_slice_map.md`; session C
executed the approved `fault/sandbox.py` deletion and then this gate.

---

## 1. The gate, and what it measured

The roadmap's exit gate has five conditions. All five are met.

| Condition | Result |
|---|---|
| 0.2, 0.3, 0.5 each landed on its own evidence | `ce0bea2d`, `3315e6af` + `e04d6ce9`, `4f54442a` |
| 0.6 decided — memo plus operator answer | `ff4e4f21` memo, option A approved 2026-08-10, executed at `5d260c7e` |
| Suite green, including whatever 0.5 registered | **88/88** `./gate suite repository.all` at exit HEAD |
| Two consecutive real exact-50 PASS | **889.45s** and **835.35s** |
| One real exact-200 PASS | **1572.30s** |

The exact-200 also discharges a debt the roadmap names explicitly: `39e31b1a`
proved the neutral lifecycle with a single exact-50, and this is the exact-200
that proof did not include. (One had already been run on 2026-08-10 at 1578.29s;
this one is at exit HEAD, after everything the three sessions changed.)

**The suite is 88 tests, not 91.** The `fault/sandbox.py` deletion removed three
registered tests and no others were added. Any instruction that still says
91/91 is stale from this commit on.

---

## 2. Item by item

### 0.2 — the container path's failure handler · `ce0bea2d`

`_execute_runtime`'s exception handler was the process path's, copied onto the
container path, where neither `nodehosts` nor `snapshots` is bound. Measured:
`NameError` on the first line, swallowed, so **every container-path failure left
an empty artifacts directory**. It could not have worked with its names bound
either — both state builders read `container_id`/`pid` off every node, and a
fleet that failed partway through starting has neither. The state is now built
from `started`.

### 0.3 — record, then remove, the exec fallback · `3315e6af`, `e04d6ce9`

The record half installed a `CommandRecorder` in `run_exact_gate`, writing to
`runtime/command_audit/`. Two general fixes were needed before it could answer
anything: the recorder is a `ContextVar` and a new thread starts with an empty
context, so everything inside `_bounded_parallel` went unrecorded (2686 rows
against 4194 once fixed, missing almost all of cluster formation); and
`record_result` rewrote the whole log per row, measured 1.96 ms/row at 250 rows
and 47.39 at 4000, which *failed* a real exact-200 at 1586.80s against a control
PASS at 1578.29s.

The remove half then had a measurement to act on. `_node_response`'s
`docker exec` transport fallback fired **four times in a passing exact-200 and
never in four passing exact-50 runs**, all four at one site: `start_node`'s
readiness poll, first attempt after `valkey-server` starts, host path reading an
empty RESP reply — inside a 30s loop that already catches, sleeps and retries.
It bought one early poll, not a run. Proof it is gone, same run before and
after: `docker exec … valkey-cli` rows were 624 actuator + 4 `cluster_probe`,
and are now 624 actuator + 0.

### 0.5 — the seam's two missing §15 operations · `4f54442a`

Derivation, both boundaries' measurements and the slice's own findings are in
`seam_completion_slice_map.md`. `load_lane_host` is evidence upload and
`release_run` is end-of-run cleanup; `reclaim_run` keeps its pre-run meaning and
now says so. **The protocol a second backend implements is frozen at
twenty-three operations.**

Two things the slice found rather than assumed. Evidence upload had **one** site
outside the seam, not several — the resource sampler already pulls its own
samples through the object the backend returns, so §15's sampler deployment and
the upload of what it produced are one member; what was left was memtier's JSON
and HDR, copied by a `docker cp` inside `observability/load.py`, a module §15
declares invariant, which named `docker` three times and now names it zero. And
end-of-run cleanup **was not behind the seam at all**: `cleanup_scenario`
dispatched on `runtime.type == "docker_process"` and otherwise ran
`docker ps --filter label=…`, so a native run would have found nothing owned by
it in Docker and written `status: PASS` with every remote process still running.
That is now a stated refusal with a test.

The slice also added the two diff views its own surfaces lacked — a `cleanup`
stage and a `load_lane_evidence` report — calibrated identical
baseline-to-baseline, with eight seeded regressions each caught by the view that
owns it.

### 0.6 — decide `fault/sandbox.py` · `ff4e4f21` memo, `5d260c7e` deletion

The memo recommended deletion; the operator approved option A on 2026-08-10;
session C executed it. `fault_sandbox_decision_memo.md` §7 is the execution
record. Both decisive claims were re-measured against HEAD first, per the
deviation rule, and both held:

- **Six of the seven fault types issue zero runtime commands** and record
  `status: PASS` for a fault lifecycle that did not happen. Measured by driving
  each type once with `run_docker` replaced by a recorder. `node_stop` is the
  only one that acts, in four commands.
- **No acceptance bar reached it.** Importing `gates.real` and
  `runtime.lifecycle` leaves `fault.sandbox` absent from `sys.modules`; the only
  fault module either pulls in is `network_proxy`. Across the 383 files of the
  two frozen exact-50 baselines the string `fault_state` appears zero times.

Gone: the module, the whole `fault` CLI command group, the two `cli_compat`
wrappers, `runtime/teardown.py::_remove_fault_state_files`, three catalog tests
and their files, and `AGENTS.md`'s claim that the two subcommands are preserved
surface. `milestones/` was not edited, and the deletion proved that right: M1
still expands, `definition_status` `READY`, 90 planned tests to 87 — exactly the
three deleted, no criterion left with nothing.

**Declared artifact change:** `cleanup_actions` can no longer contain a
`type: fault_state` row. Confirmed against evidence rather than assumed — no
baseline run and none of the three exit-gate runs ever produced one, and
`cleanup_report` diffs byte-identical to the baseline in both exact-50 runs.

---

## 3. The exit-gate runs

| Run | Gate run | Result |
|---|---|---|
| exact-50 #1 | `gate-20260810T130627Z-7d211058` | **PASS 889.45s** |
| exact-50 #2 | `gate-20260810T132133Z-454c3fbc` | **PASS 835.35s** |
| exact-200 | `gate-20260810T133540Z-47905626` | **PASS 1572.30s** |

All three: `run_verdict` **12 of 12 checks OK**, `cleanup_report` PASS with zero
resources remaining and zero cleanup errors, **zero Docker residue**, and the
string `ERROR` in **no artifact file** of any of the three. exact-200 recorded
200 known nodes and `cluster_state: ok`.

### 3.1 exact-50 against the frozen baseline

Both runs against `artifacts/baselines/exact-50-6b6f57fd/run-1`, at every
stated pass mark, identically:

| Stage | Pass mark | Run #1 | Run #2 |
|---|---|---|---|
| `runtime_start` | 7/7 | 7/7 | 7/7 |
| `cluster_form` | 5/5 | 5/5 | 5/5 |
| `management_matrix` | 6/8 | 6/8 | 6/8 |
| `fault_matrix` | 5/6 | 5/6 | 5/6 |
| `cleanup` | 2/2 | 2/2 | 2/2 |

And each delta at its **declared shape**, not merely its declared count, with no
third component in either:

- `management_matrix`, both declared components: command-log rows 1592 → 1606,
  **+14 exactly**; `cluster_migrate_keys` 4 → 18 (`ded96fac`);
  `owned_valkey_process_remove_nodes_conf` 4 → 0 with
  `owned_valkey_process_discard_prior_state` 0 → 4 (`313cacc9`'s rename, which
  moves no rows). Three row kinds changed, fourteen unchanged. Identical in both
  runs.
- `fault_matrix`, the one declared component: confined to `fault_sequence` and
  within it to the isolated side of the three partition scenarios.
  `isolated_reachable_from_this_side` 0 → 3, `isolated_unreachable_reason`
  0 → 3, `isolated_cluster_info` observed → empty ×3, `isolated_cluster_state_ok`
  true 1 → 0 and false 2 → 3. The `85d5096a` shape. Identical in both runs.
- `cleanup_report` **byte-identical** to the baseline in both runs, which is
  also the evidence for the deletion's declared artifact change.
- `load_lane_evidence`: **18 files, none empty, both JSON results parsing**,
  identical to the baseline in both runs.

### 3.2 exact-200 against the frozen exact-200 baseline

Against `artifacts/baselines/exact-200-6b6f57fd/run-1`. Every view that is
genuinely comparable is identical — `runtime_start` **6/6** and `cluster_form`
**4/4**, which is what that baseline's own `BASELINE.md` states — and the two
that are not are both explained by the baseline rather than by the candidate:

- `lifecycle_timeline:<stage>` reports `ERROR` in both stages because the file
  is **absent on the baseline side**. `lifecycle_timeline.json` is written only
  after a passing gate, and every frozen exact-200 run fails downstream.
  `BASELINE.md` predicted it unavailable on *both* sides; it is now available on
  one, because this candidate passes. That is the reverse of a regression.
- `nodehost_density_plan` differs in exactly one field,
  `scenario_config_path` — an absolute path, `…/scratchpad/wt-6b6f57fd/project/…`
  against `…/valkey_scale_lab/project/…`, because the baseline was captured from
  a `git worktree`. The tool scrubs a run's own temporary paths, not the
  checkout the baseline was captured from. Nothing about the stage differs.

### 3.3 The numbers that are supposed to be fixed

- **The fault lane's three scale-fixed numbers hold at both scales**: 9
  scenarios, 12 command rows, 15 workload windows — at exact-50 twice and at
  exact-200.
- **Primary-kill RTO**: exact-50 **47.87s** and **47.62s**, both inside the
  45–50s exact-50 band. exact-200 **47.60s**, a fifth datum for a band CLAUDE.md
  records as wider and overlapping (53.75, 53.15, 49.75, 47.62 before this one).
  No shift in the spread, so no finding.
- **`rolling_restart_probe_counts`** identical to the baseline in both exact-50
  runs (`rep138/full50/retry0/cmds376` on both lanes) — the field CLAUDE.md
  warns is a retry counter that two agreeing runs cannot prove deterministic.

---

## 4. What is open at exit

Nothing here blocks M3-A. Each is either carried deliberately or belongs to
another item; none was introduced by the precondition work.

**Carried into M3-A by operator decision (2026-08-10):**

- **End-of-run cleanup terminates by stale pid** — at cleanup each nodehost has
  12–13 live `valkey-server` processes and zero of them is a pid in
  `state.json`; `docker rm -f` is what actually stops the fleet. Correct under
  Docker; a backend with no container to remove has no such backstop. Goes to
  **M3-A item 1.4**. `seam_completion_slice_map.md` §5.1.
- **No node log is ever collected** — every node is configured with a `logfile`,
  the path is in the bundle manifest and in `state.json`, and nothing reads it.
  §15 names 日志与证据上传 and 0.5 gave 证据 a boundary, so the 日志 half has no
  implementation on either backend. Goes to **M3-A item 1.3**, mechanism
  deliberately not pre-decided. `seam_completion_slice_map.md` §5.2.

**Accepted, deliberately not fixed:**

- **No fault path checks ownership.** `_require_owned_container` was the only
  such check anywhere on a fault path and went with `fault/sandbox.py`; the
  seam's actuator has none — `kill_node` reads `nodehost_container_name` off the
  node and execs. The operator accepted this and left M1 unedited. Giving the
  actuator its own check is a recorded candidate that a second backend would
  inherit, so it belongs to whoever writes one.
- **Two unregistered scripts still invoke the deleted CLI surface**:
  `scripts/fault_failover_gate.py` shells out to `cli fault apply`/`clear` at
  three sites, and `scripts/audit_small_real_scenario_parity.py` expects the
  artifact keys it wrote. Neither is a registered check. Recorded rather than
  repaired, because repairing an unregistered script is not part of an approved
  deletion.

**Still open from before, unchanged by this work:** the `ERROR` verdict's
unfinished half (a run still fails fast at the first raise, so §12.2's
precedence is never exercised across stages, and `lifecycle_timeline.json` does
not outlive a failure) and its three smaller sites; the whole-fleet observation
cadence and the rolling restart's health gate reading whole-fleet
`CLUSTER NODES`, both measured fine at 200 and scheduled as M4 item 2.4; `_spec`
setting no `host` so `_node_command` cannot reach a container-backend node, moot
while `scale_ladder` is registered to no backend; a failing `docker_process` run
leaving only a bare `reclaim_run`; whether the pre-drain reshard stranded keys;
the `<=30` replica-attach flake; and the standalone `management_matrix`
capability having no registered real gate test.

**Awaiting the operator, from session A's reports:** the
`.github/milestone-loop/` working-tree changes left by a mis-popped stash are
still present, still uncommitted and still nobody's. Session C did not touch
them.

---

## 5. What M3-A inherits

- **A frozen protocol.** Twenty-three `NodeBackend` operations. M3 item 1.2 owes
  the whole of it, and no stale count from an older document applies.
- **A backend registry with `native_multi_ecs` absent rather than rejected**
  (`runtime/backends.py`), a lifecycle with no Docker primitive
  (`runtime/lifecycle.py`), and a Gate whose Docker-daemon check is a backend
  property.
- **Two carried findings**, above: stale-pid teardown into item 1.4, node-log
  collection into item 1.3.
- **Diff tooling that covers five stages** — `runtime_start`, `cluster_form`,
  `management_matrix`, `fault_matrix`, `cleanup` — with stated pass marks and
  declared deltas. The Docker baselines stay frozen at `6b6f57fd`; native
  baselines are frozen from M3-**B**'s real-host runs, not from simulated ones.
- **Cross-backend invariants**: the fault lane's 9/12/15, and the `85d5096a`
  partition contract (isolated side unreachable, fail-closed with a recorded
  reason) which the native actuator must present whatever mechanism it uses.
- **Two numbers to re-measure rather than assume**: the 240s formation-dwell
  window is not scale-free and must be re-argued on any distributed backend; and
  RTO is compared **per scale**, 45–50s being the exact-50 band while exact-200
  is wider and overlaps it.
- **A suite of 88**, and a milestone list where M3 has a registered check on 1 of
  its 6 criteria and M4 on 1 of 7. No placeholders.

### 5.1 M3-A session boundaries

The roadmap defers these to this report, with one item per session as the
default grain. Nothing below is started, and M3-A begins only on the operator's
explicit approval.

| Session | Scope | Hard stop |
|---|---|---|
| M3-A-1 | Item 1.0, the simulated-host harness, and item 1.1, the pinned native build. Both are lab tooling outside the product and neither can be proven without the other. | Manifest-driven bring-up of ≥2 simulated hosts, digests recorded. |
| M3-A-2 | Item 1.2, the native backend, including the transport spike the roadmap requires be measured before the choice is recorded. | Spike measured with its numbers; hermetic backend tests against a fake transport; `native_multi_ecs` present in the registry. |
| M3-A-3 | Item 1.3, cross-host evidence — which is where the node-log question is answered rather than pre-decided. | Validator accepts only host-attributed artifacts with offsets; an induced transfer failure yields `ERROR`. |
| M3-A-4 | Item 1.4, distributed cleanup — which is where the stale-pid finding is answered. | Zero residue on passing simulated runs; aborted-run reclaim clean. |
| M3-A-5 | Item 1.5, the development ladder: two-host exact-30 smoke, then native exact-50, then native exact-200, equivalence-diffed with vocabulary deltas declared in advance. | The three runs and the equivalence diff. |

Item 1.2 is the one most likely to want splitting once its map exists; that is a
decision for its own session's report, not for this one.

**Amended 2026-08-11, after M3-A-2 reported.** Item 1.2 did not split: it landed
whole, at the hard stop above. Its map found one gap in this grain instead, and
the operator accepted the fix, so **M3-A-5's scope now opens with a native
bring-up smoke** - two simulated hosts, the backend driven directly with no Gate
run and no cluster - before the two-host exact-30. The reason is that nothing
between M3-A-2 and M3-A-5 runs a single native operation against a host through
the product, so the exact-30 would otherwise be the first, with twenty-three
unexercised operations in the search space of any failure. Sessions M3-A-3 and
M3-A-4 are unchanged. See `native_backend_slice_map.md` §11.

---

## 6. State at exit

HEAD `5d260c7e`, branch `fast-iter`. Suite 88/88. Two consecutive real exact-50
and one real exact-200 PASS, all three at 12/12 with zero residue. The
precondition list is complete and **M3-A has not been started, scaffolded or
prepared for**; the correct next state is idle.
