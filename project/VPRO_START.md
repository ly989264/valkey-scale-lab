# VPRO Start

VPRO is a fixed, milestone-neutral controller for Codex goal work. A sealed
external milestone bundle supplies the goal, objective selection, program
checks, validation tiers, gates, acceptance rules, evaluator boundaries, and
write scope. VPRO supplies only the control state machine and its audit rules.

VPRO is a successor design derived from the effective controller mechanisms in
V9. It does not modify or replace V9. Do not edit any V9 controller, control
block, manifest, state, tests, evaluator, reviewer evidence, or historical
evidence when creating or running VPRO.

## Fixed Framework

Once the VPRO release is finalized, AI must not update, reseal, migrate, fork,
or otherwise evolve the framework. The CLI deliberately has no framework
`update`, `reseal`, or `migrate` command. A framework defect must stop the run
with a framework error and be returned to an external operator. It is not an
evaluator gap and has no AI-owned repair transition.

A digest stored beside writable framework code is only tamper-evident. An AI
that can edit both the code and that digest can replace both. Real enforcement
therefore requires an external operator-controlled framework anchor and an OS,
container, or protected-CI boundary that makes the finalized framework and its
anchor read-only to the worker. Every VPRO command verifies that external
anchor before trusting a bundle or run state.

`codex/vpro/framework_release.json` is the release receipt to copy to the
operator-controlled read-only anchor location. The repository copy is not a
security boundary and must never be treated as the production anchor.

## Bundle Binding

The bundle must conform to
`schemas/vpro/milestone_bundle.schema.json` and use
`schema_version: vpro-bundle-v1`. It is operator-provided policy, not worker
output. A bound bundle, controller state root, both controller HMAC keys, and
the frozen framework root must all be outside the worker workspace. Bundle
content is immutable after a run is bound.

The intended command flow uses an operator-protected `vpro` launcher:

```bash
export VPRO_FRAMEWORK_ANCHOR=/operator/read-only/vpro-anchor.json
export VPRO_STATE_HMAC_KEY_FILE=/operator/controller/vpro-state-hmac.key
export VPRO_APPROVAL_HMAC_KEY_FILE=/operator/signer/vpro-approval-hmac.key

vpro framework-verify

vpro milestone-template

vpro \
  --project-root /worker/workspace/product \
  --workspace-root /worker/workspace \
  --bundle /operator/bundles/<milestone-id>/<bundle-version>/bundle.json \
  milestone-validate

vpro \
  --project-root /worker/workspace/product \
  --workspace-root /worker/workspace \
  --bundle /operator/bundles/<milestone-id>/<bundle-version>/bundle.json \
  --profile <profile-id> \
  --run-root /operator/controller/vpro-runs/<new-run-id> \
  --actor operator bind
```

All trust-bearing commands resolve the same operator anchor from an explicit
protected-launcher environment variable `VPRO_FRAMEWORK_ANCHOR`; the CLI has
no option to replace the fixed manifest or that trust-root path. The separate
`framework-verify` call is a readiness check, not a substitute for verification
inside later commands.

The protected launcher must start an operator-read-only Python executable in
isolated, no-site mode, add the frozen source path only after interpreter
startup, and then run `valkey_scale_lab.vpro`. It must not use
`PYTHONPATH=src python -m ...`: Python can execute a worker-owned
`sitecustomize.py` before VPRO verifies its framework anchor. The parent package
initializer is part of the framework manifest for the same pre-verification
reason.

The supplied frozen bootstrap is `VPRO_LAUNCH.py`. The operator's read-only
`vpro` wrapper should execute it as follows, using a protected absolute Python
path rather than caller `PATH`:

```text
/operator/read-only/python3 -I -S -B /operator/read-only/vpro/VPRO_LAUNCH.py <arguments>
```

The bootstrap location is the framework root only. Product and worker roots
come from the explicit `--project-root` and `--workspace-root` options; they
are never inferred from the imported framework package. Starting the repository
copy with a worker-writable framework root is not a supported real-run path.

An extracted distribution consists of the framework manifest, every path in
its `files` list, and any additional `protected_paths`, all at the same relative
locations. Keep the external anchor as a separate operator-controlled copy of
the release receipt. Product bundles, adapters, evaluators, milestone files,
and evidence are not framework files and must remain with their respective
product or operator authority. The frozen `valkey_scale_lab.vpro` import name is
only the bootstrap ABI; it does not make the extracted framework depend on a
Valkey product tree.

