# Controller

This tree owns AI control frameworks and operator policy. It is outside the
Valkey product workspace.

- `vpro/` is the frozen VPRO1 release. It is not modified, resealed, or upgraded
  in place.
- `vpro2/` is the milestone-neutral successor framework.
- `integrations/valkey-scale-lab/` converts product milestone definitions into
  unsigned VPRO2 review drafts and supplies independent Valkey evaluators.
- `legacy/valkey-scale-lab/vpro1-bundles/` preserves the retired VPRO1 bundle
  authoring copies as read-only historical material.

Product goals and capability suite IDs originate in `project/milestones/` and
`project/verification/`. Budgets, capability approvals, write boundaries, and
termination policy originate here. The integration never writes controller
policy back into a project milestone.

Create an unsigned VPRO2 draft for operator review:

```bash
python3 controller/integrations/valkey-scale-lab/compile_contract.py \
  --milestone m1 \
  --output /tmp/valkey-m1.vpro2.draft.json
```

The operator must copy the selected project milestone, catalog, acceptance
tests, contract, evaluator code, receipt producer, toolchain policy, and
schemas into a snapshot outside worker write authority before binding a
trusted run. Capability receipts are generated afterward as run evidence for
the current product digest; they are not static acceptance-authority files.
Draft generation neither signs nor binds a run.

VPRO2 development starts at `vpro2/VPRO2_START.md`. The frozen VPRO1 framework
can still be verified independently with its existing launch instructions, but
its archived Valkey bundles are not the active control path.
