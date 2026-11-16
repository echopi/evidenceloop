"""Spec-driven experiment execution."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .errors import EvidenceLoopError
from .parsers import parse_gtest
from .util import bounded, sha256_file


def load_spec(path: Path) -> dict[str, Any]:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise EvidenceLoopError(f"cannot read spec: {error}") from error
    except json.JSONDecodeError as error:
        raise EvidenceLoopError(f"cannot parse spec: {error}") from error
    if not isinstance(spec, dict):
        raise EvidenceLoopError("spec must be a JSON object")
    return spec


def _validate_argv(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise EvidenceLoopError(f"{field}.argv must be a non-empty list")
    if not all(isinstance(item, str) for item in value):
        raise EvidenceLoopError(f"{field}.argv must contain strings only")
    return list(value)


def _test_id(spec: dict[str, Any], test: dict[str, Any]) -> str:
    for value in (test.get("id"), test.get("test_id"), spec.get("test_id"), spec.get("name")):
        if value:
            return str(value)
    return ""


def run_command(argv: list[str], cwd: Path, timeout_sec: int, log_path: Path) -> dict[str, Any]:
    started = time.time()
    timed_out = False
    exit_code: int | None
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        try:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout_sec,
                check=False,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            exit_code = None
            timed_out = True
        except OSError as error:
            log.write(f"evidenceloop: failed to start command: {error}\n")
            exit_code = None
    try:
        log_sha256 = sha256_file(log_path)
    except OSError:
        log_sha256 = ""
    return {
        "argv": argv,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_sec": round(time.time() - started, 3),
        "log": str(log_path),
        "log_sha256": log_sha256,
    }


def tail_lines(path: Path, count: int = 8, limit: int = 200) -> list[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [bounded(line, limit) for line in lines[-count:] if line.strip()]


def execute_spec(
    spec: dict[str, Any],
    repo: Path,
    run_dir: Path,
    skip_build: bool = False,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    build_spec = spec.get("build")
    build_argv = None
    if build_spec is not None:
        if not isinstance(build_spec, dict):
            raise EvidenceLoopError("spec.build must be an object")
        build_argv = _validate_argv(build_spec.get("argv"), "build")
    test_spec = spec.get("test")
    test_argv = None
    if test_spec is not None:
        if not isinstance(test_spec, dict):
            raise EvidenceLoopError("spec.test must be an object")
        test_argv = _validate_argv(test_spec.get("argv"), "test")

    build_result = None
    if not skip_build and build_spec is not None:
        build_result = run_command(
            build_argv,
            repo,
            int(build_spec.get("timeout_sec", 900)),
            run_dir / "build.log",
        )
        build_result["tail"] = tail_lines(run_dir / "build.log")

    test_result = None
    gtest = None
    if (
        build_result is None or build_result["exit_code"] == 0
    ) and test_spec is not None:
        test_result = run_command(
            test_argv,
            repo,
            int(test_spec.get("timeout_sec", 300)),
            run_dir / "test.log",
        )
        test_result["test_id"] = _test_id(spec, test_spec)
        gtest = parse_gtest(run_dir / "test.log")
        test_result["tail"] = tail_lines(run_dir / "test.log")

    return {
        "name": spec.get("name", ""),
        "repo": str(repo),
        "build": build_result,
        "build_skipped": bool(build_spec is not None and skip_build),
        "test": test_result,
        "gtest": gtest,
    }
