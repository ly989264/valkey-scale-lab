# Milestone Definition Rules

This directory owns product Milestone definitions. A Milestone translates a
product goal into observable completion criteria before feature development
starts. Do not begin by writing tests against an ambiguous goal: first define
what an observer must be able to see when the goal is complete.

## Development Contract

- Define every required observable condition in `milestone.json` before
  implementing the feature.
- A Criterion may omit `check` while its executable acceptance is not yet
  developed. Do not add placeholder or non-executable Catalog entries.
- Implement product behavior and its tests together. When a Criterion becomes
  executable, register the Test once in `../catalog.json` and attach its Test
  or Suite ID to the Criterion immediately.
- Catalog registration and Milestone attachment are part of the feature's
  Definition of Done, not optional follow-up work.
- A Milestone may attach the same Test more than once with different
  parameters. Gate runs every occurrence independently and in definition
  order.

## Status Rules

- `DEFINED`: at least one Criterion has no `check` field.
- `READY`: every Criterion has one or more resolvable Checks with valid
  parameters, but no execution result has been established.
- `PASS`: a READY Milestone invocation completes every expanded Test with
  `PASS`.
- `FAIL`: at least one expanded Test produces an explicit failure. A known
  failure takes precedence over a blocked Test.
- `BLOCKED`: no Test has failed, but at least one Test cannot be evaluated
  because it is blocked, errors, or times out.

Milestone definitions are not rewritten after execution. `DEFINED` and
`READY` describe the definition; `PASS`, `FAIL`, and `BLOCKED` belong to a Gate
invocation and its artifacts.
