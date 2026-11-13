"""Home-directory schema marker and compatibility checks."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import __version__
from .errors import EvidenceLoopError
from .util import now_iso

SCHEMA_VERSION = 1
META_FILENAME = "meta.json"


def meta_path(home: Path) -> Path:
    return Path(home) / META_FILENAME


def read_meta(home: Path) -> dict[str, Any] | None:
    """Return the parsed ``meta.json``, or ``None`` for a legacy home."""
    path = meta_path(home)
    if not path.exists():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EvidenceLoopError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise EvidenceLoopError(f"cannot parse {path}: {error}") from error
    if not isinstance(meta, dict):
        raise EvidenceLoopError(f"{path} must contain a JSON object")
    version = meta.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise EvidenceLoopError(f"invalid schema_version in {path}: {version!r}")
    return meta


def _check_version(home: Path, meta: dict[str, Any]) -> None:
    version = meta["schema_version"]
    if version > SCHEMA_VERSION:
        raise EvidenceLoopError(
            f"home {home} uses schema_version {version}, but this evidenceloop "
            f"supports up to {SCHEMA_VERSION}; upgrade evidenceloop or use a different --home"
        )


def validate_home(home: Path) -> None:
    """Raise when the home was written by a newer, unsupported tool version."""
    meta = read_meta(home)
    if meta is not None:
        _check_version(Path(home), meta)


def ensure_meta(home: Path) -> dict[str, Any]:
    """Create ``meta.json`` for a legacy home; the caller must hold the home lock."""
    home = Path(home)
    meta = read_meta(home)
    if meta is not None:
        _check_version(home, meta)
        return meta

    meta = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now_iso(),
        "tool_version": __version__,
    }
    path = meta_path(home)
    tmp = path.with_name(f"{META_FILENAME}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as error:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise EvidenceLoopError(f"cannot write {path}: {error}") from error
    return meta
