"""GoogleTest output parser."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..util import bounded

MAX_FAILURE_LINES = 10

RAN_RE = re.compile(r"^\[==========\] (\d+) tests? from (\d+) test suites? ran\.")
PASSED_RE = re.compile(r"^\[  PASSED  \] (\d+) tests?\.")
FAILED_COUNT_RE = re.compile(r"^\[  FAILED  \] (\d+) tests?, listed below:")
FAILED_TEST_RE = re.compile(r"^\[  FAILED  \] ([^\s(]+) \(")


def parse_gtest(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "tests_ran": None,
        "suites": None,
        "passed": None,
        "failed": None,
        "failed_tests": [],
        "failure_lines": [],
        "coverage": {
            "lines_total": 0,
            "failure_lines_total": 0,
            "failure_lines_kept": 0,
            "truncated": False,
        },
    }
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result

    failure_lines_total = 0
    in_failure = False
    for line in lines:
        match = RAN_RE.match(line)
        if match:
            result["tests_ran"] = int(match.group(1))
            result["suites"] = int(match.group(2))
            continue
        match = PASSED_RE.match(line)
        if match:
            result["passed"] = int(match.group(1))
            continue
        match = FAILED_COUNT_RE.match(line)
        if match:
            result["failed"] = int(match.group(1))
            continue
        match = FAILED_TEST_RE.match(line)
        if match:
            name = match.group(1)
            if name not in result["failed_tests"]:
                result["failed_tests"].append(name)
            in_failure = False
            continue
        if "Failure" in line:
            in_failure = True
            failure_lines_total += 1
            if len(result["failure_lines"]) < MAX_FAILURE_LINES:
                result["failure_lines"].append(bounded(line, 200))
            continue
        if in_failure and line.strip():
            failure_lines_total += 1
            if len(result["failure_lines"]) < MAX_FAILURE_LINES:
                result["failure_lines"].append(bounded(line, 200))
    result["coverage"] = {
        "lines_total": len(lines),
        "failure_lines_total": failure_lines_total,
        "failure_lines_kept": len(result["failure_lines"]),
        "truncated": failure_lines_total > len(result["failure_lines"]),
    }
    return result
