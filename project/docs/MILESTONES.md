# Product Milestones

The normative milestone definitions are JSON documents outside the product
library:

| Milestone | Definition | Roadmap state (not Gate-evaluated) |
| --- | --- | --- |
| M1 local lifecycle | `milestones/m1/milestone.json` | `READY` |
| M2 native multi-ECS | `milestones/m2/milestone.json` | Planned |
| M3 multi-ECS scale-out | `milestones/m3/milestone.json` | Planned |

Each definition states one immutable final product goal, required atomic
success conditions, stable capability suite IDs, real evidence requirements,
and promotion prerequisites. Every success condition binds exactly one
verification suite or one real evidence requirement so the Controller can
derive a precise Goal State and Gap Graph. The matching README is the
human-readable explanation; JSON is authoritative.

Executable test paths and commands live in `verification/catalog.json`, not in
milestone files. The project-level `gate` command runs only executable Test and
Suite registrations. Product tests never read milestone documents.

Run executable verification with:

```bash
./gate test gate.contracts
./gate suite product.scenarios
./gate suite repository.all
```

Milestone execution and completion evaluation are intentionally not implemented
by Gate. A roadmap `READY` label is not a trusted completion verdict; real
completion requires operator-approved execution and independent evaluation of a
sealed snapshot.
