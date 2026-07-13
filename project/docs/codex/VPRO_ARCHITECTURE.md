# VPRO Architecture

## Purpose

VPRO is a fixed controller kernel that can run any milestone described by a
valid external `vpro-bundle-v1` bundle. The kernel controls what happens next,
but it has no knowledge of a product, milestone identity, objective name,
scale, test framework, evidence shape, or domain acceptance threshold.

The bundle is the only source for:

- milestone goal and frozen contract clauses;
- objective graph and profile-based objective selection;
- worker context and allowed write paths;
- executable checks and their ordered validation tiers;
- program and evidence gates;
- retry, review, context, cache, and expensive-run limits;
- product, evaluator, check-authority, evidence, and tool boundaries.

The schema is `schemas/vpro/milestone_bundle.schema.json`. It uses JSON Schema
2020-12 and rejects unknown fields with `additionalProperties: false` at every
defined object boundary. Cross-reference and filesystem rules that JSON Schema
cannot express are mandatory semantic validation during `bundle validate` and
`bind`.

## Historical Boundary

VPRO is informed by V9 but is not a mutable V9 release. Existing V9 controller
files, goal contracts, manifests, evaluator files, state, tests, failure
reproductions, and evidence remain immutable. Historical evidence is never a
VPRO scratch area and is never rewritten during validation or a real gate.

VPRO must be implemented in a self-contained package. It must not inherit a
milestone-specific parser, migration verifier, runner environment variable, or
historical objective from any earlier controller. Existing milestone content
may be translated into an external bundle, but that bundle is not part of the
framework kernel.

## Authority Separation

VPRO retains four independent decision authorities:

1. The worker decides how to implement the active objective inside its allowed
   write paths. It cannot select the next objective or declare success.
2. The controller owns scheduling, active work, dependency ordering, attempt
   epochs, stagnation, replans, review budgets, gate ordering, and terminal
   state.
3. Program checks own PASS and FAIL. They run exact sealed argv definitions and
   record input, output, environment, and log digests.
4. A fresh reviewer looks for one requirement gap that current program checks
   missed. It cannot broaden the milestone or reject work for preference.

An external operator is a fifth, higher-trust authority. The operator selects
the bundle and profile, supplies the framework anchor, grants capabilities for
restricted gates, and owns any decision to replace a defective framework.

## Fixed Release And Root Of Trust

The finalized framework release contains the VPRO package, VPRO schemas, VPRO
contract tests, CLI, and start and architecture documents. A release manifest
hashes that complete set. Every command verifies the release digest before it
loads mutable product or state data.

This verification is only meaningful when its expected digest is outside the
worker's write authority. A manifest and expected hash in the same writable
repository are tamper-evident against mistakes, but are not an immutable root
of trust: the same actor can replace both. Production VPRO operation therefore
requires all of the following:

- an operator-controlled expected release digest or signature;
- read-only framework files enforced by the OS, a container mount, or protected
  CI rather than by prose alone;
- a run root outside worker write paths;
- a bundle that is read-only after operator selection.

The framework root, product project root, worker workspace root, external
bundle, and controller state root are distinct runtime authorities. The
launcher locates only the frozen framework; explicit CLI arguments identify
the product and worker workspace. Bind rejects a framework, bundle, or state
root inside the worker workspace.

The framework has no `update`, `reseal`, `self-repair`, version migration, or
state bootstrap escape hatch. `FRAMEWORK_DRIFT` and `FRAMEWORK_DEFECT` fail
closed. AI may not create a successor framework in response. Framework
replacement is a separate operator-governed project outside VPRO.

## Portability And Extraction

The release is a standalone filesystem closure, not an installed dependency of
the product repository. To extract it, preserve relative paths while copying
`codex/vpro/framework_manifest.json`, every `files[*].path` entry, and every
`protected_paths` entry not already present. The current protected release
receipt must exist inside that closure for boundary verification, while a
separate operator-controlled copy supplies `VPRO_FRAMEWORK_ANCHOR`. Do not copy
product bundles, adapters, evaluators, milestone descriptions, or evidence into
the framework root.

