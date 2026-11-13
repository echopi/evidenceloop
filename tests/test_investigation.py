import pytest

from evidenceloop import investigation
from evidenceloop.errors import EvidenceLoopError
from evidenceloop.ledger import Ledger


def add_evidence(ledger, kind="text", summary=None):
    entry = {
        "evidence_id": ledger.next_id(),
        "kind": kind,
        "source": "",
        "sha256": "",
        "captured_at": "",
        "producer": "test",
        "summary": summary or {},
    }
    ledger.append(entry)
    return entry["evidence_id"]


def green_experiment(ledger):
    return add_evidence(
        ledger,
        kind="experiment",
        summary={"test": {"exit_code": 0}, "gtest": {"tests_ran": 1, "passed": 1}},
    )


def test_add_requires_existing_evidence(tmp_path):
    ledger = Ledger(str(tmp_path))
    with pytest.raises(EvidenceLoopError):
        investigation.add_hypothesis(
            ledger, claim="c", expectation="e", evidence=["E-missing"]
        )


def test_add_requires_expectation(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    with pytest.raises(EvidenceLoopError):
        investigation.add_hypothesis(ledger, claim="c", expectation=" ", evidence=[evidence])


def test_confirmed_requires_reproducer_and_green(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )

    with pytest.raises(EvidenceLoopError):
        investigation.update_hypothesis(ledger, "H1", "confirmed", [evidence])

    green = green_experiment(ledger)
    result = investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=evidence, green=green
    )
    assert result["hypothesis"]["status"] == "confirmed"


def test_green_must_be_passing_experiment(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    failed = add_evidence(
        ledger, kind="experiment", summary={"test": {"exit_code": -11}}
    )
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )

    with pytest.raises(EvidenceLoopError):
        investigation.update_hypothesis(
            ledger, "H1", "confirmed", [evidence], reproducer=evidence, green=failed
        )


def test_unproven_requires_missing(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )

    with pytest.raises(EvidenceLoopError):
        investigation.update_hypothesis(ledger, "H1", "unproven", [evidence])

    result = investigation.update_hypothesis(
        ledger, "H1", "unproven", [evidence], missing="ASan stress result"
    )
    assert result["hypothesis"]["status"] == "unproven"


def test_stale_rounds_trigger_stop_rule(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )

    for _ in range(investigation.STALE_ROUNDS):
        investigation.update_hypothesis(ledger, "H1", "open", [evidence])

    state = investigation.next_action(ledger)
    assert state["action"] == "mark_unproven_or_change_evidence_source"
    assert state["no_new_evidence_rounds"] == investigation.STALE_ROUNDS


def test_next_does_not_close_while_unproven_remains(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    green = green_experiment(ledger)
    investigation.add_hypothesis(ledger, claim="first", expectation="e", evidence=[evidence])
    investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=evidence, green=green
    )
    investigation.add_hypothesis(ledger, claim="second", expectation="e", evidence=[evidence])
    investigation.update_hypothesis(
        ledger, "H2", "unproven", [evidence], missing="device trace"
    )

    state = investigation.next_action(ledger)
    assert state["action"] == "root_cause_not_closed"
    assert state["root_cause_confirmed"] is False
    assert state["counts"]["unproven"] == ["H2"]


def test_next_confirms_only_when_all_hypotheses_closed(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    green = green_experiment(ledger)
    investigation.add_hypothesis(ledger, claim="only", expectation="e", evidence=[evidence])
    investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=evidence, green=green
    )

    state = investigation.next_action(ledger)
    assert state["action"] == "root_cause_confirmed"
    assert state["root_cause_confirmed"] is True


def test_next_returns_first_open_hypothesis(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(ledger, claim="first", expectation="e", evidence=[evidence])
    investigation.add_hypothesis(ledger, claim="second", expectation="e", evidence=[evidence])

    state = investigation.next_action(ledger)
    assert state["action"] == "run_next_experiment"
    assert state["next_hypothesis"]["claim"] == "first"
