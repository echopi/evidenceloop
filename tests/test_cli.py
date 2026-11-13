import json
import sys
from pathlib import Path

import pytest

from evidenceloop import __version__
from evidenceloop.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def invoke(tmp_path, capsys, *args):
    code = main(["--home", str(tmp_path), *args])
    out = capsys.readouterr().out
    return code, json.loads(out)


def write_spec(tmp_path, name, spec):
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def gtest_script(tmp_path, name, lines, exit_code=0):
    script = tmp_path / name
    body = "\n".join(f"print({json.dumps(line)})" for line in lines)
    if exit_code:
        body += f"\nraise SystemExit({exit_code})"
    script.write_text(body + "\n", encoding="utf-8")
    return script


def passing_run_spec(tmp_path):
    script = gtest_script(
        tmp_path,
        "pass_gtest.py",
        [
            "[==========] 1 test from 1 test suite ran.",
            "[  PASSED  ] 1 test.",
        ],
    )
    return write_spec(
        tmp_path,
        "pass-spec.json",
        {
            "name": "pass-run",
            "repo": str(tmp_path),
            "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
        },
    )


def test_ingest_and_status(tmp_path, capsys):
    code, data = invoke(
        tmp_path,
        capsys,
        "ingest",
        "--kind",
        "crash_log",
        "--path",
        str(FIXTURES / "tombstone_sample.log"),
    )
    assert code == 0
    assert data["summary"]["signal_count"] == 2
    evidence_id = data["evidence_id"]

    code, view = invoke(tmp_path, capsys, "view", "--evidence", evidence_id)
    assert code == 0
    assert view["summary"]["signal_count"] == 2

    code, view = invoke(
        tmp_path, capsys, "view", "--evidence", evidence_id, "--section", "signal_events"
    )
    assert code == 0
    assert len(view["summary"]) == 2

    code, view = invoke(
        tmp_path, capsys, "view", "--evidence", evidence_id, "--section", "all"
    )
    assert code == 0
    assert view["summary"]["evidence_id"] == evidence_id

    code, status = invoke(tmp_path, capsys, "status")
    assert code == 0
    assert status["evidence_count"] == 1
    assert status["by_kind"]["crash_log"] == 1
    assert status["investigation"]["open"] == []
    assert status["latest"][0]["one_line"].startswith("2 signal event(s)")
    assert "revision=abc123" in status["latest"][0]["one_line"]


def test_view_error_paths(tmp_path, capsys):
    code, data = invoke(tmp_path, capsys, "view", "--evidence", "E-nope")
    assert code == 1
    assert "unknown evidence" in data["error"]

    code, evidence = invoke(
        tmp_path,
        capsys,
        "ingest",
        "--kind",
        "text",
        "--path",
        str(FIXTURES / "gtest_sample.log"),
    )
    assert code == 0

    code, data = invoke(
        tmp_path,
        capsys,
        "view",
        "--evidence",
        evidence["evidence_id"],
        "--section",
        "nope",
    )
    assert code == 1
    assert "no section: nope" in data["error"]


def test_ingest_missing_file(tmp_path, capsys):
    code, data = invoke(
        tmp_path, capsys, "ingest", "--kind", "text", "--path", str(tmp_path / "missing")
    )

    assert code == 1
    assert "not a file" in data["error"]


def test_status_empty_home(tmp_path, capsys):
    code, status = invoke(tmp_path, capsys, "status")

    assert code == 0
    assert status["evidence_count"] == 0
    assert status["by_kind"] == {}
    assert status["last_experiment"] is None
    assert status["latest"] == []
    assert status["investigation"]["next_claim"] == ""


def test_run_records_experiment(tmp_path, capsys):
    spec_path = passing_run_spec(tmp_path)

    code, data = invoke(tmp_path, capsys, "run", "--spec", str(spec_path))
    assert code == 0
    assert data["summary"]["test"]["exit_code"] == 0
    assert data["summary"]["gtest"]["passed"] == 1

    code, status = invoke(tmp_path, capsys, "status")
    assert code == 0
    assert status["last_experiment"]["test"]["exit_code"] == 0
    assert status["last_experiment"]["gtest"]["passed"] == 1
    assert status["latest"][0]["one_line"].startswith("build=None test=0")


