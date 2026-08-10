# Slice map: completing the seam — evidence upload and end-of-run cleanup

Roadmap (revision 5.1) item 0.5, from its precondition list. Written **before**
any code, per the roadmap's method rule for this item: derive both boundaries
from the working Docker implementation, and let the derivation — not the
roadmap's summary — decide the API shape.

HEAD when this map was written: `020e0482`.

Predecessors: `runtime_start_slice_map.md`, `cluster_form_slice_map.md`,
`management_matrix_slice_map.md`, `fault_matrix_slice_map.md`. Those four grew
`NodeBackend` from nothing to twenty-one operations. This slice is not a fifth
stage extraction — there is no stage left whose sequencing names a Docker
primitive. It closes two operations §15 names that no stage happened to need.

---

## 0. Verifying the roadmap's claims before deriving anything

The roadmap's deviation rule requires the item's premises to be checked against
HEAD first. Both hold.

**Claim 1 — "the module docstring already claims one [evidence upload]".** True.
`runtime/node_backend.py:15` says a runtime adapter replaces "inventory and
endpoint discovery, process lifecycle, the actuator, sampler deployment and
evidence upload". The protocol below it declares twenty-one operations and none
of them is evidence upload. The docstring is the seam's own statement of §15's
five categories; four are implemented.

**Claim 2 — "`reclaim_run` is *pre-run* cleanup, not teardown".** True.
`reclaim_run` is called exactly twice, both in `runtime/lifecycle.py`: once
inside the `pre_cleanup_by_label` timeline span before the network is created,
and once in `_create_process_scenario`'s failure handler. It returns `None`.
End-of-run cleanup is `docker_runtime.cleanup_scenario`, a module-level function
imported directly by `gates/adapters.py` and `cli_compat.py`. It never sees a
`NodeBackend`.

No deviation. The slice proceeds.

---

## 1. Evidence upload: deriving the boundary from the working Docker case

### 1.1 What the Docker run actually pulls off a host

The question is not "what could be uploaded" but "what does the working
implementation move from a host to the controller today". Three answers, found
by reading every `docker cp` / `docker exec … cat` in the product and then
confirming against a frozen baseline run.

| # | Evidence | How it is pulled today | Where that code lives |
|---|---|---|---|
| 1 | Resource sampler samples | `docker cp <container>:…/resource_samples.json` in `NodehostResourceAgent.stop()` | inside `DockerNodeBackend`'s `ResourceSampler` — **already behind the seam** |
| 2 | memtier JSON + HDR latency files | `docker cp <container>:<remote_dir>/. <artifacts>/load_lane` in `MemtierLoadLane._collect_outputs()` | `observability/load.py` — **outside the seam** |
| 3 | Each node's `valkey.log` | not pulled at all | — |

Measured on `artifacts/baselines/exact-50-6b6f57fd/run-1`: `runtime/load_lane/`
holds 18 files, of which 14 (`memtier_{preflight,formal}.json` and six
`*_latency_*.{hgrm,txt}` per window) exist only because of row 2. The other four
are the host-side stdout/stderr redirects, which never leave the controller.

**Row 1 is done.** Slice 3 put the sampler behind `resource_sampler(...) ->
ResourceSampler`, and the pull is an implementation detail of the object the
backend returns. §15's "本地资源采样器部署" and the upload of what it produced
turn out to be the same seam member; that is why nobody noticed the upload
category was otherwise missing.

**Row 3 is a gap, not an extraction.** Every node is configured with
`logfile <data_dir>/valkey.log` (`_process_config_text`), the path is recorded
in the bundle manifest and in `state.json`, and nothing ever reads it. §15 names
"日志与证据上传"; the 日志 half has no implementation to extract. Adding one is
new behaviour that would change what a run produces, so it is **reported here
and not done in this slice** — see §5.

