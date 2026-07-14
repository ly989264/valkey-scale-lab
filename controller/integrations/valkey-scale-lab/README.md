# Valkey Scale Lab VPRO2 Integration

This adapter is controller-owned and keeps `controller/vpro2/` free of Valkey
milestone semantics.

`compile_contract.py` reads a project milestone and verification catalog, then
maps every product success condition and real evidence gate into an unsigned
`vpro-milestone-v2` draft. `policy.json` supplies only controller concerns:
budgets, capability approvals, evaluator limits, and termination policy.

The independent evaluators under `evaluators/` do not import
`valkey_scale_lab`. The milestone evaluator checks the sealed milestone,
catalog, and prerequisite completion authority. Separate admission evaluators
validate dynamic capability-suite receipts and complete raw real-run bundles.
The real evaluator reconstructs the required raw capture and provenance graph
from the sealed scenario definition rather than trusting a candidate's list.

Generate a draft:

```bash
python3 controller/integrations/valkey-scale-lab/compile_contract.py \
  --milestone m1 \
  --output /tmp/valkey-m1.vpro2.draft.json
```

This command does not sign, bind, or start a run. Before trusted execution, an
operator must stage the paths named by the draft in this layout outside all
worker write roots:

```text
product/     selected product snapshot, milestones, catalog, and acceptance tests
authority/   contract, evaluators, producer, toolchain policy, schemas, prerequisites
run_evidence/
```

The operator reviews the draft, seals all authority and selected acceptance
inputs read-only, and only then binds the external VPRO2 run. Verification
receipts are not presealed authority: they are regenerated in `run_evidence/`
for the current run and product digest after each retained product change.

Fingerprint the operator-approved Python/pytest closure before binding:

```bash
python3 controller/integrations/valkey-scale-lab/tools/run_verification.py fingerprint \
  --python /path/to/hermetic/python \
  --output /snapshot/authority/verification_policy.json
```

After VPRO2 returns its bind challenge, produce current suite receipts outside
the worker workspace:

```bash
python3 /snapshot/authority/tools/run_verification.py run \
  --python /path/to/hermetic/python \
  --workspace-root /snapshot \
  --milestone m1 \
  --run-id <vpro2-run-id> \
  --product-digest <bind-challenge-product-digest> \
  --evidence-root /controller-runs/<run>/evidence \
  --policy /snapshot/authority/verification_policy.json
```

The producer refuses a stale product digest or a test run that mutates the
product snapshot. The admission evaluator verifies suite definition, command,
toolchain, producer, log, run, product, timestamps, skips, and all receipt
digests.

For M2 and M3, first verify the prior VPRO2 terminal receipt with its original
run authority, then create the immutable prerequisite input:

```bash
python3 controller/integrations/valkey-scale-lab/tools/seal_prerequisite.py \
  --milestone project/milestones/m1/milestone.json \
  --terminal /controller-runs/<m1-run>/terminal.json \
  --final-admission /controller-runs/<m1-run>/evidence/local.exact.200/admission.json \
  --output-dir /snapshot/authority/prerequisites/m1 \
  --terminal-verified
```

`schemas/verification_receipts.schema.json` defines the dynamic receipt
envelope. `schemas/prerequisite_completion.schema.json` defines the sealed
cross-milestone promotion authority. Distributed gates remain fail-closed
until their milestone supplies a sealed scenario definition and complete
distributed evidence profile.
