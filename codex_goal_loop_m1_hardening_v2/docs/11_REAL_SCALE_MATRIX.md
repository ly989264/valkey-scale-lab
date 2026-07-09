# 11_REAL_SCALE_MATRIX.md

## Exact-scale real evidence policy

The goal remains milestone1: local real Valkey up to 200 nodes. Do not run or require 500/1000/2000 real nodes in this loop.

Exact-scale means:

```text
30 nodes
50 nodes
100 nodes
200 nodes
```

When a capability is not meaningful at 30 nodes, the gate must record that as a structured non-required claim. It must not silently omit it.

## Resource handling

If an exact-scale run is too expensive for the current Codex environment, the worker must create a `BLOCKED_WITH_REASON` claim with:

- command attempted or preflight command;
- resource reason;
- expected artifact paths;
- exact missing fields;
- how to rerun manually.

Blocked is honest. False PASS is not.
