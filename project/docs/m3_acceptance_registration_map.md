# Roadmap item 1.7: M3's acceptance, registered

M3-B-2. Item 1.6 produced the evidence for five of M3's six criteria and
attached a check to none of them, because attaching them is this item's work.
What that work turned out to be is mostly *deciding what already asserts what* -
the code below was small, and the reasoning in §1 is the item.

**The headline.** All six criteria carry executable checks, `./gate milestone m3`
is **READY** and green on `fast-iter` (8/8, first attempt), and no criterion is evidenced by a test
that does not evidence it. Three `real.ecs.*` entries were registered; two of
them are proof harnesses that already existed and had never been registered.

---

## 1. What a native run already asserts about itself

This had to be answered before a single catalog entry was written, because it
decides whether the item is catalog work or script work. The temptation the
milestone's own no-placeholder rule exists to stop is real and specific: there
are hermetic tests with exactly the right names - `product.unit.host_evidence`,
`product.evidence.evidence_contract`, two `cleanup_*` integration tests - and
every one of them tests the *validator*, not a run.

Measured at HEAD, in the code and against `real-exact-50-c58a762a/run-1`.
`run_exact_gate` ends in `validate_raw_sources_by_kind`
(`evidence/validation.py:94`) and `build_admission_from_sources`
(`gates/real.py:595`), and both are fail-closed - a semantic error raises and the
run cannot report PASS. Between them, over the run's own artifacts:

| the run refuses itself unless | site |
|---|---|
| the compiled plan is exact and forbids downscale | `real.py:215` |
| `run_state.json` PASSes with exactly N nodes and N unique `logical_id`s | `validation.py:127-140` |
| `resource_preflight.json` admits exactly N | `validation.py:158-162` |
| an independent probe reports `cluster_state: ok`, `known_nodes == N`, `slots_assigned == slots_ok == 16384` | `real.py:616-619` |
| the observed Valkey versions are 9.1.x | `real.py:612-613` |
| `cleanup_report.json` PASSes with empty `resources_remaining` **and** empty `cleanup_errors` | `validation.py:163-167` |
| every nodehost is accounted for exactly once, carries a non-empty `host_id`, and has start- *and* end-of-run clock readings each with a measured `offset_ms` and `uncertainty_ms` | `validation.py:400-437` |
| every observed node has exactly one journal, with a sha256 and a path inside the run, attributed to one nodehost | `validation.py:439-479` |
| every artifact row belongs to this run, `command_id` and `event_id` are unique, and every `MISSING` carries a reason | `validation.py:204-233`, `:481-503` |

So **`exact.50`, `exact.200` and `evidence` need no new assertion at all.** The
run is already the check, exactly as M1's `local.exact.50` uses
`real.local.full-flow`. Pointing a criterion at a passing run of the thing the
criterion is about is not a placeholder; pointing it at a unit test of the
validator would have been.

### 1.1 The two things a passing run does *not* say

**Nothing anywhere asserts a run's backend.** `grep native_multi_ecs` over
`evidence/`, `analysis/` and `gates/` returns nothing. A PASS of
`real.local.full-flow --config real_ecs_50.yaml` and a PASS on Docker are the
same PASS, so `distributed.exact.50`'s "a real **multi-ECS** full-flow run" would
have been asserted by the *file name of a configuration*.

This needed no new code. `execution.backend_for_provider` (`execution.py:160-186`)
refuses a requested backend the configuration's `runtime.provider` does not
implement, in both directions - item 1.2 built it after a native configuration
ran on Docker. Putting `--backend native_multi_ecs` in the entry's argv makes the
entry **structurally unable to pass on Docker**, whatever configuration it is
handed. Measured alongside it, for the record: the frozen real exact-50's command
audit is **3914 rows, zero of them naming `docker`**.

**The abort path is not on a passing run's path.** `cleanup_report` proves the
run cleaned up after itself when it finished; `distributed.safety-and-cleanup`
says "leave no managed process or host resource behind", and the case that
matters is the controller that did not finish. Item 1.6 proved that on real hosts
- 43 → 0 through `release|abort|stubborn` - with a harness that was **not
registered**. Registering it is the smaller and more honest move than inventing
a second one.

