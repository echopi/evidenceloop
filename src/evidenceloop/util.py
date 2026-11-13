"""Shared helpers with no project-specific assumptions."""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path
from typing import List


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def bounded(text: object, limit: int) -> str:
    """Collapse whitespace and cap the value so summaries stay small."""
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_ids(value: str) -> List[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