The historical `valkey_scale_lab.vpro` Python namespace is a frozen launcher
ABI, not a product-root inference or domain contract. The bootstrap adds only
its own extracted `src` directory and the CLI locates the framework by that
package's fixed relative layout. All product semantics and paths still arrive
through explicit CLI roots and an external bundle. The manifest also carries
the release-time `AGENTS.md` as governance provenance; it is protected material,
not an instruction to import the originating product or its milestones.

Portability does not remove deployment prerequisites. The extracted root,
Python runtime, anchor, HMAC keys, bundle, and state service need their stated
operator protections, and the host must provide a supported macOS or Linux
sandbox plus every bundle-declared sealed tool. Within those constraints the
same unmodified framework closure validates and runs unrelated product roots.

## Bundle Contract

### Identity And Clauses

`milestone` contains an ID, semantic bundle version, title, and goal. `clauses`
contains stable clause IDs and exact requirement text. Every objective cites
at least one clause. Reviewer findings must cite one of the exact clauses
assigned to the active objective.

The milestone version identifies an immutable bundle release, not the VPRO
framework version. Any change to a clause, objective, profile, check, tier,
gate, acceptance limit, or integrity path requires a new bundle version and a
new run. An active run never adopts a changed bundle.

### Objectives

Each objective declares:

- a unique `id` and human-readable `title`;
- `depends_on`, which must reference other objectives and form a DAG;
- `clause_ids`, which must reference existing frozen clauses;
- `context_paths`, which bound context collection;
- `worker_write_paths`, which define the only paths normal WORK may change;
- `check_ids`, which must reference declared checks;
- `required_for_milestone`, which contributes to completion coverage.

The validator rejects duplicate IDs, unknown references, self-dependencies,
cycles, path escapes, symlinks that escape the workspace, and any worker write
path that overlaps framework, bundle, controller state, evidence, evaluator,
or authoritative-check paths.

### Profile Selection

A profile is the externally chosen objective-selection policy. `bind` resolves
its `objective_ids` and the complete transitive dependency closure exactly
once. The sorted resolved objectives, checks, gates, clauses, and paths are
written as a controller-owned resolved plan and hashed. Scheduling uses only
that plan; the worker cannot re-run selection or choose an easier target.

Profiles have one of two claims:

- `MILESTONE_COMPLETE` must include every objective and gate marked
  `required_for_milestone`. Omitting either is a contract error.
- `PROFILE_COMPLETE` may select a valid subset, but its terminal state can
  never be represented as milestone completion.

`include_dependency_closure` is always true in bundle v1. `gate_ids` must
reference declared gates and include every required gate for a
milestone-complete claim.

### Validation Tiers

Tiers replace fixed validation-level meanings. Each tier has a unique ID,
unique integer rank, cost class, and `reviewer_admissible` flag. Ranks define
ordering only. Domain meanings belong in the bundle and external checks.

Cost is one of `cheap`, `normal`, `expensive`, or `operator`. Expensive and
operator checks are not reviewer-admissible. An operator-cost check requires a
current operator approval even when a gate repeats an otherwise cached plan.
The semantic validator rejects ambiguous duplicate ranks.

### Checks

Each check declares an exact argv vector, project-relative working directory,
timeout, input and output paths, authority, capabilities, cache policy, and
mode. VPRO invokes argv directly and never through a shell. It rejects inline
shell fragments, path escapes, undeclared executables, and an argv executable
not listed in `integrity.allowed_tools`. Every check argv must actually invoke a
project-local executor or adapter covered by `authoritative_check_paths` as
`argv[1]`. Declaring an unused or non-executed authoritative input is
insufficient; interpreter flags before the adapter and Python `-m` dispatch are
forbidden.

