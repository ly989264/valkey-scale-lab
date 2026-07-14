# Controller Development Rules

`controller/` is the active Milestone controller. It targets one Codex Goal
session in one controlled development environment. Planner, Worker, Reviewer,
and Evaluator are logical responsibilities inside that session.

## Core Rules

- A Milestone contains only its goal, success conditions, evidence
  requirements, and termination conditions. It is immutable during a run.
- Every iteration begins with a complete independent evaluation and derives the
  current Goal State and every remaining gap from that evaluation.
- Planner receives the complete gaps, failed-path history, and remaining
  budget, then returns at most one finite objective.
- Worker writes are limited to configured project paths. Milestone,
  evaluators, acceptance rules, and Controller code are never writable paths.
- Record a Git checkpoint before Worker runs. Run the complete evaluator after
  Worker runs. Retain only a new verified pass with no regression; otherwise
  roll back and record the failed path.
- Only current evaluator results and real evidence can produce `SUCCESS`.
  Planner, Worker, Reviewer, and Codex prose are not completion evidence.
- Terminal states are `SUCCESS`, `STAGNATED`, `ENVIRONMENT_BLOCKED`,
  `NO_LEGAL_PLAN`, and `BUDGET_EXHAUSTED`.

## Development Rules

- Prefer deletion and direct sequential control flow over new protocol layers.
- Keep the package dependency-free and Milestone-neutral.
- Add focused hermetic `unittest` coverage for closed-loop behavior.
- Never weaken evaluator or evidence requirements to make a test pass.
- Never edit historical evidence under `../loop_evidence/`.