**Row 2 is the extraction.** It is also the sharper problem, because
`observability/load.py` is a module §15 declares *invariant* across the
migration ("Sentinel 和 Load Lane" is in the unchanged list) and it contains the
literal string `docker` three times.

### 1.2 What the Load Lane actually needs from a runtime

`MemtierLoadLane` takes `container: str | None`. Every use of it:

| Site | Use |
|---|---|
| `paths()` | `remote_dir = None if container is None else f"{container_dir}/{label}"` |
| `command()` | wraps the memtier argv in `["docker","exec",container,"sh","-c", f"mkdir -p {remote_dir} && exec {memtier}"]` |
| `_start()` | `launcher = "docker" if container is not None else self.executable`, for a `shutil.which` preflight |
| `_collect_outputs()` | `docker cp {container}:{remote_dir}/. {artifacts_dir}` |

Reading those four back, the lane needs exactly **two** things from a runtime,
plus one address:

1. **Run this argv somewhere that can route what the cluster announces.** The
   reason is recorded in the class's own docstring and in `Environment facts`:
   in cluster mode memtier follows MOVED to the nodehost addresses on the Docker
   network, and the macOS host cannot route those.
2. **Bring back what it wrote there.** This is §15's 证据上传.
3. **The address of the seed node, from over there.** `_load_lane_seed` returns
   `("127.0.0.1", client_port)` because under Docker the seed node is hosted in
   the same container the lane runs in.

`remote_dir` itself is *not* one of them: `/tmp/vslab-load-lane/<label>` is a
POSIX path the lane chooses for its own output and would choose identically on
an ECS host. It stays in the lane.

The `launcher` is not a fourth thing either. `_start` computes it separately
today and then builds `command`; but `command[0]` *is* the launcher, always and
by construction. Building the command first and checking `command[0]` removes
the member and is strictly more correct — it checks the binary that will
actually be executed.

### 1.3 Shape

One new operation, returning an object, following the precedent
`resource_sampler(...) -> ResourceSampler` set in Slice 3:

```python
def load_lane_host(self, node: dict[str, Any]) -> LoadLaneHost: ...

class LoadLaneHost(Protocol):
    seed_host: str
    def command(self, argv: Sequence[str], *, remote_dir: str) -> list[str]: ...
    def collect_evidence(self, remote_dir: str, local_dir: Path) -> None: ...
```

Why an object and not three flat operations: all three answers are about *one
host chosen for one node*, and a caller that had to hold a handle and pass it
back into three methods would be holding a value it cannot interpret — the
argument that dissolved `peer_address` in Slice 2 and `nodehost_container_name`
in Slice 3, applied in the other direction.

Why `command()` returns the whole argv rather than the backend owning a `Popen`:
the argv is **recorded evidence**. `MemtierLoadLane.finish()` returns
`{"command": process.command}`, which reaches
`scalable_stability_observation.json`. A backend that owned the spawn would
either lose that row or have to hand the argv back anyway. Returning the argv
keeps the recorded command byte-identical under Docker, which is what makes the
diff proof possible.

`seed_host` is an attribute, not a method, for the reason `NodehostAddress`
carries `address`: it is inventory the backend already knows when it picks the
host, not a question to be asked again later.

The lane keeps its `remote_host: LoadLaneHost | None = None` optionality. `None`
means "run memtier here", which is what every hermetic test does and what a
backend whose hosts are locally routable would want. This is the existing
`container is None` branch, unchanged.

### 1.4 What does *not* move

- The memtier argv, its parameters and its QPS rules (§8.1–8.5) — unchanged.
- `_validate_outputs`, `_validate_preflight_logs`, `_read_qps` — verification
  logic, which §15 keeps above the seam.
- `LoadLanePaths` — the lane's own naming of its files.
- `container_dir` — the lane's choice of where its output goes on the host.

---

## 2. End-of-run cleanup: deriving the boundary from the working Docker case

### 2.1 What the working implementation is

