import pytest

from evidenceloop import investigation
from evidenceloop.errors import EvidenceLoopError
from evidenceloop.ledger import Ledger


def add_evidence(
    ledger, kind="text", summary=None, sha256="", source=""
):
    entry = {
        "evidence_id": ledger.next_id(),
        "kind": kind,
        "source": source,
        "sha256": sha256,
        "captured_at": "",
        "producer": "test",
        "summary": summary or {},
    }
    ledger.append(entry)
    return entry["evidence_id"]


def experiment(ledger, test_id="case-1", exit_code=0, timed_out=False, build=None):
    summary = {
        "build_skipped": False,
        "test": {
            "test_id": test_id,
            "exit_code": exit_code,
            "timed_out": timed_out,
        },
    }
    if build is not None:
        summary["build"] = build
    return add_evidence(ledger, kind="experiment", summary=summary)


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


def test_add_requires_claim_as_mechanism(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    with pytest.raises(EvidenceLoopError, match="mechanism"):
        investigation.add_hypothesis(ledger, claim=" ", expectation="e", evidence=[evidence])


def test_confirmed_requires_reproducer_and_green(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )

    with pytest.raises(EvidenceLoopError):
        investigation.update_hypothesis(ledger, "H1", "confirmed", [evidence])

    failed = experiment(ledger, exit_code=1)
    green = experiment(ledger, exit_code=0)
    result = investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=failed, green=green
    )
    hypothesis = result["hypothesis"]
    assert hypothesis["status"] == "confirmed"
    assert hypothesis["closure"]["reproducer_test_id"] == "case-1"
    assert hypothesis["closure"]["green_test_id"] == "case-1"
    assert hypothesis["closure"]["timing_checked"] is True
    assert hypothesis["history"][-1]["mechanism"] == "c"
    assert {
        "evidence_id": failed,
        "role": "supports",
        "relation": "reproducer",
    } in hypothesis["links"]
    assert {
        "evidence_id": green,
        "role": "supports",
        "relation": "green",
    } in hypothesis["links"]


def test_green_must_be_passing_experiment(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )
    failed = experiment(ledger, exit_code=1)
    failed_green = experiment(ledger, exit_code=1)

    with pytest.raises(EvidenceLoopError, match="green"):
        investigation.update_hypothesis(
            ledger,
            "H1",
            "confirmed",
            [evidence],
            reproducer=failed,
            green=failed_green,
        )


def test_reproducer_must_be_a_failed_experiment(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )
    passing = experiment(ledger, exit_code=0)
    green = experiment(ledger, exit_code=0)

    with pytest.raises(EvidenceLoopError, match="reproducer"):
        investigation.update_hypothesis(
            ledger, "H1", "confirmed", [evidence], reproducer=passing, green=green
        )
    with pytest.raises(EvidenceLoopError, match="not an experiment"):
        investigation.update_hypothesis(
            ledger, "H1", "confirmed", [evidence], reproducer=evidence, green=green
        )


def test_reproducer_timeout_or_start_failure_is_not_valid(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )
    green = experiment(ledger, exit_code=0)
    timeout = experiment(ledger, exit_code=None, timed_out=True)
    start_failure = experiment(ledger, exit_code=None, timed_out=False)

    with pytest.raises(EvidenceLoopError, match="timed out"):
        investigation.update_hypothesis(
            ledger, "H1", "confirmed", [evidence], reproducer=timeout, green=green
        )
    with pytest.raises(EvidenceLoopError, match="start failure"):
        investigation.update_hypothesis(
            ledger,
            "H1",
            "confirmed",
            [evidence],
            reproducer=start_failure,
            green=green,
        )


def test_confirmed_requires_same_test_identity(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )
    failed = experiment(ledger, test_id="case-a", exit_code=1)
    green = experiment(ledger, test_id="case-b", exit_code=0)

    with pytest.raises(EvidenceLoopError, match="different test_id"):
        investigation.update_hypothesis(
            ledger, "H1", "confirmed", [evidence], reproducer=failed, green=green
        )
    with pytest.raises(EvidenceLoopError, match="equivalence-reason"):
        investigation.update_hypothesis(
            ledger,
            "H1",
            "confirmed",
            [evidence],
            reproducer=failed,
            green=green,
            equivalent_to="case-a",
        )
    with pytest.raises(EvidenceLoopError, match="reproducer test_id"):
        investigation.update_hypothesis(
            ledger,
            "H1",
            "confirmed",
            [evidence],
            reproducer=failed,
            green=green,
            equivalent_to="case-b",
            equivalence_reason="renamed",
        )

    result = investigation.update_hypothesis(
        ledger,
        "H1",
        "confirmed",
        [evidence],
        reproducer=failed,
        green=green,
        equivalent_to="case-a",
        equivalence_reason="the test was renamed",
    )
    closure = result["hypothesis"]["closure"]
    assert closure["equivalent_to"] == "case-a"
    assert closure["equivalence_reason"] == "the test was renamed"


