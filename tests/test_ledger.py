from evidenceloop.ledger import Ledger


def test_ids_increment_and_entries_persist(tmp_path):
    ledger = Ledger(str(tmp_path))

    assert ledger.next_id().endswith("0001")
    ledger.append({"evidence_id": ledger.next_id(), "kind": "text", "summary": {}})

    assert ledger.next_id().endswith("0002")
    entries = ledger.entries()
    assert len(entries) == 1
    assert entries[0]["kind"] == "text"


def test_malformed_lines_are_skipped(tmp_path):
    ledger = Ledger(str(tmp_path))
    ledger.append({"evidence_id": ledger.next_id(), "kind": "text", "summary": {}})
    with open(ledger.path, "a", encoding="utf-8") as handle:
        handle.write("not-json\n")

    assert len(ledger.entries()) == 1
