# Safety Boundary

This Controller assumes one trusted Codex Goal session in one controlled Git
workspace. Its safety boundary is deliberately small:

- Worker can change only the configured project paths for the current
  objective.
- Milestone, evaluators, acceptance rules, and Controller code are outside
  those paths.
- The worktree is clean before each objective and the current commit is the Git
  checkpoint.
- Out-of-scope, ineffective, blocked, or regressing changes are rolled back.
- Complete evaluator results are required before and after retained work.
- Required real evidence remains fail-closed.

The Controller is not a multi-principal security system. Do not add identity,
authorization, signing, storage, deployment, or isolation protocols to it.
