# The mutation chokepoint and the down-window validation

Written 2026-08-19. Scope was exactly the two items `m4_paid_run_checklist.md` §7
reported and the previous session refused: **F6**, the primary-kill down-window
validation, and **F2**, the management matrix's mutation chokepoint. Both are on
`run_exact_gate`'s path.

No fleet was touched - the 32-host Huawei fleet is suspended for cost, so every
measurement here is local Docker or hermetic. No baseline was frozen, touched or
re-frozen.

Read §1 before §3: the reason each item was refused is a real constraint, and the
fix is shaped by it rather than around it.

## §1 Why each was refused, and what changed the answer

**F6's refusal was that the contract is stated in the code**, three lines above
the call: giving the down-window validation a wait of its own "would nest two
bounded waits and let the fault window run to twice its intended bound", and
`FullClusterValidator.run` answers a zero timeout with "a caller that owns the
waiting asked for a single observation, so report what was seen as it was seen."

That refusal is correct about a *convergence* wait and does not reach a
**transport re-read**, and the distinction is not a matter of naming. It rests on
one property, verified in source rather than assumed:
`is_transient_transport_error` (`observability/contracts.py:83`) is an
**allowlist**, and `SemanticFailure` is excluded by its default rather than by a
branch. So a node answering with the wrong role, the wrong slots or a bad `PING`
carries `transport_transient: False` and is never re-read; only a node that
produced **no observation at all** is asked again. A re-read therefore cannot
turn a still-converging cluster into a pass, which is the failure mode the
nesting objection exists to prevent.

**F2's refusal was that a wrong fix is worse than the bug.** That stands
unchanged and is why the policy is a table rather than a retry. What made it
tractable is that every family's arbiter already exists next door.

## §2 What was measured, and one measurement that was worthless

**The down-window validation has never seen a gap on this workstation.** Across
all 91 retained `scalable_primary_failover_observation.json` files:
`nodes_expected - len(nodes_expected_unavailable) == nodes_observed` in **91 of
91**. So the F6 change is a strict no-op on every run this machine has ever
taken.

**Those 91 runs bound the cost and are not evidence the gap does not happen.**
They are a **survivor sample** for this site: before this change, a run that hit a
persistent transport gap at the down-window raised out of `wait_for_convergence`
and died, so it is not in the retained set as a comparable pass. The right reading
is that the quiet-run cost is zero, which is what the byte-identity argument
needs; the evidence that the benefit case exists is the 1280-node history, not
this sample.

**The first version of that measurement was worthless and is recorded because the
correction matters.** It counted rows with `status != "OK"` in
`full_validation.light_validation.nodes` and found 5,629 rows and zero non-OK.
That number is structurally guaranteed: `LightClusterProbe.validate` returns
`"nodes": [...observations...]`, and `observations` is filtered to `status ==
"OK"`. The artifact **cannot** contain a failed row. Counting absences in a
collection that excludes them proves nothing, and the right quantity is the
expected/observed arithmetic above.

**That correction then found a load-bearing requirement.** Because the killed
node *is* in `self.nodes` and refuses every connection, it produces a
`transport_transient` row on every single run. A re-read that did not exclude
`expected_unavailable` would pay the whole pause budget on **every** run,
re-reading a node the lane deliberately stopped - an unconditional regression in
the fault window, arriving as a change to a measured stage rather than as a test
failure. The exclusion is mutation-checked.

**Extending the down-window validation cannot move a failover metric.**
`_derive_failover_timeline` takes every observation point from
`convergence_result["rounds"]` and `sentinel_result["samples"]`, both recorded
before `full_validation()` is called - `wait_for_convergence` only calls it once
two identical healthy candidate rounds have already been seen. So
`pfail_to_promotion_ms` and `failure_to_client_recovered_ms` are derived from
observations that precede the validation, and the worst case is wall clock added
to the window's tail after RTO is already measured.