`cleanup_scenario(state_path, artifacts_dir, out_path)` in `docker_runtime.py`.
Reached three ways: the Gate's `cleanup` step through
`gates/adapters.py::ProductGateAdapter.cleanup`, the `cli gate cleanup` command
through `cli_compat`, and `_execute_runtime`'s container-path failure handler.

It dispatches on `state["runtime"]["type"] == "docker_process"` into
`_cleanup_process_scenario`, or falls through to a container-path body in the
same function.

### 2.2 The defect this leaves for a second backend, measured

A native run's `state.json` will carry `runtime.type = "native_multi_ecs"`. That
is not `"docker_process"`, so it takes the container-path body, which runs

```
docker ps -a -q --filter label=…run_id=<run>
docker network ls -q --filter label=…run_id=<run>
```

finds nothing owned by that run (there is nothing in Docker), reports
`resources_remaining: []`, `cleanup_errors: []`, and writes
**`status: "PASS"`** — while every remote Valkey process is still running.

That is the concrete thing item 0.5 exists to prevent, and it is why the Gate's
`cleanup` step passing is not evidence of anything on a backend the cleanup path
does not know about. It is reproducible hermetically and a pinning test for it
is part of this slice.

### 2.3 What in `cleanup_scenario` is Docker's and what is not

Line by line across both branches:

**The backend's** — acts on, or observes, host resources:

| Work | Today |
|---|---|
| refuse a container that is not this run's | `_require_cleanup_owned_nodehosts` (`docker inspect` labels) |
| terminate the owned Valkey processes on each host | `terminate_nodehost` (`docker exec sh -c`) |
| confirm those pids are gone | `verify_nodehost_exit` → `_wait_container_pids_gone` |
| confirm no Valkey process remains on each host | `verify_nodehost_empty` (`docker exec` scan) |
| remove the run's owned host resources | `_cleanup_resources_by_label` (`docker stop`/`rm`/`network rm`) |
| scan for residue | `owned_resources` (`docker ps`/`network ls`) |
| the timings around each of those | `cleanup_timing` |

**Not the backend's** — true of any runtime:

| Work | Today |
|---|---|
| read the state file; refuse one without `runtime.run_id` | `cleanup_scenario` head |
| delete `fault_state_*.json` from the artifacts directory | `_cleanup_fault_state_files` (local filesystem only) |
| the `orchestration` capability's extra action and report append | `_append_orchestration_orchestrator_cleanup` |
| assemble the `cleanup_report` artifact and its status | duplicated in both branches |
| write `cleanup_report.json` and `cleanup_report_<scenario>.json` | duplicated in both branches |

This is the same split `stop_node` was derived on in Slice 3: *the backend owns
the mechanism and how it observes it; the lifecycle owns when, and what the
result means.*

### 2.4 Shape — and why it is a new operation rather than reuse

The roadmap explicitly refused to pre-decide this. The derivation says: a new
operation, and `reclaim_run` cannot absorb it.

- `reclaim_run(capability_id, run_id)` is called **before any state exists**. It
  cannot terminate processes by pid because there are none to know.
- It returns `None`. Teardown's whole product is a record — twenty-one action
  rows in a real exact-50 — and §16's cleanup criterion is about that record.
- The two run at different points against different knowledge. Merging them
  would mean either pre-run cleanup pretending to report actions it has no state
  for, or teardown losing its evidence.

So `reclaim_run` keeps its meaning, and gains a docstring line saying which of
the two it is. One new operation joins it:

```python
def release_run(self, state: Mapping[str, Any]) -> RunTeardown: ...

@dataclass(frozen=True)
class RunTeardown:
    actions: list[dict[str, Any]]
    resources_remaining: list[dict[str, Any]]
    timing: dict[str, Any]
    errors: list[str]
```

`state` rather than `(nodes, nodehosts)`: the backend needs its own handles
(`container_name`, `pid`, `nodehost_container_name`) *and* the fact of which of
its two lifecycles produced them, all of which it wrote into that state itself.
Passing the mapping is passing the backend its own bookkeeping back, the same
argument `rejoin_nodehost` was derived on.

