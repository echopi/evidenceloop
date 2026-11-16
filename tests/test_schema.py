import datetime as dt
import json

import pytest

from evidenceloop import __version__, investigation, schema
from evidenceloop.cli import main
from evidenceloop.errors import EvidenceLoopError
from evidenceloop.ledger import Ledger

LEGACY_LEDGER = {
    "evidence_id": "E20260101-0001",
    "kind": "text",
    "source": "",
    "sha256": "",
    "captured_at": "2026-01-01T00:00:00+00:00",
    "producer": "legacy",
    "summary": {},
}
LEGACY_STATE = {
    "goal": "legacy goal",
    "hypotheses": [],
    "round": 0,
    "no_new_evidence_rounds": 0,
}


def _legacy_home(tmp_path):
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps(LEGACY_LEDGER) + "\n", encoding="utf-8"
    )
    (tmp_path / "investigation.json").write_text(
        json.dumps(LEGACY_STATE), encoding="utf-8"
    )
    return tmp_path


def _write_meta(home, version):
    payload = {
        "schema_version": version,
        "created_at": "2026-11-13T00:00:00+00:00",
        "tool_version": "9.9.9",
    }
    path = home / schema.META_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload


def test_legacy_home_reads_as_v1(tmp_path):
    home = _legacy_home(tmp_path)
    ledger = Ledger(str(home))

    assert [entry["evidence_id"] for entry in ledger.entries()] == ["E20260101-0001"]
    assert investigation.load(ledger)["goal"] == "legacy goal"
    assert not (home / schema.META_FILENAME).exists()


def test_first_write_creates_meta(tmp_path):
    home = _legacy_home(tmp_path)
    ledger = Ledger(str(home))

    ledger.append({"kind": "text", "summary": {}})

    meta_file = home / schema.META_FILENAME
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    assert meta["schema_version"] == schema.SCHEMA_VERSION == 1
    assert meta["tool_version"] == __version__
    dt.datetime.fromisoformat(meta["created_at"])

    created_at = meta["created_at"]
    ledger.append({"kind": "text", "summary": {}})
    again = json.loads(meta_file.read_text(encoding="utf-8"))
    assert again["created_at"] == created_at


def test_investigation_write_creates_meta(tmp_path):
    home = _legacy_home(tmp_path)
    ledger = Ledger(str(home))

    investigation.save(ledger, dict(LEGACY_STATE))

    meta = json.loads((home / schema.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["schema_version"] == schema.SCHEMA_VERSION


def test_future_schema_version_is_rejected_without_rewrite(tmp_path):
    home = _legacy_home(tmp_path)
    meta_file, payload = _write_meta(home, schema.SCHEMA_VERSION + 1)
    ledger_text = (home / "ledger.jsonl").read_text(encoding="utf-8")
    state_text = (home / "investigation.json").read_text(encoding="utf-8")
    ledger = Ledger(str(home))

    with pytest.raises(EvidenceLoopError, match="schema_version"):
        ledger.entries()
    with pytest.raises(EvidenceLoopError, match="schema_version"):
        ledger.next_id()
    with pytest.raises(EvidenceLoopError, match="schema_version"):
        ledger.append({"kind": "text", "summary": {}})
    with pytest.raises(EvidenceLoopError, match="schema_version"):
        investigation.load(ledger)
    with pytest.raises(EvidenceLoopError, match="schema_version"):
        investigation.save(ledger, dict(LEGACY_STATE))

    assert json.loads(meta_file.read_text(encoding="utf-8")) == payload
    assert (home / "ledger.jsonl").read_text(encoding="utf-8") == ledger_text
    assert (home / "investigation.json").read_text(encoding="utf-8") == state_text


def test_cli_reports_future_schema_as_json_error(tmp_path, capsys):
    home = _legacy_home(tmp_path)
    _write_meta(home, schema.SCHEMA_VERSION + 1)

    code = main(["--home", str(home), "status"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert "schema_version" in payload["error"]


def test_future_record_schema_is_rejected(tmp_path):
    record = dict(LEGACY_LEDGER)
    record["record_schema_version"] = schema.RECORD_SCHEMA_VERSION + 1
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    ledger = Ledger(str(tmp_path))

    with pytest.raises(EvidenceLoopError, match="record_schema_version"):
        ledger.entries()


def test_record_missing_fields_is_rejected(tmp_path):
    record = {"evidence_id": "E1", "kind": "text"}
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    ledger = Ledger(str(tmp_path))

    with pytest.raises(EvidenceLoopError, match="missing summary"):
        ledger.entries()


def test_future_investigation_schema_is_rejected(tmp_path):
    home = _legacy_home(tmp_path)
    state = dict(LEGACY_STATE)
    state["schema_version"] = schema.INVESTIGATION_SCHEMA_VERSION + 1
    (home / "investigation.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    ledger = Ledger(str(home))

    with pytest.raises(EvidenceLoopError, match="investigation uses schema_version"):
        investigation.load(ledger)


def test_corrupt_investigation_is_not_silently_reset(tmp_path):
    home = _legacy_home(tmp_path)
    (home / "investigation.json").write_text("{bad", encoding="utf-8")
    ledger = Ledger(str(home))

    with pytest.raises(EvidenceLoopError, match="cannot parse"):
        investigation.load(ledger)


def test_record_summary_must_be_object(tmp_path):
    record = dict(LEGACY_LEDGER)
    record["summary"] = []
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    ledger = Ledger(str(tmp_path))

    with pytest.raises(EvidenceLoopError, match="summary must be an object"):
        ledger.entries()


def test_non_object_ledger_record_is_rejected(tmp_path):
    (tmp_path / "ledger.jsonl").write_text("[1, 2]\n", encoding="utf-8")
    ledger = Ledger(str(tmp_path))

    with pytest.raises(EvidenceLoopError, match="must be a JSON object"):
        ledger.entries()


def test_investigation_must_be_object(tmp_path):
    home = _legacy_home(tmp_path)
    ledger = Ledger(str(home))

    for payload in ("null", "[]", '"text"'):
        (home / "investigation.json").write_text(payload, encoding="utf-8")
        with pytest.raises(EvidenceLoopError, match="must contain a JSON object"):
            investigation.load(ledger)


def test_investigation_core_field_types_are_checked(tmp_path):
    home = _legacy_home(tmp_path)
    ledger = Ledger(str(home))
    cases = [
        ({"hypotheses": {}}, "hypotheses must be a list"),
        ({"sources": "device"}, "sources must be a list"),
        ({"last_source": 1}, "last_source must be a string"),
        ({"round": "1"}, "round"),
        ({"hypotheses": [{"id": 1, "status": "open"}]}, "string id and status"),
    ]

    for patch, message in cases:
        state = dict(LEGACY_STATE)
        state.update(patch)
        (home / "investigation.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
        with pytest.raises(EvidenceLoopError, match=message):
            investigation.load(ledger)


def test_current_record_schema_versions_are_accepted(tmp_path):
    record = dict(LEGACY_LEDGER)
    record["record_schema_version"] = schema.RECORD_SCHEMA_VERSION
    record["summary_schema_version"] = schema.SUMMARY_SCHEMA_VERSION
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    ledger = Ledger(str(tmp_path))

    assert ledger.entries()[0]["evidence_id"] == "E20260101-0001"