At bind, each allowed tool name resolves to an absolute executable outside all
worker/controller writable roots. Its real path and content digest are sealed,
and the tool and every parent directory must be operator-read-only. Later runs
ignore caller `PATH`, invoke only the sealed absolute path, construct a child
`PATH` only from sealed tools, and revalidate every seal before execution. An
authoritative adapter that launches another declared tool consumes its exact
controller-issued path from `VPRO_SEALED_TOOLS_JSON`; it does not resolve an
unbound child executable from `PATH`.
Python checks additionally run with isolated startup, no `site` import, no
bytecode writes, and no worker `PYTHONPATH`; a worker-owned `sitecustomize.py`
therefore cannot execute before the authoritative adapter.

Check authority is either:

- `bundle`, for a definition whose oracle is fully supplied by the immutable
  bundle and an already trusted tool; or
- `evaluator`, for a checker whose implementation is covered by the current
  evaluator digest.

An acceptance check must not depend on an oracle file that the worker can
modify. Product-owned tests can be useful development inputs, but a worker may
not weaken a mutable test and use the resulting PASS as independent acceptance
authority.

Check modes are:

- `standard`, for ordinary executable validation;
- `capture`, for generation of raw evidence under controller ownership;
- `admission`, for independent evaluation of a preserved capture.

The result records the check-definition digest, input digest, relevant product
or evaluator digest, toolchain and selected environment, return status,
duration, full log path and digest, bounded failure excerpt, and declared
output artifact digests. A cached result is valid only when every bound input
is current. Cache identity includes the complete check definition, not merely
its ID.

Declared directory inputs include every file and directory entry, including
their permission modes and conventional cache or metadata names such as
`__pycache__`, `.pytest_cache`, `.mypy_cache`, and `.git`. Workspace
authorization uses the same fail-closed principle, so empty-directory and
permission-only changes are visible. VPRO's own Python and pytest caches are
disabled or redirected into controller state; the kernel never assumes
similarly named product files are semantically inert.
Before sealing a writable work item, the controller safely creates any missing
parents of its exact authorized paths. This permits a new nested target without
excluding existing ancestor directories or their modes from authorization.

`cache_unchanged_results` is fixed true in bundle v1. The controller also keeps
an explicit run counter keyed by check-definition and input digests. This
enforces `max_expensive_runs_per_input`; caching alone is not an execution
budget. Only PASS results are cached. FAIL, timeout, execution, and environment
failures are rerun within the ordinary attempt budget without interpreting
tool-specific error text; an expensive result still cannot exceed its separate
per-input execution budget.

### Gates

Gates are externally injected completion barriers. There are two v1 kinds.

A `program` gate runs its `check_ids` after every objective in
`after_objective_ids` is complete. It is useful when a milestone needs a
cross-objective executable barrier but no raw evidence lifecycle.

An `evidence` gate first runs the bundle's read-only, unprivileged evaluator
guards, then uses this fixed generic protocol for an unprivileged preflight:

```text
GUARD -> PREFLIGHT -> optional OPERATOR_APPROVAL -> CAPTURE -> ADMISSION
```

Every evidence gate has at least one standard preflight check. Guards may not
declare capabilities, expensive/operator cost, or outputs. A failed guard
therefore blocks the gate before an approval challenge or privileged work is
issued. If a preflight itself declares a capability or an expensive/operator
tier, approval moves in front of preflight so no privileged or costly process
starts first:

```text
GUARD -> OPERATOR_APPROVAL -> PREFLIGHT -> CAPTURE -> ADMISSION
```

Its bundle supplies the preflight checks, capture check, admission checks,
dependencies, approval requirement, and completion requirement. VPRO contains
no domain scale or evidence threshold. A failed or missing preflight blocks the
gate. It cannot be converted into a smaller, simulated, fixture, or skipped
PASS. An approval is valid only when it binds the run, gate, bundle digest,
check/input digest, declared capabilities, and expiration.

The `vpro-gate-approval-v2` document binds the signer identity and challenge and
must carry an HMAC-SHA256 generated by the external protected signer. The
approval key is distinct from the state-seal key, and both key paths are masked
from every check sandbox. Actor labels without a valid HMAC are rejected,
nonces cannot be reused, and approval expiry is rechecked immediately before a
privileged phase starts.