`RunTeardown` carries no status. Status is a verdict and stays above the seam.

### 2.5 Where the neutral half lives

`cleanup_scenario` becomes backend-neutral, so it leaves `docker_runtime.py`.
Not into `runtime/lifecycle.py`: that module imports `docker_runtime` at module
scope, and `docker_runtime`'s failure handler calls cleanup, so the pair would
be a cycle — and a deferred import inside an exception handler is the last place
to want one. It goes to a new **`runtime/teardown.py`**, which imports only
`runtime/backends.py` and `runtime/node_backend.py`. Dependency order stays
one-way: `backends` ← `teardown` ← `docker_runtime` ← `lifecycle`.

Backend resolution uses `BackendSpec.node_backend`, the factory
`runtime/backends.py` already declares and **nothing has ever called** —
`_execute_runtime` constructs `DockerNodeBackend()` directly. Teardown becomes
its first consumer.

Which backend: `state["backend_id"]`, falling back to `"docker_container"` when
absent. The fallback is not a preference, it is the behaviour being preserved:
the current code treats a state with no `runtime.type` as the container path,
and three contract tests plus `cli gate cleanup`'s hand-written states rely on
it. Every state a real run writes carries `backend_id`
(`_runtime_state`/`_process_runtime_state` both set it, and `execute_scenario`
sets it again), so no real native run can reach the fallback.

### 2.6 The one status rule that has to be reconciled

The two branches compute `status` differently:

- container: `PASS if not resources_remaining and not cleanup_errors`
- process: the same, **plus** `all(action["status"] != "FAIL")`

One neutral assembler needs one rule. It takes the process rule. This is a
strengthening of the container path's, and it is provably a no-op there, by
enumerating that path's action producers:

| Producer | Statuses it can emit |
|---|---|
| `_cleanup_resources_by_label` | `PASS`, `SKIPPED_WITH_REASON` only |
| the `resource_discovery` failure row | `FAIL`, and always appends to `cleanup_errors` in the same breath |
| `_cleanup_fault_state_files` | `PASS` only |
| the `orchestration` row | `FAIL` iff `resources_remaining` is non-empty |
| `_require_cleanup_owned_nodehosts` | raises; emits no row |

Every `FAIL` a container-path run can produce already forces `FAIL` through one
of the other two terms. A hermetic test pins this rather than leaving it as an
argument.

### 2.7 Action and timing order, which the artifact records

`cleanup_report.cleanup_actions` is an ordered list and is diffed. Preserved
exactly:

- backend actions first, in their existing order (process path: already-absent,
  terminate, verify_exit, verify_no_valkey_processes, container stop/remove,
  network remove);
- then the `fault_state` removals;
- then the `orchestration` row, if any.

`cleanup_timing`: the backend returns its own dict; the assembler applies
`setdefault(k, 0.0)` for the six second-valued keys, which is what the container
path does today and what the process path already satisfies. The process path's
extra `bounded_parallelism`/`parallelism` keys come through untouched, so the
two paths keep their existing — and different — key sets.

---

## 3. What the slice does not change

- No stage's sequencing. This slice touches no lifecycle stage.
- No verdict. `RunTeardown` carries no status; §12.1/§12.2 are untouched.
- The memtier argv, the sampler, the Sentinel lane, RESP.
- `reclaim_run`'s behaviour.
- `fault/sandbox.py` — that is item 0.6, decided separately.

Operation count: `NodeBackend` goes from twenty-one to **twenty-three**.

---

## 4. Proof — measured

Per CLAUDE.md's per-slice acceptance bar. Everything below is a measurement, not
a plan; the bar's items and their results are in §4.2.

### 4.0 What the runs measured

**`./gate suite repository.all` 91/91** on the changed code
(`gate-20260810T104340Z-d44d576c`), and 686 pytest tests passing.

