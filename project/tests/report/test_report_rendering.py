from __future__ import annotations

import json
from pathlib import Path

import pytest

from valkey_scale_lab.report import render_report


def test_report_renderer_writes_index_tables_chart_and_run_summary(tmp_path: Path) -> None:
    analysis = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "capability_id": "analysis_reporting",
        "run_id": "analysis_reporting-run",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "test", "version": "v1"},
        "status": "PASS",
        "source": {"capability_id": "fault_matrix"},
        "findings": [{"name": "failover", "status": "PASS"}],
        "metrics": [
            {"name": "failover_latency_ms", "status": "PASS", "value": 10.0, "unit": "ms"},
            {"name": "split_brain_duration_ms", "status": "MISSING", "value": None, "unit": "ms"},
        ],
        "missing_metrics": [
            {"metric": "split_brain_duration_ms", "status": "MISSING", "reason": "not measured"}
        ],
        "baseline_comparison": {
            "comparisons": [
                {
                    "metric": "failover_latency_ms",
                    "current_value": 10.0,
                    "baseline_value": None,
                    "delta": None,
                    "unit": "ms",
                    "status": "NO_BASELINE_YET",
                }
            ]
        },
        "command_audit": {
            "status": "PASS",
            "command_log_ref": "command_log.jsonl",
            "total_commands": 2,
            "by_command_kind": {"cluster_probe": 1, "cleanup": 1},
            "slowest_commands_topN": [
                {"command_id": "cmd-000001", "operation_id": "cluster_setup", "step_id": "cluster_probe", "command_kind": "cluster_probe", "duration_ms": 5, "status": "PASS", "exit_code": 0, "retry_index": 0}
            ],
            "failed_commands": [],
            "retry_commands": [],
        },
    }
    analysis_path = tmp_path / "analysis_summary.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    index = render_report(analysis_path, tmp_path / "report", tmp_path / "report_index.json")

    report_paths = {Path(item["path"]).name for item in index["reports"]}
    assert {
        "index.html",
        "report.md",
        "metrics.csv",
        "missing_metrics.csv",
        "baseline_comparison.csv",
        "metric_chart.svg",
        "setup_lifecycle_durations.csv",
        "setup_slowest_nodes.csv",
        "setup_waterfall.svg",
        "command_slowest.csv",
        "command_failures.csv",
        "command_retries.csv",
        "management_ops_matrix.csv",
        "management_operation_durations.csv",
        "management_topology_diffs.csv",
        "management_rolling_restart.csv",
        "management_reshard_rebalance.csv",
        "workload_benchmark_windows.csv",
        "workload_profile_summary.csv",
        "fault_timeline_events.csv",
        "fault_timeline_summary.csv",
        "failover_latency_distribution.csv",
        "split_brain_windows.csv",
        "fault_workload_impact.csv",
        "command_latency.svg",
        "management_operation_duration.svg",
        "management_topology_diff.svg",
        "workload_qps_p99_error.svg",
        "fault_timeline.svg",
        "failover_latency_distribution.svg",
        "split_brain_window.svg",
        "fault_workload_impact.svg",
        "resource_analysis_by_window.csv",
        "resource_analysis_abnormal_nodes.csv",
        "resource_trends.svg",
    } == report_paths
    assert "command_audit_report_inputs" in index
    assert "management_report_inputs" in index
    assert "workload_report_inputs" in index
    assert "fault_timeline_report_inputs" in index
    assert "resource_analysis_report_inputs" in index
    assert index["offline_policy"]["artifact_only"] is True
    assert index["offline_policy"]["llm_used"] is False
    assert index["conclusion_summary"]["source"] == "artifact_derived"
    assert (tmp_path / "report" / "exports" / "metrics.csv").exists()
    assert (tmp_path / "report" / "assets" / "metric_chart.svg").exists()
    assert (tmp_path / "run_summary.json").exists()
    assert "MISSING" in (tmp_path / "report" / "missing_metrics.csv").read_text(encoding="utf-8")
    assert "慢命令 TopN" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "Workload 基准压测" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "故障 Timeline" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "资源观测趋势" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    assert "结论摘要" in (tmp_path / "report" / "report.md").read_text(encoding="utf-8")


