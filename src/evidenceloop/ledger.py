"""Append-only evidence ledger and home-directory migration."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import schema
from .errors import EvidenceLoopError
from .locking import LOCK_TIMEOUT_SECONDS, file_lock
from .util import sha256_file  # noqa: F401  (re-exported for callers)

DEFAULT_HOME_NAME = ".eloop"


def default_home() -> Path:
    override = os.environ.get("ELOOP_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_HOME_NAME


class Ledger:
    """JSONL evidence store plus the investigation state file."""

    def __init__(
        self,
        home: str | None = None,
        lock_timeout: float = LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.home = Path(home).expanduser() if home else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "ledger.jsonl"
        self.investigation_path = self.home / "investigation.json"
        self.lock_path = self.home / "ledger.lock"
        self.lock_timeout = lock_timeout
        self.logs = self.home / "logs"
        self.logs.mkdir(exist_ok=True)

    def validate_schema(self) -> None:
        """Reject homes written with a newer schema; legacy homes read as v1."""
        schema.validate_home(self.home)

    @contextlib.contextmanager
    def write_transaction(self) -> Iterator[None]:
        """Serialize state writes and make sure the home carries schema metadata."""
        with file_lock(self.lock_path, timeout=self.lock_timeout):
            schema.validate_home(self.home)
            schema.ensure_meta(self.home)
            yield

    def entries(self) -> list[dict[str, Any]]:
        self.validate_schema()
        return self._read_entries()

    def _read_entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = self.path.read_bytes()
        except OSError as error:
            raise EvidenceLoopError(f"cannot read {self.path}: {error}") from error
        text = data.decode("utf-8", errors="replace")
        if text and not text.endswith("\n"):
            # A writer may be midway through a record; never parse a torn tail.
            text = text[: text.rfind("\n") + 1]
        items: list[dict[str, Any]] = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items

    def _next_id(self) -> str:
        day = dt.datetime.now().strftime("%Y%m%d")
        prefix = f"E{day}-"
        seq = 0
        for item in self._read_entries():
            evidence_id = item.get("evidence_id", "")
            if evidence_id.startswith(prefix):
                try:
                    seq = max(seq, int(evidence_id[len(prefix) :]))
                except ValueError:
                    continue
        return f"{prefix}{seq + 1:04d}"

    def next_id(self) -> str:
        """Return the next evidence ID; ``append`` re-allocates it under the lock."""
        with file_lock(self.lock_path, timeout=self.lock_timeout):
            self.validate_schema()
            return self._next_id()

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Append an entry and return it with the ledger-assigned evidence ID.

        The caller's dict is updated in place so commands that print the entry
        always report the ID that was actually persisted, even when several
        processes append at the same time.
        """
        with self.write_transaction():
            entry["evidence_id"] = self._next_id()
            payload = json.dumps(entry, ensure_ascii=False) + "\n"
            self._append_line(payload)
        return entry

    def _append_line(self, payload: str) -> None:
        data = payload.encode("utf-8")
        try:
            if self.path.exists() and self.path.stat().st_size > 0:
                with open(self.path, "rb") as handle:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        # Terminate a torn record left by an interrupted writer.
                        data = b"\n" + data
            fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        except OSError as error:
            raise EvidenceLoopError(f"cannot open {self.path}: {error}") from error
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
        except OSError as error:
            raise EvidenceLoopError(f"cannot write {self.path}: {error}") from error
        finally:
            os.close(fd)


def migrate_home(source: Path, target: Ledger, force: bool = False) -> dict[str, Any]:
    """Copy a legacy home into ``target`` without touching unknown files."""
    source = Path(source).expanduser()
    if not source.is_dir():
        raise EvidenceLoopError(f"source home not found: {source}")

    target.validate_schema()
    if not force:
        skipped = [
            str(target.home / name)
            for name in ("ledger.jsonl", "investigation.json")
            if (target.home / name).exists()
        ]
        if skipped:
            raise EvidenceLoopError(
                "target files already exist (use --force to overwrite): "
                + ", ".join(skipped)
            )

    copied: list[str] = []
    for name in ("ledger.jsonl", "investigation.json"):
        src = source / name
        if not src.exists():
            continue
        dst = target.home / name
        shutil.copy2(src, dst)
        copied.append(str(dst))

    src_logs = source / "logs"
    if src_logs.is_dir():
        shutil.copytree(src_logs, target.logs, dirs_exist_ok=True)
        copied.append(str(target.logs))

    return {"source": str(source), "target": str(target.home), "copied": copied}
