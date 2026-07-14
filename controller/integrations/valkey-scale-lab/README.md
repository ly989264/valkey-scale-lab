# Valkey Scale Lab Integration

This directory adapts product Milestones and their existing acceptance checks
to the minimal Controller. It does not add objectives, ordering, or reduced
completion rules.

Compile the immutable Milestone definition:

```bash
python3 controller/integrations/valkey-scale-lab/compile_contract.py \
  --milestone m1 \
  --output /tmp/valkey-m1.milestone.json
```

The result contains only the product goal, success conditions, real evidence
requirements, and Controller termination conditions. Worker path settings and
Evaluator wiring remain ordinary run configuration in `policy.json` and the
Controller constructor.

## Complete Evaluation

`full_evaluator.py` is the single callable/command used by Controller. On every
call it runs the selected verification suites, admits their structured results,
admits real evidence, and returns every condition and evidence result in the
minimal Controller format:

- `verification_admission.py` admits only current structured verification
  results with successful commands, no forbidden skips, and matching logs.
- `evidence_admission.py` admits real captures only when exact scale,
  provenance, freshness, product/run binding, lifecycle coverage, and cleanup
all match the Milestone.

Run the complete evaluator directly:

```bash
PYTHONPATH=controller/src python3 \
  controller/integrations/valkey-scale-lab/full_evaluator.py \
  --milestone /tmp/valkey-m1.milestone.json \
  --project-root project \
  --evidence-root /tmp/controller-run/evidence \
  --run-id m1-run
```

The command exits successfully when it produced a complete result, even when
some checks are `FAIL` or `MISSING`; those statuses are gaps for Planner.

The verification result files are acceptance evidence, not Controller
completion claims. Missing, stale, substituted, downscaled, malformed, or
unadmitted data must produce a non-`PASS` evidence result.

## Prerequisites

Later Milestones may consume a prior plain `SUCCESS` result plus its admitted
evidence. Prerequisite validation must recompute referenced content digests and
must not treat a summary string as proof. Historical evidence under
`loop_evidence/` remains read-only.