def test_report_renderer_marks_empty_missing_metrics_as_none(tmp_path: Path) -> None:
    analysis = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "capability_id": "analysis_reporting",
        "run_id": "analysis_reporting-empty-missing",
        "created_at": "2026-06-28T00:00:00Z",
        "producer": {"name": "test", "version": "v1"},
        "status": "PASS",
        "source": {"capability_id": "fault_matrix"},
        "findings": [],
        "metrics": [{"name": "cluster_state_ok", "status": "PASS", "value": 1, "unit": "bool"}],
        "missing_metrics": [],
        "baseline_comparison": {"comparisons": []},
    }
    analysis_path = tmp_path / "analysis_summary.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    render_report(analysis_path, tmp_path / "report", tmp_path / "report_index.json")

    markdown = (tmp_path / "report" / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")
    assert "- none" in markdown
    assert '<tr><td colspan="3">none</td></tr>' in html


# --- full-flow adapter -------------------------------------------------------
#
# A gate run leaves artifacts; the renderer reads an analysis document. The two
# vocabularies shared three keys, so rendering a correct 50-node run produced a
# report whose every section said MISSING and whose command audit said
# `total_commands: 0` - from a run that issued 4,528 commands.

import json as _json
from pathlib import Path as _Path

from valkey_scale_lab.report.full_flow import build_renderable_analysis


def _fake_run(root: _Path) -> _Path:
    """The smallest run directory that exercises every section of the adapter."""

    runtime = root / "runtime"
    (runtime / "command_audit").mkdir(parents=True)
    w = lambda name, doc: (runtime / name).write_text(_json.dumps(doc), encoding="utf-8")

    w("analysis_summary.json", {
        "run_id": "run-1", "created_at": "2026-01-01T00:00:00Z", "capability_id": "local_full_flow",
        "scenario_name": "local_full_flow", "node_count": 50, "status": "PASS",
        "management_status": "PASS", "fault_status": "PASS",
        "recovery": {"cluster_state": "ok", "known_nodes": 50}, "missing_evidence": [],
    })
    w("run_verdict.json", {"status": "PASS"})
    w("cleanup_report.json", {"status": "PASS", "resources_remaining": [], "cleanup_actions": [{}, {}]})
    w("runtime_timing_breakdown_local_full_flow.json", {"timings": [
        {"name": "fast_stage", "duration_seconds": 0.5, "status": "PASS"},
        {"name": "slow_stage", "duration_seconds": 2.0, "status": "PASS"},
        {"name": "unmeasured_stage", "duration_seconds": "MISSING", "status": "MISSING"},
    ]})
    w("command_audit/command_audit_summary.json", {
        "by_command_kind": {"cluster_probe": 2}, "failed_commands": [], "retry_commands": [],
        "pass_count": 2, "failure_count": 0, "retry_count": 0,
    })
    (runtime / "command_audit/command_log.jsonl").write_text(
        "\n".join(_json.dumps(r) for r in [
            {"command_id": "c1", "command_kind": "cluster_probe", "duration_ms": 10, "status": "PASS"},
            {"command_id": "c2", "command_kind": "cluster_probe", "duration_ms": 90, "status": "PASS"},
        ]) + "\n", encoding="utf-8")
    w("management_sequence.json", {"result": {"operation_status": "PASS", "operations": [
        {"operation_name": "reshard_slot_range", "operation_id": "op-1", "operation_duration_ms": 100.0,
         "operation_status": "PASS", "command_count": 8, "error_count": 0, "retry_count": 0,
         "topology_diff": {}, "cluster_known_nodes_before": 50, "cluster_known_nodes_after": 50, "slots_moved": 4},
    ]}})
    w("workload_windows.json", {"windows": [
        {"profile": "mixed_rw", "window_name": "event", "achieved_qps": 9.4,
         "latency_p99_ms": 77.8, "error_rate": 0.0, "status": "PASS",
         "key_slot_coverage": {"full_slot_covered": False}},
    ]})
    w("fault_sequence.json", {
        "fault_results": [{"id": "replica_stop", "operation_id": "f-1", "status": "REAL_PASS", "duration_ms": 12.0}],
        "failover_details": {"cluster_recovery_latency_ms": 47398.9, "pfail_to_promotion_ms": 1014.1,
                             "client_unavailable_to_recovered_ms": 46718.2, "read_unavailability_ms": 46848.3,
                             "failover_success": True, "replacement_logical_id": "shard-0001-replica-00",
                             "process_gone_to_pfail_ms": 45754.0, "missing_fields": []},
    })
    w("scalable_stability_observation.json", {"resource_analyses": [
        {"sampler_id": "nodehost-az-a-00", "analysis": {"status": "PASS", "process_totals": {"rss": 1}, "warnings": []}},
    ]})
    (runtime / "metrics_timeseries.jsonl").write_text(
        _json.dumps({"metric_name": "m", "metric_value": 1, "metric_unit": "ms", "source_type": "x"}) + "\n",
        encoding="utf-8")
    return runtime


def test_a_full_flow_run_renders_a_report_that_is_not_all_missing(tmp_path: _Path) -> None:
    """The defect this adapter exists for, asserted on the numbers it recovers."""

    analysis = build_renderable_analysis(_fake_run(tmp_path))

    # The three sections that were empty on a correct run.
    assert analysis["command_audit"]["total_commands"] == 2
    assert analysis["command_audit"]["slowest_commands_topN"][0]["command_id"] == "c2"
    assert analysis["management_ops"]["duration_ranking_topN"][0]["operation_name"] == "reshard_slot_range"
    assert analysis["workload_benchmark"]["windows"][0]["latency_p99_ms"] == 77.8

    # Stage durations are converted seconds -> ms, ranked, and a stage the run
    # recorded as MISSING stays MISSING rather than sorting as a zero.
    ranking = analysis["setup_aggregates"]["stage_duration_ranking"]
    assert ranking[0] == {"metric": "slow_stage", "value_ms": 2000.0, "status": "PASS"}
    assert ranking[-1]["value_ms"] == "MISSING"

    assert analysis["status"] == "PASS"
    assert {f["name"] for f in analysis["findings"]} >= {"run_verdict", "cleanup", "fault"}


def test_the_report_never_attributes_one_measurement_to_nine_scenarios(tmp_path: _Path) -> None:
    """The fabrication an earlier draft of this adapter shipped.

    `failover_details` is one measurement taken by the primary-kill lane. Copying
    it onto every fault scenario read as nine measured client outages that were
    never measured - and nine identical numbers are exactly what a reviewer would
    have skimmed past. Each scenario reports its own duration; the outage fields
    say MISSING with a reason and point at the section that does measure them.
    """

    analysis = build_renderable_analysis(_fake_run(tmp_path))
    fault = analysis["fault_timeline"]

    row = fault["rows"][0]
    assert row["metrics"]["duration_ms"] == 12.0
    assert row["metrics"]["client_unavailability_ms"]["status"] == "MISSING"
    assert "Failover" in row["metrics"]["client_unavailability_ms"]["reason"]

    # The real measurement is still reported, once, where it belongs.
    assert fault["failover_latency"]["max_ms"] == 47398.9
    assert fault["client_unavailability"]["p50_ms"] == 46718.2
    # And a single failover is declared as one sample, so nobody reads p95 as a
    # distribution over nine.
    assert fault["failover_latency"]["sample_count"] == 1


def test_an_absent_source_is_a_stated_reason_and_never_a_zero(tmp_path: _Path) -> None:
    """An empty run must not render as a healthy one."""

    runtime = tmp_path / "empty" / "runtime"
    runtime.mkdir(parents=True)

    analysis = build_renderable_analysis(runtime)

    for section in ("setup_aggregates", "command_audit", "management_ops",
                    "workload_benchmark", "fault_timeline", "resource_analysis"):
        assert analysis[section]["status"] == "SKIPPED_WITH_REASON", section
        assert analysis[section]["reason"], section
    assert analysis["status"] == "MISSING"


def test_the_html_summary_renders_values_rather_than_template_text(tmp_path) -> None:
    """The summary strip is inside an f-string, so a doubled brace ships as text.

    Written after exactly that: `{{status_class}}` renders the literal characters
    instead of the value, and every figure in the strip read as template source in
    the delivered report. Nothing else in the page would have looked wrong, so the
    check is that no unexpanded interpolation survives anywhere in the document.
    """

    analysis = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "status": "PASS",
        "source": {"capability_id": "local_full_flow"},
        "run_metadata": {"run_id": "r"},
        "findings": [],
        "command_audit": {"total_commands": 4440, "failure_count": 4, "retry_count": 0},
        "setup_aggregates": {},
        "management_ops": {},
        "workload_benchmark": {},
        "fault_timeline": {},
        "resource_analysis": {},
        "missing_metrics": [],
        "baseline_comparison": {"comparisons": []},
    }
    analysis_path = tmp_path / "analysis_summary.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    render_report(analysis_path, tmp_path / "report", tmp_path / "report_index.json")
    page = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")

    assert "{" not in page.split("<style>")[0] + page.split("</style>")[-1], (
        "an unexpanded f-string interpolation reached the rendered page"
    )
    summary = page.split('<dl class="verdict">')[1].split("</dl>")[0]
    assert ">PASS<" in summary
    assert ">4440<" in summary
    assert "local_full_flow" in summary


