# Milestone Loop Control Plane

This directory is the trusted, repository-owned control plane described by
`miletone_loop/plan.md`. It is deliberately separate from `project/`. The loop
has no database or persisted work graph: it rebuilds current state from the
default branch, GitHub Milestones, Issues, Labels, PRs, Checks, and one Control
Issue on every round.

## Fixed Interfaces

- The only workflow is `.github/workflows/milestone-loop.yml`.
- Dispatch accepts only `action=start|resume` and `milestone=m1|m2|m3|m4`.
- Candidate admission always runs `./gate suite repository.all`, then one
  Test/Suite selected from the trusted base SHA's `project/catalog.json`.
- Final acceptance always runs `./gate milestone <milestone>` on the merged
  default branch.
- `PASS`, `FAIL`, and `BLOCKED` map to GitHub `success`, `failure`, and
  `action_required` through a trusted Check Run.

Planner and Worker use bounded `codex exec --output-schema` messages. Their
process environments exclude GitHub write tokens, real-environment
credentials, lease values, and SSH agents. Planner is read-only; Worker writes
only in an isolated worktree. The coordinator performs every GitHub write only
after a fresh state comparison.

For interactive Codex work, prefer the connected GitHub Connector. A sandboxed
`gh auth status` may not be able to read the host macOS Keychain and must not,
by itself, be treated as proof that the user's host GitHub login has expired.
Use `gh` only when Connector coverage is insufficient, and confirm host CLI
authentication from the user's normal terminal when it matters.

## Required GitHub Configuration

1. Create open GitHub Milestones titled exactly `m1`, `m2`, `m3`, and `m4`.
2. Register one repository-level self-hosted runner as the `allgood` user:

   ```text
   name:    valkey-local
   root:    /Users/allgood/actions-runner-valkey
   version: 2.335.1
   labels:  self-hosted, macOS, ARM64, valkey-codex, valkey-verify, valkey-real
   ```

   Install this one runner as an `allgood` `launchd` service. The workflow's
   global concurrency serializes its role jobs; the three custom labels are
   routing labels, not separate runners or macOS account boundaries.
3. Create the protected `valkey-real` Environment with a required human
   reviewer. Put only real-check/OIDC configuration in that Environment.
4. Create repository variable `MILESTONE_LOOP_AUTO_MERGE=false` for the first
   activation and rehearsal. Set it to `true` only after the required manual
   rounds and recovery drills pass.
5. Disable/remove Goal, gh-aw, and any other scheduler that can mutate the same
   Issues or PRs. Confirm that the repository has no other workflow.
6. After the bootstrap sequence below, enable squash merge but keep repository
   auto-merge disabled through rehearsal. Protect the default branch, require a
   pull request and the `milestone-loop / candidate` Check with the
   strict/up-to-date-branch requirement, disable automatic branch updates, and
   require CODEOWNERS review for protected contract changes. This keeps a base
   branch change from being folded into an already verified candidate tree.

The single runner uses the exact tool versions in `environment.json` and
`pytest==8.4.2`. All roles share the `allgood` uid, Home, Keychain, runner root,
and work root, so labels must not be described as OS-level credential isolation.
Instead, GitHub permissions are job-scoped, real credentials are available only
to the protected `valkey-real` Environment job, Planner/Worker run through the
Codex sandbox, candidate Gate subprocesses strip GitHub, Codex/OpenAI, SSH,
cloud, lease, and real-environment variables, and every role uses separate
checkout/runtime paths plus cleanup. A malicious same-uid process or compromised
host is outside this threat model.

For Apple silicon, the pinned runner archive is
`actions-runner-osx-arm64-2.335.1.tar.gz` with SHA-256
`e1a9bc7a3661e06fa0b129d15c2064fe65dc81a431001d8958a9db1409b73769`.
Set `ACTIONS_RUNNER_VERSION=2.335.1` in the runner service environment; the
workflow rejects a missing or different value.

