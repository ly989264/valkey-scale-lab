from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.config.validation import emit_schema_report, validate_config_file
from valkey_scale_lab.execution import (
    ExecutionSelectionError,
    backend_for_provider,
    backends_for_provider,
)


def test_single_mac_template_validates(tmp_path: Path) -> None:
    out = tmp_path / "single_report.json"
    report = validate_config_file("templates/configs/single_mac_6node.yaml", out)
    assert report["valid"] is True
    assert report["status"] == "PASS"
    normalized = json.loads(Path(report["normalized_config_path"]).read_text(encoding="utf-8"))
    assert normalized["safety"]["default_max_nodes"] == 100
    assert normalized["runtime"]["valkey_image"] == "valkey-scale-lab/valkey:9.1.0-myslots"


def test_multi_az_template_validates(tmp_path: Path) -> None:
    out = tmp_path / "multi_report.json"
    report = validate_config_file("templates/configs/local_az_3x2.yaml", out)
    assert report["valid"] is True
    assert report["total_nodes"] == 6


def test_rejects_default_over_100_nodes(tmp_path: Path) -> None:
    config = tmp_path / "bad.yaml"
    config.write_text(
        """
schema_version: v1
profile_name: bad_scale
safety:
  default_max_nodes: 100
  allow_1000_nodes: false
  require_sandbox_network: true
  forbid_host_network_mutation: true
  cleanup_on_error: true
runtime:
  provider: docker
  valkey_image: valkey/valkey:9.1.0
  sandbox_mode: container_namespace
hosts:
  - host_id: local
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [controller]
network:
  virtual_az_mode: multi
  azs: [az-a, az-b]
cluster:
  shards: 51
  replicas_per_shard: 1
  port_base: 7000
  cluster_bus_port_base: 17000
workload:
  enabled: false
faults: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert {error["code"] for error in report["errors"]} == {"NODE_CAP_EXCEEDED"}


def test_rejects_1000_without_dry_run_opt_in(tmp_path: Path) -> None:
    config = tmp_path / "bad_1000.yaml"
    config.write_text(
        """
schema_version: v1
profile_name: bad_1000
safety:
  default_max_nodes: 100
  allow_1000_nodes: true
  require_1000_env: VSLAB_ALLOW_1000_DRYRUN
  require_sandbox_network: true
  forbid_host_network_mutation: true
  cleanup_on_error: true
runtime:
  provider: docker
  valkey_image: valkey/valkey:9.1.0
  sandbox_mode: container_namespace
  dry_run: false
hosts:
  - host_id: local
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [controller]
network:
  virtual_az_mode: multi
  azs: [az-a, az-b]
cluster:
  shards: 500
  replicas_per_shard: 1
  port_base: 9000
  cluster_bus_port_base: 19000
scale_profile:
  opt_in_1000: true
  dry_run_only: true
workload:
  enabled: false
faults: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert "MISSING_1000_DRY_RUN" in {error["code"] for error in report["errors"]}


def test_1000_dry_run_template_validates(tmp_path: Path) -> None:
    report = validate_config_file("templates/configs/scale_1000_dryrun_optin.yaml", tmp_path / "report.json")
    assert report["valid"] is True
    assert report["total_nodes"] == 1000


def test_exact_2000_local_full_flow_template_validates_as_controlled_profile(
    tmp_path: Path,
) -> None:
    report = validate_config_file(
        "templates/configs/scale_2000_local_full_flow_optin.yaml",
        tmp_path / "report.json",
    )

    assert report["valid"] is True
    assert report["total_nodes"] == 2000
    normalized = json.loads(
        Path(report["normalized_config_path"]).read_text(encoding="utf-8")
    )
    assert normalized["runtime"]["dry_run"] is False
    assert normalized["workload"]["enabled"] is True
    assert normalized["scale_profile"]["exact_2000_local_full_flow_opt_in"] is True


def test_scale_projection_200_plus_profile_validates(tmp_path: Path) -> None:
    config = tmp_path / "scale_250_scale_projection.yaml"
    config.write_text(
        """
schema_version: v1
profile_name: scale_250_scale_projection
safety:
  default_max_nodes: 100
  allow_1000_nodes: false
  require_sandbox_network: true
  forbid_host_network_mutation: true
  cleanup_on_error: true
runtime:
  provider: docker
  valkey_image: valkey/valkey:9.1.0
  sandbox_mode: container_namespace
  dry_run: true
hosts:
  - host_id: local
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [controller]
network:
  virtual_az_mode: multi
  azs: [az-a, az-b]
cluster:
  shards: 250
  replicas_per_shard: 0
  port_base: 12000
  cluster_bus_port_base: 22000
  node_memory_limit_mb: 32
scale_profile:
  dry_run_only: true
  scale_projection_target: true
  target_nodes: 250
  execution_mode: dry_run
workload:
  enabled: false
faults: []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = validate_config_file(config, tmp_path / "report.json")

    assert report["valid"] is True
    assert report["total_nodes"] == 250


def test_rejects_real_execution_above_200(tmp_path: Path) -> None:
    config = tmp_path / "scale_250_real.yaml"
    config.write_text(
        """
schema_version: v1
profile_name: scale_250_real
safety:
  default_max_nodes: 100
  allow_1000_nodes: false
  require_sandbox_network: true
  forbid_host_network_mutation: true
  cleanup_on_error: true
runtime:
  provider: docker
  valkey_image: valkey/valkey:9.1.0
  sandbox_mode: container_namespace
  dry_run: false
hosts:
  - host_id: local
    os: auto
    arch: auto
    ip: 127.0.0.1
    docker_endpoint: local
    memory_gb: auto
    disk_gb: auto
    labels: [controller]
network:
  virtual_az_mode: multi
  azs: [az-a, az-b]
cluster:
  shards: 250
  replicas_per_shard: 0
  port_base: 12000
  cluster_bus_port_base: 22000
  node_memory_limit_mb: 32
scale_profile:
  dry_run_only: true
  scale_projection_target: true
  target_nodes: 250
  execution_mode: dry_run
workload:
  enabled: false
faults: []
""".strip()
        + "\n",
        encoding="utf-8",
    )

    report = validate_config_file(config, tmp_path / "report.json")

    codes = {error["code"] for error in report["errors"]}
    assert report["valid"] is False
    assert "REAL_EXECUTION_ABOVE_200_FORBIDDEN" in codes
    assert "MISSING_200_PLUS_DRY_RUN_PROFILE" in codes


def test_rejects_three_virtual_az_multi_mode(tmp_path: Path) -> None:
    config = tmp_path / "three_az.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("azs: [az-a, az-b]", "azs: [az-a, az-b, az-c]"), encoding="utf-8")
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert "MULTI_AZ_COUNT" in {error["code"] for error in report["errors"]}


def test_rejects_bad_workload_ratio(tmp_path: Path) -> None:
    config = tmp_path / "bad_ratio.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("write_ratio: 0.2", "write_ratio: 0.4"), encoding="utf-8")
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert "WORKLOAD_RATIO_SUM" in {error["code"] for error in report["errors"]}


def test_rejects_host_network_mutation_and_unsafe_sandbox_mode(tmp_path: Path) -> None:
    config = tmp_path / "unsafe_network.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    text = text.replace("forbid_host_network_mutation: true", "forbid_host_network_mutation: false")
    text = text.replace("sandbox_mode: container_namespace", "sandbox_mode: host_network")
    config.write_text(text, encoding="utf-8")
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert {"HOST_NETWORK_FORBIDDEN", "SANDBOX_MODE"} <= {error["code"] for error in report["errors"]}


def test_rejects_port_base_collision(tmp_path: Path) -> None:
    config = tmp_path / "port_collision.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    text = text.replace("cluster_bus_port_base: 17100", "cluster_bus_port_base: 7100")
    config.write_text(text, encoding="utf-8")
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert "PORT_BASE_COLLISION" in {error["code"] for error in report["errors"]}


def test_rejects_invalid_fault_definition(tmp_path: Path) -> None:
    config = tmp_path / "bad_fault.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    text = text.replace("type: network_delay", "type: host_route_change")
    text = text.replace("target_scope: virtual_az", "target_scope: host")
    text = text.replace("duration_seconds: 10", "duration_seconds: 0")
    config.write_text(text, encoding="utf-8")
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert {"FAULT_TYPE", "FAULT_TARGET_SCOPE", "FAULT_DURATION"} <= {error["code"] for error in report["errors"]}


def test_failover_timeline_observer_global_defaults_are_reported(tmp_path: Path) -> None:
    report = validate_config_file("templates/configs/scale_10.yaml", tmp_path / "report.json")

    observer = report["failover_timeline_observer"]
    assert report["valid"] is True
    assert observer["enabled"] is True
    assert observer["probe_interval_ms"] == 250
    assert observer["client_probe_interval_ms"] == 250
    assert observer["probe_timeout_ms"] == 1000
    assert observer["max_observer_endpoints"] == 32


def test_rejects_invalid_failover_timeline_observer_config(tmp_path: Path) -> None:
    config = tmp_path / "bad_observer.yaml"
    text = Path("templates/configs/scale_10.yaml").read_text(encoding="utf-8")
    text += "\nobservability:\n  failover_timeline_observer:\n    enabled: yes\n    probe_interval_ms: 1\n"
    config.write_text(text, encoding="utf-8")

    report = validate_config_file(config, tmp_path / "report.json")

    assert report["valid"] is False
    codes = {error["code"] for error in report["errors"]}
    assert "FAILOVER_TIMELINE_OBSERVER_RANGE" in codes


def test_emit_schema_report(tmp_path: Path) -> None:
    out = tmp_path / "schema_report.json"
    report = emit_schema_report(out)
    assert report["status"] == "PASS"
    assert report["defaults"]["default_max_nodes"] == 100
    assert any(item["name"] == "scale_1000_opt_in" for item in report["constraints"])
    assert any(item["name"] == "two_virtual_azs" for item in report["constraints"])


def test_a_native_configuration_validates(tmp_path: Path) -> None:
    """The schema and the hand-written checks must agree about `ecs`.

    Roadmap item 1.2 admitted `runtime.provider: ecs` in `validation.py` and
    left `run_config.schema.json` pinned to `["docker"]`. The schema runs
    first, so every native configuration failed `SCHEMA_VALIDATION` before any
    of item 1.2's rules were reached - the two halves of the contract
    disagreed, in the same shape as the defect item 1.2 itself found between
    `validation.py` and `execution.BACKENDS`.
    """
    report = validate_config_file("templates/configs/native_50.yaml", tmp_path / "native.json")

    assert report["valid"] is True
    assert report["status"] == "PASS"
    normalized = json.loads(Path(report["normalized_config_path"]).read_text(encoding="utf-8"))
    assert normalized["runtime"]["provider"] == "ecs"
    assert normalized["runtime"]["host_inventory_path"]
    assert normalized["runtime"]["native_bundle_dir"]


def test_a_native_configuration_naming_no_fleet_is_refused(tmp_path: Path) -> None:
    """Widened, not loosened: `ecs` carries two requirements of its own."""
    config = tmp_path / "no_fleet.yaml"
    text = Path("templates/configs/native_50.yaml").read_text(encoding="utf-8")
    for key in ("host_inventory_path", "native_bundle_dir"):
        text = "\n".join(line for line in text.splitlines() if f"  {key}:" not in line)
    config.write_text(text + "\n", encoding="utf-8")

    report = validate_config_file(config, tmp_path / "report.json")

    assert report["valid"] is False
    codes = {error["code"] for error in report["errors"]}
    assert {"NATIVE_RUNTIME_INVENTORY", "NATIVE_RUNTIME_BUNDLE"} <= codes


def test_an_unknown_provider_is_still_refused(tmp_path: Path) -> None:
    config = tmp_path / "bad_provider.yaml"
    text = Path("templates/configs/native_50.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("provider: ecs", "provider: nomad"), encoding="utf-8")

    report = validate_config_file(config, tmp_path / "report.json")

    assert report["valid"] is False


def test_the_configuration_chooses_the_backend(tmp_path: Path) -> None:
    """A configuration's provider decides the backend, and nothing else does.

    Roadmap item 1.2 registered `native_multi_ecs` and admitted
    `runtime.provider: ecs`, but nothing joined the two: `backend_id` came from
    a CLI default of `docker_process`. Measured on the first native exact-30
    attempt - the placement read the fleet manifest and wrote `host_id:
    sim-host-00` onto four nodehosts, and the run then started four Docker
    containers for them. A run that reports a fleet it never touched is worse
    than one that refuses.
    """
    assert backend_for_provider("ecs") == "native_multi_ecs"
    assert backend_for_provider("docker") == "docker_process"
    # `docker` is implemented by two backends, so the provider narrows the
    # choice rather than making it, and naming one of them still works.
    assert set(backends_for_provider("docker")) == {"docker_container", "docker_process"}
    assert backend_for_provider("docker", requested="docker_container") == "docker_container"


def test_a_backend_that_contradicts_the_configuration_is_refused() -> None:
    """Refused in both directions: silently winning either way is the defect."""
    with pytest.raises(ExecutionSelectionError, match="does not implement"):
        backend_for_provider("ecs", requested="docker_process")
    with pytest.raises(ExecutionSelectionError, match="does not implement"):
        backend_for_provider("docker", requested="native_multi_ecs")


def test_an_unimplemented_provider_names_the_ones_that_exist() -> None:
    with pytest.raises(ExecutionSelectionError, match="no registered backend"):
        backend_for_provider("nomad")


def _codes(report: dict) -> list[str]:
    return [error["code"] for error in report.get("errors", [])]


def test_replica_count_is_bounded_at_one_to_four(tmp_path: Path) -> None:
    """The operator's standing assumption, enforced where every other cap is.

    Four is unconditional: nothing above it has been designed for, and every
    constant this product pins was measured at one replica. Below one is refused
    only for real execution, because today's replica-free configs are dry-run
    scale projections and single-AZ `non_ha_allowed` plans, and both keep
    working.
    """

    base = Path("templates/configs/scale_50.yaml").read_text(encoding="utf-8")

    for replicas, expected in [(1, []), (2, []), (4, []), (5, ["REPLICAS_PER_SHARD_ABOVE_MAX"])]:
        config = tmp_path / f"replicas_{replicas}.yaml"
        config.write_text(
            base.replace("shards: 25", "shards: 10").replace(
                "replicas_per_shard: 1", f"replicas_per_shard: {replicas}"
            ),
            encoding="utf-8",
        )
        report = validate_config_file(config, tmp_path / f"report_{replicas}.json")
        assert _codes(report) == expected, (replicas, _codes(report))

    # Real execution with no replica at all is refused, and the message says
    # which two shapes are still admitted.
    config = tmp_path / "replicas_0_real.yaml"
    config.write_text(
        base.replace("shards: 25", "shards: 10").replace("replicas_per_shard: 1", "replicas_per_shard: 0"),
        encoding="utf-8",
    )
    report = validate_config_file(config, tmp_path / "report_0_real.json")
    assert "REPLICAS_PER_SHARD_BELOW_MIN" in _codes(report)


def test_the_two_replica_free_shapes_that_already_ship_are_untouched(tmp_path: Path) -> None:
    """A dry-run projection and a single-AZ non-HA plan both keep validating."""

    projection = tmp_path / "projection.yaml"
    projection.write_text(
        Path("templates/configs/scale_1000_dryrun_optin.yaml")
        .read_text(encoding="utf-8")
        .replace("shards: 500", "shards: 1000")
        .replace("replicas_per_shard: 1", "replicas_per_shard: 0"),
        encoding="utf-8",
    )
    report = validate_config_file(projection, tmp_path / "projection.json")
    assert "REPLICAS_PER_SHARD_BELOW_MIN" not in _codes(report)

    single = tmp_path / "single_non_ha.yaml"
    text = Path("templates/configs/single_mac_6node.yaml").read_text(encoding="utf-8")
    single.write_text(
        text.replace("  node_memory_limit_mb: 128", "  node_memory_limit_mb: 128\n  non_ha_allowed: true")
        .replace("replicas_per_shard: 1", "replicas_per_shard: 0"),
        encoding="utf-8",
    )
    report = validate_config_file(single, tmp_path / "single.json")
    assert "REPLICAS_PER_SHARD_BELOW_MIN" not in _codes(report)



#: Every clause of `is_exact_1280_native_ecs_profile`, as an edit to the
#: canonical template that must put the configuration back outside the
#: exception. `cluster.shards` is here too: the node count is a clause.
EXACT_1280_CLAUSES: list[tuple[str, str, object]] = [
    ("", "profile_name", "scale_1280_native_ecs_renamed"),
    ("runtime", "provider", "docker"),
    ("runtime", "sandbox_mode", "host_namespace"),
    ("runtime", "dry_run", True),
    ("workload", "enabled", False),
    ("scale_profile", "exact_1280_native_ecs_opt_in", False),
    ("scale_profile", "target_nodes", 1279),
    ("scale_profile", "execution_mode", "operator_opt_out"),
    ("safety", "default_max_nodes", 200),
    ("safety", "allow_1000_nodes", True),
    ("safety", "require_sandbox_network", False),
    ("safety", "forbid_host_network_mutation", False),
    ("cluster", "shards", 255),
]


def _exact_1280_config() -> dict:
    """The normalized canonical template.

    The clause tests mutate this dict and call `validate_semantics` directly
    rather than writing a file and parsing it back. The first version of them
    round-tripped through JSON, which `simple_yaml` refuses - so every
    configuration was duly rejected, with `CONFIG_PARSE_ERROR`, and the tests
    passed while proving nothing about the guard.
    """

    from valkey_scale_lab.config.validation import load_effective_config

    return load_effective_config("templates/configs/scale_1280_native_ecs_optin.yaml")


def test_exact_1280_native_ecs_template_validates_as_a_named_exception(
    tmp_path: Path,
) -> None:
    """M4's target shape is admitted, and only through its own name.

    1280 crosses 1000, so this configuration collects **eight** validation
    errors without the exception - three of them from the `total_nodes >= 1000`
    block rather than the above-200 rules, which is the part easily missed when
    reasoning from the ladder. See
    `docs/real_execution_above_200_exception_memo.md` §1.
    """

    report = validate_config_file(
        "templates/configs/scale_1280_native_ecs_optin.yaml",
        tmp_path / "report.json",
    )

    assert report["valid"] is True, report["errors"]
    assert report["total_nodes"] == 1280
    normalized = json.loads(
        Path(report["normalized_config_path"]).read_text(encoding="utf-8")
    )
    assert normalized["runtime"]["provider"] == "ecs"
    assert normalized["runtime"]["dry_run"] is False
    assert normalized["workload"]["enabled"] is True
    assert normalized["safety"]["default_max_nodes"] == 100
    # The 1000-node opt-in is a dry-run mechanism and this must not be
    # reachable through it.
    assert normalized["safety"]["allow_1000_nodes"] is False
    assert normalized["scale_profile"]["exact_1280_native_ecs_opt_in"] is True


@pytest.mark.parametrize("section,key,value", EXACT_1280_CLAUSES)
def test_breaking_any_clause_of_the_1280_exception_refuses_the_run(
    section: str, key: str, value: object
) -> None:
    """A bounded exception is only as good as its narrowness, so each clause is
    broken on its own and the configuration must be refused.

    Every one of these edits leaves a configuration that is still about 1280
    real nodes on a fleet, and every one must be refused - otherwise the
    exception is a raised cap wearing a name.
    """

    from copy import deepcopy

    from valkey_scale_lab.config.validation import validate_semantics

    config = deepcopy(_exact_1280_config())
    assert validate_semantics(config) == [], "the unbroken template must validate"
    if section:
        config[section][key] = value
    else:
        config[key] = value

    codes = {error.get("code") for error in validate_semantics(config)}

    assert codes, f"{section}.{key}={value!r} was admitted"
    # Whatever else it says, it must still refuse a real run above 200 nodes -
    # unless the edit made the run a dry run, which is the one clause whose own
    # removal takes it off that path.
    if not (section == "runtime" and key == "dry_run"):
        assert "REAL_EXECUTION_ABOVE_200_FORBIDDEN" in codes, codes


def test_the_1280_exception_does_not_admit_a_neighbouring_node_count() -> None:
    """It names a node count, not a range. Moving `scale_profile.target_nodes`
    with the shard count is not enough - the predicate reads both."""

    from copy import deepcopy

    from valkey_scale_lab.config.validation import validate_semantics

    config = deepcopy(_exact_1280_config())
    config["cluster"]["shards"] = 257
    config["scale_profile"]["target_nodes"] = 1285

    codes = {error.get("code") for error in validate_semantics(config)}

    assert "REAL_EXECUTION_ABOVE_200_FORBIDDEN" in codes, codes


def test_the_two_named_real_exceptions_cannot_serve_each_others_environment() -> None:
    """exact-2000 is `docker`, exact-1280 is `ecs`, and neither widens the other.

    Checked in both directions, because a disjunction is exactly where two
    guards can quietly become one.
    """

    from copy import deepcopy

    from valkey_scale_lab.config.validation import (
        is_exact_1280_native_ecs_profile,
        is_exact_2000_local_full_flow_profile,
        load_effective_config,
        validate_semantics,
    )

    one_two_eighty = _exact_1280_config()
    two_thousand = load_effective_config(
        "templates/configs/scale_2000_local_full_flow_optin.yaml"
    )
    assert is_exact_1280_native_ecs_profile(one_two_eighty) is True
    assert is_exact_2000_local_full_flow_profile(one_two_eighty) is False
    assert is_exact_2000_local_full_flow_profile(two_thousand) is True
    assert is_exact_1280_native_ecs_profile(two_thousand) is False

    # 1280 nodes wearing exact-2000's name and provider is refused, and so is
    # 2000 nodes wearing this one's.
    borrowed = deepcopy(one_two_eighty)
    borrowed["profile_name"] = "scale_2000_local_full_flow_optin"
    borrowed["runtime"]["provider"] = "docker"
    assert validate_semantics(borrowed) != []

    borrowed = deepcopy(two_thousand)
    borrowed["profile_name"] = "scale_1280_native_ecs_optin"
    assert validate_semantics(borrowed) != []
