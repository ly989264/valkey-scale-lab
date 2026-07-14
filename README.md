# Valkey Scale Lab Repository

This repository is intentionally divided into three primary directories:

- [`project/`](project/README.md) contains the runnable package, harness,
  product tests, capability verification catalog, and product milestone definitions.
- [`controller/`](controller/README.md) contains the standalone AI control
  frameworks, the VPRO2 Valkey integration, operator policy, and archived VPRO1 material.
- `loop_evidence/` contains historical artifacts, audits, runs, and retired
  goal-loop packages.

Run product commands from `project/`. Product runtime output directories are
created on demand and are not links to historical controller evidence.

The dependency direction is one way: product milestone definitions compose
verification suite IDs; verification invokes product tests and APIs; VPRO2 may
consume sealed copies of those definitions. Product code never imports the
controller, verification runner, tests, or milestones.