The Mac must remain powered and awake. GitHub's self-hosted queue and job limits
are the outer bounds; the workflow and Agent runner add narrower wall and
silence timeouts. Runner upgrades or tool drift require updating the protected
fingerprint in a separately reviewed `contract-change` PR.

## Control Issue And Lease

The coordinator creates exactly one Control Issue per Milestone. Its body may
contain only these two lines:

```text
Authorization Lease: `{"default_sha":"","entrypoint":"","expires_at":"","milestone":"m1","nonce":"","remaining":0,"run_attempt":"","run_id":"","status":"empty","version":2}`
No-progress count: 0
```

The coordinator performs only read-side readiness preparation and records one
deduplicated `REAL_AUTHORIZATION_REQUIRED` Control Issue comment with the run
link. Both real entrypoints then wait directly on the protected `valkey-real`
Environment. The required reviewer's **Approve and deploy** action is the sole
normal human authorization for that invocation; approving a PR authorizes only
code merge and never authorizes a real run.

After Environment approval, the real job checks out the prepared immutable SHA.
Its first repository-owned command rechecks the Milestone, entrypoint, default
and checkout SHA, readiness fingerprint, live workflow run ID and attempt, and
the `valkey-real` required-reviewer rule and Control Issue. It creates a
short-lived version-2 Lease with `remaining=1` only
in memory and immediately consumes it. A single Control Issue update persists
only the invocation-bound `exhausted`, `remaining=0` receipt. Global workflow
concurrency serializes trusted controller executions; exact observed pre-write
and post-write changes fail closed, so that controller has one visible Lease
transition. Canonical legacy version-1 `empty` or `exhausted` state may migrate
after fresh approval. Active, revoked, malformed, stale, replayed, or changed
state is `HARD_BLOCKED`; a known non-replaceable Lease is reported before the
Environment review is requested. Manual Control Issue edits are not an
authorization or revocation API.

Waiting, rejection, or cancellation at the Environment gate executes no step,
so it cannot generate or consume a Lease. Every new workflow invocation or run
attempt must receive a new Environment approval and a new Lease; the controller
never renews, replays, or auto-authorizes one. Direct `workflow_dispatch`
`start|resume` remains a break-glass recovery interface, not a normal approval
step. Product commands and OIDC require confirmed authorization. Final
real-resource cleanup is eligible after the trusted authorizer emits an
invocation-bound Lease-write-attempt receipt; an `authorized=false` receipt
permits only cleanup and `BLOCKED` recording, never a product command or OIDC
request.

## M2 Candidate Readiness

The exact reviewed M2 definition in which all four candidate bindings are
`current-default` routes through the existing `start|resume` and `MILESTONE`
authorization path to candidate discovery. The discovery job first waits for
protected `valkey-real` Environment approval, then the invocation authorizer
rechecks that canonical definition and the live default SHA before generating
and consuming its one-time Lease. Missing, invalid, duplicated, inconsistent,
or explicit-baseline bindings remain `BLOCKED`; the Planner cannot choose a
candidate or turn that blocker into a product Work Item.

Discovery and promotion are separate contract decisions. Discovery retains the
exact-50 topology, cleanup, and current-invocation evidence rules, but emits a
distinct candidate-selection-only artifact. It never emits or substitutes for
`m2_performance_report.json`, is never recorded as a Milestone result, and is
not reusable M2 admission evidence.

Every discovery attempt is sealed after cleanup into a bounded result that is
bound to the workflow run and attempt, tested default SHA, invocation id,
canonical report digest, and evidence-tree digest. An `always()` recorder then
publishes the independent `milestone-loop / m2-discovery` Check and a trusted
Control Issue marker. A PASS means only that the candidate-selection screen
completed; candidate cell losses, including no surviving candidate, are never
rewritten as implementation defects and never dispatch the full M2 Gate.

