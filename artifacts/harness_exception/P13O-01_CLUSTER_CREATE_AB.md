# Harness Exception: P13O-01_CLUSTER_CREATE_AB

## Defect

The initial P13O scaffold declared `P13O-01_CLUSTER_CREATE_AB`, but did not yet include phase-specific gates, artifact validation, or a schema for the required cluster-create strategy comparison artifact.

The protected runtime wrapper also exposed only the current P13 large-cluster primary creation path, which made it impossible to compare the current `valkey_cli_cluster_create_primaries` strategy against an explicitly selected `manual_tree_meet_parallel_slots` strategy without changing source.

## Patch Scope

This phase strengthens the post-loop harness and runtime evidence only:

- add `P13O-01_CLUSTER_CREATE_AB` gates to the P13O manifest;
- add schema and validator support for `p13_cluster_create_strategy_comparison.json`;
- keep the default P13 strategy as `valkey_cli_cluster_create_primaries`;
- add explicit opt-in support for `manual_tree_meet_parallel_slots` through `VSLAB_CLUSTER_CREATE_STRATEGY`;
- record primary cluster-create sub-timings for strategy comparison.

## Before Behavior

P13 large-process scale startup used the default `valkey-cli --cluster create` primary strategy, but the post-loop could not produce the required strategy comparison artifact or run a real Valkey proof for the manual strategy.

## After Behavior

The default P13 50/100 real gates remain on the current strategy and must still pass. A separate P13O real gate can run the manual strategy in the owned Docker/process sandbox. The comparison artifact records real observed timings and marks the default strategy explicitly, without using nodes.conf fast-bootstrap or weakening membership, role-count, data-path, or cleanup evidence.
