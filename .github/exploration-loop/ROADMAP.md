# Agent-Looping-Exploration — Roadmap

Status: proposal, 2026-08-29. Companion page: https://claude.ai/code/artifact/7a0b9e09-fe58-4e3f-a47b-ef51b0361a3b
Decisions of 2026-08-29 folded in: continuous modes, plugin agents, autonomy
levels with named human critical points, extraction into a separate project.

## 0. Invariants and review rules

**Invariants.** Frozen. Workers and reviewers cite them; nobody edits them
inside a stage. Changing one is a `DECIDE` for the operator and the only way
the design moves.

1. The kernel lives in `agent-loop` and is generic; this repository holds data only (`.agent-loop/config.yaml`, `.agent-loop/backlog.yaml`).
2. No backlog item is admitted without a probe watched to fail on the current tree.
3. Exactly four terminal states: `PR_READY`, `BLOCKED`, `NO_ITEM`, `INFRA`; every one emits one notification, deduplicated by `(item, state, sha)`.
4. No loop state on GitHub except the PR itself; no labels, markers or control issues.
5. The loop never launches a paid or fleet run; `needs-fleet` items are never selectable.
6. Adapter contract: `run(role, bundle, schema, sandbox, budget) -> AgentResult`; env stripping, bounded context and the single repair live kernel-side.
7. Continuous mode has back-pressure caps (open PRs, non-progress rounds, per-round wall/tokens/one Docker run).
8. Protected-path and delta-shape holds never auto-merge at any level.

**Stage discipline.** A stage does what its bullets say and stops. If the
spec cannot be done as written, the worker records
`deviation: spec said X, built Y, because Z` in the stage record and stops;
an undeclared deviation in the diff is a contract finding.

**Review rules.** The reviewer sees the stage spec and the diff, not the
worker's reasoning; the worker sees only classified findings. Each finding is
one of:

- `contract` - violates a ROADMAP.md line or an invariant; must cite it.
- `defect` - the stage's deliverable does not do what the stage says; must show the failing case.
- `suggestion` - anything else; written to the stage record's deferred list, never acted on in the stage.

A finding without a citation or a failing case is a `suggestion`. Only
`contract` and `defect` send work back. Two review rounds per stage; a third
goes to the operator with both positions.

**Scope first.** The reviewer's first question is whether any hunk in the
diff is required by no stage bullet; each such hunk is
`contract: built beyond spec` and comes back as *remove*. Each stage states
an expected size; a diff well past it is a deviation. A finding that would
grow the diff is a `suggestion` by definition - a review can only move the
code toward the spec.

## 1. What came before, in four generations

| Generation | Mechanism | Produced | Retired because |
|---|---|---|---|
| Hand-audited stages (P00–P46, CML00–15) | Human drives Codex; an audit step decides PASS/FAIL | 73 audits, 73 PASS, 0 rejections | The audit never rejected anything |
| Markdown goal-loop v1 (`codex_goal_loop_m1`) | Nine stages, designer/worker/reviewer subagents, prose checklists | M1 "acceptance" PASS on non-emptiness checks | False PASS |
| Hardening v2 | Machine-checkable contracts C00–C12, claim ledger, fail-closed `BLOCKED_WITH_REASON` | 29 required claims: 0 passed, 29 blocked | Honest, but produced no evidence |
| Local meta-runs v2–v9 | Hash-chained `loop_state.json` | 8 runs, 133 iterations, 9.3 h: 2 real progress, 2 kernel defects, 2 abandoned, 1 pass-by-exhaustion | Kernel was the main failure surface |
| GitHub milestone loop (2026-07-18 → 08-06) | Planner/Worker via `codex exec`, coordinator-only GitHub writes, state rebuilt from Issues/labels/comments, single-use Lease, protected Environment | 500 runs (252 failed); 27 product PRs vs 23 loop-plumbing PRs; 36 % of commits touched `.github/` | 45 % of plumbing commits were state reconciliation and lease repair; one silent stop, never fixed |

The recurring blocker in every generation: real exact-scale evidence needs a
fleet, money and an operator's judgement. No loop could produce it; each got
better only at refusing to fake it.

### Worth keeping from the GitHub loop

- Fail-closed verification bound to `(base, head, tree)`, re-checked before and after merge (`coordinator.py:1808`).
- Planner read-only, Worker in a throwaway worktree, one writer to GitHub (`agent.py:95`).
- Per-role environment stripping (`agent.py:32`, `verifier.py:49`).
- Bounded context that blocks rather than truncates (`context_builder.py:103`).
- Protected-path list enforced at three points; recovery scoped by label (`recovery.py:96`).
- The single-use lease pattern is correct for paid runs — just not worth its cost while paid runs are operator-launched.

### What made it fragile

