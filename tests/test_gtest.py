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


def test_missing_file_returns_empty_result(tmp_path):
    result = parse_gtest(tmp_path / "missing.log")

    assert result["tests_ran"] is None
    assert result["failed_tests"] == []