The approval tag signs the ASCII domain `vpro-gate-approval-v2\\0` followed by
compact, key-sorted JSON of every approval field except `hmac_sha256`. The
signed fields are `schema_version`, `run_id`, `gate_id`, `bundle_digest`,
`product_digest`, `approval_challenge_digest`, `cost_acknowledged`,
`expires_at_unix`, `nonce`, and `operator_id`.

Capture receives controller-generated `VPRO_RUN_ID`, `VPRO_BUNDLE_DIGEST`,
`VPRO_PRODUCT_DIGEST`, `VPRO_EVIDENCE_ROOT`, and
`VPRO_OWNERSHIP_TOKEN` environment values. Admission binds the immutable raw
capture digest, evaluator digest, bundle digest, and product digest. Evaluator
strengthening invalidates admission, but it does not force recapture while the
preserved raw capture and product inputs remain current.

### Acceptance Policy

`common_check_ids`, objective checks, controller-accepted reviewer checks, and
`closure_check_ids` form executable acceptance. The controller orders ordinary
checks by tier rank and stops at the first failure. Closure checks are a
regression floor and must be current at final completion. Gates run only after
their declared objective dependencies.

The objective rule is
`CURRENT_PROGRAM_PASS_AND_BOUNDED_REVIEW`. A current program PASS transitions
to acceptance review while budget remains. A fresh reviewer can return:

- `NO_GAP`, which completes the objective while inputs remain current; or
- `GAP`, which must include one exact clause, one novel check, and one current
  failing reproduction.

The added check must use a reviewer-admissible tier, be hermetic, avoid current
run evidence, and place its oracle in an authoritative path. VPRO records its
definition and target-content digest in state. Later edits are integrity
failures.

A `PRODUCT_GAP` returns to normal work. An `EVALUATOR_GAP` enters controlled
evaluator repair. Gap classification must match whether the new check covers
evaluator inputs. The bundle fixes one new gap per review round and bounds all
attempts, stagnation, replans, and review rounds.
Exhausting the review budget without a final `NO_GAP` blocks the objective; it
is never positive completion evidence.

The milestone rule is
`ALL_SELECTED_REQUIRED_OBJECTIVES_GATES_AND_CLOSURE_CURRENT`. Terminal
completion requires the resolved profile coverage, every selected objective,
every selected required gate, current closure PASS results, current digests,
valid state and event seals, and no active work item.

## Attempt And Stagnation Accounting

Progress stores an explicit `budget_epoch` and `attempts_used`. Within an epoch,
attempts are monotonic. A changed failure identity, defined by the check
definition, current input digest, status, and return code, can reset only
stagnation scoring; it cannot reset attempts, replans, or review rounds.

Only two audited controller transitions may create a new attempt epoch:

- acceptance of a bounded replan; or
- acceptance of a novel, reproduced reviewer gap.

Those transitions increment `budget_epoch`, reset `attempts_used`, and consume
their separate replan or review budget. Arbitrary failure identity changes do
not create fresh budgets. This preserves bounded convergence without allowing
the worker to cycle between failures indefinitely.
The replan diagnosis is included in the next worker item and must fit both the
failure-excerpt limit and that item's fully serialized context budget before
the replan transition is committed.

## State Machine

The objective state machine is:

```text
PENDING -> WORKING -> EVALUATE
EVALUATE FAIL -> PENDING
PENDING exhausted/stagnant -> REVIEW_REPLAN -> PENDING or BLOCKED
EVALUATE PASS -> PROGRAM_PASS -> REVIEW_ACCEPTANCE
REVIEW NO_GAP -> COMPLETE
REVIEW PRODUCT_GAP -> PENDING in a new budget epoch
REVIEW EVALUATOR_GAP -> EVALUATOR_REPAIR_REQUIRED
EVALUATOR_REPAIR_REQUIRED -> REVERIFY -> EVALUATE
```

