from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from valkey_scale_lab.evidence import ArtifactRecord, MISSING_STATUSES

if TYPE_CHECKING:
    from valkey_scale_lab.analysis import ValidatedAnalysis


REPORT_SCHEMA_VERSION = "valkey-scale-lab-validated-report-v1"
REQUIRED_SURFACES = (
    "topology",
    "lifecycle_timing",
    "bottlenecks",
    "resources",
    "workload_impact",
    "management_operations",
    "failover",
    "recovery",
    "errors",
    "cleanup",
    "missing_evidence",
)


class ValidatedReportError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedReport:
    root: Path
    index_path: Path
    index_sha256: str
    report_digest: str
    run_digest: str
    document: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())
        object.__setattr__(self, "index_path", self.index_path.resolve())
        object.__setattr__(self, "document", _freeze_json(self.document))


def render_validated_report(
    analysis: "ValidatedAnalysis", out_dir: str | Path
) -> ValidatedReport:
    """Render deterministic derived views from a validated-analysis capability."""
    _require_validated_analysis(analysis)
    output_root = Path(out_dir).resolve()
    evidence_root = analysis.evidence_root.resolve()
    analysis_path = analysis.path.resolve()
    _validate_output_boundary(output_root, evidence_root, analysis_path)
    _validate_analysis_capability(analysis)

    source_rows = tuple(_source_record(record) for record in analysis.source_artifacts)
    surfaces = _json_value(analysis.document["surfaces"])
    provenance_refs = _json_value(analysis.document["provenance_refs"])
    analysis_digests = analysis.document.get("digests")
    run_digest = (
        str(analysis_digests.get("run"))
        if isinstance(analysis_digests, Mapping)
        else ""
    )
    digests = {
        "analysis": analysis.sha256,
        "admission": analysis.admission_digest,
        "definition": analysis.definition_digest,
        "product": analysis.product_digest,
        "run": run_digest,
        "capture": analysis.capture_digest,
        "provenance": analysis.provenance_digest,
    }
    view_document = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "artifact_type": "validated_analysis_derived_view",
        "status": "DERIVED",
        "run_id": analysis.run_id,
        "requested_nodes": analysis.requested_nodes,
        "observed_nodes": analysis.observed_nodes,
        "digests": digests,
        "source_artifacts": source_rows,
        "surfaces": surfaces,
    }

    json_bytes = _json_bytes(view_document)
    markdown_bytes = _render_markdown(view_document).encode("utf-8")
    html_bytes = _render_html(view_document).encode("utf-8")
    csv_bytes = _render_csv(surfaces).encode("utf-8")
    payloads = (
        ("report.json", "json", json_bytes),
        ("report.md", "markdown", markdown_bytes),
        ("index.html", "html", html_bytes),
        ("surfaces.csv", "csv", csv_bytes),
    )
    views = [
        {
            "path": name,
            "format": format_name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "status": "DERIVED",
        }
        for name, format_name, payload in payloads
    ]
    index_without_digest = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "artifact_type": "validated_report_index",
        "status": "DERIVED",
        "run_id": analysis.run_id,
        "requested_nodes": analysis.requested_nodes,
        "observed_nodes": analysis.observed_nodes,
        "offline": True,
        "digests": digests,
        "analysis": {
            "path": Path(os.path.relpath(analysis_path, output_root)).as_posix(),
            "sha256": analysis.sha256,
        },
        "provenance_refs": provenance_refs,
        "source_artifacts": source_rows,
        "missing_data_taxonomy": list(MISSING_STATUSES),
        "surfaces": [
            {
                "id": name,
                "status": surfaces[name]["status"],
                **(
                    {"reason": surfaces[name]["reason"]}
                    if surfaces[name]["status"] in MISSING_STATUSES
                    else {}
                ),
            }
            for name in REQUIRED_SURFACES
        ],
        "surface_statuses": {
            name: surfaces[name]["status"] for name in REQUIRED_SURFACES
        },
        "views": views,
    }
    report_digest = _canonical_digest(index_without_digest)
    index = {**index_without_digest, "report_digest": report_digest}

    protected_before = _protected_hashes(analysis)
    output_root.mkdir(parents=True, exist_ok=True)
    output_paths = {
        name: _safe_output_path(output_root, name)
        for name, _format_name, _payload in payloads
    }
    index_path = _safe_output_path(output_root, "report_index.json")
    for name, _format_name, payload in payloads:
        _write_bytes(output_paths[name], payload)
    _write_bytes(index_path, _json_bytes(index))
    if _protected_hashes(analysis) != protected_before:
        raise ValidatedReportError("report rendering modified a protected analysis or evidence source")

    return ValidatedReport(
        root=output_root,
        index_path=index_path,
        index_sha256=_sha256_file(index_path),
        report_digest=report_digest,
        run_digest=run_digest,
        document=index,
    )


