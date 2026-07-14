# Controller Start

## Preconditions

- Python 3.11 or newer and Git are available.
- The project is in a clean Git worktree.
- Worker write paths exclude the Milestone, evaluator, acceptance rules, and
  Controller code.
- The evaluator performs the complete Milestone acceptance and real-evidence
  checks from the current project version.

## Run

Construct `Controller` with the Milestone path, project root, allowed write
paths, evaluator callback, and optional plain status path. Call `run` with a
Planner callback and Worker callback.

Planner receives the complete Goal State, complete gap list, failed attempts,
and remaining iteration and wall-clock budget. It returns one `Objective` or
`None`. Worker receives that objective and the project root.

The Controller itself performs the review decisions:

1. Validate that the objective targets current gaps and allowed paths.
2. Record the current Git commit as the checkpoint.
3. Run Worker once.
4. Reject and roll back changes outside the objective.
5. Run the complete evaluator.
6. Commit only when a new condition or evidence requirement passes and no
   previous pass regresses or becomes blocked.
7. Otherwise roll back and add the objective to failed-path history.

Success is the current full evaluator result, not a role or model statement.
The other terminal outcomes are `STAGNATED`, `ENVIRONMENT_BLOCKED`,
`NO_LEGAL_PLAN`, and `BUDGET_EXHAUSTED`.
