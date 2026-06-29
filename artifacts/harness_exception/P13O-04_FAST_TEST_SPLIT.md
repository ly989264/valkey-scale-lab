# Harness Exception: P13O-04_FAST_TEST_SPLIT

## Defect

The protected P13 harness currently runs `scale_tests` as the full unmarked command:

```bash
python3 -m pytest -q tests/unit tests/scale tests/integration
```

The latest P13 gate result recorded this fast preflight lane at 90.232059 seconds, which made the default P13 feedback loop include test cost that belongs in an explicit slow/perf lane. P13 real Valkey evidence already comes from `scripts/valkey_e2e_gate.py`, so keeping slow/perf tests in the default `scale_tests` gate is unnecessary and makes the phase gate harder to iterate safely.

## Patch

P13O-04 changes protected harness files only to preserve and strengthen requirements:

- define pytest `slow` and `perf` markers;
- mark waiting/probe coverage that can become timeout-sensitive as `slow`;
- change only the P13 `scale_tests` command to exclude `slow` and `perf` by default;
- keep slow/perf tests explicitly runnable through a P13O gate;
- add a machine-readable P13O-04 artifact and validation path.
- refresh the harness lock entry for `codex/phase_manifest.json` to the documented fast-lane command hash.

## Before / After

Before: P13 `scale_tests` mixed fast checks with any slow/perf checks under one unmarked command, and the historical P13 gate showed a 90.232059 second duration.

After: P13 `scale_tests` is a fast marker lane, slow/perf tests remain selectable with `-m 'slow or perf'`, and P13 correctness evidence remains in the real Docker/Valkey wrapper gates.
