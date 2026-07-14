"""Report generation entry points."""
from valkey_scale_lab.report.final import FinalReportError, build_final_report
from valkey_scale_lab.report.render import ReportError, render_report
from valkey_scale_lab.report.validated import (
    REPORT_SCHEMA_VERSION,
    REQUIRED_SURFACES,
    ValidatedReport,
    ValidatedReportError,
    render_validated_report,
)

__all__ = [
    "FinalReportError",
    "REPORT_SCHEMA_VERSION",
    "REQUIRED_SURFACES",
    "ReportError",
    "ValidatedReport",
    "ValidatedReportError",
    "build_final_report",
    "render_report",
    "render_validated_report",
]
