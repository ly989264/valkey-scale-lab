# Decision memo: what to do with `fault/sandbox.py`

Roadmap (revision 5.1) item 0.6. **This memo is the executable half.** The
deletion it recommends was reserved to the operator by the roadmap's approval
rule; it has since been approved and is recorded below, and it is still not
performed here.

Measured against HEAD `020e0482` plus roadmap item 0.5's changes.

The question item 0.6 asks is narrow and worth keeping in view: *the decision
changes what a second backend must implement.* If the `cli fault apply`/`clear`
surface survives, `EcsNodeBackend` owes it an implementation; if not, it owes
nothing.

---

## Operator decision — 2026-08-10

**Option A approved: delete the module and the `cli fault apply`/`clear`
surface.** Execution belongs to the next worker session, not to the one that
wrote this memo; the session that wrote it was scoped to the memo alone and the
approval arrived inside it.

Two things travel with the approval and are not optional parts of it:

- `runtime/teardown.py::_remove_fault_state_files` becomes dead with the module,
  because `apply_fault` is the only producer of `fault_state_*.json` anywhere in
  the product. Its cleanup-action row disappears from `cleanup_report` - a small
  artifact change to declare, and it moves no baseline diff, since both frozen
  exact-50 runs already record zero such rows.
- M1 needs **no** edit, decided 2026-08-10 after measuring it: `product.fault`
  survives the deletion with `product.fault.network_proxy`, so no criterion
  loses its checks. §5 records what that does cost - the only ownership check
  on any fault path goes with the module - and that giving the seam's actuator
  one instead is a candidate, not a decision.

The rest of this memo is the evidence the decision was taken on, unchanged.

---

## Recommendation

**Delete the module and the CLI surface it serves.**

The decisive finding is not the duplication the roadmap and CLAUDE.md both name.
It is this: **six of the seven fault types the surface advertises inject no
fault at all, and report `status: PASS` for a fault lifecycle that did not
happen.** That is fabricated evidence by this repository's own standard, and it
is the kind of thing a second backend should not be asked to reproduce.

If the operator wants the surface kept, there is a smaller option that fixes the
fabrication without costing `EcsNodeBackend` anything new; it is §5 below.

---

## 1. What the module is

`src/valkey_scale_lab/fault/sandbox.py`, **490 lines**: `apply_fault`,
`clear_fault` and seventeen private helpers. It imports `run_docker` from
`docker_runtime` and issues `docker exec`, `docker inspect` and `docker start`
directly.

Reachable from exactly one place: `cli fault apply` and `cli fault clear`, via
`cli_compat.apply_fault` / `cli_compat.clear_fault`.

It is **not** the fault lane. The fault lane a real run exercises goes through
the seam's seven actuator operations on `NodeBackend`, and never touches this
module.

## 2. What it actually does, measured by reading every branch

`apply_fault` accepts seven `fault_type` values. Only one of them acts:

| `fault_type` | What `apply_fault` does |
|---|---|
| `node_stop` | ownership-label check on the nodehost, `docker exec … sh -c "kill -KILL <pid>"`, then a `/proc` absence probe |
| `network_delay` | records `action: sandbox_proxy_lifecycle_recorded`, `host_network_mutated: false`, `status: PASS` |
| `network_loss` | as above |
| `network_partition` | as above |
| `network_flap` | as above |
| `process_stop` | as above |
| `process_restart` | as above |

The six rows below the first take a single `else` branch. Nothing is delayed,
dropped, partitioned, flapped, stopped or restarted. The run writes a
`fault_state_<id>.json`, a `fault_apply` artifact and a `fault_report.json`, all
saying `PASS`, and `clear_fault` then writes the matching
`sandbox_proxy_lifecycle_cleared`.

A second dead branch: `clear_fault`'s `container_stop` restore path
(`sandbox.py:324`) responds to an `observed_impact.action` that `apply_fault`
never writes — it writes `process_sigkill` and nothing else. Only a hand-written
`fault_state_*.json` reaches it.

## 3. What exercises it

**No acceptance bar.** `real.local.full-flow` never calls it, at any scale. Both
frozen exact-50 baselines confirm this from the other end: **zero
`fault_state_*.json` files and zero `fault_state` cleanup actions** in either
run, while the same runs record the fault lane's nine scenarios, twelve command
rows and fifteen workload windows through the seam.

**Three hermetic catalog tests**, all of which fake `run_docker`:

| Catalog test | File | Milestone attachment |
|---|---|---|
| `product.fault.sandbox_fault` | `tests/fault/test_sandbox_fault.py` | suite `product.fault` → M1 `local.operations-and-recovery` |
| `product.fault.owned_runtime_guard_gap` | `tests/fault/test_owned_runtime_guard_gap.py` | as above |
| `product.unit.fault_sandbox` | `tests/unit/test_fault_sandbox.py` | suite `product.unit` → M1 `local.lifecycle` |

Note the third `product.fault` member, `product.fault.network_proxy`, tests
`fault/network_proxy.py` — the in-process host TCP proxy the fault lane really
uses — and is untouched by any option here.