### 1.2 `product.orchestrator` is stale in a measurable way

It runs `tests/orchestrator/test_local_orchestrator.py` over
`valkey_scale_lab.orchestrator.local.validate_inventory`, whose host records are
`{host_id, ip, docker_endpoint}`. That module is imported by `docker_runtime.py`
and by nothing else. A native run reads `runtime/host_inventory.py`. So M3's
inventory criterion was evidenced by a test of a module a native run never
executes - which is what the roadmap means by the shim item 1.7 supersedes.

The real contract is covered by `product.unit.native_backend` (77 tests): a
manifest read into neutral records, a manifest that is not one refused, a host
missing an address refused, placement joined to hosts by availability zone, two
nodehosts on one host refused, ports outside a host's declared range refused.

**One clause of the statement had no test on the real module, and now has one.**
`load_host_inventory` rejects a duplicate `host_id` (`host_inventory.py:200`) and
nothing tested it; the shim tested duplicate rejection, for the other inventory.
"Rejects duplicate hosts" is the criterion's own words, so the test is this
item's - and it costs no counts, because it joins a module the catalog already
registers.

**Reported rather than decided: the statement is written in the shim's
vocabulary.** "Accepts explicit local **and SSH** endpoints" is
`docker_endpoint: "local" | "ssh://…"`. A fleet manifest has only an ssh
`control_endpoint`, and the native contract has no notion of a local one. Rather
than drop the clause's only evidence while claiming to have superseded it, the
criterion carries **both** checks: `product.unit.native_backend` for the contract
a native run actually reads, and `product.orchestrator` for the clause that is
about the other one. Whether the statement should be narrowed to the distributed
runtime is a change to what the milestone claims, and therefore the operator's.

---

## 2. The attachment map, and why it costs what it costs

`select_milestone` (`planning.py:74-116`) does **not** deduplicate: attaching one
test to *k* criteria runs it *k* times. M2's `promotion-and-regression` lists
`real.local.full-flow` twice for that reason. So the attachment map is a
fleet-time decision and not only a bookkeeping one, and it was taken by the
operator on 2026-08-13 from a costed set of options.

| criterion | check | what establishes it | cost |
|---|---|---|---|
| `inventory-and-placement` | `product.unit.native_backend`, `product.orchestrator` | §1.2 | ~5 s |
| `native-runtime` | `real.ecs.bringup` | every seam operation on ≥2 real hosts | 17.9 s |
| `exact.50` | `real.ecs.full-flow` n=50 | §1 + `--backend native_multi_ecs` | 14 min |
| `exact.200` | `real.ecs.full-flow` n=200 | as above | 24 min |
| `evidence` | `real.ecs.full-flow` n=50 | §1's host-evidence rows | 14 min |
| `safety-and-cleanup` | `real.ecs.cleanup-ownership` ×2 | `release` and `abort` on real hosts | 28 s |

The rejected alternative was to point `native-runtime`, `evidence` and
`safety-and-cleanup` at their own full-flow runs: 4 × exact-50 + 1 × exact-200,
about 96 minutes, four chances for an intermittent failure, and the abort path
still unevidenced by any check. The chosen map takes **two exact-50 and one
exact-200** - which is the ladder's own acceptance bar, arrived at from the
criteria rather than imposed on them - plus three short fleet proofs.

A criterion that goes red now names what broke. That is the property the
alternative loses: five criteria failing identically because one run failed says
nothing about which claim is in doubt.

---

## 3. `ulimit -n` had nowhere to go, and now has somewhere

Every real exact-200 has been taken under `ulimit -n 65536`, recorded in
`real_fleet_ladder_slice_map.md` §1 as part of the environment. `runtime_fd_limit`
requires `max(1024, nodes*8 + nodehosts*32)` = **1856** at exact-200, and Debian's
default soft limit is 1024. **The catalog runner has no shell**, so the invocation
that produced the frozen baselines cannot be written into an entry.

