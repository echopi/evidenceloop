import json

import pytest

from evidenceloop.cli import main
from evidenceloop.errors import EvidenceLoopError
from evidenceloop.ledger import Ledger, migrate_home


def make_legacy_home(tmp_path):
    source = tmp_path / "legacy"
    (source / "logs" / "run-1").mkdir(parents=True)
    (source / "ledger.jsonl").write_text('{"evidence_id": "E1"}\n', encoding="utf-8")
    (source / "investigation.json").write_text('{"goal": "legacy"}', encoding="utf-8")
    (source / "logs" / "run-1" / "test.log").write_text("log line\n", encoding="utf-8")
    (source / "notes.txt").write_text("leave me\n", encoding="utf-8")
    return source


def invoke(home, capsys, *args):
    code = main(["--home", str(home), *args])
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_migrate_copies_ledger_investigation_and_logs(tmp_path):
    source = make_legacy_home(tmp_path)
    target = Ledger(str(tmp_path / "target"))

    result = migrate_home(source, target)

    assert result["source"] == str(source)
    assert result["target"] == str(target.home)
    assert (target.home / "ledger.jsonl").read_text(encoding="utf-8") == (
        '{"evidence_id": "E1"}\n'
    )
    assert (target.home / "investigation.json").read_text(encoding="utf-8") == (
        '{"goal": "legacy"}'
    )
    assert (target.logs / "run-1" / "test.log").read_text(encoding="utf-8") == (
        "log line\n"
    )
    assert not (target.home / "notes.txt").exists()
    assert len(result["copied"]) == 3


def test_migrate_without_optional_files(tmp_path):
    source = tmp_path / "empty"
    source.mkdir()
    target = Ledger(str(tmp_path / "target"))

    result = migrate_home(source, target)

    assert result["copied"] == []


def test_migrate_existing_target_requires_force(tmp_path):
    source = make_legacy_home(tmp_path)
    target = Ledger(str(tmp_path / "target"))
    (target.home / "ledger.jsonl").write_text("existing\n", encoding="utf-8")

    with pytest.raises(EvidenceLoopError) as error:
        migrate_home(source, target)

    assert "--force" in str(error.value)
    assert (target.home / "ledger.jsonl").read_text(encoding="utf-8") == "existing\n"
    assert not (target.logs / "run-1").exists()


def test_migrate_force_overwrites_existing_files(tmp_path):
    source = make_legacy_home(tmp_path)
    target = Ledger(str(tmp_path / "target"))
    (target.home / "ledger.jsonl").write_text("old\n", encoding="utf-8")
    (target.home / "investigation.json").write_text("old\n", encoding="utf-8")

    result = migrate_home(source, target, force=True)

    assert (target.home / "ledger.jsonl").read_text(encoding="utf-8") == (
        '{"evidence_id": "E1"}\n'
    )
    assert (target.home / "investigation.json").read_text(encoding="utf-8") == (
        '{"goal": "legacy"}'
    )
    assert len(result["copied"]) == 3


def test_migrate_missing_source_raises(tmp_path):
    target = Ledger(str(tmp_path / "target"))

    with pytest.raises(EvidenceLoopError) as error:
        migrate_home(tmp_path / "missing", target)

    assert "source home not found" in str(error.value)


def test_migrate_cli_round_trip(tmp_path, capsys):
    source = make_legacy_home(tmp_path)

    code, data = invoke(tmp_path, capsys, "migrate", "--from", str(source))
    assert code == 0
    assert len(data["copied"]) == 3
    assert (tmp_path / "ledger.jsonl").is_file()

    code, data = invoke(tmp_path, capsys, "migrate", "--from", str(source))
    assert code == 1
    assert "--force" in data["error"]

    code, data = invoke(tmp_path, capsys, "migrate", "--from", str(source), "--force")
    assert code == 0
    assert (tmp_path / "investigation.json").is_file()