Both halves of that are structural rather than observed. `wait_for_convergence`
appends its last round *before* the candidate check and returns `rounds` as-is, so
no code path can add a round after `full_validation()` runs. And the Sentinel
terminates on its own clock from its own samples - `rto_ms` is
`streak_start - fault_monotonic`, and the two futures run concurrently in one
executor, so a slow validation delays the **join**, not the probe. One further
check: `full_validation` is called in the branch that has already decided, and the
180s deadline is tested only at the top of the loop, so a slow re-read cannot turn
an already-converged wait into a deadline failure. The "would nest two bounded
waits" comment therefore stays true - this adds bounded time to a branch that has
already reached its verdict.

**What does span the validation, for the honest list**: everything after
`convergence_future.result()` shifts later - the restore, the recovery validation,
the scenario's own wall and the fault workload windows' walls. All are durations
or timestamps, excluded from every diff view by the standing normalisation, and
none feeds a verdict.

**The fault lane's row count constrains F2's row design**, and this is the fact
§7.2 does not carry. Counted from both frozen exact-50 baselines,
`fault_command_log.jsonl` is 12 rows: `owned_fault_probe` x9,
`actuator_kill_primary` x1, `owned_valkey_process_start` x1 and
**`cluster_replicate_restored_primary` x1**. That last one comes through the
mutation chokepoint, so a design writing one row per attempt would break the
pinned **9 / 12 / 15** invariant the first time a transient fired in the fault
window.

## §3 What changed

### §3.1 F6: a gated transport re-read, opt-in, at one site

`LightClusterProbe` gained `transport_reread_attempts` (default **1**, meaning
ask once - every existing caller is unchanged) and
`_reread_transport_gaps`. `run()` is now collect, re-read the gaps, validate.
`FullClusterValidator` forwards the knob. **One site sets it**: the primary-kill
down-window validation, which keeps `convergence_timeout=0.0`.

Three properties make it a re-read rather than a wait: it is gated on
`transport_transient`, so a semantic answer is never re-asked; it re-reads only
the gapped subset, never the fleet; and its bound is fixed rather than the
convergence deadline. **The accept condition is byte-identical** - a node that
still does not answer leaves a `FAIL` row and `validate` raises exactly as
before. `failure_kind` is untouched, so a timeout remains a §12.1 *semantic*
observation; only the retry axis moves.

### §3.2 F2: a per-family policy table, default raise

`_MANAGEMENT_MUTATION_TRANSPORT_POLICY` keys on `command_kind` at
`_management_log_node_command`. **Ten kinds reach that function** and the set is
closed - re-derived by an AST walk over the whole module, not by grep - with a
regression test asserting the table's keys equal the set of literals found and
that exactly one call passes a non-literal (the pass-through wrapper forwarding
its own parameter). Anything unnamed **raises**, so an eleventh kind is
fail-closed.

| policy | kinds | why |
|---|---|---|
| `reissue` | `cluster_setslot_importing`, `cluster_setslot_migrating`, `cluster_setslot_node`, `cluster_meet_restored_node` | setting the same flag, owner or acquaintance twice is a no-op. Bounded, and **still raises when exhausted**. `MEET` is here because re-issuing is cheaper than its 120s arbiter, not because it lacks one |
| `suppress` | the three `cluster_failover_*`, both `cluster_replicate_*`, `cluster_migrate_keys` | never re-issued; the verify that already follows is the arbiter |

An **error reply is neither retried nor suppressed** on any kind: the node was
reached and will say the same thing again. That falls out of the predicate's
allowlist rather than needing a branch.

**Why `reissue` still raises when exhausted, which is the part that needed
deciding.** `suppress` is only safe where something downstream would notice the
command never landed. For `cluster_setslot_node` the follow-up is
`_management_reshard_node_owns_slot(target, ...)`, which asks the **target** -
so it cannot tell that one of 256 primaries never applied the command.
Suppressing there would let a run continue with a primary holding a stale slot
owner, so the bounded re-issue fails closed instead.