**One non-gate consumer**: `scripts/audit_small_real_scenario_parity.py` names
`fault_sandbox` as a surface and expects `sandbox_only`,
`host_network_mutated`, `global_firewall_mutated` and `fault_state_cleared`
keys. It is a standalone audit script, not a registered check.

Separately, the *scenario* named `fault_sandbox` — registered to
`docker_container` and aliased in `compat/phase_aliases.py` — is a different
thing from this module and is unaffected by every option below. Worth stating
because the names collide: `_execute_runtime`'s container path writes no
fault-specific artifact for that scenario either.

## 4. What it costs a second backend

§15 makes the actuator one of the five things a runtime adapter replaces. After
slice 4 the actuator is seven `NodeBackend` operations. This module is a
**second** Docker actuator sitting outside the seam, with its own ownership
check, its own process-absence probe, its own restart wait and its own retry
policy.

If the surface survives unchanged, `EcsNodeBackend` owes, in addition to the
seam it already owes:

- an ownership check against a remote host's own labelling scheme;
- a remote SIGKILL by pid;
- a remote process-absence probe (there is no `/proc` on the controller, so this
  is a second remote read alongside `stop_node`'s);
- a remote restart from a config file, with a pid-file wait, a stability window
  and a retry count;
- and — the awkward part — **six fault types that must continue to inject
  nothing**, or else the native backend would start injecting faults the Docker
  backend never did, which is the opposite of M3's same-semantics thesis.

The overlap with what it already owes is near total: `node_stop` + its clear is
`kill_node` followed by `start_node`.

## 5. The options, priced

**A — delete the module and the CLI surface (recommended).**

Removes: `fault/sandbox.py` (490 lines); the `fault apply` / `fault clear`
subcommands in `cli.py`; `cli_compat.apply_fault` / `clear_fault`; the two
catalog tests that exist only for it plus `owned_runtime_guard_gap`; and their
test files. It also makes `runtime/teardown.py::_remove_fault_state_files` dead
— `apply_fault` is the only producer of `fault_state_*.json` anywhere in the
product — so that helper and its cleanup-action row go too, which is a small
artifact change to declare rather than to slip in.

`EcsNodeBackend` then owes nothing beyond the seam.

**No milestone edit is required.** An earlier draft of this memo said M1's
`local.operations-and-recovery` check list needed a decision. Measured, it does
not. That criterion covers six behaviours — "Management, workload, fault,
failover, recovery, and stability" — and attaches four suites; only
`product.fault` is touched, and it **survives**, going 3 tests → 1
(`product.fault.network_proxy`, which tests the in-process TCP proxy the fault
lane really uses and has nothing to do with this module). `product.unit` goes
22 → 21. Nothing reports `DEFINED`; no criterion loses its checks. Removing the
criterion would delete failover, observability and stability coverage that has
no connection to `fault/sandbox.py`.

**The real cost is narrower, and it is a coverage loss rather than a milestone
one.** `_require_owned_container` — which inspects a container's labels and
refuses if they are not this run's — is the **only ownership check on any fault
path**, and `product.fault.owned_runtime_guard_gap` is its only test. The seam's
own actuator does not have one: `kill_node` takes `nodehost_container_name`
straight from inventory and execs. So deleting this module removes the one test
of the criterion's own phrase, "confined to project-owned resources".

That is not an argument against deleting. The module is six-sevenths inert, and
the seam's container names come from inventory it produced itself, so the
practical exposure is low. It is an argument that the question worth asking is
whether the *actuator* should gain an ownership check — a separate change, with
its own evidence, that a second backend would then inherit.

**Operator decision, 2026-08-10: change nothing in M1.** The deletion lands
clean and the ownership-refusal test is simply gone. Giving the actuator its own
ownership check is recorded here as a candidate, deliberately not done.

**B — keep the surface, make it truthful (the middle option).**

Delete the six no-op fault types so the CLI stops advertising faults it does not
inject, delete the unreachable `container_stop` clear branch, and re-express
`node_stop` and its clear on the seam's existing `kill_node` and `start_node`.

Result: the CLI keeps a working, honest single-fault surface; the second Docker
actuator disappears; `EcsNodeBackend` owes **nothing new**, because it already
owes those two operations. Cost is a real change to `apply_fault`'s accepted
input set and to the artifacts the six removed types used to write — a behaviour
change needing its own evidence, unlike option A which removes a path nothing
exercises.

**C — keep it as it is.**

Costs `EcsNodeBackend` everything in §4, including the obligation to keep six
fault types inert. Recommended against.

## 6. What this memo does not decide

Per the roadmap's approval rule, removing a CLI surface is the operator's call.
Nothing in this memo had been executed when §1-§5 were written: `fault/sandbox.py`,
the CLI subcommands and all three tests were untouched at that commit.

If option A or B is approved, it is a session C item with its own commit, its
own evidence, and — for A — the milestone-criterion decision named in §5.

---

## 7. Execution record

**Option A executed in the commit that carries this section**, from HEAD
`d987975f`. The roadmap's deviation rule asks that an item's premises be
verified rather than trusted, so both decisive claims were re-measured against
that HEAD before anything was removed. Both hold.

### 7.1 Six of seven types still inject nothing — measured, not read

§2 derived this by reading every branch. It was re-derived by running
`apply_fault` once per accepted type against a fabricated single-node state,
with `run_docker` replaced by a recorder that counts calls and answers the
ownership probe with this run's labels:

| `fault_type` | runtime commands issued | recorded `status` | recorded `action` |
|---|---|---|---|
| `network_delay` | **0** | `PASS` | `sandbox_proxy_lifecycle_recorded` |
| `network_loss` | **0** | `PASS` | `sandbox_proxy_lifecycle_recorded` |
| `network_partition` | **0** | `PASS` | `sandbox_proxy_lifecycle_recorded` |
| `network_flap` | **0** | `PASS` | `sandbox_proxy_lifecycle_recorded` |
| `process_stop` | **0** | `PASS` | `sandbox_proxy_lifecycle_recorded` |
| `process_restart` | **0** | `PASS` | `sandbox_proxy_lifecycle_recorded` |
| `node_stop` | 4 | `PASS` | `process_sigkill` |

`node_stop`'s four are the ownership inspect, the presence preflight, the
`kill -KILL` and one absence probe. The same run confirms §2's second dead
branch from the other end: `apply_fault` records `process_sigkill` and only
that, so `clear_fault`'s `container_stop` restore path is unreachable from it.

### 7.2 No acceptance bar reaches it — measured from both ends

Importing `gates.real` and then `runtime.lifecycle` — the whole real-run
path — leaves `valkey_scale_lab.fault.sandbox` absent from `sys.modules`. The
only `fault` module either pulls in is `fault.network_proxy`, which this
deletion keeps. Across the 383 files of the two frozen exact-50 baseline runs,
the string `fault_state` appears **zero** times and there is no
`fault_state_*.json`, which is also the confirmation §5 owed for
`_remove_fault_state_files`: its cleanup-action row was already absent from
every baseline `cleanup_report`, so removing the producer moves no diff view.

### 7.3 What was removed

- `src/valkey_scale_lab/fault/sandbox.py`, 490 lines.
- `cli.py`: the whole `fault` command group. Its only two subcommands were
  `apply` and `clear`, so nothing was left for a bare `fault` parser to carry.
  `_fault_apply`, `_fault_clear` and the `FaultError` import went with it.
- `cli_compat.py`: the `fault_sandbox` import, the `apply_fault` and
  `clear_fault` wrappers, and their two `__all__` entries.
- `runtime/teardown.py::_remove_fault_state_files` and its call, per §5. The
  `cleanup_report` change is declared: `cleanup_actions` can no longer contain a
  `type: fault_state` row. No run in evidence ever produced one.
- `catalog.json`: `product.fault.sandbox_fault`,
  `product.fault.owned_runtime_guard_gap`, `product.unit.fault_sandbox` and
  their three test files. No placeholder replaced them. `product.fault` goes
  3 tests to 1, `product.unit` 22 to 21, `product.all` 88 to 85, and
  **`repository.all` 91 to 88** — the standing suite count changes with this
  commit.
- `tests/integration/test_docker_runtime_contract.py::test_cleanup_removes_fault_state_files`,
  which pinned the helper §5 named as dead.
- The two rows and one handler test in `tests/cli/test_compatibility_wrappers.py`
  that covered the deleted wrappers, and `tests/unit/test_cli_contract.py`'s
  assertion that `fault` appears in `--help`.
- `AGENTS.md`'s Product Interface list, which named both subcommands as
  preserved surface; it now records that they were deleted and why.

Three pinned counts in `verification/tests/test_contracts.py` moved with it, and
one of them is the measurement §5 promised rather than bookkeeping. The catalog
goes 95 registered tests to 92. **M1's expansion goes 90 planned tests to 87 and
its `definition_status` stays `READY`** - the three that left are exactly the
three deleted, no criterion expanded to nothing, and the milestone still plans.
That is the deletion's own proof that `milestones/` needed no edit.

`milestones/` is untouched, per the operator decision in §5.

### 7.4 Two consumers left pointing at a surface that is gone

§3 named one: `scripts/audit_small_real_scenario_parity.py`. There is a second,
which §3 missed — `scripts/fault_failover_gate.py` shells out to
`python3 -m valkey_scale_lab.cli fault apply` and `... fault clear` at three
sites. Neither script is a registered check: `catalog.json`'s only non-pytest
runner is `scripts/m2_performance_gate.py`, and `fault_failover_gate.py` is
reached only from `scripts/failover_rto_timeout_matrix.py`, another standalone.
Both are recorded here rather than changed, because repairing an unregistered
script is not part of an approved deletion and would need its own evidence.

The same is true of `fault_report.json`, the flat artifact `_write_fault_report`
produced. Nothing in `src/` read it; the audit scripts above did.
