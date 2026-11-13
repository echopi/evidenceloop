"""Append-only evidence ledger and home-directory migration."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import EvidenceLoopError
from .util import sha256_file  # noqa: F401  (re-exported for callers)

DEFAULT_HOME_NAME = ".eloop"


def default_home() -> Path:
    override = os.environ.get("ELOOP_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_HOME_NAME


class Ledger:
    """JSONL evidence store plus the investigation state file."""

    def __init__(self, home: Optional[str] = None) -> None:
        self.home = Path(home).expanduser() if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "ledger.jsonl"
        self.investigation_path = self.home / "investigation.json"
        self.logs = self.home / "logs"
        self.logs.mkdir(exist_ok=True)

    def entries(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        items: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items

    def next_id(self) -> str:
        day = dt.datetime.now().strftime("%Y%m%d")
        prefix = "E%s-" % day
        seq = 0
        for item in self.entries():
            evidence_id = item.get("evidence_id", "")
            if evidence_id.startswith(prefix):
                try:
                    seq = max(seq, int(evidence_id[len(prefix) :]))
                except ValueError:
                    continue
        return "%s%04d" % (prefix, seq + 1)

    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry


def migrate_home(source: Path, target: Ledger, force: bool = False) -> Dict[str, Any]:
    """Copy a legacy home into ``target`` without touching unknown files."""
    source = Path(source).expanduser()
    if not source.is_dir():
        raise EvidenceLoopError("source home not found: %s" % source)

    copied: List[str] = []
    skipped: List[str] = []
    for name in ("ledger.jsonl", "investigation.json"):
        src = source / name
        if not src.exists():
            continue
        dst = target.home / name
        if dst.exists() and not force:
            skipped.append(str(dst))
            continue
        shutil.copy2(src, dst)
        copied.append(str(dst))

    src_logs = source / "logs"
    if src_logs.is_dir():
        shutil.copytree(src_logs, target.logs, dirs_exist_ok=True)
        copied.append(str(target.logs))

    if skipped and not force:
        raise EvidenceLoopError(
            "target files already exist (use --force to overwrite): %s" % ", ".join(skipped)
        )
    return {"source": str(source), "target": str(target.home), "copied": copied}
