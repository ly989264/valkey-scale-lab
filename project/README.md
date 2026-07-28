# valkey-scale-lab

`valkey-scale-lab` is a local-first Valkey 9.1.x experiment product. Its source,
tests, verification catalog, and delivery milestones are deliberately separate:

```text
src/valkey_scale_lab/   product library and CLI
tests/                  product behavior tests
catalog.json            the single executable Test/Suite catalog
verification/           generic Gate engine and contract tests
milestones/             product goals and acceptance composition
```

Product code does not load tests, verification policy, or milestones. Tests use
product APIs directly. The executable verification catalog is separate from
the milestone roadmap and owns every registered pytest path and command.

## Custom Valkey Image

Build the pinned Valkey 9.1.0 image before any real run:

```bash
./scripts/build_valkey_image.sh
```

The build verifies the upstream archive and repository patch, applies the
patch with zero fuzz, and produces
`valkey-scale-lab/valkey:9.1.0-myslots`. Real runtime preflight requires this
local image and never builds or falls back to the upstream image.

## Scalable Observation

`docs/scalable_cluster_observability_design.md` is the authoritative cluster
validation, Sentinel, Load Lane, failover, resource, and verdict contract.
Runtime adapters provide endpoints, actuation, and local resource access; they
must not add observation layers or verdict states beyond that document.

The current implementation covers cluster validation, Sentinel, Load Lane,
failover, and verdict handling. Deployment of one persistent local resource
sampler per nodehost/ECS is deferred to a separate change; the stability
verdict in this change does not claim resource-sampling coverage.

## Product Commands

Create a run and validate a configuration:

```bash
python3 -m valkey_scale_lab.cli run init --run-id local-run
python3 -m valkey_scale_lab.cli config validate \
  --config config/example.yaml \
  --out runs/local-run/artifacts/config_validation_report.json
```

Execute an exact-scale real scenario with explicit, product-neutral context:

```bash
python3 -m valkey_scale_lab.cli gate execute \
  --definition src/valkey_scale_lab/scenarios/definitions/local_full_flow_v1.json \
  --nodes 50 \
  --config templates/configs/scale_50.yaml \
  --run-id local-run \
  --ownership-id local-owner \
  --provenance-id local-provenance \
  --artifacts-dir runs/local-run/artifacts \
  --product-digest "$(python3 -c 'from valkey_scale_lab.gates.real import product_tree_digest; print(product_tree_digest())')"
```

Real execution preserves the exact requested scale, performs resource
preflight, and never turns a smaller run, dry run, or fixture into real
evidence. Large runs additionally require the explicit authorization flags
defined by the product safety policy.

Offline analysis and reporting consume validated artifacts:

```bash
python3 -m valkey_scale_lab.cli analyze \
  --input runs/local-run \
  --out runs/local-run/artifacts/analysis_summary.json
python3 -m valkey_scale_lab.cli report \
  --analysis runs/local-run/artifacts/analysis_summary.json \
  --out-dir runs/local-run/reports \
  --index-out runs/local-run/reports/report_index.json
```

## Verification

`gate` is the project-level entry point for executable checks. It loads the
flat registry in `catalog.json`, validates all parameters before
starting a process, runs the selected checks, and writes complete logs and a
summary under `artifacts/gate-runs/`.

Show the command contract and run one registered test:

```bash
./gate help
./gate test product.unit.cli_contract
```

Run a domain suite or the complete pytest registry:

```bash
./gate suite product.unit
./gate suite repository.all
```

Single-Test parameters come only from repeated `--param NAME=VALUE` arguments:

```bash
./gate test real.local.full-flow \
  --param nodes=50 \
  --param config=templates/configs/scale_50.yaml
```

Suite parameters come only from a JSON file grouped by Test ID:

```json
{
  "real.local.full-flow": {
    "nodes": 50,
    "config": "templates/configs/scale_50.yaml"
  }
}
```

```bash
./gate suite real.local.full-suite --params-file suite-params.json
```

Registered pytest skips fail closed. `repository.all` includes all product and
Gate pytest files but deliberately excludes the resource-consuming real run.

Milestones compose registered Tests and Suites into observable product
acceptance. Parameters for a parameterized Test live on its Milestone Check,
so one Test can be executed repeatedly with different values:

```bash
./gate milestone m1
```

M1 expands every product pytest Test once, then executes the real local full
flow at exactly 50 and 200 nodes. M2 defines local cluster-formation and
automatic-failover performance tuning and is `READY`; its real matrix Tests
still require explicit operator authorization. M3 defines the native
multi-ECS lifecycle and M4 defines multi-ECS scale-out; both remain `DEFINED`
and cannot report `PASS` while a Criterion has no Check.