`cluster_meet_restored_node` is the one kind whose filing is a cost judgement
rather than a safety one: `_wait_process_known` does follow it and would notice
`known_nodes` short, so suppress would be *safe* there - it is simply worse, two
seconds of re-issue against two minutes of wait-then-raise, and MEET is
idempotent. Stated because a later reader deciding an eleventh kind by the
`reissue` rule alone would misfile it.

**`FAILOVER` is the trap and it is defused structurally, not by care.** The
chokepoint never re-issues anything in the `suppress` set, so there is nothing to
get wrong by pattern-matching the `SETSLOT` case. Verified per site: all three
`CLUSTER FAILOVER` calls are followed by `_management_wait_node_role`, both
`CLUSTER REPLICATE` calls by `_wait_process_replica_of`, and
`cluster_migrate_keys` sits in a drain loop that re-reads
`CLUSTER GETKEYSINSLOT` every iteration - so the loop *is* the retry and the
raise was the only thing stopping it doing its job.

**One consequence of suppress, accepted rather than hidden.**
`_management_wait_node_role` raises on its deadline and has no branch concluding
"the role never changed". So a genuinely *lost* `FAILOVER` stays run-fatal - it
dies at the wait, later, with a less specific message than today's. That is still
strictly better than dying on a transport failure whose command landed, and the
alternative is the re-issue this family forbids.

**Row accounting.** One row per command, always. `attempt_count` appears only
when a re-issue happened and `retry_eligible` only when a raise was suppressed,
so a command that answered first time writes exactly the row it always wrote -
the `5082e4e8`/F3 principle, and the reason the fault lane's twelve rows do not
move.

**`attempt_count` is reused rather than invented, and that was checked rather than
assumed.** It is already written by three other row builders - measured in the
frozen exact-50 baseline, `actuator_kill_primary` x1 and `owned_fault_probe` x9 in
`fault_command_log`, and `scalable_stability_window` x1 of 1,592 rows in
`management_command_log` - with exactly this meaning, and
`command_log_entry.schema.json` types it `integer, minimum 1` with
`additionalProperties: true` (which is also how F3's `retry_eligible` ships
without being a declared property). So this adds a value to an existing
vocabulary rather than a second name for one concept. Note the consequence:
`diff_stage_artifacts.py`'s own docstring lists `attempt_count` among the fields
that "carry the claim", so a chokepoint row acquiring one **is** a diff finding -
correctly, and only on a run that actually saw a transient.

Three sharper facts about that reuse, each checked rather than inferred:

- **At all three existing sites the value is a hardcoded literal `1`**, paired
  with `retry_index: 0`, as fixed evidence shape - no code path has ever produced
  a value above 1. That is *why* §14.5 measured it "identical throughout". So
  this reuses the field's name and type while being the first to use its
  **range**, and the schema's `minimum: 1`-with-no-maximum has never been
  exercised.
- **It creates a third presence convention.** Legacy rows carry it always
  (constant 1); chokepoint rows carry it only when >= 2; F3's `retry_eligible`
  carries only on the branch that needed it. So on a chokepoint row absence means
  one attempt, and on a legacy row absence never occurs. The byte-identity
  argument decides it - a quiet run must write the row it always wrote - but it is
  written down here so that a later reader does not "fix" the inconsistency in
  either direction and either break quiet-run byte-identity or churn three frozen
  baselines' row shapes.
