# VPRO2 Security Model

## Trust Objective

VPRO2 prevents a Worker-controlled engineering loop from obtaining success by
editing the goal, weakening acceptance, forging evidence, silently reducing
scope, spending unapproved resources, or repeating an ineffective path under a
new name.

The reference implementation is fail-closed, but its file hashes and HMACs are
not a substitute for operating-system authority separation.

## Protected Authorities

Production deployment must keep these outside Worker write and read authority
as appropriate:

- the extracted VPRO2 release and its embedded manifest;
- the external operator receipt authorizing the manifest;
- the external Milestone contract;
- evaluator executables, schemas, and trust material;
- the controller run root, event journal, budget ledger, and terminal receipt;
- five distinct role keys and the state-seal key;
- operator approval and real-environment credentials;
- non-rollback or append-only storage used for run state and receipts.

The framework root, project root, Worker workspace, run root, contract path,
receipt path, evaluator authority, and signing-key locations are separate
runtime authorities. Mere placement in different repository directories is not
security isolation.

## Verify-Before-Import

The protected wrapper invokes:

```text
python3 -I -S -B /read-only/VPRO2_LAUNCH.py ...
```

`-I` ignores user site and `PYTHONPATH`, `-S` avoids automatic site imports,
and `-B` prevents bytecode writes. Before importing `vpro2`, the launcher:

1. loads the fixed embedded manifest and an absolute external receipt path;
2. checks exact schemas, fields, framework version, and manifest digest;
3. rejects a receipt inside the framework, unsafe permissions, and hard links;
4. validates every safe relative release path and rejects user-controlled
   symlink traversal;
5. hashes every declared file;
6. enumerates every declared release root and rejects missing, extra,
   unsupported, or symlink entries;
7. confirms that the launcher and manifest are protected paths.

Only then is the verified `src/` directory placed on `sys.path`. There is no
fallback to a repository receipt, default manifest, installed `vpro2` package,
or unverified `PYTHONPATH` module.

The receipt schema authorizes a manifest; it does not generate one. Release
authoring and signing are external packaging operations. Runtime commands do
not expose update, reseal, self-repair, or migration functions.

## Role Authentication

Controller, Worker, Reviewer, Evaluator, and Operator actions use distinct
`vpro2-authority-envelope-v1` credentials. Envelopes bind the run, role,
action, nonce, issuance, expiry, and canonical payload. The verifier rejects a
wrong role, action, run, key, time window, or reused nonce.

The local reference envelope uses HMAC-SHA256. HMAC authenticates messages
between protected components, but a process holding a verification secret also
has the mathematical ability to create a tag. Strong deployments therefore
place each role signer and its key behind a separate service or OS identity,
and expose only verification or narrowly scoped signing APIs to the controller.
An asymmetric or remote attestation profile may replace local HMAC without
changing the role separation rules.

Actor strings, process names, prose claims, and environment variables are not
identities. Keys must be at least 32 random bytes, unique per role and state,
outside framework/workspace/run roots, free of hard links, and inaccessible to
the Worker. The controller must not expose a general signing command.

## Worker Isolation

Worker access is restricted to the active temporary objective:

- a bounded, digest-recorded context manifest;
- a transaction derived from the current product baseline;
- the declared write subset only;
- declared tools and capabilities only;
- a reserved amount of time, context, writes, evidence, and cost.

The framework, contract, evaluators, authority paths, controller state, raw
evidence, and keys are never Worker-writable. Pre/post workspace manifests
reject out-of-scope effects. A candidate cannot promote itself; only the
Controller may promote a transaction after independent Goal Delta evaluation.

Filesystem digests detect modifications but do not stop a same-UID process from
attempting them. Use separate users, read-only mounts, namespaces/containers,
protected CI, or a controller service. Host network, devices, processes,
credentials, and costly infrastructure need equivalent capability isolation.

## Independent Evaluation

Evaluator definitions are immutable contract inputs. The evaluator runner
executes the exact sealed tool and adapter, with no shell and no Worker-granted
capabilities. It binds result files to run ID, evaluator ID, input digest, and
product digest; checks structured condition, evidence, and causal-fact fields;
checks exit-code consistency; and rejects any evaluator change to the Worker
workspace.

Evaluator reports and logs remain controller-owned, and admitted artifacts are
copied into per-evaluation content-addressed archives before Goal State is
sealed. macOS uses a deny-by-default `sandbox-exec` profile with exact declared
reads, one sealed executable, private result/scratch writes, and no network.
Linux uses an isolated `bwrap` root containing sealed system runtime roots,
declared inputs, and private result/scratch writes; it does not mount the host
root or Worker workspace, and admission sees raw evidence only when declared.
Because a general runtime root can contain additional executables, high-risk
Linux deployments must add an operator-owned seccomp/LSM execution policy or a
minimal evaluator runtime image. Process-group termination, file-descriptor and
file-size limits, scratch cleanup, and scratch post-audit bound the in-process
fallback; an operator-owned filesystem quota remains mandatory because POSIX
RLIMITs cannot impose a portable per-directory byte quota. Missing, malformed,
timed-out, contradictory, or stale reports are not PASS. Evaluator drift or a
defective acceptance contract cannot be repaired inside the active run. The
Operator must select a new evaluator/contract version and start a new run.

## Real Evidence

`capture_class: REAL` requires provenance, a finite freshness interval, exact
run binding, exact product binding, admission by every declared independent
evaluator, and `substitution_policy: FORBIDDEN`.

The following never satisfy a required real-evidence condition:

- fixtures, simulations, dry runs, generated examples, or Worker self-reports;
- smaller, partial, relabelled, or silently downscaled executions;
- missing, skipped, unsupported, stale, or cross-run artifacts;
- a PASS record whose named artifact is missing or unsafe;
- raw capture without current independent admission;
- evaluator admission whose evaluator or product digest has changed.

Raw capture and evaluator admission have separate digests. A read-only
admission rerun may reuse preserved raw capture only while provenance,
freshness, run, product, and integrity bindings remain valid.

## State And Audit

State writes are locked and atomic. Each transition appends an HMAC-authenticated
event containing the prior event tag and current state payload digest. The JSONL
journal must exactly match the in-state event list. Milestone, Goal State, Gap
Graph, objective, review, reservation, transaction, evaluator report, Goal
Delta, path decision, and terminal records are linked by digests.

Both success and failure produce an authenticated terminal receipt. Verification
recomputes the terminal predicate and all current authority digests; it does not
trust a mutable `status` field.

HMAC chains detect editing, truncation, and inconsistent mirrors, but cannot
detect restoration of a complete earlier authenticated snapshot. The run root
must therefore use operator-controlled monotonic, non-rollback, or append-only
storage. Backups need rollback-resistant generation or transparency-log checks.

## Same-UID Limitation

If the Worker and Controller share a UID with unrestricted host access, the
Worker may read HMAC keys, replace a release and receipt together, attach to
processes, alter files between checks, or restore an old state snapshot. No
Python path check or digest can make that deployment adversary-safe.

For trusted runs, isolate the Worker from the Controller and Operator with OS
permissions or services. Repository-local manifests and receipts are useful
development receipts, not a production root of trust.

## Fail-Closed Events

The controller terminates immediately on framework, contract, evaluator,
authority, state, evidence, transaction, or event-chain integrity anomalies.
It also terminates under the frozen budget, stagnation, no-plan, persistent
environment, and authenticated operator-abort policies. None of these failures
may be converted into success, a reduced Milestone, a fresh budget, or an
automatic framework repair.
