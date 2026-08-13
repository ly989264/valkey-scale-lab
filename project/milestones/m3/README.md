# M3 - Native Multi-ECS Lifecycle

M3 moves the lifecycle to directly managed Valkey processes on multiple ECS
hosts. All six Criteria carry executable Checks: inventory and placement
through `product.unit.native_backend` beside the original
`product.orchestrator` Suite, native bring-up through `real.ecs.bringup`, the
exact real 50- and 200-node runs and cross-host evidence through
`real.ecs.full-flow`, and ownership-safe cleanup through
`real.ecs.cleanup-ownership` in both release and abort modes.

The definition is therefore `READY`. The `real.ecs.*` Checks run against the
operator's fleet from the in-VPC controller and are not part of
`repository.all`.
