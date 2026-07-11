# 07_MULTI_AGENT_PROTOCOL.md

## Real subagent artifacts

Each subagent must write a role artifact:

```text
runs/m1-hardening/<stage_id>/agents/design.md
runs/m1-hardening/<stage_id>/agents/worker.md
runs/m1-hardening/<stage_id>/agents/review.md
```

Each artifact must include:

```text
role: design|worker|review
agent_invocation: real_subagent
stage_id: Hxx
source_commit_before: <sha>
source_commit_after: <sha or MISSING>
```

The phrase `simulated` is forbidden in these role artifacts except inside a quoted violation example in this protocol file.

## Review agent authority

The review agent must inspect:

- diff;
- gate scripts;
- gate result artifacts;
- evidence manifest;
- stage-specific acceptance matrix;
- forbidden shortcut scan.

Review PASS is invalid unless all required hard gates pass or the stage is explicitly and correctly blocked.
