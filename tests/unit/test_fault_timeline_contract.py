from __future__ import annotations

import pytest

from valkey_scale_lab.observer.failover_timeline import (
    FailoverTimelineError,
    M1_REQUIRED_TIMELINE_EVENTS,
    build_failover_latency_sample_from_timeline,
    build_fault_timeline_report,
    derive_fault_timeline_metrics,
    make_fault_timeline_event,
)


def test_fault_timeline_derives_required_metrics_without_cleanup_substitution() -> None:
    events = _events()
    metrics = derive_fault_timeline_metrics(events, {"fault_metrics": {"client_unavailability_ms": 45, "split_brain_window_ms": 0, "cluster_down_window_ms": 12}})

    assert metrics["apply_duration_ms"] == 10
    assert metrics["failover_latency_ms"] == 20
    assert metrics["cleanup_duration_ms"] == 10
    assert metrics["client_unavailability_ms"] == 45

    report = build_fault_timeline_report(events, phase_id="M1-S06", run_id="run", workload_windows={"fault_metrics": {"client_unavailability_ms": 45, "split_brain_window_ms": 0, "cluster_down_window_ms": 12}})
    sample = build_failover_latency_sample_from_timeline(report["fault_rows"][0])
    assert sample["derived_from_timeline"] is True
    assert sample["timeline_ref"].startswith("fault_timeline_events.jsonl#")


def test_missing_effect_observed_requires_reason_and_propagates_missing_metric() -> None:
    events = _events(missing_event="fault_effect_observed")
    metrics = derive_fault_timeline_metrics(events, {})

    assert metrics["effect_observed_delay_ms"]["status"] == "MISSING"
    assert "fault_effect_observed" in metrics["effect_observed_delay_ms"]["reason"]


def test_observed_events_must_be_monotonic() -> None:
    events = _events()
    events[4]["monotonic_ms"] = events[3]["monotonic_ms"] - 1

    with pytest.raises(FailoverTimelineError, match="monotonic"):
        derive_fault_timeline_metrics(events, {})


def test_unobserved_event_without_reason_is_rejected() -> None:
    with pytest.raises(FailoverTimelineError, match="requires reason"):
        make_fault_timeline_event(
            phase_id="M1-S06",
            run_id="run",
            scenario_name="scenario",
            sample_id="sample",
            fault_id="fault",
            fault_type="primary_stop_failover",
            node_count=6,
            scale_rung="small",
            event_name="fault_effect_observed",
            event_status="MISSING",
        )


def _events(missing_event: str | None = None) -> list[dict]:
    rows = []
    for index, event_name in enumerate(M1_REQUIRED_TIMELINE_EVENTS):
        status = "MISSING" if event_name == missing_event else "OBSERVED"
        rows.append(
            make_fault_timeline_event(
                phase_id="M1-S06",
                run_id="run",
                scenario_name="scenario",
                sample_id="sample",
                fault_id="fault",
                fault_type="primary_stop_failover",
                node_count=6,
                scale_rung="small",
                event_name=event_name,
                event_status=status,
                timestamp_unix_ms=1800000000000 + index * 10 if status == "OBSERVED" else None,
                monotonic_ms_value=1000 + index * 10 if status == "OBSERVED" else None,
                reason="effect was not observed by probe" if status == "MISSING" else "",
            )
        )
    return rows
