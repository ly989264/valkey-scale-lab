from __future__ import annotations

from valkey_scale_lab.runtime import docker_runtime


def test_size_to_bytes_parses_docker_units() -> None:
    assert docker_runtime._size_to_bytes("1kB") == 1000
    assert docker_runtime._size_to_bytes("1MiB") == 1024 * 1024
    assert docker_runtime._size_to_bytes("2.5MB") == 2_500_000


def test_system_metric_windows_follow_available_artifacts(tmp_path) -> None:
    (tmp_path / "management_ops_matrix.json").write_text("{}", encoding="utf-8")
    (tmp_path / "workload_windows.json").write_text("{}", encoding="utf-8")
    (tmp_path / "fault_timeline_report.json").write_text("{}", encoding="utf-8")
    assert docker_runtime._system_metric_windows_for_artifacts(tmp_path) == [
        "setup",
        "cleanup",
        "management",
        "workload",
        "fault",
    ]