**Two consecutive real exact-50 runs, both PASS**: 909.03s
(`gate-20260810T104851Z-428f8432`) and 836.50s
(`gate-20260810T110415Z-f328b01f`). Both against
`artifacts/baselines/exact-50-6b6f57fd/run-1`:

| Stage | Result | Pass mark |
|---|---|---|
| `runtime_start` | 7/7 identical | 7/7 |
| `cluster_form` | 5/5 identical | 5/5 |
| `management_matrix` | 6/8 identical | 6/8 |
| `fault_matrix` | 5/6 identical | 5/6 |
| `cleanup` (added by this slice) | 2/2 identical | — |

**Identical in both runs**, and each the declared shape rather than merely the
declared count:

- `management_matrix`, both declared components and no third: command-log rows
  1592 → 1606, **+14 exactly**; `cluster_migrate_keys` 4 → 18 (`ded96fac`);
  `owned_valkey_process_remove_nodes_conf` 4 → 0 with
  `owned_valkey_process_discard_prior_state` 0 → 4 (`313cacc9`'s rename, which
  moves no rows). Three row kinds changed, fourteen unchanged.
- `fault_matrix`, the one declared component and no third: confined to
  `fault_sequence`, and within it to the isolated side of exactly the three
  partition scenarios — `minority_majority`, `network_partition`,
  `split_brain_detection`. `isolated_reachable_from_this_side` and
  `isolated_unreachable_reason` added ×3, `isolated_cluster_info` no longer
  observed ×3, `isolated_cluster_state_ok` true→false ×1 (the one scenario where
  the baseline had it true). The `85d5096a` shape.
- The fault lane's three scale-fixed numbers hold: **9 scenarios, 12 command
  rows, 15 workload windows**.

**This slice's own two surfaces, on a real run:**

- `cleanup_report` is **byte-identical to the baseline** under the new neutral
  assembler, in both runs. Moving the report above the seam and the acting below
  it changed nothing a run records — which is what makes this a move.
- `load_lane_evidence` reports **18 files, none empty, both JSON results
  parsing**, identical to the baseline in both runs. The extracted upload
  operation brings back exactly what the `docker cp` inside
  `observability/load.py` used to.

### 4.1 The views detect a defect, not only agree

Calibration first: every stage above is identical **baseline-to-baseline**,
including the new `cleanup` stage at 2/2 and `management_matrix` at 8/8, so no
normalisation here is loose enough to hide a real difference.

Then eight plausible regressions were seeded into a copy of a baseline run and
each had to be caught by the view that owns it. **All eight were detected:**

| Seeded defect | Owning view |
|---|---|
| a `verify_exit` row's status flipped to `SKIPPED_WITH_REASON` | `cleanup_report` |
| a whole nodehost's `terminate` row dropped | `cleanup_report` |
| `cleanup_report_<scenario>.json` diverging from `cleanup_report.json` | `cleanup_report` |
| residue appearing in `resources_remaining` | `cleanup_report` |
| a residual scan's live-pid list emptied | `cleanup_report` |
| the `cleanup` lifecycle step's status flipped to `FAIL` | `lifecycle_timeline:cleanup` |
| an uploaded memtier file missing | `load_lane_evidence` |
| an uploaded memtier file truncated to empty | `load_lane_evidence` |

And a **control**: renumbering every pid in the report while changing nothing
else must *not* fire, and did not. That is what proves the pid-list reduction to
counts is a boundary drawn by what the field is, rather than an exclusion added
until the diff went green — the failure mode Slice 3 recorded.

### 4.2 The rest of the bar

- Targeted hermetic tests added: the native-state cleanup refusal (§2.2), the
  status-rule equivalence (§2.6), the Docker `LoadLaneHost` argv and copy
  pinned where they now live, `_load_lane_seed` asking the backend, and a
  boundary test that `observability/load.py` contains no Docker literal.
