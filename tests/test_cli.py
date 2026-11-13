import json
from pathlib import Path

from evidenceloop.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def invoke(tmp_path, capsys, *args):
    code = main(["--home", str(tmp_path), *args])
    out = capsys.readouterr().out
    return code, json.loads(out)


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

    code, status = invoke(tmp_path, capsys, "status")
    assert code == 0
    assert status["evidence_count"] == 1
    assert status["by_kind"]["crash_log"] == 1
    assert status["investigation"]["open"] == []


def test_run_records_experiment(tmp_path, capsys):
    spec = {
        "name": "demo",
        "repo": str(tmp_path),
        "test": {
            "argv": [
                "python3",
                "-c",
                "print('[==========] 1 test from 1 test suite ran.');"
                "print('[  PASSED  ] 1 test.')",
            ],
            "timeout_sec": 30,
        },
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    code, data = invoke(tmp_path, capsys, "run", "--spec", str(spec_path))
    assert code == 0
    assert data["summary"]["test"]["exit_code"] == 0
    assert data["summary"]["gtest"]["passed"] == 1


def test_hypothesis_guard_and_next(tmp_path, capsys):
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
        evidence["evidence_id"],
    )
    assert code == 0

    code, data = invoke(tmp_path, capsys, "hyp", "update", "H1", "--status", "confirmed")
    assert code == 1
    assert "reproducer" in data["error"]

    code, data = invoke(tmp_path, capsys, "next")
    assert code == 0
    assert data["action"] == "run_next_experiment"
    assert data["next_hypothesis"]["id"] == "H1"
