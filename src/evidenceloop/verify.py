"""Read-only evidence integrity verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import EvidenceLoopError
from .ledger import Ledger
from .util import sha256_file

STATUS_ORDER = {"ok": 0, "unverifiable": 1, "missing": 2, "hash_mismatch": 3}


def _resolve(path_value: str, base: Path) -> Path:
    path = Path(path_value).expanduser()
    return path if path.is_absolute() else base / path


def _check_file(path_value: str, expected: str, base: Path) -> dict[str, Any]:
    if not isinstance(path_value, str) or not isinstance(expected, str):
        return {
            "path": path_value,
            "expected_sha256": expected,
            "actual_sha256": None,
            "status": "unverifiable",
            "reason": "path or expected digest is not a string",
        }
    if not path_value or not expected:
        return {
            "path": path_value,
            "expected_sha256": expected,
            "actual_sha256": None,
            "status": "unverifiable",
            "reason": "missing path or expected digest",
        }
    path = _resolve(path_value, base)
    if not path.is_file():
        return {
            "path": str(path),
            "expected_sha256": expected,
            "actual_sha256": None,
            "status": "missing",
        }
    try:
        actual = sha256_file(path)
    except OSError:
        return {
            "path": str(path),
            "expected_sha256": expected,
            "actual_sha256": None,
            "status": "missing",
        }
    return {
        "path": str(path),
        "expected_sha256": expected,
        "actual_sha256": actual,
        "status": "ok" if actual == expected else "hash_mismatch",
    }


def _unverifiable(reason: str, path: str = "", expected: str = "") -> dict[str, Any]:
    return {
        "path": path,
        "expected_sha256": expected,
        "actual_sha256": None,
        "status": "unverifiable",
        "reason": reason,
    }


def _read_spec(entry: dict[str, Any], base: Path) -> dict[str, Any] | None:
    path_value = entry.get("source")
    if not isinstance(path_value, str) or not path_value:
        return None
    path = _resolve(str(path_value), base)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _spec_build_is_valid(spec: dict[str, Any] | None) -> bool:
    if not isinstance(spec, dict):
        return False
    build = spec.get("build")
    if not isinstance(build, dict):
        return False
    argv = build.get("argv")
    return (
        isinstance(argv, list)
        and bool(argv)
        and all(isinstance(item, str) for item in argv)
    )


def _overall(statuses: list[str]) -> str:
    if not statuses:
        return "unverifiable"
    return max(statuses, key=lambda status: STATUS_ORDER.get(status, 1))


def _verify_entry(entry: dict[str, Any], base: Path) -> dict[str, Any]:
    parts: dict[str, Any] = {
        "source": _check_file(entry.get("source", ""), entry.get("sha256", ""), base)
    }
    if entry.get("kind") == "experiment":
        summary = entry.get("summary") or {}
        spec = _read_spec(entry, base)
        build = summary.get("build")
        if isinstance(build, dict):
            parts["build_log"] = _check_file(
                build.get("log", ""), build.get("log_sha256", ""), base
            )
        elif summary.get("build_skipped") is True:
            if not _spec_build_is_valid(spec):
                parts["build_log"] = _unverifiable(
                    "build_skipped without a valid build spec"
                )
        elif isinstance(spec, dict) and spec.get("build") is not None:
            parts["build_log"] = _unverifiable("build result is missing")
        test = summary.get("test")
        if isinstance(test, dict):
            parts["test_log"] = _check_file(
                test.get("log", ""), test.get("log_sha256", ""), base
            )
        else:
            parts["test_log"] = _unverifiable("test result is missing")
    statuses = [part["status"] for part in parts.values()]
    return {
        "evidence_id": entry.get("evidence_id"),
        "kind": entry.get("kind"),
        "status": _overall(statuses),
        "parts": parts,
    }


def verify_ledger(ledger: Ledger, evidence_id: str | None = None) -> dict[str, Any]:
    entries = ledger.entries()
    if evidence_id is not None:
        entries = [
            entry for entry in entries if entry.get("evidence_id") == evidence_id
        ]
        if not entries:
            raise EvidenceLoopError(f"unknown evidence: {evidence_id}")
    results = [_verify_entry(entry, ledger.home) for entry in entries]
    counts = {status: 0 for status in STATUS_ORDER}
    for result in results:
        counts[result["status"]] += 1
    return {
        "checked": len(results),
        "ok": counts["ok"],
        "missing": counts["missing"],
        "hash_mismatch": counts["hash_mismatch"],
        "unverifiable": counts["unverifiable"],
        "evidence": results,
    }
