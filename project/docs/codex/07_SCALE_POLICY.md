# 07_SCALE_POLICY.md — Scale Policy

## 1. Default ceiling

Automatic development and gate phases may run up to 100 Valkey nodes. They must never default to 1000 nodes.

```text
P00-P02: fake/planner/dry-run allowed
P03-P11: real Valkey small and medium gates
P12: real 10 and 30 node gates
P13: real 50 and 100 node gates
P14: optional 1000-node dry-run/resource-check only
```

## 2. Resource preflight

Before any real scale rung, the project must check:

- available memory;
- CPU count;
- disk free space;
- Docker availability;
- port range availability;
- configured Valkey memory limit;
- expected container count;
- cleanup state from previous runs.

A resource preflight failure is a phase failure for P12/P13. It must not be converted to PASS.

## 3. 1000-node policy

1000-node mode is opt-in. It must require both:

1. config field `scale_profile.opt_in_1000: true`; and
2. environment variable `VSLAB_ALLOW_1000_DRYRUN=I_UNDERSTAND_THIS_IS_NOT_A_DEFAULT_GATE`.

Default P14 behavior is dry-run/resource estimation. Real 1000-node execution must require a separate explicit command and must not be part of Codex's automatic loop.

