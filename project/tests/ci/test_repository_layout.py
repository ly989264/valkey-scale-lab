from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "validate_repository_layout.py"
SPEC = importlib.util.spec_from_file_location("layout", SCRIPT)
assert SPEC and SPEC.loader
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)


def write_baseline(path: Path, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda row: row["logical_path"].encode("utf-8"))
    payload = {
        "schema_version": "v1",
        "artifact_type": "evidence_integrity",
        "hash_algorithm": "sha256",
        "record_format": "logical_path\\0byte_count\\0sha256\\n",
        "source_logical_roots": list(layout.ROOTS),
        "excluded_prefixes": list(layout.EXCLUDED_PREFIXES),
        "roots": {
            root: layout.counts([row for row in rows if row["logical_path"].split("/", 1)[0] == root])
            for root in layout.ROOTS
        },
        "aggregate": layout.counts(rows),
        "files": rows,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def make_tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    project = repo / "project"
    evidence = repo / "loop_evidence"
    for directory in (repo / ".git", repo / ".github", project, evidence):
        directory.mkdir(parents=True, exist_ok=True)
    for filename in (".gitignore", "AGENTS.md", "README.md"):
        (repo / filename).write_text(filename, encoding="utf-8")
    for name in layout.ACTIVE_DIRS:
        (project / name).mkdir()
    retired = evidence / "retired_loop_packages"
    retired.mkdir()
    for name in layout.RETIRED:
        target = retired / name
        if name in {"codex_goal_loop_m1", "codex_goal_loop_m1_hardening_v2"}:
            target.mkdir()
        else:
            target.write_text(name, encoding="utf-8")
    rows = []
    for root in layout.ROOTS:
        target = evidence / root / "old.txt"
        target.parent.mkdir()
        target.write_text(f"{root}-evidence", encoding="utf-8")
        rows.append({
            "logical_path": f"{root}/old.txt",
            "type": "regular",
            "byte_count": target.stat().st_size,
            "sha256": layout.sha256_file(target),
        })
    for name, target in layout.LINKS.items():
        os.symlink(target, project / name)
    baseline = tmp_path / "baseline.json"
    write_baseline(baseline, rows)
    return repo, project, evidence, baseline


def run_verify(tmp_path: Path, repo: Path, project: Path, evidence: Path, baseline: Path) -> tuple[int, dict]:
    out = tmp_path / "report.json"
    summary = tmp_path / "summary.json"
    args = argparse.Namespace(
        repo_root=str(repo), project_root=str(project), evidence_root=str(evidence),
        baseline=str(baseline), out=str(out), phase_summary=str(summary),
    )
    result = layout.verify(args)
    return result, json.loads(out.read_text(encoding="utf-8"))


def test_valid_end_to_end_layout_passes(tmp_path: Path) -> None:
    repo, project, evidence, baseline = make_tree(tmp_path)
    result, report = run_verify(tmp_path, repo, project, evidence, baseline)
    assert result == 0
    assert report["status"] == "PASS"
    assert layout.validate_report_semantics(report) == []


def test_missing_broken_absolute_and_escaping_links_fail(tmp_path: Path) -> None:
    for mode in ("missing", "broken", "absolute", "escaping"):
        case = tmp_path / mode
        repo, project, evidence, baseline = make_tree(case)
        link = project / "artifacts"
        link.unlink()
        if mode == "broken":
            os.symlink("../loop_evidence/absent", link)
        elif mode == "absolute":
            os.symlink(str((evidence / "artifacts").resolve()), link)
        elif mode == "escaping":
            os.symlink("../../outside", link)
        result, report = run_verify(case, repo, project, evidence, baseline)
        assert result == 1, mode
        assert report["status"] == "FAIL"
        assert any("invalid compatibility link" in error for error in report["errors"])


def test_unexpected_root_and_misclassification_fail(tmp_path: Path) -> None:
    repo, project, evidence, baseline = make_tree(tmp_path)
    (repo / "unexpected").write_text("no", encoding="utf-8")
    (project / "src").rmdir()
    result, report = run_verify(tmp_path, repo, project, evidence, baseline)
    assert result == 1
    assert report["unexpected_root_entries"] == ["unexpected"]
    assert report["classifications"]["project/src"] is False


def test_missing_mutated_and_extra_evidence_fail(tmp_path: Path) -> None:
    for mode in ("missing", "mutated", "extra"):
        case = tmp_path / mode
        repo, project, evidence, baseline = make_tree(case)
        target = evidence / "artifacts/old.txt"
        if mode == "missing":
            target.unlink()
        elif mode == "mutated":
            target.write_text("changed-content", encoding="utf-8")
        else:
            (evidence / "artifacts/extra.txt").write_text("extra", encoding="utf-8")
        result, report = run_verify(case, repo, project, evidence, baseline)
        assert result == 1, mode
        assert report["status"] == "FAIL"
        assert report["integrity"][{"missing": "missing", "mutated": "changed", "extra": "unexpected"}[mode]], mode


def test_baseline_rejects_malformed_aggregate_and_per_root_without_rewrite(tmp_path: Path) -> None:
    for field in ("aggregate", "root"):
        case = tmp_path / field
        _, _, _, baseline = make_tree(case)
        payload = json.loads(baseline.read_text(encoding="utf-8"))
        if field == "aggregate":
            payload["aggregate"]["file_count"] = 0
        else:
            payload["roots"]["artifacts"]["file_count"] = 0
        baseline.write_text(json.dumps(payload), encoding="utf-8")
        original = baseline.read_bytes()
        try:
            layout.load_baseline(baseline)
        except ValueError as exc:
            assert "does not match" in str(exc)
        else:
            raise AssertionError(f"malformed {field} baseline accepted")
        assert baseline.read_bytes() == original


def test_verification_never_rewrites_baseline(tmp_path: Path) -> None:
    repo, project, evidence, baseline = make_tree(tmp_path)
    original = baseline.read_bytes()
    (evidence / "runs/old.txt").write_text("mutated", encoding="utf-8")
    result, _ = run_verify(tmp_path, repo, project, evidence, baseline)
    assert result == 1
    assert baseline.read_bytes() == original


def test_false_pass_semantics_are_rejected(tmp_path: Path) -> None:
    repo, project, evidence, baseline = make_tree(tmp_path)
    _, valid = run_verify(tmp_path, repo, project, evidence, baseline)
    mutations = [
        lambda report: report["errors"].append("hidden failure"),
        lambda report: report["unexpected_root_entries"].append("extra"),
        lambda report: report["links"][0].update(valid=False),
        lambda report: report["classifications"].update({"project/src": False}),
        lambda report: report["integrity"]["missing"].append("artifacts/missing"),
        lambda report: report["integrity"]["changed"].append("artifacts/changed"),
        lambda report: report["integrity"]["unexpected"].append("artifacts/extra"),
        lambda report: report["integrity"]["observed"].update(file_count=0),
    ]
    for mutate in mutations:
        report = json.loads(json.dumps(valid))
        mutate(report)
        assert layout.validate_report_semantics(report), report


def test_schema_gate_rejects_false_pass_report(tmp_path: Path) -> None:
    repo, project, evidence, baseline = make_tree(tmp_path)
    _, report = run_verify(tmp_path, repo, project, evidence, baseline)
    report["errors"] = ["concealed"]
    report["links"][0]["valid"] = False
    report["classifications"]["project/src"] = False
    report["integrity"]["observed"]["file_count"] = 0
    instance = tmp_path / "false-pass.json"
    instance.write_text(json.dumps(report), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, "scripts/validate_json_schema.py", "--schema",
            "schemas/artifact/repository_layout_report.schema.json", "--instance", str(instance),
        ],
        cwd=Path(__file__).parents[2], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "PASS requires" in result.stderr
    schema = json.loads((Path(__file__).parents[2] / "schemas/artifact/repository_layout_report.schema.json").read_text(encoding="utf-8"))
    assert schema["allOf"][0]["if"]["properties"]["status"]["const"] == "PASS"


def test_record_digest_is_deterministic_and_p46_exclusions_are_exact(tmp_path: Path) -> None:
    path = tmp_path / "artifacts/old.json"
    path.parent.mkdir()
    path.write_text("old", encoding="utf-8")
    before = layout.counts(layout.inventory(tmp_path, ["artifacts/old.json"]))
    path.write_text("NEW", encoding="utf-8")
    after = layout.counts(layout.inventory(tmp_path, ["artifacts/old.json"]))
    assert before["byte_count"] == after["byte_count"] == 3
    assert before["tree_sha256"] != after["tree_sha256"]
    assert layout.excluded("artifacts/phases/P46_REPOSITORY_LAYOUT_MIGRATION/phase_summary.json")
    assert layout.excluded("audit/P46_REPOSITORY_LAYOUT_MIGRATION/AUDIT.md")
    assert not layout.excluded("artifacts/phases/P45_FINAL_AUDIT_REPORT/final.json")
