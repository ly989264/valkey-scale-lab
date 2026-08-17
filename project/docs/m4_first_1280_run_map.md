# M4-3: the first real 1280-node run

256 shards x 4 replicas on the twelve `c4a-standard-2` hosts of `gce-m3b`, through
the Gate, from the in-VPC controller. This is the first time this product has run
anything above 200 nodes for real, and the first time it has run a five-member
shard at fleet width.

**Read §2 before reading any result.** Everything it declares was compiled at
`17b2b798` against the real fleet manifest *before* a run was taken, which is the
rule MR-2 and MR-3 established: a quantity predicted after the fact is not a
prediction. §3 is a placement defect the compile found and no run had ever met;
it is not this item's to fix and it changes how §5's fault-lane numbers must be
read.

## §1 What stood between the exception and a Gate run, and why it was one entry

`9d797b80` admitted a real 1280-node run to the *library*:
`is_exact_1280_native_ecs_profile` is the fourth named bounded exception, and
`templates/configs/scale_1280_native_ecs_optin.yaml` is the configuration it
names. `real_execution_above_200_exception_memo.md` §5 records deliberately
*not* registering a catalog entry for it, because an entry nothing has ever
executed is the placeholder the milestone rules forbid. So the executable
boundary stayed where it was: `real.ecs.full-flow` declares `nodes` with
`"maximum": 200`, and no configuration could cross it.

`real.ecs.full-flow-1280` is that entry, and it declares `nodes` with
**`minimum` and `maximum` both 1280**. A range would be wider than the exception
it exists to exercise - the exception names a node count on purpose, and an entry
admitting 30..1280 would let a configuration the exception refuses reach the same
runner. `real.ecs.full-flow` keeps its `maximum: 200` untouched, so every
exact-200 acceptance entry is exactly what it was and M3's milestone is unmoved.

Everything else is `real.ecs.full-flow`'s own argv: `scripts/ecs_gate.py`, which
raises `RLIMIT_NOFILE` toward 65536 and `execv`s the CLI with
`--backend native_multi_ecs`. **No `--profile` flag**, because the run path
resolves `exact-1280` from the node count alone - and because `cli.py`'s
`gate execute --profile` carries a hardcoded `choices` list that does not contain
`exact-1280`, so an entry that passed the flag would be refused by argparse
before anything else ran. That is a latent inconsistency in the CLI, reported
here and not fixed: nothing needs the flag.