- Old paths proven removed: no `docker` in `observability/load.py`, no
  `cleanup_scenario` or `_cleanup_process_scenario` in `docker_runtime.py`, and
  one report assembly rather than two.
- No small-scale smoke stage applies: this slice modifies no lifecycle stage, so
  the bar's "real small-scale smoke of the modified stage" has no target. The
  two exact-50 runs exercise both extracted boundaries end to end.

### 4.3 The diff coverage this slice added

Neither of this slice's two artifact surfaces was covered by
`scripts/diff_stage_artifacts.py` before it. Both are added, because a slice
that cannot be diffed on its own output cannot be proven.

**A new `cleanup` stage** — `cleanup` is one of the twelve
`lifecycle_timeline.json` steps, so this is a real stage entry:

- `lifecycle_timeline:cleanup`
- `cleanup_report` — the whole artifact under the existing scrub, plus the
  per-action volatile fields (pid lists, stdout/stderr) reduced to counts.

**One new reported item under `management_matrix`** — `load_lane_evidence`:
which files arrived under `runtime/load_lane/`, whether each is non-empty, and
whether the two JSON files parse. Reported rather than diffed, and deliberately:
memtier's latency numbers move between runs, and CLAUDE.md's rule is to draw the
boundary by what the field *is* rather than to add exclusions until the diff
goes green. It is a `STAGE_REPORTED` entry, so `management_matrix`'s stated 6/8
denominator is untouched.

---

## 5. Findings this derivation produced, not fixed here

Each is reported rather than acted on, because each would change what a run
produces and so cannot ride inside a proof-by-unchanged-diff.

### 5.1 End-of-run process termination runs against stale pids

Measured on both frozen exact-50 baselines. At cleanup time each of the four
nodehosts has 12–13 live `valkey-server` processes, and **zero of them** is a
pid recorded in `state.json`:

| nodehost | pids in state | live at cleanup | overlap |
|---|---|---|---|
| az-a-00 | 13 | 13 | 0 |
| az-a-01 | 12 | 12 | 0 |
| az-b-00 | 13 | 13 | 0 |
| az-b-01 | 12 | 12 | 0 |

`state.json` is last written before the management matrix, and the rolling
restart plus the fault matrix replace every process. So the `terminate` step
signals fifty pids that no longer exist, `verify_exit` confirms they are gone —
truthfully, and uselessly — and all four `verify_no_valkey_processes` rows come
back `SKIPPED_WITH_REASON` with the live list. The fleet is actually stopped by
`docker rm -f`, one step later.

Under Docker the outcome is still correct, and `resources_remaining` is empty,
so the report says `PASS` and means it. **A backend with no container to remove
has no such backstop**, which is exactly M3's "no managed process or host
resource behind" criterion. Extracting the boundary faithfully preserves the
staleness; fixing it changes `cleanup_report` contents and belongs to its own
commit with its own evidence — most naturally M3 item 1.4, or a Session C
follow-up if the operator wants it before M3.

### 5.2 No node log is ever collected

§15 names 日志与证据上传 as one adapter category. The 证据 half now has a
boundary; the 日志 half has no implementation on either backend. Fifty
`valkey.log` files exist inside the nodehosts of every run and are destroyed
with the containers. Adding collection is new behaviour and a new artifact, so
it wants its own decision — including whether §13's diagnostic escalation is
where it belongs.

### 5.3 `BackendSpec.node_backend` had no consumer

`runtime/backends.py` has declared a `node_backend` factory per backend since
`39e31b1a`, and `_execute_runtime` ignores it, constructing `DockerNodeBackend()`
unconditionally. This slice makes teardown its first consumer. Pointing
`_execute_runtime` at it too is a one-line change with a real behavioural
consequence (it is what makes a second backend selectable at run time as well as
at teardown), so it is named here rather than folded in silently. It belongs to
whoever writes the second backend — M3 item 1.2.
