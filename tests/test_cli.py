import json
import sys
from pathlib import Path

import pytest

from evidenceloop import __version__, schema
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


def passing_run_spec(tmp_path, name="pass-run", test_id="pass-run", slug="pass"):
    script = gtest_script(
        tmp_path,
        f"{slug}_gtest.py",
        [
            "[==========] 1 test from 1 test suite ran.",
            "[  PASSED  ] 1 test.",
        ],
    )
    return write_spec(
        tmp_path,
        f"{slug}-spec.json",
        {
            "name": name,
            "test_id": test_id,
            "repo": str(tmp_path),
            "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
        },
    )


def failing_run_spec(tmp_path, name="fail-run", test_id="fail-run", slug="fail"):
    script = gtest_script(
        tmp_path,
        f"{slug}_gtest.py",
        [
            "[==========] 1 test from 1 test suite ran.",
            "[  PASSED  ] 0 tests.",
            "[  FAILED  ] 1 test, listed below:",
            "[  FAILED  ] Suite.Case (0 ms)",
        ],
        exit_code=1,
    )
    return write_spec(
        tmp_path,
        f"{slug}-spec.json",
        {
            "name": name,
            "test_id": test_id,
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
    assert data["summary"]["test"]["test_id"] == "pass-run"
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
    assert data["summary"]["test"]["test_id"] == "fail-run"
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
    assert data["summary"]["build_skipped"] is True
    assert data["summary"]["test"]["exit_code"] == 0
    assert data["summary"]["test"]["test_id"] == "skip-build"

    code, verify_result = invoke(tmp_path, capsys, "verify")
    assert code == 0
    assert verify_result["ok"] == 1


def test_run_skip_build_rejects_invalid_build_spec(tmp_path, capsys):
    script = gtest_script(
        tmp_path,
        "pass_for_bad_skip.py",
        ["[==========] 1 test from 1 test suite ran.", "[  PASSED  ] 1 test."],
    )
    cases = [
        (False, "spec.build must be an object"),
        ({}, "build.argv must be a non-empty list"),
    ]

    for index, (build, message) in enumerate(cases):
        spec_path = write_spec(
            tmp_path,
            f"bad-skip-{index}.json",
            {
                "name": f"bad-skip-{index}",
                "repo": str(tmp_path),
                "build": build,
                "test": {"argv": [sys.executable, str(script)], "timeout_sec": 30},
            },
        )

        code, data = invoke(
            tmp_path, capsys, "run", "--spec", str(spec_path), "--skip-build"
        )

        assert code == 1
        assert message in data["error"]


def test_skip_build_content_key_differs_from_no_build(tmp_path, capsys):
    script = gtest_script(
        tmp_path,
        "same_case.py",
        ["[==========] 1 test from 1 test suite ran.", "[  PASSED  ] 1 test."],
    )
    test_step = {
        "argv": [sys.executable, str(script)],
        "timeout_sec": 30,
    }
    no_build_path = write_spec(
        tmp_path,
        "no-build-same.json",
        {
            "name": "no-build",
            "test_id": "same-case",
            "repo": str(tmp_path),
            "test": test_step,
        },
    )
    skip_build_path = write_spec(
        tmp_path,
        "skip-build-same.json",
        {
            "name": "skip-build",
            "test_id": "same-case",
            "repo": str(tmp_path),
            "build": {"argv": [sys.executable, "-c", "print('built')"]},
            "test": test_step,
        },
    )

    code, first = invoke(tmp_path, capsys, "run", "--spec", str(no_build_path))
    assert code == 0
    code, second = invoke(
        tmp_path, capsys, "run", "--spec", str(skip_build_path), "--skip-build"
    )
    assert code == 0

    code, first_view = invoke(
        tmp_path,
        capsys,
        "view",
        "--evidence",
        first["evidence_id"],
        "--section",
        "all",
    )
    assert code == 0
    code, second_view = invoke(
        tmp_path,
        capsys,
        "view",
        "--evidence",
        second["evidence_id"],
        "--section",
        "all",
    )
    assert code == 0
    assert (
        first_view["summary"]["content_key"]
        != second_view["summary"]["content_key"]
    )


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


def test_hypothesis_confirmed_requires_failed_reproducer_and_same_test(tmp_path, capsys):
    evidence_id = ingest_text(tmp_path, capsys)
    code, _ = invoke(
        tmp_path,
        capsys,
        "hyp",
        "add",
        "--claim",
        "claim",
        "--mechanism",
        "explicit mechanism",
        "--expect",
        "expectation",
        "--evidence",
        evidence_id,
    )
    assert code == 0

    passing_path = passing_run_spec(
        tmp_path, name="closure-pass", test_id="closure-case", slug="closure-pass"
    )
    code, passing = invoke(tmp_path, capsys, "run", "--spec", str(passing_path))
    assert code == 0
    passing_id = passing["evidence_id"]

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "confirmed",
        "--reproducer",
        passing_id,
        "--green",
        passing_id,
    )
    assert code == 1
    assert "reproducer" in data["error"]

    failing_path = failing_run_spec(
        tmp_path, name="closure-fail", test_id="closure-case", slug="closure-fail"
    )
    code, failing = invoke(tmp_path, capsys, "run", "--spec", str(failing_path))
    assert code == 0
    failing_id = failing["evidence_id"]

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "confirmed",
        "--reproducer",
        failing_id,
        "--green",
        passing_id,
    )
    assert code == 0
    assert data["hypothesis"]["status"] == "confirmed"
    assert data["hypothesis"]["closure"]["mechanism"] == "explicit mechanism"
    links = data["hypothesis"]["links"]
    assert {
        "evidence_id": failing_id,
        "role": "supports",
        "relation": "reproducer",
    } in links
    assert {
        "evidence_id": passing_id,
        "role": "supports",
        "relation": "green",
    } in links


