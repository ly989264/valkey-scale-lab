# valkey-scale-lab

`valkey-scale-lab` is a local-first Valkey 9.1.x experiment product. Its source,
tests, verification catalog, and delivery milestones are deliberately separate:

```text
src/valkey_scale_lab/   product library and CLI
tests/                  product behavior tests
verification/           capability-suite catalog and runner
milestones/             product goals and acceptance composition
```

Product code does not load tests, verification policy, or milestones. Tests use
product APIs directly. Milestones refer only to stable verification suite IDs;
the catalog owns their executable pytest paths and commands.

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

Validate the catalog and milestone composition without running real resources:

```bash
python3 verification/run.py catalog validate
python3 verification/run.py milestone validate --id m1
python3 verification/run.py milestone validate --id m2
python3 verification/run.py milestone validate --id m3
```

Run a capability suite by stable ID:

```bash
python3 verification/run.py suite --id scenario.contract
```

`PLANNED` suites return `BLOCKED`; required skips fail. Real suites require
operator-approved capabilities and explicit parameters. The machine-readable
milestone definitions and completion conditions are under `milestones/`.