When the review budget is exhausted, a current program PASS blocks unless a
reviewer has already returned `NO_GAP` (which completes immediately). Passing
all previously accepted gap checks proves those known gaps are fixed, but does
not substitute for the fresh review conclusion required by this rule.

The run state machine is:

```text
UNBOUND -> BOUND -> OBJECTIVES -> GATES -> FINAL_CLOSURE
FINAL_CLOSURE -> MILESTONE_COMPLETE or PROFILE_COMPLETE
any active phase -> BLOCKED or integrity DRIFT terminal
```

`next` is idempotent while `active_work_item` exists. `evaluate`, `review`, and
repair acceptance require the exact active work ID. Gate approval instead
requires the exact current controller-issued challenge digest. Only the
controller writes state transitions.
Review work has empty write authority. The controller checks its issue-time
workspace and evidence baselines both before accepting the report and after any
gap reproduction, so product or workspace-sibling drift cannot be absorbed by
a replan or acceptance decision.

VPRO automates the bounded state transition and evidence loop, not the worker
or reviewer implementation itself. An external orchestrator repeatedly calls
`next` and dispatches the returned item to the named independent authority.
The objective DAG makes prerequisite closure, write/context scoping, and stale
result revalidation explicit. Ready objectives are selected deterministically
in sealed bundle order; bundle v1 does not execute branches in parallel. Gates
are likewise a sealed ordered list after their objective dependencies, rather
than a second mutable DAG.

Discovery is intentionally bounded. Executable checks find encoded failures; a
fresh reviewer may add one reproduced, cheap, unprivileged check for one frozen
contract clause per round. Product gaps return to scoped work and evaluator
gaps enter isolated repair. Review cannot invent clauses, objectives, gates, or
privileged tests after bind. Infrastructure-scale discoveries therefore require
predeclared gates or an operator-selected successor bundle, not mutation of the
active goal.

## Evaluator Repair

Evaluator code is separately versioned because executable admission may have a
real gap while the goal and framework remain correct. A reproduced
`EVALUATOR_GAP` records:

- the failing added check and its content anchor;
- baseline product digest;
- baseline digest of everything outside evaluator repair paths;
- allowed evaluator repair paths;
- current evaluator generation and digest.

During repair, the worker receives only those repair paths. Acceptance rejects
any product change or out-of-scope repository change. It runs the new gap check
and every evaluator guard check. PASS increments the evaluator generation,
records the new digest, invalidates evaluator-dependent admission results, and
enters `REVERIFY`. Failure consumes a bounded repair attempt.

A goal-clause defect, bundle defect, or framework defect is not an evaluator
gap. VPRO cannot repair or reinterpret those contracts in place.

## Permission And Path Enforcement

The controller records path digests before issuing work and checks them before
accepting evaluation:

- WORK may change only the active objective's worker write paths;
- REVIEW may add only the single proposed authoritative reviewer check;
- EVALUATOR_REPAIR may change only evaluator repair paths;
- CAPTURE may write only its new controller-owned evidence root;
- ADMISSION may read the capture and write only a separate admission area;
- state, events, logs, approvals, and completion seals are controller-owned.

All paths are normalized and checked without following a symlink. Project paths
stay within the explicit worker workspace; evidence paths stay within the
separate controller state root. Input digests reject symlink files and symlink
directories rather than silently omitting them. Overlapping role paths are
rejected at bind.

Checks additionally run inside a sealed OS filesystem sandbox. macOS uses
`sandbox-exec`; Linux x86-64/AArch64 uses Bubblewrap with the host root mounted
read-only. Only a controller-created scratch directory and declared evidence
output directories are writable. HMAC key paths are explicitly unreadable.
Checks without declared capabilities also run with `/dev/null` standard input,
private network/PID/IPC/device namespaces, and an architecture-checked seccomp
policy that rejects socket creation, connect/bind/listen/accept entrypoints,
x32 calls, keyring IPC, io_uring, and descriptor stealing. It deliberately
keeps anonymous `socketpair` and I/O on already-owned descriptors available for
local test-process coordination. Blocking socket creation still prevents host
network and pathname daemon-socket access, which a network namespace alone
would not isolate for AF_UNIX. Bind fails closed without a supported platform
and architecture policy.
Pre/post digests cover the entire worker workspace, including project siblings,
and independently cover controller evidence paths.