def _require_validated_analysis(value: Any) -> None:
    from valkey_scale_lab.analysis import ValidatedAnalysis

    if not isinstance(value, ValidatedAnalysis):
        raise TypeError("report input must be a ValidatedAnalysis capability")


def _validate_output_boundary(output: Path, evidence: Path, analysis_path: Path) -> None:
    if output == evidence or output.is_relative_to(evidence) or evidence.is_relative_to(output):
        raise ValidatedReportError("report output must be outside the protected evidence root")
    if output == analysis_path or analysis_path.is_relative_to(output):
        raise ValidatedReportError("report output must not contain or replace the analysis source")


def _safe_output_path(root: Path, name: str) -> Path:
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValidatedReportError(f"report output path escapes through a symlink: {name}")
    return path


def _validate_analysis_capability(analysis: "ValidatedAnalysis") -> None:
    errors: list[str] = []
    if not analysis.path.is_file() or _sha256_file(analysis.path) != analysis.sha256:
        errors.append("validated analysis source hash mismatch")
    document = analysis.document
    try:
        stored_document = json.loads(analysis.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"validated analysis source is not readable JSON: {exc}")
    else:
        if stored_document != _json_value(document):
            errors.append("validated analysis capability does not match its source document")
    if document.get("status") != "DERIVED":
        errors.append("validated analysis must have DERIVED status")
    surfaces = document.get("surfaces")
    if not isinstance(surfaces, Mapping):
        errors.append("validated analysis surfaces are required")
    else:
        if set(surfaces) != set(REQUIRED_SURFACES):
            errors.append("validated analysis must contain exactly the required surfaces")
        for name in REQUIRED_SURFACES:
            surface = surfaces.get(name)
            if not isinstance(surface, Mapping):
                errors.append(f"analysis surface {name} must be an object")
                continue
            status = surface.get("status")
            if status not in {"OBSERVED", *MISSING_STATUSES}:
                errors.append(f"analysis surface {name} has invalid status {status!r}")
            if status in MISSING_STATUSES:
                reason = surface.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    errors.append(f"analysis surface {name} missing status requires a reason")
    digests = document.get("digests")
    if not isinstance(digests, Mapping) or not _is_digest(digests.get("run")):
        errors.append("validated analysis requires a run digest")
    elif (
        document.get("run_id") != analysis.run_id
        or document.get("requested_nodes") != analysis.requested_nodes
        or document.get("observed_nodes") != analysis.observed_nodes
        or digests.get("admission") != analysis.admission_digest
        or digests.get("definition") != analysis.definition_digest
        or digests.get("product") != analysis.product_digest
        or digests.get("capture") != analysis.capture_digest
        or digests.get("provenance") != analysis.provenance_digest
    ):
        errors.append("validated analysis metadata does not match its source document")
    provenance_refs = document.get("provenance_refs")
    if not isinstance(provenance_refs, Mapping):
        errors.append("validated analysis provenance references are required")
    else:
        for name in ("capture_manifest", "provenance"):
            ref = provenance_refs.get(name)
            if not isinstance(ref, Mapping):
                errors.append(f"validated analysis {name} reference is required")
                continue
            _validate_referenced_file(
                analysis.evidence_root, ref.get("path"), ref.get("sha256"), name, errors
            )
    source_records = [
        _analysis_source_record(record) for record in analysis.source_artifacts
    ]
    if document.get("source_artifacts") != _freeze_json(source_records):
        errors.append("validated analysis artifact references are incomplete or changed")
    for record in analysis.source_artifacts:
        _validate_source_record(record, analysis.evidence_root, errors)
    if errors:
        raise ValidatedReportError("; ".join(errors))


def _validate_source_record(record: ArtifactRecord, root: Path, errors: list[str]) -> None:
    for label, raw_path, expected in (
        ("artifact", record.path, record.sha256),
        ("raw source", record.source_path, record.source_sha256),
    ):
        path = (root / raw_path).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            errors.append(f"{record.kind} {label} path is missing or unsafe")
        elif _sha256_file(path) != expected:
            errors.append(f"{record.kind} {label} hash mismatch")


