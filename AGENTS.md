# Repository Entry Point

This repository has three deliberately separate authorities:

- `project/` is the runnable `valkey-scale-lab` product. Read
  `project/AGENTS.md` before changing product code.
- `controller/` is the active AI controller release and policy root. Read
  `controller/AGENTS.md` before working there and never reseal it from the
  product workspace.
- `loop_evidence/` contains historical controller evidence. Never edit or
  rewrite historical evidence during repository maintenance.

Do not restore controller packages, prompts, state, or generated controller
evidence under `project/`. Product-specific executable checks may live with the
product, but controller kernels and controller-owned policy must stay in
`controller/`.
