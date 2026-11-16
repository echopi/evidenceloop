import pytest

from evidenceloop.errors import EvidenceLoopError
from evidenceloop.ledger import Ledger
from evidenceloop.util import sha256_file
from evidenceloop.verify import verify_ledger


def add_source_evidence(ledger, path, kind="text", summary=None):
    entry = {
        "kind": kind,
        "source": str(path),
        "sha256": sha256_file(path),
        "summary": summary or {},
        "producer": "test",
    }
    ledger.append(entry)
    return entry["evidence_id"]


def test_verify_ok_missing_and_hash_mismatch(tmp_path):
    source = tmp_path / "crash.log"
    source.write_text("crash", encoding="utf-8")
    ledger = Ledger(str(tmp_path / "home"))
    evidence_id = add_source_evidence(ledger, source)

    result = verify_ledger(ledger)
    assert result["checked"] == 1
    assert result["ok"] == 1
    assert result["evidence"][0]["status"] == "ok"
    assert result["evidence"][0]["parts"]["source"]["status"] == "ok"

    source.write_text("changed", encoding="utf-8")
    result = verify_ledger(ledger, evidence_id)
    assert result["hash_mismatch"] == 1
    assert result["evidence"][0]["status"] == "hash_mismatch"

    source.unlink()
    result = verify_ledger(ledger)
    assert result["missing"] == 1
    assert result["evidence"][0]["status"] == "missing"


def test_verify_unverifiable_without_digest(tmp_path):
    ledger = Ledger(str(tmp_path))
    ledger.append(
        {
            "kind": "text",
            "source": str(tmp_path / "missing"),
            "sha256": "",
            "summary": {},
        }
    )

    result = verify_ledger(ledger)

    assert result["unverifiable"] == 1
    assert result["evidence"][0]["status"] == "unverifiable"