`scripts/ecs_gate.py` is where it went: it raises `RLIMIT_NOFILE` toward 65536,
never above the hard limit, prints what it got, and `execv`s the same CLI argv
`real.local.full-flow` uses plus `--backend native_multi_ecs`. Measured on the
first run through it: `RLIMIT_NOFILE soft 1024 -> 65536`.

The operator chose this over raising the limit durably on the controller,
because it makes `./gate milestone m3` state its own requirement rather than
depend on one machine having been configured once. **The preflight is not
weakened and is not meant to be**: it asks whether *this process* can hold O(N)
persistent RESP connections plus one ssh master per host, and the answer becomes
true because the process really does raise its limit. A controller whose hard
limit is below what the run needs still fails the preflight, with both numbers in
`resource_preflight.json` - which is also where the limit the run actually held is
recorded, so the milestone's evidence says what environment it ran in rather than
leaving it silently true of one machine.

`execv` rather than a subprocess, so the raised limit is inherited, the run keeps
the pid and process group the Gate is holding, and the Gate's timeout and its
SIGTERM-to-the-group reach the run itself instead of a wrapper.

---

## 4. What was registered

Three tests and one suite. All three are `{"type": "command", "result": "json"}`,
the form `error_verdict_map.md` settled and every `real.local.*` sibling uses: the
process exits 0 whenever it wrote a verdict, because a non-zero exit makes the
Gate report FAIL without ever reading the file.

- **`real.ecs.full-flow`** (`nodes`, `config`) → `scripts/ecs_gate.py`. §3.
- **`real.ecs.bringup`** (`fleet_id`) → `scripts/native_bringup_smoke.py`, which
  already **refuses a fleet of fewer than two hosts** (`native_bringup_smoke.py:148`),
  so "at least two ECS hosts" is asserted by the check rather than assumed of it.
- **`real.ecs.cleanup-ownership`** (`fleet_id`, `mode`) →
  `scripts/native_cleanup_proof.py`, which places real residue and then asks the
  hosts over its own ssh rather than through the backend it is proving.
- **`real.ecs.full-suite`**, beside `real.local.full-suite`, for operator use.

The two harnesses each gained a `--result-path` and nothing else. Without it they
report an exit code, which the Gate can only read as PASS or FAIL - throwing away
the one thing a smoke exists to say, which is *which* operation did not answer.

### 4.1 The counts this moved

`repository.all` **92**, unchanged - the new entries are `command` runners and
`repository.all` is the pytest tests. The catalog **96 → 99**, the M1 plan **91**,
unchanged. `verification/tests/test_contracts.py` pins the first two, and two
further assertions there moved with this item: M3's `definition_status`
**DEFINED → READY**, and M3's expansion, which now lists all eight checks in
order rather than the single shim.

---

## 5. The result

**`./gate milestone m3` is PASS, 8/8, `definition_status: READY`, on the first
attempt**, from the in-VPC controller at `2a30563b`. Invocation
`gate-20260813T015536Z-551fcacf`, 53 minutes end to end.

| check | status | seconds | detail |
|---|---|---|---|
| `product.unit.native_backend` | PASS | 0.41 | 77 tests |
| `product.orchestrator.local_orchestrator` | PASS | 0.16 | 4 tests |
| `real.ecs.bringup` | PASS | 14.14 | 62/62 seam operations on 8 hosts |
| `real.ecs.full-flow` n=50 | PASS | 876.75 | exact-50 full flow admitted |
| `real.ecs.full-flow` n=200 | PASS | 1430.26 | exact-200 full flow admitted |
| `real.ecs.full-flow` n=50 | PASS | 886.73 | exact-50 full flow admitted |
| `real.ecs.cleanup-ownership` release | PASS | 17.04 | zero managed residue on 8 hosts |
| `real.ecs.cleanup-ownership` abort | PASS | 13.08 | zero managed residue on 8 hosts |