**The counts it moved, measured rather than predicted: catalog 99 -> 100, and
nothing else.** `repository.all` is still **92** and the M1 plan still **91**,
because a `real.ecs.*` entry is a `command` runner in neither the
`repository.all` suite nor M1's expansion - the same result `m3_acceptance_
registration_map.md` recorded when it registered three of them. A handover that
says otherwise is quoting the pytest-entry rule.

The entry was deliberately **not** added to the `real.ecs.full-suite` suite.
That suite is the operator-invoked set behind M3's acceptance; adding a
two-hour 1280-node run to it would make an M3 check cost an M4 run.

One regression test guards the boundary in both directions -
`real.ecs.full-flow` must still refuse 1280, and the new entry must refuse 1279
and 1281. It joins `verification/tests/test_contracts.py`, a module the catalog
already registers, so it moves no count. Mutation-checked twice: widening the new
entry's maximum, and widening `real.ecs.full-flow`'s to admit 1280, each make it
fail.

### §1.1 The entry has to assert the operator act, and the first attempt found out how

The entry as first written was `real.ecs.full-flow`'s argv with a wider node
bound, and it **failed in 0.21 s without touching the fleet**. The reason is
correct and is the whole point of the exception:
`local_full_flow_v1.json`'s `scale_policy` sets
`above_200_requires_operator_opt_in` and `above_200_requires_cost_acknowledgement`,
so `GateOrchestrator._execution_permission_failure` refuses any plan above 200
nodes whose request carries neither - and `real.ecs.full-flow`'s argv carries
neither, correctly, because exact-200 is not above 200.

So `scripts/ecs_gate.py` gained two pass-through flags, **off unless an entry
asks for them**, and the 1280 entry asks for them. That keeps
`real.ecs.full-flow`'s argv byte-identical to what every frozen real baseline was
taken under, which the boundary test now asserts in both directions and which is
mutation-checked both ways.

**Reported rather than slipped in, because this is the safety surface the memo
was written about.** `real_execution_above_200_exception_memo.md` §3.2 says
`operator_opt_in` and `cost_acknowledged` are threaded arguments "which no file
can assert about itself - that is what makes it an operator act rather than a
configuration", and a catalog entry is a file. The distinction that survives is
between the run's *configuration* asserting it and the *invocation* asserting it:
the entry is part of the invocation, exactly as `--backend native_multi_ecs`
already is, and a run reaches it only because an operator named the 1280-node
test. What still cannot be self-asserted is what matters - no configuration can
put itself past `is_exact_1280_native_ecs_profile`, and no node count but 1280
can reach this runner.

### §1.2 A Gate-plan refusal reports a traceback instead of a verdict

Found by the same attempt and **reported, not fixed**. When
`_execution_permission_failure` or `_contract_failure` refuses, every lifecycle
step is marked skipped and `GateService.execute` returns a `GateResult` carrying
the real reason - here `REQUEST_OPERATOR_OPT_IN_REQUIRED`, "explicit operator
opt-in is required for this Gate plan". `run_exact_gate` then calls
`adapter.execution_snapshot` unconditionally, which raises
`AdapterOwnershipError: run_id '...' has no adapter execution`, because no step
ever registered one. The `GateResult` is discarded on the way out and
`_write_run_verdict` - the next line - never runs.

So the operator is shown "has no adapter execution" for a run that was refused
for a stated reason, and the refused run leaves **no `run_verdict.json` at all**.
That is the same family as the admission defect closed in 2026-08-13's §12.2
work: a run whose outcome was decided somewhere the reader cannot see. It is not
this item's to close - it is on `run_exact_gate`'s path, which every real run
passes through, so it needs its own change and its own two consecutive real runs
behind it. It affects no passing run, which is why no acceptance to date has met
it.

### §1.3 The reclaim proof had to be told how dense to be

`real_execution_above_200_exception_memo.md` §4 asks for the ownership proof at
the new density *before* a full-flow run, so that a two-hour run failing at
ninety minutes does not leave 1280 processes across twelve hosts with no measured
reclaim behind it. `scripts/native_cleanup_proof.py` hardcoded
`NODES_PER_HOST = 2`, so run as it stood it would have proved reclaim at two
processes a host and said nothing about a hundred.

It now takes `--nodes-per-host`, defaulting to the 2 every prior proof was taken
at. The enumeration itself did not change and did not need to - it walks `/proc`
by working directory and does not care how many it finds - which is exactly why
the number has to be stated rather than assumed: "reclaim works" at two is not
evidence about a run that places a hundred and seven.

## §2 Declared in advance: every quantity, compiled at `17b2b798`

Compiled on the controller against the real `gce-m3b` manifest
(sha256 `e2ea81b2…`, twelve hosts), through `validate_semantics`,
`build_cluster_plan`, the run path's `_node_specs` and `_process_nodehosts`, and
the **real** rolling-restart batcher. Not read off a table.

| quantity | declared |
|---|---|
| semantic errors | **0** |
| nodes / shards / replicas | **1280** = 256 x (1 + 4) |
| nodehosts = hosts | **12**, one per host |
| nodes per nodehost | **107 x 8, 106 x 4** |
| fleet per AZ | **640 / 640** |
| shards sharing a nodehost | **0 of 256** |
| shard AZ split | **3/2, all 256** |
| client ports / bus ports | **7800-9079** / **17800-19079** |
| memory per host | 107 x 64 MiB = **6848 MiB** of 7911 |
| `runtime_fd_limit` `required_min` | **10,624** against `ecs_gate.py`'s 65536 |
| rolling-restart batches, **each** operation | **194**, max concurrent **8** |
| batch sizes, each operation | 8 x 147, 7, 5, 4, 3, 2 x 42, 1 |
| `cleanup_actions` rows | **60** = 5 x nodehosts, native, four kinds |
| Sentinel `canary_count` = shard count | **256** |
| node configs carrying the r>=2 topology pin | **1280 of 1280** |
| `management_command_log` rows, by the MR-2 law | **~21,900** |
| fault lane | **9 scenarios / 12 command rows / 15 windows**, invariant by design |

Two of these disagree with what M4-3 was handed, and the compile is what says so.

**The batch geometry is 194 per operation, not 160.** `m4_density_calibration.md`
§5 compiled 161 per operation for 1280 nodes on *eight* nodehosts, and the
twelve-host handoff carried 320 in total forward unchanged. On twelve it is
**194 and 194, 388 in total**, and the extra 68 are not a rounding difference -
they are 42 batches of **size 2** in each operation's primary pass, for the
reason §3 gives. Duration is roughly unmoved even so, because a batch of 2 is
cheaper than a batch of 8: the density calibration measured 7.75 s per 2-wide
batch against 17.4 s per 8-wide, which puts the management matrix at
**~100 minutes** rather than the 93 the eight-host arithmetic gave.

**`runtime_fd_limit` asks for 10,624, not 10,496.** The memo computed
`nodes*8 + nodehosts*32` at eight nodehosts; twelve adds 128. Still an order of
magnitude under the 65536 `ecs_gate.py` sets, so nothing about the controller
changes - but it is the number that will appear in `resource_preflight.json`.

**This is a new baseline class and is deliberately not diffable against the
frozen pairs.** `artifacts/baselines/real-exact-{50,200}-c58a762a/` are
one-replica runs at 4 and 8 nodehosts. Against them `nodehost_density_plan`,
`state`, every `nodehost_id`, the fault matrix's targets and `cleanup_report`
differ *structurally*, not by drift, and a view score comparing them would carry
no information. MR-3 §10 item 1 already establishes that a multi-replica run
cannot self-calibrate in `fault_matrix` (four candidates, and a different replica
has won every time) and that `management_matrix` cannot on this fleet either. So
the two runs are compared **to each other**, at field level and as a vocabulary
comparison, and not scored against a frozen pair.

## §3 The placement defect the compile found, which no run had ever met

Every declared constraint above holds, and primaries are still not evenly placed:

| | az-a | az-b |
|---|---|---|
| primaries per nodehost | **64, 0, 0, 64, 0, 0** | 22, 22, 21, 21, 21, 21 |

Four of az-a's six nodehosts hold **zero** primaries, and two hold 64 each -
a quarter of the cluster's primaries on one host.

**The cause, read at `nodehost_density.py:_assign_within_az` and confirmed by
compiling the shape.** At one replica per shard the positional round-robin
assignment is used and is even. At r>=2 a shard has several members in one AZ, the
positional assignment would put two of them on one nodehost, and the function
falls back to walking the AZ a shard at a time: each shard's same-AZ members take
consecutive nodehosts from a running cursor, and the cursor advances by the group
size. The majority AZ's group is **3** members at r=4, and a shard's group is
ordered primary-first, so **the primary always lands at `cursor % len`, and the
cursor only ever takes values ≡ 0 (mod gcd(3, nodehosts_in_AZ))**. Six nodehosts
per AZ makes that `{0, 3}`.

The function's own docstring says the walk "keeps the per-nodehost counts within
one of each other", and it does - of *nodes*. It says nothing about roles, and
that is the gap.

**It is general, not a property of 1280.** Compiled across `nodehosts_per_az`
2 through 6 at 256x4, 60x4 and 24x1:

- at **r = 1** it never fires - the positional assignment is used and is even;
- at **r >= 2** it fires whenever an AZ's nodehost count is **divisible by 3**;
- 4 and 5 nodehosts per AZ are even; 3 and 6 are not.

**It never fired before because every fleet this product has ever had was 4
nodehosts per AZ.** MR-2 and MR-3's multi-replica runs were all at 4/AZ, and
`m4_density_calibration.md`'s own 8-host 1280 plan is even at 32 primaries each.
The twelve-host rebuild - taken to remove the memory variable, and it did - moved
the fleet onto the one nodehost count where this shows.

**Two consequences, declared rather than discovered in a diff.**

1. **The primary rolling-restart pass serialises.** One node per nodehost per
   batch means at most 2 az-a primaries can restart together, so once az-b's 128
   are exhausted the remaining 84 az-a primaries go **2 at a time for 42
   batches**. That is the whole of the 160 -> 194 difference.
2. **The fault lane's blast radius is disproportionate.** Target selection takes
   `sorted(nodehost_ids)[0]`, which is `nodehost-az-a-00` - one of the two
   64-primary hosts. So `node_host_stop`, `network_partition`,
   `minority_majority` and `split_brain_detection` each remove **64 of 256
   primaries, 25%**, where the same selection at exact-200 removes 13 of 100.
   `az_stop` pauses all of az-a and so half the primaries, which it would at any
   placement.

**Not fixed here, deliberately.** Spreading the primaries means changing the
walk, and that moves `nodehost_density_plan`, every node's `nodehost_id`, the
fault matrix's targets and the cleanup row ordering on **every** future real run,
one-replica runs included if the fallback's trigger moves. It is a change on a
real run's path and needs its own evidence, which is its own item. The operator
was told before this item ran and chose to take the run as configured, so that
M4's first numbers are the shipped behaviour at shipped knobs on the fleet as
provisioned. What this section buys is that the numbers are read correctly rather
than mistaken for a property of scale.

## §4 The reclaim proof at M4's own density

*(Filled in from the run.)*

## §5 The runs

*(Filled in from the runs.)*

## §6 What M4-2 and the next session inherit

*(Filled in at the end.)*
