from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigParseError(ValueError):
    pass


def parse_config_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = parse_yaml_subset(text)
    if not isinstance(data, dict):
        raise ConfigParseError("config root must be an object")
    return data


def parse_yaml_subset(text: str) -> Any:
    lines = _logical_lines(text)
    if not lines:
        return {}
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    for lineno, indent, content in lines:
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigParseError(f"line {lineno}: invalid indentation")
        parent = stack[-1][1]
        if content.startswith("- "):
            if not isinstance(parent, list):
                raise ConfigParseError(f"line {lineno}: list item without list parent")
            item_text = content[2:].strip()
            if not item_text:
                item: Any = {}
                parent.append(item)
                stack.append((indent, item))
                continue
            if ":" in item_text and not item_text.startswith(('"', "'")):
                key, value_text = _split_key_value(item_text, lineno)
                item = {key: _parse_scalar(value_text)}
                parent.append(item)
                stack.append((indent, item))
            else:
                parent.append(_parse_scalar(item_text))
            continue
        key, value_text = _split_key_value(content, lineno)
        if not isinstance(parent, dict):
            raise ConfigParseError(f"line {lineno}: mapping entry without mapping parent")
        if value_text == "":
            child = _infer_child(lines, lineno, indent)
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value_text)
    return root


def _logical_lines(text: str) -> list[tuple[int, int, str]]:
    lines: list[tuple[int, int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        without_comment = _strip_comment(raw).rstrip()
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        if "\t" in without_comment[:indent]:
            raise ConfigParseError(f"line {lineno}: tabs are not supported for indentation")
        lines.append((lineno, indent, without_comment.strip()))
    return lines


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:idx]
    return line


def _split_key_value(text: str, lineno: int) -> tuple[str, str]:
    if ":" not in text:
        raise ConfigParseError(f"line {lineno}: expected key: value")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise ConfigParseError(f"line {lineno}: empty key")
    return key, value.strip()


def _infer_child(lines: list[tuple[int, int, str]], current_lineno: int, current_indent: int) -> Any:
    for lineno, indent, content in lines:
        if lineno <= current_lineno:
            continue
        if indent <= current_indent:
            break
        return [] if content.startswith("- ") else {}
    return {}


def _parse_scalar(text: str) -> Any:
    if text == "":
        return None
    if text in {"true", "True"}:
        return True
    if text in {"false", "False"}:
        return False
    if text in {"null", "None", "~"}:
        return None
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in inner.split(",")]
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text