Verified from the three runs' own artifacts rather than from the score:

| | exact-50 | exact-200 | exact-50 |
|---|---|---|---|
| `backend_id` | `native_multi_ecs` | `native_multi_ecs` | `native_multi_ecs` |
| requested → observed | 50 → 50 | 200 → 200 | 50 → 50 |
| distinct fleet hosts | 4 | 8 | 4 |
| `run_verdict` | PASS, 12/12 OK | PASS, 12/12 OK | PASS, 12/12 OK |
| `cleanup_report` | PASS, 20 rows | PASS, 40 rows | PASS, 20 rows |
| `resources_remaining` | 0 | 0 | 0 |
| residual scan `found` | 0 on each of 4 | 0 on each of 8 | 0 on each of 4 |
| journals | 50 | 200 | 50 |
| `runtime_fd_limit` soft / required | 65536 / 1024 | **65536 / 1856** | 65536 / 1024 |

The string `ERROR` appears in **no** artifact of any of the three runs. The
fault lane is **9 scenarios / 12 command rows / 15 workload windows with nine
`REAL_PASS`** in all three - the three scale-fixed numbers holding at both
scales on real hardware, unchanged. Primary-kill RTO 46.02 s and 49.00 s at
exact-50 (inside the 45-50 s band) and 53.38 s at exact-200 (inside that scale's
47.6-53.8 s spread), so `simulated_ladder_slice_map.md` §15.6's watch item does
not fire.

The exact-200 row is the one §3 exists for: `required_min` 1856 against a soft
limit of 65536 that only `scripts/ecs_gate.py` set. Under the shell invocation
this entry replaces, that number is where the run would have stopped.

`repository.all` is **92/92** on the Mac and **91/92** on the controller, the
missing one being `product.integration.docker_runtime_contract` - 152 tests,
0 failed, 1 skipped for the absent Docker daemon, which the controller should
not have.

### 5.1 One directory, reported rather than counted as clean

All eight hosts were also asked directly over ssh, outside the product, the way
item 1.6 asked them: **zero `valkey-server` processes and zero `vslab` firewall
rules on all eight**. One host, `vslab-host-a-1`, holds
`/tmp/vslab-load-lane` - **an empty directory**, 4 KB, no children.

It is not new and it is not this item's. Item 1.5 §7.1 made the Load Lane's
remote root run-scoped and made the lane remove what it created - leaf with
`rm -rf`, run-scoped parent with `rmdir`. What survives is the *fixed* root above
that run-scoped parent, which no run owns and which nothing on the host
attributes to one. That is exactly why `_scan_run_residue` does not report it,
and why `found: 0` is truthful rather than convenient: the scan reports what a
run owns, and this is not owned.

Stated here so it is not rediscovered as a surprise: `distributed.safety-and-cleanup`
is green over eight hosts holding no managed process, no run state, no bundle and
no rule, plus one empty directory at a fixed path.

---

## 6. What this item leaves open

1. **The `inventory-and-placement` statement's "local endpoints" clause** (§1.2).
   Reported, not decided; the criterion keeps both checks so no evidence is
   dropped while the question is open.
2. **`real.ecs.*` cannot run from the workstation and cannot be planned to.**
   The fleet manifest lives under `project/artifacts/`, which is gitignored, so
   `fleet_id` is a `string` parameter rather than a `path`: a path parameter is
   validated for existence at plan time and would refuse to plan anywhere but the
   controller. The consequence is that a typo in a fleet id is found by the
   script rather than by the Gate.
3. **Everything item 1.6 left open is still open** and none of it is this item's:
   `run` not classifying a transport failure, a native run's command audit
   recording no ssh, whether the preflight should validate the document the run
   uses, the aborted controller's ssh masters, the resource-to-timeline monotonic
   correlation, a failing run collecting no journals, the absent fault-path
   ownership check, the missing `signalled` count, `SamplerSpec`'s duplication,
   `_state_nodehost` dropping `remote_bundle_dir`, and why the health-gate
   escalation inverts with scale.
