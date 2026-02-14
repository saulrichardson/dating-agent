from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_DOTENV_LOADED = False


def _repo_root() -> Path:
    # automation_service/mobile/env.py -> repo root is two levels up
    return Path(__file__).resolve().parents[2]


def load_dotenv(*, path: Optional[str | Path] = None, override: bool = False) -> dict[str, str]:
    """
    Minimal .env loader (no external deps).

    - Ignores blank lines and comments starting with '#'
    - Supports optional leading 'export '
    - Parses KEY=VALUE where VALUE may be quoted
    - Sets os.environ unless the key already exists (unless override=True)

    Returns a dict of keys that were set.
    """
    dotenv_path = Path(path).expanduser().resolve() if path is not None else (_repo_root() / ".env")
    if not dotenv_path.exists():
        return {}
    if dotenv_path.is_dir():
        raise RuntimeError(f".env path is a directory: {dotenv_path}")

    loaded: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if not override and os.environ.get(key) is not None:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded


def ensure_dotenv_loaded() -> dict[str, str]:
    """
    Load repo-root .env exactly once per process.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return {}
    loaded = load_dotenv()
    _DOTENV_LOADED = True
    return loaded