def test_the_report_page_has_no_external_dependency(tmp_path) -> None:
    """The whole point: a host with no internet must still render this report.

    Fonts, styles and charts are local or system, so the page carries no scheme,
    no protocol-relative reference and no CDN host.
    """

    analysis = {
        "schema_version": "v1",
        "artifact_type": "analysis_summary",
        "status": "PASS",
        "source": {"capability_id": "local_full_flow"},
        "run_metadata": {"run_id": "r"},
        "findings": [],
        "command_audit": {},
        "setup_aggregates": {},
        "management_ops": {},
        "workload_benchmark": {},
        "fault_timeline": {},
        "resource_analysis": {},
        "missing_metrics": [],
        "baseline_comparison": {"comparisons": []},
    }
    analysis_path = tmp_path / "analysis_summary.json"
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
    render_report(analysis_path, tmp_path / "report", tmp_path / "report_index.json")
    page = (tmp_path / "report" / "index.html").read_text(encoding="utf-8")

    for forbidden in ("http:", "https:", "cdn.", "googleapis", "unpkg", "jsdelivr"):
        assert forbidden not in page, forbidden
    # A protocol-relative reference is the one an external-URL scan misses most
    # easily, and the contract script rejects it too.
    assert "//" not in page


# --- the report says the same thing in two languages -----------------------