def test_run_parses_failing_gtest(tmp_path, capsys):
    script = gtest_script(
        tmp_path,
        "fail_gtest.py",
        [
            "[==========] 2 tests from 1 test suite ran.",
            "[  PASSED  ] 1 test.",
            "[  FAILED  ] 1 test, listed below:",
            "[  FAILED  ] Suite.Case (0 ms)",
            "  Failure",
            "  boom",
        ],
        exit_code=1,
    )
    spec_path = write_spec(
        tmp_path,
        "fail-spec.json",
        {
            "name": "fail-run",
            "repo": str(tmp_path),
            "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
        },
    )

    code, data = invoke(tmp_path, capsys, "run", "--spec", str(spec_path))

    assert code == 0
    assert data["summary"]["test"]["exit_code"] == 1
    assert data["summary"]["gtest"]["tests_ran"] == 2
    assert data["summary"]["gtest"]["failed"] == 1
    assert data["summary"]["gtest"]["failed_tests"] == ["Suite.Case"]
    assert data["summary"]["gtest"]["failure_lines"]
    run_dirs = [item for item in (tmp_path / "logs").iterdir() if item.is_dir()]
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "test.log").is_file()


def test_run_missing_repo(tmp_path, capsys):
    spec_path = write_spec(
        tmp_path,
        "missing-repo.json",
        {
            "name": "missing-repo",
            "repo": str(tmp_path / "nope"),
            "test": {"argv": [sys.executable, "-c", "print('x')"]},
        },
    )

    code, data = invoke(tmp_path, capsys, "run", "--spec", str(spec_path))

    assert code == 1
    assert "repo not found" in data["error"]


def test_run_bad_spec(tmp_path, capsys):
    spec_path = tmp_path / "bad-spec.json"
    spec_path.write_text("{not json", encoding="utf-8")

    code, data = invoke(tmp_path, capsys, "run", "--spec", str(spec_path))

    assert code == 1
    assert "cannot parse spec" in data["error"]


def test_run_skip_build(tmp_path, capsys):
    script = gtest_script(
        tmp_path,
        "pass_gtest.py",
        ["[==========] 1 test from 1 test suite ran.", "[  PASSED  ] 1 test."],
    )
    spec_path = write_spec(
        tmp_path,
        "skip-build.json",
        {
            "name": "skip-build",
            "repo": str(tmp_path),
            "build": {"argv": [sys.executable, "-c", "raise SystemExit(2)"]},
            "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
        },
    )

    code, data = invoke(tmp_path, capsys, "run", "--spec", str(spec_path), "--skip-build")

    assert code == 0
    assert data["summary"]["build"] is None
    assert data["summary"]["test"]["exit_code"] == 0


def ingest_text(tmp_path, capsys):
    code, evidence = invoke(
        tmp_path,
        capsys,
        "ingest",
        "--kind",
        "text",
        "--path",
        str(FIXTURES / "gtest_sample.log"),
    )
    assert code == 0
    return evidence["evidence_id"]


def test_hypothesis_confirmed_guard_and_next(tmp_path, capsys):
    evidence_id = ingest_text(tmp_path, capsys)

    code, _ = invoke(
        tmp_path,
        capsys,
        "hyp",
        "add",
        "--claim",
        "claim",
        "--expect",
        "expectation",
        "--evidence",
        evidence_id,
        "--goal",
        "ship the fix",
    )
    assert code == 0

    code, listed = invoke(tmp_path, capsys, "hyp", "list")
    assert code == 0
    assert listed["hypotheses"][0]["id"] == "H1"

    code, data = invoke(tmp_path, capsys, "hyp", "update", "H1", "--status", "confirmed")
    assert code == 1
    assert "reproducer" in data["error"]

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "confirmed",
        "--reproducer",
        evidence_id,
    )
    assert code == 1
    assert "green" in data["error"]

    code, data = invoke(tmp_path, capsys, "next")
    assert code == 0
    assert data["action"] == "run_next_experiment"
    assert data["next_hypothesis"]["id"] == "H1"
    assert data["goal"] == "ship the fix"


def test_hypothesis_unproven_guard(tmp_path, capsys):
    evidence_id = ingest_text(tmp_path, capsys)
    code, _ = invoke(
        tmp_path,
        capsys,
        "hyp",
        "add",
        "--claim",
        "claim",
        "--expect",
        "expectation",
        "--evidence",
        evidence_id,
    )
    assert code == 0

    code, data = invoke(tmp_path, capsys, "hyp", "update", "H1", "--status", "unproven")
    assert code == 1
    assert "missing" in data["error"]

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "unproven",
        "--missing",
        "device trace",
    )
    assert code == 0
    assert data["hypothesis"]["status"] == "unproven"

    code, data = invoke(tmp_path, capsys, "next")
    assert code == 0
    assert data["action"] == "root_cause_not_closed"


def test_cli_rejects_invalid_status(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main(["--home", str(tmp_path), "hyp", "update", "H1", "--status", "pending"])

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as error:
        main(["--version"])

    assert error.value.code == 0
    assert f"evidenceloop {__version__}" in capsys.readouterr().out
