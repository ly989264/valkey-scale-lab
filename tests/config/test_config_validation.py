from __future__ import annotations

import json
from pathlib import Path

from valkey_scale_lab.config.validation import emit_schema_report, validate_config_file


def test_single_mac_template_validates(tmp_path: Path) -> None:
    out = tmp_path / "single_report.json"
    report = validate_config_file("templates/configs/single_mac_6node.yaml", out)
    assert report["valid"] is True
    assert report["status"] == "PASS"
    normalized = json.loads(Path(report["normalized_config_path"]).read_text(encoding="utf-8"))
    assert normalized["safety"]["default_max_nodes"] == 100
    assert normalized["runtime"]["valkey_image"].startswith("valkey/valkey:9.1.")


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
  azs: [az-a, az-b, az-c]
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


def test_rejects_bad_workload_ratio(tmp_path: Path) -> None:
    config = tmp_path / "bad_ratio.yaml"
    text = Path("templates/configs/local_az_3x2.yaml").read_text(encoding="utf-8")
    config.write_text(text.replace("write_ratio: 0.2", "write_ratio: 0.4"), encoding="utf-8")
    report = validate_config_file(config, tmp_path / "report.json")
    assert report["valid"] is False
    assert "WORKLOAD_RATIO_SUM" in {error["code"] for error in report["errors"]}


def test_emit_schema_report(tmp_path: Path) -> None:
    out = tmp_path / "schema_report.json"
    report = emit_schema_report(out)
    assert report["status"] == "PASS"
    assert report["defaults"]["default_max_nodes"] == 100
    assert any(item["name"] == "scale_1000_opt_in" for item in report["constraints"])
