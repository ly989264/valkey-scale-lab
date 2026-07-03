"""Report generation entry points."""
from valkey_scale_lab.report.final import FinalReportError, build_final_goal_loop_report
from valkey_scale_lab.report.render import ReportError, render_report

__all__ = ["FinalReportError", "ReportError", "build_final_goal_loop_report", "render_report"]
