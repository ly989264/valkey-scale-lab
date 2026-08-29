# M4 - the 1280-node target

M4 is one target and not a ladder: **256 primaries with four replicas each, 1280
valkey-servers**, on a fleet the operator supplies at any provider. The earlier
500 / 1000 / 2000 ladder is superseded.

Six Criteria, every one with Checks, so the definition is `READY`. Four of them
are provable without spending a run and are green on this branch: exact-scale
compilation and the named 1280-node exception, the placement of the target shape,
and the run's own report rendering.

Two of them are the run. `scale.exact.1280` and `scale.telemetry-and-transfer`
resolve to `real.ecs.full-flow-1280`, which carries `--operator-opt-in` and
`--cost-acknowledged` in its own argv, and `scale.fault-safety-and-cleanup`
resolves to reclaim proven on the operator's own fleet. **So `./gate milestone m4`
on a controller with a live fleet manifest spends money.** That is deliberate -
the milestone's acceptance *is* the run, and the alternative was a milestone no
command could ever accept - but it is stated here and in
`docs/fleet_operator_runbook.md` §11 so that nobody discovers it by typing it.

Until that run is taken, `READY` and `FAIL` are both correct at once: the
definition is complete, and the acceptance is unmet. `definition_status` is about
whether every Criterion has a Check, never about whether it passed.

`fleet_id: m4-fleet` in the cleanup Checks is the fleet id the runbook's
`make_fleet_manifest.py` example writes. A fleet built under another id needs the
same edit here that `host_inventory_path` needs in the configuration.

The whole procedure, from an empty cloud account to a readable report, is
`docs/fleet_operator_runbook.md`. It expects no help from anyone who has read this
repository.