- **Chokepoint rows gain `attempt_count` without a `retry_index` sibling, and it
  is inert at the *field* level - not, as an earlier draft of this map said, at
  the file level.** That earlier claim was wrong twice and the correction is
  worth more than the fact. `retry_index` is not unconsumed: `analysis/summary.py`
  derives `retry_count` and `retry_commands` from it and `report/render.py` emits
  it in the command CSV and in prose, all reading `command_log.jsonl` - the
  command *audit*, a third file. And the chokepoint's two logs **are** read
  downstream: `evidence/pipeline.py` and `evidence/validation.py` name both files
  literally, and `evidence/pipeline.py` **renames** `management_command_log.jsonl`
  to the stream kind `command_log`, which `analysis/validated.py` then consumes at
  two sites. A grep for the file name in `analysis/` finds nothing precisely
  because of that rename.

  What actually holds is narrower and is the reason the gap is real: **no consumer
  of those two logs reads any of `attempt_count`, `retry_eligible` or
  `retry_index`**, and `_normalize_command` is a passthrough (`dict(row)` plus a
  timestamp backfill), so it neither strips nor inspects them. So a re-issue is
  invisible to the analysis's retry counters - a reporting gap rather than a
  defect, left to whoever wants those counters to span the audit and the two
  command logs alike.

  **One consequence for the declared surface**: because the passthrough carries
  unknown keys, on a *transient* run an `attempt_count >= 2` or `retry_eligible`
  row reaches the validated `admission_v2` stream as well as the two command logs.
  Nothing refuses it - `attempt_count` is a declared schema property and
  `retry_eligible` rides `additionalProperties: true`, which is how F3 already
  ships - and quiet runs stay byte-identical everywhere.

## §4 What was reported rather than fixed

**`is_transient_transport_error` is written against a RESP vocabulary this
transport does not speak.** Every one of the ten mutation kinds reaches the
network through `_node_command` -> `_node_response` -> `_host_command`, which is a
raw `socket.create_connection` plus this module's **own** `_read_resp`. That
parser raises `DockerRuntimeError` for the two truncation cases and for a peer
closing mid-reply (`fp.read(1)` returns `b""` -> `unknown RESP prefix b''`),
where `valkey/resp.py` raises `RespProtocolError` and `EOFError` - and those are
the names the predicate matches. So the predicate's own docstring line "or the
byte stream did not parse" is **false on this path**, and a node dropping the
connection mid-reply classifies non-transient.

Consequences, both stated rather than fixed:

- F2 covers the **measured** failure class - a slow node under gossip load times
  out, and `socket.timeout`/`TimeoutError`/`ConnectionRefusedError`/
  `ConnectionResetError`/`BrokenPipeError` are all matched - and does not cover
  EOF or truncation.
- **F6 does not inherit the gap, and that is why deferring it is safe rather than
  convenient.** `LightClusterProbe` speaks `RespConnection` from
  `valkey/resp.py`, which raises `EOFError` and `RespProtocolError` for exactly
  these cases - the names the predicate matches. The two items sit on opposite
  sides of the boundary: F6 is whole without the vocabulary fix, and F2 is
  under-inclusive rather than wrong with it.
- **The same gap is already live in the landed F3 fix**, whose
  `retry_eligible = is_transient_transport_error(exc)` answers `False` for a
  survivor that closed the connection mid-`FORGET`-reply.

It was not fixed here because the product has **two RESP client implementations
with disjoint failure vocabularies**, and reconciling them is not a change to
make inside a retry item: `RespProtocolError` is a bare `RuntimeError`, not a
`DockerRuntimeError`, so retyping the parser's raises changes what every
`except DockerRuntimeError` on that path catches. It needs its own item and its
own evidence.

**`MIGRATE` carries no `REPLACE`, and the retry has one un-retryable sub-case.**
The argv is `["MIGRATE", addr, port, "", "0", "5000", "KEYS", *batch]`. A
transport failure can leave a key on both nodes, and the re-issued `MIGRATE`
then meets `-BUSYKEY`, an error *reply*, which the policy correctly refuses to
retry - so that sub-case still raises. It is a strict improvement anyway: today a
`MIGRATE` transient is **always** fatal, and after this it is fatal only when the
key actually double-landed. Adding `REPLACE` would fix it and changes the argv,
which `management_command_log` compares field by field, so it is the operator's
call rather than this item's.

**The same one-shot fatality applies to all seven `FullClusterValidator` call
sites, not only the zero-timeout one.** `run()` catches `ConvergenceFailure`
only, so a transport transient raises `SemanticFailure` straight out of every
site regardless of its convergence timeout. F6's scope named the down-window
instance because it is the worst - it runs while the primary is dead and the
fleet is gossiping the failure - but the others share the defect and are merely
less likely to be hit. Reported by operator decision; the mechanism is now in
place should a later item want it.

## §5 Proof