def _cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def test_every_message_carries_both_languages_and_says_something() -> None:
    """A key present in one language and absent in the other is the failure mode.

    The catalog is the only place either language is written, so a key that
    exists for one and not the other produces a report that is half translated
    rather than one that fails to build - and half translated reads as a
    rendering defect to whoever opens it.
    """

    from valkey_scale_lab.report import messages as messages_module

    tables = {lang: messages_module.messages(lang) for lang in messages_module.LANGUAGES}
    keys = {lang: set(table) for lang, table in tables.items()}
    assert keys["zh"] == keys["en"], keys["zh"].symmetric_difference(keys["en"])
    for lang, table in tables.items():
        empty = sorted(key for key, value in table.items() if not value.strip())
        assert empty == [], (lang, empty)

    # Every named field of a zh template must exist in the en one, or the
    # translation drops a number the reader was meant to see.
    import string

    for key in keys["zh"]:
        fields = {
            lang: {
                name
                for _, name, _, _ in string.Formatter().parse(tables[lang][key])
                if name
            }
            for lang in tables
        }
        assert fields["zh"] == fields["en"], (key, fields)


def test_an_unknown_language_is_refused_rather_than_defaulted() -> None:
    """Defaulting would produce a report in a language nobody asked for.

    The artifact carries no note of which was requested, so a reader could not
    tell a silent fallback from a deliberate choice.
    """

    from valkey_scale_lab.report import messages as messages_module

    with pytest.raises(messages_module.UnknownLanguage):
        messages_module.messages("fr")


