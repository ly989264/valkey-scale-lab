from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class EvaluationError(ValueError):
    pass


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise EvaluationError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"{path} must contain a JSON object")
    return value


def canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        return None
    path = (root / raw).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    if not path.is_file() or path.is_symlink():
        return None
    return path


def environment_bindings() -> tuple[str, str, str, str, Path, Path]:
    names = (
        "VPRO2_EVALUATOR_ID",
        "VPRO2_RUN_ID",
        "VPRO2_PRODUCT_DIGEST",
        "VPRO2_INPUT_DIGEST",
        "VPRO2_RESULT_PATH",
        "VPRO2_EVIDENCE_ROOT",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise EvaluationError(f"missing evaluator environment: {missing}")
    return (
        os.environ[names[0]],
        os.environ[names[1]],
        os.environ[names[2]],
        os.environ[names[3]],
        Path(os.environ[names[4]]).resolve(),
        Path(os.environ[names[5]]).resolve(),
    )


def write_result(
    *,
    evaluator_id: str,
    run_id: str,
    product_digest: str,
    input_digest: str,
    result_path: Path,
    condition_results: list[dict[str, Any]],
    evidence_results: list[dict[str, Any]],
) -> int:
    value = {
        "schema_version": "vpro2-evaluator-result-v1",
        "evaluator_id": evaluator_id,
        "run_id": run_id,
        "product_digest": product_digest,
        "input_digest": input_digest,
        "condition_results": condition_results,
        "evidence_results": evidence_results,
        "facts": [],
    }
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    statuses = [item["status"] for item in (*condition_results, *evidence_results)]
    return 0 if statuses and all(status == "PASS" for status in statuses) else 1