`integrity.evidence_roots` are logical paths below the controller-owned run
root, not worker project directories. Capture and admission checks receive the
resolved location through `VPRO_EVIDENCE_ROOT`; declared evidence inputs and
outputs are digested from that run-owned location. An output may be a regular
file or a non-symlink directory. Directory outputs are recursively sealed, and
any symlink anywhere in their tree fails closed.

Digest checks detect unauthorized edits, while the check sandbox prevents host
filesystem writes outside the controller grants. Strong separation for the
human/agent worker still needs OS permissions, separate users, container
mounts, or a controller service that keeps framework, bundle, state, and signing
keys outside the worker sandbox.

## Integrity And Audit

VPRO maintains separate digests for separate authorities:

- `framework_digest` covers the complete fixed controller release;
- `toolchain_digest` covers the absolute path and content digest of every
  operator-read-only executable admitted at bind;
- `bundle_digest` covers the immutable external goal contract;
- `resolved_plan_digest` covers the one-time profile resolution;
- `evaluator_digest` identifies the current evaluator generation;
- `product_digest` covers every declared product root and worker write path;
- capture and admission digests independently identify raw and admitted
  evidence.

Product identity excludes framework, bundle, evaluator, controller state, and
run evidence. The validator nevertheless requires every worker write path and
acceptance product input to be covered by a product root, preventing a bundle
from changing unmeasured product code.

State writes are locked and atomic. Every state transition appends an
HMAC-SHA256 authenticated event containing the prior event tag, current state
payload hash, actor, work item, transition, relevant authority digests, and
result references. Every read verifies the protected key identity, the in-state
chain, and exact `events.jsonl` parity. Full command logs remain on disk; work
items expose only bounded excerpts and paths.

Terminal `completion.seal.json` binds the anchor-authorized framework digest,
sealed toolchain, bundle and resolved-plan digests, final evaluator and product
digests, state payload and last event tag, all gate results, and all admitted
evidence. The completion file has its own HMAC-SHA256. `verify-completion`
reconstructs and authenticates the terminal decision with the protected
controller key.

These tags provide authenticity, not an independent clock or monotonic storage
primitive. Replaying an older complete set of otherwise valid state, journal,
plan, logs, and completion files is prevented by deployment: the run root must
be backed by operator-controlled non-rollback storage or an append-only
controller service. The local file format deliberately does not claim to
detect restoration of a fully authenticated historical snapshot on a hostile
same-UID host.

## CLI Lifecycle

The v1 CLI surface is intentionally narrow:

- `framework-verify` verifies the fixed external root selected by the protected launcher.
- `milestone-template` prints the sealed, milestone-neutral starter bundle.
- `--project-root ... --bundle ... milestone-validate` performs schema and
  semantic validation and reports all missing required fields as JSON paths.
  Its separate, static `execution_readiness` result is `BLOCKED` while
  authoritative paths or declared executables are unavailable. Dynamic
  resource readiness remains the responsibility of controller-scheduled gate
  preflight; `bundle-validate` is the compatibility alias.
- `--project-root ... --workspace-root ... --bundle ... --profile ...
  --run-root ... bind`
  rejects static `BLOCKED` readiness, then creates one new run and its resolved
  plan.
- `doctor`, `status`, and `next` inspect or schedule an existing run.
- `evaluate --work-item-id ...` executes checks only for that exact active WORK
  or VERIFY item. Evidence gates use a distinct unprivileged `GATE_GUARD`
  phase before any operator approval, privileged preflight, or capture.
- `review --report ...` submits one structured review decision.
- `accept-evaluator-repair --work-item-id ...` evaluates only the exact isolated
  repair item.
