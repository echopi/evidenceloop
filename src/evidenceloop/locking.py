"""Cross-platform advisory file locking for state writes."""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Iterator
from pathlib import Path

from .errors import EvidenceLoopError

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

LOCK_TIMEOUT_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.01


def _acquire(fd: int) -> None:
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is not None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return
    raise EvidenceLoopError("file locking is not supported on this platform")


def _release(fd: int) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` or raise after ``timeout`` seconds."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + max(0.0, timeout)
    try:
        while True:
            try:
                _acquire(fd)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise EvidenceLoopError(
                        f"timed out after {timeout:.1f}s waiting for lock: {path}"
                    ) from None
                time.sleep(_POLL_INTERVAL_SECONDS)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)