def test_verify_experiment_logs(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    build_log = tmp_path / "build.log"
    build_log.write_text("built", encoding="utf-8")
    test_log = tmp_path / "test.log"
    test_log.write_text("passed", encoding="utf-8")
    ledger = Ledger(str(tmp_path / "home"))
    ledger.append(
        {
            "kind": "experiment",
            "source": str(spec),
            "sha256": sha256_file(spec),
            "summary": {
                "build": {
                    "log": str(build_log),
                    "log_sha256": sha256_file(build_log),
                },
                "test": {
                    "test_id": "case",
                    "exit_code": 0,
                    "log": str(test_log),
                    "log_sha256": sha256_file(test_log),
                },
            },
        }
    )

    result = verify_ledger(ledger)
    assert result["ok"] == 1
    parts = result["evidence"][0]["parts"]
    assert parts["build_log"]["status"] == "ok"
    assert parts["test_log"]["status"] == "ok"

    test_log.unlink()
    result = verify_ledger(ledger)
    assert result["missing"] == 1
    assert result["evidence"][0]["parts"]["test_log"]["status"] == "missing"


def test_incomplete_experiment_is_unverifiable(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    ledger = Ledger(str(tmp_path / "home"))
    ledger.append(
        {
            "kind": "experiment",
            "source": str(spec),
            "sha256": sha256_file(spec),
            "summary": {},
        }
    )

    result = verify_ledger(ledger)

    assert result["unverifiable"] == 1
    entry = result["evidence"][0]
    assert entry["status"] == "unverifiable"
    assert entry["parts"]["test_log"]["status"] == "unverifiable"


def test_experiment_missing_log_digest_is_unverifiable(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text("{}", encoding="utf-8")
    test_log = tmp_path / "test.log"
    test_log.write_text("passed", encoding="utf-8")
    ledger = Ledger(str(tmp_path / "home"))
    ledger.append(
        {
            "kind": "experiment",
            "source": str(spec),
            "sha256": sha256_file(spec),
            "summary": {
                "test": {
                    "test_id": "case",
                    "exit_code": 0,
                    "log": str(test_log),
                }
            },
        }
    )

    result = verify_ledger(ledger)

    assert result["unverifiable"] == 1
    assert result["evidence"][0]["parts"]["test_log"]["status"] == "unverifiable"


def test_experiment_missing_expected_build_is_unverifiable(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text('{"build": {"argv": ["make"]}}', encoding="utf-8")
    test_log = tmp_path / "test.log"
    test_log.write_text("passed", encoding="utf-8")
    ledger = Ledger(str(tmp_path / "home"))
    ledger.append(
        {
            "kind": "experiment",
            "source": str(spec),
            "sha256": sha256_file(spec),
            "summary": {
                "test": {
                    "test_id": "case",
                    "exit_code": 0,
                    "log": str(test_log),
                    "log_sha256": sha256_file(test_log),
                }
            },
        }
    )

    result = verify_ledger(ledger)

    assert result["unverifiable"] == 1
    assert result["evidence"][0]["parts"]["build_log"]["status"] == "unverifiable"


def test_skip_build_experiment_verifies_ok(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text('{"build": {"argv": ["make"]}}', encoding="utf-8")
    test_log = tmp_path / "test.log"
    test_log.write_text("passed", encoding="utf-8")
    ledger = Ledger(str(tmp_path / "home"))
    ledger.append(
        {
            "kind": "experiment",
            "source": str(spec),
            "sha256": sha256_file(spec),
            "summary": {
                "build": None,
                "build_skipped": True,
                "test": {
                    "test_id": "case",
                    "exit_code": 0,
                    "log": str(test_log),
                    "log_sha256": sha256_file(test_log),
                },
            },
        }
    )

    result = verify_ledger(ledger)

    assert result["ok"] == 1
    assert "build_log" not in result["evidence"][0]["parts"]


def test_forged_build_skipped_without_valid_spec_is_unverifiable(tmp_path):
    for index, spec_body in enumerate(
        ("{}", '{"build": {}}', '{"build": false}')
    ):
        spec = tmp_path / f"spec-{index}.json"
        spec.write_text(spec_body, encoding="utf-8")
        test_log = tmp_path / f"test-{index}.log"
        test_log.write_text("passed", encoding="utf-8")
        ledger = Ledger(str(tmp_path / f"home-{index}"))
        ledger.append(
            {
                "kind": "experiment",
                "source": str(spec),
                "sha256": sha256_file(spec),
                "summary": {
                    "build": None,
                    "build_skipped": True,
                    "test": {
                        "test_id": "case",
                        "exit_code": 0,
                        "log": str(test_log),
                        "log_sha256": sha256_file(test_log),
                    },
                },
            }
        )

        result = verify_ledger(ledger)

        assert result["unverifiable"] == 1
        assert result["evidence"][0]["parts"]["build_log"]["status"] == "unverifiable"


def test_malformed_path_type_is_unverifiable(tmp_path):
    ledger = Ledger(str(tmp_path))
    ledger.append(
        {
            "kind": "text",
            "source": 1,
            "sha256": "abc",
            "summary": {},
        }
    )

    result = verify_ledger(ledger)

    assert result["unverifiable"] == 1
    assert result["evidence"][0]["parts"]["source"]["status"] == "unverifiable"


def test_relative_path_resolves_against_ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    source = home / "crash.log"
    source.write_text("crash", encoding="utf-8")
    ledger = Ledger(str(home))
    ledger.append(
        {
            "kind": "text",
            "source": "crash.log",
            "sha256": sha256_file(source),
            "summary": {},
        }
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = verify_ledger(ledger)

    assert result["ok"] == 1


def test_verify_does_not_create_home(tmp_path):
    home = tmp_path / "missing"
    ledger = Ledger(str(home))

    result = verify_ledger(ledger)

    assert result["checked"] == 0
    assert not home.exists()


def test_verify_unknown_evidence(tmp_path):
    ledger = Ledger(str(tmp_path))

    with pytest.raises(EvidenceLoopError, match="unknown evidence"):
        verify_ledger(ledger, "E-missing")
