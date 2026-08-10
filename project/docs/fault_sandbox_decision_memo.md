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
- M1's `local.operations-and-recovery` check list needs its own decision (§5),
  not a silent shrink to the network proxy.

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

**The one real cost, and it is the operator's to weigh:** M1's
`local.operations-and-recovery` criterion says fault behaviour must remain
"bounded, observable, and confined to project-owned resources", and after
deletion its attached checks are `product.failover`, `product.observability`,
`product.stability` and a `product.fault` reduced to the network proxy alone.
The behaviour that criterion describes *is* covered on real runs — by the fault
lane, through `real.local.full-flow` — but that test is attached to
`local.exact.50` and `local.exact.200`, not to this criterion. So deletion
should be accompanied by a decision about that criterion's check list, not
performed and left. That is a milestone edit, which is why it is named here.

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
Nothing in this memo has been executed: `fault/sandbox.py`, the CLI subcommands
and all three tests are untouched at this commit.

If option A or B is approved, it is a session C item with its own commit, its
own evidence, and — for A — the milestone-criterion decision named in §5.
