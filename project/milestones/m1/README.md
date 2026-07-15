# M1 - Complete Local Cluster Lifecycle

M1 proves the complete local Mac/Linux lifecycle. Its five hermetic Criterion
groups expand the 18 product domain Suites, covering every product pytest file
exactly once. Two additional Criteria reuse `real.local.full-flow` with
different parameters to require exact real Valkey runs at 50 and 200 nodes.

The definition is `READY`. `./gate milestone m1` is the complete acceptance
command; fake and fixture-based checks cannot substitute for either real run.
