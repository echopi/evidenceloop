"""Spec-driven experiment execution."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import EvidenceLoopError
from .parsers import parse_gtest
from .util import bounded


def load_spec(path: Path) -> Dict[str, Any]:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as error:
        raise EvidenceLoopError("cannot read spec: %s" % error)
    except json.JSONDecodeError as error:
        raise EvidenceLoopError("cannot parse spec: %s" % error)
    if not isinstance(spec, dict):
        raise EvidenceLoopError("spec must be a JSON object")
    return spec


def _validate_argv(value: Any, field: str) -> List[str]:
    if not isinstance(value, list) or not value:
        raise EvidenceLoopError("%s.argv must be a non-empty list" % field)
    if not all(isinstance(item, str) for item in value):
        raise EvidenceLoopError("%s.argv must contain strings only" % field)
    return list(value)


def run_command(argv: List[str], cwd: Path, timeout_sec: int, log_path: Path) -> Dict[str, Any]:
    started = time.time()
    timed_out = False
    exit_code: Optional[int]
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
            log.write("evidenceloop: failed to start command: %s\n" % error)
            exit_code = None
    return {
        "argv": argv,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_sec": round(time.time() - started, 3),
        "log": str(log_path),
    }


def tail_lines(path: Path, count: int = 8, limit: int = 200) -> List[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [bounded(line, limit) for line in lines[-count:] if line.strip()]


def execute_spec(
    spec: Dict[str, Any],
    repo: Path,
    run_dir: Path,
    skip_build: bool = False,
) -> Dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    build_result = None
    if not skip_build and spec.get("build"):
        build = spec["build"]
        if not isinstance(build, dict):
            raise EvidenceLoopError("spec.build must be an object")
        build_result = run_command(
            _validate_argv(build.get("argv"), "build"),
            repo,
            int(build.get("timeout_sec", 900)),
            run_dir / "build.log",
        )
        build_result["tail"] = tail_lines(run_dir / "build.log")

    test_result = None
    gtest = None
    if (build_result is None or build_result["exit_code"] == 0) and spec.get("test"):
        test = spec["test"]
        if not isinstance(test, dict):
            raise EvidenceLoopError("spec.test must be an object")
        test_result = run_command(
            _validate_argv(test.get("argv"), "test"),
            repo,
            int(test.get("timeout_sec", 300)),
            run_dir / "test.log",
        )
        gtest = parse_gtest(run_dir / "test.log")
        test_result["tail"] = tail_lines(run_dir / "test.log")

    return {
        "name": spec.get("name", ""),
        "repo": str(repo),
        "build": build_result,
        "test": test_result,
        "gtest": gtest,
    }
