# Repository Entry Point

This repository has one active product root and one immutable historical
archive:

- `project/` is the runnable `valkey-scale-lab` product. Read
  `project/AGENTS.md` before changing product code.
- `loop_evidence/` contains historical AI controller evidence. Never edit or
  rewrite it during repository maintenance.

The AI controller is retired. Do not restore its packages, prompts, runtime
state, policy, or generated evidence under `project/`. Product-specific
executable checks may live with the product; controller frameworks and
controller-owned policy are not part of the active repository.
