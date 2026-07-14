# Product Milestones

The normative milestone definitions are JSON documents outside the product
library:

| Milestone | Definition | Current structural state |
| --- | --- | --- |
| M1 local lifecycle | `milestones/m1/milestone.json` | `READY` |
| M2 native multi-ECS | `milestones/m2/milestone.json` | `BLOCKED` on planned suites |
| M3 multi-ECS scale-out | `milestones/m3/milestone.json` | `BLOCKED` on planned suites |

Each definition states one immutable final product goal, required atomic
success conditions, stable capability suite IDs, real evidence requirements,
and promotion prerequisites. Every success condition binds exactly one
verification suite or one real evidence requirement so the Controller can
derive a precise Goal State and Gap Graph. The matching README is the
human-readable explanation; JSON is authoritative.

Executable test paths and commands live in `verification/catalog.json`, not in
milestone files. `verification/run.py` resolves suite IDs and fails closed for
unknown, skipped, or `PLANNED` suites. Product tests never read these milestone
documents.

Validate the composition with:

```bash
python3 verification/run.py catalog validate
python3 verification/run.py milestone validate --id m1
python3 verification/run.py milestone validate --id m2
python3 verification/run.py milestone validate --id m3
```

A structurally `READY` milestone is not a trusted completion verdict. Real
completion requires operator-approved execution and independent evaluation of a
sealed snapshot.
