import json
import multiprocessing
import os
import re

import pytest

from evidenceloop import investigation
from evidenceloop.errors import EvidenceLoopError
from evidenceloop.ledger import Ledger
from evidenceloop.locking import file_lock

WRITERS = 2
ENTRIES_PER_WRITER = 100
HYPOTHESES_PER_WRITER = 25


def _write_entries(home, count):
    ledger = Ledger(home)
    for index in range(count):
        entry = {
            "evidence_id": ledger.next_id(),
            "kind": "text",
            "producer": f"writer-{os.getpid()}",
            "summary": {"index": index},
        }
        ledger.append(entry)


def _add_hypotheses(home, evidence_id, count):
    ledger = Ledger(home)
    for index in range(count):
        investigation.add_hypothesis(
            ledger,
            claim=f"claim-{index}",
            expectation="expectation",
            evidence=[evidence_id],
        )


def _run_workers(target, args_list):
    processes = [
        multiprocessing.Process(target=target, args=args) for args in args_list
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(120)
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join(10)
    assert [process.exitcode for process in processes] == [0] * len(processes)


def test_concurrent_writers_allocate_unique_ids(tmp_path):
    home = str(tmp_path)
    _run_workers(
        _write_entries,
        [(home, ENTRIES_PER_WRITER)] * WRITERS,
    )

    raw = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    lines = [line for line in raw.split("\n") if line]
    records = [json.loads(line) for line in lines]
    ids = [record["evidence_id"] for record in records]

    assert len(records) == WRITERS * ENTRIES_PER_WRITER
    assert len(set(ids)) == len(records)
    assert all(re.fullmatch(r"E\d{8}-\d{4}", evidence_id) for evidence_id in ids)
    assert len(Ledger(home).entries()) == len(records)

    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == 1


def test_concurrent_hypothesis_writes_do_not_lose_updates(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence_id = ledger.append({"kind": "text", "summary": {}})["evidence_id"]

    _run_workers(
        _add_hypotheses,
        [(str(tmp_path), evidence_id, HYPOTHESES_PER_WRITER)] * WRITERS,
    )

    state = investigation.load(Ledger(str(tmp_path)))
    ids = [item["id"] for item in state["hypotheses"]]
    assert len(ids) == WRITERS * HYPOTHESES_PER_WRITER
    assert len(set(ids)) == len(ids)


def test_lock_timeout_raises_instead_of_dropping_write(tmp_path):
    ledger = Ledger(str(tmp_path), lock_timeout=0.2)
    with file_lock(ledger.lock_path):
        with pytest.raises(EvidenceLoopError, match="lock"):
            ledger.append({"kind": "text", "summary": {}})

    assert ledger.entries() == []
    assert not (tmp_path / "meta.json").exists()


def test_torn_trailing_record_is_never_returned(tmp_path):
    ledger = Ledger(str(tmp_path))
    ledger.append({"kind": "text", "summary": {}})
    with open(ledger.path, "a", encoding="utf-8") as handle:
        handle.write('{"evidence_id": "E-torn", "kind": "text"')

    assert [entry["kind"] for entry in ledger.entries()] == ["text"]

    ledger.append({"kind": "text", "summary": {}})
    assert [entry["kind"] for entry in ledger.entries()] == ["text", "text"]
