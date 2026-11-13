import json
import sys

import pytest

from evidenceloop import runner
from evidenceloop.errors import EvidenceLoopError

GTEST_PASS = (
    "[==========] 2 tests from 1 test suite ran.\n"
    "[  PASSED  ] 2 tests.\n"
)
GTEST_FAIL = (
    "[==========] 2 tests from 1 test suite ran.\n"
    "[  PASSED  ] 1 test.\n"
    "[  FAILED  ] 1 test, listed below:\n"
    "[  FAILED  ] Suite.Case (0 ms)\n"
    "  Failure\n"
    "  Expected equality of these values:\n"
    "    actual\n"
    "      Which is: 1\n"
)


def write_script(tmp_path, name, body, exit_code=0):
    script = tmp_path / name
    if exit_code:
        body += f"raise SystemExit({exit_code})\n"
    script.write_text(body, encoding="utf-8")
    return script


def test_execute_spec_success(tmp_path):
    script = write_script(
        tmp_path,
        "pass_gtest.py",
        "print('[==========] 2 tests from 1 test suite ran.')\n"
        "print('[  PASSED  ] 2 tests.')\n",
    )
    spec = {
        "name": "ok",
        "repo": str(tmp_path),
        "build": {"argv": [sys.executable, "-c", "print('built')"], "timeout_sec": 30},
        "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
    }

    summary = runner.execute_spec(spec, tmp_path, tmp_path / "run")

    assert summary["name"] == "ok"
    assert summary["repo"] == str(tmp_path)
    assert summary["build"]["exit_code"] == 0
    assert summary["build"]["timed_out"] is False
    assert summary["build"]["tail"] == ["built"]
    assert summary["test"]["exit_code"] == 0
    assert summary["gtest"]["tests_ran"] == 2
    assert summary["gtest"]["passed"] == 2
    assert summary["gtest"]["failed"] is None
    assert (tmp_path / "run" / "build.log").is_file()
    assert (tmp_path / "run" / "test.log").is_file()


def test_execute_spec_build_failure_skips_test(tmp_path):
    marker = tmp_path / "test-ran"
    script = write_script(
        tmp_path,
        "marker.py",
        f"open({str(marker)!r}, 'w', encoding='utf-8').write('ran')\n",
    )
    spec = {
        "repo": str(tmp_path),
        "build": {"argv": [sys.executable, "-c", "raise SystemExit(3)"], "timeout_sec": 30},
        "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
    }

    summary = runner.execute_spec(spec, tmp_path, tmp_path / "run")

    assert summary["build"]["exit_code"] == 3
    assert summary["test"] is None
    assert summary["gtest"] is None
    assert not marker.exists()


def test_execute_spec_timeout(tmp_path):
    spec = {
        "repo": str(tmp_path),
        "test": {
            "argv": [sys.executable, "-c", "import time; time.sleep(5)"],
            "timeout_sec": 1,
        },
    }

    summary = runner.execute_spec(spec, tmp_path, tmp_path / "run")

    assert summary["test"]["timed_out"] is True
    assert summary["test"]["exit_code"] is None
    assert summary["gtest"]["tests_ran"] is None


def test_execute_spec_parses_failing_gtest(tmp_path):
    script = write_script(
        tmp_path,
        "fail_gtest.py",
        f"print({json.dumps(GTEST_FAIL)})\n",
        exit_code=1,
    )
    spec = {
        "name": "fail",
        "repo": str(tmp_path),
        "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
    }

    summary = runner.execute_spec(spec, tmp_path, tmp_path / "run")

    assert summary["test"]["exit_code"] == 1
    assert summary["gtest"]["tests_ran"] == 2
    assert summary["gtest"]["passed"] == 1
    assert summary["gtest"]["failed"] == 1
    assert summary["gtest"]["failed_tests"] == ["Suite.Case"]
    assert summary["gtest"]["failure_lines"]
    assert any("Failure" in line for line in summary["gtest"]["failure_lines"])


def test_execute_spec_skip_build(tmp_path):
    script = write_script(
        tmp_path,
        "pass_gtest.py",
        f"print({json.dumps(GTEST_PASS)})\n",
    )
    spec = {
        "repo": str(tmp_path),
        "build": {"argv": [sys.executable, "-c", "raise SystemExit(2)"]},
        "test": {"argv": [sys.executable, str(script)]},
    }

    summary = runner.execute_spec(spec, tmp_path, tmp_path / "run", skip_build=True)

    assert summary["build"] is None
    assert summary["test"]["exit_code"] == 0
    assert summary["gtest"]["tests_ran"] == 2


def test_execute_spec_without_build_or_test(tmp_path):
    summary = runner.execute_spec({"repo": str(tmp_path)}, tmp_path, tmp_path / "run")

    assert summary["name"] == ""
    assert summary["build"] is None
    assert summary["test"] is None


def test_execute_spec_rejects_invalid_argv(tmp_path):
    cases = [
        ({"build": {"argv": "make"}}, "non-empty list"),
        ({"build": {"argv": []}}, "non-empty list"),
        ({"build": {"argv": ["make", 1]}}, "strings only"),
        ({"test": {"argv": ["make", None]}}, "strings only"),
    ]
    for extra, message in cases:
        spec = {"repo": str(tmp_path)}
        spec.update(extra)
        with pytest.raises(EvidenceLoopError) as error:
            runner.execute_spec(spec, tmp_path, tmp_path / "run")
        assert message in str(error.value)


def test_execute_spec_rejects_non_object_steps(tmp_path):
    with pytest.raises(EvidenceLoopError) as error:
        runner.execute_spec(
            {"repo": str(tmp_path), "build": "make"}, tmp_path, tmp_path / "run"
        )
    assert "spec.build must be an object" in str(error.value)

    with pytest.raises(EvidenceLoopError) as error:
        runner.execute_spec(
            {"repo": str(tmp_path), "test": "make"}, tmp_path, tmp_path / "run"
        )
    assert "spec.test must be an object" in str(error.value)


def test_load_spec_errors(tmp_path):
    with pytest.raises(EvidenceLoopError) as error:
        runner.load_spec(tmp_path / "missing.json")
    assert "cannot read spec" in str(error.value)

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(EvidenceLoopError) as error:
        runner.load_spec(bad)
    assert "cannot parse spec" in str(error.value)

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(EvidenceLoopError) as error:
        runner.load_spec(array)
    assert "JSON object" in str(error.value)

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"name": "demo"}), encoding="utf-8")
    assert runner.load_spec(good)["name"] == "demo"


def test_run_command_start_failure(tmp_path):
    log_path = tmp_path / "build.log"

    result = runner.run_command(
        [str(tmp_path / "missing-binary")], tmp_path, 5, log_path
    )

    assert result["exit_code"] is None
    assert result["timed_out"] is False
    assert "failed to start command" in log_path.read_text(encoding="utf-8")


def test_tail_lines_bounds_and_missing_file(tmp_path):
    assert runner.tail_lines(tmp_path / "missing.log") == []

    log_path = tmp_path / "out.log"
    log_path.write_text("x" * 300 + "\n\nlast\n", encoding="utf-8")
    lines = runner.tail_lines(log_path, count=3, limit=20)

    assert lines == ["x" * 17 + "...", "last"]
