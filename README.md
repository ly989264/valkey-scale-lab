# Valkey Scale Lab Repository

This repository contains one active product directory and one immutable
historical archive:

- [`project/`](project/README.md) contains the runnable package, harness,
  product tests, capability verification catalog, and product milestone definitions.
- `loop_evidence/` contains historical artifacts, audits, runs, and retired
  AI controller packages. It is retained for historical inspection only and
  must not be rewritten during repository maintenance.

Run product commands from `project/`. Product runtime output directories are
created on demand and are not links to historical controller evidence.

Product milestone definitions compose verification suite IDs, and verification
invokes product tests and APIs. Product code never imports the verification
runner, tests, milestones, or historical evidence.
