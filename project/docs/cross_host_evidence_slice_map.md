# Roadmap item 1.3: cross-host evidence

Session M3-A-3. Scope is exactly this item. Written before any code, from the
working Docker implementation, per the project's slice method.

Read `seam_completion_slice_map.md` §1 first: it derived the evidence-upload
boundary this item is the other half of, and its §5.2 is the finding this item
inherits. Read `native_backend_slice_map.md` for the backend and the transport
this item uses.

What this item does **not** own: the stale-pid teardown finding and the residue
scan (item 1.4); the bring-up smoke and all three ladder runs (item 1.5, at its
front by the operator's decision of 2026-08-11); `_check_ports_free`'s loopback
bind and the real transport numbers (M3-B).

---

## 0. Checking the item's premises against HEAD before deriving anything

The roadmap's deviation rule wants the item's stated premises verified first.
Three of the four hold; one is stale in the repository's own notes and one is
sharper than the roadmap knew.

**Premise 1 — "no node log is ever collected".** Holds. Every node is configured
with `logfile <data_dir>/valkey.log` (`_process_config_text`), the path is on the
node record in `state.json` and in each nodehost bundle's `manifest.json`, and
nothing in the product reads it. Measured at HEAD: `log_file` appears as a value
written and never as a value read.

**Premise 2 — "a failed transfer is `ERROR` under the existing §12.1 rule".**
Holds for the Docker backend and **fails for the native one**, which is this
item's sharpest inherited defect and is measured in §7.

**Premise 3 — "evidence/validation.py:41 turns an unreadable artifact into a
FAIL where §12.1 says it is ERROR".** **Stale.** It was fixed at `eb4924db`
(2026-08-09), inside the `ERROR` verdict work: `validate_raw_sources_by_kind`
returns `RawSourceErrors(semantic=..., tool=...)`, and `run_exact_gate` raises
`DockerRuntimeError` for the first and `CollectionError` for the second, in
§12.2's order. CLAUDE.md still lists it as open; that line is wrong and this
item corrects it rather than re-doing the work. Nothing here needs a verdict
semantics change, which is why nothing in §9 is reported under the approval
rule.

**Premise 4 — simulated hosts share a kernel clock so offsets will be ~0.**
Holds, and §2 shows why that is not the obstacle it sounds like: what is
measurable on this fleet is the estimator's own bound, and the bound is what
makes an offset mean anything on a real one.

No deviation. The slice proceeds.

---

## 1. What "complete and attributable" has to mean, derived

M3's criterion names six things - cross-host clocks, process journals, command
logs, evidence transfer, provenance, product bindings - and one adjective pair.
The adjective pair is the whole difficulty: "complete and attributable" is not
checkable until it names what a validator refuses.

So the derivation starts from the working Docker run and asks, of every piece of
evidence a run produces: **on which machine was it produced, and does the run's
own evidence say so?**

### 1.1 The four surfaces, and where each is produced

Measured against `artifacts/baselines/exact-50-6b6f57fd/run-1`, by reading every
producer rather than by reading the artifact names.

| # | Evidence | Produced on | Stamped by whose clock | Says which host? |
|---|---|---|---|---|
| 1 | command logs (`management_command_log.jsonl`, `fault_command_log.jsonl`) | controller | **controller** | no - only `target_logical_id` |
| 2 | resource sampler documents (inside `scalable_stability_observation.json`) | **host** | **host** | no - only `static.sampler_id` |
| 3 | memtier JSON + HDR (`runtime/load_lane/`) | **host** | host (memtier's own) | **no - nothing at all** |
| 4 | node journals (`<data_dir>/valkey.log`) | **host** | host | not collected |

Three facts fall out of that table, and each decides part of the item.

**Command logs are already attributable and already single-clocked.** Every row
is timed by the transport on the controller - `_exec_record` under Docker,
`CommandResult` under the native backend - so a command log is one clock's record
of what the controller asked for, on either backend, and `target_logical_id`
plus the run's own inventory resolves the host. Nothing in this item touches
them. That is worth stating because the criterion names them and the honest
answer is "already true", not "therefore ignore".

**Rows 2 and 3 are host-produced and only incidentally attributed.** A resource
document is attributed by `sampler_id`, which is a *nodehost* id; under Docker a
nodehost is a container and the distinction does not arise, and under a manifest
a nodehost is placed on a named host by `_place_nodehosts_on_fleet`. The load
lane's files carry no attribution of any kind - `runtime/load_lane/` is 18 files
named by window, and which of the four nodehosts memtier ran on is recoverable
only by reading the `command` argv out of the stability observation and
recognising a container name in it.

**Row 4 does not exist.** §15 names 日志与证据上传 as one adapter category; item
0.5 gave 证据 a boundary and found the 日志 half had no implementation to
extract. This is where it gets one.

### 1.2 The definition this item adopts

> An artifact is **attributable** when the run's own evidence names the host it
> was produced on, in the vocabulary the inventory uses (`host_id`), and names
> the offset between that host's clock and the controller's at the time.
>
> A run's host evidence is **complete** when every node that the run observed has
> a journal, every host that carried a nodehost has a clock offset measured at
> both ends of the run, and every host-produced surface is claimed by exactly one
> host.

Both halves are refusable, which is the property the acceptance asks for, and
neither is satisfiable by a run that merely produced files.

Note what this deliberately does *not* say: it says nothing about the offset
being small. A validator that required offsets near zero would be asserting a
property of the fleet - and on this development fleet it would be asserting the
harness. The product requires the offset to be **measured and bounded**; whether
it is near zero is an observation, and §2.4 is where this session observes it.

---

## 2. Cross-host clocks, measured

### 2.1 Why offsets are not ceremony

The reason to measure a host's clock is not that the criterion names it. It is
that **evidence stamped on a host is already being correlated with evidence
stamped on the controller**, today, by code that §11.4 requires:

> timestamps -> 与 actuator、Sentinel、Load、拓扑事件关联

`analyze_resource_samples` implements that in `_event_overlaps`, which asks
whether a controller-recorded timeline event falls inside a host-recorded sample
interval. Under Docker both clocks are behind the same Linux kernel and the
question is at least well posed. Across a fleet it is not: two hosts' wall clocks
drift and the correlation silently attributes a network drop to the wrong window.

§10 records what measuring this found about that correlation *today*, which is
worse than drift and is not this item's to fix.

### 2.2 The estimator

The smallest honest measurement over the transport that already exists, which is
NTP's exchange with the return leg not separately observable:

```
t0    = controller wall clock
host  = one command on the host that prints its wall clock
t1    = controller wall clock
offset      = host - (t0 + t1)/2
uncertainty = (t1 - t0)/2
```

The true offset lies in `[host - t1, host - t0]`, an interval of width equal to
the round trip and centred on the estimate. **The uncertainty is not decoration:
on this fleet it is larger than everything being measured**, and an offset
recorded without it would be a number with no meaning.

Two properties of this estimator matter and both were measured rather than
assumed.

### 2.3 What one exchange costs, and why three are taken

Two simulated hosts (`--fleet-id sim-a --hosts 2`), multiplexed ssh, 2026-08-11.
`k` is how many exchanges are taken per reading, keeping the one with the
smallest round trip - the minimum-delay filter, because the sample that spent
least time in flight is the least biased.

| k | host | offset median | offset range | round trip median | round trip max |
|---|---|---|---|---|---|
| 1 | sim-host-00 | +3.04 ms | +2.26 … **+26.94** | 9.68 ms | **57.45 ms** |
| 1 | sim-host-01 | +2.76 ms | +2.23 … **+26.17** | 8.92 ms | **55.72 ms** |
| 3 | sim-host-00 | +2.34 ms | +2.10 … +3.17 | 8.25 ms | 9.76 ms |
| 3 | sim-host-01 | +2.39 ms | +2.08 … +2.96 | 8.31 ms | 9.49 ms |
| 5 | sim-host-00 | +2.31 ms | +2.16 … +2.74 | 8.15 ms | 8.98 ms |
| 5 | sim-host-01 | +2.26 ms | +2.02 … +2.60 | 7.93 ms | 8.73 ms |

**k=3 is the choice, on the numbers.** A single exchange has a tail: one reading
in twenty came back at 57 ms round trip and 27 ms offset, on hosts whose true
offset is zero. Three exchanges collapse the offset range from 24.7 ms to 1.1 ms
and the worst round trip from 57 ms to 9.8 ms. Five buy a further 0.07 ms and
cost another exchange, so the filter is three. The cost is six commands per host
per run - three at each end - which at exact-200's eight hosts is 48 commands
against the run's own 4,194.

### 2.4 The residual is the estimator's bias, not a skew

The offset does not come out at zero on hosts that share a kernel clock: it comes
out at **+2.3 ms**, consistently, on both hosts. That is not clock skew, it is
the exchange's asymmetry - the outbound leg carries a command through sshd and
forks a shell, the return leg carries a line of text - so the host reads its
clock later than the midpoint of the bracket.

What makes it honest rather than wrong is that it is inside its own bound:
`|+2.3| < 4.1 = round_trip/2`. The measured interval contains zero, which is the
truth about this fleet.

The same estimator over `docker exec` against the same containers, same hour:

| arm | k | offset median | round trip median | bound = rt/2 | offset as % of bound |
|---|---|---|---|---|---|
| multiplexed ssh | 3 | +2.3 ms | 8.3 ms | 4.1 ms | 56 % |
| `docker exec` | 3 | **+19.7 ms** | **51.5 ms** | 25.7 ms | **77 %** |

**The Docker backend's reading is six times less precise than the native one's**,
because `docker exec`'s outbound leg is that much longer than its return. Both
brackets contain zero, which is what this fleet's shared kernel says they must,
but the Docker arm uses three quarters of its own bound to do it. That is a
measured argument for recording the interval rather than the point estimate, and
it is the reason the validator is written against "present and bounded" rather
than against a threshold: a threshold that passed on ssh would fail on
`docker exec` while both were correct.

### 2.4a What the host is asked, decided on the same kind of measurement

Both backends must ask the identical question or the two readings are not
comparable, so the argv is part of the contract. Two candidates, one host,
30 reads each:

| argv | round trip median | min-of-3 median | bound | monotonic resolution |
|---|---|---|---|---|
| `python3` wall + monotonic | 18.33 ms | 17.36 ms | 8.68 ms | full float |
| `sh -c "date; cut /proc/uptime"` | 11.31 ms | 10.44 ms | **5.22 ms** | **10 ms** |

The cheaper arm looks better until its own output is read: `/proc/uptime` prints
hundredths - measured `684.44` against python3's `684.4572976` - so it saves
3.5 ms of bound and gives back **10 ms of quantisation on the very value it
exists to supply**. `python3` also reports `time.monotonic()`, which is the clock
§11.1's sampler stamps its samples with, so the pair it returns is on the same
scale as the evidence the offset is for. Decided: `python3`.

### 2.5 Monotonic clocks are recorded, not compared

A host's `time.monotonic()` and the controller's have unrelated origins - it is a
per-boot counter - so there is no offset between them to measure and none is
claimed. The reading records the host's monotonic value **beside** its wall
clock, so that a host-monotonic timestamp elsewhere in the run's evidence can be
mapped to host wall time and from there, through the offset, to controller wall
time. That chain is what makes §11.4's correlation possible at all; §10 records
that today it is not the chain the correlation actually uses.

---

## 3. Process journals: the mechanism, decided here

The roadmap and both predecessor maps deliberately left this open. Four questions
had to be answered and each is answered from what the working run does.

### 3.1 What the journal is

Valkey's own `logfile`, one per node, at `<data_dir>/valkey.log`. Not a
synthesised artifact: the criterion says *process journals*, the process writes
one, the run configures where, and the run throws it away. There is nothing to
design.

It is opened in append mode and survives the restarts the run performs - the
rolling restart stops and starts every node, and `start_node(fresh_cluster_
identity=True)` removes `nodes.conf` and `dump.rdb` and not the log - so one file
per node holds the whole run.

### 3.2 When it is pulled: once, at the last boundary where it is complete

The roadmap's phrase is "pulls artifacts at stage boundaries". Applied to an
append-only cumulative file that is the wrong reading, and the right one is
derivable: pulling at every boundary re-transfers the same prefix N times and
produces N partial copies that then have to be reconciled, which is the spooling
subsystem the roadmap forbids in the same sentence. **One pull, at the last
boundary at which the journal is both complete and still on the host.**

That boundary is exact: after `write_full_flow_artifacts` (or
`write_management_matrix_artifacts`) returns and before `_create_process_
scenario` returns, which is before the Gate's `cleanup` step and therefore before
`release_run` removes the run's state root. Every stage that touches a node has
finished; nothing has been deleted.

The cost of the alternative is not hypothetical either way, and the cost of this
one was measured: see §11.

**What this does not cover, stated rather than discovered later:** a run that
fails mid-flight loses its journals, because `_create_process_scenario`'s handler
reclaims and re-raises without pulling. That is the same gap CLAUDE.md already
records as the largest remaining piece of §12.2 - every artifact a failing run
leaves says `PASS` or is absent - and it is not this item's to close. It is
noted in §10.

### 3.3 Per node, not per host

One transfer per node journal rather than one directory pull per host. Under
Docker the alternative would be `docker cp <container>:<run_root>/. <local>`,
which brings `dump.rdb` and `nodes.conf` back with it - at exact-50 that is data
the run has no use for and did not ask for. Per node also gives per-node
attribution, which is what "process journals" means when the process is a node.

### 3.4 Where they land

`runtime/node_journals/<host_id>/<logical_id>.log`. The host is in the path
because that is attribution a reader cannot lose, and because on a fleet two
hosts can hold nodes with adjacent logical ids and a flat directory would say
nothing about which machine either came from.

---

## 4. The seam: one new operation, argued

The backend must do two things it cannot do today - read a host's clock, and
fetch a named file from a host. Neither is expressible through the twenty-three.

The temptation is `load_lane_host(node).collect_evidence(remote_dir, local_dir)`,
which would mechanically work: both implementations copy a remote directory to a
local one. It is rejected because it is a lie about what the object is. A
`LoadLaneHost` is *where the Load Lane runs for this node*; using it to fetch a
journal would make the seam's own docstring false, and the native implementation
copies `{remote_dir}/.` wholesale, so it would drag the dataset back with the log.

So: **one new operation, taking the protocol from twenty-three to twenty-four.**
It is argued rather than convenient on three grounds:

1. §15 names 日志与证据上传 as one of the five adapter categories. Item 0.5
   implemented 证据 for the two surfaces that existed and recorded that the 日志
   half had no implementation on either backend. This is that half, in the
   category §15 already assigns to the adapter.
2. Reading a host's clock is not expressible above the seam by construction: the
   controller cannot know what a host's clock says without asking the host, and
   asking is what the adapter is.
3. The shape follows the two precedents exactly rather than inventing one.

```python
def host_evidence(self, nodehost: dict[str, Any]) -> HostEvidence: ...

class HostEvidence(Protocol):
    def clock_exchanges(self, count: int) -> list[dict[str, Any]]: ...
    def collect_node_journal(self, node: Mapping[str, Any], local_path: Path) -> None: ...
```

**Why one object with two methods rather than two flat operations.** The same
argument that made `resource_sampler` one member (deploy the agent and collect
what it wrote) and `load_lane_host` one member (run a command there and bring
back what it wrote): both answers are about *one host*, reached over the one
channel the backend has to it, and a caller holding a handle to pass back into
two operations would be holding a value it cannot interpret. The two verbs here
are literally `LoadLaneHost`'s two verbs - run something there, fetch something
from there - applied to a different subject.

**Why the arithmetic is not in the backend.** `clock_exchanges` returns the raw
brackets - `controller_before_unix_ms`, `host_unix_ms`, `host_monotonic_s`,
`controller_after_unix_ms` - and the lifecycle computes offset, uncertainty and
the minimum-delay selection. Two backends that each computed their own offset
would be two estimators, and §2.4's comparison between them would be comparing
implementations rather than transports. One estimator, above the seam, is what
makes a Docker offset and a native offset the same kind of number.

**Why `collect_node_journal` takes the node and not a path.** Where a node's log
physically lives is the backend's knowledge - the same argument
`start_node(fresh_cluster_identity=True)` was derived on. The node record carries
`log_file`, so the backend reads it and knows how to reach it; the lifecycle
supplies the local destination, which is its own artifact tree.

**Why it takes a nodehost.** A clock belongs to a host, and under this protocol a
nodehost is how the lifecycle names a host it has started something on. That is
the same argument `pause_nodehost` and `isolate_nodehost` were derived on.

---

## 5. Where the lifecycle calls it

Three sites, all in `_create_process_scenario`, none of them a new stage.

| When | What | Why there |
|---|---|---|
| after `nodehost_start` | clock reading, per nodehost | earliest point at which every host is claimed and reachable |
| after the matrices return | clock reading, per nodehost | latest point before teardown; the pair brackets the run |
| after the matrices return | one journal per node | §3.2 |

No new `lifecycle_timeline` step and no new setup-timeline segment. The run's
twelve steps are the scenario definition's and adding a thirteenth would change
what every consumer of `lifecycle_timeline.json` counts, for bookkeeping this
item can record inside its own artifact. The collection's own timing goes in
`host_evidence.json`.

---

## 6. The artifact, and what the validator refuses

### 6.1 `host_evidence.json`

```
artifact_type   host_evidence
schema_version  v1
run_id, status
fleet_id        the manifest's fleet id, or "local" where there is no manifest
hosts[]
  host_id
  nodehost_ids[]
  clock
    start / end
      controller_unix_ms, host_unix_ms, host_monotonic_seconds
      offset_ms, uncertainty_ms, round_trip_ms, exchanges
  journals[]
      logical_id, path, sha256, bytes
  load_lane_dirs[]        which uploaded load-lane directories came from here
  resource_sampler_ids[]  which resource documents came from here
timing
  clock_start_seconds, clock_end_seconds, journal_collect_seconds
```

`load_lane_dirs` and `resource_sampler_ids` are the attribution of §1.1's rows 2
and 3. They are *claims recorded where the choice was made* rather than fields
added to those artifacts: the load lane always seeds from `nodes[0]`
(`_load_lane_seed`) and a resource sampler is created for the nodes of one
nodehost, so in both cases the run knows the host at the moment it picks it, and
writing it into those artifacts instead would move two frozen diff views to
record something the run already knew.

### 6.2 What the validator refuses

`host_evidence.json` joins the scenario definition's declared artifacts, so it is
required raw evidence and reaches the admission provenance graph - which is what
"recorded in provenance" means concretely: the offsets are inside a document
whose digest is bound into `admission.json`.

`validate_raw_sources_by_kind` gains checks that refuse:

- the artifact absent, not `PASS`, or naming another run - already the shape of
  every other declared artifact's check;
- a host with no `host_id`, or two hosts with the same one;
- a nodehost claimed by no host or by two;
- a clock reading missing at either end, or with a non-numeric `offset_ms` or
  `uncertainty_ms` - **an offset without its bound is refused**, per §2.2;
- a node in `run_state.json` with no journal row, or a journal row whose
  `logical_id` is not a node of this run - the "complete" half of §1.2;
- a journal row without a 64-character digest, or naming a file that is not
  under the run's own artifact tree.

Each is a semantic error in `RawSourceErrors.semantic`: these are readings of
evidence that exists and is wrong, not evidence that could not be read. The
kind that could not be read is §7's.

---

## 7. A failed transfer is `ERROR`, and the defect that stops it today

Measured at HEAD, and it is the item's sharpest inherited defect.

`DockerLoadLaneHost.collect_evidence` raises `CollectionError` when
`docker cp` fails. `is_collection_failure` answers `True`, the orchestrator
records `STEP_TOOL_ERROR`, `run_exact_gate` re-raises a `CollectionError`, and
the run reports `ERROR`. That is the path the whole `ERROR` verdict work built
and proved on a staged Docker-daemon failure.

`NativeLoadLaneHost.collect_evidence` calls `MultiplexedSshTransport.get`, which
raises **`TransportError`**, which subclasses `RuntimeError` and nothing else.
`is_collection_failure` answers `False` for it - correctly, since it answers
`False` for anything it cannot place, and calling a cluster failure a tool error
is the direction that loses a finding. So a native evidence transfer that fails
today produces `STEP_EXCEPTION`, and the run reports **`FAIL`**.

That is worse than the silence the acceptance names, and in a specific way:
`FAIL` is the claim that the cluster was observed and found wanting, and what
actually happened is that the controller could not copy a file. §12.1 puts
必要证据无法写入 on the collector's side of the line, without ambiguity.

**The fix is at the site that is actually wrong**, which is not
`is_collection_failure` and not `TransportError`. A transport failure is not
*inherently* a collection failure - `run` carries the fault actuator's commands,
and §9.1 requires an actuator that could not act to report rather than raise, so
widening `is_collection_failure` to cover every `TransportError` would relabel
fault-path failures as tool errors. It is the *evidence* call sites that know
what they were doing: `collect_node_journal` and `collect_evidence` raise
`CollectionError` from the transport failure, exactly as the Docker sibling
already does. Two sites, each one line, each at the point where the code knows
the file it could not fetch was necessary evidence.

No verdict semantics change and nothing here needs the approval rule: §12.1's
rule is unchanged, the classifier is unchanged, and what changes is that one
backend now raises the class the rule was already written for.

---

## 8. Whether a run records that its fleet was simulated

`simulated_host_and_native_bundle_map.md` §3.3 left this to this item, and warned
that a wrong answer makes every simulated result either unattributable or a fact
about the harness. The answer is derived, not chosen:

**A run records which fleet it ran on. It does not record, and must not be able
to record, what that fleet was.**

The harness already settled half of it: `_reject_container_vocabulary` refuses to
write a manifest containing the string `simulated`, so there is no field the
product could read even if it wanted one. The fleet's nature lives in the sidecar
`harness_provenance.json`, which carries `"simulated": true` and which the
product never reads.

What the run *can* record is identity, all of it read from the host rather than
from Docker: `fleet_id`, and per host the `host_id` and the manifest's digest.
`host_evidence.json` carries them. So "was this run's fleet simulated?" is
answerable from the run's own evidence in one deterministic hop - `fleet_id`
joins to the sidecar beside the manifest - and it is answered by the harness,
which is the only thing that knows.

The alternative - a `simulated` flag reaching the product - would be the defect
item 1.0 built `_reject_container_vocabulary` to prevent, arriving through the
evidence layer instead of the inventory layer. And the alternative of recording
nothing would leave a green native exact-50 indistinguishable from an acceptance
run, which is what the roadmap warns about when it says simulated runs are
development evidence only.

**Item 1.5 still owes declaring it.** A baseline frozen from a simulated run
should say so in its `BASELINE.md`, the way both existing baselines say what
commit they were taken at. That is a statement by the person freezing it, which
is the right kind of statement for a fact the product cannot observe.

---

## 9. What this item changes outside itself

Stated in advance so that nothing arrives as drift.

1. `NodeBackend` gains `host_evidence`, and both backends implement it. The
   protocol goes from twenty-three operations to **twenty-four** (§4).
2. `_create_process_scenario` gains three calls and one artifact write (§5).
3. The scenario definition declares `host_evidence.json` as required raw
   evidence, which changes `definition_digest` and adds one admitted artifact
   kind. No existing artifact's shape changes.
4. `validate_raw_sources_by_kind` gains the checks in §6.2.
5. `NativeLoadLaneHost.collect_evidence` raises `CollectionError` (§7).
6. Two new files per run that no diff view covers: `host_evidence.json` and the
   `node_journals/` tree.

**No existing artifact changes**, which is what makes the Docker proof a
five-stage identity rather than a new declared delta. The predicted result of the
acceptance diff is therefore: `runtime_start` 7/7, `cluster_form` 5/5, `cleanup`
2/2, `management_matrix` 6/8, `fault_matrix` 5/6, both existing deltas at their
existing shapes and no third. §11 records whether that held.

---

## 10. Findings this derivation produced and did not fix

### 10.1 The resource-to-timeline correlation compares two unrelated clocks

Found while deriving §2.1, by looking at a baseline rather than at the code.

`_event_overlaps(events, start, end)` keeps a timeline event whose `monotonic`
falls inside a resource sample interval. The sample interval's bounds are the
**host's** `time.monotonic()`, stamped by the sampler inside the nodehost. The
events' `monotonic` comes from the Sentinel and light-probe rows, stamped by the
**controller**. A monotonic clock is a per-boot counter with an arbitrary origin,
so these two are not comparable, and this is structural rather than a matter of
drift.

Measured on `exact-50-6b6f57fd/run-1`, one run, both numbers from the same file:

| | monotonic range |
|---|---|
| resource samples (host) | 1847.93 … 1967.98 |
| Sentinel and light-probe events (controller) | 478.70 … ~600 |

They cannot overlap. So the run's
`timeline_correlation.network_error_or_drop_overlap_count: 0` and
`oom_event_overlap_count: 0` do not mean "no overlap was observed"; they mean no
overlap is expressible. §11.4 requires this correlation and it is not happening.

**Not fixed here, deliberately.** Fixing it changes what
`scalable_stability_observation.json` reports, which is a diff-view surface, and
it needs the offsets this item is introducing before it can be done correctly at
all - the mapping is host monotonic → host wall → controller wall, and the middle
term is exactly §2.5's reading. So this item supplies the input and the
correction is its own change with its own evidence. It belongs to whoever owns
the resource analysis next; it is not item 1.4's and not item 1.5's.

### 10.2 A failing run still collects no journals

§3.2. The one time a node's log is most wanted is the run that failed, and
`_create_process_scenario`'s handler reclaims and re-raises without pulling. This
is the same shape as CLAUDE.md's open §12.2 item - a failing run's artifacts all
say `PASS` or are absent - and closing it needs that item's decision about what a
failing run writes, not a pull bolted into an exception handler.

### 10.3 The load lane's own attribution stays a claim, not an observation

§6.1 records which host the load lane ran on because the run chose it. Nothing
checks that memtier actually ran there. Under either backend the argv in
`scalable_stability_observation.json` names the host or container, so a reader
can check by hand; a validator cannot. Recording the claim is strictly better
than the nothing that is there today, and observing it would mean parsing an argv
to re-derive a value the run already had.

---

## 11. Proof

Per CLAUDE.md's per-slice acceptance bar. §11.0 is what was planned; §11.1
onwards is what was measured.

### 11.0 What has to be shown

- `./gate suite repository.all` green at its new count, with this item's Test
  registered once and the two Gate contract numbers moved with it.
- Hermetic proof of both backends' `host_evidence` against a fake transport: the
  argv, the exchange shape, the journal fetch, and both refusal paths.
- The estimator proven on a real fleet: every measured interval contains zero on
  hosts that share a kernel clock (§2.4), and a deliberately shifted host clock
  falls outside its bound - the second half hermetically, because shifting a
  simulated host's clock would shift the VM's and therefore the controller's.
- The validator proven to refuse each of §6.2's six cases.
- **An induced transfer failure yields `ERROR`**, measured on a real gate
  invocation, not asserted: `Status: ERROR`, `summary.json` overall `ERROR`,
  exit code 0, and the failing stage `ERROR` in `run_verdict.json`.
- Two consecutive real exact-50, diffed against the frozen baseline with the diff
  calibrated baseline-to-baseline first, at §9's predicted marks.

### 11.1 The suite, and the three numbers a registered Test moves

`./gate suite repository.all` **92/92**, from 91. `product.unit.host_evidence`
is registered once, and with it the catalog goes **95 → 96** and the M1 plan
**90 → 91**; both are pinned by `verification/tests/test_contracts.py` and fail
loudly if only the catalog is edited. 780 pytest checks, of which 34 are this
item's.

The scenario definition's own guard fired as designed and is worth naming: the
artifact set, the admitted-kind order and the admission compatibility rules are a
closed registry with a **pinned definition digest**, so adding one artifact was
five coordinated edits and a digest that had to be re-stated deliberately.
`37ae6483…` → `acdcbcfe…`.

### 11.2 An induced transfer failure yields `ERROR`, measured twice

Both arms were induced from *outside* the product - a `docker` shim earlier on
`PATH` that passes every argument through to the real client except the one it is
staging - so no product code has a test hook in it.

**Arm 1, the clock read**, failing right after `nodehost_start`:

```
[1/1] ERROR real.local.full-flow (13.14s)
primary=STEP_TOOL_ERROR:could not read the clock of …nodehost-az-a-00
```

**Arm 2, the journal transfer** - the one the acceptance actually names - on a
run that had already completed formation, the management matrix and the fault
matrix, failing at the collection boundary 696 s in:

```
[1/1] ERROR real.local.full-flow (696.43s)
primary=STEP_TOOL_ERROR:could not copy the journal of shard-0000-primary out of …nodehost-az-a-00
```

Both, identically, in the run's own evidence rather than only in the Gate's:

| | |
|---|---|
| Gate `Status:` | **ERROR** |
| `summary.json` overall / per test | **ERROR** / **ERROR** |
| exit code | **0** - the run wrote a verdict, so it must not fail by exit code |
| `result.json` | `{"status": "ERROR", "summary": …}` |
| `run_verdict.json` | `runtime_start` **ERROR** with the reason; `gate_status` `FAIL` |
| residue | **zero** containers, zero networks |

`gate_status: FAIL` beside `status: ERROR` is correct and not a contradiction:
`GateStatus` is the Gate's own lifecycle result and stays `PASS/FAIL/BLOCKED`,
and the §12.1 *kind* travels in the failure code. `run_verdict` is where §12.2's
vocabulary is applied, and it says `ERROR`.

One pre-existing oddity the runs surface rather than introduce: `stages_not_run`
lists `cluster_form` through `report` as `SKIPPED_WITH_REASON` even though the
work of several of them ran. That is because the whole run happens inside the
Gate's `runtime_start` step, so fail-fast marks the later *projected* steps as
not run. Unchanged by this item and noted so it is not read as a new defect.

### 11.3 Two real exact-50, and what the Docker path did with the change

**PASS 868.18s** (`gate-20260811T032659Z-9e5cd245`) and **PASS 864.61s**
(`gate-20260811T034141Z-35a95abb`). Both 12 of 12 checks OK, `cleanup_report`
PASS with zero residue, and the word `ERROR` in no artifact of either.

Calibrated baseline-to-baseline first, all five stages: `runtime_start` 7/7,
`cluster_form` 5/5, `management_matrix` **8/8**, `fault_matrix` 6/6, `cleanup`
2/2 - so no normalisation here is loose enough to hide a real difference.

Against the frozen `exact-50-6b6f57fd` baseline, **both runs identically**:

| stage | mark | pass mark |
|---|---|---|
| `runtime_start` | **7/7** | 7/7 |
| `cluster_form` | **5/5** | 5/5 |
| `cleanup` | **2/2** | 2/2 |
| `management_matrix` | **6/8** | 6/8 |
| `fault_matrix` | **5/6** | 5/6 |

Both inherited deltas at their declared *shapes*, in both runs, with no third:
command-log rows **1592 → 1606, exactly +14**; `cluster_migrate_keys` **4 → 18**;
`owned_valkey_process_remove_nodes_conf` 4 → 0 with
`owned_valkey_process_discard_prior_state` 0 → 4, a rename that moves no rows;
**three row kinds changed and fourteen unchanged**. Fault lane **9 scenarios / 12
command rows / 15 windows** in both. RTO **46.086 s** and **49.101 s**, inside
the 45-50 s exact-50 band.

So §9's prediction held: this item adds two files and changes none, and the five
stages are identical to what they were before it.

### 11.4 What the two runs measured about the mechanism itself

The parts that only a real run can say, identical in shape across both:

| | run 1 | run 2 |
|---|---|---|
| nodehost rows, each attributed | 4 | 4 |
| `fleet_ids` | `["local"]` | `["local"]` |
| journals collected | **50 / 50** | **50 / 50** |
| journal bytes | 7,944,149 (159 KB mean) | 7,724,102 (154 KB mean) |
| clock readings | 8 (4 hosts × 2 ends) | 8 |
| offset range | +20.9 … +29.7 ms | +21.6 … +25.1 ms |
| uncertainty range | 30.0 … 40.0 ms | 32.0 … 35.5 ms |
| **every interval contains zero** | **yes** | **yes** |
| collection cost | 2.86 s of 868 s (0.33 %) | 2.85 s of 865 s (0.33 %) |

**Every one of the sixteen measured intervals contains zero**, which is the truth
about a fleet whose "hosts" share the controller's kernel. That is the estimator
proven on real hosts; the detection half - a clock that is genuinely elsewhere
falling *outside* its bound - is proven hermetically, because shifting a
simulated host's clock would shift the kernel the controller shares with it.

Two numbers worth carrying forward rather than leaving in a table.

**The offsets are systematically positive and use about 70 % of their bound**,
which is §2.4's exchange asymmetry appearing again under load: the spike measured
+19.7 ms against a 25.7 ms bound on an idle container, and a real exact-50
measures +21 … +30 ms against 30 … 40 ms. Consistent, and it is the reason the
validator asks for a bound rather than a threshold.

**A node journal is about 155 KB at exact-50**, so the whole collection is ~7.8 MB
per run and takes ~1.1 s. Recorded, not resolved: evidence volume stays the
roadmap's open decision point until the end of M3, and the number that decides it
is exact-200's, not this one's.

### 11.5 The rest of the bar

- Hermetic proof against a fake transport: **34 checks**, covering the estimator
  (including a one-minute-fast host falling outside its bound), both backends'
  argv for both verbs, both backends' `CollectionError` on failure, the journal
  layout and digesting, the document's attribution of all three host-produced
  surfaces, and **eleven separate validator refusals**.
- Old path proven removed: there is no old path. The 日志 half of §15 had no
  implementation to replace, and the two `TransportError` leaks are gone from the
  sites that knew the file was necessary evidence.
- Small-scale smoke of the modified stage: the two induced-failure runs at
  exact-30 are it - the second reached the collection boundary through the whole
  management and fault matrices before failing where it was made to.
- exact-200 was **not** run. The bar asks for one where a slice modifies
  `runtime_start`, `cluster_form` or `stabilize`; this item modifies none of them
  - it adds two files at a boundary after the matrices and changes no existing
  artifact, which the five identical stage marks measure. Named here rather than
  quietly skipped.

### 11.6 What this item did not prove

The same honest boundary item 1.2 recorded, narrowed by one step: **no journal
has been fetched off a host over ssh through the product**. The native
`HostEvidence` is proven against a fake transport and its Docker sibling is
proven on real containers, but the ssh path from `start_nodehost` to a collected
journal has not run end to end. That is item 1.5's ladder, and the bring-up smoke
at its front is now the natural place to drive `host_evidence`'s two verbs
alongside the three argv §11 of the native backend map already names.
