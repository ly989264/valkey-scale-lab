#!/usr/bin/env python3
"""Fail-closed admission for M2 paired, real-Valkey performance evidence.

This command does not implement an optimization and does not accept fixtures or
retained captures.  A real capture producer must write
``m2_performance_report.json`` and all of its referenced sources inside the
current Gate test artifact directory.  This command verifies that closed bundle
and emits only the Gate command+json result at ``--result-path``.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shlex
import sys
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from valkey_scale_lab.metrics import nearest_rank
from valkey_scale_lab.metrics.m2_resource import (
    validate_and_aggregate_m2_resource_samples,
)

try:
    from schema_validator import load_json, validate
except ModuleNotFoundError:  # Imported as scripts.m2_performance_gate in tests.
    from scripts.schema_validator import load_json, validate

try:
    from m2_performance_capture import capture_current_invocation
except ModuleNotFoundError:  # Imported as scripts.m2_performance_gate in tests.
    from scripts.m2_performance_capture import capture_current_invocation


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "artifact" / "m2_performance_report.schema.json"
CLEANUP_SCHEMA_PATH = ROOT / "schemas" / "artifact" / "cleanup_report.schema.json"
SETUP_TIMELINE_SCHEMA_PATH = ROOT / "schemas" / "artifact" / "setup_timeline.schema.json"
RESOURCE_PREFLIGHT_SCHEMA_PATH = ROOT / "schemas" / "artifact" / "resource_preflight.schema.json"
REPORT_NAME = "m2_performance_report.json"
AUTHORIZATION_ENV = "VSLAB_M2_REAL_AUTHORIZATION"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VALKEY_91_RE = re.compile(r"^9\.1\.")
DOCKER_CONTAINER_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", re.ASCII)
LATENCY_HISTOGRAM_SCHEMA_VERSION = "m2-relative-latency-histogram-v1"
LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE = 100
LATENCY_HISTOGRAM_MIN_POSITIVE_MS = 0.000001
LATENCY_HISTOGRAM_MAX_MS = 10_000.0
LATENCY_HISTOGRAM_BUCKET_LIMIT = 4_096
LATENCY_HISTOGRAM_MIN_TICK = math.floor(
    math.log2(LATENCY_HISTOGRAM_MIN_POSITIVE_MS)
    * LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE
)
LATENCY_HISTOGRAM_MAX_TICK = math.ceil(
    math.log2(LATENCY_HISTOGRAM_MAX_MS)
    * LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE
)
LATENCY_HISTOGRAM_MAX_INDEX = (
    LATENCY_HISTOGRAM_MAX_TICK - LATENCY_HISTOGRAM_MIN_TICK
)

BASELINE_FORMATION = {
    "kind": "cluster_create_strategy",
    "value": "valkey_cli_cluster_create_primaries",
}
BASELINE_FAILOVER = {"kind": "cluster_node_timeout_ms", "value": 30000}
DIRECT_FAILOVER_FULL_VALIDATION_TIMEOUT_MS = 20000
FAILURE_RATES = ("one", "10_percent", "33_percent")
CONTROL_DIGEST_KEYS = {
    "valkey_binary",
    "product",
    "configuration_except_treatment",
    "topology",
    "placement",
    "host",
    "workload",
    "resource_preflight",
}
PROVENANCE_CONTROL_FIELDS = {
    "valkey_binary_digest": "valkey_binary",
    "product_digest": "product",
    "configuration_digest": "configuration_except_treatment",
    "topology_digest": "topology",
    "placement_digest": "placement",
    "environment_digest": "host",
    "workload_digest": "workload",
    "resource_preflight_digest": "resource_preflight",
}
COMMON_SOURCE_CATEGORIES = {
    "attempt",
    "state",
    "cleanup",
    "provenance",
    "timeline",
    "command_log",
    "resource",
    "workload",
    "topology",
}
FORBIDDEN_EVIDENCE_PATH_PARTS = {
    "fixture",
    "fixtures",
    "historical",
    "loop_evidence",
    "retained",
}
RESOURCE_METRICS = (
    "peak_rss_bytes",
    "cpu_time_seconds",
    "fd_count",
    "connection_count",
    "cluster_bus_bytes",
)
FORMATION_MARKERS = (
    "last_process_ping",
    "first_membership_command",
    "all_primaries_known",
    "all_slots_assigned",
    "all_replicas_attached",
    "all_replicas_synchronized",
    "every_node_clean",
    "data_path_probe",
)
FAILOVER_MARKERS = (
    "sigkill_barrier",
    "all_processes_gone",
    "first_pfail",
    "quorum_fail",
    "first_promotion",
    "all_slots_covered_cluster_ok",
    "stable_client_recovery",
    "every_node_converged",
)
CRITERIA_BY_KIND = {
    "formation": {
        "performance.measurement-contract",
        "performance.cluster-formation-experiment",
        "performance.cluster-formation-budget",
    },
    "failover": {
        "performance.measurement-contract",
        "performance.automatic-failover-experiment",
        "performance.automatic-failover-budget",
    },
    "stability": {
        "performance.measurement-contract",
        "performance.stability-and-resource-safety",
    },
}


def round_half_up(value: int | float | Decimal) -> int:
    """Round to the nearest integer with exact halves rounded upward."""
    if isinstance(value, bool):
        raise ValueError("half-up input must be numeric")
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if not decimal.is_finite() or decimal < 0:
        raise ValueError("half-up input must be finite and non-negative")
    return int(decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def failed_primary_count(scale: int, failure_rate: str) -> int:
    if scale not in {50, 200}:
        raise ValueError("M2 failover scale must be exactly 50 or 200")
    primaries = scale // 2
    if failure_rate == "one":
        return 1
    if failure_rate == "10_percent":
        return round_half_up(Decimal(primaries) * Decimal("0.10"))
    if failure_rate == "33_percent":
        return round_half_up(Decimal(primaries) * Decimal("0.33"))
    raise ValueError(f"unsupported failure rate {failure_rate!r}")


def report_digest(report: Mapping[str, Any]) -> str:
    payload = dict(report)
    payload.pop("report_digest", None)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _treatment_key(value: Any) -> tuple[Any, ...]:
    treatment = _object(value)
    return (
        treatment.get("kind"),
        treatment.get("value"),
        treatment.get("bounded_parallelism"),
        treatment.get("cluster_create_strategy"),
        treatment.get("cluster_node_timeout_ms"),
    )


def _add(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def _all_unique(values: Iterable[Any]) -> bool:
    items = list(values)
    return len(items) == len(set(items))


def _relative_improvement(baseline: float, candidate: float) -> float | None:
    if baseline <= 0:
        return None
    return (baseline - candidate) / baseline


def _within_regression(baseline: float, candidate: float, limit: float) -> bool:
    if baseline == 0:
        return candidate == 0
    return candidate <= baseline * (1.0 + limit)


def _latency_bucket_bounds(bucket_index: int) -> tuple[float, float]:
    tick = LATENCY_HISTOGRAM_MIN_TICK + bucket_index
    return (
        0.0
        if bucket_index == 0
        else 2.0 ** ((tick - 1) / LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE),
        2.0 ** (tick / LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE),
    )


def _latency_bucket_index_from_upper(value: float) -> int | None:
    if value <= 0 or value > 2.0 ** (
        LATENCY_HISTOGRAM_MAX_TICK / LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE
    ):
        return None
    tick = round(math.log2(value) * LATENCY_HISTOGRAM_BUCKETS_PER_OCTAVE)
    bucket_index = tick - LATENCY_HISTOGRAM_MIN_TICK
    if not 0 <= bucket_index <= LATENCY_HISTOGRAM_MAX_INDEX:
        return None
    _lower, upper = _latency_bucket_bounds(bucket_index)
    return (
        bucket_index
        if math.isclose(value, upper, rel_tol=1e-12, abs_tol=1e-15)
        else None
    )


def _histogram_p99_within_regression(
    baseline_upper: float,
    candidate_upper: float,
    limit: float,
) -> bool:
    baseline_index = _latency_bucket_index_from_upper(baseline_upper)
    candidate_index = _latency_bucket_index_from_upper(candidate_upper)
    if baseline_index is None or candidate_index is None:
        return False
    baseline_lower, _baseline_upper = _latency_bucket_bounds(baseline_index)
    _candidate_lower, conservative_candidate = _latency_bucket_bounds(candidate_index)
    return conservative_candidate <= baseline_lower * (1.0 + limit)


def _resource_regression_clean(
    baseline_trial: Mapping[str, Any], candidate_trial: Mapping[str, Any]
) -> bool:
    baseline_window = _object(baseline_trial.get("resource_window"))
    candidate_window = _object(candidate_trial.get("resource_window"))
    for metric in RESOURCE_METRICS:
        baseline_value = _number(baseline_window.get(metric))
        candidate_value = _number(candidate_window.get(metric))
        if (
            baseline_value is None
            or candidate_value is None
            or baseline_value < 0
            or candidate_value < 0
            or not _within_regression(baseline_value, candidate_value, 0.10)
        ):
            return False
    return True


def _validate_required_shape(report: Mapping[str, Any]) -> list[str]:
    schema = load_json(SCHEMA_PATH)
    errors = validate(report, schema)
    # The dependency-free validator does not resolve $ref. Validate every M2
    # definition explicitly rather than silently accepting partial objects.
    definitions = _object(schema.get("$defs"))

    def validate_definition(value: Any, name: str, path: str) -> None:
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            errors.append(f"{path}: schema definition {name!r} is missing")
            return
        errors.extend(validate(value, definition, path))

    validate_definition(report.get("baseline"), "treatment", "$.baseline")
    for index, candidate in enumerate(_array(report.get("candidates"))):
        validate_definition(candidate, "treatment", f"$.candidates[{index}]")
    if report.get("selected_candidate") is not None:
        validate_definition(report.get("selected_candidate"), "treatment", "$.selected_candidate")
    for index, trial in enumerate(_array(report.get("trials"))):
        validate_definition(trial, "trial", f"$.trials[{index}]")
        item = _object(trial)
        validate_definition(item.get("treatment"), "treatment", f"$.trials[{index}].treatment")
        for ref_index, ref in enumerate(_array(item.get("source_sha256s"))):
            validate_definition(ref, "sourceRef", f"$.trials[{index}].source_sha256s[{ref_index}]")
    for index, pair in enumerate(_array(report.get("pairs"))):
        validate_definition(pair, "pair", f"$.pairs[{index}]")
    for index, cell in enumerate(_array(report.get("cells"))):
        validate_definition(cell, "cell", f"$.cells[{index}]")
        validate_definition(_object(cell).get("candidate"), "treatment", f"$.cells[{index}].candidate")
    for index, ref in enumerate(_array(report.get("source_refs"))):
        validate_definition(ref, "sourceRef", f"$.source_refs[{index}]")

    for name in ("baseline", "current_defaults", "protocol"):
        if not isinstance(report.get(name), dict):
            errors.append(f"$.{name}: expected object")
    for name in (
        "candidates",
        "trials",
        "pairs",
        "cells",
        "criterion_results",
        "invalid_samples",
        "started_trial_ids",
        "source_refs",
        "errors",
    ):
        if not isinstance(report.get(name), list):
            errors.append(f"$.{name}: expected array")
    return errors


def _validate_protocol(report: Mapping[str, Any], errors: list[str]) -> None:
    protocol = _object(report.get("protocol"))
    expected = {
        "percentile_method": "nearest-rank",
        "paired": True,
        "arm_order": "alternating-AB-BA",
        "fresh_cluster_per_arm": True,
        "cleanup_between_arms": True,
        "fixture_admission_allowed": False,
        "historical_admission_allowed": False,
        "downscale_allowed": False,
        "takeover_allowed": False,
        "stable_window_seconds": 1,
    }
    for field, value in expected.items():
        _add(errors, protocol.get(field) == value, f"protocol.{field} must be {value!r}")
    _add(
        errors,
        isinstance(protocol.get("formation_pairs_per_scale"), int)
        and protocol["formation_pairs_per_scale"] >= 7,
        "protocol.formation_pairs_per_scale must be at least 7",
    )
    _add(
        errors,
        isinstance(protocol.get("failover_pairs_per_cell"), int)
        and protocol["failover_pairs_per_cell"] >= 10,
        "protocol.failover_pairs_per_cell must be at least 10",
    )
    _add(
        errors,
        isinstance(protocol.get("stable_window_min_pairs"), int)
        and protocol["stable_window_min_pairs"] >= 10,
        "protocol.stable_window_min_pairs must be at least 10",
    )
    interval = _number(protocol.get("affected_shard_max_interval_ms"))
    _add(
        errors,
        interval is not None and 0 < interval <= 100,
        "protocol.affected_shard_max_interval_ms must be in (0, 100]",
    )
    _add(
        errors,
        isinstance(protocol.get("soak_seconds"), int) and protocol["soak_seconds"] >= 1800,
        "protocol.soak_seconds must be at least 1800",
    )


def _validate_criterion_results(report: Mapping[str, Any], errors: list[str]) -> None:
    kind = report.get("experiment_kind")
    expected = CRITERIA_BY_KIND.get(str(kind), set())
    rows = _array(report.get("criterion_results"))
    ids = [row.get("criterion_id") for row in rows if isinstance(row, dict)]
    _add(errors, set(ids) == expected and len(ids) == len(expected), f"criterion_results must contain exactly {sorted(expected)}")
    if report.get("status") == "PASS":
        for row in rows:
            item = _object(row)
            _add(errors, item.get("status") == "PASS", f"criterion {item.get('criterion_id', 'MISSING')} is not PASS")
            _add(errors, item.get("errors") == [], f"criterion {item.get('criterion_id', 'MISSING')} contains errors")


def _validate_trial_common(
    trial: Mapping[str, Any],
    report: Mapping[str, Any],
    errors: list[str],
    *,
    allow_safety_rejection: bool = False,
) -> None:
    trial_id = str(trial.get("trial_id", "MISSING"))
    prefix = f"trial {trial_id}"
    _add(errors, trial.get("real_valkey") is True, f"{prefix} is not real Valkey")
    _add(errors, trial.get("fresh_cluster") is True, f"{prefix} is not a fresh cluster")
    _add(errors, trial.get("timing_source") == "monotonic-observed", f"{prefix} does not use observed monotonic time")
    _add(errors, _number(trial.get("unexplained_seconds")) == 0.0, f"{prefix} has missing or unexplained wall time")
    scale = trial.get("scale")
    _add(errors, scale in {50, 100, 200}, f"{prefix} has an invalid or downscaled scale")
    correctness = _object(trial.get("correctness"))
    _add(errors, correctness.get("exact_membership") is True, f"{prefix} lacks exact membership")
    _add(errors, correctness.get("observed_nodes") == scale, f"{prefix} observed node count is not exact")
    _add(errors, correctness.get("slots_covered") == 16384, f"{prefix} lacks full slot coverage")
    _add(errors, correctness.get("replicas_synchronized") is True, f"{prefix} replicas are not synchronized")
    _add(errors, correctness.get("clean_topology") is True, f"{prefix} topology is not clean")
    _add(errors, correctness.get("data_path") is True, f"{prefix} data-path probe did not pass")
    _add(errors, correctness.get("split_brain") is False, f"{prefix} observed split brain")
    _add(errors, correctness.get("slot_loss") is False, f"{prefix} observed slot loss")
    for field in ("unexpected_pfail", "unexpected_fail", "unexpected_promotions"):
        _add(errors, correctness.get(field) == 0, f"{prefix} has nonzero {field}")

    resources = _object(trial.get("resource_window"))
    for metric in RESOURCE_METRICS:
        value = _number(resources.get(metric))
        _add(errors, value is not None and value >= 0, f"{prefix} resource {metric} is missing")
    for metric in ("cluster_link_errors", "buffer_overflows"):
        value = resources.get(metric)
        _add(
            errors,
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            and (value == 0 or allow_safety_rejection),
            f"{prefix} resource {metric} must be zero",
        )
    _add(errors, (_number(resources.get("duration_seconds")) or 0) > 0, f"{prefix} resource window duration is missing")

    cleanup = _object(trial.get("cleanup"))
    _add(errors, cleanup.get("status") == "PASS", f"{prefix} cleanup did not PASS")
    _add(errors, cleanup.get("resources_remaining") == [], f"{prefix} cleanup left owned resources")
    _add(errors, cleanup.get("cleanup_errors") == [], f"{prefix} cleanup has errors")
    _add(errors, isinstance(cleanup.get("evidence_ref"), str) and bool(cleanup.get("evidence_ref")), f"{prefix} cleanup evidence reference is missing")

    provenance = _object(trial.get("provenance"))
    _add(errors, provenance.get("status") == "PASS", f"{prefix} provenance did not PASS")
    _add(errors, provenance.get("current_invocation") is True, f"{prefix} provenance is not current")
    _add(errors, provenance.get("invocation_run_id") == report.get("invocation_run_id"), f"{prefix} provenance invocation does not match")
    _add(errors, provenance.get("product_owned") is True, f"{prefix} is not product-owned evidence")
    _add(errors, provenance.get("fixture") is False, f"{prefix} uses fixture evidence")
    _add(errors, provenance.get("historical") is False, f"{prefix} uses historical evidence")
    versions = _array(provenance.get("valkey_versions"))
    _add(errors, bool(versions) and all(isinstance(v, str) and VALKEY_91_RE.match(v) for v in versions), f"{prefix} lacks observed Valkey 9.1.x versions")
    for field in (
        "definition_digest",
        "valkey_binary_digest",
        "product_digest",
        "configuration_digest",
        "environment_digest",
        "topology_digest",
        "placement_digest",
        "workload_digest",
        "command_digest",
        "capture_digest",
        "resource_preflight_digest",
    ):
        _add(errors, isinstance(provenance.get(field), str) and SHA256_RE.fullmatch(provenance[field]) is not None, f"{prefix} provenance {field} is missing")
    refs = _array(trial.get("source_sha256s"))
    _add(errors, bool(refs), f"{prefix} has no source hashes")
    controls = _object(trial.get("control_digests"))
    _add(errors, set(controls) == CONTROL_DIGEST_KEYS, f"{prefix} control digest set is incomplete")
    _add(errors, all(isinstance(v, str) and SHA256_RE.fullmatch(v) for v in controls.values()), f"{prefix} has invalid control digests")
    for provenance_field, control_field in PROVENANCE_CONTROL_FIELDS.items():
        _add(
            errors,
            provenance.get(provenance_field) == controls.get(control_field),
            f"{prefix} provenance {provenance_field} does not match control {control_field}",
        )


def _validate_source_categories(
    trial: Mapping[str, Any],
    *,
    experiment_kind: Any,
    cell: Mapping[str, Any] | None,
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    refs = [_object(item) for item in _array(trial.get("source_sha256s"))]
    expected = set(COMMON_SOURCE_CATEGORIES)
    if experiment_kind == "failover" or (
        experiment_kind == "stability"
        and cell is not None
        and cell.get("failure_rate") != "none"
    ):
        expected.add("fault")
    categories = [ref.get("category") for ref in refs]
    _add(errors, set(categories) == expected, f"trial {trial_id} source categories must be exactly {sorted(expected)}")
    for category in ("attempt", "cleanup", "provenance"):
        _add(errors, categories.count(category) == 1, f"trial {trial_id} requires exactly one {category} source")


def _validate_marker_order(
    trial: Mapping[str, Any],
    required: Sequence[str],
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    markers = _object(trial.get("monotonic_markers"))
    values: list[float] = []
    for name in required:
        value = _number(markers.get(name))
        if value is None:
            errors.append(f"trial {trial_id} is missing monotonic marker {name}")
        else:
            values.append(value)
    if len(values) == len(required) and any(left > right for left, right in zip(values, values[1:])):
        errors.append(f"trial {trial_id} monotonic markers are out of order")


def _validate_pairs(
    report: Mapping[str, Any],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    cells_by_id: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> dict[str, list[Mapping[str, Any]]]:
    pairs = [_object(row) for row in _array(report.get("pairs"))]
    pair_ids = [row.get("pair_id") for row in pairs]
    _add(errors, all(isinstance(value, str) and value for value in pair_ids), "pair ids must be non-empty strings")
    _add(errors, _all_unique(pair_ids), "pair ids must be unique")
    by_cell: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    referenced_trials: list[str] = []
    for pair in pairs:
        pair_id = pair.get("pair_id", "MISSING")
        cell_id = pair.get("cell_id", "MISSING")
        by_cell[str(cell_id)].append(pair)
        baseline_id = pair.get("baseline_trial_id")
        candidate_id = pair.get("candidate_trial_id")
        referenced_trials.extend([str(baseline_id), str(candidate_id)])
        baseline = trials_by_id.get(str(baseline_id))
        candidate = trials_by_id.get(str(candidate_id))
        if baseline is None or candidate is None:
            errors.append(f"pair {pair_id} references missing trials")
            continue
        _add(errors, baseline.get("pair_id") == pair_id and candidate.get("pair_id") == pair_id, f"pair {pair_id} trial pair ids disagree")
        _add(errors, baseline.get("cell_id") == cell_id and candidate.get("cell_id") == cell_id, f"pair {pair_id} trial cell ids disagree")
        _add(errors, baseline.get("arm") == "baseline" and candidate.get("arm") == "candidate", f"pair {pair_id} arm labels are invalid")
        order = pair.get("order")
        expected_orders = (1, 2) if order == "AB" else (2, 1) if order == "BA" else (0, 0)
        _add(errors, (baseline.get("order"), candidate.get("order")) == expected_orders, f"pair {pair_id} arm order does not match {order!r}")
        _add(errors, _treatment_key(baseline.get("treatment")) == _treatment_key(report.get("baseline")), f"pair {pair_id} baseline treatment is wrong")
        candidate_cell = _object(cells_by_id.get(str(cell_id), {}))
        cell_candidate = candidate_cell.get("candidate")
        _add(errors, _treatment_key(candidate.get("treatment")) == _treatment_key(cell_candidate), f"pair {pair_id} candidate treatment is wrong")
        controls = _object(pair.get("control_digests"))
        _add(errors, set(controls) == CONTROL_DIGEST_KEYS, f"pair {pair_id} control digest set is incomplete")
        _add(errors, controls == _object(baseline.get("control_digests")) == _object(candidate.get("control_digests")), f"pair {pair_id} did not hold controls constant")
        baseline_fault = baseline.get("fault")
        candidate_fault = candidate.get("fault")
        if baseline_fault is not None or candidate_fault is not None:
            baseline_targets = {
                (str(target.get("logical_id")), str(target.get("shard_id")))
                for target in _array(_object(baseline_fault).get("targets"))
                if isinstance(target, dict)
            }
            candidate_targets = {
                (str(target.get("logical_id")), str(target.get("shard_id")))
                for target in _array(_object(candidate_fault).get("targets"))
                if isinstance(target, dict)
            }
            _add(
                errors,
                bool(baseline_targets)
                and baseline_targets == candidate_targets
                and len(baseline_targets) == len(_array(_object(baseline_fault).get("targets")))
                and len(candidate_targets) == len(_array(_object(candidate_fault).get("targets"))),
                f"pair {pair_id} did not hold logical fault targets and shards constant",
            )
        allow_discovery_resource_rejection = (
            candidate_cell.get("campaign_step") == "discovery"
            and candidate_cell.get("status") == "FAIL"
        )
        duration = _number(pair.get("equal_observation_seconds"))
        baseline_duration = _number(_object(baseline.get("resource_window")).get("duration_seconds"))
        candidate_duration = _number(_object(candidate.get("resource_window")).get("duration_seconds"))
        _add(
            errors,
            duration is not None
            and duration > 0
            and baseline_duration == duration
            and candidate_duration == duration,
            f"pair {pair_id} resource windows are not equal-duration",
        )
        for metric in RESOURCE_METRICS:
            baseline_value = _number(_object(baseline.get("resource_window")).get(metric))
            candidate_value = _number(_object(candidate.get("resource_window")).get(metric))
            _add(
                errors,
                baseline_value is not None
                and candidate_value is not None
                and (
                    _within_regression(baseline_value, candidate_value, 0.10)
                    or allow_discovery_resource_rejection
                ),
                f"pair {pair_id} {metric} regressed by more than 10 percent",
            )

    _add(errors, _all_unique(referenced_trials), "a trial is reused by more than one pair")
    _add(
        errors,
        set(referenced_trials) == set(trials_by_id),
        "every started trial must be referenced by exactly one pair",
    )
    for cell_id, cell_pairs in by_cell.items():
        ordered = sorted(cell_pairs, key=lambda row: row.get("sequence", 0))
        sequences = [row.get("sequence") for row in ordered]
        _add(errors, sequences == list(range(1, len(ordered) + 1)), f"cell {cell_id} pair sequences are not contiguous")
        for index, pair in enumerate(ordered, start=1):
            expected = "AB" if index % 2 else "BA"
            _add(errors, pair.get("order") == expected, f"cell {cell_id} pair {index} must use {expected} order")
    return by_cell


def _cell_index(report: Mapping[str, Any], errors: list[str]) -> dict[str, Mapping[str, Any]]:
    cells = [_object(row) for row in _array(report.get("cells"))]
    cell_ids = [row.get("cell_id") for row in cells]
    _add(errors, all(isinstance(value, str) and value for value in cell_ids), "cell ids must be non-empty strings")
    _add(errors, _all_unique(cell_ids), "cell ids must be unique")
    return {str(row.get("cell_id")): row for row in cells}


def _trials_for_pairs(
    pairs: Sequence[Mapping[str, Any]],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    arm: str,
) -> list[Mapping[str, Any]]:
    field = "baseline_trial_id" if arm == "baseline" else "candidate_trial_id"
    return [trials_by_id[str(pair[field])] for pair in pairs if str(pair.get(field)) in trials_by_id]


def _metric_values(
    trials: Sequence[Mapping[str, Any]],
    field: str,
    errors: list[str],
) -> list[float]:
    values: list[float] = []
    for trial in trials:
        value = _number(_object(trial.get("derived_intervals")).get(field))
        if value is None:
            errors.append(f"trial {trial.get('trial_id', 'MISSING')} is missing interval {field}")
        else:
            values.append(value)
    return values


def _trial_safety_clean(trial: Mapping[str, Any]) -> bool:
    resources = _object(trial.get("resource_window"))
    return not resources or (
        resources.get("cluster_link_errors") == 0
        and resources.get("buffer_overflows") == 0
    )


def _validate_formation_discovery(
    report: Mapping[str, Any],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    pairs_by_cell: Mapping[str, list[Mapping[str, Any]]],
    cells_by_id: Mapping[str, Mapping[str, Any]],
    errors: list[str],
    *,
    require_selected: bool,
    allow_legacy_screen: bool = False,
) -> set[tuple[Any, ...]]:
    _add(errors, _treatment_key(report.get("baseline")) == _treatment_key(BASELINE_FORMATION), "formation baseline must force the current valkey-cli primary-create path")
    candidates = [_object(item) for item in _array(report.get("candidates"))]
    _add(errors, bool(candidates), "formation discovery candidates are missing")
    manual = [item for item in candidates if item.get("value") == "manual_tree_meet_parallel_slots"]
    range_candidates = [
        item
        for item in candidates
        if isinstance(item.get("value"), str)
        and "addslotsrange" in item["value"].lower()
    ]
    screen_version = report.get("candidate_screen_version")
    legacy_screen = allow_legacy_screen and screen_version is None
    expected_parallelism = {4, 8, 16} if legacy_screen else {2, 4, 8, 16}
    _add(
        errors,
        screen_version == "v2" or legacy_screen,
        "formation discovery candidate screen version must be 'v2'",
    )
    _add(errors, len(manual) == 1, "formation discovery must include the existing manual-tree diagnostic")
    _add(errors, {item.get("bounded_parallelism") for item in range_candidates} == expected_parallelism, "formation discovery must include the declared bounded ADDSLOTSRANGE parallelism screen")
    candidate_keys = [_treatment_key(item) for item in candidates]
    expected_candidate_keys = {
        ("cluster_create_strategy", "manual_tree_meet_parallel_slots", None, None, None),
        *{
            (
                "cluster_create_strategy",
                "tree_meet_addslotsrange",
                parallelism,
                None,
                None,
            )
            for parallelism in sorted(expected_parallelism)
        },
    }
    _add(
        errors,
        len(candidate_keys) == len(expected_candidate_keys)
        and set(candidate_keys) == expected_candidate_keys,
        "formation discovery must contain exactly the fixed manual-tree and ADDSLOTSRANGE candidates",
    )
    _add(errors, _all_unique(candidate_keys), "formation candidate treatments must be unique")
    selected = _object(report.get("selected_candidate"))
    if require_selected:
        _add(errors, _treatment_key(selected) in set(candidate_keys), "selected formation candidate was not in the discovery screen")
        _add(errors, _treatment_key(selected) != _treatment_key(report.get("baseline")), "formation candidate must differ from the baseline")

    discovery = [cell for cell in cells_by_id.values() if cell.get("campaign_step") == "discovery"]
    _add(errors, len(discovery) == len(candidates), "formation requires one exact-50 discovery cell per candidate")
    survivor_keys: set[tuple[Any, ...]] = set()
    for candidate in candidates:
        matching = [
            cell
            for cell in discovery
            if cell.get("scale") == 50
            and cell.get("failure_rate") == "none"
            and _treatment_key(cell.get("candidate")) == _treatment_key(candidate)
        ]
        _add(errors, len(matching) == 1, f"formation candidate {_treatment_key(candidate)!r} lacks an exact-50 discovery cell")
        if matching:
            discovery_cell = matching[0]
            discovery_cell_id = str(discovery_cell.get("cell_id"))
            cell_pairs = pairs_by_cell.get(discovery_cell_id, [])
            _add(errors, isinstance(discovery_cell.get("required_pairs"), int) and discovery_cell["required_pairs"] >= 1, f"formation discovery cell {discovery_cell_id} requires fewer than one pair")
            _add(errors, len(cell_pairs) >= 1, f"formation discovery cell {discovery_cell_id} has no fresh pair")
            baseline_values = _metric_values(
                _trials_for_pairs(cell_pairs, trials_by_id, "baseline"),
                "formation_seconds",
                errors,
            )
            candidate_values = _metric_values(
                _trials_for_pairs(cell_pairs, trials_by_id, "candidate"),
                "formation_seconds",
                errors,
            )
            passed = (
                len(baseline_values) == len(cell_pairs)
                and len(candidate_values) == len(cell_pairs)
                and bool(cell_pairs)
                and all(
                    _trial_safety_clean(trial)
                    for trial in _trials_for_pairs(cell_pairs, trials_by_id, "candidate")
                )
                and all(
                    _resource_regression_clean(baseline_trial, candidate_trial)
                    for baseline_trial, candidate_trial in zip(
                        _trials_for_pairs(cell_pairs, trials_by_id, "baseline"),
                        _trials_for_pairs(cell_pairs, trials_by_id, "candidate"),
                    )
                )
                and nearest_rank(candidate_values, 0.50) < nearest_rank(baseline_values, 0.50)
            )
            expected_status = "PASS" if passed else "FAIL"
            _add(errors, discovery_cell.get("status") == expected_status, f"formation discovery cell {discovery_cell_id} status does not match measured screen result")
            if passed:
                survivor_keys.add(_treatment_key(candidate))
            if require_selected and _treatment_key(candidate) == _treatment_key(selected):
                _add(errors, passed, "selected formation candidate did not beat baseline in discovery")

    if require_selected:
        _add(errors, _treatment_key(selected) in survivor_keys, "selected formation candidate is not a discovery survivor")
    return survivor_keys


def _validate_formation(
    report: Mapping[str, Any],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    pairs_by_cell: Mapping[str, list[Mapping[str, Any]]],
    cells_by_id: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    survivor_keys = _validate_formation_discovery(
        report,
        trials_by_id,
        pairs_by_cell,
        cells_by_id,
        errors,
        require_selected=True,
    )
    promotion = [cell for cell in cells_by_id.values() if cell.get("campaign_step") == "promotion"]
    expected_promotion = {
        (candidate_key, scale)
        for candidate_key in survivor_keys
        for scale in (50, 100, 200)
    }
    observed_promotion = {
        (_treatment_key(cell.get("candidate")), cell.get("scale"))
        for cell in promotion
    }
    _add(
        errors,
        observed_promotion == expected_promotion and len(promotion) == len(expected_promotion),
        "every and only formation discovery survivor must run exact 50, 100, and 200 promotion cells",
    )
    for cell in promotion:
        scale = cell.get("scale")
        cell_id = str(cell.get("cell_id"))
        _add(errors, _treatment_key(cell.get("candidate")) in survivor_keys, f"formation cell {cell_id} promotes a discovery loser")
        pairs = pairs_by_cell.get(cell_id, [])
        _add(errors, cell.get("status") == "PASS", f"formation promotion cell {cell_id} did not PASS")
        _add(errors, isinstance(cell.get("required_pairs"), int) and cell["required_pairs"] >= 7, f"formation cell {cell_id} requires fewer than 7 pairs")
        _add(errors, len(pairs) >= 7, f"formation cell {cell_id} has fewer than 7 valid pairs")
        baseline_trials = _trials_for_pairs(pairs, trials_by_id, "baseline")
        candidate_trials = _trials_for_pairs(pairs, trials_by_id, "candidate")
        baseline_values = _metric_values(baseline_trials, "formation_seconds", errors)
        candidate_values = _metric_values(candidate_trials, "formation_seconds", errors)
        if len(baseline_values) >= 7 and len(candidate_values) >= 7:
            baseline_median = nearest_rank(baseline_values, 0.50)
            candidate_median = nearest_rank(candidate_values, 0.50)
            improvement = _relative_improvement(baseline_median, candidate_median)
            threshold = 0.20 if scale == 50 else 0.30
            _add(errors, improvement is not None and improvement >= threshold, f"formation exact-{scale} median improvement is below {threshold:.0%}")
            _add(errors, nearest_rank(candidate_values, 0.95) <= 60.0, f"formation exact-{scale} observed p95 exceeds 60 seconds")

    _validate_formation_trials(trials_by_id.values(), errors)


def _validate_formation_trials(
    trials: Iterable[Mapping[str, Any]], errors: list[str]
) -> None:
    for trial in trials:
        _validate_marker_order(trial, FORMATION_MARKERS, errors)
        markers = _object(trial.get("monotonic_markers"))
        interval = _number(_object(trial.get("derived_intervals")).get("formation_seconds"))
        start = _number(markers.get("last_process_ping"))
        end = _number(markers.get("data_path_probe"))
        _add(
            errors,
            interval is not None
            and interval > 0
            and start is not None
            and end is not None
            and math.isclose(interval, end - start, rel_tol=0, abs_tol=1e-6),
            f"trial {trial.get('trial_id', 'MISSING')} formation interval is not derived from required endpoints",
        )


def _validate_fault(
    trial: Mapping[str, Any],
    cell: Mapping[str, Any],
    physical_fault_ids: set[str],
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    fault = _object(trial.get("fault"))
    _add(
        errors,
        fault == _compact_fault_summary(fault),
        f"trial {trial_id} fault summary contains raw or non-contract fields",
    )
    _add(errors, fault.get("mode") == "owned-process-sigkill", f"trial {trial_id} did not use owned-process SIGKILL")
    _add(errors, fault.get("signal") == "SIGKILL", f"trial {trial_id} did not use SIGKILL")
    commands = _array(fault.get("commands"))
    normalized = [" ".join(str(item).upper().split()) for item in commands]
    forbidden = ("CLUSTER FAILOVER", " TAKEOVER", " FORCE")
    _add(errors, not any(any(token in f" {command}" for token in forbidden) for command in normalized), f"trial {trial_id} used FAILOVER, FORCE, or TAKEOVER")
    targets = [_object(item) for item in _array(fault.get("targets"))]
    target_ids = [target.get("logical_id") for target in targets]
    _add(errors, bool(targets) and _all_unique(target_ids), f"trial {trial_id} fault targets are absent or duplicated")
    for target in targets:
        _add(errors, isinstance(target.get("pid"), int) and target["pid"] > 0, f"trial {trial_id} target PID is missing")
        _add(errors, target.get("ownership_id") == trial.get("ownership_id"), f"trial {trial_id} target ownership is invalid")
        _add(errors, target.get("process_gone") is True, f"trial {trial_id} lacks target PID-gone proof")
        fault_id = target.get("physical_fault_id")
        _add(errors, isinstance(fault_id, str) and bool(fault_id), f"trial {trial_id} physical fault id is missing")
        if isinstance(fault_id, str):
            _add(errors, fault_id not in physical_fault_ids, f"physical fault id {fault_id!r} is reused")
            physical_fault_ids.add(fault_id)
    scale = trial.get("scale")
    rate = cell.get("failure_rate")
    expected = failed_primary_count(int(scale), str(rate)) if scale in {50, 200} and rate in FAILURE_RATES else None
    _add(errors, fault.get("primary_count") == (scale // 2 if isinstance(scale, int) else None), f"trial {trial_id} primary count is wrong")
    _add(errors, fault.get("failed_primary_count") == expected == len(targets), f"trial {trial_id} failure count does not use half-up rounding")
    skew = _number(fault.get("injection_skew_ms"))
    barrier_span = _number(fault.get("signal_barrier_span_ms"))
    _add(
        errors,
        skew is not None
        and barrier_span is not None
        and math.isclose(skew, barrier_span, rel_tol=0, abs_tol=1e-6)
        and 0 <= skew <= 500,
        f"trial {trial_id} physical SIGKILL barrier span exceeds 500 ms or is unbound",
    )
    _add(errors, _number(fault.get("barrier_monotonic")) is not None, f"trial {trial_id} fault barrier is missing")

    workload = _object(trial.get("workload"))
    _add(errors, workload.get("persistent_cluster_client") is True, f"trial {trial_id} did not use a persistent cluster-aware client")
    _add(errors, workload.get("per_operation_process_spawn") is False, f"trial {trial_id} spawned a process per client operation")
    cadence = _number(workload.get("affected_shard_max_interval_ms"))
    _add(errors, cadence is not None and 0 < cadence <= 100, f"trial {trial_id} affected-shard cadence exceeds 100 ms")
    stable = [_object(item) for item in _array(workload.get("stable_shards"))]
    target_shards = {str(target.get("shard_id")) for target in targets}
    stable_shards = {str(item.get("shard_id")) for item in stable}
    _add(errors, stable_shards == target_shards and len(stable) == len(targets), f"trial {trial_id} stable recovery does not cover every affected shard")
    endpoints: list[float] = []
    for item in stable:
        endpoint = _number(item.get("endpoint_monotonic"))
        start = _number(item.get("window_start_monotonic"))
        if endpoint is not None:
            endpoints.append(endpoint)
        _add(errors, item.get("window_seconds") == 1, f"trial {trial_id} stable shard window is not exactly one second")
        _add(errors, isinstance(item.get("consecutive_pairs"), int) and item["consecutive_pairs"] >= 10, f"trial {trial_id} stable shard has fewer than ten pairs")
        _add(errors, item.get("errors") == 0 and item.get("timeouts") == 0, f"trial {trial_id} stable shard contains an error or timeout")
        _add(errors, item.get("earliest_qualifying") is True, f"trial {trial_id} stable shard endpoint is not the earliest qualifying window")
        _add(errors, start is not None and endpoint is not None and math.isclose(endpoint - start, 1.0, rel_tol=0, abs_tol=1e-6), f"trial {trial_id} stable shard endpoint does not close its one-second window")
    aggregate = _number(_object(trial.get("monotonic_markers")).get("stable_client_recovery"))
    _add(errors, bool(endpoints) and aggregate == max(endpoints), f"trial {trial_id} stable recovery is not the latest affected-shard endpoint")


def _validate_failover_intervals(trial: Mapping[str, Any], errors: list[str]) -> None:
    intervals = _object(trial.get("derived_intervals"))
    markers = _object(trial.get("monotonic_markers"))
    endpoints = {
        "kill_to_stable_seconds": ("sigkill_barrier", "stable_client_recovery"),
        "pfail_to_cluster_ok_seconds": ("first_pfail", "all_slots_covered_cluster_ok"),
        "process_gone_to_pfail_seconds": ("all_processes_gone", "first_pfail"),
        "cluster_ok_to_stable_seconds": ("all_slots_covered_cluster_ok", "stable_client_recovery"),
    }
    for interval_name, (start_name, end_name) in endpoints.items():
        interval = _number(intervals.get(interval_name))
        start = _number(markers.get(start_name))
        end = _number(markers.get(end_name))
        _add(
            errors,
            interval is not None
            and start is not None
            and end is not None
            and math.isclose(interval, end - start, rel_tol=0, abs_tol=1e-6),
            f"trial {trial.get('trial_id', 'MISSING')} interval {interval_name} is not derived from its markers",
        )


def _failover_discovery_passed(
    pairs: Sequence[Mapping[str, Any]],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> bool:
    baseline_trials = _trials_for_pairs(pairs, trials_by_id, "baseline")
    candidate_trials = _trials_for_pairs(pairs, trials_by_id, "candidate")
    baseline_rto = _metric_values(baseline_trials, "kill_to_stable_seconds", errors)
    candidate_rto = _metric_values(candidate_trials, "kill_to_stable_seconds", errors)
    candidate_pfail = _metric_values(candidate_trials, "pfail_to_cluster_ok_seconds", errors)
    candidate_detection = _metric_values(candidate_trials, "process_gone_to_pfail_seconds", errors)
    candidate_client = _metric_values(candidate_trials, "cluster_ok_to_stable_seconds", errors)
    complete = bool(pairs) and all(
        len(values) == len(pairs)
        for values in (
            baseline_rto,
            candidate_rto,
            candidate_pfail,
            candidate_detection,
            candidate_client,
        )
    )
    return (
        complete
        and all(_trial_safety_clean(trial) for trial in candidate_trials)
        and all(
            _resource_regression_clean(baseline_trial, candidate_trial)
            for baseline_trial, candidate_trial in zip(baseline_trials, candidate_trials)
        )
        and nearest_rank(candidate_rto, 0.50) < nearest_rank(baseline_rto, 0.50)
        and nearest_rank(candidate_rto, 0.95) <= 35.0
        and nearest_rank(candidate_pfail, 0.95) <= 10.0
        and nearest_rank(candidate_detection, 0.95) <= 25.0
        and max(candidate_client) <= 2.0
    )


def _validate_failover_discovery(
    report: Mapping[str, Any],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    pairs_by_cell: Mapping[str, list[Mapping[str, Any]]],
    cells_by_id: Mapping[str, Mapping[str, Any]],
    errors: list[str],
    *,
    require_selected: bool,
) -> set[tuple[Any, ...]]:
    defaults = _object(report.get("current_defaults"))
    current_strategy = defaults.get("cluster_create_strategy")
    _add(
        errors,
        isinstance(current_strategy, str)
        and bool(current_strategy)
        and current_strategy == _current_formation_strategy(),
        "failover current formation strategy is not bound to the product default",
    )
    expected_baseline = {
        **BASELINE_FAILOVER,
        "cluster_create_strategy": current_strategy,
    }
    _add(
        errors,
        _treatment_key(report.get("baseline")) == _treatment_key(expected_baseline),
        "failover baseline must force 30000 ms while holding the current formation strategy",
    )
    candidates = [_object(item) for item in _array(report.get("candidates"))]
    expected_candidates = {
        ("cluster_node_timeout_ms", 5000, None, current_strategy, None),
        ("cluster_node_timeout_ms", 10000, None, current_strategy, None),
        ("cluster_node_timeout_ms", 15000, None, current_strategy, None),
    }
    candidate_keys = [_treatment_key(item) for item in candidates]
    _add(
        errors,
        len(candidate_keys) == len(expected_candidates)
        and _all_unique(candidate_keys)
        and set(candidate_keys) == expected_candidates,
        "failover screen must contain 5000, 10000, and 15000 ms with one current formation strategy",
    )
    selected = _object(report.get("selected_candidate"))
    if require_selected:
        _add(errors, _treatment_key(selected) in expected_candidates, "selected failover timeout was not screened")
        _add(errors, _treatment_key(selected) != _treatment_key(report.get("baseline")), "failover candidate must differ from 30000 ms")

    discovery = [cell for cell in cells_by_id.values() if cell.get("campaign_step") == "discovery"]
    _add(errors, len(discovery) == 3, "failover requires three exact-50 single-failure discovery cells")
    survivor_keys: set[tuple[Any, ...]] = set()
    for candidate in candidates:
        matching = [
            cell
            for cell in discovery
            if cell.get("scale") == 50
            and cell.get("failure_rate") == "one"
            and _treatment_key(cell.get("candidate")) == _treatment_key(candidate)
        ]
        _add(errors, len(matching) == 1, f"timeout candidate {candidate.get('value')} lacks an exact-50 single-failure screen")
        if matching:
            discovery_cell = matching[0]
            discovery_cell_id = str(discovery_cell.get("cell_id"))
            discovery_pairs = pairs_by_cell.get(discovery_cell_id, [])
            _add(errors, isinstance(discovery_cell.get("required_pairs"), int) and discovery_cell["required_pairs"] >= 1, f"failover discovery cell {discovery_cell_id} requires fewer than one pair")
            _add(errors, bool(discovery_pairs), f"failover discovery cell {discovery_cell_id} has no fresh pair")
            passed = _failover_discovery_passed(discovery_pairs, trials_by_id, errors)
            expected_status = "PASS" if passed else "FAIL"
            _add(errors, discovery_cell.get("status") == expected_status, f"failover discovery cell {discovery_cell_id} status does not match measured screen result")
            if passed:
                survivor_keys.add(_treatment_key(candidate))
            if require_selected and _treatment_key(candidate) == _treatment_key(selected):
                _add(errors, passed, "selected failover timeout did not pass discovery")

    if require_selected:
        _add(errors, _treatment_key(selected) in survivor_keys, "selected failover timeout is not a discovery survivor")
    return survivor_keys


def _validate_failover(
    report: Mapping[str, Any],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    pairs_by_cell: Mapping[str, list[Mapping[str, Any]]],
    cells_by_id: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    selected = _object(report.get("selected_candidate"))
    if selected.get("value") == DIRECT_FAILOVER_FULL_VALIDATION_TIMEOUT_MS:
        defaults = _object(report.get("current_defaults"))
        current_strategy = defaults.get("cluster_create_strategy")
        expected_baseline = {
            **BASELINE_FAILOVER,
            "cluster_create_strategy": current_strategy,
        }
        expected_candidate = (
            "cluster_node_timeout_ms",
            DIRECT_FAILOVER_FULL_VALIDATION_TIMEOUT_MS,
            None,
            current_strategy,
            None,
        )
        candidate_keys = [_treatment_key(item) for item in _array(report.get("candidates"))]
        _add(
            errors,
            isinstance(current_strategy, str)
            and bool(current_strategy)
            and current_strategy == _current_formation_strategy(),
            "direct failover candidate current formation strategy is not bound to the product default",
        )
        _add(
            errors,
            _treatment_key(report.get("baseline")) == _treatment_key(expected_baseline),
            "direct failover baseline must force 30000 ms while holding the current formation strategy",
        )
        _add(
            errors,
            candidate_keys == [expected_candidate],
            "direct failover validation must contain only the authorized 20000 ms candidate",
        )
        _add(
            errors,
            _treatment_key(selected) == expected_candidate,
            "direct failover selected candidate must be the authorized 20000 ms timeout",
        )
        _add(
            errors,
            not [cell for cell in cells_by_id.values() if cell.get("campaign_step") == "discovery"],
            "direct failover validation cannot add a discovery screen",
        )
        survivor_keys = {expected_candidate}
    else:
        survivor_keys = _validate_failover_discovery(
            report,
            trials_by_id,
            pairs_by_cell,
            cells_by_id,
            errors,
            require_selected=True,
        )
    matrix = [cell for cell in cells_by_id.values() if cell.get("campaign_step") == "matrix"]
    observed_cells = {
        (_treatment_key(cell.get("candidate")), cell.get("scale"), cell.get("failure_rate"))
        for cell in matrix
    }
    expected_cells = {
        (candidate_key, scale, rate)
        for candidate_key in survivor_keys
        for scale in (50, 200)
        for rate in FAILURE_RATES
    }
    _add(
        errors,
        observed_cells == expected_cells and len(matrix) == len(expected_cells),
        "every and only failover discovery survivor must run exact 50/200 by one/10%/33%",
    )
    physical_fault_ids: set[str] = set()
    for trial in trials_by_id.values():
        cell = cells_by_id.get(str(trial.get("cell_id")))
        if cell is not None and cell.get("campaign_step") in {"discovery", "matrix"}:
            _validate_marker_order(trial, FAILOVER_MARKERS, errors)
            _validate_fault(trial, cell, physical_fault_ids, errors)
            _validate_failover_intervals(trial, errors)
    candidate_process_gone_values: list[float] = []
    rto_limits = {"one": 35.0, "10_percent": 45.0, "33_percent": 55.0}
    pfail_limits = {"one": 10.0, "10_percent": 15.0, "33_percent": 25.0}
    for cell in matrix:
        cell_id = str(cell.get("cell_id"))
        _add(errors, _treatment_key(cell.get("candidate")) in survivor_keys, f"failover cell {cell_id} does not use the admitted candidate")
        pairs = pairs_by_cell.get(cell_id, [])
        _add(errors, cell.get("status") == "PASS", f"failover matrix cell {cell_id} did not PASS")
        _add(errors, isinstance(cell.get("required_pairs"), int) and cell["required_pairs"] >= 10, f"failover cell {cell_id} requires fewer than 10 pairs")
        _add(errors, len(pairs) >= 10, f"failover cell {cell_id} has fewer than 10 valid pairs")
        baseline_trials = _trials_for_pairs(pairs, trials_by_id, "baseline")
        candidate_trials = _trials_for_pairs(pairs, trials_by_id, "candidate")
        baseline_rto = _metric_values(baseline_trials, "kill_to_stable_seconds", errors)
        candidate_rto = _metric_values(candidate_trials, "kill_to_stable_seconds", errors)
        candidate_pfail = _metric_values(candidate_trials, "pfail_to_cluster_ok_seconds", errors)
        candidate_process_gone = _metric_values(candidate_trials, "process_gone_to_pfail_seconds", errors)
        candidate_process_gone_values.extend(candidate_process_gone)
        if len(baseline_rto) >= 10 and len(candidate_rto) >= 10:
            for percentile in (0.50, 0.95):
                baseline_value = nearest_rank(baseline_rto, percentile)
                candidate_value = nearest_rank(candidate_rto, percentile)
                improvement = _relative_improvement(baseline_value, candidate_value)
                _add(errors, improvement is not None and improvement >= 0.20, f"failover cell {cell_id} p{int(percentile * 100)} improvement is below 20 percent")
            rate = str(cell.get("failure_rate"))
            _add(errors, nearest_rank(candidate_rto, 0.95) <= rto_limits[rate], f"failover cell {cell_id} client RTO p95 exceeds its absolute budget")
        if len(candidate_pfail) >= 10:
            rate = str(cell.get("failure_rate"))
            _add(errors, nearest_rank(candidate_pfail, 0.95) <= pfail_limits[rate], f"failover cell {cell_id} PFAIL-to-cluster-OK p95 exceeds its budget")
        for trial in (*baseline_trials, *candidate_trials):
            intervals = _object(trial.get("derived_intervals"))
            if trial.get("arm") == "candidate":
                cluster_to_client = _number(intervals.get("cluster_ok_to_stable_seconds"))
                _add(errors, cluster_to_client is not None and cluster_to_client <= 2.0, f"trial {trial.get('trial_id', 'MISSING')} cluster-OK to stable client exceeds 2 seconds")
    expected_process_gone_samples = 60 * len(survivor_keys)
    if expected_process_gone_samples > 0 and len(candidate_process_gone_values) >= expected_process_gone_samples:
        _add(errors, nearest_rank(candidate_process_gone_values, 0.95) <= 25.0, "failover process-gone-to-PFAIL p95 exceeds 25 seconds")
    else:
        errors.append(
            "failover process-gone-to-PFAIL distribution has fewer than "
            f"{expected_process_gone_samples} candidate samples"
        )


def _validate_stability(
    report: Mapping[str, Any],
    trials_by_id: Mapping[str, Mapping[str, Any]],
    pairs_by_cell: Mapping[str, list[Mapping[str, Any]]],
    cells_by_id: Mapping[str, Mapping[str, Any]],
    errors: list[str],
) -> None:
    selected = _object(report.get("selected_candidate"))
    baseline_settings = _object(report.get("baseline"))
    _add(errors, bool(selected), "stability report has no selected candidate")
    _add(
        errors,
        baseline_settings.get("kind") == "selected_settings"
        and baseline_settings.get("cluster_create_strategy") == BASELINE_FORMATION["value"]
        and baseline_settings.get("cluster_node_timeout_ms") == BASELINE_FAILOVER["value"],
        "stability baseline must use the M1 cluster-create strategy and 30000 ms timeout",
    )
    _add(errors, selected.get("kind") == "selected_settings", "stability candidate must describe selected settings")
    _add(
        errors,
        (
            selected.get("cluster_create_strategy"),
            selected.get("cluster_node_timeout_ms"),
            selected.get("bounded_parallelism"),
        )
        != (
            baseline_settings.get("cluster_create_strategy"),
            baseline_settings.get("cluster_node_timeout_ms"),
            baseline_settings.get("bounded_parallelism"),
        ),
        "stability selected settings must differ from the M1 baseline",
    )
    paired_cells = [cell for cell in cells_by_id.values() if cell.get("campaign_step") == "stability"]
    bootstrap = [cell for cell in paired_cells if cell.get("scale") == 200 and cell.get("failure_rate") == "none"]
    fault = [cell for cell in paired_cells if cell.get("scale") == 200 and cell.get("failure_rate") == "33_percent"]
    _add(errors, len(paired_cells) == 2, "stability requires exactly its bootstrap and 33-percent fault cells")
    _add(errors, len(bootstrap) == 1, "stability requires one exact-200 paired bootstrap window")
    _add(errors, len(fault) == 1, "stability requires one exact-200 paired 33-percent fault window")

    soak_cells = [
        cell
        for cell in cells_by_id.values()
        if cell.get("campaign_step") == "soak"
        and cell.get("scale") == 200
        and cell.get("failure_rate") == "none"
    ]
    _add(errors, len(soak_cells) == 1, "stability requires one exact-200 paired soak")

    def validate_workload_pair(pair: Mapping[str, Any]) -> None:
        baseline_trial = trials_by_id.get(str(pair.get("baseline_trial_id")), {})
        candidate_trial = trials_by_id.get(str(pair.get("candidate_trial_id")), {})
        baseline_workload = _object(baseline_trial.get("workload"))
        candidate_workload = _object(candidate_trial.get("workload"))
        pair_id = pair.get("pair_id", "MISSING")
        baseline_duration = _number(baseline_workload.get("duration_seconds"))
        candidate_duration = _number(candidate_workload.get("duration_seconds"))
        requested_duration = _number(pair.get("equal_observation_seconds"))
        _add(
            errors,
            requested_duration is not None
            and requested_duration > 0
            and baseline_duration is not None
            and baseline_duration >= requested_duration
            and candidate_duration is not None
            and candidate_duration >= requested_duration,
            f"stability pair {pair_id} workload windows do not cover the equal requested duration",
        )
        baseline_throughput = _number(baseline_workload.get("set_throughput_ops_per_second"))
        candidate_throughput = _number(candidate_workload.get("set_throughput_ops_per_second"))
        _add(errors, baseline_throughput is not None and baseline_throughput > 0 and candidate_throughput is not None and candidate_throughput >= baseline_throughput * 0.95, f"stability pair {pair_id} throughput regressed by more than 5 percent")
        baseline_latency = _number(baseline_workload.get("p99_latency_ms"))
        candidate_latency = _number(candidate_workload.get("p99_latency_ms"))
        _add(
            errors,
            baseline_latency is not None
            and candidate_latency is not None
            and _histogram_p99_within_regression(
                baseline_latency,
                candidate_latency,
                0.10,
            ),
            f"stability pair {pair_id} p99 latency regressed by more than 10 percent",
        )
        _add(errors, baseline_workload.get("errors") == 0 and candidate_workload.get("errors") == 0, f"stability pair {pair_id} workload has errors")

    for cell in (*bootstrap, *fault, *soak_cells):
        cell_id = str(cell.get("cell_id"))
        pairs = pairs_by_cell.get(cell_id, [])
        _add(errors, _treatment_key(cell.get("candidate")) == _treatment_key(selected), f"stability cell {cell_id} does not exercise selected settings")
        _add(errors, cell.get("status") == "PASS", f"stability cell {cell_id} did not PASS")
        _add(errors, isinstance(cell.get("required_pairs"), int) and cell["required_pairs"] >= 1, f"stability cell {cell_id} requires fewer than one pair")
        _add(errors, len(pairs) >= 1, f"stability cell {cell_id} has no A/B pair")
        if cell.get("failure_rate") == "none":
            for pair in pairs:
                validate_workload_pair(pair)

    physical_fault_ids: set[str] = set()
    for cell in fault:
        for trial in trials_by_id.values():
            if trial.get("cell_id") != cell.get("cell_id"):
                continue
            _validate_marker_order(trial, FAILOVER_MARKERS, errors)
            _validate_fault(trial, cell, physical_fault_ids, errors)

    if soak_cells:
        soak_cell = soak_cells[0]
        soak_pairs = pairs_by_cell.get(str(soak_cell.get("cell_id")), [])
        for trial in (
            *_trials_for_pairs(soak_pairs, trials_by_id, "baseline"),
            *_trials_for_pairs(soak_pairs, trials_by_id, "candidate"),
        ):
            resources = _object(trial.get("resource_window"))
            workload = _object(trial.get("workload"))
            _add(errors, (_number(resources.get("duration_seconds")) or 0) >= 1800, "exact-200 resource soak is shorter than 30 minutes")
            _add(errors, (_number(workload.get("duration_seconds")) or 0) >= 1800, "exact-200 workload soak is shorter than 30 minutes")
            _add(errors, workload.get("errors") == 0, "exact-200 soak workload has errors")


def _validate_trials_and_pairs(
    report: Mapping[str, Any],
    errors: list[str],
    *,
    allow_discovery_safety_rejections: bool = False,
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, list[Mapping[str, Any]]],
]:
    kind = report.get("experiment_kind")
    invocation_run_id = report.get("invocation_run_id")
    trials = [_object(row) for row in _array(report.get("trials"))]
    trial_ids = [row.get("trial_id") for row in trials]
    run_ids = [row.get("run_id") for row in trials]
    ownership_ids = [row.get("ownership_id") for row in trials]
    _add(errors, all(isinstance(value, str) and value for value in trial_ids), "trial ids must be non-empty strings")
    _add(errors, _all_unique(trial_ids), "trial ids must be unique")
    _add(errors, _all_unique(run_ids), "physical trial run ids must be unique")
    _add(errors, _all_unique(ownership_ids), "physical trial ownership ids must be unique")
    started_trial_ids = _array(report.get("started_trial_ids"))
    _add(errors, all(isinstance(value, str) and value for value in started_trial_ids), "started trial ids must be non-empty strings")
    _add(errors, _all_unique(started_trial_ids), "started trial ids must be unique")
    _add(errors, set(started_trial_ids) == set(trial_ids), "started trial ledger must match every reported trial exactly")
    cells_by_id = _cell_index(report, errors)
    trials_by_id: dict[str, Mapping[str, Any]] = {str(row.get("trial_id")): row for row in trials}
    for trial in trials:
        cell = cells_by_id.get(str(trial.get("cell_id")), {})
        allow_safety_rejection = (
            allow_discovery_safety_rejections
            and trial.get("arm") == "candidate"
            and cell.get("campaign_step") == "discovery"
            and cell.get("status") == "FAIL"
        )
        _validate_trial_common(
            trial,
            report,
            errors,
            allow_safety_rejection=allow_safety_rejection,
        )
        _add(errors, isinstance(trial.get("run_id"), str) and str(trial.get("run_id")).startswith(f"{invocation_run_id}-"), f"trial {trial.get('trial_id', 'MISSING')} run id is not attributable to this invocation")
        _add(errors, trial.get("ownership_id") == trial.get("run_id"), f"trial {trial.get('trial_id', 'MISSING')} ownership id must equal its run id")

    pairs_by_cell = _validate_pairs(report, trials_by_id, cells_by_id, errors)
    for cell_id, pairs in pairs_by_cell.items():
        _add(errors, cell_id in cells_by_id, f"pairs reference unknown cell {cell_id}")
        if cell_id in cells_by_id:
            required = cells_by_id[cell_id].get("required_pairs")
            _add(errors, isinstance(required, int) and len(pairs) >= required, f"cell {cell_id} has fewer pairs than declared")
    for trial in trials:
        _add(errors, str(trial.get("cell_id")) in cells_by_id, f"trial {trial.get('trial_id', 'MISSING')} references an unknown cell")
        _validate_source_categories(
            trial,
            experiment_kind=kind,
            cell=cells_by_id.get(str(trial.get("cell_id"))),
            errors=errors,
        )
    return trials_by_id, cells_by_id, pairs_by_cell


def validate_report(
    report: Mapping[str, Any],
    *,
    expected_kind: str | None = None,
    expected_invocation_run_id: str | None = None,
) -> list[str]:
    """Validate M2 schema, pairing, estimators, budgets, and safety semantics."""
    errors = _validate_required_shape(report)
    kind = report.get("experiment_kind")
    if expected_kind is not None:
        _add(errors, kind == expected_kind, f"report experiment_kind must be {expected_kind!r}")
    invocation_run_id = report.get("invocation_run_id")
    if expected_invocation_run_id is not None:
        _add(errors, invocation_run_id == expected_invocation_run_id, "report invocation_run_id does not match this Gate invocation")
    _add(errors, report.get("campaign_id") == invocation_run_id, "campaign_id must equal invocation_run_id")
    _add(errors, report.get("real_valkey") is True, "real admission report is not real Valkey")
    _add(errors, report.get("execution_mode") == "valkey-real", "real admission report execution_mode is not valkey-real")
    _add(errors, report.get("invalid_samples") == [], "invalid samples are present; they cannot be replaced or ignored")
    _add(errors, report.get("errors") == [], "report contains producer errors")
    digest = report.get("report_digest")
    try:
        expected_digest = report_digest(report)
    except (TypeError, ValueError):
        expected_digest = ""
        errors.append("report is not canonical finite JSON")
    _add(errors, digest == expected_digest, "report_digest does not match canonical report content")
    _validate_protocol(report, errors)
    _validate_criterion_results(report, errors)

    trials_by_id, cells_by_id, pairs_by_cell = _validate_trials_and_pairs(report, errors)

    if kind == "formation":
        _validate_formation(report, trials_by_id, pairs_by_cell, cells_by_id, errors)
    elif kind == "failover":
        _validate_failover(report, trials_by_id, pairs_by_cell, cells_by_id, errors)
    elif kind == "stability":
        _validate_stability(report, trials_by_id, pairs_by_cell, cells_by_id, errors)
    else:
        errors.append(f"unsupported experiment_kind {kind!r}")
    if not errors:
        _add(errors, report.get("status") == "PASS", "fully valid report status must be PASS")
    return list(dict.fromkeys(errors))


def validate_discovery_campaign(
    report: Mapping[str, Any],
    *,
    expected_kind: str,
    expected_invocation_run_id: str,
    allow_legacy_formation_screen: bool = False,
) -> list[str]:
    """Validate one selection-only exact-50 discovery campaign."""
    errors: list[str] = []
    required = {
        "campaign_id",
        "invocation_run_id",
        "experiment_kind",
        "status",
        "real_valkey",
        "execution_mode",
        "baseline",
        "candidates",
        "current_defaults",
        "protocol",
        "started_trial_ids",
        "trials",
        "pairs",
        "cells",
        "invalid_samples",
        "source_refs",
        "errors",
    }
    legacy_formation_screen = (
        allow_legacy_formation_screen
        and expected_kind == "formation"
        and report.get("candidate_screen_version") is None
    )
    if expected_kind == "formation":
        allowed_fields = (
            {frozenset(required)}
            if legacy_formation_screen
            else {frozenset(required | {"candidate_screen_version"})}
        )
    else:
        allowed_fields = {
            frozenset(required),
            frozenset(required | {"candidate_screen_version"}),
        }
    _add(errors, frozenset(report) in allowed_fields, "discovery campaign fields are incomplete or unexpected")
    _add(errors, expected_kind in {"formation", "failover"}, "discovery campaign kind is unsupported")
    _add(errors, report.get("experiment_kind") == expected_kind, "discovery campaign kind does not match")
    _add(errors, report.get("campaign_id") == expected_invocation_run_id, "discovery campaign id does not match this invocation")
    _add(errors, report.get("invocation_run_id") == expected_invocation_run_id, "discovery invocation id does not match")
    _add(errors, report.get("real_valkey") is True, "discovery campaign is not real Valkey")
    _add(errors, report.get("execution_mode") == "valkey-real", "discovery campaign execution mode is not valkey-real")
    _add(errors, report.get("invalid_samples") == [], "discovery campaign contains invalid samples")
    _add(errors, report.get("errors") == [], "discovery campaign contains producer errors")
    _validate_protocol(report, errors)

    trials_by_id, cells_by_id, pairs_by_cell = _validate_trials_and_pairs(
        report,
        errors,
        allow_discovery_safety_rejections=True,
    )
    cells = list(cells_by_id.values())
    _add(errors, bool(cells) and all(cell.get("campaign_step") == "discovery" for cell in cells), "discovery campaign contains a non-discovery cell")
    for cell in cells:
        cell_id = str(cell.get("cell_id"))
        _add(errors, cell.get("required_pairs") == 1, f"discovery cell {cell_id} must require exactly one pair")
        _add(errors, len(pairs_by_cell.get(cell_id, [])) == 1, f"discovery cell {cell_id} must contain exactly one pair")

    if expected_kind == "formation":
        _validate_formation_discovery(
            report,
            trials_by_id,
            pairs_by_cell,
            cells_by_id,
            errors,
            require_selected=False,
            allow_legacy_screen=legacy_formation_screen,
        )
        _validate_formation_trials(trials_by_id.values(), errors)
    elif expected_kind == "failover":
        _validate_failover_discovery(
            report,
            trials_by_id,
            pairs_by_cell,
            cells_by_id,
            errors,
            require_selected=False,
        )
        physical_fault_ids: set[str] = set()
        for trial in trials_by_id.values():
            cell = cells_by_id.get(str(trial.get("cell_id")), {})
            _validate_marker_order(trial, FAILOVER_MARKERS, errors)
            _validate_fault(trial, cell, physical_fault_ids, errors)
            _validate_failover_intervals(trial, errors)
    if not errors:
        _add(errors, report.get("status") == "PASS", "valid discovery campaign status must be PASS")
    return list(dict.fromkeys(errors))


def _safe_source_path(artifacts_dir: Path, relative: Any) -> tuple[Path | None, str | None]:
    if not isinstance(relative, str) or not relative:
        return None, "source path is not non-empty text"
    candidate_path = Path(relative)
    lowered = {part.lower() for part in candidate_path.parts}
    if candidate_path.is_absolute() or ".." in candidate_path.parts:
        return None, f"source path escapes the current artifact directory: {relative!r}"
    if lowered.intersection({"loop_evidence", "fixtures", "fixture", "historical", "retained"}):
        return None, f"source path names forbidden non-current evidence: {relative!r}"
    root = artifacts_dir.resolve()
    if {part.lower() for part in root.parts}.intersection(FORBIDDEN_EVIDENCE_PATH_PARTS):
        return None, "artifacts directory names forbidden fixture, historical, retained, or loop evidence"
    candidate = (root / candidate_path).resolve()
    if candidate == root or not candidate.is_relative_to(root):
        return None, f"source path escapes the current artifact directory: {relative!r}"
    return candidate, None


def _load_bound_json_source(
    ref: Mapping[str, Any],
    *,
    artifacts_dir: Path,
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    path, path_error = _safe_source_path(artifacts_dir, ref.get("path"))
    if path_error:
        errors.append(f"{label}: {path_error}")
        return None
    expected = ref.get("sha256")
    if (
        path is None
        or not path.is_file()
        or path.is_symlink()
        or not isinstance(expected, str)
        or SHA256_RE.fullmatch(expected) is None
        or _file_digest(path) != expected
    ):
        errors.append(f"{label} is missing or not digest-bound")
        return None
    try:
        if path.name.endswith(".json.gz"):
            with gzip.open(path, mode="rt", encoding="utf-8") as handle:
                value = json.load(handle)
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    if not value:
        errors.append(f"{label} must contain a non-empty JSON object")
        return None
    return value


def _load_bound_jsonl_source(
    ref: Mapping[str, Any],
    *,
    artifacts_dir: Path,
    label: str,
    errors: list[str],
) -> list[dict[str, Any]] | None:
    path, path_error = _safe_source_path(artifacts_dir, ref.get("path"))
    expected = ref.get("sha256")
    if path_error:
        errors.append(f"{label}: {path_error}")
        return None
    if (
        path is None
        or not path.is_file()
        or path.is_symlink()
        or not isinstance(expected, str)
        or SHA256_RE.fullmatch(expected) is None
        or _file_digest(path) != expected
    ):
        errors.append(f"{label} is missing or not digest-bound")
        return None
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, UnicodeError) as exc:
        errors.append(f"{label} is not readable UTF-8: {exc}")
        return None
    if not lines:
        errors.append(f"{label} must contain at least one JSONL row")
        return None
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{label} line {index} is not valid JSON: {exc}")
            return None
        if not isinstance(value, dict) or not value:
            errors.append(f"{label} line {index} must contain a non-empty JSON object")
            return None
        rows.append(value)
    return rows


def _same_number(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return (
        left_number is not None
        and right_number is not None
        and math.isclose(left_number, right_number, rel_tol=0, abs_tol=tolerance)
    )


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@lru_cache(maxsize=1)
def _current_product_digest() -> str:
    source_root = str(ROOT / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    from valkey_scale_lab.gates.real import product_tree_digest

    return str(product_tree_digest(ROOT))


def _current_formation_strategy() -> str:
    source_root = str(ROOT / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    from valkey_scale_lab.runtime.docker_runtime import CLUSTER_CREATE_STRATEGY_DEFAULT

    return str(CLUSTER_CREATE_STRATEGY_DEFAULT)


def _validate_provenance_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    report: Mapping[str, Any],
    refs_by_category: Mapping[str, list[dict[str, Any]]],
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    summary = _object(trial.get("provenance"))
    _add(errors, document == summary, f"trial {trial_id} provenance source does not exactly match its summary")
    _add(
        errors,
        document.get("definition_digest")
        == _canonical_digest({"mode": report.get("experiment_kind"), "protocol": report.get("protocol")}),
        f"trial {trial_id} provenance definition digest is not derived from this report",
    )
    command_refs = refs_by_category.get("command_log", [])
    _add(
        errors,
        len(command_refs) == 1 and document.get("command_digest") == command_refs[0].get("sha256"),
        f"trial {trial_id} provenance command digest does not bind the command source",
    )
    captured = {
        category: rows[0].get("sha256")
        for category, rows in refs_by_category.items()
        if category != "provenance" and len(rows) == 1
    }
    _add(
        errors,
        document.get("capture_digest") == _canonical_digest(captured),
        f"trial {trial_id} provenance capture digest does not bind the raw source set",
    )
    _add(
        errors,
        document.get("product_digest") == _current_product_digest(),
        f"trial {trial_id} provenance product digest does not match the current product tree",
    )
    scale = trial.get("scale")
    config_path = ROOT / "templates" / "configs" / f"scale_{scale}.yaml"
    _add(
        errors,
        scale in {50, 100, 200}
        and config_path.is_file()
        and document.get("configuration_digest") == _file_digest(config_path),
        f"trial {trial_id} provenance configuration digest does not match its exact-scale config",
    )


def _validate_timeline_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    errors: list[str],
) -> None:
    source_root = str(ROOT / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    from valkey_scale_lab.runtime.setup_timeline import (
        REQUIRED_M2_SETUP_EVENTS,
        validate_setup_timeline_artifact,
        validate_setup_timeline_events,
    )

    trial_id = trial.get("trial_id", "MISSING")
    schema = load_json(SETUP_TIMELINE_SCHEMA_PATH)
    for message in validate(document, schema):
        errors.append(f"trial {trial_id} timeline evidence: {message}")
    for message in validate_setup_timeline_artifact(dict(document)):
        errors.append(f"trial {trial_id} timeline evidence: {message}")
    events = [_object(value) for value in _array(document.get("events"))]
    for message in validate_setup_timeline_events(events, required_names=REQUIRED_M2_SETUP_EVENTS):
        errors.append(f"trial {trial_id} timeline evidence: {message}")
    _add(errors, document.get("status") == "PASS", f"trial {trial_id} setup timeline did not PASS")
    _add(errors, document.get("run_id") == trial.get("run_id"), f"trial {trial_id} setup timeline run id does not match")
    _add(errors, document.get("node_count") == trial.get("scale"), f"trial {trial_id} setup timeline node count does not match")
    _add(errors, document.get("profile_id") == f"exact-{trial.get('scale')}", f"trial {trial_id} setup timeline profile is not exact")
    _add(errors, document.get("errors") == [], f"trial {trial_id} setup timeline reports errors")
    total = _number(document.get("setup_timeline_total_seconds"))
    wall = _number(document.get("setup_command_wall_seconds"))
    unexplained = _number(document.get("setup_timeline_unexplained_seconds"))
    segments = [_object(value) for value in _array(document.get("segments"))]
    segment_total = sum(
        float(segment["duration_seconds"])
        for segment in segments
        if isinstance(segment, dict) and _number(segment.get("duration_seconds")) is not None
    )
    _add(errors, total is not None and math.isclose(total, segment_total, rel_tol=0, abs_tol=1e-6), f"trial {trial_id} setup timeline total is not derived from its segments")
    _add(errors, wall is not None and total is not None and math.isclose(wall, total, rel_tol=0, abs_tol=1e-6), f"trial {trial_id} setup timeline has unexplained wall time")
    _add(errors, unexplained == 0.0 and trial.get("unexplained_seconds") == 0.0, f"trial {trial_id} setup timeline has unexplained wall time")
    wall_source = _object(document.get("setup_command_wall_source"))
    wrapper_start = _number(wall_source.get("started_at_monotonic"))
    wrapper_end = _number(wall_source.get("ended_at_monotonic"))
    event_times = [_number(event.get("at_monotonic")) for event in events]
    _add(
        errors,
        wall_source.get("status") == "PASS"
        and wall_source.get("clock") == "monotonic"
        and wrapper_start is not None
        and wrapper_end is not None
        and wrapper_end >= wrapper_start
        and wall is not None
        and _same_number(wall, wrapper_end - wrapper_start)
        and bool(segments)
        and _same_number(segments[0].get("start_monotonic"), wrapper_start)
        and _same_number(segments[-1].get("end_monotonic"), wrapper_end)
        and all(value is not None and wrapper_start <= value <= wrapper_end for value in event_times),
        f"trial {trial_id} setup timeline is not bounded by the observed monotonic wrapper",
    )

    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_name[str(event.get("name"))].append(event)
    markers = _object(trial.get("monotonic_markers"))
    for name in REQUIRED_M2_SETUP_EVENTS:
        observed = by_name.get(name, [])
        _add(errors, len(observed) == 1, f"trial {trial_id} setup timeline must contain exactly one {name} event")
        if len(observed) == 1:
            _add(
                errors,
                _same_number(observed[0].get("at_monotonic"), markers.get(name)),
                f"trial {trial_id} marker {name} does not match setup timeline source",
            )
    start = _number(markers.get("last_process_ping"))
    end = _number(markers.get("data_path_probe"))
    formation = _number(_object(trial.get("derived_intervals")).get("formation_seconds"))
    _add(
        errors,
        start is not None
        and end is not None
        and formation is not None
        and math.isclose(formation, end - start, rel_tol=0, abs_tol=1e-6),
        f"trial {trial_id} formation interval is not bound to setup timeline endpoints",
    )


def _expand_resource_directional_links(
    document: Mapping[str, Any],
    *,
    trial_id: Any,
    errors: list[str],
) -> dict[str, Any]:
    expanded = dict(document)
    raw_entries = expanded.pop("directional_cluster_links_dictionary", None)
    entries = raw_entries if isinstance(raw_entries, list) else []
    links_by_digest: dict[str, list[Any]] = {}
    declared_digests: list[str] = []
    _add(
        errors,
        isinstance(raw_entries, list) and bool(raw_entries),
        f"trial {trial_id} resource directional CLUSTER LINKS dictionary is missing",
    )
    link_fields = {
        "direction",
        "node_id",
        "create_time",
        "events",
        "send_buffer_allocated",
        "send_buffer_used",
    }
    for index, raw_entry in enumerate(entries, start=1):
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        digest = entry.get("sha256")
        links = entry.get("directional_cluster_links")
        try:
            canonical_digest = (
                _canonical_digest(links)
                if isinstance(links, list)
                else None
            )
        except (TypeError, ValueError):
            canonical_digest = None
        links_valid = isinstance(links, list) and all(
            isinstance(link, dict)
            and set(link) == link_fields
            and link.get("direction") in {"to", "from"}
            and isinstance(link.get("node_id"), str)
            and len(link["node_id"]) == 40
            and all(character in "0123456789abcdef" for character in link["node_id"].lower())
            and isinstance(link.get("create_time"), int)
            and not isinstance(link.get("create_time"), bool)
            and link["create_time"] >= 0
            and isinstance(link.get("events"), str)
            and all(event in {"r", "w"} for event in link["events"])
            and len(set(link["events"])) == len(link["events"])
            and isinstance(link.get("send_buffer_allocated"), int)
            and not isinstance(link.get("send_buffer_allocated"), bool)
            and link["send_buffer_allocated"] >= 0
            and isinstance(link.get("send_buffer_used"), int)
            and not isinstance(link.get("send_buffer_used"), bool)
            and link["send_buffer_used"] >= 0
            for link in (links if isinstance(links, list) else [])
        )
        entry_valid = (
            isinstance(raw_entry, dict)
            and set(raw_entry) == {"sha256", "directional_cluster_links"}
            and isinstance(digest, str)
            and SHA256_RE.fullmatch(digest) is not None
            and links_valid
            and canonical_digest == digest
        )
        _add(
            errors,
            entry_valid,
            f"trial {trial_id} resource directional CLUSTER LINKS dictionary entry {index} is invalid",
        )
        if isinstance(digest, str):
            declared_digests.append(digest)
        if entry_valid and digest not in links_by_digest:
            links_by_digest[digest] = links
    _add(
        errors,
        len(declared_digests) == len(entries)
        and _all_unique(declared_digests)
        and len(links_by_digest) == len(entries),
        f"trial {trial_id} resource directional CLUSTER LINKS dictionary contains duplicate entries",
    )

    referenced_digests: set[str] = set()
    process_count = 0
    expanded_samples: list[Any] = []
    for sample in _array(document.get("samples")):
        if not isinstance(sample, dict):
            expanded_samples.append(sample)
            continue
        sample_row = dict(sample)
        expanded_nodehosts: list[Any] = []
        for nodehost in _array(sample.get("nodehosts")):
            if not isinstance(nodehost, dict):
                expanded_nodehosts.append(nodehost)
                continue
            nodehost_row = dict(nodehost)
            expanded_processes: list[Any] = []
            for process in _array(nodehost.get("processes")):
                if not isinstance(process, dict):
                    expanded_processes.append(process)
                    continue
                process_row = dict(process)
                process_count += 1
                digest = process_row.get("directional_cluster_links_sha256")
                _add(
                    errors,
                    isinstance(process, dict)
                    and "directional_cluster_links" not in process,
                    f"trial {trial_id} resource process contains inline directional CLUSTER LINKS",
                )
                ref_valid = (
                    isinstance(digest, str)
                    and SHA256_RE.fullmatch(digest) is not None
                    and digest in links_by_digest
                )
                _add(
                    errors,
                    ref_valid,
                    f"trial {trial_id} resource process directional CLUSTER LINKS reference is missing or invalid",
                )
                if isinstance(digest, str):
                    referenced_digests.add(digest)
                if ref_valid:
                    process_row.pop("directional_cluster_links_sha256", None)
                    process_row["directional_cluster_links"] = links_by_digest[digest]
                expanded_processes.append(process_row)
            if isinstance(nodehost.get("processes"), list):
                nodehost_row["processes"] = expanded_processes
            expanded_nodehosts.append(nodehost_row)
        if isinstance(sample.get("nodehosts"), list):
            sample_row["nodehosts"] = expanded_nodehosts
        expanded_samples.append(sample_row)
    if isinstance(document.get("samples"), list):
        expanded["samples"] = expanded_samples
    _add(
        errors,
        process_count > 0 and set(links_by_digest) == referenced_digests,
        f"trial {trial_id} resource directional CLUSTER LINKS dictionary has unreferenced or unknown entries",
    )
    return expanded


def _validate_resource_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    *,
    fault_trial: bool,
    allow_initial_membership_transitions: bool,
    state_document: Mapping[str, Any] | None,
    errors: list[str],
) -> dict[str, Any]:
    trial_id = trial.get("trial_id", "MISSING")
    summary = _object(trial.get("resource_window"))
    coverage = _object(document.get("coverage"))
    raw_metrics = _object(document.get("metrics"))
    ownership = _object(document.get("ownership"))
    state_nodes = [_object(row) for row in _array(_object(state_document).get("nodes"))]
    state_nodehosts = [_object(row) for row in _array(_object(state_document).get("nodehosts"))]
    expected_samples = coverage.get("expected_sample_count")
    expanded_document = _expand_resource_directional_links(
        document,
        trial_id=trial_id,
        errors=errors,
    )
    recomputed = validate_and_aggregate_m2_resource_samples(
        expanded_document,
        allow_initial_membership_transitions=allow_initial_membership_transitions,
    )
    recomputed_metrics = _object(recomputed.get("metrics"))
    recomputed_coverage = _object(recomputed.get("coverage"))
    _add(errors, document.get("status") == "PASS", f"trial {trial_id} resource source did not PASS")
    _add(errors, document.get("artifact_type") == "m2_resource_window", f"trial {trial_id} resource source type is invalid")
    _add(errors, document.get("errors") == [], f"trial {trial_id} resource source reports errors")
    _add(errors, coverage.get("complete") is True, f"trial {trial_id} resource source coverage is incomplete")
    _add(
        errors,
        isinstance(expected_samples, int)
        and not isinstance(expected_samples, bool)
        and expected_samples > 0
        and coverage.get("observed_sample_count") == expected_samples,
        f"trial {trial_id} resource source sample coverage is incomplete",
    )
    _add(errors, coverage.get("process_count") == trial.get("scale"), f"trial {trial_id} resource source process coverage is not exact")
    _add(errors, ownership.get("ownership_ids") == [trial.get("ownership_id")], f"trial {trial_id} resource source ownership does not match")
    state_pids = sorted(
        row["pid"]
        for row in state_nodes
        if isinstance(row.get("pid"), int) and not isinstance(row.get("pid"), bool)
    )
    state_ports = sorted(
        row["client_port"]
        for row in state_nodes
        if isinstance(row.get("client_port"), int) and not isinstance(row.get("client_port"), bool)
    )
    state_container_ids = sorted(
        {
            str(row["container_id"])
            for row in (*state_nodehosts, *state_nodes)
            if isinstance(row.get("container_id"), str) and row.get("container_id")
        }
    )
    ownership_pids = _array(ownership.get("pids"))
    ownership_ports = _array(ownership.get("client_ports"))
    ownership_containers = _array(ownership.get("container_ids"))
    _add(
        errors,
        state_document is not None
        and all(isinstance(value, int) and not isinstance(value, bool) for value in ownership_pids)
        and all(isinstance(value, int) and not isinstance(value, bool) for value in ownership_ports)
        and all(isinstance(value, str) for value in ownership_containers)
        and sorted(ownership_pids) == state_pids
        and sorted(ownership_ports) == state_ports
        and sorted(ownership_containers) == state_container_ids,
        f"trial {trial_id} resource ownership is not bound to the runtime state",
    )
    _add(
        errors,
        recomputed.get("status") == "PASS"
        and recomputed.get("errors") == []
        and recomputed_coverage.get("complete") is True
        and recomputed_coverage.get("process_count") == trial.get("scale"),
        f"trial {trial_id} raw resource samples are incomplete or invalid",
    )
    _add(errors, _same_number(document.get("duration_seconds"), summary.get("duration_seconds")), f"trial {trial_id} resource duration does not match its summary")
    for metric in (*RESOURCE_METRICS, "cluster_link_errors", "buffer_overflows"):
        _add(
            errors,
            _same_number(raw_metrics.get(metric), recomputed_metrics.get(metric))
            and _same_number(recomputed_metrics.get(metric), summary.get(metric)),
            f"trial {trial_id} resource metric {metric} is not raw-derived",
        )
    if fault_trial:
        target_rows = [_object(target) for target in _array(_object(trial.get("fault")).get("targets"))]
        state_by_logical = {
            str(node.get("logical_id")): node
            for node in state_nodes
            if isinstance(node.get("logical_id"), str) and node.get("logical_id")
        }
        target_processes: set[tuple[str, str, int]] = set()
        targets_bound_to_state = bool(target_rows)
        for target in target_rows:
            node = state_by_logical.get(str(target.get("logical_id")))
            pid = target.get("pid")
            if (
                node is None
                or not isinstance(pid, int)
                or isinstance(pid, bool)
                or node.get("pid") != pid
                or not isinstance(node.get("nodehost_id"), str)
                or not node.get("nodehost_id")
                or not isinstance(node.get("container_id"), str)
                or not node.get("container_id")
            ):
                targets_bound_to_state = False
                continue
            target_processes.add(
                (str(node["nodehost_id"]), str(node["container_id"]), int(pid))
            )

        def process_identities(value: Any) -> tuple[set[tuple[str, str, int]], bool]:
            rows = _array(value)
            identities: set[tuple[str, str, int]] = set()
            valid = bool(rows)
            for row in rows:
                item = _object(row)
                nodehost_id = item.get("nodehost_id")
                container_id = item.get("container_id")
                pid = item.get("pid")
                if (
                    not isinstance(nodehost_id, str)
                    or not nodehost_id
                    or not isinstance(container_id, str)
                    or not container_id
                    or not isinstance(pid, int)
                    or isinstance(pid, bool)
                    or pid <= 0
                ):
                    valid = False
                    continue
                identities.add((nodehost_id, container_id, pid))
            return identities, valid and len(identities) == len(rows)

        capture = _object(document.get("fault_target_capture"))
        recomputed_capture = _object(recomputed.get("fault_target_capture"))
        expected, expected_valid = process_identities(capture.get("expected_gone_processes"))
        observed, observed_valid = process_identities(capture.get("observed_gone_processes"))
        captured, captured_valid = process_identities(capture.get("captured_before_gone_processes"))
        _add(
            errors,
            targets_bound_to_state
            and len(target_processes) == len(target_rows)
            and expected_valid
            and observed_valid
            and captured_valid
            and expected == observed == captured == target_processes
            and capture.get("binding_status") == "PASS",
            f"trial {trial_id} resource source does not bind every SIGKILL target",
        )
        recomputed_expected, recomputed_expected_valid = process_identities(
            recomputed_capture.get("expected_gone_processes")
        )
        recomputed_observed, recomputed_observed_valid = process_identities(
            recomputed_capture.get("observed_gone_processes")
        )
        recomputed_captured, recomputed_captured_valid = process_identities(
            recomputed_capture.get("captured_before_gone_processes")
        )
        _add(
            errors,
            recomputed_expected_valid
            and recomputed_observed_valid
            and recomputed_captured_valid
            and recomputed_expected == recomputed_observed == recomputed_captured == target_processes
            and recomputed_capture.get("binding_status") == "PASS",
            f"trial {trial_id} SIGKILL resource binding is not raw-derived",
        )
        samples = [_object(value) for value in _array(document.get("samples"))]
        barrier = _number(_object(trial.get("monotonic_markers")).get("sigkill_barrier"))
        pre_end = _number(samples[0].get("ended_at_monotonic_seconds")) if samples else None
        window_start = _number(samples[1].get("started_at_monotonic_seconds")) if len(samples) > 1 else None
        _add(
            errors,
            barrier is not None
            and pre_end is not None
            and window_start is not None
            and samples[0].get("sample_phase") == "pre_barrier"
            and pre_end <= barrier <= window_start,
            f"trial {trial_id} resource window is not synchronized to the SIGKILL barrier",
        )
    elif "soak" not in str(trial.get("cell_id", "")):
        samples = [_object(value) for value in _array(document.get("samples"))]
        first_end = _number(samples[0].get("ended_at_monotonic_seconds")) if samples else None
        first_membership = _number(_object(trial.get("monotonic_markers")).get("first_membership_command"))
        _add(
            errors,
            first_end is not None and first_membership is not None and first_end <= first_membership,
            f"trial {trial_id} resource window did not capture every owned process before cluster formation",
        )
    return {
        "duration_seconds": document.get("duration_seconds"),
        "interval_seconds": document.get("interval_seconds"),
        "safety_metrics": {
            field: recomputed_metrics.get(field)
            for field in ("cluster_link_errors", "buffer_overflows")
        },
        "coverage": {
            field: recomputed_coverage.get(field)
            for field in (
                "expected_sample_count",
                "observed_sample_count",
                "nodehost_count",
                "process_count",
                "actual_window_span_seconds",
                "sampling_envelope_span_seconds",
            )
        },
    }


def _validate_equal_resource_window_facts(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    allow_candidate_safety_failure: bool = False,
) -> list[str]:
    errors: list[str] = []
    for arm_name, facts in (("baseline", baseline), ("candidate", candidate)):
        safety_metrics = _object(facts.get("safety_metrics"))
        for field in ("cluster_link_errors", "buffer_overflows"):
            value = safety_metrics.get(field)
            if value != 0 and not (
                arm_name == "candidate" and allow_candidate_safety_failure
            ):
                errors.append(f"{arm_name} metric {field} must be zero")
    for field in ("duration_seconds", "interval_seconds"):
        left = baseline.get(field)
        right = candidate.get(field)
        if not _same_number(left, right):
            errors.append(
                f"resource windows have unequal {field}: "
                f"baseline={left!r} candidate={right!r}"
            )

    baseline_coverage = _object(baseline.get("coverage"))
    candidate_coverage = _object(candidate.get("coverage"))
    for field in (
        "expected_sample_count",
        "observed_sample_count",
        "nodehost_count",
        "process_count",
    ):
        left = baseline_coverage.get(field, "MISSING")
        right = candidate_coverage.get(field, "MISSING")
        if left != right:
            errors.append(
                f"resource windows have unequal coverage {field}: "
                f"baseline={left!r} candidate={right!r}"
            )

    interval = _number(baseline.get("interval_seconds"))
    equality_tolerance = (
        min(0.5, max(0.001, float(interval) * 0.1))
        if interval is not None and interval > 0
        else 0.0
    )
    for field in (
        "actual_window_span_seconds",
        "sampling_envelope_span_seconds",
    ):
        left = _number(baseline_coverage.get(field))
        right = _number(candidate_coverage.get(field))
        if (
            left is None
            or right is None
            or abs(left - right) > equality_tolerance + 1e-6
        ):
            errors.append(
                f"resource windows have unequal {field}: "
                f"baseline={baseline_coverage.get(field, 'MISSING')!r} "
                f"candidate={candidate_coverage.get(field, 'MISSING')!r}"
            )
    return errors


def _histogram_nearest_rank(
    histogram: Any,
    percentile: float,
) -> tuple[float | None, int, bool]:
    if (
        not isinstance(histogram, dict)
        or set(histogram) != {"schema_version", "buckets"}
        or histogram.get("schema_version") != LATENCY_HISTOGRAM_SCHEMA_VERSION
    ):
        return None, 0, False
    rows = histogram.get("buckets")
    if not isinstance(rows, list) or len(rows) > LATENCY_HISTOGRAM_BUCKET_LIMIT:
        return None, 0, False
    parsed: list[tuple[int, int]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"index", "count"}:
            return None, 0, False
        bucket_index = row.get("index")
        count = row.get("count")
        if (
            not isinstance(bucket_index, int)
            or isinstance(bucket_index, bool)
            or not 0 <= bucket_index <= LATENCY_HISTOGRAM_MAX_INDEX
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count <= 0
        ):
            return None, 0, False
        parsed.append((bucket_index, count))
    indices = [bucket_index for bucket_index, _count in parsed]
    if not parsed or indices != sorted(indices) or len(set(indices)) != len(indices):
        return None, 0, False
    total = sum(count for _bucket_index, count in parsed)
    rank = math.ceil(percentile * total)
    cumulative = 0
    for bucket_index, count in parsed:
        cumulative += count
        if cumulative >= rank:
            _lower, upper = _latency_bucket_bounds(bucket_index)
            return upper, total, True
    return None, 0, False


def _validate_workload_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    *,
    fault_trial: bool,
    topology_facts: Mapping[str, Any] | None = None,
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    summary = _object(trial.get("workload"))
    raw_errors = document.get("errors")
    error_count = document.get("error_count", len(raw_errors) if isinstance(raw_errors, list) else None)
    _add(errors, document.get("status") == "PASS", f"trial {trial_id} workload source did not PASS")
    _add(errors, isinstance(raw_errors, list), f"trial {trial_id} workload source errors are not an array")
    _add(
        errors,
        isinstance(error_count, int)
        and not isinstance(error_count, bool)
        and error_count >= 0
        and isinstance(raw_errors, list)
        and error_count == len(raw_errors)
        and error_count == summary.get("errors"),
        f"trial {trial_id} workload error count does not match its summary",
    )
    if not fault_trial:
        _add(errors, raw_errors == [] and error_count == 0, f"trial {trial_id} steady-state workload source reports errors")
    if "timeout_count" in document:
        timeout_count = document.get("timeout_count")
        _add(
            errors,
            isinstance(timeout_count, int)
            and not isinstance(timeout_count, bool)
            and timeout_count >= 0
            and (fault_trial or timeout_count == 0),
            f"trial {trial_id} workload timeout count is invalid",
        )
    for metric in (
        "duration_seconds",
        "set_throughput_ops_per_second",
        "p99_latency_ms",
        "affected_shard_max_interval_ms",
    ):
        _add(errors, _same_number(document.get(metric), summary.get(metric)), f"trial {trial_id} workload metric {metric} does not match its summary")
    for field in ("persistent_cluster_client", "per_operation_process_spawn", "stable_shards"):
        _add(errors, document.get(field) == summary.get(field), f"trial {trial_id} workload field {field} does not match its summary")
    if not fault_trial:
        _add(
            errors,
            document.get("latency_operation") == "SET",
            f"trial {trial_id} steady workload latency histogram is not identified as SET latency",
        )
        started = _number(document.get("started_at_monotonic"))
        ended = _number(document.get("ended_at_monotonic"))
        requested = _number(document.get("requested_duration_seconds"))
        observed = ended - started if started is not None and ended is not None else None
        histogram_p99, histogram_count, histogram_valid = _histogram_nearest_rank(
            document.get("latency_histogram"),
            0.99,
        )
        operation_count = document.get("operation_count")
        throughput = (
            histogram_count / observed
            if observed is not None and observed > 0 and histogram_count > 0
            else None
        )
        _add(
            errors,
            started is not None
            and ended is not None
            and observed is not None
            and observed > 0
            and requested is not None
            and requested > 0
            and observed >= requested - 1e-6
            and _same_number(document.get("duration_seconds"), observed, tolerance=1e-6),
            f"trial {trial_id} steady workload does not cover its raw monotonic window",
        )
        _add(
            errors,
            isinstance(operation_count, int)
            and not isinstance(operation_count, bool)
            and operation_count == histogram_count
            and operation_count > 0,
            f"trial {trial_id} steady workload operation count is not histogram-derived",
        )
        _add(
            errors,
            histogram_valid,
            f"trial {trial_id} steady workload latency histogram bins are invalid",
        )
        _add(
            errors,
            histogram_p99 is not None
            and throughput is not None
            and _same_number(document.get("p99_latency_ms"), histogram_p99, tolerance=1e-6)
            and _same_number(document.get("set_throughput_ops_per_second"), throughput, tolerance=1e-6),
            f"trial {trial_id} steady workload throughput or p99 is not raw-derived",
        )
    fault = _object(trial.get("fault"))
    targets = sorted(
        (
            {
                "logical_id": str(target.get("logical_id")),
                "shard_id": str(target.get("shard_id")),
            }
            for target in _array(fault.get("targets"))
            if isinstance(target, dict)
        ),
        key=lambda row: (row["logical_id"], row["shard_id"]),
    )
    expected_workload_digest = _canonical_digest(
        {
            "value_size_bytes": document.get("value_size_bytes"),
            "persistent": document.get("persistent_cluster_client"),
            "duration": document.get("requested_duration_seconds"),
            "fault_targets": targets,
        }
    )
    _add(
        errors,
        document.get("value_size_bytes") == 512
        and _number(document.get("requested_duration_seconds")) is not None
        and _object(trial.get("provenance")).get("workload_digest") == expected_workload_digest,
        f"trial {trial_id} workload digest is not derived from the raw workload contract",
    )
    if fault_trial:
        _validate_fault_client_evidence(document, trial, errors)
    if str(trial.get("cell_id", "")).startswith("stability-") and trial.get("fault") is None:
        _validate_stability_observation(
            document.get("stability_observation"),
            trial,
            expected_baseline_roles=_object(topology_facts).get("expected_roles_by_node_id"),
            errors=errors,
        )


def _validate_fault_client_evidence(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    fault = _object(trial.get("fault"))
    markers = _object(trial.get("monotonic_markers"))
    barrier = _number(markers.get("sigkill_barrier"))
    cluster_ok = _number(markers.get("all_slots_covered_cluster_ok"))
    duration = _number(document.get("requested_duration_seconds"))
    target_shards = {
        str(target.get("shard_id"))
        for target in _array(fault.get("targets"))
        if isinstance(target, dict) and isinstance(target.get("shard_id"), str) and target.get("shard_id")
    }
    series = [_object(row) for row in _array(document.get("client_series"))]
    affected = [row for row in series if row.get("affected") is True]
    controls = [row for row in series if row.get("affected") is False]
    affected_ids = [str(row.get("shard_id")) for row in affected]
    control_ids = [str(row.get("shard_id")) for row in controls]
    declared_control_ids = _array(document.get("unaffected_control_shards"))
    _add(
        errors,
        bool(target_shards)
        and len(affected) == len(target_shards)
        and set(affected_ids) == target_shards
        and _all_unique(affected_ids),
        f"trial {trial_id} client series does not cover every affected shard exactly once",
    )
    _add(
        errors,
        bool(controls)
        and all(isinstance(row.get("shard_id"), str) and row.get("shard_id") for row in controls)
        and all(isinstance(value, str) and value for value in declared_control_ids)
        and _all_unique(control_ids)
        and _all_unique(declared_control_ids)
        and set(control_ids) == set(declared_control_ids)
        and set(control_ids).isdisjoint(target_shards),
        f"trial {trial_id} client series lacks a bound unaffected control shard",
    )
    _add(
        errors,
        barrier is not None and cluster_ok is not None and duration is not None and duration > 0,
        f"trial {trial_id} client series lacks its fault window bounds",
    )
    if barrier is None or cluster_ok is None or duration is None or duration <= 0:
        return

    window_end = barrier + duration
    attempts_by_shard: dict[str, list[dict[str, Any]]] = {}
    all_success_latencies: list[float] = []
    all_error_messages: list[str] = []
    all_error_timeouts = 0
    all_set_successes = 0
    raw_series_valid = len(series) == len(affected) + len(controls)
    for row in series:
        shard_id = row.get("shard_id")
        raw_attempt_values = row.get("attempts")
        row_valid = (
            isinstance(shard_id, str)
            and bool(shard_id)
            and shard_id not in attempts_by_shard
            and isinstance(raw_attempt_values, list)
            and bool(raw_attempt_values)
            and all(isinstance(value, dict) for value in raw_attempt_values)
        )
        parsed_attempts: list[dict[str, Any]] = []
        if isinstance(raw_attempt_values, list):
            for value in raw_attempt_values:
                sample = _object(value)
                started = _number(sample.get("started_at_monotonic"))
                completed = _number(sample.get("completed_at_monotonic"))
                set_completed = _number(sample.get("set_completed_at_monotonic"))
                get_completed = _number(sample.get("get_completed_at_monotonic"))
                latency = _number(sample.get("latency_ms"))
                set_succeeded = sample.get("set_succeeded")
                get_succeeded = sample.get("get_succeeded")
                value_matches = sample.get("value_matches")
                timed_out = sample.get("timed_out")
                error = sample.get("error")
                moved_count = sample.get("moved_count")
                ask_count = sample.get("ask_count")
                passed = (
                    set_succeeded is True
                    and get_succeeded is True
                    and value_matches is True
                    and timed_out is False
                    and error == ""
                )
                structurally_valid = (
                    started is not None
                    and completed is not None
                    and completed >= started
                    and latency is not None
                    and latency >= 0
                    and math.isclose(
                        latency,
                        (completed - started) * 1000.0,
                        rel_tol=0,
                        abs_tol=0.002001,
                    )
                    and all(
                        isinstance(sample.get(field), bool)
                        for field in (
                            "set_succeeded",
                            "get_succeeded",
                            "value_matches",
                            "timed_out",
                        )
                    )
                    and isinstance(error, str)
                    and (
                        set_completed is not None
                        or sample.get("set_completed_at_monotonic") == "MISSING"
                    )
                    and (
                        get_completed is not None
                        or sample.get("get_completed_at_monotonic") == "MISSING"
                    )
                    and (set_completed is None or started <= set_completed <= completed)
                    and (get_completed is None or started <= get_completed <= completed)
                    and (set_completed is None or get_completed is None or get_completed >= set_completed)
                    and (set_succeeded is not True or set_completed is not None)
                    and (get_succeeded is not True or get_completed is not None)
                    and (value_matches is not True or get_succeeded is True)
                    and sample.get("status") == ("PASS" if passed else "FAIL")
                    and isinstance(moved_count, int)
                    and not isinstance(moved_count, bool)
                    and moved_count >= 0
                    and isinstance(ask_count, int)
                    and not isinstance(ask_count, bool)
                    and ask_count >= 0
                )
                row_valid = row_valid and structurally_valid
                if structurally_valid:
                    parsed_attempts.append(
                        {
                            **sample,
                            "started": started,
                            "completed": completed,
                            "latency": latency,
                        }
                    )
        if isinstance(shard_id, str) and shard_id:
            attempts_by_shard[shard_id] = [
                sample
                for sample in parsed_attempts
                if barrier <= float(sample["started"]) <= window_end
            ]
        window_attempts = [
            sample
            for sample in parsed_attempts
            if barrier <= float(sample["started"]) <= window_end
        ]
        successful_latencies = [
            sample["latency"]
            for sample in window_attempts
            if sample.get("status") == "PASS"
        ]
        error_attempts = [
            sample
            for sample in window_attempts
            if sample.get("status") != "PASS"
        ]
        duplicate_raw_views = {
            "attempt_started_monotonic",
            "successful_pair_latencies_ms",
            "samples_through_stable_endpoint",
        }
        row_valid = (
            row_valid
            and duplicate_raw_views.isdisjoint(row)
            and all(
                left["started"] < right["started"]
                and left["completed"] <= right["completed"]
                for left, right in zip(parsed_attempts, parsed_attempts[1:])
            )
            and row.get("attempt_count") == len(window_attempts)
            and row.get("set_success_count")
            == sum(sample.get("set_succeeded") is True for sample in window_attempts)
            and row.get("get_success_count")
            == sum(sample.get("get_succeeded") is True for sample in window_attempts)
            and row.get("error_count") == len(error_attempts)
            and row.get("timeout_count")
            == sum(sample.get("timed_out") is True for sample in window_attempts)
            and row.get("moved_count")
            == sum(int(sample["moved_count"]) for sample in window_attempts)
            and row.get("ask_count")
            == sum(int(sample["ask_count"]) for sample in window_attempts)
        )
        _add(
            errors,
            row_valid,
            f"trial {trial_id} client shard {shard_id or 'MISSING'} raw attempts or summaries are inconsistent",
        )
        raw_series_valid = raw_series_valid and row_valid
        all_success_latencies.extend(successful_latencies)
        all_error_messages.extend(
            str(sample.get("error") or "client operation failed")
            for sample in error_attempts
        )
        all_error_timeouts += sum(
            sample.get("timed_out") is True for sample in error_attempts
        )
        all_set_successes += sum(
            sample.get("set_succeeded") is True for sample in window_attempts
        )

    raw_p99 = (
        round(nearest_rank(all_success_latencies, 0.99), 6)
        if all_success_latencies
        else None
    )
    raw_throughput = round(all_set_successes / duration, 6)
    _add(
        errors,
        raw_series_valid
        and _same_number(document.get("duration_seconds"), duration)
        and _same_number(document.get("set_throughput_ops_per_second"), raw_throughput)
        and raw_p99 is not None
        and _same_number(document.get("p99_latency_ms"), raw_p99)
        and document.get("errors") == all_error_messages
        and document.get("error_count") == len(all_error_messages)
        and document.get("timeout_count") == all_error_timeouts,
        f"trial {trial_id} fault workload throughput, p99, errors, or timeouts are not raw-derived",
    )
    cadence_rows = {
        str(row.get("shard_id")): row
        for row in (_object(value) for value in _array(document.get("per_shard")))
        if row.get("affected") is True
    }
    raw_control_cadence_rows = [
        row
        for row in (_object(value) for value in _array(document.get("per_shard")))
        if row.get("affected") is False
    ]
    control_cadence_ids = [str(row.get("shard_id")) for row in raw_control_cadence_rows]
    control_cadence_rows = {
        str(row.get("shard_id")): row for row in raw_control_cadence_rows
    }
    _add(
        errors,
        len(raw_control_cadence_rows) == len(controls)
        and _all_unique(control_cadence_ids)
        and set(control_cadence_rows) == set(control_ids),
        f"trial {trial_id} unaffected control cadence summaries are incomplete or duplicated",
    )
    stable_rows = {
        str(row.get("shard_id")): row
        for row in (_object(value) for value in _array(document.get("stable_shards")))
    }
    stable_row_ids = [
        str(row.get("shard_id"))
        for row in (_object(value) for value in _array(document.get("stable_shards")))
    ]
    _add(
        errors,
        set(stable_row_ids) == target_shards and _all_unique(stable_row_ids),
        f"trial {trial_id} stable summaries do not cover every affected shard exactly once",
    )
    recomputed_endpoints: dict[str, float] = {}
    cadence_maxima: list[float] = []
    successful_write_completions: list[float] = []
    successful_read_completions: list[float] = []
    for row in controls:
        shard_id = str(row.get("shard_id"))
        numeric_starts = [
            float(sample["started"])
            for sample in attempts_by_shard.get(shard_id, [])
        ]
        _add(
            errors,
            bool(numeric_starts)
            and all(left < right for left, right in zip(numeric_starts, numeric_starts[1:]))
            and row.get("attempt_count") == len(numeric_starts)
            and isinstance(row.get("key"), str)
            and bool(row.get("key")),
            f"trial {trial_id} unaffected control shard {shard_id} has an incomplete attempt series",
        )
        in_window = [value for value in numeric_starts if barrier <= value <= window_end]
        cadence_gaps = [max(in_window[0] - barrier, 0.0)] if in_window else []
        cadence_gaps.extend(right - left for left, right in zip(in_window, in_window[1:]))
        if in_window:
            cadence_gaps.append(max(window_end - in_window[-1], 0.0))
        maximum_ms = round(max(cadence_gaps) * 1000.0, 6) if cadence_gaps else None
        cadence = control_cadence_rows.get(shard_id, {})
        _add(
            errors,
            maximum_ms is not None
            and maximum_ms <= 100.0 + 1e-6
            and cadence.get("affected") is False
            and cadence.get("status") == "PASS"
            and cadence.get("attempt_count") == len(in_window)
            and _same_number(cadence.get("max_attempt_interval_ms"), maximum_ms),
            f"trial {trial_id} unaffected control shard {shard_id} cadence is missing, exceeds 100 ms, or is not raw-derived",
        )
    for row in affected:
        shard_id = str(row.get("shard_id"))
        numeric_starts = [
            float(sample["started"])
            for sample in attempts_by_shard.get(shard_id, [])
        ]
        _add(
            errors,
            bool(numeric_starts)
            and all(left < right for left, right in zip(numeric_starts, numeric_starts[1:]))
            and row.get("attempt_count") == len(numeric_starts),
            f"trial {trial_id} affected shard {shard_id} has an incomplete attempt series",
        )
        in_window = [value for value in numeric_starts if barrier <= value <= window_end]
        cadence_gaps = [max(in_window[0] - barrier, 0.0)] if in_window else []
        cadence_gaps.extend(right - left for left, right in zip(in_window, in_window[1:]))
        if in_window:
            cadence_gaps.append(max(window_end - in_window[-1], 0.0))
        maximum_ms = round(max(cadence_gaps) * 1000.0, 6) if cadence_gaps else None
        cadence = cadence_rows.get(shard_id, {})
        _add(
            errors,
            maximum_ms is not None
            and maximum_ms <= 100.0 + 1e-6
            and cadence.get("status") == "PASS"
            and cadence.get("attempt_count") == len(in_window)
            and _same_number(cadence.get("max_attempt_interval_ms"), maximum_ms),
            f"trial {trial_id} affected shard {shard_id} cadence is missing, exceeds 100 ms, or is not raw-derived",
        )
        if maximum_ms is not None:
            cadence_maxima.append(maximum_ms)

        samples = attempts_by_shard.get(shard_id, [])
        for sample in samples:
            set_completed = _number(sample.get("set_completed_at_monotonic"))
            get_completed = _number(sample.get("get_completed_at_monotonic"))
            if (
                float(sample["started"]) >= barrier
                and sample.get("set_succeeded") is True
                and set_completed is not None
                and set_completed >= barrier
            ):
                successful_write_completions.append(set_completed)
            if (
                float(sample["started"]) >= barrier
                and sample.get("get_succeeded") is True
                and sample.get("value_matches") is True
                and get_completed is not None
                and get_completed >= barrier
            ):
                successful_read_completions.append(get_completed)
        stable = _earliest_stable_window(samples, cluster_ok=cluster_ok)
        summary = stable_rows.get(shard_id, {})
        if stable is None:
            errors.append(f"trial {trial_id} affected shard {shard_id} has no qualifying raw stable window")
            continue
        endpoint, consecutive_pairs = stable
        recomputed_endpoints[shard_id] = endpoint
        _add(
            errors,
            _same_number(summary.get("endpoint_monotonic"), endpoint)
            and _same_number(summary.get("window_start_monotonic"), endpoint - 1.0)
            and summary.get("window_seconds") == 1
            and summary.get("consecutive_pairs") == consecutive_pairs
            and summary.get("errors") == 0
            and summary.get("timeouts") == 0
            and summary.get("earliest_qualifying") is True,
            f"trial {trial_id} affected shard {shard_id} stable summary is not the earliest raw one-second window",
        )

    _add(
        errors,
        len(cadence_maxima) == len(target_shards)
        and _same_number(document.get("affected_shard_max_interval_ms"), max(cadence_maxima, default=-1.0)),
        f"trial {trial_id} aggregate affected-shard cadence is not raw-derived",
    )
    latest = max(recomputed_endpoints.values(), default=None)
    _add(
        errors,
        len(recomputed_endpoints) == len(target_shards)
        and latest is not None
        and _same_number(markers.get("stable_client_recovery"), latest),
        f"trial {trial_id} stable recovery marker is not the latest affected-shard raw endpoint",
    )
    accumulator = _object(document.get("accumulator"))
    required_shards = _array(accumulator.get("required_shards"))
    valid_required_shards = all(isinstance(value, str) and value for value in required_shards)
    accumulator_shards = {
        str(row.get("shard_id")): row
        for row in (_object(value) for value in _array(accumulator.get("shards")))
    }
    _add(
        errors,
        accumulator.get("status") == "PASS"
        and _same_number(accumulator.get("window_ms"), 1000.0)
        and accumulator.get("min_pairs") == 10
        and _same_number(accumulator.get("max_pair_interval_ms"), 100.0)
        and valid_required_shards
        and set(required_shards) == target_shards
        and _all_unique(required_shards)
        and latest is not None
        and _same_number(accumulator.get("stable_endpoint_monotonic_ms"), latest * 1000.0)
        and all(
            shard_id in accumulator_shards
            and accumulator_shards[shard_id].get("status") == "PASS"
            and _same_number(
                accumulator_shards[shard_id].get("stable_at_monotonic_ms"),
                endpoint * 1000.0,
            )
            for shard_id, endpoint in recomputed_endpoints.items()
        ),
        f"trial {trial_id} stable accumulator is not bound to the raw client series",
    )
    first_success = _object(document.get("first_success"))
    intervals = _object(trial.get("derived_intervals"))
    for interval_name, source_name, raw_completions in (
        ("sigkill_to_first_write_seconds", "first_affected_write", successful_write_completions),
        ("sigkill_to_first_read_seconds", "first_affected_read", successful_read_completions),
    ):
        observed = _number(first_success.get(source_name))
        interval = _number(intervals.get(interval_name))
        recomputed = min(raw_completions, default=None)
        _add(
            errors,
            recomputed is not None
            and observed is not None
            and interval is not None
            and _same_number(observed, recomputed)
            and barrier <= observed <= (latest if latest is not None else window_end)
            and math.isclose(interval, observed - barrier, rel_tol=0, abs_tol=1e-6),
            f"trial {trial_id} interval {interval_name} is not bound to raw client recovery",
        )


def _earliest_stable_window(
    samples: Sequence[Mapping[str, Any]],
    *,
    cluster_ok: float,
) -> tuple[float, int] | None:
    streak: list[Mapping[str, Any]] = []
    for sample in samples:
        started = float(sample["started"])
        completed = float(sample["completed"])
        if started < cluster_ok:
            continue
        passed = (
            sample.get("set_succeeded") is True
            and sample.get("get_succeeded") is True
            and sample.get("value_matches") is True
            and sample.get("timed_out") is False
            and sample.get("error") == ""
        )
        if not passed:
            streak.clear()
            continue
        if streak and completed - float(streak[-1]["completed"]) > 0.1 + 1e-9:
            streak.clear()
        streak.append(sample)
        if len(streak) >= 10 and completed - float(streak[0]["completed"]) >= 1.0 - 1e-9:
            in_window = [row for row in streak if float(row["completed"]) >= completed - 1.0 - 1e-9]
            return round(completed, 6), len(in_window)
    return None


def _validate_stability_observation(
    raw: Any,
    trial: Mapping[str, Any],
    *,
    expected_baseline_roles: Any,
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    observation = _object(raw)
    samples = [_object(sample) for sample in _array(observation.get("samples"))]
    duration = _number(observation.get("duration_seconds"))
    interval = _number(observation.get("interval_seconds"))
    observed_duration = _number(observation.get("observed_duration_seconds"))
    expected_samples = observation.get("expected_sample_count")
    _add(errors, observation.get("artifact_type") == "m2_stability_observation", f"trial {trial_id} stability observation type is invalid")
    _add(errors, observation.get("status") == "PASS" and observation.get("errors") == [], f"trial {trial_id} stability observation did not PASS")
    _add(
        errors,
        duration is not None
        and _same_number(duration, _object(trial.get("workload")).get("duration_seconds"))
        and interval is not None
        and interval > 0
        and observed_duration is not None
        and observed_duration >= duration,
        f"trial {trial_id} stability observation does not cover the complete workload window",
    )
    _add(
        errors,
        isinstance(expected_samples, int)
        and not isinstance(expected_samples, bool)
        and expected_samples > 1
        and len(samples) == expected_samples == observation.get("observed_sample_count"),
        f"trial {trial_id} stability observation sample coverage is incomplete",
    )
    starts = [_number(sample.get("started_at_monotonic")) for sample in samples]
    _add(errors, all(value is not None for value in starts), f"trial {trial_id} stability samples lack monotonic timestamps")
    numeric_starts = [float(value) for value in starts if value is not None]
    max_gap_ms = max(
        ((right - left) * 1000.0 for left, right in zip(numeric_starts, numeric_starts[1:])),
        default=0.0,
    )
    _add(
        errors,
        all(right >= left for left, right in zip(numeric_starts, numeric_starts[1:]))
        and interval is not None
        and max_gap_ms <= interval * 1000.0 + 500.0
        and _same_number(observation.get("max_sample_interval_ms"), max_gap_ms, tolerance=1e-3),
        f"trial {trial_id} stability sample cadence is incomplete",
    )
    baseline_roles = _object(observation.get("baseline_roles"))
    rebuilt_baseline_roles = _object(expected_baseline_roles)
    _add(
        errors,
        bool(rebuilt_baseline_roles) and baseline_roles == rebuilt_baseline_roles,
        f"trial {trial_id} stability baseline roles do not match the pre-window raw topology",
    )
    expected_nodes = trial.get("scale")
    for sample in samples:
        recomputed = _recompute_stability_facts(
            [_object(probe) for probe in _array(sample.get("probes"))],
            expected_nodes=expected_nodes,
            baseline_roles=rebuilt_baseline_roles,
        )
        _add(errors, sample.get("facts") == recomputed, f"trial {trial_id} stability sample facts are not derived from raw probes")
        _add(errors, recomputed.get("status") == "PASS", f"trial {trial_id} stability sample observed an unsafe topology")


def _recompute_stability_facts(
    probes: Sequence[Mapping[str, Any]],
    *,
    expected_nodes: Any,
    baseline_roles: Mapping[str, Any],
) -> dict[str, Any]:
    unexpected_pfail: set[str] = set()
    unexpected_fail: set[str] = set()
    unexpected_promotions: set[str] = set()
    split_brain = False
    slot_loss = False
    clean = bool(probes) and isinstance(expected_nodes, int) and expected_nodes > 0
    for probe in probes:
        nodes = _object(probe.get("cluster_nodes"))
        clean = clean and (
            probe.get("status") == "PASS"
            and probe.get("cluster_state") == "ok"
            and probe.get("cluster_slots_assigned") == 16384
            and probe.get("cluster_slots_ok") == 16384
            and probe.get("cluster_known_nodes") == expected_nodes
            and len(nodes) == expected_nodes
        )
        owned_slots: set[int] = set()
        for node_id, raw_node in nodes.items():
            node = _object(raw_node)
            flags = {str(flag) for flag in _array(node.get("flags"))}
            if flags.intersection({"pfail", "fail?"}):
                unexpected_pfail.add(str(node_id))
            if "fail" in flags:
                unexpected_fail.add(str(node_id))
            if flags.intersection({"handshake", "noaddr"}) or node.get("link_state") != "connected":
                clean = False
            role = str(node.get("role"))
            if baseline_roles.get(str(node_id)) != role:
                unexpected_promotions.add(str(node_id))
            if role == "primary":
                slots = _slot_tokens(_array(node.get("slots")))
                if not slots:
                    slot_loss = True
                if owned_slots.intersection(slots):
                    split_brain = True
                owned_slots.update(slots)
        if len(owned_slots) != 16384:
            slot_loss = True
    passed = clean and not unexpected_pfail and not unexpected_fail and not unexpected_promotions and not split_brain and not slot_loss
    return {
        "status": "PASS" if passed else "FAIL",
        "unexpected_pfail_node_ids": sorted(unexpected_pfail),
        "unexpected_fail_node_ids": sorted(unexpected_fail),
        "unexpected_promotion_node_ids": sorted(unexpected_promotions),
        "split_brain": split_brain,
        "slot_loss": slot_loss,
        "clean_topology": clean,
    }


def _slot_tokens(tokens: Sequence[Any]) -> set[int]:
    slots: set[int] = set()
    for value in tokens:
        token = str(value)
        if token.startswith("["):
            continue
        if token.isdigit():
            slots.add(int(token))
        elif "-" in token:
            left, right = token.split("-", 1)
            if left.isdigit() and right.isdigit() and int(left) <= int(right):
                slots.update(range(int(left), int(right) + 1))
    return {slot for slot in slots if 0 <= slot <= 16383}


def _stable_slot_tokens(tokens: Sequence[Any]) -> bool:
    for value in tokens:
        token = str(value)
        if token.isdigit():
            if not 0 <= int(token) <= 16383:
                return False
            continue
        if "-" in token and not token.startswith("["):
            left, right = token.split("-", 1)
            if left.isdigit() and right.isdigit() and 0 <= int(left) <= int(right) <= 16383:
                continue
        return False
    return True


def _recompute_topology_facts(
    probes: Sequence[Mapping[str, Any]],
    topology_rows: Sequence[Mapping[str, Any]],
    *,
    expected_nodes: Any,
) -> dict[str, Any]:
    valid_scale = isinstance(expected_nodes, int) and not isinstance(expected_nodes, bool) and expected_nodes > 0
    expected_by_logical: dict[str, dict[str, str]] = {}
    controls_valid = valid_scale and len(topology_rows) == expected_nodes
    for row in topology_rows:
        logical_id = row.get("logical_id")
        role = row.get("role")
        shard_id = row.get("shard_id")
        valid_row = (
            isinstance(logical_id, str)
            and bool(logical_id)
            and isinstance(shard_id, str)
            and bool(shard_id)
            and role in {"primary", "replica"}
            and logical_id not in expected_by_logical
        )
        controls_valid = controls_valid and valid_row
        if valid_row:
            expected_by_logical[logical_id] = {"role": str(role), "shard_id": shard_id}

    expected_logical_ids = set(expected_by_logical)
    probe_logical_ids = [probe.get("logical_id") for probe in probes]
    probe_ids_valid = all(isinstance(value, str) and bool(value) for value in probe_logical_ids)
    mapping_valid = (
        controls_valid
        and len(probes) == expected_nodes
        and probe_ids_valid
        and len(probe_logical_ids) == len(set(str(value) for value in probe_logical_ids))
        and set(str(value) for value in probe_logical_ids) == expected_logical_ids
    )
    logical_to_node_id: dict[str, str] = {}
    for probe in probes:
        logical_id = probe.get("logical_id")
        nodes = _object(probe.get("cluster_nodes"))
        myself_ids = [
            str(node_id)
            for node_id, raw_node in nodes.items()
            if "myself" in {str(flag) for flag in _array(_object(raw_node).get("flags"))}
        ]
        if isinstance(logical_id, str) and logical_id in expected_logical_ids and len(myself_ids) == 1:
            logical_to_node_id[logical_id] = myself_ids[0]
        else:
            mapping_valid = False
    mapping_valid = (
        mapping_valid
        and len(logical_to_node_id) == len(expected_by_logical)
        and len(set(logical_to_node_id.values())) == len(logical_to_node_id)
    )

    expected_roles_by_node_id = {
        logical_to_node_id[logical_id]: row["role"]
        for logical_id, row in expected_by_logical.items()
        if logical_id in logical_to_node_id
    }
    expected_shards_by_node_id = {
        logical_to_node_id[logical_id]: row["shard_id"]
        for logical_id, row in expected_by_logical.items()
        if logical_id in logical_to_node_id
    }
    logical_by_node_id = {node_id: logical_id for logical_id, node_id in logical_to_node_id.items()}
    expected_primary_by_shard: dict[str, str] = {}
    shard_role_counts: dict[str, dict[str, int]] = {}
    for logical_id, row in expected_by_logical.items():
        shard_id = row["shard_id"]
        counts = shard_role_counts.setdefault(shard_id, {"primary": 0, "replica": 0})
        counts[row["role"]] += 1
        if row["role"] == "primary" and logical_id in logical_to_node_id:
            expected_primary_by_shard[shard_id] = logical_to_node_id[logical_id]
    expected_replicas = [row for row in expected_by_logical.values() if row["role"] == "replica"]
    replica_layout_valid = bool(expected_replicas) and all(
        counts == {"primary": 1, "replica": 1} for counts in shard_role_counts.values()
    )

    mapped_node_ids = set(logical_to_node_id.values())
    canonical_node_ids: set[str] | None = None
    exact_membership = mapping_valid
    clean_probe_summaries = bool(probes)
    link_clean = bool(probes)
    stable_slots = bool(probes)
    roles_match = mapping_valid
    replicas_synchronized = mapping_valid and replica_layout_valid
    unexpected_pfail_ids: set[str] = set()
    unexpected_fail_ids: set[str] = set()
    unexpected_promotion_ids: set[str] = set()
    split_brain = False
    slot_loss = not bool(probes)
    slot_counts: list[int] = []
    canonical_slot_owners: dict[int, str] | None = None

    for probe in probes:
        nodes = _object(probe.get("cluster_nodes"))
        node_ids = set(str(node_id) for node_id in nodes)
        if canonical_node_ids is None:
            canonical_node_ids = node_ids
        exact_membership = exact_membership and (
            node_ids == mapped_node_ids
            and node_ids == canonical_node_ids
            and len(nodes) == expected_nodes
            and probe.get("cluster_known_nodes") == expected_nodes
        )
        clean_probe_summaries = clean_probe_summaries and (
            probe.get("status") == "PASS"
            and probe.get("ping") == "PONG"
            and probe.get("cluster_state") == "ok"
            and probe.get("cluster_slots_assigned") == 16384
            and probe.get("cluster_slots_ok") == 16384
            and probe.get("cluster_known_nodes") == expected_nodes
        )
        owned_slots: set[int] = set()
        slot_owners: dict[int, str] = {}
        view_split_brain = False
        for node_id, raw_node in nodes.items():
            node = _object(raw_node)
            flags = {str(flag) for flag in _array(node.get("flags"))}
            node_id = str(node_id)
            primary_flag = "master" in flags
            replica_flag = bool(flags.intersection({"slave", "replica"}))
            observed_role = "primary" if primary_flag and not replica_flag else "replica" if replica_flag and not primary_flag else "unknown"
            if flags.intersection({"pfail", "fail?"}):
                unexpected_pfail_ids.add(node_id)
            if "fail" in flags:
                unexpected_fail_ids.add(node_id)
            if flags.intersection({"handshake", "noaddr"}) or node.get("link_state") != "connected":
                link_clean = False
            expected_role = expected_roles_by_node_id.get(node_id)
            roles_match = roles_match and (
                expected_role is not None
                and observed_role == expected_role
                and node.get("role") == observed_role
                and node.get("node_id") == node_id
            )
            if expected_role == "replica" and observed_role == "primary":
                unexpected_promotion_ids.add(node_id)
            raw_slots = _array(node.get("slots"))
            stable_slots = stable_slots and _stable_slot_tokens(raw_slots)
            if observed_role == "primary":
                node_slots = _slot_tokens(raw_slots)
                if owned_slots.intersection(node_slots):
                    view_split_brain = True
                owned_slots.update(node_slots)
                for slot in node_slots:
                    if slot in slot_owners and slot_owners[slot] != node_id:
                        view_split_brain = True
                    slot_owners[slot] = node_id
            elif raw_slots:
                stable_slots = False
            if expected_role == "replica":
                logical_id = logical_by_node_id.get(node_id)
                expected_master = (
                    expected_primary_by_shard.get(expected_by_logical[logical_id]["shard_id"])
                    if logical_id is not None
                    else None
                )
                replicas_synchronized = replicas_synchronized and observed_role == "replica" and node.get("master_id") == expected_master
        if canonical_slot_owners is None:
            canonical_slot_owners = slot_owners
        elif slot_owners != canonical_slot_owners:
            view_split_brain = True
        split_brain = split_brain or view_split_brain
        slot_counts.append(len(owned_slots))
        slot_loss = slot_loss or len(owned_slots) != 16384

    observed_nodes = len(canonical_node_ids or set())
    slots_covered = min(slot_counts, default=0)
    clean_topology = (
        exact_membership
        and clean_probe_summaries
        and link_clean
        and stable_slots
        and roles_match
        and replicas_synchronized
        and not unexpected_pfail_ids
        and not unexpected_fail_ids
        and not unexpected_promotion_ids
        and not split_brain
        and not slot_loss
    )
    return {
        "exact_membership": exact_membership,
        "observed_nodes": observed_nodes,
        "slots_covered": slots_covered,
        "replicas_synchronized": replicas_synchronized,
        "clean_topology": clean_topology,
        "split_brain": split_brain,
        "slot_loss": slot_loss,
        "unexpected_pfail": len(unexpected_pfail_ids),
        "unexpected_fail": len(unexpected_fail_ids),
        "unexpected_promotions": len(unexpected_promotion_ids),
        "link_clean": link_clean,
        "roles_match": roles_match,
        "identity_mapping_complete": mapping_valid,
        "expected_roles_by_node_id": dict(sorted(expected_roles_by_node_id.items())),
        "expected_shards_by_node_id": dict(sorted(expected_shards_by_node_id.items())),
        "expected_node_id_by_logical": dict(sorted(logical_to_node_id.items())),
    }


def _validate_topology_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    trial_id = trial.get("trial_id", "MISSING")
    scale = trial.get("scale")
    probes = [_object(value) for value in _array(document.get("probes"))]
    versions = document.get("versions")
    binary_sha256s = document.get("valkey_binary_sha256s")
    provenance_versions = _object(trial.get("provenance")).get("valkey_versions")
    _add(errors, document.get("status") == "PASS", f"trial {trial_id} topology source did not PASS")
    _add(errors, versions == provenance_versions and isinstance(versions, list) and bool(versions), f"trial {trial_id} topology versions do not match provenance")
    _add(
        errors,
        isinstance(binary_sha256s, list)
        and bool(binary_sha256s)
        and all(isinstance(value, str) and SHA256_RE.fullmatch(value) for value in binary_sha256s)
        and _object(trial.get("provenance")).get("valkey_binary_digest")
        == _canonical_digest(
            {
                "versions": sorted(versions) if isinstance(versions, list) else [],
                "valkey_binary_sha256s": sorted(binary_sha256s) if isinstance(binary_sha256s, list) else [],
            }
        ),
        f"trial {trial_id} Valkey binary digest is not derived from observed binaries",
    )
    topology_control = document.get("topology_control")
    placement_control = document.get("placement_control")
    environment_control = document.get("environment_control")
    provenance = _object(trial.get("provenance"))
    topology_rows = [_object(row) for row in topology_control] if isinstance(topology_control, list) else []
    placement_rows = [_object(row) for row in placement_control] if isinstance(placement_control, list) else []
    topology_logical_ids = [row.get("logical_id") for row in topology_rows]
    placement_logical_ids = [row.get("logical_id") for row in placement_rows]
    roles = [row.get("role") for row in topology_rows]
    expected_role_count = scale // 2 if isinstance(scale, int) and not isinstance(scale, bool) else -1
    _add(
        errors,
        isinstance(topology_control, list)
        and len(topology_control) == scale
        and all(isinstance(value, str) and value for value in topology_logical_ids)
        and _all_unique(topology_logical_ids)
        and roles.count("primary") == expected_role_count
        and roles.count("replica") == expected_role_count
        and provenance.get("topology_digest") == _canonical_digest(topology_control),
        f"trial {trial_id} topology digest is not derived from its raw control",
    )
    _add(
        errors,
        isinstance(placement_control, list)
        and len(placement_control) == scale
        and all(isinstance(value, str) and value for value in placement_logical_ids)
        and all(isinstance(value, str) and value for value in topology_logical_ids)
        and sorted(placement_logical_ids) == sorted(topology_logical_ids)
        and all(
            all(isinstance(row.get(field), str) and row.get(field) for field in ("nodehost_id", "host_id", "az_id"))
            for row in placement_rows
        )
        and provenance.get("placement_digest") == _canonical_digest(placement_control),
        f"trial {trial_id} placement digest is not derived from its raw control",
    )
    _add(
        errors,
        isinstance(environment_control, dict)
        and bool(environment_control)
        and provenance.get("environment_digest") == _canonical_digest(environment_control),
        f"trial {trial_id} environment digest is not derived from its raw control",
    )
    facts = _recompute_topology_facts(probes, topology_rows, expected_nodes=scale)
    _add(errors, isinstance(scale, int) and len(probes) == scale, f"trial {trial_id} topology source does not cover every node")
    _add(
        errors,
        facts["identity_mapping_complete"] is True,
        f"trial {trial_id} logical-to-Valkey identity mapping is incomplete or ambiguous",
    )
    _add(errors, facts["roles_match"] is True, f"trial {trial_id} observed roles do not match topology_control")
    _add(errors, facts["link_clean"] is True, f"trial {trial_id} raw topology has a disconnected cluster link")
    correctness = _object(trial.get("correctness"))
    _add(
        errors,
        facts["exact_membership"] is True
        and correctness.get("exact_membership") == facts["exact_membership"]
        and correctness.get("observed_nodes") == facts["observed_nodes"],
        f"trial {trial_id} topology source does not bind exact membership",
    )
    _add(
        errors,
        facts["slots_covered"] == 16384
        and correctness.get("slots_covered") == facts["slots_covered"],
        f"trial {trial_id} topology source does not bind exact clean membership and slots",
    )
    _add(
        errors,
        correctness.get("replicas_synchronized") == facts["replicas_synchronized"] is True,
        f"trial {trial_id} topology source does not bind synchronized replicas",
    )
    required_correctness = {
        "clean_topology": True,
        "split_brain": False,
        "slot_loss": False,
        "unexpected_pfail": 0,
        "unexpected_fail": 0,
        "unexpected_promotions": 0,
    }
    for field, required in required_correctness.items():
        _add(
            errors,
            facts[field] == required and correctness.get(field) == facts[field],
            f"trial {trial_id} correctness {field} is not derived from raw topology probes",
        )
    return facts


def _validate_command_source(
    rows: Sequence[Mapping[str, Any]],
    trial: Mapping[str, Any],
    *,
    fault_trial: bool,
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    _add(errors, bool(rows), f"trial {trial_id} command source is empty")
    sequences: list[Any] = []
    for index, row in enumerate(rows, start=1):
        prefix = f"trial {trial_id} command source row {index}"
        sequences.append(row.get("sequence"))
        _add(errors, row.get("artifact_type") == "runtime_command_log_entry", f"{prefix} has an invalid artifact type")
        _add(errors, row.get("run_id") == trial.get("run_id"), f"{prefix} is not owned by the trial run")
        _add(errors, row.get("status") in {"PASS", "RETRY", "SKIPPED_WITH_REASON"}, f"{prefix} contains FAIL, TIMEOUT, or missing status")
        _add(errors, isinstance(row.get("sequence"), int) and not isinstance(row.get("sequence"), bool) and row["sequence"] > 0, f"{prefix} has no valid sequence")
        start = _number(row.get("started_at_monotonic_ms"))
        end = _number(row.get("ended_at_monotonic_ms"))
        duration = _number(row.get("monotonic_duration_ms"))
        _add(
            errors,
            start is not None
            and end is not None
            and duration is not None
            and end >= start
            and math.isclose(duration, end - start, rel_tol=0, abs_tol=1e-3),
            f"{prefix} lacks complete monotonic bounds",
        )
        if fault_trial:
            argv = [str(value) for value in _array(row.get("argv"))]
            cli_index = next(
                (
                    position
                    for position, value in enumerate(argv)
                    if os.path.basename(value).lower() == "valkey-cli"
                ),
                None,
            )
            command: list[str] = []
            if cli_index is not None:
                position = cli_index + 1
                while position < len(argv):
                    option = argv[position].lower()
                    if option in {"-c", "--raw", "-3", "--json"}:
                        position += 1
                        continue
                    if option in {"-h", "-p"}:
                        position += 2
                        continue
                    break
                command = [value.upper() for value in argv[position : position + 2]]
            _add(
                errors,
                command != ["CLUSTER", "FAILOVER"],
                f"{prefix} uses CLUSTER FAILOVER",
            )
    valid_sequences = [value for value in sequences if isinstance(value, int) and not isinstance(value, bool)]
    _add(errors, len(valid_sequences) == len(set(valid_sequences)), f"trial {trial_id} command source sequences are duplicated")


def _validate_state_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    scale = trial.get("scale")
    runtime = _object(document.get("runtime"))
    nodes = [_object(row) for row in _array(document.get("nodes"))]
    logical_ids = [row.get("logical_id") for row in nodes]
    physical_ids = [(row.get("container_name"), row.get("pid")) for row in nodes]
    _add(
        errors,
        document.get("backend_id") == "docker_process"
        and runtime.get("type") == "docker_process"
        and runtime.get("project") == "valkey-scale-lab"
        and runtime.get("run_id") == trial.get("run_id") == trial.get("ownership_id"),
        f"trial {trial_id} state is not an owned docker_process run",
    )
    _add(
        errors,
        isinstance(scale, int)
        and document.get("requested_nodes") == scale
        and document.get("observed_nodes") == scale
        and runtime.get("logical_node_count") == scale
        and len(nodes) == scale,
        f"trial {trial_id} state does not prove exact requested membership",
    )
    _add(
        errors,
        _all_unique(logical_ids)
        and _all_unique(physical_ids)
        and all(isinstance(value, str) and value for value in logical_ids)
        and all(
            isinstance(container, str)
            and bool(container)
            and isinstance(pid, int)
            and not isinstance(pid, bool)
            and pid > 0
            for container, pid in physical_ids
        )
        and all(row.get("simulated") is not True for row in nodes),
        f"trial {trial_id} state lacks unique real process ownership",
    )
    treatment = _object(trial.get("treatment"))
    kind = treatment.get("kind")
    actual_strategy = runtime.get("cluster_create_strategy")
    actual_timeout = runtime.get("effective_cluster_node_timeout_ms")
    if kind == "cluster_create_strategy":
        _add(
            errors,
            actual_strategy == treatment.get("value"),
            f"trial {trial_id} state does not bind the cluster-create treatment",
        )
    elif kind == "cluster_node_timeout_ms":
        _add(
            errors,
            actual_timeout == treatment.get("value")
            and isinstance(treatment.get("cluster_create_strategy"), str)
            and actual_strategy == treatment.get("cluster_create_strategy"),
            f"trial {trial_id} state does not bind the timeout treatment and paired formation strategy",
        )
    elif kind == "selected_settings":
        _add(
            errors,
            actual_strategy == treatment.get("cluster_create_strategy")
            and actual_timeout == treatment.get("cluster_node_timeout_ms"),
            f"trial {trial_id} state does not bind the selected settings",
        )
    else:
        errors.append(f"trial {trial_id} state has an unsupported treatment kind")
    bounded_parallelism = treatment.get("bounded_parallelism")
    if isinstance(bounded_parallelism, int) and not isinstance(bounded_parallelism, bool):
        _add(
            errors,
            runtime.get("cluster_create_parallelism") == bounded_parallelism,
            f"trial {trial_id} state does not bind bounded cluster-create parallelism",
        )


def _validate_attempt_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    errors: list[str],
) -> tuple[float, float] | None:
    trial_id = trial.get("trial_id", "MISSING")
    setup = _object(document.get("setup"))
    cleanup = _object(document.get("cleanup"))
    trial_start = _number(document.get("trial_started_at_monotonic"))
    trial_end = _number(document.get("trial_ended_at_monotonic"))
    setup_start = _number(setup.get("started_at_monotonic"))
    setup_end = _number(setup.get("ended_at_monotonic"))
    cleanup_start = _number(cleanup.get("started_at_monotonic"))
    cleanup_end = _number(cleanup.get("ended_at_monotonic"))
    _add(
        errors,
        document.get("artifact_type") == "m2_trial_attempt"
        and document.get("status") == "PASS"
        and document.get("trial_id") == trial_id
        and document.get("run_id") == trial.get("run_id")
        and document.get("ownership_id") == trial.get("ownership_id"),
        f"trial {trial_id} attempt evidence does not bind the completed owned run",
    )
    ordered = (
        trial_start is not None
        and setup_start is not None
        and setup_end is not None
        and cleanup_start is not None
        and cleanup_end is not None
        and trial_end is not None
        and trial_start <= setup_start <= setup_end <= cleanup_start <= cleanup_end <= trial_end
    )
    _add(
        errors,
        ordered and setup.get("returncode") == 0 and cleanup.get("returncode") == 0,
        f"trial {trial_id} attempt lacks ordered successful setup and cleanup bounds",
    )
    return (trial_start, trial_end) if ordered else None


def _recompute_compact_fault_facts(
    raw_views: Any,
    *,
    initial_roles: Mapping[str, Any],
    node_shards: Mapping[str, Any],
    target_node_ids: set[str],
    replacement_node_ids: set[str],
    expected_nodes: Any,
) -> tuple[dict[str, Any], bool, list[str]]:
    views = _array(raw_views)
    parsed = [value for value in views if isinstance(value, dict)]
    logical_ids = [str(view.get("logical_id")) for view in parsed]
    expected_node_ids = set(str(node_id) for node_id in initial_roles)
    mappings_complete = (
        isinstance(expected_nodes, int)
        and not isinstance(expected_nodes, bool)
        and expected_nodes > 0
        and len(expected_node_ids) == expected_nodes
        and set(str(node_id) for node_id in node_shards) == expected_node_ids
        and all(role in {"primary", "replica"} for role in initial_roles.values())
        and all(isinstance(shard_id, str) and shard_id for shard_id in node_shards.values())
    )
    view_contract = (
        mappings_complete
        and bool(views)
        and len(parsed) == len(views)
        and _all_unique(logical_ids)
        and all(isinstance(view.get("logical_id"), str) and view.get("logical_id") for view in parsed)
        and all(
            set(_object(view.get("cluster_nodes"))) == expected_node_ids
            and len(_object(view.get("cluster_nodes"))) == expected_nodes
            and set(_object(view.get("target_flags"))) == target_node_ids
            and set(_object(view.get("replacement_roles"))) == replacement_node_ids
            and all(
                isinstance(flags, list) and all(isinstance(flag, str) for flag in flags)
                for flags in _object(view.get("target_flags")).values()
            )
            and all(
                _object(view.get("target_flags")).get(node_id)
                == _object(_object(view.get("cluster_nodes")).get(node_id)).get("flags")
                for node_id in target_node_ids
            )
            and all(
                _object(view.get("replacement_roles")).get(node_id)
                == _object(_object(view.get("cluster_nodes")).get(node_id)).get("role")
                for node_id in replacement_node_ids
            )
            for view in parsed
        )
    )
    passing = [view for view in parsed if view.get("status") == "PASS"]
    complete = view_contract and len(passing) == len(parsed)

    def flags(view: Mapping[str, Any], node_id: str) -> set[str]:
        return {
            str(value)
            for value in _array(
                _object(_object(view.get("cluster_nodes")).get(node_id)).get("flags")
            )
        }

    def observed_role(node: Mapping[str, Any]) -> str:
        node_flags = {str(value) for value in _array(node.get("flags"))}
        primary = "master" in node_flags
        replica = bool(node_flags.intersection({"slave", "replica"}))
        if primary and not replica:
            return "primary"
        if replica and not primary:
            return "replica"
        return "unknown"

    target_pfail = sorted(
        node_id
        for node_id in target_node_ids
        if any(flags(view, node_id).intersection({"pfail", "fail?"}) for view in passing)
    )
    target_fail = sorted(
        node_id for node_id in target_node_ids if any("fail" in flags(view, node_id) for view in passing)
    )
    promoted = sorted(
        node_id
        for node_id in replacement_node_ids
        if any(
            observed_role(_object(_object(view.get("cluster_nodes")).get(node_id))) == "primary"
            for view in passing
        )
    )
    replacement_complete = complete and bool(replacement_node_ids) and all(
        all(
            observed_role(_object(_object(view.get("cluster_nodes")).get(node_id))) == "primary"
            for view in passing
        )
        for node_id in replacement_node_ids
    )
    exact_membership = (
        complete
        and all(
            view.get("cluster_known_nodes") == expected_nodes
            and set(_object(view.get("cluster_nodes"))) == expected_node_ids
            for view in passing
        )
    )
    summary_slots_ok = exact_membership and all(
        view.get("cluster_state") == "ok"
        and view.get("cluster_slots_assigned") == 16384
        and view.get("cluster_slots_ok") == 16384
        for view in passing
    )
    known_counts = [
        len(_object(view.get("cluster_nodes")))
        for view in passing
    ]
    all_expected_fail = complete and all(
        all("fail" in flags(view, node_id) for view in passing)
        for node_id in target_node_ids
    )
    unexpected_pfail_ids: set[str] = set()
    unexpected_fail_ids: set[str] = set()
    unexpected_promotion_ids: set[str] = set()
    clean_topology = complete
    split_brain = False
    raw_slots_ok = exact_membership
    for view in passing:
        nodes = _object(view.get("cluster_nodes"))
        live_primaries: dict[str, int] = {}
        owned_slots: set[int] = set()
        view_slots_valid = True
        for raw_node_id, raw_node in nodes.items():
            node_id = str(raw_node_id)
            node = _object(raw_node)
            raw_flags = node.get("flags")
            raw_slots = node.get("slots")
            node_flags = {str(value) for value in _array(raw_flags)}
            role = observed_role(node)
            master_id = node.get("master_id")
            slots_structurally_valid = (
                isinstance(raw_slots, list)
                and all(isinstance(value, str) for value in raw_slots)
                and _stable_slot_tokens(raw_slots)
            )
            row_contract = (
                node.get("node_id") == node_id
                and isinstance(node.get("addr"), str)
                and bool(node.get("addr"))
                and isinstance(raw_flags, list)
                and all(isinstance(value, str) for value in raw_flags)
                and slots_structurally_valid
                and role in {"primary", "replica"}
                and node.get("role") == role
                and (
                    (role == "primary" and master_id in {None, "-"})
                    or (
                        role == "replica"
                        and isinstance(master_id, str)
                        and bool(master_id)
                    )
                )
                and node.get("link_state") in {"connected", "disconnected"}
            )
            clean_topology = clean_topology and row_contract
            if node_flags.intersection({"handshake", "noaddr"}):
                clean_topology = False
            if node_id not in target_node_ids and node.get("link_state") != "connected":
                clean_topology = False
            if node_id not in target_node_ids and node_flags.intersection({"pfail", "fail?"}):
                unexpected_pfail_ids.add(node_id)
            if node_id not in target_node_ids and "fail" in node_flags:
                unexpected_fail_ids.add(node_id)
            if initial_roles.get(node_id) == "replica" and role == "primary" and node_id not in replacement_node_ids:
                unexpected_promotion_ids.add(node_id)
            if role == "replica" and raw_slots:
                clean_topology = False
            if role == "primary" and master_id not in {None, "-"}:
                clean_topology = False
            if role == "replica":
                master = _object(nodes.get(master_id)) if isinstance(master_id, str) else {}
                master_flags = {
                    str(value) for value in _array(master.get("flags"))
                }
                if (
                    not master
                    or node_shards.get(node_id) != node_shards.get(str(master_id))
                    or observed_role(master) != "primary"
                    or master.get("link_state") != "connected"
                    or master_flags.intersection(
                        {"pfail", "fail?", "fail", "handshake", "noaddr"}
                    )
                ):
                    clean_topology = False
            if role == "primary" and not node_flags.intersection({"pfail", "fail?", "fail", "handshake", "noaddr"}):
                shard_id = node_shards.get(node_id)
                if isinstance(shard_id, str) and shard_id:
                    live_primaries[shard_id] = live_primaries.get(shard_id, 0) + 1
                else:
                    clean_topology = False
                node_slots = _slot_tokens(raw_slots) if slots_structurally_valid else set()
                if owned_slots.intersection(node_slots):
                    split_brain = True
                    view_slots_valid = False
                owned_slots.update(node_slots)
        if any(count > 1 for count in live_primaries.values()):
            split_brain = True
            view_slots_valid = False
        if len(owned_slots) != 16384:
            view_slots_valid = False
        raw_slots_ok = raw_slots_ok and view_slots_valid
    slots_ok = summary_slots_ok and raw_slots_ok and not split_brain
    converged = (
        exact_membership
        and slots_ok
        and replacement_complete
        and all_expected_fail
        and clean_topology
        and not split_brain
        and not unexpected_pfail_ids
        and not unexpected_fail_ids
        and not unexpected_promotion_ids
    )
    return (
        {
            "probe_count": len(views),
            "passing_probe_count": len(passing),
            "target_pfail_node_ids": target_pfail,
            "target_fail_node_ids": target_fail,
            "promoted_replacement_node_ids": promoted,
            "replacement_promotions_complete": replacement_complete,
            "all_expected_targets_fail": all_expected_fail,
            "exact_membership": exact_membership,
            "observed_nodes": expected_nodes if exact_membership else max(known_counts, default=0),
            "slots_covered": 16384 if slots_ok else 0,
            "cluster_ok_all_slots": slots_ok and replacement_complete,
            "clean_topology": clean_topology,
            "unexpected_pfail": len(unexpected_pfail_ids),
            "unexpected_fail": len(unexpected_fail_ids),
            "unexpected_promotions": len(unexpected_promotion_ids),
            "split_brain": split_brain,
            "slot_loss": not slots_ok,
            "converged": converged,
        },
        view_contract,
        logical_ids,
    )


def _validate_fault_fact_row(
    facts: Mapping[str, Any],
    recomputed: Mapping[str, Any],
    *,
    trial_id: Any,
    label: str,
    errors: list[str],
) -> None:
    for field, value in recomputed.items():
        _add(
            errors,
            facts.get(field) == value,
            f"trial {trial_id} {label} fact {field} is not derived from its compact raw views",
        )
    counts_valid = all(
        isinstance(facts.get(field), int)
        and not isinstance(facts.get(field), bool)
        and facts[field] >= 0
        for field in ("unexpected_pfail", "unexpected_fail", "unexpected_promotions")
    )
    booleans_valid = all(
        isinstance(facts.get(field), bool)
        for field in ("clean_topology", "split_brain", "converged")
    )
    _add(errors, counts_valid and booleans_valid, f"trial {trial_id} {label} safety facts are incomplete")
    expected_converged = (
        recomputed.get("exact_membership") is True
        and recomputed.get("cluster_ok_all_slots") is True
        and recomputed.get("replacement_promotions_complete") is True
        and recomputed.get("all_expected_targets_fail") is True
        and recomputed.get("slot_loss") is False
        and facts.get("clean_topology") is True
        and facts.get("split_brain") is False
        and all(facts.get(field) == 0 for field in ("unexpected_pfail", "unexpected_fail", "unexpected_promotions"))
    )
    _add(
        errors,
        facts.get("converged") is expected_converged,
        f"trial {trial_id} {label} convergence is not derived from its raw facts",
    )


def _validate_fault_topology_view_dictionary(
    document: Mapping[str, Any],
    *,
    trial_id: Any,
    errors: list[str],
) -> dict[str, list[Any]]:
    raw_entries = document.get("topology_view_dictionary")
    entries = raw_entries if isinstance(raw_entries, list) else []
    views_by_digest: dict[str, list[Any]] = {}
    declared_digests: list[str] = []
    _add(
        errors,
        isinstance(raw_entries, list) and bool(raw_entries),
        f"trial {trial_id} fault topology view dictionary is missing",
    )
    for index, raw_entry in enumerate(entries, start=1):
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        digest = entry.get("sha256")
        views = entry.get("views")
        try:
            canonical_digest = (
                _canonical_digest(views)
                if isinstance(views, list) and bool(views)
                else None
            )
        except (TypeError, ValueError):
            canonical_digest = None
        entry_valid = (
            isinstance(raw_entry, dict)
            and set(raw_entry) == {"sha256", "views"}
            and isinstance(digest, str)
            and SHA256_RE.fullmatch(digest) is not None
            and isinstance(views, list)
            and bool(views)
            and canonical_digest == digest
        )
        _add(
            errors,
            entry_valid,
            f"trial {trial_id} fault topology view dictionary entry {index} is not canonically digest-bound",
        )
        if isinstance(digest, str):
            declared_digests.append(digest)
        if entry_valid and digest not in views_by_digest:
            views_by_digest[digest] = views
    _add(
        errors,
        len(declared_digests) == len(entries)
        and _all_unique(declared_digests)
        and len(views_by_digest) == len(entries),
        f"trial {trial_id} fault topology view dictionary contains duplicate entries",
    )

    referenced_digests: set[str] = set()
    for index, raw_round in enumerate(_array(document.get("observer_rounds")), start=1):
        round_row = raw_round if isinstance(raw_round, dict) else {}
        digest = round_row.get("views_sha256")
        _add(
            errors,
            isinstance(raw_round, dict) and "views" not in raw_round,
            f"trial {trial_id} observer round {index} contains inline topology views",
        )
        ref_valid = (
            isinstance(digest, str)
            and SHA256_RE.fullmatch(digest) is not None
            and digest in views_by_digest
        )
        _add(
            errors,
            ref_valid,
            f"trial {trial_id} observer round {index} topology view reference is missing or invalid",
        )
        if isinstance(digest, str):
            referenced_digests.add(digest)

    convergence_digest = document.get("every_node_convergence_views_sha256")
    _add(
        errors,
        "every_node_convergence_views" not in document,
        f"trial {trial_id} every-node convergence contains inline topology views",
    )
    convergence_ref_valid = (
        isinstance(convergence_digest, str)
        and SHA256_RE.fullmatch(convergence_digest) is not None
        and convergence_digest in views_by_digest
    )
    _add(
        errors,
        convergence_ref_valid,
        f"trial {trial_id} every-node convergence topology view reference is missing or invalid",
    )
    if isinstance(convergence_digest, str):
        referenced_digests.add(convergence_digest)
    _add(
        errors,
        set(views_by_digest) == referenced_digests,
        f"trial {trial_id} fault topology view dictionary has unreferenced or unknown entries",
    )
    return views_by_digest


def _validate_fault_source(
    document: Mapping[str, Any],
    trial: Mapping[str, Any],
    *,
    topology_document: Mapping[str, Any] | None,
    state_document: Mapping[str, Any] | None,
    errors: list[str],
) -> None:
    trial_id = trial.get("trial_id", "MISSING")
    summary = _object(trial.get("fault"))
    _add(
        errors,
        summary == _compact_fault_summary(document),
        f"trial {trial_id} fault summary is not the compact raw-derived projection",
    )
    _add(errors, document.get("status") == "PASS", f"trial {trial_id} fault source did not PASS")
    _add(errors, document.get("errors") == [], f"trial {trial_id} fault source reports errors")
    source_markers = _object(document.get("monotonic_markers"))
    trial_markers = _object(trial.get("monotonic_markers"))
    for marker in FAILOVER_MARKERS:
        _add(
            errors,
            marker in source_markers and _same_number(source_markers.get(marker), trial_markers.get(marker)),
            f"trial {trial_id} fault marker {marker} does not match its source",
        )
    expected_nodes = trial.get("scale")
    topology_source = _object(topology_document)
    topology_facts = _recompute_topology_facts(
        [_object(value) for value in _array(topology_source.get("probes"))],
        [_object(value) for value in _array(topology_source.get("topology_control"))],
        expected_nodes=expected_nodes,
    )
    initial_roles = _object(document.get("initial_roles"))
    node_shards = _object(document.get("node_shards"))
    expected_roles = _object(topology_facts.get("expected_roles_by_node_id"))
    expected_shards = _object(topology_facts.get("expected_shards_by_node_id"))
    expected_node_id_by_logical = _object(topology_facts.get("expected_node_id_by_logical"))
    _add(
        errors,
        topology_document is not None
        and topology_facts.get("identity_mapping_complete") is True
        and initial_roles == expected_roles
        and node_shards == expected_shards
        and len(initial_roles) == expected_nodes
        and len(node_shards) == expected_nodes,
        f"trial {trial_id} fault initial roles or shard identities are not bound to pre-fault raw topology",
    )

    target_rows = [_object(value) for value in _array(document.get("targets"))]
    target_node_ids = {
        str(row.get("valkey_node_id"))
        for row in target_rows
        if isinstance(row.get("valkey_node_id"), str) and row.get("valkey_node_id")
    }
    declared_targets = _array(document.get("target_node_ids"))
    replacement_values = _array(document.get("replacement_node_ids"))
    replacement_node_ids = {
        str(value) for value in replacement_values if isinstance(value, str) and value
    }
    target_logical_ids = {
        str(row.get("logical_id"))
        for row in target_rows
        if isinstance(row.get("logical_id"), str) and row.get("logical_id")
    }
    target_shards = {
        str(row.get("shard_id"))
        for row in target_rows
        if isinstance(row.get("shard_id"), str) and row.get("shard_id")
    }
    barrier = _number(document.get("barrier_monotonic"))
    barrier_ms = barrier * 1000.0 if barrier is not None else None
    signal_sent_values: list[float] = []
    signal_completed_values: list[float] = []
    signal_envelope_valid = bool(target_rows) and barrier_ms is not None
    for row in target_rows:
        sent = _number(row.get("signal_sent_at_monotonic_ms"))
        completed = _number(row.get("signal_completed_at_monotonic_ms"))
        gone = _number(row.get("process_gone_at_monotonic_ms"))
        if (
            sent is None
            or completed is None
            or gone is None
            or barrier_ms is None
            or not barrier_ms <= sent <= completed <= gone
            or row.get("status") != "PASS"
            or row.get("error", "") != ""
        ):
            signal_envelope_valid = False
            continue
        signal_sent_values.append(sent)
        signal_completed_values.append(completed)
    raw_barrier_span = (
        round(max(signal_completed_values) - min(signal_sent_values), 3)
        if len(signal_sent_values) == len(signal_completed_values) == len(target_rows)
        else None
    )
    _add(
        errors,
        signal_envelope_valid
        and raw_barrier_span is not None
        and raw_barrier_span <= 500.0
        and _same_number(document.get("fault_apply_monotonic_ms"), barrier_ms)
        and _same_number(document.get("signal_barrier_span_ms"), raw_barrier_span)
        and _same_number(document.get("injection_skew_ms"), raw_barrier_span),
        f"trial {trial_id} SIGKILL barrier span is not raw-derived or exceeds 500 ms",
    )
    state_nodes = {
        str(node.get("logical_id")): node
        for node in (_object(value) for value in _array(_object(state_document).get("nodes")))
        if isinstance(node.get("logical_id"), str) and node.get("logical_id")
    }
    expected_batches: dict[str, dict[str, Any]] = {}
    container_names: dict[str, str] = {}
    container_ids: dict[str, str] = {}
    command_binding_valid = bool(target_logical_ids)
    for logical_id in sorted(target_logical_ids):
        node = state_nodes.get(logical_id)
        if (
            node is None
            or not isinstance(node.get("container_id"), str)
            or DOCKER_CONTAINER_REF_RE.fullmatch(node["container_id"]) is None
            or not isinstance(node.get("container_name"), str)
            or DOCKER_CONTAINER_REF_RE.fullmatch(node["container_name"]) is None
            or not isinstance(node.get("pid"), int)
            or isinstance(node.get("pid"), bool)
            or not 1 < node["pid"] <= 2_147_483_647
            or not isinstance(node.get("pid_file"), str)
            or not node["pid_file"].startswith("/")
            or not isinstance(node.get("config_file"), str)
            or not node["config_file"].startswith("/")
            or not isinstance(node.get("client_port"), int)
            or isinstance(node.get("client_port"), bool)
            or not 1 <= node["client_port"] <= 65535
        ):
            command_binding_valid = False
            continue
        container_name = str(node["container_name"])
        container_id = str(node["container_id"])
        if (
            container_names.get(container_name, container_id) != container_id
            or container_ids.get(container_id, container_name) != container_name
        ):
            command_binding_valid = False
        container_names[container_name] = container_id
        container_ids[container_id] = container_name
        batch = expected_batches.setdefault(
            container_id,
            {
                "container_name": container_name,
                "logical_ids": [],
                "pids": [],
            },
        )
        if batch["container_name"] != node["container_name"]:
            command_binding_valid = False
        batch["logical_ids"].append(logical_id)
        batch["pids"].append(int(node["pid"]))
    observed_batches = [_object(value) for value in _array(document.get("command_batches"))]
    observed_by_container: dict[str, dict[str, Any]] = {}
    rendered_commands: list[str] = []
    for batch in observed_batches:
        container_id = batch.get("container_id")
        if not isinstance(container_id, str) or not container_id or container_id in observed_by_container:
            command_binding_valid = False
            continue
        observed_by_container[container_id] = batch
        expected = expected_batches.get(container_id)
        argv = batch.get("argv")
        started = _number(batch.get("started_at_monotonic"))
        ended = _number(batch.get("ended_at_monotonic"))
        if expected is None:
            command_binding_valid = False
            continue
        pid_text = " ".join(str(pid) for pid in expected["pids"])
        expected_argv = [
            "exec",
            container_id,
            "sh",
            "-c",
            f"kill -KILL {pid_text}",
        ]
        if not (
            batch.get("container_name") == expected["container_name"]
            and batch.get("logical_ids") == expected["logical_ids"]
            and batch.get("pids") == expected["pids"]
            and batch.get("ownership_id") == trial.get("ownership_id")
            and argv == expected_argv
            and batch.get("status") == "PASS"
            and batch.get("returncode") == 0
            and isinstance(batch.get("stdout"), str)
            and started is not None
            and ended is not None
            and barrier is not None
            and barrier <= started <= ended
        ):
            command_binding_valid = False
        if isinstance(argv, list) and all(isinstance(value, str) for value in argv):
            rendered_commands.append(shlex.join(["docker", *argv]))
    _add(
        errors,
        command_binding_valid
        and set(observed_by_container) == set(expected_batches)
        and len(observed_batches) == len(expected_batches)
        and document.get("commands") == rendered_commands,
        f"trial {trial_id} SIGKILL command batches are not bound to owned target processes",
    )
    _add(
        errors,
        bool(target_rows)
        and len(target_node_ids) == len(target_rows)
        and len(target_logical_ids) == len(target_rows)
        and len(target_shards) == len(target_rows)
        and all(row.get("process_gone") is True for row in target_rows)
        and all(
            expected_node_id_by_logical.get(str(row.get("logical_id"))) == row.get("valkey_node_id")
            and initial_roles.get(str(row.get("valkey_node_id"))) == "primary"
            and node_shards.get(str(row.get("valkey_node_id"))) == row.get("shard_id")
            for row in target_rows
        )
        and all(isinstance(value, str) and value for value in declared_targets)
        and _all_unique(declared_targets)
        and set(declared_targets) == target_node_ids,
        f"trial {trial_id} fault target node ids are incomplete or not raw-derived",
    )
    _add(
        errors,
        len(replacement_node_ids) == len(target_node_ids)
        and len(replacement_values) == len(replacement_node_ids)
        and target_node_ids.isdisjoint(replacement_node_ids),
        f"trial {trial_id} replacement node ids are incomplete or duplicated",
    )
    _add(
        errors,
        bool(replacement_node_ids)
        and all(initial_roles.get(node_id) == "replica" for node_id in replacement_node_ids)
        and {str(node_shards.get(node_id)) for node_id in replacement_node_ids} == target_shards,
        f"trial {trial_id} replacements are not the pre-fault replicas of the affected shards",
    )
    gone_values = [
        float(value) / 1000.0
        for value in (row.get("process_gone_at_monotonic_ms") for row in target_rows)
        if _number(value) is not None
    ]
    _add(
        errors,
        barrier is not None and _same_number(source_markers.get("sigkill_barrier"), barrier),
        f"trial {trial_id} SIGKILL barrier marker is not raw-derived",
    )
    _add(
        errors,
        len(gone_values) == len(target_rows)
        and _same_number(source_markers.get("all_processes_gone"), max(gone_values, default=-1.0)),
        f"trial {trial_id} all-processes-gone marker is not raw-derived",
    )

    view_dictionary = _validate_fault_topology_view_dictionary(
        document,
        trial_id=trial_id,
        errors=errors,
    )
    rounds = _array(document.get("observer_rounds"))
    derived_markers: dict[str, float] = {}
    aggregate_safety = {
        "unexpected_pfail": 0,
        "unexpected_fail": 0,
        "unexpected_promotions": 0,
        "split_brain": False,
    }
    previous_at: float | None = None
    convergence_marker = _number(source_markers.get("every_node_converged"))
    post_convergence_rounds = 0
    expected_survivor_logical_ids = set(str(value) for value in expected_node_id_by_logical) - target_logical_ids
    representative_logical_ids: set[str] | None = None
    for index, raw_round in enumerate(rounds, start=1):
        round_row = _object(raw_round)
        observed_at = _number(round_row.get("at_monotonic"))
        probe_started = _number(round_row.get("probe_started_at_monotonic"))
        duration_ms = _number(round_row.get("probe_duration_ms"))
        bounds_valid = (
            observed_at is not None
            and probe_started is not None
            and duration_ms is not None
            and probe_started <= observed_at
            and (previous_at is None or observed_at >= previous_at)
            and math.isclose(duration_ms, (observed_at - probe_started) * 1000.0, rel_tol=0, abs_tol=1e-3)
        )
        _add(errors, bounds_valid, f"trial {trial_id} observer round {index} has invalid monotonic bounds")
        if observed_at is not None:
            previous_at = observed_at
        views_digest = round_row.get("views_sha256")
        recomputed, view_contract, _logical_ids = _recompute_compact_fault_facts(
            view_dictionary.get(str(views_digest)),
            initial_roles=initial_roles,
            node_shards=node_shards,
            target_node_ids=target_node_ids,
            replacement_node_ids=replacement_node_ids,
            expected_nodes=expected_nodes,
        )
        logical_id_set = set(_logical_ids)
        if representative_logical_ids is None:
            representative_logical_ids = logical_id_set
        _add(
            errors,
            bool(logical_id_set)
            and logical_id_set == representative_logical_ids
            and logical_id_set.issubset(expected_survivor_logical_ids)
            and len(logical_id_set) == min(3, len(expected_survivor_logical_ids)),
            f"trial {trial_id} observer round {index} is not bound to the surviving topology identities",
        )
        _add(errors, view_contract, f"trial {trial_id} observer round {index} compact views are incomplete")
        facts = _object(round_row.get("facts"))
        _validate_fault_fact_row(
            facts,
            recomputed,
            trial_id=trial_id,
            label=f"observer round {index}",
            errors=errors,
        )
        if (
            observed_at is not None
            and convergence_marker is not None
            and observed_at > convergence_marker
        ):
            post_convergence_rounds += 1
            _add(
                errors,
                recomputed.get("converged") is True
                and recomputed.get("unexpected_pfail") == 0
                and recomputed.get("unexpected_fail") == 0
                and recomputed.get("unexpected_promotions") == 0
                and recomputed.get("split_brain") is False
                and recomputed.get("slot_loss") is False,
                f"trial {trial_id} observer round {index} regressed after every-node convergence",
            )
        if observed_at is not None:
            if recomputed["target_pfail_node_ids"]:
                derived_markers.setdefault("first_pfail", observed_at)
            if "first_pfail" in derived_markers and recomputed["target_fail_node_ids"]:
                derived_markers.setdefault("quorum_fail", observed_at)
            if "quorum_fail" in derived_markers and recomputed["promoted_replacement_node_ids"]:
                derived_markers.setdefault("first_promotion", observed_at)
            if "first_promotion" in derived_markers and recomputed["cluster_ok_all_slots"] is True:
                derived_markers.setdefault("all_slots_covered_cluster_ok", observed_at)
        for field in ("unexpected_pfail", "unexpected_fail", "unexpected_promotions"):
            value = recomputed.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                aggregate_safety[field] = max(int(aggregate_safety[field]), value)
        aggregate_safety["split_brain"] = bool(
            aggregate_safety["split_brain"] or recomputed.get("split_brain") is True
        )
    _add(errors, bool(rounds), f"trial {trial_id} has no raw fault observer rounds")
    requested_duration = _number(_object(trial.get("workload")).get("duration_seconds"))
    _add(
        errors,
        barrier is not None
        and requested_duration is not None
        and previous_at is not None
        and previous_at >= barrier + requested_duration,
        f"trial {trial_id} raw fault observer rounds do not cover the complete fixed window",
    )
    _add(
        errors,
        post_convergence_rounds > 0,
        f"trial {trial_id} has no fixed observation round after every-node convergence",
    )
    for marker in ("first_pfail", "quorum_fail", "first_promotion", "all_slots_covered_cluster_ok"):
        _add(
            errors,
            marker in derived_markers and _same_number(source_markers.get(marker), derived_markers.get(marker)),
            f"trial {trial_id} fault marker {marker} is not the earliest raw observer transition",
        )
    _add(
        errors,
        document.get("observed_safety") == aggregate_safety,
        f"trial {trial_id} unexpected safety summary is not derived from raw observer rounds",
    )
    correctness = _object(trial.get("correctness"))
    for field in ("unexpected_pfail", "unexpected_fail", "unexpected_promotions", "split_brain"):
        _add(
            errors,
            correctness.get(field) == aggregate_safety[field],
            f"trial {trial_id} correctness {field} is not bound to raw fault safety",
        )

    full_facts = _object(document.get("topology_facts"))
    convergence_views_digest = document.get("every_node_convergence_views_sha256")
    full_recomputed, full_contract, survivor_ids = _recompute_compact_fault_facts(
        view_dictionary.get(str(convergence_views_digest)),
        initial_roles=initial_roles,
        node_shards=node_shards,
        target_node_ids=target_node_ids,
        replacement_node_ids=replacement_node_ids,
        expected_nodes=expected_nodes,
    )
    expected_survivors = (
        expected_nodes - len(target_node_ids)
        if isinstance(expected_nodes, int) and not isinstance(expected_nodes, bool)
        else -1
    )
    _add(
        errors,
        full_contract
        and len(survivor_ids) == expected_survivors
        and set(survivor_ids) == expected_survivor_logical_ids,
        f"trial {trial_id} every-node convergence views do not cover every surviving node",
    )
    _validate_fault_fact_row(
        full_facts,
        full_recomputed,
        trial_id=trial_id,
        label="every-node convergence",
        errors=errors,
    )
    stable_at = _number(source_markers.get("stable_client_recovery"))
    convergence_at = _number(source_markers.get("every_node_converged"))
    convergence_probe = _object(document.get("every_node_convergence_probe"))
    convergence_probe_started = _number(convergence_probe.get("probe_started_at_monotonic"))
    convergence_probe_observed = _number(convergence_probe.get("at_monotonic"))
    convergence_probe_duration_ms = _number(convergence_probe.get("probe_duration_ms"))
    convergence_probe_bounds_valid = (
        convergence_probe_started is not None
        and convergence_probe_observed is not None
        and convergence_probe_duration_ms is not None
        and stable_at is not None
        and convergence_probe_started >= stable_at
        and convergence_probe_observed >= convergence_probe_started
        and math.isclose(
            convergence_probe_duration_ms,
            (convergence_probe_observed - convergence_probe_started) * 1000.0,
            rel_tol=0,
            abs_tol=1e-3,
        )
    )
    _add(
        errors,
        convergence_probe_bounds_valid,
        f"trial {trial_id} every-node convergence probe lacks direct monotonic bounds",
    )
    _add(
        errors,
        full_facts.get("converged") is True
        and convergence_at is not None
        and convergence_probe_bounds_valid
        and _same_number(convergence_at, convergence_probe_observed),
        f"trial {trial_id} every-node convergence marker is not bound to the full raw survivor views",
    )
    for summary_field, fact_field in (
        ("exact_membership", "exact_membership"),
        ("observed_nodes", "observed_nodes"),
        ("slots_covered", "slots_covered"),
        ("replicas_synchronized", "replacement_promotions_complete"),
        ("clean_topology", "clean_topology"),
        ("slot_loss", "slot_loss"),
    ):
        _add(
            errors,
            correctness.get(summary_field) == full_facts.get(fact_field),
            f"trial {trial_id} correctness {summary_field} is not bound to every-node convergence",
        )

    intervals = _object(trial.get("derived_intervals"))
    for interval_name, (start_name, end_name) in {
        "kill_to_stable_seconds": ("sigkill_barrier", "stable_client_recovery"),
        "pfail_to_cluster_ok_seconds": ("first_pfail", "all_slots_covered_cluster_ok"),
        "process_gone_to_pfail_seconds": ("all_processes_gone", "first_pfail"),
        "cluster_ok_to_stable_seconds": ("all_slots_covered_cluster_ok", "stable_client_recovery"),
        "sigkill_to_pfail_seconds": ("sigkill_barrier", "first_pfail"),
        "pfail_to_quorum_fail_seconds": ("first_pfail", "quorum_fail"),
        "quorum_fail_to_promotion_seconds": ("quorum_fail", "first_promotion"),
        "promotion_to_cluster_ok_seconds": ("first_promotion", "all_slots_covered_cluster_ok"),
        "recovery_to_convergence_seconds": ("stable_client_recovery", "every_node_converged"),
    }.items():
        start = _number(source_markers.get(start_name))
        end = _number(source_markers.get(end_name))
        interval = _number(intervals.get(interval_name))
        _add(
            errors,
            start is not None
            and end is not None
            and interval is not None
            and math.isclose(interval, end - start, rel_tol=0, abs_tol=1e-6),
            f"trial {trial_id} interval {interval_name} is not derived from the fault source",
        )


def _compact_fault_summary(document: Mapping[str, Any]) -> dict[str, Any]:
    summary_fields = (
        "status",
        "errors",
        "mode",
        "signal",
        "commands",
        "barrier_monotonic",
        "primary_count",
        "failed_primary_count",
        "injection_skew_ms",
        "signal_barrier_span_ms",
    )
    target_fields = (
        "logical_id",
        "shard_id",
        "pid",
        "ownership_id",
        "process_gone",
        "physical_fault_id",
    )
    return {
        **{field: document.get(field) for field in summary_fields},
        "targets": [
            {field: target.get(field) for field in target_fields}
            for target in (_object(value) for value in _array(document.get("targets")))
        ],
    }


def validate_current_invocation_sources(
    report: Mapping[str, Any],
    *,
    artifacts_dir: Path,
    allow_discovery_safety_rejections: bool = False,
) -> list[str]:
    """Verify every source exists, is non-symlinked, current, and digest-bound."""
    errors: list[str] = []
    cleanup_schema = load_json(CLEANUP_SCHEMA_PATH)
    preflight_schema = load_json(RESOURCE_PREFLIGHT_SCHEMA_PATH)
    top_refs = [_object(row) for row in _array(report.get("source_refs"))]
    if report.get("status") == "BLOCKED" and not _array(report.get("trials")) and not top_refs:
        return []
    preflight_documents: dict[str, dict[str, Any]] = {}
    for index, ref in enumerate(
        (row for row in top_refs if row.get("category") == "preflight"),
        start=1,
    ):
        document = _load_bound_json_source(
            ref,
            artifacts_dir=artifacts_dir,
            label=f"resource preflight evidence {index}",
            errors=errors,
        )
        if document is None:
            continue
        for message in validate(document, preflight_schema):
            errors.append(f"resource preflight evidence {index}: {message}")
        checks = _array(document.get("checks"))
        _add(
            errors,
            document.get("status") == "PASS"
            and document.get("can_run") is True
            and document.get("dry_run") is False
            and bool(checks)
            and all(_object(check).get("status") == "PASS" for check in checks),
            f"resource preflight evidence {index} did not authorize the exact real run",
        )
        digest = ref.get("sha256")
        if isinstance(digest, str):
            _add(errors, digest not in preflight_documents, "resource preflight digest is duplicated")
            preflight_documents[digest] = document
    cells_by_id = {
        str(cell.get("cell_id")): cell
        for cell in (_object(value) for value in _array(report.get("cells")))
    }
    trials_by_id = {
        str(trial.get("trial_id")): trial
        for trial in (_object(value) for value in _array(report.get("trials")))
    }
    trial_refs: list[dict[str, Any]] = []
    attempt_bounds: dict[str, tuple[float, float]] = {}
    resource_documents: dict[str, dict[str, Any]] = {}
    for trial_value in _array(report.get("trials")):
        trial = _object(trial_value)
        trial_id = trial.get("trial_id", "MISSING")
        cell = cells_by_id.get(str(trial.get("cell_id")), {})
        fault_trial = report.get("experiment_kind") == "failover" or (
            report.get("experiment_kind") == "stability"
            and cell.get("failure_rate") != "none"
        )
        preflight_digest = _object(trial.get("provenance")).get("resource_preflight_digest")
        preflight = preflight_documents.get(str(preflight_digest))
        _add(errors, preflight is not None, f"trial {trial_id} resource preflight is not bound to a current source")
        if preflight is not None:
            _add(errors, preflight.get("node_count") == trial.get("scale"), f"trial {trial_id} resource preflight scale is not exact")
            _add(errors, preflight.get("profile_id") == f"exact-{trial.get('scale')}", f"trial {trial_id} resource preflight profile is not exact")
        evidence_root, root_error = _safe_source_path(artifacts_dir, trial.get("evidence_root"))
        if root_error:
            errors.append(f"trial {trial_id}: {root_error}")
        elif evidence_root is None or not evidence_root.is_dir() or evidence_root.is_symlink():
            errors.append(f"trial {trial_id} evidence_root is absent, not a directory, or a symlink")
        refs = [_object(row) for row in _array(trial.get("source_sha256s"))]
        trial_refs.extend(refs)
        refs_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for ref in refs:
            refs_by_category[str(ref.get("category"))].append(ref)
        expected_categories = set(COMMON_SOURCE_CATEGORIES)
        if fault_trial:
            expected_categories.add("fault")
        for category in sorted(expected_categories):
            _add(
                errors,
                len(refs_by_category.get(category, [])) == 1,
                f"trial {trial_id} requires exactly one {category} source",
            )
        _add(
            errors,
            set(refs_by_category) == expected_categories,
            f"trial {trial_id} raw source categories are incomplete or unexpected",
        )
        cleanup_ref = _object(trial.get("cleanup")).get("evidence_ref")
        provenance_ref = _object(trial.get("provenance")).get("evidence_ref")
        cleanup_sources = refs_by_category.get("cleanup", [])
        provenance_sources = refs_by_category.get("provenance", [])
        attempt_sources = refs_by_category.get("attempt", [])
        _add(errors, len(cleanup_sources) == 1 and cleanup_sources[0].get("path") == cleanup_ref, f"trial {trial_id} cleanup evidence is not digest-bound to its category")
        _add(errors, len(provenance_sources) == 1 and provenance_sources[0].get("path") == provenance_ref, f"trial {trial_id} provenance evidence is not digest-bound to its category")
        _add(errors, len(attempt_sources) == 1, f"trial {trial_id} attempt evidence is missing")

        if len(attempt_sources) == 1:
            attempt = _load_bound_json_source(
                attempt_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} attempt evidence",
                errors=errors,
            )
            if attempt is not None:
                bounds = _validate_attempt_source(attempt, trial, errors)
                if bounds is not None:
                    attempt_bounds[str(trial_id)] = bounds

        state_document: dict[str, Any] | None = None
        state_sources = refs_by_category.get("state", [])
        if len(state_sources) == 1:
            state_document = _load_bound_json_source(
                state_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} state evidence",
                errors=errors,
            )
            if state_document is not None:
                _validate_state_source(state_document, trial, errors)

        if len(cleanup_sources) == 1:
            cleanup_document = _load_bound_json_source(
                cleanup_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} cleanup evidence",
                errors=errors,
            )
            if cleanup_document is not None:
                for message in validate(cleanup_document, cleanup_schema):
                    errors.append(f"trial {trial_id} cleanup evidence: {message}")
                cleanup_summary = _object(trial.get("cleanup"))
                _add(errors, cleanup_document.get("run_id") == trial.get("run_id"), f"trial {trial_id} cleanup evidence run id does not match")
                _add(errors, cleanup_document.get("status") == cleanup_summary.get("status") == "PASS", f"trial {trial_id} cleanup evidence did not PASS")
                _add(errors, cleanup_document.get("resources_remaining") == cleanup_summary.get("resources_remaining") == [], f"trial {trial_id} cleanup evidence reports residual resources")
                _add(errors, cleanup_document.get("cleanup_errors") == cleanup_summary.get("cleanup_errors") == [], f"trial {trial_id} cleanup evidence reports cleanup errors")

        provenance_document = None
        if len(provenance_sources) == 1:
            provenance_document = _load_bound_json_source(
                provenance_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} provenance evidence",
                errors=errors,
            )
        if provenance_document is not None:
            _validate_provenance_source(provenance_document, trial, report, refs_by_category, errors)

        timeline_sources = refs_by_category.get("timeline", [])
        if len(timeline_sources) == 1:
            timeline_document = _load_bound_json_source(
                timeline_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} timeline evidence",
                errors=errors,
            )
            if timeline_document is not None:
                _validate_timeline_source(timeline_document, trial, errors)

        resource_sources = refs_by_category.get("resource", [])
        if len(resource_sources) == 1:
            resource_document = _load_bound_json_source(
                resource_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} resource evidence",
                errors=errors,
            )
            if resource_document is not None:
                allow_initial_membership_transitions = (
                    not fault_trial and "soak" not in str(trial.get("cell_id", ""))
                )
                resource_documents[str(trial_id)] = _validate_resource_source(
                    resource_document,
                    trial,
                    fault_trial=fault_trial,
                    allow_initial_membership_transitions=allow_initial_membership_transitions,
                    state_document=state_document,
                    errors=errors,
                )

        topology_facts: dict[str, Any] | None = None
        topology_document: dict[str, Any] | None = None
        topology_sources = refs_by_category.get("topology", [])
        if len(topology_sources) == 1:
            topology_document = _load_bound_json_source(
                topology_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} topology evidence",
                errors=errors,
            )
            if topology_document is not None:
                topology_facts = _validate_topology_source(topology_document, trial, errors)

        workload_sources = refs_by_category.get("workload", [])
        if len(workload_sources) == 1:
            workload_document = _load_bound_json_source(
                workload_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} workload evidence",
                errors=errors,
            )
            if workload_document is not None:
                _validate_workload_source(
                    workload_document,
                    trial,
                    fault_trial=fault_trial,
                    topology_facts=topology_facts,
                    errors=errors,
                )

        command_sources = refs_by_category.get("command_log", [])
        if len(command_sources) == 1:
            command_rows = _load_bound_jsonl_source(
                command_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} command evidence",
                errors=errors,
            )
            if command_rows is not None:
                _validate_command_source(command_rows, trial, fault_trial=fault_trial, errors=errors)

        fault_sources = refs_by_category.get("fault", [])
        if fault_trial and len(fault_sources) == 1:
            fault_document = _load_bound_json_source(
                fault_sources[0],
                artifacts_dir=artifacts_dir,
                label=f"trial {trial_id} fault evidence",
                errors=errors,
            )
            if fault_document is not None:
                _validate_fault_source(
                    fault_document,
                    trial,
                    topology_document=topology_document,
                    state_document=state_document,
                    errors=errors,
                )
        if evidence_root is not None:
            for ref in refs:
                path, path_error = _safe_source_path(artifacts_dir, ref.get("path"))
                if path_error:
                    errors.append(f"trial {trial_id}: {path_error}")
                elif path is not None and not path.is_relative_to(evidence_root):
                    errors.append(f"trial {trial_id} source is outside its evidence_root: {ref.get('path')!r}")

    for pair in (_object(value) for value in _array(report.get("pairs"))):
        pair_id = pair.get("pair_id", "MISSING")
        baseline = resource_documents.get(str(pair.get("baseline_trial_id")))
        candidate = resource_documents.get(str(pair.get("candidate_trial_id")))
        if baseline is None or candidate is None:
            continue
        candidate_trial = trials_by_id.get(str(pair.get("candidate_trial_id")), {})
        candidate_cell = cells_by_id.get(str(candidate_trial.get("cell_id")), {})
        allow_candidate_safety_failure = (
            allow_discovery_safety_rejections
            and candidate_trial.get("arm") == "candidate"
            and candidate_cell.get("campaign_step") == "discovery"
            and candidate_cell.get("status") == "FAIL"
            and not _trial_safety_clean(candidate_trial)
        )
        for message in _validate_equal_resource_window_facts(
            baseline,
            candidate,
            allow_candidate_safety_failure=allow_candidate_safety_failure,
        ):
            errors.append(f"pair {pair_id} resource window: {message}")

    intervals = sorted((start, end, trial_id) for trial_id, (start, end) in attempt_bounds.items())
    _add(
        errors,
        len(intervals) == len(_array(report.get("trials")))
        and all(left_end <= right_start for (_left_start, left_end, _left_id), (right_start, _right_end, _right_id) in zip(intervals, intervals[1:])),
        "trial attempt windows overlap or do not cover every completed trial",
    )
    for pair in (_object(value) for value in _array(report.get("pairs"))):
        order = pair.get("order")
        first_id = pair.get("baseline_trial_id") if order == "AB" else pair.get("candidate_trial_id")
        second_id = pair.get("candidate_trial_id") if order == "AB" else pair.get("baseline_trial_id")
        first = attempt_bounds.get(str(first_id))
        second = attempt_bounds.get(str(second_id))
        _add(
            errors,
            first is not None and second is not None and first[1] <= second[0],
            f"pair {pair.get('pair_id', 'MISSING')} did not cleanup its first arm before starting its second arm",
        )

    top_pairs = [(row.get("category"), row.get("path"), row.get("sha256")) for row in top_refs]
    trial_pairs = [(row.get("category"), row.get("path"), row.get("sha256")) for row in trial_refs]
    _add(errors, _all_unique(top_pairs), "top-level source_refs contain duplicates")
    _add(errors, _all_unique(trial_pairs), "trial source references contain duplicates")
    _add(errors, set(trial_pairs).issubset(set(top_pairs)), "top-level source_refs do not cover every trial source")
    extra_top_refs = set(top_pairs) - set(trial_pairs)
    _add(
        errors,
        bool(preflight_documents)
        and all(category == "preflight" for category, _path, _digest in extra_top_refs)
        and len(extra_top_refs) == len(preflight_documents),
        "top-level non-trial sources must be exactly the bound current preflights",
    )
    for ref in top_refs:
        relative = ref.get("path")
        expected = ref.get("sha256")
        path, path_error = _safe_source_path(artifacts_dir, relative)
        if path_error:
            errors.append(path_error)
            continue
        if not isinstance(expected, str) or SHA256_RE.fullmatch(expected) is None:
            errors.append(f"source {relative!r} has an invalid sha256")
            continue
        if path is None or not path.is_file() or path.is_symlink():
            errors.append(f"source {relative!r} is missing, not a regular file, or a symlink")
            continue
        if path.name in {REPORT_NAME, "result.json"}:
            errors.append(f"source {relative!r} cannot self-attest the admission result")
            continue
        if _file_digest(path) != expected:
            errors.append(f"source {relative!r} sha256 does not match")
    return list(dict.fromkeys(errors))


def _validate_blocked_report(
    report: Mapping[str, Any],
    *,
    expected_kind: str,
    expected_invocation_run_id: str,
) -> list[str]:
    errors = _validate_required_shape(report)
    _add(errors, report.get("status") == "BLOCKED", "blocked report status is not BLOCKED")
    _add(errors, report.get("experiment_kind") == expected_kind, "blocked report experiment kind is wrong")
    _add(errors, report.get("campaign_id") == expected_invocation_run_id == report.get("invocation_run_id"), "blocked report is not attributable to this invocation")
    _add(errors, report.get("real_valkey") is False, "blocked report cannot claim real Valkey execution")
    _add(errors, report.get("execution_mode") == "not-run", "blocked report execution mode must be not-run")
    _add(errors, report.get("started_trial_ids") == [] and report.get("trials") == [] and report.get("pairs") == [] and report.get("cells") == [], "blocked report cannot contain partial performance samples")
    _add(errors, report.get("invalid_samples") == [], "blocked report cannot hide invalid samples")
    reasons = _array(report.get("errors"))
    _add(errors, bool(reasons) and all(isinstance(reason, str) and reason.startswith("ENVIRONMENT_BLOCKED:") for reason in reasons), "BLOCKED is reserved for explicit pre-execution environment blockers")
    criterion_rows = [_object(row) for row in _array(report.get("criterion_results"))]
    _add(errors, {row.get("criterion_id") for row in criterion_rows} == CRITERIA_BY_KIND[expected_kind], "blocked criterion result set is incomplete")
    _add(errors, all(row.get("status") == "BLOCKED" for row in criterion_rows), "blocked criterion results must all be BLOCKED")
    try:
        expected_digest = report_digest(report)
    except (TypeError, ValueError):
        expected_digest = ""
    _add(errors, report.get("report_digest") == expected_digest, "blocked report digest is invalid")
    return list(dict.fromkeys(errors))


def _validate_selection(report: Mapping[str, Any], args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    selected = _object(report.get("selected_candidate"))
    defaults = _object(report.get("current_defaults"))
    if args.mode in {"formation", "stability"}:
        requested = args.selected_strategy
        expected = defaults.get("cluster_create_strategy") if requested == "current-default" else requested
        requested_parallelism = getattr(args, "selected_parallelism", "current-default")
        expected_parallelism: Any = None
        if expected == "tree_meet_addslotsrange":
            if requested_parallelism == "current-default":
                expected_parallelism = selected.get("bounded_parallelism")
            else:
                try:
                    expected_parallelism = int(requested_parallelism)
                except (TypeError, ValueError):
                    errors.append("selected parallelism must be current-default or an integer")
        if args.mode == "formation":
            _add(errors, selected.get("kind") == "cluster_create_strategy" and selected.get("value") == expected and selected.get("bounded_parallelism") == expected_parallelism, "selected formation strategy or parallelism does not match the Check parameters")
    if args.mode in {"failover", "stability"}:
        requested_timeout = args.selected_timeout_ms
        expected_timeout: Any = defaults.get("cluster_node_timeout_ms")
        if requested_timeout != "current-default":
            try:
                expected_timeout = int(requested_timeout)
            except (TypeError, ValueError):
                errors.append("selected timeout must be current-default or an integer")
        if args.mode == "failover":
            _add(errors, selected.get("kind") == "cluster_node_timeout_ms" and selected.get("value") == expected_timeout, "selected failover timeout does not match the Check parameter")
    if args.mode == "stability":
        requested_strategy = args.selected_strategy
        expected_strategy = defaults.get("cluster_create_strategy") if requested_strategy == "current-default" else requested_strategy
        _add(
            errors,
            selected.get("kind") == "selected_settings"
            and selected.get("cluster_create_strategy") == expected_strategy
            and selected.get("cluster_node_timeout_ms") == expected_timeout,
            "selected stability settings do not match the Check parameters",
        )
        if expected_strategy == "tree_meet_addslotsrange":
            _add(errors, selected.get("bounded_parallelism") == expected_parallelism, "selected stability parallelism does not match the Check parameter")
    return errors


def _write_result(path: Path, status: str, summary: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"status": status, "summary": summary}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _authorized(run_id: str) -> bool:
    value = os.environ.get(AUTHORIZATION_ENV, "").strip()
    return value in {"1", run_id}


def _forbidden_evidence_root(path: Path) -> bool:
    return bool(
        {part.lower() for part in path.resolve().parts}.intersection(
            FORBIDDEN_EVIDENCE_PATH_PARTS
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)

    def common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--run-id", required=True)
        subparser.add_argument("--artifacts-dir", type=Path, required=True)
        subparser.add_argument("--result-path", type=Path, required=True)

    formation = subparsers.add_parser("formation")
    common(formation)
    formation.add_argument("--selected-strategy", required=True)
    formation.add_argument("--selected-parallelism", default="current-default")

    failover = subparsers.add_parser("failover")
    common(failover)
    failover.add_argument("--selected-timeout-ms", required=True)

    stability = subparsers.add_parser("stability")
    common(stability)
    stability.add_argument("--selected-strategy", required=True)
    stability.add_argument("--selected-parallelism", default="current-default")
    stability.add_argument("--selected-timeout-ms", required=True)
    return parser


def run(args: argparse.Namespace) -> tuple[str, str]:
    if _forbidden_evidence_root(args.artifacts_dir):
        return "FAIL", "M2 artifacts directory names forbidden fixture, historical, retained, or loop evidence"
    if not _authorized(args.run_id):
        return (
            "BLOCKED",
            f"real M2 matrix requires explicit {AUTHORIZATION_ENV}=1 (or this Gate run id); no trial was started",
        )
    artifacts_dir = args.artifacts_dir.resolve()
    report_path = artifacts_dir / REPORT_NAME
    trials_path = artifacts_dir / "trials"
    if report_path.exists() or trials_path.exists():
        return "FAIL", "refusing pre-existing M2 report or trial directory"
    capture_status, capture_summary = capture_current_invocation(args)
    if not report_path.is_file() or report_path.is_symlink():
        return "FAIL", f"current invocation did not produce {REPORT_NAME}: {capture_summary}"
    try:
        report_value = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "FAIL", f"cannot read current M2 report: {exc}"
    if not isinstance(report_value, dict):
        return "FAIL", "current M2 report is not a JSON object"
    report: dict[str, Any] = report_value
    if report.get("status") != capture_status:
        return "FAIL", "capture status does not match the current-invocation report"
    if report.get("status") == "BLOCKED":
        errors = _validate_blocked_report(
            report,
            expected_kind=args.mode,
            expected_invocation_run_id=args.run_id,
        )
        errors.extend(validate_current_invocation_sources(report, artifacts_dir=artifacts_dir))
        if errors:
            return "FAIL", "; ".join(errors[:8])
        return "BLOCKED", "; ".join(str(reason) for reason in report.get("errors", []))

    errors = validate_report(
        report,
        expected_kind=args.mode,
        expected_invocation_run_id=args.run_id,
    )
    errors.extend(_validate_selection(report, args))
    errors.extend(validate_current_invocation_sources(report, artifacts_dir=artifacts_dir))
    errors = list(dict.fromkeys(errors))
    if errors:
        return "FAIL", "; ".join(errors[:8])
    return "PASS", f"validated {len(report.get('trials', []))} current real-Valkey trials"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if _forbidden_evidence_root(args.result_path):
        return 2
    try:
        status, summary = run(args)
    except Exception as exc:  # noqa: BLE001 - command+json must remain machine-readable
        status, summary = "FAIL", f"M2 admission raised {type(exc).__name__}: {exc}"
    _write_result(args.result_path, status, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