def test_confirmed_requires_post_hypothesis_evidence(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    old_failed = experiment(ledger, exit_code=1)
    old_green = experiment(ledger, exit_code=0)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )

    with pytest.raises(EvidenceLoopError, match="after the hypothesis"):
        investigation.update_hypothesis(
            ledger,
            "H1",
            "confirmed",
            [evidence],
            reproducer=old_failed,
            green=old_green,
        )

    new_failed = experiment(ledger, exit_code=1)
    new_green = experiment(ledger, exit_code=0)
    result = investigation.update_hypothesis(
        ledger,
        "H1",
        "confirmed",
        [evidence],
        reproducer=new_failed,
        green=new_green,
    )
    assert result["hypothesis"]["status"] == "confirmed"


def test_ruled_out_requires_contradicts(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )

    with pytest.raises(EvidenceLoopError, match="contradicts"):
        investigation.update_hypothesis(
            ledger, "H1", "ruled_out", [evidence]
        )

    result = investigation.update_hypothesis(
        ledger, "H1", "ruled_out", [evidence], contradicts=[evidence]
    )
    assert result["hypothesis"]["status"] == "ruled_out"
    assert {
        "evidence_id": evidence,
        "role": "contradicts",
        "relation": "observation",
    } in result["hypothesis"]["links"]


def test_legacy_confirmed_requires_revalidation(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )
    failed = experiment(ledger, exit_code=1)
    green = experiment(ledger, exit_code=0)
    investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=failed, green=green
    )

    state = investigation.load(ledger)
    state["hypotheses"][0].pop("closure")
    investigation.save(ledger, state)

    action = investigation.next_action(ledger)
    assert action["action"] == "legacy_unvalidated"
    assert action["root_cause_confirmed"] is False
    assert action["counts"]["legacy_unvalidated"] == ["H1"]

    investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=failed, green=green
    )
    assert investigation.next_action(ledger)["action"] == "root_cause_confirmed"


def test_legacy_hypothesis_requires_rebase_for_valid_closure(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )
    failed = experiment(ledger, exit_code=1)
    green = experiment(ledger, exit_code=0)

    state = investigation.load(ledger)
    state["hypotheses"][0].pop("created_ledger_seq")
    investigation.save(ledger, state)

    result = investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=failed, green=green
    )
    assert result["hypothesis"]["closure"]["timing_checked"] is False

    action = investigation.next_action(ledger)
    assert action["action"] == "legacy_unvalidated"
    assert action["root_cause_confirmed"] is False

    investigation.update_hypothesis(
        ledger, "H1", "open", [evidence], rebase_timing=True
    )
    new_failed = experiment(ledger, exit_code=1)
    new_green = experiment(ledger, exit_code=0)
    result = investigation.update_hypothesis(
        ledger,
        "H1",
        "confirmed",
        [evidence],
        reproducer=new_failed,
        green=new_green,
    )

    assert result["hypothesis"]["closure"]["timing_checked"] is True
    assert investigation.next_action(ledger)["action"] == "root_cause_confirmed"


def test_legacy_ruled_out_requires_contradicts(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence]
    )
    investigation.update_hypothesis(
        ledger, "H1", "ruled_out", [evidence], contradicts=[evidence]
    )

    state = investigation.load(ledger)
    state["hypotheses"][0]["links"] = []
    investigation.save(ledger, state)

    action = investigation.next_action(ledger)
    assert action["action"] == "legacy_unvalidated"
    assert action["counts"]["legacy_unvalidated"] == ["H1"]


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


