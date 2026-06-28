#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from schema_validator import load_json, validate


def validate_jsonl(instance_path: Path, schema: dict) -> list[str]:
    errors: list[str] = []
    with instance_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {lineno}: invalid JSON: {exc}")
                continue
            for err in validate(obj, schema, f"$[line {lineno}]"):
                errors.append(err)
    if not instance_path.read_text(encoding="utf-8").strip():
        errors.append("JSONL file is empty")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    schema_path = Path(args.schema)
    instance_path = Path(args.instance)
    if not schema_path.exists():
        print(f"schema not found: {schema_path}", file=sys.stderr)
        return 2
    if not instance_path.exists():
        print(f"instance not found: {instance_path}", file=sys.stderr)
        return 2

    schema = load_json(schema_path)
    if args.jsonl or instance_path.suffix == ".jsonl":
        errors = validate_jsonl(instance_path, schema)
    else:
        errors = validate(load_json(instance_path), schema)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    print(f"PASS schema={schema_path} instance={instance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
