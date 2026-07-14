# Controller

This tree is the active AI controller release and owns operator policy. It is outside the
Valkey product workspace.

- `src/controller/` contains the milestone-neutral controller package.
- `CONTROLLER_LAUNCH.py` is the protected verify-before-import launcher.
- `integrations/valkey-scale-lab/` converts product milestone definitions into
  unsigned controller review drafts and supplies independent Valkey evaluators.

Product goals and capability suite IDs originate in `project/milestones/` and
`project/verification/`. Budgets, capability approvals, write boundaries, and
termination policy originate here. The integration never writes controller
policy back into a project milestone.

Create an unsigned controller draft for operator review:

```bash
python3 controller/integrations/valkey-scale-lab/compile_contract.py \
  --milestone m1 \
  --output /tmp/valkey-m1.controller.draft.json
```

The operator must copy the selected project milestone, catalog, acceptance
tests, contract, evaluator code, receipt producer, toolchain policy, and
schemas into a snapshot outside worker write authority before binding a
trusted run. Capability receipts are generated afterward as run evidence for
the current product digest; they are not static acceptance-authority files.
Draft generation neither signs nor binds a run.

Controller development starts at `CONTROLLER_START.md`. Retired controller
release directories are not part of the active tree; historical run evidence
remains under `../loop_evidence/` and must not be rewritten.
