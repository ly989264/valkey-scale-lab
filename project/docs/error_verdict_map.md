# Map: the `ERROR` verdict

Written before changing any code, the way the four slice maps were, and argued
from measurement rather than from the two symptoms that motivated the work.
Measured at `81b15931`, 2026-08-09, against the two frozen baselines at
`6b6f57fd` — 168 artifact files across four runs.

This is a semantic change to a validation contract, so the working rules require
reporting before it lands. This map is that report.

## What the work turned out to be

The obvious reading of §16 items 13 and 14 is "the run does not have an `ERROR`
state, so add one". That reading is wrong on the evidence, in both directions.

`ERROR` is not missing. `final_verdict()` computes it correctly, and in a real
exact-50 run it is computed — and then thrown away one statement later:

    docker_runtime.py:8510   stability_result = StabilityWindow(...).run()
    docker_runtime.py:8519   _write_json_artifact(... scalable_stability_observation.json ...)
    docker_runtime.py:8531   if stability_result["status"] != "PASS":
    docker_runtime.py:8532       raise DockerRuntimeError(
    docker_runtime.py:8533           "120-second scalable stability observation failed: " ...

`PASS`, `FAIL` and `ERROR` all take the same branch, and the branch says
*failed*. That raise becomes `GateStatus.FAIL`, then exit 1, then the Gate's
`FAIL`. So the work is not to invent a state; it is to stop discarding the one
state the design already fixed, and to give it a road out.

And in the other direction, the run does not have a `PASS` either — not a
computed one. Every run-level status in the full flow is a literal, or an
expression whose non-`PASS` branch cannot be reached:

| Artifact | Where its `status` comes from | Can it say `FAIL`? |
| --- | --- | --- |
| `lifecycle_timeline.json` | literal `"PASS"`, `gates/real.py:464`; every step row literal `"PASS"`, `:448` | no — the writer raises if a stage span is missing |
| `full_flow_result.json` | expression, `docker_runtime.py:8058` | no — see below |
| `analysis_summary.json` | same expression, `:9579` | no — same reason |
| `scalable_primary_failover_observation.json` | literal `"PASS"`, `:8865`; `failover_success` literal `True`, `:8874` | no — every failure raises first |
| `scalable_stability_observation.json` | `final_verdict()`, the only real one | yes, and `ERROR` too — discarded at `:8531` |

`full_flow_result.json`'s expression is
`all(step PASS) and management PASS and fault PASS`. All twelve step rows are
hardcoded `"PASS"` (`_local_full_flow_lifecycle_steps`, `:9500`), and the
`artifact_validation` stage at `:7945` already raised if either summary was not
`PASS`. So the `else "FAIL"` branch is dead code, and the same is true of
`analysis_summary.json`'s. Confirmed by the artifacts: a failing exact-200 run
writes neither file.

The consequence is measurable. **In a failing run, every product artifact that
survives says `PASS`, and the only thing that says `FAIL` is the Gate's own
`summary.json`, on the strength of an exit code.** Both exact-200 baseline runs:

    exact-200-6b6f57fd/run-1  summary.json  status FAIL   detail "exit code 1"
                              23 json/jsonl files written, of which
                              run_state.json status PASS, state.json PASS,
                              cluster_myslots_report.json PASS,
                              cleanup_report.json PASS, resource_preflight PASS
                              — and no full_flow_result.json at all

So the verdict is not aggregated anywhere. It is a chain of raises with an exit
code at the end. §16 items 13 and 14 are unmet not because a value is missing
from an enum but because there is no aggregation for a value to be missing from.

## Where a verdict is formed today, end to end

Measured by reading each hop and confirming it against the baselines. "Can
express" means values the code at that hop can actually emit, not values its
type would allow.

| Hop | Site | Can express | Measured in the baselines |
| --- | --- | --- | --- |
| check task | `run_check`, `contracts.py:52` | `OK` / `FAIL` / `ERROR` | 10 `OK` per exact-50 run |
| lane aggregation | `final_verdict`, `contracts.py:95` | `PASS` / `FAIL` / `ERROR` + `tool_errors` | `PASS`, `tool_errors: []` |
| — stability lane | `StabilityWindow.run`, `stability.py:43` | all three | `PASS` ×2 runs |
| — resource observation | `run_resource_observation`, `resource_observation.py:21` | all three | **never runs** — see below |
| §9 failover lane | `docker_runtime.py:8865` | literal `PASS`, else raise | `PASS` ×2 |
| stage summary (management) | `:8574` `PASS if all operations PASS else FAIL` | `PASS` / `FAIL` | `PASS` ×2 |
| stage summary (fault) | `:9094` | `PASS` / `FAIL` | `PASS` ×2 |
| stage gate | `artifact_validation`, `:7945` | raise if either is not `PASS` | not taken |
| run artifact | `full_flow_result.json`, `:8058` | `PASS` only (FAIL unreachable) | `PASS` ×2, absent ×2 |
| admission validator | `validate_raw_sources`, `evidence/validation.py:83` | error strings → raise | no errors |
| Gate service | `GateService.execute`, `orchestrator.py:74` | `PASS` / `FAIL` / `BLOCKED` | `PASS` / `FAIL` |
| process exit | `_gate_execute`, `cli.py:468` | `0` / `1` / `2` | `0`, `1` |
| runner | `verification/runner.py:131` | for `result: exit_code`: `PASS` / `FAIL` | `PASS`, `FAIL` |
| gate summary | `_overall_status`, `verification/gate.py:78` | non-milestone: `PASS` / `FAIL` | `PASS`, `FAIL` |

Four things in that table are worth stating separately because they change what
the fix has to touch.

**The resource observation never runs in a full-flow run.** It is the second
`final_verdict` caller, but its only caller is gated on
`_m2_bootstrap_resource_seconds()` (`docker_runtime.py:1312`), which returns
`None` unless an M2 measurement environment variable is set. `find` over all four
baselines returns no `resource_observation.json`. So in a real run there is
exactly **one** reachable `final_verdict` call: the stability window's.

**`GateStatus` has no `ERROR`.** `gates/contracts.py:26` is `PASS`, `FAIL`,
`BLOCKED`, and `GateService.execute` catches *every* exception from a lifecycle
step (`orchestrator.py:74`) and returns `GateStatus.FAIL` unless the failure code
is one of three `BLOCKED` ones. It does, however, already record
`exception_type` on the `FailureInfo` (`orchestrator.py:347`), so the
information needed to tell a `CollectionError` from a semantic failure survives
to the `GateResult` — it is simply not consulted.

**The admission validator is a second hard `PASS` gate, and it is easy to
miss.** `validate_raw_sources` requires `status == "PASS"` on ten named
artifacts, including `full_flow_result.json`, `lifecycle_timeline.json` and
`scenario_results.json`, plus `resource_preflight.json` and a residue-free
`cleanup_report.json`. `run_exact_gate` raises if it returns anything
(`gates/real.py:234`). And `evidence_admission_candidate.schema.json` pins
`status` to `const: "PASS"`. So even if `full_flow_result.json` could say
`ERROR`, this validator would convert it to a raise, and then to `FAIL`. That is
correct behaviour for the *admission* — an admission candidate that is not `PASS`
should not exist — but it means an `ERROR` run has to stop before admission is
attempted rather than flow through it.

**The runner already has `ERROR` and `TIMEOUT`, and the gate already prints
them.** `verification/runner.py` emits `status = "ERROR"` for a process it
cannot start (`:165`), an unreadable JUnit file (`:149`) and a malformed JSON
result (`:143`), and `TIMEOUT` at `:125`. `verification/gate.py:71` colours
`ERROR`. `_overall_status` folds `{BLOCKED, ERROR, TIMEOUT}` into `BLOCKED` —
but only for a milestone selection; for a `test` or `suite` selection it is
`PASS if all PASS else FAIL` and an `ERROR` row would be reported as an overall
`FAIL`. So `ERROR` is representable in `TestResult.status` and in
`summary.json`, and reserved by convention for the harness failing to run a
test, exactly as CLAUDE.md records.

## §12.2's "必要检查" — the set is not derivable, and that is a finding

§12.2 defines aggregation over 全部必要检查. The set is not written down anywhere,
and it cannot be derived from the code, because nothing in the code marks a
check as necessary. What exists instead is four different granularities of
pass/fail row, none of which is a check in §12.1's sense except the first:

| Kind of row | Count in one exact-50 run | Vocabulary |
| --- | --- | --- |
| `CheckResult` (the §12.1 vocabulary) | 10 | `OK` / `FAIL` / `ERROR` |
| lifecycle steps, `full_flow_result.json` | 12 | literal `PASS` |
| measured lifecycle stages, `lifecycle_timeline.json` | 12 | literal `PASS` |
| management operations | 11 | `PASS` / `FAIL` / 5 more |
| fault scenarios | 9 | `REAL_PASS` |
| workload windows | 82 | `PASS` / `FAIL` |
| light-probe node rows | 1053 `OK` | `OK` / `FAIL` |
| Sentinel fault samples | 453 / 465 | `OK` / `FAIL` |
| resource-preflight checks | 15 | `PASS` / `FAIL` |

The ten `CheckResult`s are, verbatim from `run-1`:

    load_preflight  sentinel_prepare  light_start_boundary
    load_formal_window  stability_light_rounds  stability_sentinel_rounds
    resource_analysis:nodehost-az-a-00 …-a-01 …-b-00 …-b-01

That is the whole of the §12.1-shaped check surface in a real run, and it covers
one lane out of five. So **§12.2's necessary set cannot be derived, and the
honest thing is to say so rather than to invent it.**

What *can* be derived is a necessary-evidence set, which is a different thing at
a coarser granularity, and it is already executable in two places:

- `local_full_flow_v1.json` declares 15 required artifacts and 12 lifecycle
  stages. Every one is required: `_write_measured_lifecycle` raises on a missing
  stage span, `load_raw_documents` records an error for a missing artifact.
- `validate_raw_sources` names which of those 15 must carry `status == "PASS"`,
  and adds the streams, the lifecycle ids and the scenario rows.

Recommendation: do not fabricate a check registry. Define §12.2's aggregation
over the *stages* the scenario definition already declares — one verdict per
lifecycle stage, twelve of them, aggregated by §12.2's rule — and let a stage's
verdict be the `final_verdict` of whatever checks that stage runs. That gives
the aggregation a written-down domain that already exists, is already validated,
and is already the unit the diff views and the setup timeline are built on. The
ten `CheckResult`s then aggregate into `management_matrix`'s stage verdict
instead of into a lane artifact nobody reads. What it does not give is
check-level necessity inside a stage; that stays undefined, and should be
recorded as undefined rather than guessed.

## The boundary fork — decided

CLAUDE.md: product code must not import the verification runner; verification
consumes the product from outside. Measured, the boundary is clean in both
directions — `grep` for `from verification` under `src/` and `scripts/` returns
nothing, and `grep` for `valkey_scale_lab` under `verification/` (excluding its
own tests) returns nothing. Whatever this change does must keep that true.

Three ways `ERROR` can cross:

**A — the Gate's result contract grows the status.** Add `ERROR` to
`_read_json_result`'s accepted set (`runner.py:71`) and teach `_overall_status`
that a non-milestone selection with an `ERROR` row and no `FAIL` row is `ERROR`.
Two small edits in `verification/`, plus a row in
`test_command_json_result_contract`. But it is not sufficient on its own:
`real.local.full-flow` declares `result: exit_code`, so it cannot reach
`_read_json_result` at all.

**B — a distinguished exit code.** Teach `runner.py` that for
`result: exit_code`, some code (say 3) means `ERROR`, and have `_gate_execute`
return it. One edit each side, no catalog change. But it encodes a verdict as a
magic integer that nothing declares, in a repository whose whole style is
machine-readable contracts, and it gives the run no place to say *why*.

**C — `real.local.full-flow` changes result type to `json`.** The product writes
`{"status": ..., "summary": ...}` to `{gate.result_path}`; `_read_json_result`
grows `ERROR`; `_overall_status` grows the §12.2 rule.

C is the recommendation, and the deciding evidence is that it is not new
machinery. The catalog census:

    95 tests   91 (pytest, junit)   3 (command, json)   1 (command, exit_code)

The one `exit_code` test is `real.local.full-flow`. Its three siblings —
`real.local.m2-cluster-formation`, `-m2-automatic-failover`,
`-m2-stability-resource` — already declare `result: json`, already take
`--result-path`, and `scripts/m2_performance_gate.py:4754` already has the
`_write_result` helper and a `main` that always exits 0 and lets the file carry
the verdict. So C makes the full-flow test consistent with every other real test
in the catalog rather than introducing a pattern.

C also has the right shape for the admission problem. `_read_json_result` is
only consulted when the process exits 0, so an `ERROR` run must exit 0 and write
its verdict — which forces the CLI to convert a collector failure into a written
result instead of a traceback, which is precisely what §12.1 asks for. And
because the result is written by the CLI, the run can stop before
`validate_admission_sources` and `build_admission_from_sources` are reached, so
no `ERROR` run ever tries to produce an admission candidate whose schema forbids
it.

Note the consequence to state in the change: after C the catalog has zero
`exit_code` tests, while `verification/catalog.py:173` still permits the pairing
and `test_catalog_rejects_invalid_runner_pairs` still pins it. Leave both — the
result type stays supported and unused; removing it would be a separate,
unrelated narrowing of the Gate.

What C does *not* license: the product must not learn what `_read_json_result`
accepts. The product writes the §12.2 vocabulary because §12.2 is the product's
own contract (§15 lists `最终 PASS/FAIL/ERROR 语义` as backend-invariant); the
runner independently accepts that vocabulary. The two agree because the design
document says so, not because either imports the other.

## Collector or tool failure reported as a Valkey semantic failure

§16 item 12 requires that 采集器技术失败、Valkey 语义失败和计划内故障 not be
mistaken for each other. Enumerated by walking what raises and what catches — 80
`except Exception` sites under `src/`, plus every `"FAIL"` literal — not from the
two known cases. Eleven sites survived reading; four dissolved.

### The `MISSING`-topology family is five defects, not one

`_management_live_topology` (`:7685`) drops every node whose light-probe row is
not `OK`. It has ten call sites, and the consequence differs at each:

| Site | What a dropped node does |
| --- | --- |
| `:10919` strict rolling restart | `raise DockerRuntimeError("live role changed … actual=MISSING")` — the known one. A collector gap reported as a role change. |
| `:11138` final placement check | `topology_placement_restored` goes false, feeds `pass_status` at `:11156`, and the operation records `operation_status: FAIL` with `role_placement_restored: false`. **Same defect, second site, and this one does not raise — it writes a false claim into evidence.** |
| `:11211` plan entries | `live_roles` defaults to `"MISSING"`, then raises `"strict rolling restart could not determine live roles"`. Honest message, same cause — worth citing beside `:10919` as the wording the other site should have had. |
| `:7643` reshard slot counts | the dropped primary is silently absent from `counts`, so `_management_matrix_slot_balance` (`:10532`) computes `min`/`max`/`imbalance` over the survivors and reports `PASS`. **A partial collector failure silently changes a measured number.** If every primary drops it returns `status: FAIL, "No primary slot counts were observable"` — a collection failure, labelled `FAIL`. |
| `:9053`, `:10823`, `:11004`, `:11722` | each does `next(node for node in nodes if topology.get(...)["role"] == …)`. A dropped node makes that raise a bare `StopIteration` with no message — the same shape CLAUDE.md already records for `az_stop` at six nodes. Neither `FAIL` nor `ERROR`; an opaque traceback. |
| `:7133` topology snapshot | `except Exception → parsed_nodes = [{"status": MISSING, "reason": repr(exc)}]`. The reason is recorded, which is closer to right, but fifty nodes of evidence collapse to one row and the snapshot's own `status` is untouched. |

So the single fix CLAUDE.md describes covers one of five. All five have one
cause — a probe result being silently equated with cluster state — and one
correct shape, which the repository already has a precedent for: the partition
probe's `isolated_reachable_from_this_side` /
`isolated_unreachable_reason` pair, whose validator (`:9236`) accepts absence
only with a recorded reason and raises otherwise. `_management_live_topology`
should return the unreachable rows with their reason instead of dropping them,
and each caller should decide, explicitly, whether an unreachable node is an
`ERROR` for it.

### The bounded waits label a collector failure `FAIL`

`_wait_process_light_clean` (`:4382`) catches `Exception` — which includes the
`CollectionError` that `LightClusterProbe.run` raises at `cluster.py:375` — and
records `runtime_all_node_light_probe` with `status="FAIL"` and the exception
repr. `_record_timing` is sticky (`:3545`), so the row means "some iteration of
this bounded wait failed", which for a convergence wait is by construction
expected. Measured in the frozen baselines:

    run-1  count=30  status=FAIL  details.error=SemanticFailure("shard-0019-replica-00
           CLUSTER INFO mismatch: cluster_state ok→fail, slots 16384→15729")
    run-2  count=1   status=PASS

Two things follow. First, the two runs genuinely differ, which is why
`cluster_form_timing_rows` already excludes this row from the diff and reports
`count=` / `status=` instead — so this row is a *reported* value, not a diffed
one. Second, `SemanticFailure` and `CollectionError` land in the same handler and
produce the same label, which is the §16 item 12 conflation exactly.
`_run_timed_step` (`:3515`) has the same shape generically.

`_wait_process_predicate` (`:4435`) and `_wait_process_light_clean` (`:4398`)
both stamp `runtime_diagnostic_full_probe` with `status="FAIL"` on their way to
raising. That row is postmortem diagnosis — §13's step 4 — and labelling
diagnosis `FAIL` conflates diagnosis with judgement.

### `_process_node_snapshot` fabricates cluster state from an exception

`:4531`: `except Exception → {"probe_status": "FAIL", "error": repr(exc),
"cluster_state": "unknown", "known_nodes": 0, "slots_assigned": 0, …}`. Every
caller then compares those zeros against expectations
(`:4325`, `_management_matrix_clean_health` at `:11472`), so an unreachable node becomes a
cluster with no slots. This is the mechanism behind the rolling restart's
whole-fleet health gate as well as the convergence waits. §12.1 says a Valkey
refusal *is* a cluster observation, so `probe_status: FAIL` is defensible; the
zeroed fields are not, because they are not observations at all.

### One command-log site conflates the two, and `c3bd05fc` already gave it the tool

`_management_log_node_command` (`:7175`) catches `Exception`, writes
`status: "FAIL"` with the repr in `stderr_tail`, and raises. A `-ERR` reply is
now a distinct `ValkeyErrorReply` after `c3bd05fc`, so a genuine Valkey error and
an unreachable node are distinguishable at that site — and are not
distinguished. The `owned_fault_probe` row at `:9158` has the same shape but
already records `error_type`, so it carries the evidence and just does not act
on it. 1592 rows in `management_command_log.jsonl` per exact-50 run, all `PASS`
in both baselines.

### The evidence layer treats an unreadable artifact as a failed run

`load_raw_documents` (`evidence/validation.py:41`) turns `OSError`,
`UnicodeError` and `JSONDecodeError` into an error string, which
`validate_raw_sources` returns, which `run_exact_gate` raises, which becomes
`FAIL`. §12.1 lists 必要证据无法写入 as 采集工作失败 — an `ERROR` — in as many
words. This is the cleanest, least arguable site in the enumeration and it is
outside `observability/` entirely.

### The actuator, at the one place it is built

`ActuatorRecorder.complete()` raises `CollectionError` before the command row is
appended (`:8729` before `:8730`), so §9.1's `result` is never persisted on the
path where it matters, and the row's `status` is a literal `"PASS"` for the same
reason. Recorded already in CLAUDE.md; confirmed unchanged. The one test that
pins it (`test_scalable_observability.py:1534`) asserts only that a non-`OK`
result raises `CollectionError`, so reordering the append before the raise does
not disturb it.

`sandbox.py:117` is a second actuator with the same defect
(`record["status"] = "FAIL"` on a probe exception). No acceptance bar reaches it;
see "not fixed".

### Four candidates that dissolved on reading

Recording these, because the rule working is part of the map.

- **`ClusterRouter.get` raising `SemanticFailure` for "could not reach a live
  seed"** (`sentinel.py:304`) looked like the worst case in the enumeration: a
  transport failure typed as a semantic one. It is correct. §12.1 says
  *Valkey 拒绝连接、超时…而当前阶段要求它正常：成功观察到集群异常* — a refused
  connection is an observation of the cluster, not a collector failure. The one
  residue is that `last_error` may be a *local* failure (the measured
  `[Errno 49] Can't assign requested address`), and wrapping that in
  `SemanticFailure` is wrong; the cause is preserved via `from last_error`, so
  this is a classification at one site, not a redesign.
- **`FullClusterValidator.run`'s `ConvergenceFailure` retry loop**
  (`cluster.py:850`) looked like a semantic failure being retried, against §13's
  "技术重试与 Valkey 语义失败不能混为一谈". It is not: the retry happens inside
  one check, before any `CheckResult` exists, and `ConvergenceFailure` is
  defined (`contracts.py:22`) as exactly the states a healthy cluster leaves on
  its own. `run_check` never retries a `SemanticFailure`, `ConvergenceFailure`
  included, so once a verdict is formed it is final.
- **`sentinel.py:207` and `:401`, `except SemanticFailure: continue`.** Both are
  inside bounded waits that end in `raise SemanticFailure`. Same argument.
- **`command_recorder.py:146`**, which labels a non-zero `docker` exit `FAIL`,
  is a real conflation but unreached: `run_exact_gate` installs no
  `CommandRecorder`, and no `command_log.jsonl` from that recorder appears in
  any baseline.

### The 462 per-sample `FAIL`s — decided

Measured precisely, and the number is not stable:

| Run | fault-probe samples | of which | lane verdict | RTO |
| --- | --- | --- | --- | --- |
| exact-50 run-1 | 443 `FAIL`, 10 `OK` | 442 `SemanticFailure` on the affected canary, 1 `RespCommandError` | `OK` | 47093.83 ms |
| exact-50 run-2 | 455 `FAIL`, 10 `OK` | 454 `SemanticFailure`, 1 `RespCommandError` on both canaries | `OK` | 47042.55 ms |

The decision: **this is a label defect, not a verdict defect, and it should be
fixed as part of this change rather than held or ignored.** Three reasons, in
order of weight.

1. The repository already has the right word for it, in the sibling observer
   watching the same window. `AffectedShardObserver.sample_round`
   (`failover.py:129`) catches the same class of error during the same failover
   and records `"status": "TRANSIENT"`, with the comment *transient during
   failover is observed data*. Two observers, one window, two vocabularies. That
   is not a reading question; it is an inconsistency with a precedent.
2. The field is not a verdict. `status` here is the predicate the recovery
   streak is computed from (`sentinel.py:532`): `OK` extends the streak,
   anything else resets it. The lane's verdict is the RTO and the streak, and it
   is correctly `OK`. So §12.1's 不逐样本判 `FAIL` is violated in wording, not in
   judgement — which is why it must not be "fixed" by changing the lane.
3. It costs nothing to the acceptance bar. `failover_observation:verdicts`
   already excludes `samples` from `sentinel_fault_probe` (see below), so
   renaming the label moves no diff view.

What it must not become: a warning, a `MISSING`, or anything §12.2's 不使用 list
forbids. `TRANSIENT` is a sample label in an evidence array, not a verdict state,
and adding no new *verdict* state is what §17 requires.

## What §13 rules out

§13 separates formal verdict from diagnosis and forbids arguing a confirmed
`FAIL` back to `OK`. Three concrete prohibitions for this change:

- **No "retry the run" and no post-hoc reclassification.** Once `run_check`
  returns `FAIL`, nothing downstream may look again and soften it. The
  once-only technical retry lives inside `run_check` and nowhere else; a second
  retry loop anywhere in the new aggregation would be a §13 violation even if it
  only ever fired on `CollectionError`.
- **`FAIL` beats `ERROR`, always.** §12.2's fourth clause. A run with one
  confirmed semantic `FAIL` and forty tool errors is `FAIL` with a tool-error
  list — never `ERROR`, never `BLOCKED`, never "inconclusive". `final_verdict`
  already implements this and the new aggregation must reuse it rather than
  re-derive it.
- **Diagnosis must not be labelled.** The postmortem probes
  (`runtime_diagnostic_full_probe`, `_management_errors_by_type`, the batch-3
  `CLUSTER NODES` reads) are §13's escalation steps. Stamping them `FAIL` is
  what makes them look like verdicts. They should carry a diagnostic kind, not a
  status — and, per §13's step 3, they must not be able to change the frozen
  window's verdict.

It also rules out the tempting shortcut of making the stability lane's `ERROR`
into a `BLOCKED`. §12.2's 不使用 list does not name `BLOCKED`, but
`GateStatus.BLOCKED` already means something specific in this repository —
preflight refused to admit the run, no runtime was created — and three
`FailureInfo` codes are wired to it (`orchestrator.py:131`). Reusing it for
"the collector broke mid-run" would erase a distinction the Gate currently
makes correctly.

## Blast radius

**Tests that pin a status.** 31 test files assert a literal `PASS` or `FAIL`
somewhere. The ones that pin the sites this change touches are few:

| Site | Tests |
| --- | --- |
| JSON result status set | `verification/tests/test_executor.py:194` (`[("PASS",0),("FAIL",1),("BLOCKED",1)]`), `:219` (malformed → `ERROR`), `:473` (`BLOCKED` precedence), `:516` (timeout → `BLOCKED`) |
| catalog runner/result pairing | `verification/tests/test_contracts.py:158` |
| `full_flow_result.json` | `tests/provenance/test_exact_gate_measured_sources.py`, `test_exact_gate_scenario_provenance.py`, `tests/scenarios/test_definition_contract.py` |
| admission validator | `tests/evidence/test_evidence_contract.py`, `tests/real_valkey/test_exact_gate.py` |
| `actual=MISSING` / live topology | `tests/integration/test_rolling_restart_scaling.py`, `test_docker_runtime_contract.py` |
| `ActuatorRecorder` | `tests/unit/test_scalable_observability.py:1534` |
| `run_check` / `final_verdict` | `tests/unit/test_scalable_observability.py:978-1017` — already cover all three states |

**Schemas.** 102 status-like enums or consts across 89 artifact schemas.
**Exactly two already allow `ERROR`**, both in
`resource_observation.schema.json` (`/properties/status` →
`[PASS, FAIL, ERROR]`, `/properties/checks/items/properties/status` →
`[OK, FAIL, ERROR]`) — the schema for the artifact that uses `final_verdict`. So
the precedent for the §12 vocabulary exists in the schema layer, in exactly the
right place, and nowhere else. There is **no schema for
`full_flow_result.json`**, `scalable_stability_observation.json` or
`scalable_primary_failover_observation.json`; those three are validated only by
`validate_raw_sources`'s `status == "PASS"` check and by the scenario
definition's artifact list. Whichever artifact grows the run verdict will need
its own enum, and `evidence_admission_candidate.schema.json`'s
`const: "PASS"` must stay as it is.

**Catalog.** One entry changes (`real.local.full-flow`: `result` and two argv
elements). `repository.all` stays 91 pytest tests; `real.local.full-suite` stays
one.

**Artifacts carrying a status at all.** Measured over `exact-50 run-1`: 47 of
the 61 json/jsonl files carry at least one status-shaped field, at 4652 `PASS`,
1053 `OK`, 566 `MISSING`, 446 `FAIL`, 46 `REAL_PASS`, 13
`SKIPPED_WITH_REASON`, 3 `PARTIAL`, 2 `NOT_APPLICABLE` — and **zero `ERROR`,
across all four baseline runs and all 168 files.** That zero is the cleanest
statement of the current state: the value the design fixes has never once been
written.

The other vocabularies are a hazard for this change, not part of it.
`REAL_PASS`, `PARTIAL`, `NO_BASELINE_YET`, `PASS_NOOP_VERIFIED`,
`UNSUPPORTED_WITH_REASON`, `BLOCKED_WITH_REASON`, `DEGRADED_WITH_REASON`,
`MEASURED`, `OBSERVED`, `RETRY` all exist in schemas today. §12.2 forbids
*adding new final states*; it does not require deleting per-row vocabularies
that are not final verdicts. Do not tidy them in this change.

## The acceptance bar

This is not a stage, so the per-slice bar does not apply. It touches artifacts
every stage owns, and the stage-owned views are calibrated against baselines
frozen at `6b6f57fd` that predate it. The bar has to be built the other way
round: from what the views *contain*.

**Which views may move: none.** Measured by running all 27 stage views over
`exact-50 run-1` and extracting every status-shaped value inside each view
output. Every one is `PASS`, `OK`, `MISSING`, `REAL_PASS` or `NOT_APPLICABLE`.
**No view carries a `FAIL` or an `ERROR` in a passing run.** Therefore, on a
passing candidate:

    runtime_start        7/7 identical
    cluster_form         5/5 identical
    management_matrix    6/8 — the +14 cluster_migrate_keys shape from ded96fac
    fault_matrix         5/6 — the 85d5096a partition-side shape

must hold exactly as before, and **any view that moves is a regression**, not
slice drift. That is a stronger and simpler criterion than the stage slices got,
and it is available precisely because a correct `ERROR` change is invisible to a
passing run.

Two views deserve naming because they contain the fields most likely to be
touched by accident:

- `failover_observation:verdicts` compares `actuator` (`target`, `action`,
  `result`), the presence of the three §9.1 timestamp objects, and
  `sentinel_fault_probe` **minus** `samples`, `connection_events`, `rto_ms` and
  `stable_confirmed_at_monotonic`. So fixing §9.1's row ordering must leave
  `actuator.result == "OK"` and the three stamps present, and renaming the
  sample label moves nothing. If the actuator record grows a field, this view
  moves — and that is a legitimate move to declare in advance, not a surprise.
- `management_command_log` compares all 1592 rows including `status`. If
  `_management_log_node_command` starts distinguishing `ValkeyErrorReply` from a
  transport failure, every row in a passing run is still `PASS`, so this view
  must stay identical. It is the best single detector for an accidental
  reclassification of a healthy command.

`STAGE_REPORTED` items are printed, not diffed:
`runtime_all_node_light_probe` (`count=` / `status=`) will read
`status=FAIL` on one baseline and `status=PASS` on the other, and after this
change should read something that is not a verdict at all. Report the change in
that string beside the diff; do not treat its movement as a failure.

**How a real `FAIL` quietly turned into an `ERROR` gets caught.** This is the
risk the whole bar exists for, and no artifact diff can catch it, because a
`FAIL` run writes almost no artifacts. Three checks, none optional:

1. **A hermetic FAIL-beats-ERROR test at the aggregation site.** §12.2's fourth
   clause, driven directly: one confirmed semantic `FAIL` plus one or more
   `CollectionError`s must aggregate to `FAIL` with a non-empty `tool_errors`,
   at every hop that now has an aggregation — stage verdict, run verdict, JSON
   result, `_overall_status`. `final_verdict` already has this test
   (`test_scalable_observability.py:984`); the new hops need theirs.
2. **A hermetic negative test per reclassified site.** For each of the eleven
   sites above, a test that a *semantic* failure at that site still produces
   `FAIL`, paired with the test that a *collector* failure produces `ERROR`.
   Reclassification bugs are one-directional: the danger is the `FAIL` case
   drifting into the `ERROR` branch, so the `FAIL` assertion is the load-bearing
   one and must exist for every site touched.
3. **A real run that must still be `FAIL`.** The clean-room case:
   exact-6 `fault_matrix` reaches `az_stop`'s bare `StopIteration`
   (`single_mac_6node.yaml`, `virtual_az_mode: single`, both nodehosts in
   `az-local`) — a *product* defect on real infrastructure, unreachable by the
   Gate's `minimum: 30` but reachable directly through
   `python3 -m valkey_scale_lab.cli gate execute`. If that run comes back
   `ERROR` after this change, the change has laundered a defect into a tool
   error. It must stay `FAIL`, or, if the `StopIteration` is judged a collector
   failure, the judgement must be argued in writing at that site rather than
   arrived at by a `try/except` widening.

Plus the unchanged floor: `./gate suite repository.all` at 91/91 before
committing, and two consecutive real exact-50 runs after. `exact-200` is not
required — this change touches no stage whose bar demands it, and the two
exact-200 baselines cannot supply the management or fault views at all.

## How an `ERROR` run gets produced at all — honestly

The hard part of this change is not writing it; it is showing it works. Real
runs pass, and there is no way to make a collector fail at fifty nodes on
demand. Stated plainly:

**Hermetic, provable.** `run_check` and `final_verdict` in all three states
(exists). The eleven reclassified sites, each driven with a raising fake
(`CollectionError` on one side, `SemanticFailure` on the other) — the
`NodeBackend` seam and the recording-backend pattern from Slices 1-4 make this
straightforward, and `tests/integration/test_docker_runtime_contract.py` already
drives stages with `run_docker` raising. `_read_json_result` and
`_overall_status` over `{PASS, FAIL, ERROR, BLOCKED}` and their precedence, in
`verification/tests/test_executor.py`, which already builds throwaway catalogs
and one-line command tests. `run_exact_gate` end to end with `execute_scenario`
monkeypatched to raise a `CollectionError`, asserting the written result file
says `ERROR` and no admission candidate exists — the seam
`test_run_exact_gate_uses_compiled_service_then_canonical_admission`
(`tests/real_valkey/test_exact_gate.py:244`) already uses.

**Real, provable.** That a passing exact-50 is unchanged: two runs, 23 of 27
views identical to the frozen baselines with the two known shapes. That a real
`FAIL` is still a `FAIL`: the exact-6 `az_stop` run above. That the `TRANSIENT`
label lands in a real fault window with the lane still `OK` and the RTO still
between 45 s and 50 s.

**Not provable, and to be recorded as such in the change.** That a real
collector failure at real scale produces `ERROR` end to end. The one naturally
occurring instance is the measured `[Errno 49] Can't assign requested address`
at 200 nodes, and `85d5096a` fixed its cause, so it cannot be reproduced without
deliberately reintroducing a socket leak. Two honest partial substitutes, both
worth doing, neither a proof: kill the `docker` daemon mid-run at exact-30 and
assert the verdict is `ERROR` rather than `FAIL` — a tool failure, unambiguously
§12.1's first bullet, and cheap to stage; and delete one required artifact after
the run but before `validate_raw_sources`, which exercises the
`evidence/validation.py` site with a real run's evidence. Say in the commit that
the natural collector failure at scale remains unproven, and do not claim
otherwise.

## Found and deliberately not fixed

- **`scripts/m2_performance_gate.py:4856`** — `except Exception → status "FAIL"`
  at the top level of the three M2 real gates, the same conflation as
  `_gate_execute`'s, in the file that is otherwise the model for the JSON result
  route. M2 is parked; fixing it would drag three parked catalog entries into
  this change.
- **`fault/sandbox.py:117`** — the second Docker actuator, which sets both
  `record["status"]` and `record["observed_impact"]["status"]` to `FAIL` from a
  probe exception. 490 lines, reached only from `cli.py fault apply`/`clear` and
  `compat/`. No acceptance bar exercises it, and CLAUDE.md already lists deciding
  its fate as its own question.
- **`observer/failover_timeline.py`** (`:1338`, `:1367`, and the four
  `PASS if all samples PASS else FAIL` aggregates) — the same sample-label shape
  as the Sentinel probe, in the M2/observer capability, unreached by the
  full-flow lifecycle.
- **`_gate_execute`'s catch list** (`cli.py:486`) folds `OSError` (tool) and
  `ValueError`/`JSONDecodeError` (mostly semantic) into one `return 1`. This one
  *does* have to change for option C to work, but only enough to write the
  result file with the right status — not into a general exception taxonomy for
  the CLI.
- **The other status vocabularies** (`REAL_PASS`, `PARTIAL`,
  `NO_BASELINE_YET`, `PASS_NOOP_VERIFIED`, …). Not final verdicts, not forbidden
  by §12.2, and tidying them would move dozens of diff views for no contract
  gain.
- **`full_flow_matrix.json` / `run_summary.json` / `quant_summary.json` report
  `status: "PARTIAL"`** in a fully passing run (`:9724`). None is in the scenario
  definition's 15 required artifacts, so no validator reads them. Worth its own
  look; not this change.
- **Whether §12.2's aggregation should also cover the resource observation.**
  It is the second `final_verdict` caller and it never runs in a full-flow run.
  Wiring it in is a behaviour change to the bootstrap path with its own
  measurement; the recommendation above deliberately aggregates over stages, and
  the resource observation joins whenever its gate is opened.
- **Check-level necessity inside a stage.** Recommended above to stay
  undefined. Recording it as undefined is the finding; inventing a registry to
  close it would be exactly the kind of fabrication §12.1's
  *采集器只按预先定义的检查规则返回结果* is written against.

## Order of work, when this is approved

Not a plan, a dependency statement — three of these cannot land alone.

1. The vocabulary and the road out: option C, `_read_json_result`,
   `_overall_status`, the CLI writing its result, the schema enum for whichever
   artifact carries the run verdict. Nothing observable changes yet.
2. The aggregation: stage verdicts via `final_verdict`, the run verdict from
   them, `scalable_stability_observation.json`'s `ERROR` stopping being
   discarded at `:8531`. This is the change that makes items 13 and 14 met.
3. The eleven reclassified sites, in one change per cause, not one per site —
   the five `MISSING`-topology consequences are one cause; the bounded waits are
   one; §9.1's actuator ordering is one; `evidence/validation.py` is one.

CLAUDE.md is right that `actual=MISSING` and §9.1's actuator cannot be fixed
alone, and this map narrows why: not because they share a symptom, but because
step 3 has nowhere to send an `ERROR` until steps 1 and 2 exist.

## The `ERROR` verdict is accepted

Six commits, `5b359f00` through `313cacc9`. Measured against the bar this map set
for itself:

| Bar item | Result |
| --- | --- |
| `./gate suite repository.all` | 91/91 before each of the five code commits |
| Diff calibration on the frozen baselines first | `runtime_start` 7/7, `cluster_form` 5/5, `management_matrix` 8/8, `fault_matrix` 6/6 |
| No stage view may move | held: 7/7, 5/5, 6/8, 5/6 in two consecutive runs, both differing views matching their declared shapes |
| Two consecutive real exact-50 | PASS 870.93s and PASS 840.16s, zero residue, `full_flow_result` PASS with twelve steps in both |
| A real `FAIL` must stay `FAIL` | held, by accident rather than design - see below |
| An `ERROR` run produced at all | **held, and unstubbed** - see below |

The two declared deltas, checked by content rather than by view count and
identical in both runs: `management_command_log` grows +14 rows, all
`cluster_migrate_keys` (4 → 18), and exactly four rows change kind and argv with
`313cacc9`'s rename, leaving 14 row kinds untouched; `fault_sequence` keeps all
nine scenario ids and all nine statuses, and the delta stays confined to the three
partition scenarios' isolated side with the other six untouched.

### The part that cannot be claimed as designed

This map said an `ERROR` run at real scale was unprovable, and that a real `FAIL`
staying a `FAIL` would be shown by an exact-6 run. Both statements turned out
wrong, in opposite directions.

**The `FAIL` direction was proven by an accident.** The second real run failed at
397.64s on a `ValkeyErrorReply` - a genuine Valkey semantic failure - and came out
`STEP_EXCEPTION` → `FAIL`, never touching the tool-error branch. That is better
evidence than anything constructible, and it was luck. It remains the only
real-scale instance of the direction that matters most.

**The `ERROR` direction became provable because the enumeration had a hole.**
Looking for the exact-6 case instead found `_require_docker_daemon` raising
`DockerRuntimeError`, so an unreachable daemon - §12.1's 任务未发起, nothing
observed at all - was reported as `FAIL`. Fixed in `40290bee`, and because it can
be staged by pointing `DOCKER_HOST` at a socket that does not exist, it turned the
unprovable item into a measurement: `Status: ERROR`, `summary.json` overall
`ERROR`, exit code 0, no code stubbed and no daemon disturbed.

Why the enumeration missed it is the reusable part. It walked `except` handlers
and `"FAIL"` literals inside the observation code. This site is a plain `raise` in
the gate's preflight that never labels anything `FAIL` itself - it becomes one
only downstream, in `_gate_execute`'s catch tuple. **An enumeration keyed on where
a status string is written cannot see a site that only acquires its status by
propagation.** Any future sweep of this kind needs to walk what reaches each
catch, not only what each catch writes.

### Corrections this work made to the map above

- **The exact-6 clean-room case does not exist.** `local_full_flow_v1.json`
  declares `scale_policy.min_nodes: 30`, so `gate execute` rejects six at plan
  compilation. CLAUDE.md's note that the product does not refuse six is about
  `_full_flow_profile` alone. The run is still real evidence for the `FAIL`
  direction, but it never reaches the fault matrix.
- **The `MISSING` topology defect is five consequences, and the classification
  cannot come from which handler caught it.** A non-`OK` light row is returned
  both when the node never answered and when it answered and disagreed, so the
  §12.1 split had to be derived from the design's own words - a refused connection
  or a timeout is a *semantic* observation - rather than from the code's shape.
- **§12.2's precedence is still not exercised across stages.** The run fails fast,
  so one run never holds both a `FAIL` and an `ERROR`. That needs
  `lifecycle_timeline.json` to outlive a failure, which it does not.

### What defect-seeding caught that calibration could not

Both times, in this work's own tests rather than in the product:

- The first rolling-restart gap test passed with the batch-loop check deleted. It
  covered `_management_matrix_rolling_restart_plan_entries`, not the per-batch
  re-read it was written for.
- The second put the gap on a shard peer, which the per-target check correctly
  ignores, so it still did not reach the site.

With the gap on an actual restart target, deleting the check reproduces the
exact-200 baseline's message verbatim: `strict rolling restart live role changed
for shard-0000-replica-00: planned=replica actual=MISSING`. Two tests that agreed
with their fixes would have shipped as false assurance.
