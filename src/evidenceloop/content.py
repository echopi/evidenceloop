"""Stable content identity for evidence novelty checks."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _experiment_payload(entry: dict[str, Any]) -> dict[str, Any]:
    summary = entry.get("summary") or {}
    test = summary.get("test") or {}
    build = summary.get("build") or {}
    return {
        "kind": "experiment",
        "build_skipped": summary.get("build_skipped"),
        "test_id": test.get("test_id", ""),
        "test_argv": test.get("argv"),
        "test_exit": test.get("exit_code"),
        "test_timed_out": test.get("timed_out"),
        "test_log_sha256": test.get("log_sha256", ""),
        "build_argv": build.get("argv") if isinstance(build, dict) else None,
        "build_exit": build.get("exit_code") if isinstance(build, dict) else None,
        "build_timed_out": (
            build.get("timed_out") if isinstance(build, dict) else None
        ),
        "build_log_sha256": (
            build.get("log_sha256", "") if isinstance(build, dict) else ""
        ),
    }


def _experiment_identity_complete(
    test: Any, build: Any, build_skipped: Any
) -> bool:
    if not isinstance(build_skipped, bool):
        return False
    if not isinstance(test, dict):
        return False
    if not test.get("test_id") or not test.get("log_sha256"):
        return False
    if build is not None:
        if not isinstance(build, dict) or not build or not build.get("log_sha256"):
            return False
    return True


def compute_content_key(entry: dict[str, Any]) -> str:
    if entry.get("kind") == "experiment":
        summary = entry.get("summary") or {}
        payload = _experiment_payload(entry)
        if not _experiment_identity_complete(
            summary.get("test"),
            summary.get("build"),
            summary.get("build_skipped"),
        ):
            payload["evidence_id"] = entry.get("evidence_id", "")
            payload["source"] = entry.get("source", "")
    else:
        sha256 = str(entry.get("sha256", ""))
        if sha256:
            payload = {"kind": entry.get("kind", ""), "sha256": sha256}
        else:
            # Legacy records without a digest still need a stable identity.
            payload = {
                "kind": entry.get("kind", ""),
                "source": entry.get("source", ""),
                "evidence_id": entry.get("evidence_id", ""),
            }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def content_key(entry: dict[str, Any]) -> str:
    existing = entry.get("content_key")
    if existing:
        return str(existing)
    return compute_content_key(entry)
