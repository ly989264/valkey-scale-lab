# VPRO Product Milestone Bundles

These are the source descriptions for the three product milestones in
`project/docs/MILESTONES.md`:

- `milestone1.bundle.json`: local lifecycle with required exact 50 and 200 gates;
- `milestone2.bundle.json`: native multi-ECS lifecycle with representative 50
  and 200 gates;
- `milestone3.bundle.json`: sequential exact 500, 1000, and 2000 promotion gates.

Validate an authoring copy with:

```text
VPRO_FRAMEWORK_ANCHOR=<anchor> python3 -I -S -B controller/vpro/VPRO_LAUNCH.py \
  --project-root project --bundle <bundle> milestone-validate
```

The repository copies are controller-policy authoring sources, not production
authority. Before
`bind`, an operator must copy the selected bundle outside the worker workspace
and protect it from worker writes. The external run must use that copied path.

The Valkey-specific executable adapter and evaluator remain under
`project/checks/vpro/` and `project/evaluators/vpro/`. They implement product
acceptance only; the generic controller kernel, schema, state machine, and
controller tests are all rooted under `controller/vpro/`.

`status: PASS` means the bundle is structurally and semantically valid.
`execution_readiness.status` is a static check of external acceptance/evaluator
paths and declared tools; dynamic resource readiness remains a gate preflight
responsibility. All three repository bundles are intentionally `BLOCKED` today.
Milestone 1 has a real product gate, but it still lacks a milestone-specific
evaluator, negative evaluator tests independent of worker-writable product
validators, and a sandbox-compatible authoritative network-proxy test. The
existing loopback test skips when socket creation is denied, so VPRO excludes it
from closure and blocks readiness until a no-skip replacement is externally
authored. Milestone 2 and Milestone 3
also lack native ECS implementation, external acceptance suites, authenticated
prerequisite verification, authoritative resource preflight, real gate commands,
and their milestone-specific evaluators. The adapter fails closed rather than
falling back to the shared structural policy or treating a plan, fixture,
product-reported PASS, or reduced scale as completion.

The acceptance adapter invokes a separately sealed `pytest` executable with
user site packages and plugin autoload disabled. It treats every skip as a
failure because an unexecuted required behavior is not evidence. Static
readiness therefore also remains `BLOCKED` until that operator-read-only tool is
available. The operator must provide it as a hermetic executable or protect its
shebang interpreter and imported package tree as part of the deployment
toolchain; VPRO v1 seals the declared executable, not an arbitrary interpreter's
transitive imports.

Each missing evaluator module must expose `self_check(milestone)` and
`evaluate(...)`. It must validate raw evidence and provenance without importing
a validator from `src/`, bind freshness to the current VPRO run and capture work,
and include the authenticated prerequisite receipt when one is required. Its
negative tests must prove rejection of partial, stale, fixture-derived,
relabeled, fabricated, wrong-product, and wrong-scale evidence.

The Milestone 2 and 3 preflight modules must expose `run(...)` and return an
exact-scale `vpro-distributed-preflight-v1` report with PASS results for quota,
capacity, ports, file descriptors, memory, CPU, network, storage, credentials,
ownership, and cost. They are authoritative operator modules, not wrappers that
accept a product CLI exit code.

Milestone 2 requires `milestones/prerequisites/milestone1-completion.json` and
the external `checks/vpro/milestone2_prerequisite.py` verifier; Milestone 3 uses
the corresponding Milestone 2 receipt and verifier. `verify(receipt=...)` must
authenticate the complete prior VPRO completion payload against an external
operator trust root, including run, framework, bundle, profile, product, gate,
evidence, and terminal admission digests. The Milestone 3 receipt must expose
the admitted 200-node baseline used by comparison checks. A receipt containing
only plausible fields and a 64-character string is not sufficient.

Each later scale rung consumes and validates the prior admission decision. Its
canonical decision digest, milestone, scale, and product digest must all match;
a copied or hand-edited PASS decision does not authorize promotion.
