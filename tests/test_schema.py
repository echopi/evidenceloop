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