### §5.0 The runs

Four real Docker exact-50, two per commit, each pair at one commit, plus the
isolating diff against the previous commit's own run and - because it is the
check that actually settles the one moving field - the consecutive diff of the
two runs at the same commit.

| commit | run | result |
|---|---|---|
| `52ef2d9c` F6 | A1 | **PASS 904.17 s** |
| `52ef2d9c` F6 | A2 | **PASS 867.09 s** |
| `0b4f0881` F2 | B1 | **PASS 905.58 s** |
| `0b4f0881` F2 | B2 | **PASS 888.16 s** |

All four: `run_verdict` **12/12 OK**, `fault_command_log` **exactly 12 rows** with
its kind census unchanged, `management_command_log` 1,606 rows, **no non-PASS row
in either log**, and **zero artifacts containing the string `ERROR`**.

Scored against the frozen baseline, which calibrates 7/7, 5/5, 8/8, 6/6, 2/2
against itself (re-taken at this HEAD before any candidate), **all four runs give
`runtime_start` 6/7, `cluster_form` 5/5, `management_matrix` 6/8, `fault_matrix`
4/6, `cleanup` 2/2** - the predicted marks, and identical across all four.

**The isolating diffs are empty.** F6 against the previous commit's run: 7/7, 5/5,
**8/8**, 6/6, 2/2 - no differing view at all. F2 against F6's own run: 7/7, 5/5,
**8/8**, 6/6, 2/2 - likewise.