def test_hypothesis_confirmed_accepts_equivalent_test_id(tmp_path, capsys):
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

    failing_path = failing_run_spec(
        tmp_path, name="eq-fail", test_id="case-a", slug="eq-fail"
    )
    passing_path = passing_run_spec(
        tmp_path, name="eq-pass", test_id="case-b", slug="eq-pass"
    )
    code, failing = invoke(tmp_path, capsys, "run", "--spec", str(failing_path))
    assert code == 0
    code, passing = invoke(tmp_path, capsys, "run", "--spec", str(passing_path))
    assert code == 0

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "confirmed",
        "--reproducer",
        failing["evidence_id"],
        "--green",
        passing["evidence_id"],
    )
    assert code == 1
    assert "different test_id" in data["error"]

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "confirmed",
        "--reproducer",
        failing["evidence_id"],
        "--green",
        passing["evidence_id"],
        "--equivalent-to",
        "case-a",
        "--equivalence-reason",
        "renamed case",
    )
    assert code == 0
    assert data["hypothesis"]["closure"]["equivalent_to"] == "case-a"


def test_hypothesis_ruled_out_requires_contradicts(tmp_path, capsys):
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

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "ruled_out",
        "--evidence",
        evidence_id,
    )
    assert code == 1
    assert "contradicts" in data["error"]

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "ruled_out",
        "--contradicts",
        evidence_id,
    )
    assert code == 0
    assert data["hypothesis"]["status"] == "ruled_out"
    assert {
        "evidence_id": evidence_id,
        "role": "contradicts",
        "relation": "observation",
    } in data["hypothesis"]["links"]


def test_verify_command_and_status_flags(tmp_path, capsys):
    source = tmp_path / "evidence.log"
    source.write_text("hello\n", encoding="utf-8")
    code, evidence = invoke(
        tmp_path, capsys, "ingest", "--kind", "text", "--path", str(source)
    )
    assert code == 0
    evidence_id = evidence["evidence_id"]

    code, result = invoke(tmp_path, capsys, "verify")
    assert code == 0
    assert result["checked"] == 1
    assert result["ok"] == 1

    code, result = invoke(tmp_path, capsys, "verify", "--evidence", evidence_id)
    assert code == 0
    assert result["evidence"][0]["evidence_id"] == evidence_id

    source.write_text("changed\n", encoding="utf-8")
    code, result = invoke(tmp_path, capsys, "verify")
    assert code == 0
    assert result["hash_mismatch"] == 1

    code, status = invoke(tmp_path, capsys, "status", "--verify")
    assert code == 0
    assert status["verification"]["hash_mismatch"] == 1

    code, next_result = invoke(tmp_path, capsys, "next", "--verify")
    assert code == 0
    assert next_result["verification"]["hash_mismatch"] == 1


