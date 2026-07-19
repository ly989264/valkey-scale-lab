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
Authorization Lease: `{"expires_at":"","milestone":"m1","nonce":"","remaining":0,"status":"empty","version":1}`
No-progress count: 0
```

Before an authorized real run, a human edits only the JSON value to a unique,
short-lived active lease, for example:

```text
Authorization Lease: `{"expires_at":"2026-07-18T16:00:00Z","milestone":"m1","nonce":"m1-20260718-01","remaining":1,"status":"active","version":1}`
No-progress count: 0
```

`authorize-real` validates and atomically consumes one execution before the
job protected by the `valkey-real` Environment can start. Expired, exhausted,
revoked, malformed, or concurrently changed leases produce `BLOCKED`. A label
edit cannot resume the loop; only dispatch with `action=resume` can do that.

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
Agent output followed by its single repair, candidate `BLOCKED`, lease
exhaustion, runner interruption, and recovery cleanup. Do not enable automatic
merge until all drills pass and `valkey-local` is online with all three routing
labels visible in GitHub.

After all drills pass, enable repository auto-merge and set
`MILESTONE_LOOP_AUTO_MERGE=true` before the full M1 acceptance run.

Normal operation starts with:

```bash
gh workflow run milestone-loop.yml -f action=start -f milestone=m1
```

After a blocker is corrected, the only recovery entry is:

```bash
gh workflow run milestone-loop.yml -f action=resume -f milestone=m1
```

Final completion is not inferred from Issues, PRs, or candidate Checks. It is
only the `PASS` summary emitted by the fixed M1 Gate on `valkey-real`, followed
by human Milestone closure.
