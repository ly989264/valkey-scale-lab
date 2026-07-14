# Controller

This directory holds reusable control frameworks and project-specific control
policy. It is deliberately outside every product workspace.

- `vpro/` is the frozen, standalone and milestone-agnostic VPRO framework
  release. Its manifest, release receipt, historical package namespace, and
  relative layout are unchanged.
- `bundles/valkey-scale-lab/` contains repository authoring copies of the
  Valkey milestone bundles. An operator must copy a selected bundle and the
  VPRO release outside the worker workspace before a trusted run.
- `legacy/` preserves retired Goal/Meta controller sources and control
  material. It is archive material, not part of the product package.

The sealed `vpro/AGENTS.md` and `valkey_scale_lab` package marker are release
provenance and bootstrap ABI. They do not make the framework depend on the
Valkey product; product semantics enter only through an external bundle and an
explicit `--project-root`.

Validate the extracted framework from the repository root:

```bash
VPRO_FRAMEWORK_ANCHOR="$PWD/controller/vpro/codex/vpro/framework_release.json" \
  python3 -I -S -B controller/vpro/VPRO_LAUNCH.py framework-verify
```

Validate a Valkey bundle against the product tree:

```bash
VPRO_FRAMEWORK_ANCHOR="$PWD/controller/vpro/codex/vpro/framework_release.json" \
  python3 -I -S -B controller/vpro/VPRO_LAUNCH.py \
  --project-root "$PWD/project" \
  --bundle "$PWD/controller/bundles/valkey-scale-lab/milestone1.bundle.json" \
  milestone-validate
```

The repository release receipt is suitable for development verification only;
it is not a production trust root.