def test_the_english_report_carries_no_chinese_anywhere(tmp_path: _Path) -> None:
    """Including the reasons, which are written by the adapter rather than the renderer.

    This is what the language has to reach two layers for: the prose an absence
    states is produced where the absence is found, so rendering alone in English
    would leave every `SKIPPED_WITH_REASON` in Chinese.
    """

    from valkey_scale_lab.report.full_flow import build_renderable_analysis
    from valkey_scale_lab.report.render import render_report

    runtime = _fake_run(tmp_path)
    out = tmp_path / "en"
    out.mkdir()
    analysis = build_renderable_analysis(runtime, lang="en")
    path = out / "renderable_analysis.json"
    path.write_text(_json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    render_report(path, out, out / "report_index.json", lang="en")

    offenders = [
        item.name
        for item in sorted(out.rglob("*"))
        if item.is_file() and _cjk(item.read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == [], offenders


def test_both_languages_report_the_same_numbers(tmp_path: _Path) -> None:
    """The language chooses sentences and nothing else.

    Same file names and byte-identical data exports, so two renderings of one run
    are comparable rather than two separate reports. If a translation ever moved
    a number, this is what would catch it.
    """

    from valkey_scale_lab.report.full_flow import build_renderable_analysis
    from valkey_scale_lab.report.render import render_report

    runtime = _fake_run(tmp_path)
    rendered = {}
    for lang in ("zh", "en"):
        out = tmp_path / f"report-{lang}"
        out.mkdir()
        analysis = build_renderable_analysis(runtime, lang=lang)
        path = out / "renderable_analysis.json"
        path.write_text(_json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        render_report(path, out, out / "report_index.json", lang=lang)
        rendered[lang] = out

    names = {
        lang: sorted(item.relative_to(out).as_posix() for item in out.rglob("*") if item.is_file())
        for lang, out in rendered.items()
    }
    assert names["zh"] == names["en"]

    # The data-only exports carry no prose at all, so they must match byte for
    # byte. `split_brain_windows.csv` and `fault_timeline_events.csv` do carry a
    # reason column and are deliberately not in this list.
    for name in ["metrics.csv", "command_slowest.csv", "management_ops_matrix.csv"]:
        assert (rendered["zh"] / name).read_bytes() == (rendered["en"] / name).read_bytes(), name


def test_rendering_an_analysis_in_the_other_language_is_refused(tmp_path: _Path) -> None:
    """Half of the report would be translated and half would not.

    The reasons live in the analysis; the headings live in the renderer. Mixing
    them produces a page that looks broken rather than one that says what it is.
    """

    from valkey_scale_lab.report.full_flow import build_renderable_analysis
    from valkey_scale_lab.report.render import ReportError, render_report

    runtime = _fake_run(tmp_path)
    out = tmp_path / "mixed"
    out.mkdir()
    path = out / "renderable_analysis.json"
    path.write_text(
        _json.dumps(build_renderable_analysis(runtime, lang="en"), ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ReportError, match="build the analysis in the language"):
        render_report(path, out, out / "report_index.json", lang="zh")


def test_an_analysis_from_before_the_language_field_still_renders(tmp_path: _Path) -> None:
    """Every run taken before this change has no `language`, and must stay renderable.

    Refusing it would make old runs unrenderable for a field they could not have
    carried, which is a worse outcome than rendering them as asked.
    """

    from valkey_scale_lab.report.full_flow import build_renderable_analysis
    from valkey_scale_lab.report.render import render_report

    runtime = _fake_run(tmp_path)
    out = tmp_path / "legacy"
    out.mkdir()
    analysis = build_renderable_analysis(runtime, lang="zh")
    analysis.pop("language")
    path = out / "renderable_analysis.json"
    path.write_text(_json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

    render_report(path, out, out / "report_index.json", lang="zh")
    assert (out / "report.md").is_file()


def test_the_gate_renders_a_report_in_every_language_it_knows() -> None:
    """A mechanism implemented, tested, and not switched on is the shape to guard against.

    Asserted on the call site rather than on the helper, because the helper
    working proves nothing about the run producing both.
    """

    import ast
    from pathlib import Path as _P

    from valkey_scale_lab.gates import real as gates_real

    source = _P(gates_real.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_render_run_report"
    )
    loops = [node for node in ast.walk(function) if isinstance(node, ast.For)]
    assert loops, "the gate renders one language and not every one"
    assert any(
        isinstance(loop.iter, ast.Name) and loop.iter.id == "LANGUAGES" for loop in loops
    ), "the gate must iterate the catalog's languages rather than a list of its own"
