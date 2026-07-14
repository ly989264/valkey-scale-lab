# Migration From VPRO1

## No In-Place Upgrade

VPRO1 and VPRO2 are separate releases and protocols. The frozen
`controller/vpro/` 1.0.0 files, manifest, receipt, state, reviewer records, and
historical evidence remain unchanged.

There is no VPRO1 state-to-VPRO2 migration, no manifest reseal, no receipt
replacement, and no command that upgrades a running controller. Selecting
VPRO2 means extracting and protecting a separate release, authoring a new
`vpro-milestone-v2` contract, and binding a fresh empty run root.

This successor is an operator-governed project outside the VPRO1 runtime. It is
not VPRO1 responding to its own `FRAMEWORK_DEFECT` by editing itself.

## Contract Reauthoring

A VPRO1 bundle cannot be trusted as a VPRO2 contract by deleting a few fields.
The operator and independent acceptance owner must reauthor it:

| VPRO1 concept | VPRO2 treatment |
| --- | --- |
| `milestone.goal` | Becomes the reviewed immutable `final_goal`. |
| clauses | Split into atomic executable `success_conditions`; prose alone is insufficient. |
| objectives and `depends_on` | Removed. VPRO2 derives temporary objectives and causal dependencies each iteration. |
| profiles | Removed. VPRO2 has no subset-completion claim. |
| common/objective/closure checks | Recast as sealed independent Milestone evaluators where they truly own a condition verdict. |
| evidence gates | Split into real-evidence requirements, capture authority, and independent admission evaluators. |
| fixed validation tiers/order | Replaced by fresh Milestone evaluation and dynamic root-blocker planning. |
| worker context/write paths | Widened only into global safety maxima; each temporary objective receives a smaller controller-selected subset. |
| attempt/review budgets | Reauthored as total resource budgets and explicit failure thresholds. |
| evaluator repair paths | Removed from active-run Worker authority. Evaluator changes require a successor contract and fresh run. |

The VPRO2 schema recursively rejects VPRO1 objective, dependency, profile,
gate, and implementation-order fields. Any conversion utility may emit only an
untrusted draft and must never sign, bind, or claim semantic equivalence.

## Evidence Reuse

VPRO1 PASS results, objective completion, profile completion, cache entries,
review conclusions, and budget epochs never carry into VPRO2.

Preserved raw real-world capture may be referenced only when all of these are
true:

- the new VPRO2 contract explicitly permits the relevant evidence requirement;
- the raw artifact is copied or mounted into a new controller-owned evidence
  authority without rewriting historical storage;
- current VPRO2 admission evaluators independently validate provenance,
  capture class, freshness, exact product binding, exact run binding, and
  no-substitution policy;
- the result is represented as a new VPRO2 evaluator report and evidence digest.

Because VPRO2 requires exact run binding for `REAL` evidence by default, most
VPRO1 capture will be historical input rather than completion evidence. It may
help diagnosis, but it cannot silently satisfy a new run.

Never edit `loop_evidence/` or a VPRO1 run to make it look VPRO2-compatible.

## Operational Cutover

1. Keep the VPRO1 extracted release and run roots read-only.
2. Extract VPRO2 to a different operator-controlled read-only root.
3. Verify the VPRO2 embedded manifest with a separately stored external
   receipt before importing the package.
4. Reauthor and independently review the Milestone v2 contract.
5. Provision five distinct authority identities, a separate state-seal key,
   an isolated Worker transaction environment, and non-rollback run storage.
6. Validate evaluator availability and safety paths without executing Worker
   changes.
7. Bind a fresh run and begin with full Milestone evaluation.
8. Archive the terminal success or failure receipt alongside the exact release
   receipt and Milestone digest.

Rollback of the deployment means stopping VPRO2 and independently operating an
existing VPRO1 run under its original protocol. It never means feeding VPRO2
state into VPRO1 or editing either release.
