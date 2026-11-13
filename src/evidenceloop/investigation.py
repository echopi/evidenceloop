"""Hypothesis state machine for sustained investigations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import EvidenceLoopError
from .ledger import Ledger
from .util import now_iso, split_ids

STATUSES = ("open", "ruled_out", "confirmed", "unproven")
STALE_ROUNDS = 3


def load(ledger: Ledger) -> dict[str, Any]:
    ledger.validate_schema()
    state: dict[str, Any] = {
        "goal": "",
        "hypotheses": [],
        "round": 0,
        "no_new_evidence_rounds": 0,
        "updated_at": now_iso(),
    }
    if not ledger.investigation_path.exists():
        return state
    try:
        stored = json.loads(ledger.investigation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return state
    if isinstance(stored, dict):
        state.update(stored)
    state.setdefault("goal", "")
    state.setdefault("hypotheses", [])
    state.setdefault("round", 0)
    state.setdefault("no_new_evidence_rounds", 0)
    return state


def save(ledger: Ledger, state: dict[str, Any]) -> None:
    with ledger.write_transaction():
        _save_unlocked(ledger, state)


def _save_unlocked(ledger: Ledger, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    payload = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    _atomic_write(ledger.investigation_path, payload)


def _atomic_write(path: Path, payload: str) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as error:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise EvidenceLoopError(f"cannot write {path}: {error}") from error


def entries_by_id(ledger: Ledger) -> dict[str, dict[str, Any]]:
    return {entry.get("evidence_id"): entry for entry in ledger.entries()}


def is_green(entry: dict[str, Any] | None) -> bool:
    if not entry or entry.get("kind") != "experiment":
        return False
    summary = entry.get("summary") or {}
    test = summary.get("test") or {}
    return test.get("exit_code") == 0


def next_hypothesis_id(state: dict[str, Any]) -> str:
    highest = 0
    for hypothesis in state.get("hypotheses", []):
        raw = str(hypothesis.get("id", "H0"))
        if raw.startswith("H") and raw[1:].isdigit():
            highest = max(highest, int(raw[1:]))
    return f"H{highest + 1}"


def _require_known(known: dict[str, dict[str, Any]], evidence: list[str]) -> None:
    unknown = [item for item in evidence if item not in known]
    if unknown:
        raise EvidenceLoopError("unknown evidence: {}".format(", ".join(unknown)))


def add_hypothesis(
    ledger: Ledger,
    claim: str,
    expectation: str,
    evidence: list[str],
    spec: str = "",
    goal: str = "",
    note: str = "",
) -> dict[str, Any]:
    if not evidence:
        raise EvidenceLoopError("at least one evidence id is required")
    if not expectation.strip():
        raise EvidenceLoopError("expectation is required before running an experiment")
    with ledger.write_transaction():
        known = entries_by_id(ledger)
        _require_known(known, evidence)

        state = load(ledger)
        if goal:
            state["goal"] = goal
        hypothesis = {
            "id": next_hypothesis_id(state),
            "claim": claim,
            "expectation": expectation,
            "evidence": evidence,
            "spec": spec,
            "status": "open",
            "note": note,
            "created_at": now_iso(),
            "history": [],
        }
        state["hypotheses"].append(hypothesis)
        _save_unlocked(ledger, state)
    return {"hypothesis": hypothesis, "round": state["round"]}


def update_hypothesis(
    ledger: Ledger,
    hypothesis_id: str,
    status: str,
    evidence: list[str],
    note: str = "",
    missing: str = "",
    reproducer: str = "",
    green: str = "",
) -> dict[str, Any]:
    if status not in STATUSES:
        raise EvidenceLoopError(f"invalid status: {status}")
    with ledger.write_transaction():
        state = load(ledger)
        hypothesis = next(
            (item for item in state["hypotheses"] if item.get("id") == hypothesis_id), None
        )
        if not hypothesis:
            raise EvidenceLoopError(f"unknown hypothesis: {hypothesis_id}")

        known = entries_by_id(ledger)
        _require_known(known, evidence)

        if status == "confirmed":
            if not reproducer or not green:
                raise EvidenceLoopError(
                    "confirmed requires --reproducer and --green evidence "
                    "(root cause = mechanism + reproducer + green run)"
                )
            _require_known(known, [reproducer, green])
            if not is_green(known[green]):
                raise EvidenceLoopError(
                    f"green evidence is not a passing experiment: {green}"
                )
        if status == "unproven" and not missing.strip():
            raise EvidenceLoopError("unproven requires --missing describing the evidence gap")

        new_evidence = [
            item for item in evidence if item not in hypothesis.get("evidence", [])
        ]
        hypothesis["evidence"] = list(
            dict.fromkeys([*hypothesis.get("evidence", []), *evidence])
        )
        hypothesis["history"].append(
            {
                "at": now_iso(),
                "status": status,
                "evidence": evidence,
                "new_evidence": new_evidence,
                "note": note,
                "missing": missing,
                "reproducer": reproducer,
                "green": green,
            }
        )
        hypothesis["status"] = status
        if note:
            hypothesis["note"] = note

        state["round"] += 1
        if new_evidence:
            state["no_new_evidence_rounds"] = 0
        else:
            state["no_new_evidence_rounds"] += 1
        _save_unlocked(ledger, state)
    return {"hypothesis": hypothesis, "round": state["round"]}


def next_action(ledger: Ledger) -> dict[str, Any]:
    state = load(ledger)
    open_items = [item for item in state["hypotheses"] if item.get("status") == "open"]
    confirmed = [item["id"] for item in state["hypotheses"] if item.get("status") == "confirmed"]
    unproven = [item["id"] for item in state["hypotheses"] if item.get("status") == "unproven"]
    ruled_out = [item["id"] for item in state["hypotheses"] if item.get("status") == "ruled_out"]
    stale = state.get("no_new_evidence_rounds", 0) >= STALE_ROUNDS

    if open_items:
        if stale:
            action = "mark_unproven_or_change_evidence_source"
        elif confirmed:
            action = "continue_remaining_hypotheses"
        else:
            action = "run_next_experiment"
    elif unproven:
        # A confirmed hypothesis is scoped. The investigation is not closed
        # while any hypothesis is still unproven.
        action = "root_cause_not_closed"
    elif confirmed:
        action = "root_cause_confirmed"
    else:
        action = "no_open_hypothesis"

    return {
        "goal": state.get("goal", ""),
        "round": state.get("round", 0),
        "no_new_evidence_rounds": state.get("no_new_evidence_rounds", 0),
        "action": action,
        "root_cause_confirmed": action == "root_cause_confirmed",
        "next_hypothesis": open_items[0] if open_items else None,
        "counts": {
            "open": len(open_items),
            "confirmed": confirmed,
            "unproven": unproven,
            "ruled_out": ruled_out,
        },
        "rules": [
            "declare expectation before running the experiment",
            "each round must add or consume evidence",
            "confirmed requires mechanism + reproducer + green run",
            "root_cause_confirmed requires no open or unproven hypotheses",
            f"after {STALE_ROUNDS} rounds without new evidence, "
            "mark unproven or change evidence source",
        ],
    }


def summary(ledger: Ledger) -> dict[str, Any]:
    state = load(ledger)
    open_items = [item for item in state["hypotheses"] if item.get("status") == "open"]
    return {
        "goal": state.get("goal", ""),
        "round": state.get("round", 0),
        "no_new_evidence_rounds": state.get("no_new_evidence_rounds", 0),
        "open": [item["id"] for item in open_items],
        "confirmed": [
            item["id"] for item in state["hypotheses"] if item.get("status") == "confirmed"
        ],
        "unproven": [
            item["id"] for item in state["hypotheses"] if item.get("status") == "unproven"
        ],
        "next_claim": open_items[0]["claim"] if open_items else "",
    }


def parse_evidence_arg(value: str) -> list[str]:
    return split_ids(value)
