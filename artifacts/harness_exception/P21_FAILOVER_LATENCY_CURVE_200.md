# Harness Exception - P21_FAILOVER_LATENCY_CURVE_200

## Defect

P21 is declared as an automatic real Valkey gate in `codex/phase_manifest.json`, but the locked harness did not yet provide the strict 200-node config, P21 runtime admission, P21 resource preflight exception, P21 controller behavior, or strong P21 artifact assertions needed to execute the stage safely.

## Patch

This stage intentionally changes locked harness scripts and templates only to strengthen P21:

- add `templates/configs/scale_200.yaml` as the explicit 200-node config;
- teach `scripts/safety_scan.py` the same exact `scale_200.yaml`/P21 bounded exception while preserving the normal `>100` rejection for all other default configs;
- keep the normal 100-node default cap while allowing only the bounded P21 exact-200 resource preflight and runtime sample scenarios;
- make the P21 controller run `resource_preflight_200` first, block without fake PASS artifacts on failure, and run exactly three real 200-node samples on success;
- require cleanup, unique run/state references, real Valkey evidence, exact sample counts, timestamp arithmetic, and a valid combined 30/50/100/200 curve;
- extend focused unit/integration assertions so downshifted, fake, duplicate, missing-cleanup, or malformed P21 artifacts fail.

## Before / After

Before: P21 referenced a missing config and had no complete controller/runtime path, so it could not produce or strongly verify 200-node evidence.

After: P21 either blocks on strict resource preflight with `BLOCKED.md`, or produces only real 200-node evidence from exactly three samples and validates the resulting artifacts.