def test_duplicate_content_does_not_reset_stale(tmp_path):
    ledger = Ledger(str(tmp_path))
    first = add_evidence(ledger, sha256="same-digest", source="/crash.log")
    duplicate = add_evidence(ledger, sha256="same-digest", source="/crash.log")
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[first], source="logcat"
    )

    result = investigation.update_hypothesis(
        ledger, "H1", "open", [duplicate], source="logcat"
    )

    assert result["hypothesis"]["history"][-1]["new_content"] == []
    state = investigation.load(ledger)
    assert state["no_new_evidence_rounds"] == 1
    assert len(state["hypotheses"][0]["content_keys"]) == 1


def test_source_switch_resets_stale(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="c", expectation="e", evidence=[evidence], source="logcat"
    )
    for _ in range(investigation.STALE_ROUNDS):
        investigation.update_hypothesis(ledger, "H1", "open", [evidence])

    assert (
        investigation.load(ledger)["no_new_evidence_rounds"]
        == investigation.STALE_ROUNDS
    )

    result = investigation.update_hypothesis(
        ledger, "H1", "open", [evidence], source="asan"
    )

    assert result["hypothesis"]["last_source"] == "asan"
    state = investigation.load(ledger)
    assert state["no_new_evidence_rounds"] == 0
    assert state["sources"] == ["logcat", "asan"]
    action = investigation.next_action(ledger)
    assert action["last_source"] == "asan"
    assert action["sources"] == ["logcat", "asan"]


def test_revision_guards_add_and_update(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    added = investigation.add_hypothesis(
        ledger, claim="first", expectation="e", evidence=[evidence]
    )
    revision = added["revision"]
    assert revision == 1

    with pytest.raises(EvidenceLoopError, match="revision mismatch"):
        investigation.add_hypothesis(
            ledger,
            claim="second",
            expectation="e",
            evidence=[evidence],
            if_revision=revision - 1,
        )

    second = investigation.add_hypothesis(
        ledger,
        claim="second",
        expectation="e",
        evidence=[evidence],
        if_revision=revision,
    )
    assert second["revision"] == revision + 1

    with pytest.raises(EvidenceLoopError, match="revision mismatch"):
        investigation.update_hypothesis(
            ledger, "H1", "open", [evidence], if_revision=revision
        )

    updated = investigation.update_hypothesis(
        ledger,
        "H1",
        "open",
        [evidence],
        if_revision=second["revision"],
    )
    assert updated["revision"] == second["revision"] + 1
    assert investigation.next_action(ledger)["revision"] == updated["revision"]


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
    investigation.add_hypothesis(ledger, claim="first", expectation="e", evidence=[evidence])
    failed = experiment(ledger, exit_code=1)
    green = experiment(ledger, exit_code=0)
    investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=failed, green=green
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
    investigation.add_hypothesis(ledger, claim="only", expectation="e", evidence=[evidence])
    failed = experiment(ledger, exit_code=1)
    green = experiment(ledger, exit_code=0)
    investigation.update_hypothesis(
        ledger, "H1", "confirmed", [evidence], reproducer=failed, green=green
    )

    state = investigation.next_action(ledger)
    assert state["action"] == "root_cause_confirmed"
    assert state["root_cause_confirmed"] is True
    assert state["counts"]["legacy_unvalidated"] == []


def test_next_returns_first_open_hypothesis(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(ledger, claim="first", expectation="e", evidence=[evidence])
    investigation.add_hypothesis(ledger, claim="second", expectation="e", evidence=[evidence])

    state = investigation.next_action(ledger)
    assert state["action"] == "run_next_experiment"
    assert state["next_hypothesis"]["claim"] == "first"


def test_mechanism_defaults_to_claim_and_can_be_explicit(tmp_path):
    ledger = Ledger(str(tmp_path))
    evidence = add_evidence(ledger)
    investigation.add_hypothesis(
        ledger, claim="claim mechanism", expectation="e", evidence=[evidence]
    )
    investigation.add_hypothesis(
        ledger,
        claim="claim text",
        expectation="e",
        evidence=[evidence],
        mechanism="explicit mechanism",
    )

    state = investigation.load(ledger)
    assert state["hypotheses"][0]["mechanism"] == "claim mechanism"
    assert state["hypotheses"][0]["mechanism_source"] == "claim"
    assert state["hypotheses"][1]["mechanism"] == "explicit mechanism"
    assert state["hypotheses"][1]["mechanism_source"] == "explicit"