**The one view that ever moves is decided by the consecutive diff.** Both
same-commit pairs (A1 vs A2, B1 vs B2) score `management_matrix` 7/8, and in each
case the entire difference is a **single `stdout_tail`** - the rolling-restart
health gate's retry record, e.g. `retry_count 0 → 1` with `full_probe_count
0 → 50` on one batch - at identical row counts, one changed line in the whole
hunk. Two runs of the *same code* differ in it, so it is a per-run observation
rather than anything either commit did, which is what `BASELINE.md` already says
about that field and why the consecutive diff was worth taking rather than
assumed.

**The F2-specific assertion, scoped so it cannot pass by accident**: across both
F2 runs, of the **1,154 rows** whose `command_kind` is one of the ten the policy
table names, **none carries `attempt_count` or `retry_eligible`**. That is the
quiet-run byte-identity property. It has to be scoped to chokepoint kinds,
because eleven *legacy* rows carry `attempt_count: 1` by construction and a naive
"are the new keys absent" grep hits them and reports a false positive - which it
did, on the first attempt.



- `./gate suite repository.all` **92/92**. Counts unmoved: catalog **100**, M1
  plan **91**. Both items' tests joined `product.unit.nodehost_density`, a module
  the catalog already registers, so no count moves.
- **Ten mutations, ten detected**, each with the mutation **asserted to have
  applied** before its result was trusted and the file asserted reverted
  afterwards.
- Two of those checks earned their place. `F6-1` first reported
  `MUTATION-NOT-APPLICABLE` because its target string occurs twice - `validate`
  carries the same `not in unavailable` clause - so the harness was measuring
  nothing and said so instead of passing. And `F2-2` came back **NOT DETECTED**:
  `test_an_error_reply_is_never_retried_or_suppressed` asserted only that the call
  raised, which stays true when an error reply is re-issued three times and
  raises at the end. The test now asserts the **call count**, because the raise
  alone does not express the doctrine. That is the third session running in which
  a test passed for the wrong reason and only the mutation check said so.

### §5.1 What is vacuous on the workstation

`is_transient_transport_error` names both `TimeoutError` and `socket.timeout`
because they are the same class only from Python 3.10; the workstation is 3.9 and
the controller 3.12. The tests here raise `socket.timeout`-equivalent
`TimeoutError` and `ConnectionRefusedError` directly, so they are meaningful on
both. **No assertion here is vacuous on 3.9** - and one that would be was
deliberately not written: asserting
`is_transient_transport_error(concurrent.futures.TimeoutError())` is `False`
passes trivially on 3.9 and would **fail** on 3.12, where that class *is* the
builtin. The guarantee that no third producer of a pool timeout reaches a retry
is held by the existing AST sweep, not by a type assertion.


## §6 The four follow-up items, 2026-08-19

The operator approved all four open items from §4 and the handoff, and required
that each be designed with the second model before any code. That discussion is
what shaped three of the four; where it changed the answer is recorded here
rather than only the answer.

### §6.1 The parse-failure vocabulary, and a fourth hole the same argument found

`docker_runtime` has its **own** RESP parser, separate from `valkey/resp.py`.
It raised plain `DockerRuntimeError` for truncation and for a peer closing
mid-reply, where `resp.py` raises `RespProtocolError` and `EOFError` - the names
`is_transient_transport_error` matches. So the predicate's own docstring line
"the byte stream did not parse" was **false on this transport**, and both the
mutation chokepoint (§3.2) and the landed FORGET fix gated on it.

**The fix is a class inheriting both**, which none of the three candidates on the
ledger proposed: retype the sites, widen the predicate, or unify the two clients.

```python
class RespTransportError(DockerRuntimeError, RespProtocolError):
```

Measured rather than argued - MRO clean, `is_transient_transport_error` True,
`is_collection_failure` **False**, `isinstance(exc, DockerRuntimeError)` True. So
every existing `except` on this transport catches exactly what it caught (zero
blast radius), the predicate starts matching, and **no §12.1 verdict moves**,
which is what made this an evidence-only change rather than one needing operator
sign-off. Confirmed there is no `except RespProtocolError` or `except EOFError`
anywhere, so no control flow changes either.

**A fourth hole, found by asking what else the same argument covers**: `int()` on
a desynced length line raised a bare `ValueError` at three sites - not even a
`DockerRuntimeError`, so it escaped every handler on this transport *and* the
predicate. Taken in the same commit, because leaving it would make the commit's
own claim false on three lines. The empty-read message also said "unknown RESP
prefix" where the truth is a closed connection.

One class rather than three: truncation, desync and a closed socket mean the same
thing to every caller, none of which distinguishes them by type, and the message
keeps the distinction for whoever reads the row.

### §6.2 Every `FullClusterValidator` site, not just the down-window

`run()` retries only `ConvergenceFailure`, so an unanswered node raises
`SemanticFailure` straight out of **all seven** sites regardless of convergence
timeout. §4 reported this; the operator scoped it out at the time and approved it
now.

**Measured across 140 retained runs and 1,360 light validations at every site:
zero unexplained gaps.** So uniform `transport_reread_attempts=3` costs nothing
on a passing run. Same survivor-sample caveat as §2 - it bounds the cost, it is
not evidence gaps do not happen.

**The structural half the measurement cannot see**, and it answers the "site
inside a convergence loop" worry directly: a transport gap makes `validate` raise
`SemanticFailure`, which that loop does **not** retry, so a persisting gap pays
the re-read budget **once** rather than once per attempt. Only pathological
flapping across attempts could multiply it, and the measurement bounds that.

### §6.3 The audit ledger, made executable past the management lane

The existing AST guard only inspects `_management*` and `_run_scalable*` scopes,
so every other function in the module was exempt **by naming convention** - which
is not a decision anyone took. Widened module-wide, exactly **three** un-retried
reads remain, each safe for a *different* structural reason:

| exemption | why it is safe |
|---|---|
| `_node_command` | the transport primitive itself; retrying inside it would blind-retry every mutation that passes through it - the exact thing §3.2's policy table exists to prevent |
| `_process_node_is_replica_of` | a leaf read whose safety is positional: all three callers bound it in a deadline loop that treats an unanswered probe as "not yet confirmed" |
| `_natural_probe_key_for_primary` | gated by `_m2_measurement_enabled()` at its single call site; never on the full-flow path |

**Deliberately not widened to every read verb.** The `_wait_process_*` predicates
are un-retried by design because their enclosing loop is the retry, and an
AST-only rule that could not see that would grow an exemption list until it meant
nothing. The line that survives is *scope*, not verb - and the `_node_command`
note is the load-bearing one, because it is what stops a later reader "fixing"
the guard by wrapping the primitive.

### §6.4 `MIGRATE` gains `REPLACE`, argued in layers

The committed loop-continue had a sub-case it could not absorb: `MIGRATE` restores
to the target then deletes locally, so a transport failure between those leaves
the key on both nodes, and the re-issue meets `-BUSYKEY` - an error *reply*, which
the policy correctly refuses to retry. The retry died at the failure it existed to
absorb.

**Three independent claims of decreasing logical priority, not one claim at three
strengths.** Each matters only if the one above it fails:

1. **Protocol.** `REPLACE` cannot clobber newer data. `ASK` is issued by the
   source only for a key the source does **not** hold, so a key in the
   both-copies state is served locally and no client is ever redirected to the
   target for it. The target's copy is the one we restored, or older, never
   newer. This is the correctness argument and it stands alone.
2. **Observability.** Even if 1 had a hole, no consumer compares the value of any
   key that can be mid-migration. The one real value comparison is the Sentinel
   canary (`sentinel.py:562`), and canaries are selected inside the fault
   sequence, after all slot movement.
3. **Severity.** Even if a clobber were observed, the data is benchmark filler
   with no consumer that could care.

Claim 2 corrects an earlier draft that said "nothing in this product compares a
value", which is false; what is true is narrower and rests on stage ordering.

**Issued always, not only on the retry.** A retry-only option is a branch that
never runs in a passing run and first executes at 1280 nodes under a gossip
storm - the class of untested path this audit exists to remove.

### §6.5 The delta was rehearsed, which turned a prediction into a measurement

Before the first run: copy a completed run, rewrite its 18 `cluster_migrate_keys`
argvs to insert `REPLACE`, diff the copy. Free, and it produced the exact
rendering the real run would.

**It also caught a second measurement of mine that was too crude.** Comparing raw
argv by kind said the shape was unchanged with and without `REPLACE` - because
raw argv carries the seeded key names and never matches across runs at all. The
tool's own normalised rendering is authoritative and disagrees: those rows *do*
match today and stop matching with `REPLACE`.

Declared in advance from the rehearsal, then met by the real run:

| quantity | declared | measured |
|---|---|---|
| score vs frozen baseline | unchanged | 6/7, 5/5, 6/8, 4/6, 2/2 |
| `REPLACE` insertions in the rendering | 5 | **5** |
| isolating vs predecessor | `management_matrix` 7/8, argv only | 7/8, **10 changed lines, every one `+"REPLACE"`** |
| row counts | unmoved | 1606 / 1606, fault 12 / 12 |

At kind level the inherited summary survives verbatim; the migrate *component*
moves from "4 matching + 14 added" to "4 changed in argv only + 14 added".

### §6.6 A process failure worth more than the item

**Item 2 was committed with a red suite.** Only the unit module and the mutation
harness were run first, not `repository.all`, which the working rules require
*before* a commit. The failure was real: `test_docker_runtime_contract.py:3969`
pins the exact `MIGRATE` argv, and the change breaks it by design.

The shape is the transferable part. The declared-delta discipline enumerated
everything that **reads** the argv - artifacts, views, the classifier, both
backends - and never asked what **asserts** it. Those are different populations,
and the second is one grep: `MIGRATE` across `tests/`, `schemas/`,
`verification/` and fixtures in **all** file types, not only `.py`. Run
afterwards, it returns exactly one executable pin, the one that failed.

Note also that this session's own new test passed throughout, because it asserts
`REPLACE` is present. **A test written to guard a change cannot report what the
change breaks elsewhere** - a different failure from the others collected here,
which were checks that could not distinguish their two cases; this one is a
complete check of the wrong scope.

Fixed by updating the pinned assertion with a comment recording why the position
matters, and **amended into the same commit** rather than added as a follow-up,
because this repo verifies each commit in its own worktree so the series
bisects. Verified the amend touched only the test file, so runs already started
at the pre-amend commit exercise byte-identical product code.