Only a statically allowlisted programming failure with one unambiguous affected
campaign may request the existing bounded Planner/Worker diagnosis. `CaptureError`,
environment and safety failures, missing or invalid artifacts, stale SHAs,
digest mismatches, cleanup failures, and unknown results require human action.
Replay of the same tested-SHA failure fingerprint, including a new attempt, is
a no-op after its one diagnosis dispatch. A discovery repair may touch only a
narrow reviewed product path set and is always opened as a `contract-change` PR;
it is never auto-merged. After that PR is merged, the existing `after-merge` job
dispatches a fresh planning round.

Durable human-action transitions are trusted, deduplicated Control Issue
comments. Their key includes Milestone, state, target PR/run, and SHA. The
defined states are `PR_REVIEW_REQUIRED`, `REAL_AUTHORIZATION_REQUIRED`,
`HARD_BLOCKED`, and `M2_COMPLETE`; the repository does not contain an email or
other external notification service. Readers page the full Control Issue
comment history before marker deduplication; the human-action recorder appends
a missing marker without truncating, deleting, or migrating old comments.

After reviewing discovery, a human-reviewed `contract-change` PR must set the
same explicit candidates on the formation, failover, and stability Checks. A
human may explicitly redefine M2 to replace the failover screen with one named
direct full-validation candidate; that exception must be encoded in the fixed
M2 contract, retain every matrix cell and all thresholds, durations, safety,
cleanup, and Environment gates, and cannot promote a default. If
the chosen formation candidate needs a bounded parallelism that the current
parameters cannot express, that PR must extend the Check contract explicitly;
it must not change the product default first. The complete M2 Gate then
captures fresh discovery, promotion, stability, and regression evidence. It
cannot reuse the selection run, and that pre-promotion result is evidence for
a later reviewed default-promotion Contract Change rather than permission to
close M2. After promotion, the complete authoritative M2 Gate must run again
with a new Lease and fresh evidence so its unchanged exact-50 and exact-200 M1
checks exercise the promoted defaults. Only that post-promotion run can support
closing M2.

## Activation And Drills

Run the hermetic contract check first:

```bash
python3 .github/milestone-loop/selftest.py
```

The first activation has a one-time trust bootstrap and must use this order:

1. Human-review the first `contract-change` PR while
   `milestone-loop / candidate` is not a required Check.
2. Merge that control-plane PR without making the expected bootstrap candidate
   failure required. Its trusted base does not yet contain
   `.github/milestone-loop/loop.py`.
3. Confirm the control plane is on the default branch, then enable the strict
   required `milestone-loop / candidate` Check. This exception never applies to
   later PRs.
4. Continue with the three rehearsal rounds and the full GitHub M1 acceptance.

With auto-merge still disabled, perform at least three real GitHub dispatch
rounds. Keep their run URLs in the activation PR or Control Issue comments and
exercise: repeat dispatch/idempotency, a stale live-state rejection, malformed
Agent output followed by its single repair, candidate `BLOCKED`, Environment
rejection/cancellation with no Lease change, same-attempt replay rejection,
runner interruption, and recovery cleanup. Do not enable automatic
merge until all drills pass and `valkey-local` is online with all three routing
labels visible in GitHub.

After all drills pass, enable repository auto-merge and set
`MILESTONE_LOOP_AUTO_MERGE=true` before the full M1 acceptance run.

Normal operation continues from the existing post-merge dispatch. Direct
dispatch is retained only for break-glass start or recovery:

```bash
gh workflow run milestone-loop.yml -f action=start -f milestone=m1
```

After a hard blocker is corrected, the break-glass recovery entry is:

```bash
gh workflow run milestone-loop.yml -f action=resume -f milestone=m1
```

Final completion is not inferred from Issues, PRs, or candidate Checks. It is
only the `PASS` summary emitted by the fixed M1 Gate on `valkey-real`, followed
by human Milestone closure.