def _protected_hashes(analysis: "ValidatedAnalysis") -> dict[Path, str]:
    paths = {analysis.path.resolve()}
    root = analysis.evidence_root.resolve()
    for record in analysis.source_artifacts:
        paths.add((root / record.path).resolve())
        paths.add((root / record.source_path).resolve())
    refs = analysis.document.get("provenance_refs")
    if isinstance(refs, Mapping):
        for ref in refs.values():
            if isinstance(ref, Mapping) and isinstance(ref.get("path"), str):
                paths.add((root / ref["path"]).resolve())
    return {path: _sha256_file(path) for path in sorted(paths) if path.is_file()}


def _validate_referenced_file(
    root: Path,
    raw_path: Any,
    expected_sha256: Any,
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(raw_path, str) or not _is_digest(expected_sha256):
        errors.append(f"validated analysis {label} reference requires path and hash")
        return
    path = (root / raw_path).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        errors.append(f"validated analysis {label} reference is missing or unsafe")
    elif _sha256_file(path) != expected_sha256:
        errors.append(f"validated analysis {label} reference hash mismatch")


def _source_record(record: ArtifactRecord) -> dict[str, Any]:
    return {
        "artifact_id": record.artifact_id,
        "kind": record.kind,
        "path": record.path,
        "sha256": record.sha256,
        "source_path": record.source_path,
        "source_sha256": record.source_sha256,
        "transform_id": record.transform_id,
        "provenance_node_id": record.provenance_node_id,
    }


def _analysis_source_record(record: ArtifactRecord) -> dict[str, Any]:
    return {
        "kind": record.kind,
        "path": record.path,
        "format": record.format,
        "sha256": record.sha256,
        "source_path": record.source_path,
        "source_sha256": record.source_sha256,
        "transform_id": record.transform_id,
        "provenance_node_id": record.provenance_node_id,
    }


def _render_markdown(document: Mapping[str, Any]) -> str:
    lines = [
        "# Validated Analysis Report",
        "",
        f"Run: `{document['run_id']}`",
        f"Nodes: `{document['observed_nodes']}` observed / `{document['requested_nodes']}` requested",
        "",
        "## Digests",
        "",
        "| Name | SHA-256 |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {_md(name)} | `{digest}` |"
        for name, digest in document["digests"].items()
    )
    lines.extend(["", "## Surfaces", ""])
    for name in REQUIRED_SURFACES:
        surface = document["surfaces"][name]
        lines.extend(
            [
                f"### {_title(name)}",
                "",
                f"Status: `{surface['status']}`",
                "",
                "```json",
                json.dumps(surface, indent=2, sort_keys=True, ensure_ascii=True),
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_html(document: Mapping[str, Any]) -> str:
    digest_rows = "".join(
        f"<tr><th>{html.escape(name)}</th><td><code>{html.escape(value)}</code></td></tr>"
        for name, value in document["digests"].items()
    )
    sections = "".join(
        "<section>"
        f"<h2>{html.escape(_title(name))}</h2>"
        f"<p>Status: <code>{html.escape(str(document['surfaces'][name]['status']))}</code></p>"
        f"<pre>{html.escape(json.dumps(document['surfaces'][name], indent=2, sort_keys=True, ensure_ascii=True))}</pre>"
        "</section>"
        for name in REQUIRED_SURFACES
    )
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Validated Analysis Report</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;}"
        "table{border-collapse:collapse;width:100%;}th,td{border:1px solid #bbb;padding:.5rem;text-align:left;}"
        "pre{overflow:auto;background:#f4f4f4;padding:1rem;}code{overflow-wrap:anywhere;}</style>"
        "</head><body><h1>Validated Analysis Report</h1>"
        f"<p>Run: <code>{html.escape(str(document['run_id']))}</code></p>"
        f"<p>Nodes: {document['observed_nodes']} observed / {document['requested_nodes']} requested</p>"
        f"<h2>Digests</h2><table>{digest_rows}</table>{sections}</body></html>\n"
    )


def _render_csv(surfaces: Mapping[str, Any]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=("surface", "status", "reason", "value_json"),
        lineterminator="\n",
    )
    writer.writeheader()
    for name in REQUIRED_SURFACES:
        surface = surfaces[name]
        writer.writerow(
            {
                "surface": name,
                "status": surface["status"],
                "reason": surface.get("reason", ""),
                "value_json": json.dumps(
                    surface, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                ),
            }
        )
    return stream.getvalue()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _title(value: str) -> str:
    return value.replace("_", " ").title()


def _md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "REQUIRED_SURFACES",
    "ValidatedReport",
    "ValidatedReportError",
    "render_validated_report",
]
