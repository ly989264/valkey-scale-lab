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

## Controller status

- Operator authorisation 2026-08-29: run every stage without stopping between
  them; stop only when the roadmap is done or a stage is blocked. Paid or
  fleet runs remain out of scope. Decisions taken by the controller are
  recorded in each stage record.
- Kernel checkout: `~/centos_ex/projects/VibeCoding/agent-loop`.
- Last completed cycle: Stage 1a. Current: Stage 1b.
- Resume instruction for any session: read this block and the last stage
  record, then continue with the next cycle of §4.