- `approve-gate --approval ...` consumes operator authorization bound to a
  specific active gate and digest.
- `verify-completion` reconstructs a terminal decision.

Every trust-bearing command resolves the external anchor only from the
protected launcher's `VPRO_FRAMEWORK_ANCHOR` environment and verifies it in the
same process before loading the bundle or state. A prior `framework-verify`
invocation is only a readiness check and does not authorize a later process.

The launcher itself is part of the external enforcement boundary: it must use
an operator-read-only Python in isolated, no-site mode and inject the frozen
source path only after interpreter startup. Direct `PYTHONPATH=src python -m`
startup is forbidden because `sitecustomize` would run before internal anchor
verification. The framework manifest therefore also seals the parent
`valkey_scale_lab/__init__.py` imported before VPRO CLI code. The frozen
`VPRO_LAUNCH.py` bootstrap and CLI both fail closed unless Python was started
with `-I -S -B`; the external wrapper must select that Python by protected
absolute path.

The same protected wrapper supplies distinct `VPRO_STATE_HMAC_KEY_FILE` and
`VPRO_APPROVAL_HMAC_KEY_FILE` values. Each key is at least 32 bytes, outside the
framework, worker workspace, and run root, has no hard links, and is not
group/world writable. Every parent directory must also be operator-controlled
and non-replaceable by the worker. The controller does not expose a signing
command; approval documents are produced by the external operator signer. A
same-UID process with arbitrary host access is inside the controller trust
boundary and must be excluded by the wrapper, a separate user, or a service.

The repository's `codex/vpro/framework_release.json` is only a distribution
receipt for the anchor digest. Production setup must copy it outside the worker
workspace and make that external copy read-only; pointing the launcher back at
the repository receipt provides auditability, not authority separation.

There is no bootstrap from hand-authored state, no migration from a prior
controller, no framework update, no framework reseal, and no command that edits
a bundle. Bundle authoring and release signing occur outside the VPRO runtime.
The printed template is a starting artifact, not an implicit default: every
placeholder must be replaced and `bind` always repeats validation against the
immutable external bundle.

## Required Semantic Validation

In addition to JSON Schema, `bundle validate` and `bind` must reject:

- duplicate IDs or tier ranks;
- unknown objective, clause, check, tier, profile, or gate references;
- objective cycles, self-dependencies, or incomplete profile dependency
  closure;
- a milestone-complete profile that omits any required objective or gate;
- check tools not in `allowed_tools`, tools not operator-read-only, missing
  authoritative argv adapters, module/shell/inline execution, empty argv, or
  invalid timeout and cost combinations;
- reviewer-admissible tiers marked expensive or operator cost;
- capture or admission check modes used in the wrong gate position;
- evaluator repair paths that do not cover evaluator paths;
- path escape, unsafe symlink, overlapping authority paths, or worker paths not
  covered by product roots;
- acceptance checks whose oracle is worker-writable;
- evidence gates without admission, or admission that can modify raw capture;
- empty evidence preflight plans, gate-kind fields from the other gate variant,
  non-standard checks in preflight positions, or privileged/writing evaluator
  guards;
- any milestone-specific default supplied by framework code rather than the
  bundle.

## Versioning And Genericity

VPRO accepts exactly `vpro-bundle-v1`. Bundle versions can advance while the
schema remains v1. Evaluator generations can advance only through controlled
repair. Runs are immutable records identified by framework, bundle, profile,
and resolved-plan digests.

The framework itself does not self-version forward. An unsupported bundle or
new controller requirement returns `UNSUPPORTED_BUNDLE_SCHEMA` or
`FRAMEWORK_DEFECT` to the external operator. AI must not create VPRO v2.

Framework tests use at least two unrelated synthetic bundles with different
objective graphs, tier names, tool commands, and gate shapes. A genericity
audit rejects domain names, fixed objective IDs, fixed scale values,
milestone-specific environment variables, historical migration hashes, or
hard-coded bundle paths in the VPRO kernel. This makes external injection a
tested boundary rather than a naming convention.
