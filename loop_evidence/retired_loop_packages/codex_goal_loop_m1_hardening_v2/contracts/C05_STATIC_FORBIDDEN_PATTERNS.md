# C05 Static forbidden patterns

The static shortcut gate must scan production hardening and acceptance scripts for patterns indicating weak gates.

Forbidden examples:

```text
if not matrix: matrix = _json(root / "tests/fixtures"
if not metrics: metrics = _jsonl(root / "tests/fixtures"
metric_count > 0
bool(metrics)
status in {"PASS", "SKIPPED_WITH_REASON"}
legacy evidence passed with Valkey 9.1
simulated design subagent
simulated worker subagent
simulated review subagent
```

The scanner must allow fixture references inside tests and fixture validation code, but not inside milestone PASS logic.