`milestone-template` prints the sealed, milestone-neutral starter bundle.
`milestone-validate` (with `bundle-validate` retained as a compatibility alias)
returns a machine-readable report. Invalid bundles include every absent
required field as a JSON path in `missing_fields`, the semantic parser error in
`errors`, and the template command. A valid bundle also reports
`execution_readiness`: its static scope covers authoritative paths and declared
executables. Missing static authority produces `BLOCKED` even though
configuration `status` remains `PASS`; dynamic resources still require the
gate's controller-scheduled preflight. `bind` rejects static `BLOCKED` readiness
and performs the same authoritative validation again, so a separate successful
validation command cannot authorize a later changed bundle.

`bind` accepts only a new empty run root. It resolves the selected profile and
its dependency closure once, seals the resolved plan, and records framework,
bundle, plan, product, and evaluator digests. It never imports mutable PASS
results, cache entries, reviewer checks, or completion claims from another
controller run.

## Controller Loop

After binding, scheduling remains controller-owned:

- Every evidence gate first runs its read-only, unprivileged evaluator guards.
  A failing guard blocks the gate before any operator approval or capture.

```bash
vpro \
  --project-root <project> --workspace-root <workspace> \
  --bundle <bundle> --profile <profile> --run-root <run-root> doctor
vpro \
  --project-root <project> --workspace-root <workspace> \
  --bundle <bundle> --profile <profile> --run-root <run-root> \
  --actor worker next
```

Follow the returned work item. Use `evaluate`, `review`,
or `accept-evaluator-repair` only for the active work item and with its exact
work item identifier. Gate approval uses the exact current controller-issued
challenge digest. Approval documents use `vpro-gate-approval-v2` and require an
HMAC-SHA256 from the protected external signer; an actor label alone is never
authority. `next` is idempotent while work is active.
Do not edit controller state or rerun unchanged expensive checks outside the
controller.

The controller loop is automatic at the scheduling and evidence level, not an
embedded worker daemon: an external orchestrator must keep calling `next` and
dispatch each item to the required worker, fresh reviewer, gate runner, or
operator. Objective dependencies form a sealed DAG so prerequisite closure and
stale-result revalidation cannot be bypassed. VPRO chooses one ready objective
at a time in sealed bundle order; v1 does not run independent branches in
parallel. A reviewer can discover one reproducible cheap gap in a frozen clause
per round. If the review budget ends without `NO_GAP`, the objective blocks
rather than turning budget exhaustion into completion.

The approval tag is computed over the ASCII domain
`vpro-gate-approval-v2\\0` followed by compact, key-sorted JSON containing all
approval fields except `hmac_sha256`. The two key files and every parent
directory must be operator-controlled and unavailable to worker processes; a
path merely outside the workspace is not enough when an arbitrary same-UID
host process can still read or replace it.

Every check runs under a sealed platform filesystem sandbox: `sandbox-exec` on
macOS or Bubblewrap (`bwrap`) on Linux x86-64/AArch64. The host is
mounted/readable as needed, but only controller-created scratch and declared
evidence output parents are writable. A declared evidence output may be a
regular file or a non-symlink directory; directories are recursively digested.
Both HMAC key files are explicitly unreadable inside the sandbox; checks without
declared capabilities also lose network and daemon-socket access. On Linux,
anonymous `socketpair` IPC and I/O on already-owned descriptors remain available
so local test-process coordination still works. Their standard input is
`/dev/null`. Bind fails closed when the platform or architecture sandbox policy
is unavailable.

Completion comes only from current executable evidence. A worker statement,
document, commit, or hand-edited state is never completion evidence. A
milestone-complete profile must cover every objective and gate declared
required by its bundle. A subset profile can produce only `PROFILE_COMPLETE`.

Use `verify-completion` to revalidate a terminal completion seal against the
external framework anchor, immutable bundle, resolved plan, final evaluator,
current product, event journal, and admitted evidence.

The keyed seals prevent a worker from synthesizing new state or completion
records. Freshness against restoration of an older, fully authenticated run
snapshot additionally requires operator storage that is non-rollback or an
external append-only controller service; the local file format cannot supply a
monotonic trust anchor by itself.

The complete contract and state-machine rationale are documented in
`docs/codex/VPRO_ARCHITECTURE.md`.
