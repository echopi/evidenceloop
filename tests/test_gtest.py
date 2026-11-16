from pathlib import Path

from evidenceloop.parsers import parse_gtest

FIXTURE = Path(__file__).parent / "fixtures" / "gtest_sample.log"


def test_counts_and_failed_names():
    result = parse_gtest(FIXTURE)

    assert result["tests_ran"] == 3
    assert result["suites"] == 1
    assert result["passed"] == 2
    assert result["failed"] == 1
    assert result["failed_tests"] == ["Suite.Case"]
    assert result["failure_lines"]
    assert result["coverage"]["lines_total"] > 0
    assert result["coverage"]["failure_lines_kept"] == len(result["failure_lines"])
    assert result["coverage"]["truncated"] is False


def test_failure_lines_are_bounded(tmp_path):
    lines = [
        "[==========] 1 test from 1 test suite ran.",
        "[  PASSED  ] 0 tests.",
        "[  FAILED  ] 1 test, listed below:",
        "[  FAILED  ] Suite.Case (0 ms)",
        "  Failure",
    ]
    lines.extend(f"  line-{index}" for index in range(15))
    path = tmp_path / "gtest.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = parse_gtest(path)

    assert result["coverage"]["failure_lines_total"] == 16
    assert result["coverage"]["failure_lines_kept"] == 10
    assert result["coverage"]["truncated"] is True


def test_missing_file_returns_empty_result(tmp_path):
    result = parse_gtest(tmp_path / "missing.log")

    assert result["tests_ran"] is None
    assert result["failed_tests"] == []
    assert result["coverage"]["lines_total"] == 0
    assert result["coverage"]["truncated"] is False