- GitHub as the state store, by string convention: 10 labels, 11 comment-marker protocols, 23 regexes, a `fullmatch`ed Control Issue body. 18 reconciliation commits in 19 days.
- 25 `collect_snapshot()` re-reads; 82 `LoopBlocked` + 226 `ContractError` raises in 5.8k lines.
- Exact ten-field tool fingerprint (`loop.py:107`) — one line of `environment.json` cost a PR (#24).
- `codex exec --json` stdout framing drove the silence detector.
- Silent terminal states; the 2026-07-20 retrospective's nine requirements were never built.
- Readiness not machine-checkable (M2 promotion item selected before its evidence existed).
- Scope: a milestone-closing autopilot including real runs — where the lease, Environment and 5-day jobs came from.

### Live hazard (as of 2026-08-29) — RESOLVED by Stage 0, same day

On the remote, `milestone-loop.yml` is active on the default branch, runner
`valkey-local` is online as a launchd service, `MILESTONE_LOOP_AUTO_MERGE=true`,
Control Issues #3/#7 open, PRs #90/#92 labelled work-items. The `.disabled`
rename exists only on unpushed `fast-iter`.
**Stage 0 neutralised it the same day: the paragraph above describes the
remote before 2026-08-29 and no longer holds.** The workflow is
`disabled_manually`, `MILESTONE_LOOP_AUTO_MERGE=false`, and every PR and
Issue is closed. The text is kept unedited as the record of what was found;
the Stage 0 record at the end of this file has the after-state and three ways
this paragraph was wrong.

## 2. Reframing

Unit of work: **turn one open question into one merged change with its own
measurement.**

| Concern | Milestone loop | Exploration loop |
|---|---|---|
| Source of work | GitHub Issues + Milestones | `.agent-loop/backlog.yaml`; each item has a probe that fails while open |
| State | Rebuilt from labels/comments | Local JSONL ledger; the PR is the only GitHub-side state |
| Cadence | Dispatch chain | Modes `once` · `continuous` · `schedule` · `until`, with back-pressure |
| Agents | `codex exec` hard-wired | Adapter plugins (`claude-code`, `codex`, `shell`), model per role, escalation ladder |
| Verification | `repository.all` + one target | probe → fix → probe passes → mutation check → focused + `product.unit` → delta shape for Docker items; `repository.all` nightly |
| Merge | Auto-merge after Check | Autonomy level per cost class: L1 human merges, L2 loop merges, L3 loop also admits backlog |
| Real runs | Lease + Environment | Never launched by the loop; it drafts a run plan and asks (`DECIDE`) |
| Stop states | Comment, no ping | Every terminal state → one `FYI` or `DECIDE`, deduped by `(item, state, sha)` |
| Ownership | This repo's `.github/` | Separate `agent-loop` repo; this project holds config + backlog only |

## 3. The finished system

### Shape

```
agent-loop/                      separate repo, pip-installable
  kernel/    pick · worktree · verify · ledger · notify · publish · modes
  agents/    claude-code · codex · shell
  notify/    stdout · file · macos · webhook
  scm/       github (gh) · local-only
  cli        agent-loop run --mode continuous --level L2
             agent-loop status | pause | resume | drill | plan

valkey_scale_lab/                this project: data only
  .agent-loop/config.yaml        agents per role, level per cost class, caps,
                                 protected paths, verify commands, notify targets, branch
  .agent-loop/backlog.yaml       items: statement · probe · proof · cost class · selectable
```

Same split the Gate uses: generic engine (`verification/`) and project data
(`catalog.json`).

### Agent adapter contract

```
run(role, bundle, schema, sandbox, budget) -> AgentResult
  role     planner | worker | reviewer | diagnoser
  sandbox  read-only | worktree-write
  budget   wall_s · silence_s · max_tokens
AgentResult  status ok|malformed|timeout|refused · json · cost · raw_tail
```

Env stripping, bounded context and the single repair round-trip live on the
kernel side, so every adapter inherits them. Per-role choice and escalation are
config (`worker: [claude-code:sonnet-5, claude-code:opus-5]`, `reviewer: codex`).
The `shell` adapter takes the bundle on stdin — how a self-hosted model plugs in.

### Modes and back-pressure

| Mode | Next round starts when | Use |
|---|---|---|
| `once` | never | drills, debugging |
| `continuous` | previous round ended and a trigger fired: backlog edited, PR merged/closed, BLOCKED item reopened, idle timer | normal operation |
| `schedule` | cron | machines that sleep; wall-clock caps |
| `until` | continuous, stopping at N PRs / $ / hours | bounded experiments |

Back-pressure (not optional): cap on open unmerged PRs (default 3); cap on
consecutive non-progress rounds (5 → sleep, notify once); per-round caps on wall
time, tokens, Docker runs (one).

### Autonomy levels and the three critical points

| Level | Loop does alone | Human decides |
|---|---|---|
| L1 assist | opens PR | merge |
| L2 auto | reviewer agent + CI + evidence gate → merges | nothing on the happy path |
| L3 auto+ | also admits backlog items it observed, each with a probe it watched fail | nothing |

Levels are per cost class (`hermetic: L2`, `docker-exact-50: L1`). At every
level three points stay human, arriving as a `DECIDE` notification — one
question, one link, expiring into `BLOCKED`:

1. Money and shared infrastructure — any fleet or paid run, any run above a configured size.
2. Contract and baseline changes — diffs touching protected paths (schemas, design doc, frozen baselines, validation contract) or whose delta shape does not match the declared one. Auto-open, never auto-merge.
3. Widening scope — changing `selectable`, reprioritising, or the plumbing-PR share crossing its threshold.

Everything else is `FYI`. Start at L1 for the first ~5 PRs, then raise.

### One round

```
trigger (continuous / schedule / once)
  0  lock            gate run or session active?           -> INFRA
  1  probes          none failing?                         -> NO_ITEM
                     pick highest-priority failing item; skip BLOCKED-at-this-sha
  2  worktree        explore/<item> from the configured branch
  3  worker          stripped env, bounded bundle; returns diff + test +
                     mutation evidence, or BLOCKED(reason); malformed -> 1 repair -> INFRA
  4  verify          probe passes · reverted fix fails its test · focused + product.unit
                     · docker items: exact-50 run, delta shape vs declared
  5  publish         push branch, open PR (diff explanation + ledger line + evidence)
  6  review          reviewer agent posts one comment; CI runs
  7  merge           L2 and gate green -> squash merge; L1 or protected -> DECIDE
  8  ledger + cleanup + one notification, deduped by (item, state, sha)
```

### What the operator sees

```
FYI     PR_READY  retry-read-broad-except      #104  merged (L2)  38 min  $1.9
DECIDE  transport-rc255-classify  touches schemas/ - merge? [link]  expires 24h
FYI     BLOCKED   preflight-document-choice   "operator's call per CLAUDE.md"
FYI     NO_ITEM   all selectable probes pass
```

Act on `DECIDE` lines and `BLOCKED` reasons. New work enters as an item with a
probe watched to fail. The loop never launches a paid or fleet run.

## 4. Stages

Each stage is a separate operator decision; the state between stages is idle.

### Stage 0 — Make the remote safe; name the new project
Changes GitHub state, needs approval. 1 session, Sonnet 5.
- Disable the workflow on the remote (`gh workflow disable milestone-loop`) or push the `.disabled` rename; `MILESTONE_LOOP_AUTO_MERGE=false`.
- Close PRs #90/#92 and Control Issues #3/#7 with a note pointing here; keep history. Decide the runner's fate.
- Record the target branch (default branch is 232 commits behind `fast-iter` by the 2026-08-13 decision). Create the empty `agent-loop` repository (name, visibility).

### Stage 1 — Backlog as data, with executable readiness
This repo only. 2 sessions: Opus 5 (classify), Fable 5 (probes).
- `.agent-loop/backlog.yaml` from CLAUDE.md "What is still open": id, statement, probe, proof, cost class (`hermetic` / `docker-exact-50` / `needs-fleet`), design-doc section, `selectable`.
- Admission: every probe run on the current tree and seen to fail; a passing probe is rejected, not adjusted. `needs-fleet` → `selectable: false`.
- A check asserts backlog and CLAUDE.md agree; registering it moves catalog and `repository.all` counts by one each.

### Stage 2 — Kernel in the new repo
This project as first consumer. 3 sessions: Opus 5, Fable 5, Opus 5.
- 2a Skeleton: config, pick, worktree, ledger, four terminal states, notify (`stdout`, `file`, `macos`), adapter contract with `claude-code`, `codex`, `shell`; env stripping / bounded context / one-repair ported from old `agent.py` and `context_builder.py`; labelled cleanup from `recovery.py`. Mode `once`. Hermetic tests.
- 2b First real round on a hermetic item, watched; smallest fix at the failing site; mutation evidence verified by hand.
- 2c Two more rounds including a `docker-exact-50` item with the delta-shape check; lock file; tool-version drift as a ledger warning.

### Stage 3 — Publish, review, merge; autonomy levels
Pushes and merges, needs approval once. 1 session, Opus 5.
- `scm/github`: push, PR with diff explanation + ledger line + evidence; reviewer role posts one comment; plain CI (focused + `product.unit` on PR, `repository.all` nightly).
- L1/L2 merge logic with protected-path and delta-shape holds; `DECIDE` with expiry. This project starts at L1.

### Stage 4 — Modes, back-pressure, drills
After three merged PRs. 2 sessions: Opus 5 (drills), Sonnet 5 (modes).
- Drills as tests, each watched to fail first: idempotent re-run; malformed output → one repair → INFRA; BLOCKED notifies once and is skipped; killed worker leaves nothing; wedged Docker → INFRA not retry; open-PR cap → sleep.
- `continuous`, `schedule`, `until`; triggers; caps; `pause`/`resume`; ledger metrics (plumbing share, time-to-notification, cost per merged PR). Raise `hermetic` to L2.

### Stage 5 — Second consumer; L3
When a second project wants it. 1–2 sessions, Opus 5.
- Point `agent-loop` at another repository with only `config.yaml` + `backlog.yaml`; fix whatever leaked from valkey-scale-lab into the kernel.
- L3: planner role proposing backlog items from failing checks and the open list, each with a probe it watched fail.

### Never, at any level
- Launching paid or fleet runs.
- Admitting a backlog item without a watched-to-fail probe.
- Milestone closure — `./gate milestone m4` is the operator's call.

## 5. Sessions and models

| # | Deliverable | Model | Why |
|---|---|---|---|
| 1 | S0 remote safety, new repo | Sonnet 5 | checklist `gh` work |
| 2 | S1a backlog classification | Opus 5 | reads code, writes none |
| 3 | S1b probes watched to fail | Fable 5 | where generation 1 lied |
| 4 | S2a kernel + adapters | Opus 5 | well-specified code |
| 5 | S2b first real round | Fable 5 | v7/v8 died in their first minutes |
| 6 | S2c more rounds, Docker, lock | Opus 5 | iteration |
| 7 | S3 publish/review/merge, levels | Opus 5 | merge logic carries risk |
| 8 | S4a drills | Opus 5 | adversarial tests |
| 9 | S4b modes, back-pressure, metrics | Sonnet 5 | configuration |
| 10 | Reserve: first-week diagnosis | Fable 5 | defect class before any fix |
| 11 | Reserve: docs into CLAUDE.md | Sonnet 5 | under 40 lines |
| 12–13 | S5 second consumer, L3 | Opus 5 | generalisation |

Inside the loop the worker defaults to Sonnet 5, escalating to Opus 5 on
retry; a backlog item's cost class may carry a model override.

## 6. Session prompts

Preamble for every session:

```
Read CLAUDE.md and .github/exploration-loop/ROADMAP.md first. This session
does exactly one stage of that roadmap and stops. Do not start the next
stage, do not touch loop_evidence/, do not push or change GitHub unless this
prompt says so. Commit each distinct change separately with what was observed.
End with: what was done, what was verified and how, what was left out and why.
```

Per-session blocks (append to the preamble):

**1 · S0** (Sonnet 5)
```
Stage 0. Read-only first: list the live state of ly989264/valkey-scale-lab
(workflows, runner, MILESTONE_LOOP_AUTO_MERGE, open PRs/issues with
milestone-loop labels) and show me before changing anything. Then, with my
approval per item: disable the milestone-loop workflow, set
MILESTONE_LOOP_AUTO_MERGE=false, close PRs #90 #92 and issues #3 #7 with a
one-line comment pointing at ROADMAP.md. Do not delete labels, branches or
history; do not touch the runner service. Record in ROADMAP.md the target
branch and the name/visibility of the new agent-loop repository.
```

**2 · S1a** (Opus 5)
```
Stage 1a. Create .agent-loop/backlog.yaml from CLAUDE.md "What is still
open": id, statement (verbatim), cost class (hermetic | docker-exact-50 |
needs-fleet), file:line where the item lives today, design-doc section it
must not contradict, selectable. Classify by reading code; where CLAUDE.md
no longer matches source, say so in the entry and fix neither. No probe or
proof fields yet. No product code changes.
```

**3 · S1b** (Fable 5)
```
Stage 1b. For each hermetic entry add a probe (exits non-zero while open)
and a proof. Run every probe on the current tree and show me its non-zero
exit; a probe that passes today is rejected, not adjusted. Add
scripts/assert_backlog_matches_claude_md.py, register it once in
catalog.json and repository.all - expect catalog +1, repository.all +1, M1
plan unchanged; tell me if the M1 count moves. docker-exact-50 entries get a
probe only if it runs under 5 minutes; needs-fleet entries get
selectable: false and no probe.
```

**4 · S2a** (Opus 5, in the agent-loop repo)
```
Stage 2a. Build the agent-loop kernel with no GitHub state: config loader
(.agent-loop/config.yaml in a consumer repo), probe-based pick, git
worktree, JSONL ledger, four terminal states PR_READY / BLOCKED / NO_ITEM /
INFRA each emitting one notification (stdout, file, osascript) deduped by
(item, state, sha). Adapter contract run(role, bundle, schema, sandbox,
budget) with claude-code, codex and shell adapters; env stripping, bounded
context and the single repair round-trip ported from valkey_scale_lab's
.github/milestone-loop/agent.py and context_builder.py, labelled cleanup
from recovery.py. Worker schema includes a mutation-evidence field. Mode
once only. Hermetic tests; no real round.
```

**5 · S2b** (Fable 5)
```
Stage 2b. Run one real round against valkey_scale_lab on hermetic item
<id>. Watch it; when it fails, report the exact stage and reason before
fixing, then the smallest fix at that site. Verify the worker's mutation
evidence by reverting its fix and watching its test fail. Stop after one
round reaches PR_READY or BLOCKED with a notification I received. Do not
push.
```

**6 · S2c** (Opus 5)
```
Stage 2c. Two further rounds, one on a docker-exact-50 item with the
delta-shape check against the frozen baseline. Add the lock file so a
concurrent gate run or interactive session makes the kernel refuse up
front; record tool versions in the ledger as a warning-only drift line.
Report the three ledger lines.
```

**7 · S3** (Opus 5)
```
Stage 3. scm/github: on PR_READY push the branch and open a PR with gh
(diff explanation, ledger line, mutation evidence). Reviewer role posts one
comment. Plain CI workflow in the consumer repo: focused tests +
./gate suite product.unit on PR, repository.all nightly. Implement L1/L2
per cost class with protected-path and delta-shape holds and the DECIDE
notification with expiry. valkey_scale_lab starts at L1. Ask me before the
first push; that is the only remote change this session.
```

**8 · S4a** (Opus 5)
```
Stage 4a. Drills as tests, each watched to fail before its fix: repeat
run is a no-op; malformed output gets one repair then INFRA; a BLOCKED item
notifies once and is skipped next round; a worker killed mid-round leaves
no worktree and no labelled Docker resource; a wedged Docker (network
create returns an id `docker network ls` lacks) is INFRA, not retried;
open-PR cap reached -> sleep and one notification.
```

**9 · S4b** (Sonnet 5)
```
Stage 4b. Add modes continuous / schedule / until with triggers (backlog
edit, PR merged or closed, BLOCKED reopened, idle timer) and caps (open
PRs, consecutive non-progress rounds, wall time, tokens, one Docker run per
round); pause/resume; ledger metrics: plumbing-PR share,
time-to-notification, cost per merged PR. Raise hermetic to L2 in
valkey_scale_lab's config. Show me the command that starts continuous mode;
do not start it.
```

**10 · Reserve** (Fable 5) - written when needed: paste the ledger lines and
notification of the failure; ask for the defect class before any fix.

**11 · Reserve** (Sonnet 5)
```
Fold the exploration loop into CLAUDE.md "Where the work stands" and
"Working rules" in under 40 lines; derivation into SESSION_HISTORY.md.
Check the new text for the bare word "phase".
```

**12-13 · S5** (Opus 5)
```
Stage 5. Point agent-loop at <second repo> with only config.yaml and
backlog.yaml; every valkey-specific assumption found in the kernel is a
bug to fix in the kernel. Then add the planner role for L3: it proposes
backlog items from failing checks and the open list, each with a probe it
ran and saw fail; admission still rejects a passing probe.
```

## 7. Risks specific to this project

- Exploration generates churn; every item carries a measurement, and anything touching a frozen baseline's delta shape is a `DECIDE`.
- One shared Mac: the kernel takes a lock and refuses rather than detecting afterwards.
- Continuous mode without back-pressure is meta-runs v4/v5 again.
- Two agent CLIs: the adapter contract must not depend on stdout framing.
- A loop is only as honest as its probes — watched to fail before admission, at L3 too.

## Stage 0 record — 2026-08-29

Session 1 of §6. Operator-approved item by item; nothing here was done without a
yes. Labels, branches, milestones, history, the `valkey-local` runner service and
its launchd plist were not touched.

### Decisions

- **Target branch for the exploration loop: `fast-iter`.** The default branch
  `codex/valkey-scale-lab-loop` stays where it is, per the 2026-08-13 decision;
  no merge is proposed.
- **New kernel repository: `ly989264/agent-loop`, public** — created empty, no
  README, no first commit. Public rather than private because
  `valkey-scale-lab` itself is public.
- **Runner `valkey-local` keeps running** as a launchd service. With the
  workflow disabled it has nothing to pick up.

### What was changed on the remote

| Item | Before | After | URL |
|---|---|---|---|
| `milestone-loop` workflow | `active` | `disabled_manually` | https://github.com/ly989264/valkey-scale-lab/actions/workflows/milestone-loop.yml |
| `MILESTONE_LOOP_AUTO_MERGE` | `true` (2026-07-19) | `false` | https://github.com/ly989264/valkey-scale-lab/settings/variables/actions |
| PR #90 | open, `contract-change` + `milestone-loop:work-item` | closed, commented | https://github.com/ly989264/valkey-scale-lab/pull/90 |
| PR #92 | open, `milestone-loop:work-item` | closed, commented | https://github.com/ly989264/valkey-scale-lab/pull/92 |
| Control Issue #3 (`m1 control`) | open | closed, commented | https://github.com/ly989264/valkey-scale-lab/issues/3 |
| Control Issue #7 (`m2 control`) | open | closed, commented | https://github.com/ly989264/valkey-scale-lab/issues/7 |
| PR #93 | open, `fast-iter` -> default branch, 100 commits | closed, commented; **branch retained** | https://github.com/ly989264/valkey-scale-lab/pull/93 |
| 21 `milestone-loop:work-item` Issues | open | closed, commented; labels kept | #91 #89 #87 #85 #81 #75 #69 #61 #59 #57 #55 #54 #52 #49 #48 #42 #36 #32 #27 #10 #8 |
| `ly989264/agent-loop` | did not exist | created, public, empty | https://github.com/ly989264/agent-loop |

The workflow was disabled **first**, before any PR or Issue was touched, because
it triggers on `pull_request` including `labeled`/`unlabeled`.

### Corrections to §1 "Live hazard", from reading the remote

- **The workflow has no `schedule` trigger.** It fires on `pull_request`
  (opened, synchronize, reopened, labeled, unlabeled, closed) and
  `workflow_dispatch`. Its last run was 2026-08-03.
- **The `candidate` job has no label gate**: its only condition is
  `event_name == 'pull_request' && action != 'closed'`. Any PR activity queued a
  `runs-on: [self-hosted, macOS, valkey-verify]` job with
  `timeout-minutes: 360`. That, not a timer, was the hazard.
- **23 open Issues carried a `milestone-loop:*` label, not two.** #3 and #7 are
  the Control Issues; the other 21 are `milestone-loop:work-item`, most also
  `milestone-loop:completed`. All 23 were closed, on the operator's instruction,
  after the first pass had left the 21 open. **No open Issue carries a
  `milestone-loop:*` label any more.** Every Issue keeps its labels, and all ten
  `milestone-loop:*` label definitions still exist in the repository — nothing
  was deleted, only closed.
- **#80 and #73 carried no `milestone-loop:*` label and were closed too**, on
  the operator's instruction, so **the repository now has no open Issue and no
  open PR at all**. Neither was loop plumbing, and closing did not resolve
  either, so both are restated here:
  - **#80** (2026-07-29, `enhancement`, `m2`) — *Add representative
    multi-primary failover coverage to `LOCAL_FULL_FLOW`.* The canonical fault
    matrix has a single-primary `primary_failover` scenario only, while
    simultaneous loss of one / 10 % / 33 % of primaries is a supported fault
    that the separate M2 campaign exercises and the full lifecycle never
    proves. It asks for one bounded representative multi-primary owned-process
    `SIGKILL` scenario at the default configuration — no baseline/candidate
    comparison inside the lifecycle — failing closed unless targets, affected
    shards, recovery, convergence and cleanup are all proven, with the existing
    single-primary scenario untouched. **This is open product work**, and a
    candidate for `.agent-loop/backlog.yaml` in Stage 1, where it would need a
    probe watched to fail before admission.
  - **#73** (2026-07-27, no labels) — an M2 decision request to widen the
    formation-discovery screen after `tree_meet_addslotsrange` p16 lost to the
    baseline at exact-50 (73.20 s against 53.74 s, +36.2 %). Overtaken: M3 is
    closed and M4 is in progress. Re-raise it as a backlog item if the matrix
    change is still wanted.
- **PR #93 `fast-iter` -> `codex/valkey-scale-lab-loop` was open**, 100 commits,
  since 2026-08-07 - a live path to the merge the 2026-08-13 decision forbids.
  Reported, then closed on the operator's instruction in the same session.
  **`fast-iter` is kept: it is the branch this project is developed on.**
  Closing a pull request never deletes its head branch - GitHub deletes a head
  branch only on *merge*, and only when `delete_branch_on_merge` is set, which
  this repository has as `false`. No `--delete-branch` was passed. Verified
  before and after: `fast-iter` is at `6556ac7f` on `origin` either side of the
  close, and the closed PR still names it as its head.
- The `valkey-real` Environment still exists and was left alone.

Stage 1 is a separate operator decision. The state between stages is idle.

## Stage 1a record — 2026-08-29

Worker: interactive session (Opus), stopped by the controller after it had
finished; its output was kept rather than regenerated. Reviewer: Opus
subagent, scope-first.

- 21 items in `.agent-loop/backlog.yaml`, statements byte-identical to
  CLAUDE.md after joining hard wraps; CLAUDE.md order and groups (6/3/5/6/1).
- Cost classes: 12 docker-exact-50, 5 hermetic, 4 needs-fleet; 5
  `selectable: false` (the 4 needs-fleet, plus the preflight-document item
  CLAUDE.md marks as the operator's call). Invariant 5 holds.
- Three places CLAUDE.md no longer matches source, recorded in `notes`, both
  sides left as they are, all three verified true by the reviewer: process
  RSS is recorded (`resources.py:244`); the management chokepoint records
  `attempt_count` (`docker_runtime.py:7542`); planner/runtime ordering
  diverges at every replica count (48/50 ordinals at 25x1).
- Review: RETURN on four `defect`s, all cited `file:line` sites one to eleven
  lines before the thing described. Corrected by the controller directly
  (mechanical, cited) rather than re-dispatched. Two header slips the worker
  declared were fixed the same way.
- Decision by the controller: closed Issue #80 (multi-primary failover
  coverage) is not added; it is feature work, not an open defect in the list.
- Left out: nothing.

Deferred (suggestions, not acted on):
1. Two more sites land on a comment rather than the statement
   (`docker_runtime.py:7920` -> `:7922`; `native_backend.py:1207` -> `:1208`).
2. `cost_class_reason` (21x) and 18 confirmation-only `notes` exceed the
   bullets; judged as classification evidence, not design.
3. Header lines 11-12 prescribe Stage 1b's normalisation.
4. `analysis-retry-counters-see-only-the-command-audit`: a reader-side fix
   would be hermetic.
5. `state-nodehost-drops-remote-bundle-dir`: restoring the key moves
   `state.json` in every frozen baseline, which is a docker-exact-50 re-proof.
6. `report-run-id-identical-in-every-run`: `M2_RUN_ID_ENV` overrides
   `_run_id`, so "identical" holds only with M2 measurement disabled.

## Stage 1b record — 2026-08-29

Worker: Fable 5, interactive session, on `fast-iter` at `66009427` plus the
Stage 1a commits. Nothing under `project/src`, `loop_evidence/` or on GitHub
was touched; no backlog item was fixed.

- Probes and proofs, on the five `hermetic` entries. Three received both
  fields; every probe was run from `project/` on the current tree and exited
  1, in the order below. Each is a check of the defect against the product
  API, not a grep.
  1. `retry-read-catches-a-broad-exception` — hands `_retry_read` a callable
     raising `RespCommandError` with `attempts=3, pause=0` and asserts one
     call. **exit 1**: `AssertionError: an error reply was retried: 3 calls`.
     Proof: a test beside it asserting one call on an error reply and three on
     `socket.timeout`; mutation check reverts the narrowing.
  2. `ssh-failure-is-not-classified-in-the-transport` — stubs
     `subprocess.run` in `host_transport` with rc 255 and ssh's own
     `No route to host` on stderr, asserts `MultiplexedSshTransport.run`
     raises `TransportError`. **exit 1**: `ssh failure returned as
     CommandResult rc 255: ssh: connect to host 10.0.0.1 port 22: No route to
     host`. Proof: a `test_native_backend.py` test for that case beside one
     where a remote command's own 255 is still returned as a `CommandResult`.
  3. `process-runtime-state-call-site-is-unreached-by-the-suite` — wraps the
     real `_process_runtime_state` with a caller-frame recorder, runs the two
     modules that reach `_create_process_scenario` in-process, and exits 0
     only if the real function was called from `lifecycle.py`. **exit 1**:
     `real _process_runtime_state reached from lifecycle.py at lines [],
     pytest rc 0` (172 tests pass; the only route stubs it with
     `lambda *_args, **_kwargs` at `test_docker_runtime_contract.py:1202`).
     Proof: a test driving that path with the real signature; mutation check
     adds a wrong keyword at `lifecycle.py:324`.
- Two hermetic entries were left without a probe, both `selectable` as they
  were:
  - `state-nodehost-drops-remote-bundle-dir`: the statement names no defect
    to fix - the key is dropped *and nothing needs it*. The only probe that
    fails today asserts the key is present, which prescribes restoring it, a
    direction the statement does not ask for and one Stage 1a's deferred
    item 5 already notes would move `state.json` in every frozen baseline.
    A probe that would be honest to the statement passes today, and a
    passing probe is rejected, not adjusted.
  - `preflight-validates-the-profile-template-not-the-run-document`: an
    operator decision (`selectable: false` since Stage 1a). Neither outcome
    is "open" in a way an exit code can encode, so no probe.
- No `docker-exact-50` entry received a probe: each needs a real exact-50
  run, and none of those completes under 5 minutes. The four `needs-fleet`
  entries stay `selectable: false` with no probe.
- `project/scripts/assert_backlog_matches_claude_md.py` (97 lines): reads
  CLAUDE.md `### What is still open` up to the next heading, joins each
  bullet's hard wraps with single spaces, and requires every backlog
  `statement` to be byte-identical to one bullet, every bullet claimed
  exactly once, and `source.item_count`, the item count and the bullet count
  to agree. Observed: exit 0, `backlog matches CLAUDE.md: 21 open items`;
  exit 1 with two named disagreements when one statement in a copy of the
  backlog is changed by a single byte. Focused test:
  `project/tests/repository/test_backlog_matches_claude_md.py` (4 tests:
  checked-in pair, hard-wrap join stopping at the next heading, one-byte
  drift, count mismatch).
- Registration: `repository.backlog_matches_claude_md` in `catalog.json` and
  in `repository.all` only. Counts: catalog **100 -> 101**, `repository.all`
  **92 -> 93**, M1 plan **91, unchanged** (it draws from `product.*` suites,
  which the new entry does not join). The one pinned number in
  `verification/tests/test_contracts.py` moved with it; `gate.contracts`
  23/23.
- `./gate suite repository.all` on the final tree: **93/93 PASS**, run directory
  `project/artifacts/gate-runs/gate-20260829T082241Z-fcbc79c5/` (entry 093 is
  `repository.backlog_matches_claude_md`). Run once; no checker failed by
  chance.
- Neither new file contains the word the execution-axis contract forbids;
  the filename matches no milestone-stage pattern.
- Deviations: `deviation: spec said a probe and proof on each hermetic
  entry, built them on three of five, because the other two have no probe
  that fails today without prescribing a fix the statement does not name`.
  The backlog's header comment and `stage: '1a'` were updated to `1b`, since
  the header said no probe fields existed yet and would have been false.
- Left out: nothing else.

Commits: `f1655a78` (probes), `0cd6561e` (script, test, registration),
and the commit that adds this record.

Review (Opus, scope-first): RETURN on one `defect` — probe 1 caught
`DockerRuntimeError`, so a correct fix that re-raises a non-transient error
on the first attempt (the reviewer applied that three-line patch and showed
the probe still red) would never turn it green. Widened to `Exception` by the
controller (one token, cited); probe re-run, exit 1. Verified: `project/src`
untouched, all three probes real and non-proxy, both refusals correct, the
agreement script catches a one-byte change, a missing item, an unclaimed
CLAUDE.md bullet and a duplicate; counts 101 / 93 / 91. Deferred: probe 2
passes under a fix that maps every rc 255 to `TransportError` (its `proof`
closes that); probe 3's pytest argv is two modules, so a fix landing its test
elsewhere stays red (its `proof` targets a listed module).

## Stage 2a record — 2026-08-29

Worker: Opus subagent in `~/centos_ex/projects/VibeCoding/agent-loop`.
Reviewer: Opus subagent, scope-first, two rounds. Kernel pushed to
`origin/main` at `d2d8c5b` (19 commits).

- Built as specified: package + `pyproject.toml` (stdlib + PyYAML), CLI
  `run --mode once` / `status`, ten-key config loader refusing unknown keys,
  `examples/valkey_scale_lab.config.yaml`, probe-based pick in file order
  skipping BLOCKED-at-sha, `git worktree add -b explore/<item>` removed on
  every exit path, adapter contract exactly as §3 with `claude-code`,
  `codex`, `shell`; env stripping, byte-cap refusal and one repair
  kernel-side; verify = probe exits 0 + cost-class command + protected paths
  (tracked, untracked and committed); JSONL ledger with the eight fields;
  four terminal states, one notification each via stdout/file/macos,
  deduplicated by (item, state, sha). 59 hermetic tests.
- Review round 1: 5 `contract` (drift plumbing belonged to 2c; three
  consumer env prefixes inside the kernel; `--detach` where `-b` suffices;
  an undeclared ledger field; dead code) and 4 `defect` with measured
  failing cases (protected-path check blind to untracked/committed files;
  caps not firing inside `readline`; `BrokenPipeError` escaping `run_once`
  with no terminal state; worktree created outside `try/finally`). All nine
  fixed in nine commits; round 2 re-measured each and passed.
- Deviation, accepted: probes run in the `cwd` of their cost class's verify
  entry, because the ten keys allow no separate probe directory and invariant
  1 forbids a consumer path in the kernel.
- Size: ~1,000 code lines of kernel against ~400 expected. The reviewer
  attributes the excess to verbosity of required behaviour (per-key
  validation, one dataclass per concept), not to features; ~25 lines of
  beyond-spec code were found and removed.
- Controller: `.agent-loop/config.yaml` installed in this repository from
  the kernel's example, unchanged (data only).

Deferred (suggestions):
1. `config.py` per-value assertions could be a table.
2. A child that stays alive without reading its bundle is still not bounded
   by the budget (`adapters/base.py:96-103`, measured 60 s); unreachable with
   the shipped adapters, which read stdin immediately. Belongs with 2b/2c.
3. Cleanup deletes `explore/<item>`; Stage 3 must push before cleanup or skip
   the deletion on `PR_READY`. **Carried into the Stage 3 spec.**

## Stage 2b record — 2026-08-29

Worker: Fable 5, interactive session, on `fast-iter` at `b872744f`, kernel
`~/centos_ex/projects/VibeCoding/agent-loop` main at `d2d8c5b`. Nothing under
`project/src`, `loop_evidence/` or on GitHub was touched by this session; the
only product change any round made lived in the round's worktree and was
removed with it. Nothing was pushed.

- Pre-run fix (2a deferred item 3): kernel `2582ffa`. On `PR_READY` the round
  marks its workspace `keep_branch`; cleanup still removes the worktree and
  temp dir and skips only the `explore/<item>` branch. Every other state
  deletes it as before. One worktree test; the round test now pins that a
  second round on the same item while the branch exists ends `INFRA` (from
  `git worktree add -b` refusing the existing branch), and the dedup test
  clears the branch between its two rounds. 60/60.
- Item picked, all three attempts: `retry-read-catches-a-broad-exception`
  (first failing probe in file order; probes 2 and 3 were run and also fail,
  as Stage 1b measured).
- Attempt 1 — `INFRA` at stage 3 (worker), 22.5 s, cost null:
  `claude -p --model sonnet-5` answered `api_error_status 404: There's an
  issue with the selected model (sonnet-5)`. The kernel classified it
  `refused` -> `INFRA`, wrote the ledger line and one notification, so the
  kernel was right and the data wrong. Consumer fix `e2bdbab0`:
  `.agent-loop/config.yaml` names `claude-code:sonnet` / `claude-code:opus`,
  the aliases `claude --help` lists. Kernel `183455c` corrects the example
  config the consumer's was copied from.
- Attempt 2 — `INFRA` at stage 3 (worker), 319.4 s, cost null: `worker
  returned timeout:` with an empty tail. The 300 s `silence_s` cap fired,
  and it always would: `claude -p --output-format json` prints nothing until
  the agent finishes, so the silence cap could only ever kill a healthy
  worker. Measured beside it: `./gate suite product.unit` takes 53 s, so the
  cap's value was not the defect. Kernel `ab33ae8`: the `claude-code` adapter
  runs `--output-format stream-json --verbose` (one line per event; measured
  with a one-word prompt: `system`, `rate_limit_event`, `assistant`, then the
  `result` envelope with `total_cost_usd`, `is_error`, `result`) and takes
  its answer from the last `type: result` line; `TAIL_LINE_BYTES` 4 000 ->
  64 000 because that envelope carries `modelUsage` and would otherwise be
  cut and read as malformed. One hermetic test with a fake `claude` on PATH.
  61/61.
- Attempt 3 — `BLOCKED`, 406.0 s, cost $1.50, notification received on stdout
  and as the last line of `.agent-loop/notifications.log`. The worker
  (Sonnet, real `claude -p`) reported: `_retry_read` (`docker_runtime.py:3613`)
  re-raises when `is_transient_transport_error(exc)` is false, matching the
  chokepoint at `:7509`; two tests added to
  `tests/integration/test_docker_runtime_contract.py` (one call on
  `RespCommandError`, three then `DockerRuntimeError` on `socket.timeout`);
  14 other call sites checked. Then: its Bash tool refused every `python3`,
  `./gate` and `pytest` invocation with "This command requires approval",
  reproduced three ways, so it could not run the suite or the mutation check
  and answered `status: blocked` rather than invent an observed failure line.
  That is the correct worker behaviour and the round's finding: the adapter's
  `worktree-write` sandbox maps to `--permission-mode acceptEdits`, which in
  `-p` mode allows edits and denies every Bash command, so no worker can ever
  produce the mutation evidence the schema requires. **Not fixed here**: the
  three-attempt budget was spent and a fix without a run to watch is exactly
  what this stage exists to avoid. The candidate is one adapter change - a
  per-consumer allowlist (`--allowedTools 'Bash(python3:*)' ...`) is data
  the ten config keys do not carry, and `bypassPermissions` widens the
  sandbox to everything; which one is a `DECIDE`, carried into 2c.
- Ledger lines (`.agent-loop/ledger.jsonl`, untracked, reasons abbreviated):
  1. `ts 09:32:03Z · item retry-read-catches-a-broad-exception · sha b872744f
     · INFRA · worker returned refused: ... api_error_status 404 ... (sonnet-5)
     · cost null · 22.518 s`
  2. `ts 09:38:07Z · same item · sha e2bdbab0 · INFRA · worker returned
     timeout: · cost null · 319.438 s`
  3. `ts 09:47:15Z · same item · sha e2bdbab0 · BLOCKED · worker blocked: The
     fix and its test are written and applied to the working tree ... could
     not run the mutation check ... · cost 1.5047 · 406.024 s`
  Every line carries `tool_versions` {claude 2.1.251, git 2.50.1, python3
  3.9.6}. The two files are loop state and stay untracked.
- Mutation check on the worker's diff: **not possible**, and reported as
  such. `BLOCKED` deletes the branch by design, and the worker's changes were
  uncommitted in the worktree, so `worktree remove --force` dropped them;
  verified afterwards that no `explore/*` branch, no worktree and no trace of
  the worker's test exist in the main tree. That second half is itself a
  defect in the pre-run fix - a kept branch would have pointed at the base
  sha. Kernel `7fd4ca3`: on `PR_READY` the round runs `git add -A` and
  commits `agent-loop: <item>` with a fixed identity before cleanup; the
  round test now shows the worker's file on the kept branch. Mutation check
  on that change: with the `commit_all` call reverted the test failed on
  `'agent-loop: an-item' not found in 'initial ...'`; restored, 61/61.
- Explore branch: none survives (`BLOCKED`); diffstat n/a.
- Kernel commits on main, unpushed: `2582ffa`, `183455c`, `ab33ae8`,
  `7fd4ca3` (main is 4 ahead of `origin/main` at `d2d8c5b`). Consumer commit
  on `fast-iter`: `e2bdbab0`, plus the one adding this record.
- Deviations: `deviation: spec said one round reaching PR_READY or BLOCKED
  with the worker's mutation evidence verified by hand, built a BLOCKED round
  whose evidence could not be verified, because the worker was denied the
  commands that produce it and the diff did not survive BLOCKED cleanup`.
  Kernel size: four commits, ~90 lines, against "the retention fix plus what
  the run exposes"; each is one observed failure.
- Left out: the adapter permission fix (above, `DECIDE`); a `claude -p`
  worker also prints a `rate_limit_event` line, which the tail keeps and
  nothing reads.

**Continuation, same day.** Controller decision on the `DECIDE`: no
`bypassPermissions`. Kernel `fd98a3b`: `allowed_tools()` in
`adapters/base.py` derives `Bash(<program>:*)` from the cost class's verify
command and the picked item's probe - the program each starts with, leading
`NAME=value` assignments included - plus `Read`, `Edit`, `Write`; `build()`
passes the list to the adapter and the `claude-code` adapter appends it under
`--allowedTools` for `worktree-write`; nothing consumer-specific in the
kernel, no new config key, codex adapter untouched; one hermetic test with a
fake `claude` asserts the exact argv; 62/62. Argv used on this consumer:
`claude -p --output-format stream-json --verbose --model sonnet
--permission-mode acceptEdits --allowedTools
"Bash(./gate:*),Bash(PYTHONPATH=src python3:*),Read,Edit,Write"`.

Attempt 4 (the last) - `BLOCKED` at stage 4 (verify), 504.6 s, cost $1.04,
notification received on stdout and in `.agent-loop/notifications.log`.
The worker was denied nothing and answered `done`; the kernel's verify
found the probe passing and then `./gate suite product.unit` failing:
`24/25 passed, Status: FAIL`. Which entry failed is **not recoverable**:
the ledger keeps the last 800 characters of the command's output, which
are six `PASS` rows and the summary, and the gate's run directory
(`.agent-loop/worktrees/<item>/project/artifacts/gate-runs/gate-20260829T095947Z-2f7ea13b`)
was inside the worktree that `BLOCKED` cleanup removed - together with the
worker's diff, so no by-hand mutation check and no diffstat, as in
attempt 3. Ledger line: `ts 10:00:43Z · retry-read-catches-a-broad-exception
· sha 8aa3f13a · BLOCKED · verify command './gate suite product.unit' failed
(exit 1): ... 24/25 passed Status: FAIL · cost 1.0406 · 504.634 s`. No
`explore/*` branch survives. Not fixed (budget spent), for 2c: a `BLOCKED`
that comes from verify destroys the two things needed to act on it - the
diff and the failing check's name; keeping the branch on that state too, and
keeping the verify command's failing rows rather than its tail, are the
candidates.

Review (Opus, scope-first) of the five kernel commits and the config fix:
RETURN on one `defect` — `round.py:80-81`: a `git commit` that fails on
PR_READY (a hook, `commit.gpgsign`) ends the round INFRA, `cost: null`, and
deletes the branch the fix exists to keep; three lines at the site, carried
into Stage 2c's first item. No `contract`: every hunk maps to an observed
failure or the controller decision. Measured: silence cap now measures gaps
between stream events; `allowed_tools()` never emits `Bash(*)`, and Claude
Code refuses unlisted parts of compound commands; `--allowedTools` with
`acceptEdits` really permits the listed Bash in `-p` mode. Security note
for the operator, **a DECIDE before L2 or continuous mode**: the allowlist
bounds the shell, not the filesystem — a worker's `python3` runs with the
operator's `HOME` and can read `~/.ssh`, `~/.claude`; env stripping removes
variables, not access. Fine at L1 with a human merge; needs an OS sandbox
before Stage 4 raises the level. Deferred: a probe whose first line is a
comment derives no Bash grant; a PR_READY branch left in place makes later
rounds on that item INFRA until deleted (a livelock in `continuous`).

## Stage 2c record — 2026-08-29

Worker: Opus 5 subagent, on `fast-iter` at `cf345afc`, kernel
`~/centos_ex/projects/VibeCoding/agent-loop` main at `fd98a3b`. Nothing under
`project/src`, `loop_evidence/` or on GitHub was touched by this session;
the only product change any round made lives on a kept `explore/` branch.
Nothing was pushed. Kernel main is now **12 commits ahead of `origin/main`**,
the last two being review round 1's two defects: `3016a7d` (fixture, above)
and `34421a0` (`round.py`'s docstring still said "lock-free pick" after the
lock went in).

**Kernel, five commits, +213 lines under `agent_loop/` (121 of them code, the
rest docstring and comment) plus 246 test lines; 74/74 hermetic tests.** Each
was watched to fail with its fix reverted before it was committed.

1. `bdbf47f` — *Keep the diff and the cost when the round's commit fails*
   (the 2b review defect at `round.py:80-81`). Observed with a failing
   `pre-commit` hook: the PR_READY commit raised out of `_worker_round`, so
   `run_once` caught it as a plain infrastructure failure, wrote INFRA with
   `cost: null`, and cleanup deleted both `explore/<item>` and the worktree
   holding the worker's uncommitted diff. `_retain()` now marks the branch
   kept *before* committing and, on failure, marks the worktree kept too and
   returns the reason, so the round ends INFRA with the worker's cost
   recorded and no evidence is lost. Mutation check: `None != 1.5`.
2. `e50d587` — *Retain the diff when verify is what blocks the round* (2b
   carried item). A BLOCKED that comes from verify (probe still failing,
   verify command failed, protected path touched) now commits onto
   `explore/<item>` and keeps the branch exactly as PR_READY does; a
   worker-returned `blocked` has applied nothing and still deletes. Both
   tested. Mutation check: `'explore/an-item' not found in ['main']`.
3. `a5f1fd2` — *Keep a failing verify command's failing rows, not its tail*.
   `verify.failing_lines()` keeps the lines carrying FAIL / ERROR / Error /
   Traceback, bounded to 40 with a count of what it dropped, falling back to
   the tail when nothing is marked. Tested against fake `./gate suite`
   output — twelve PASS rows, one FAIL row, **forty** more PASS rows,
   `Status: FAIL` — which puts the failing row 2 279 bytes above the end, out
   of reach of the tail. Mutation check: with `output[-800:]` restored the
   reason is fourteen passing rows and `Status: FAIL`, and the assertion that
   it names `product.unit.docker_runtime_contract` fails. **Corrected after
   review round 1** (`3016a7d`): the first fixture left only 748 bytes after
   the FAIL row, so the tail still contained it and that assertion passed
   under mutation - only `assertNotIn("PASS")` failed. The sentences this
   replaces described a measurement that had not been made.
4. `747a7a6` — *Take a lock before the round picks anything*.
   `agent-loop run` takes `<worktree_root>/.lock` (pid + timestamp) before
   pick; refuses INFRA naming the holding pid while that process is alive;
   takes over a lock whose holder is gone (a killed round would otherwise
   wedge the loop for ever); refuses INFRA naming any worktree under the root
   that this round did not create; released on every exit path and never
   removed by the round that was refused. Four lock tests plus one round
   test. Mutation check: PR_READY != INFRA.
5. `9af3ba9` — *Note tool-version drift on the round's own ledger line*.
   `ledger.drift()` compares this round's `tool_versions` with the last
   recorded round's and names each tool that moved, including one that
   appeared or disappeared; written to the line's declared `warning` field
   and nowhere else — no new state, no notification, no effect on the
   terminal state, because an upgrade is not a failure. Mutation check:
   `records[1]['warning']` None.

**Rounds.** Budget three, two spent; the third would have bought a copy of
the second's line.

- Round 1 (free, deliberate, launched while round 2's worker was running) —
  `INFRA` in **0.044 s**, no worker spawned, the holder's lock left intact:
  `ts 10:23:18Z · item null · sha cf345afc · INFRA · another round holds
  .../worktrees/.lock (pid 42249 since 2026-08-29T10:22:30Z); wait for it or
  remove the file · cost null · 0.044 s · warning null`. The lock exercised
  against the real consumer, not only in tests.
- Round 2 — `BLOCKED` at verify, **330.3 s, cost $0.79**, notification on
  stdout and in `.agent-loop/notifications.log`: `ts 10:28:01Z · item
  retry-read-catches-a-broad-exception · sha cf345afc · BLOCKED · verify
  command './gate suite product.unit' failed (exit 1): [18/25] FAIL
  product.unit.server_profile (0.32s) / product.unit.server_profile FAIL
  0.32 8 tests, 0 failed, 0 errors, 1 skipped / Status: FAIL · cost 0.7935 ·
  330.345 s · warning null`. Items 2, 3 and 5 all did their work in it: the
  reason **names the failing check**, the branch **survived**, and the drift
  field was correctly null.

**The failing check, identified: `product.unit.server_profile`, and it is
pre-existing and environmental, not the worker's fix.** Its 8 tests report
0 failed, 0 errors, **1 skipped**, and `verification/runner.py:155-161`
makes any skip a FAIL. The skip is
`tests/unit/test_server_profile.py:151`, taken when
`artifacts/baselines/exact-50-6b6f57fd/.../node_configs` is absent — and
`project/artifacts/` is in `.gitignore`, so the frozen baseline exists in
the operator's working tree and **in no fresh checkout or `git worktree`**.
Measured three ways: `./gate suite product.unit` in the main working tree is
**25/25 PASS**; `./gate test product.unit.server_profile` in a clean
detached worktree of the same commit `cf345afc`, with no worker diff at all,
**FAILs identically**; the worker's diff touches only `docker_runtime.py`
and `test_docker_runtime_contract.py`. This is also, with near certainty,
2b attempt 4's unrecoverable `24/25`.

**Consequence: PR_READY is unreachable for every hermetic item until this is
decided, so the two remaining rounds were not spent.** `./gate suite
product.unit` cannot pass in the throwaway worktree a round verifies in, for
any item and any worker. Two candidate fixes, both **operator DECIDEs** and
neither taken here: make the frozen baseline reachable from a fresh checkout
(the loop cannot invent it, and `project/artifacts/baselines` is a protected
path), or change the Gate's skip-is-FAIL policy — a validation-contract
change that CLAUDE.md's working rules say to report rather than make.

**The worker's diff and the by-hand mutation check.** Branch
`explore/retry-read-catches-a-broad-exception`, commit `8cfd4b00`,
`agent-loop: retry-read-catches-a-broad-exception`, diffstat **2 files, +41**:
`project/src/valkey_scale_lab/runtime/docker_runtime.py` +7 (two of them the
fix: `_retry_read` re-raises when `is_transient_transport_error(exc)` is
false) and `project/tests/integration/test_docker_runtime_contract.py` +34
(two tests). Checked out at `8cfd4b00`, both tests pass; with the two-line
fix removed **`test_retry_read_does_not_retry_an_error_reply` fails** with
`DockerRuntimeError: probe failed after 3 attempts:
RespCommandError('ERR unknown command')`, while
`test_retry_read_still_retries_a_transient_transport_failure` keeps passing,
so the pair is not a tautology; restored, 2 passed. **This is the mutation
evidence 2b could not obtain, and it is the whole point of item 2.**

- `deviation: spec said a docker-exact-50 round with the delta-shape check,
  built none, because no docker-exact-50 item has a probe (Stage 1b), so
  pick cannot select one; the delta-shape verify entry is written when an
  item earns a probe.` Writing an unexercised `verify.docker-exact-50` entry
  would have been a contract entry nothing had run.
- `deviation: spec said one round reaching PR_READY, built one BLOCKED
  round, because the hermetic verify command cannot pass in any worktree for
  an environmental reason this stage identified and is not authorised to
  fix.` The mutation check the goal exists to produce was done by hand on the
  retained branch instead.
- Left out: the two DECIDEs above; the 2b review's Stage 4 sandbox DECIDE
  (a worker's `python3` still runs with the operator's `HOME`); the deferred
  livelock — a kept `explore/` branch now also outlives BLOCKED, so a later
  round on the same item at a new sha is INFRA until the branch is deleted,
  which is Stage 3's to resolve when it pushes and deletes. **Worse for the
  worktree item 1 keeps**: an uncommittable diff leaves a worktree under the
  root, and the lock's foreign-worktree check then refuses *every* later
  round on *any* item until a person removes it - a stop in `once`, a
  livelock in `continuous`. Deliberate (the diff exists nowhere else) and
  carried to Stage 4.

## Stage 3 record — 2026-08-29

Worker: Opus 5 subagent, on `fast-iter` at `47cd29e9`, kernel
`~/centos_ex/projects/VibeCoding/agent-loop` main at `34421a0` (= `origin/main`).
Review round 1 returned one `contract` and one `defect`; both are fixed below,
in their own commits.
Nothing under `project/src`, `loop_evidence/` or the disabled `milestone-loop`
workflow was touched by this session; the only product change is the one the
round itself produced, and it is on a pull request nobody merged. **Kernel main
is five commits ahead of `origin/main`, unpushed** — pushing the kernel was
not this session's to do. `fast-iter` is pushed.

**Kernel, five commits, +700 lines under `agent_loop/` and +530 test lines;
105/105 hermetic tests.** Commits 4 and 5 are review round 1's two returns. Each behaviour was watched to fail with its fix
reverted before it was committed.

1. `46bf6c3` — *Publish before cleanup* (2a deferred 3). An `scm/` package with
   a `github` publisher (`git push --force-with-lease`, then `gh`; read-only
   otherwise) and a `local-only` no-op that stays the **default**, so every
   hermetic test and any consumer that has not opted in opens nothing. A new
   `scm` config key selects one. On `PR_READY` the round pushes
   `explore/<item>` and opens a pull request titled `agent-loop: <item>`
   against the configured branch, **inside the workspace context manager**, so
   the branch still exists. The body is deterministic and written by the kernel,
   never by an agent: item id, statement, the worker's `reason`, the two
   mutation-evidence fields, `git diff --stat` and the ledger line. A branch
   that already has an open pull request gets **that one updated** rather than a
   second one opened. The ledger line gains `pr_url`. Once origin holds the
   branch the local copy is no longer the only one, so cleanup takes it — which
   is also what retires the 2c deferred livelock, where a kept `explore/` branch
   made every later round on that item `INFRA`. Mutation checks: with the
   publish call removed the round test fails on the absent `pr_url`; with the
   existing-pull-request branch removed the update test fails on `gh pr create
   printed no URL`.
2. `f9b65ad` — *One review comment, and no fix loop*. After publish the
   `reviewer` role runs (adapter from `agents.reviewer`, sandbox `read-only`) on
   a bundle carrying the backlog entry, the `base...head` diff and §0's finding
   classes with their rules; it answers `findings: [{kind, location, claim,
   citation}]` against a schema, and they become **exactly one** pull-request
   comment. A re-run posts none. **Corrected by review round 1** (`eef1781`,
   below): the first version deduplicated by reading an HTML marker back off the
   comments, which is loop state on GitHub. The findings are **not** fed back to the worker.
   `validate()` gains array support, which the list needs. A review that cannot
   be run at all — no `reviewer` configured, a bundle over the cap, a `gh`
   failure — is said so on the round's line and **never costs the round its pull
   request**, since the change is already published. Mutation checks: with the
   marker check removed a second comment is posted and two tests fail; with
   array support removed three schema tests fail.
3. `08794ae` — *Levels*. `levels.<cost_class>` is now `L1` or `L2`; `L3` is
   still refused, and a class the config says nothing about is `L1`. L1 leaves
   the pull request open and notifies `FYI`. L2 squash-merges through `gh pr
   merge --squash` when the reviewer returned **no `contract` and no `defect`
   finding**, nothing in the diff is protected and the verify step flagged
   nothing; otherwise it leaves it open and notifies `DECIDE` — one line
   carrying the item, the link and the question. Invariant 8 is read **twice**:
   verify BLOCKs a protected path, and the merge guard reads
   `VerifyOutcome.protected` again, so nothing rests on one function. A refused
   squash-merge turns back into a `DECIDE`. **DECIDE expiry** is a constant
   (24 h), not a config key: a later round on an item whose `DECIDE` pull
   request is older than that and still open ends `BLOCKED` with that reason
   **before any worker is spawned**, which is why the ledger line also carries
   the round's `decision`. No new terminal state, and it fits in the twenty
   lines the spec allowed. Mutation checks: with L1's early return removed three
   decision tests fail; with the protected-path hold removed two more; with the
   expiry condition always true the expiry test and the round test fail.
4. `eef1781` — *Ask the ledger, not a marker on GitHub* (round 1 `contract`,
   invariant 4). The `<!-- agent-loop:review -->` marker and the `gh pr view
   --json comments` read-back are gone. The ledger line carries `review_posted`;
   `ledger.reviewed(records, pr_url)` answers the question from the records the
   round already loaded, before the comment is written, and the publisher now
   posts what it is given in one `gh` call and inspects nothing. Mutation check:
   with the consultation removed the round test fails on a second comment.
5. `004a430` — *A failed publish leaves the item re-runnable* (round 1
   `defect`). `git push` may already have put `explore/<item>` on origin when
   `gh pr create` then fails, and `_retain` had marked the local branch kept: a
   later round on that item ended `INFRA` at `git worktree add -b` with no pull
   request anywhere to show for it. The publish call clears `keep_branch` before
   re-raising, so the local branch goes and what the round did survives in the
   ledger reason. Both halves tested with a fake `gh` - rc 1 on `create` after a
   push that landed, and a push to a remote that does not exist. Mutation check:
   with the `except` made unreachable the branch is left behind and the test
   fails.
6. Bullet 4 of the spec needed no code: the reviewer's findings reach the pull request and
   the round's ledger line, and are read by the level decision. Nothing carries
   them back to a worker, and there is no second worker invocation in the round.

**Consumer, one commit, `b2229eb8`.** `.agent-loop/config.yaml` gains
`scm: github` and a `reviewer: claude-code:sonnet` rung with its own caps;
**`levels` stays `L1` on both cost classes**. `.github/workflows/agent-loop-ci.yml`
is new: on `pull_request` into `fast-iter` from a head branch starting
`explore/`, one job on `[self-hosted, macOS, valkey-verify]`, 60 min, checkout
then `cd project && ./scripts/agent_loop_verify_hermetic.sh`; plus a `schedule`
job, same runner and timeout, running `cd project && ./gate suite
repository.all`. `permissions: contents: read` and nothing else. Checked for the
bare word "phase": absent. The disabled `milestone-loop` workflow was not
touched.

**The round.** Budget two, one spent. The leftover local branch
`explore/retry-read-catches-a-broad-exception` was deleted first so the round
could recreate it.

- `PR_READY`, **390.9 s, cost $0.57**, notification on stdout and in
  `.agent-loop/notifications.log`, prefixed `FYI`. Ledger line: `ts 11:10:38Z ·
  item retry-read-catches-a-broad-exception · sha b2229eb8 · PR_READY · probe
  passes, ./scripts/agent_loop_verify_hermetic.sh passes, no protected path
  touched; test ...::test_retry_read_does_not_retry_an_error_reply_only_a_transport_failure;
  reverted "...removing the `if not is_transient_transport_error(exc): raise`
  guard at docker_runtime.py:3632-3633..." observed "E ... DockerRuntimeError:
  probe failed after 3 attempts: RespCommandError('ERR unknown command')" ·
  https://github.com/ly989264/valkey-scale-lab/pull/94 · 0 finding(s), posted ·
  level L1, so a person merges · cost 0.5731 · 390.922 s · warning null ·
  pr_url .../pull/94 · decision FYI`.
- **Pull request: https://github.com/ly989264/valkey-scale-lab/pull/94**, open,
  `explore/retry-read-catches-a-broad-exception` -> `fast-iter`, two files,
  +38: `project/src/valkey_scale_lab/runtime/docker_runtime.py` +7 and
  `project/tests/integration/test_docker_runtime_contract.py` +31. This is the
  hermetic verify passing in a throwaway worktree for the first time — the
  wrapper committed at `8a20a7f3` is what unblocked it, and it is the same fix
  the 2c round produced by hand.
- **Reviewer findings as posted: none.** The comment reads `## Reviewer
  findings / No findings.` It is the only comment on the pull request. It was
  posted with the marker the round-1 `contract` finding removed; the marker is
  inert text and no later round reads it. A no-finding review is a legitimate answer on a 38-line diff whose
  mutation evidence the kernel had already verified, but it is one data point
  and says nothing yet about whether the reviewer role finds anything when there
  is something to find.
- The local `explore/` branch is gone and `origin` holds it, as designed.

**CI result: it triggered, failed for the reason Stage 2c already identified,
and is now green.** Run
https://github.com/ly989264/valkey-scale-lab/actions/runs/33249453424, 1 m 32 s
on `valkey-local`: `hermetic verify` fail, `repository.all` correctly skipped
(it is a `schedule`-only job). The failure is **24/25, `product.unit.server_profile`
FAIL, 8 tests, 0 failed, 0 errors, 1 skipped** — the frozen exact-50 baseline is
under `project/artifacts/`, which is gitignored, so it is in no fresh checkout;
`agent_loop_verify_hermetic.sh` links it from the *main checkout* a `git
worktree` shares, and a CI checkout has no main checkout to link from. **The
loop's own verify passes and CI's does not, on the same command and the same
machine.** This is not a Stage 3 defect and not fixable inside the spec's
"nothing else in the workflow": it is the same operator `DECIDE` 2c raised —
make the frozen baseline reachable from a fresh checkout (`project/artifacts/baselines`
is a protected path), or change the Gate's skip-is-FAIL policy
(`verification/runner.py:155-161`), which is a validation-contract change
CLAUDE.md's working rules say to report rather than make. **The controller took
a third route the same day** (`23b3fb08`): the wrapper takes
`AGENT_LOOP_BASELINES` and the workflow passes the repository variable of that
name, pointing at the runner's own main checkout; the Gate's skip-is-FAIL policy
and every protected path are unchanged. **PR #94's check is now green, 25/25**,
run https://github.com/ly989264/valkey-scale-lab/actions/runs/33249704350, 1 m
16 s. The 2c `DECIDE` itself is untouched and still open.

**L2 must not be enabled on this consumer before the sandbox `DECIDE` from the
Stage 2b review is answered**: the worker's `--allowedTools` allowlist bounds
the shell, not the filesystem, so a worker's `python3` runs with the operator's
`HOME` and can read `~/.ssh` and `~/.claude`. A human merge is what currently
stands between that and a merged diff. The config comment beside `levels` says
so too.

- `deviation: spec said repository.all nightly, built a schedule job that
  cannot fire, because schedule runs only from the default branch and fast-iter
  is not it.` The default branch is `codex/valkey-scale-lab-loop` and the
  2026-08-13 decision forbids merging `fast-iter` into it, so the workflow's
  `schedule` trigger has no copy on the branch GitHub would read it from. **A
  `DECIDE` for the operator**: change the default branch to `fast-iter`, or run
  the nightly from launchd on the Mac. The `pull_request` half is unaffected -
  it is read from the merge ref and has already run.
- `deviation: spec said ~250 kernel lines, built 700 under agent_loop/ (about
  540 of them statements, the rest docstring and comment), because three
  deliverables each needed their own module — a two-publisher scm/ package with
  a real forge client, a reviewer schema and bundle, and the level decision with
  its expiry — and none of the three shares code with another.` No hunk was
  found that no bullet asks for; the excess is volume, not scope.
Deferred (round 1, suggestion-class or below):
1. The second invariant-8 guard is **unreachable**: `verify` already BLOCKs a
   protected path, so `VerifyOutcome.protected` is always empty by the time the
   merge guard reads it. It is defence in depth against a future path to
   `PR_READY` that skips verify, and it is tested only through `level.decide`
   directly. Remove it or reach it from a real case; not this stage's.

- Left out, each needing its own evidence and none of it anyone's current item:
  the nightly `DECIDE` above and 2c's baseline `DECIDE`; the `codex` adapter is untouched and unused as
  a reviewer; a `local-only` consumer still runs no reviewer at all, because a
  review with nowhere to post is not written anywhere; `gh pr merge --squash`
  does not delete the remote branch, so L2 will leave `explore/` branches on
  `origin`; and the L2 path has been exercised only against a fake `gh`, never
  against GitHub, since this consumer is L1 by decision.

## Controller status

- Controller decision 2026-08-29: Stage 4 runs 4b (modes, caps) before 4a
  (drills), because the open-PR-cap drill needs the cap to exist. L2 is not
  enabled on this consumer until the sandbox DECIDE (Stage 2b review) is taken.

- Operator authorisation 2026-08-29: run every stage without stopping between
  them; stop only when the roadmap is done or a stage is blocked. Paid or
  fleet runs remain out of scope. Decisions taken by the controller are
  recorded in each stage record.
- Kernel checkout: `~/centos_ex/projects/VibeCoding/agent-loop`.
- Last completed cycles: 1b, 2a (kernel pushed), 2b and 2c (kernel ten commits
  ahead of origin, unpushed; two DECIDEs open from 2c, both about what a round
  can verify), and 3 (kernel three commits ahead of origin, unpushed; PR #94
  open at L1 with a green check; one new DECIDE, the nightly that cannot fire).
  Current: 4a.
- Resume instruction for any session: read this block and the last stage
  record, then continue with the next cycle of §4.
