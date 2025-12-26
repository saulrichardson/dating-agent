from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_file(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    if file_path.is_dir():
        raise IsADirectoryError(f"Expected a JSON file but found a directory: {file_path}")

    raw = file_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {file_path}: {e}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Expected top-level JSON object in {file_path}")
    return data


def require_key(obj: dict[str, Any], key: str, *, context: str) -> Any:
    if key not in obj:
        raise ValueError(f"Missing required key '{key}' in {context}")
    return obj[key]

