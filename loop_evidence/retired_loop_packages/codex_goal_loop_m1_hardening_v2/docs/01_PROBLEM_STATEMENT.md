# 01_PROBLEM_STATEMENT.md

## Observed failures to fix

The prior milestone1 loop produced useful framework work, but allowed a false completion state. The hardening loop exists to fix these concrete issues:

| Failure | Why it is unacceptable |
|---|---|
| `milestone1_status: PASS` while M1-format exact-scale evidence is incomplete | A milestone PASS must be backed by real M1-format artifacts, not a mixture of fixtures and legacy evidence. |
| Acceptance gate falls back to `tests/fixtures` | Fixtures can test parsers and renderers; they cannot prove real-scale execution. |
| Legacy evidence satisfies new stage claims | Old `valkey_e2e_evidence.json` can prove old real cluster execution only, not new setup telemetry, command audit, benchmark, timeline, or system-metric coverage. |
| Real setup telemetry has core metrics skipped | If setup cannot show meet/slots/replicate/probe timings, it cannot explain setup bottlenecks. |
| 200-node management command log remains empty | A management PASS without command traceability is not auditable. |
| Workload benchmark passes with one metric row | A benchmark must cover profiles, windows, and required metrics; one row is smoke-level evidence. |
| Fault timeline is fake/PARTIAL | Fault timeline claims need real timelines or an explicit blocked state. |
| Chinese report passes with weak inputs | Report generation is necessary but not sufficient; source evidence quality must be checked. |

## Hardening objective

After this loop, the repository must either:

- produce an honest `milestone1_status: PASS` with exact-scale M1-format evidence; or
- produce `milestone1_status: BLOCKED_WITH_REASON` with precise missing exact-scale claims.

False PASS must be impossible under the new gate scripts.