def test_ingest_records_contract_metadata(tmp_path, capsys):
    source = tmp_path / "evidence.log"
    source.write_text("hello\n", encoding="utf-8")
    code, evidence = invoke(
        tmp_path, capsys, "ingest", "--kind", "text", "--path", str(source)
    )
    assert code == 0

    code, view = invoke(
        tmp_path,
        capsys,
        "view",
        "--evidence",
        evidence["evidence_id"],
        "--section",
        "all",
    )
    assert code == 0
    entry = view["summary"]
    assert entry["producer_version"] == __version__
    assert entry["record_schema_version"] == schema.RECORD_SCHEMA_VERSION
    assert entry["summary_schema_version"] == schema.SUMMARY_SCHEMA_VERSION
    assert entry["parser"]["name"] == "text"
    assert entry["content_key"]
    assert entry["summary"]["coverage"]["size_bytes"] == len("hello\n")


def test_run_records_contract_metadata(tmp_path, capsys):
    spec_path = passing_run_spec(tmp_path)
    code, data = invoke(tmp_path, capsys, "run", "--spec", str(spec_path))
    assert code == 0
    assert data["summary"]["test"]["log_sha256"]

    code, view = invoke(
        tmp_path,
        capsys,
        "view",
        "--evidence",
        data["evidence_id"],
        "--section",
        "all",
    )
    assert code == 0
    entry = view["summary"]
    assert entry["producer_version"] == __version__
    assert entry["record_schema_version"] == schema.RECORD_SCHEMA_VERSION
    assert entry["parser"]["name"] == "gtest"
    assert entry["content_key"]


def test_hypothesis_revision_and_source(tmp_path, capsys):
    evidence_id = ingest_text(tmp_path, capsys)
    code, added = invoke(
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
        "--source",
        "logcat",
    )
    assert code == 0
    assert added["revision"] == 1
    assert added["hypothesis"]["source"] == "logcat"

    code, listed = invoke(tmp_path, capsys, "hyp", "list")
    assert code == 0
    revision = listed["revision"]
    assert listed["last_source"] == "logcat"

    code, data = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "open",
        "--if-revision",
        str(revision - 1),
        "--source",
        "asan",
    )
    assert code == 1
    assert "revision mismatch" in data["error"]

    code, updated = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "open",
        "--if-revision",
        str(revision),
        "--source",
        "asan",
    )
    assert code == 0
    assert updated["revision"] == revision + 1
    assert updated["hypothesis"]["last_source"] == "asan"

    code, next_result = invoke(tmp_path, capsys, "next")
    assert code == 0
    assert next_result["last_source"] == "asan"
    assert next_result["sources"] == ["logcat", "asan"]

    code, rebased = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "open",
        "--rebase-timing",
    )
    assert code == 0
    assert rebased["hypothesis"]["history"][-1]["rebase_timing"] is True


def test_verify_does_not_create_missing_home(tmp_path, capsys):
    home = tmp_path / "missing"
    code = main(["--home", str(home), "verify"])
    data = json.loads(capsys.readouterr().out)

    assert code == 0
    assert data["checked"] == 0
    assert not home.exists()


def test_duplicate_ingest_does_not_reset_stale(tmp_path, capsys):
    source = tmp_path / "crash.log"
    source.write_text("same\n", encoding="utf-8")
    code, first = invoke(
        tmp_path, capsys, "ingest", "--kind", "text", "--path", str(source)
    )
    assert code == 0
    code, second = invoke(
        tmp_path, capsys, "ingest", "--kind", "text", "--path", str(source)
    )
    assert code == 0

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
        first["evidence_id"],
    )
    assert code == 0

    code, updated = invoke(
        tmp_path,
        capsys,
        "hyp",
        "update",
        "H1",
        "--status",
        "open",
        "--evidence",
        second["evidence_id"],
    )
    assert code == 0
    assert updated["hypothesis"]["history"][-1]["new_content"] == []

    code, state = invoke(tmp_path, capsys, "hyp", "list")
    assert code == 0
    assert state["no_new_evidence_rounds"] == 1


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
