# Product Milestones

The normative product Milestones are JSON documents outside the product
library:

| Milestone | Definition | Definition status |
| --- | --- | --- |
| M1 local lifecycle | `milestones/m1/milestone.json` | `READY` |
| M2 native multi-ECS | `milestones/m2/milestone.json` | `DEFINED` |
| M3 multi-ECS scale-out | `milestones/m3/milestone.json` | `DEFINED` |

Each definition contains one goal and observable Criteria. A Criterion omits
`check` until its executable acceptance exists. Executable Tests and Suites
are defined once in the project-root `catalog.json`; Milestones only reference
their IDs and provide per-Test parameters.

The matching README explains intent, while `milestone.json` is authoritative.
Product library code and product tests do not load Milestones. Milestone and
Catalog contract coverage stays under `verification/tests/`.

Run executable verification with:

```bash
./gate test gate.contracts
./gate suite product.scenarios
./gate suite repository.all
./gate milestone m1
```

`DEFINED` and `READY` describe a definition and are never written back after a
run. A Milestone invocation reports `PASS`, `FAIL`, or `BLOCKED` in its Gate
summary. M1 can pass only when all product tests and both exact real 50-node
and 200-node runs pass. M2 and M3 cannot pass until every Criterion has an
attached executable Check.
