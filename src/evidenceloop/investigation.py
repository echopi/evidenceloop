"""Hypothesis state machine for sustained investigations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import schema
from .content import content_key
from .errors import EvidenceLoopError
from .ledger import Ledger
from .util import now_iso, split_ids

STATUSES = ("open", "ruled_out", "confirmed", "unproven")
STALE_ROUNDS = 3
CLOSURE_RULES_VERSION = 1


def load(ledger: Ledger) -> dict[str, Any]:
    ledger.validate_schema()
    state: dict[str, Any] = {
        "goal": "",
        "hypotheses": [],
        "round": 0,
        "no_new_evidence_rounds": 0,
        "revision": 0,
        "schema_version": schema.INVESTIGATION_SCHEMA_VERSION,
        "last_source": "",
        "sources": [],
        "updated_at": now_iso(),
    }
    if not ledger.investigation_path.exists():
        return state
    try:
        text = ledger.investigation_path.read_text(encoding="utf-8")
    except OSError as error:
        raise EvidenceLoopError(
            f"cannot read {ledger.investigation_path}: {error}"
        ) from error
    try:
        stored = json.loads(text)
    except json.JSONDecodeError as error:
        raise EvidenceLoopError(
            f"cannot parse {ledger.investigation_path}: {error}"
        ) from error
    if not isinstance(stored, dict):
        raise EvidenceLoopError(
            f"{ledger.investigation_path} must contain a JSON object"
        )
    state.update(stored)
    state.setdefault("goal", "")
    state.setdefault("hypotheses", [])
    state.setdefault("round", 0)
    state.setdefault("no_new_evidence_rounds", 0)
    state.setdefault("revision", 0)
    state.setdefault("schema_version", 1)
    state.setdefault("last_source", "")
    state.setdefault("sources", [])
    version = state["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise EvidenceLoopError(f"invalid investigation schema_version: {version!r}")
    if version > schema.INVESTIGATION_SCHEMA_VERSION:
        raise EvidenceLoopError(
            f"investigation uses schema_version {version}, but this evidenceloop "
            f"supports up to {schema.INVESTIGATION_SCHEMA_VERSION}"
        )
    revision = state["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise EvidenceLoopError(f"invalid investigation revision: {revision!r}")
    if not isinstance(state["goal"], str):
        raise EvidenceLoopError("investigation goal must be a string")
    if not isinstance(state["hypotheses"], list):
        raise EvidenceLoopError("investigation hypotheses must be a list")
    for item in state["hypotheses"]:
        if not isinstance(item, dict):
            raise EvidenceLoopError("investigation hypotheses must contain objects")
        if not isinstance(item.get("id"), str) or not isinstance(
            item.get("status"), str
        ):
            raise EvidenceLoopError(
                "investigation hypothesis entries must contain string id and status"
            )
    if not isinstance(state["sources"], list) or not all(
        isinstance(item, str) for item in state["sources"]
    ):
        raise EvidenceLoopError("investigation sources must be a list of strings")
    if not isinstance(state["last_source"], str):
        raise EvidenceLoopError("investigation last_source must be a string")
    for key in ("round", "no_new_evidence_rounds"):
        value = state[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EvidenceLoopError(f"invalid investigation {key}: {value!r}")
    return state


def save(ledger: Ledger, state: dict[str, Any]) -> None:
    with ledger.write_transaction():
        _save_unlocked(ledger, state)


def _save_unlocked(ledger: Ledger, state: dict[str, Any]) -> None:
    revision = state.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise EvidenceLoopError(f"invalid investigation revision: {revision!r}")
    state["schema_version"] = schema.INVESTIGATION_SCHEMA_VERSION
    state["revision"] = revision + 1
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


def _experiment_test(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry or entry.get("kind") != "experiment":
        return None
    summary = entry.get("summary") or {}
    test = summary.get("test")
    return test if isinstance(test, dict) else None


def _experiment_test_id(entry: dict[str, Any] | None) -> str:
    test = _experiment_test(entry)
    if not test:
        return ""
    value = test.get("test_id")
    return "" if value is None else str(value)


def _build_ok(entry: dict[str, Any]) -> bool:
    summary = entry.get("summary") or {}
    build = summary.get("build")
    if not build:
        return True
    if not isinstance(build, dict):
        return False
    return build.get("exit_code") == 0 and not build.get("timed_out")


def _experiment_problem(
    entry: dict[str, Any] | None,
    label: str,
    require_failure: bool,
) -> str | None:
    test = _experiment_test(entry)
    if test is None:
        return f"{label} is not an experiment with a test result"
    if test.get("timed_out"):
        return f"{label} experiment timed out"
    exit_code = test.get("exit_code")
    if exit_code is None:
        return f"{label} experiment did not produce an exit code (start failure)"
    if require_failure and exit_code == 0:
        return f"{label} experiment passed; a reproducer must fail"
    if not require_failure and exit_code != 0:
        return f"{label} experiment did not pass"
    if not _build_ok(entry):
        return f"{label} experiment build did not succeed"
    if not _experiment_test_id(entry):
        return f"{label} experiment has no test_id; set test_id in the spec"
    return None


def is_green(entry: dict[str, Any] | None) -> bool:
    return _experiment_problem(entry, "green", False) is None


def _links(ids: list[str], role: str, relation: str = "observation") -> list[dict[str, str]]:
    return [
        {"evidence_id": evidence_id, "role": role, "relation": relation}
        for evidence_id in dict.fromkeys(ids)
    ]


def _merge_links(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = list(existing or [])
    seen = {
        (link.get("evidence_id"), link.get("role"), link.get("relation"))
        for link in merged
    }
    for link in incoming:
        key = (link.get("evidence_id"), link.get("role"), link.get("relation"))
        if key not in seen:
            merged.append(link)
            seen.add(key)
    return merged


def _has_contradiction(hypothesis: dict[str, Any]) -> bool:
    return any(
        link.get("role") == "contradicts"
        for link in (hypothesis.get("links") or [])
        if isinstance(link, dict)
    )


def _is_validated_closed(hypothesis: dict[str, Any]) -> bool:
    status = hypothesis.get("status")
    if status == "confirmed":
        closure = hypothesis.get("closure") or {}
        return (
            closure.get("rules_version") == CLOSURE_RULES_VERSION
            and closure.get("timing_checked") is True
        )
    if status == "ruled_out":
        return _has_contradiction(hypothesis)
    return False


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


def _check_revision(state: dict[str, Any], expected: int | None) -> None:
    if expected is None:
        return
    current = state.get("revision", 0)
    if current != expected:
        raise EvidenceLoopError(
            f"revision mismatch: current {current}, expected {expected}; "
            "reread the investigation before updating"
        )


def add_hypothesis(
    ledger: Ledger,
    claim: str,
    expectation: str,
    evidence: list[str],
    spec: str = "",
    goal: str = "",
    note: str = "",
    mechanism: str = "",
    source: str = "",
    if_revision: int | None = None,
) -> dict[str, Any]:
    if not evidence:
        raise EvidenceLoopError("at least one evidence id is required")
    if not claim.strip():
        raise EvidenceLoopError("claim is required as the declared mechanism")
    if not expectation.strip():
        raise EvidenceLoopError("expectation is required before running an experiment")
    with ledger.write_transaction():
        entries = ledger.entries()
        known = {entry.get("evidence_id"): entry for entry in entries}
        _require_known(known, evidence)

        state = load(ledger)
        _check_revision(state, if_revision)
        if goal:
            state["goal"] = goal
        declared_mechanism = mechanism.strip() or claim.strip()
        source_value = source.strip()
        content_keys = list(
            dict.fromkeys(content_key(known[evidence_id]) for evidence_id in evidence)
        )
        hypothesis = {
            "id": next_hypothesis_id(state),
            "claim": claim,
            "mechanism": declared_mechanism,
            "mechanism_source": "explicit" if mechanism.strip() else "claim",
            "expectation": expectation,
            "evidence": list(dict.fromkeys(evidence)),
            "content_keys": content_keys,
            "links": [],
            "spec": spec,
            "status": "open",
            "note": note,
            "source": source_value,
            "last_source": source_value,
            "created_at": now_iso(),
            "created_ledger_seq": len(entries),
            "history": [],
        }
        state["hypotheses"].append(hypothesis)
        if source_value:
            state["last_source"] = source_value
            state["sources"] = list(
                dict.fromkeys([*state.get("sources", []), source_value])
            )
        _save_unlocked(ledger, state)
    return {
        "hypothesis": hypothesis,
        "round": state["round"],
        "revision": state.get("revision", 0),
    }


def update_hypothesis(
    ledger: Ledger,
    hypothesis_id: str,
    status: str,
    evidence: list[str],
    note: str = "",
    missing: str = "",
    reproducer: str = "",
    green: str = "",
    supports: list[str] | None = None,
    contradicts: list[str] | None = None,
    equivalent_to: str = "",
    equivalence_reason: str = "",
    mechanism: str = "",
    source: str = "",
    rebase_timing: bool = False,
    if_revision: int | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise EvidenceLoopError(f"invalid status: {status}")
    supports = supports or []
    contradicts = contradicts or []
    with ledger.write_transaction():
        state = load(ledger)
        _check_revision(state, if_revision)
        hypothesis = next(
            (item for item in state["hypotheses"] if item.get("id") == hypothesis_id), None
        )
        if not hypothesis:
            raise EvidenceLoopError(f"unknown hypothesis: {hypothesis_id}")

        entries = ledger.entries()
        known = {entry.get("evidence_id"): entry for entry in entries}
        index = {
            entry.get("evidence_id"): position
            for position, entry in enumerate(entries)
        }
        incoming = list(dict.fromkeys([*evidence, *supports, *contradicts]))
        if status == "confirmed":
            if not reproducer or not green:
                raise EvidenceLoopError(
                    "confirmed requires --reproducer and --green evidence "
                    "(root cause = mechanism + reproducer + green run)"
                )
            incoming = list(dict.fromkeys([*incoming, reproducer, green]))
        _require_known(known, incoming)

        if rebase_timing:
            hypothesis["created_ledger_seq"] = len(entries)

        if "content_keys" not in hypothesis:
            hypothesis["content_keys"] = list(
                dict.fromkeys(
                    content_key(known[evidence_id])
                    for evidence_id in hypothesis.get("evidence", [])
                    if evidence_id in known
                )
            )
        existing_content_keys = set(hypothesis.get("content_keys", []))
        incoming_keys = [content_key(known[evidence_id]) for evidence_id in incoming]
        novel_ids: list[str] = []
        novel_keys: set[str] = set()
        for evidence_id, key in zip(incoming, incoming_keys):
            if key not in existing_content_keys and key not in novel_keys:
                novel_ids.append(evidence_id)
                novel_keys.add(key)

        source_value = (
            source.strip()
            or hypothesis.get("last_source", "")
            or hypothesis.get("source", "")
        )
        source_changed = bool(source.strip()) and source_value != (
            hypothesis.get("last_source") or ""
        )
        hypothesis["last_source"] = source_value
        if source_value:
            state["last_source"] = source_value
            state["sources"] = list(
                dict.fromkeys([*state.get("sources", []), source_value])
            )

        if mechanism.strip():
            hypothesis["mechanism"] = mechanism.strip()
            hypothesis["mechanism_source"] = "explicit"
        mechanism_value = hypothesis.get("mechanism") or hypothesis.get("claim", "")

        closure_info: dict[str, Any] | None = None
        equivalent = ""
        reason = ""
        if status == "confirmed":
            reproblem = _experiment_problem(known.get(reproducer), "reproducer", True)
            if reproblem:
                raise EvidenceLoopError(f"{reproblem}: {reproducer}")
            green_problem = _experiment_problem(known.get(green), "green", False)
            if green_problem:
                raise EvidenceLoopError(f"{green_problem}: {green}")

            repro_test_id = _experiment_test_id(known.get(reproducer))
            green_test_id = _experiment_test_id(known.get(green))
            if repro_test_id != green_test_id:
                if not equivalent_to:
                    raise EvidenceLoopError(
                        "reproducer and green use different test_id values; pass "
                        "--equivalent-to <reproducer_test_id> and "
                        "--equivalence-reason <why they are equivalent>"
                    )
                if equivalent_to != repro_test_id:
                    raise EvidenceLoopError(
                        f"--equivalent-to must name the reproducer test_id: {repro_test_id}"
                    )
                if not equivalence_reason.strip():
                    raise EvidenceLoopError(
                        "different test_id values require --equivalence-reason"
                    )
                equivalent = equivalent_to
                reason = equivalence_reason.strip()

            created_seq = hypothesis.get("created_ledger_seq")
            timing_checked = isinstance(created_seq, int) and not isinstance(
                created_seq, bool
            )
            if timing_checked:
                for label, evidence_id in (("reproducer", reproducer), ("green", green)):
                    position = index.get(evidence_id)
                    if position is None or position < created_seq:
                        raise EvidenceLoopError(
                            f"{label} evidence must be appended after the hypothesis "
                            f"was created: {evidence_id}"
                        )

            if not mechanism_value.strip():
                raise EvidenceLoopError("confirmed requires a declared mechanism")
            closure_info = {
                "rules_version": CLOSURE_RULES_VERSION,
                "validated_at": now_iso(),
                "reproducer": reproducer,
                "green": green,
                "reproducer_test_id": repro_test_id,
                "green_test_id": green_test_id,
                "equivalent_to": equivalent,
                "equivalence_reason": reason,
                "mechanism": mechanism_value.strip(),
                "timing_checked": timing_checked,
            }

        new_links: list[dict[str, str]] = []
        new_links.extend(_links(supports, "supports"))
        new_links.extend(_links(contradicts, "contradicts"))
        if status == "confirmed":
            new_links.extend(_links([reproducer], "supports", "reproducer"))
            new_links.extend(_links([green], "supports", "green"))
        merged_links = _merge_links(hypothesis.get("links", []), new_links)
        if status == "ruled_out" and not any(
            link.get("role") == "contradicts" for link in merged_links
        ):
            raise EvidenceLoopError(
                "ruled_out requires at least one contradicting evidence (--contradicts)"
            )

        if status == "unproven" and not missing.strip():
            raise EvidenceLoopError("unproven requires --missing describing the evidence gap")

        existing_evidence = list(hypothesis.get("evidence", []))
        hypothesis["evidence"] = list(
            dict.fromkeys([*existing_evidence, *incoming])
        )
        hypothesis["content_keys"] = list(
            dict.fromkeys([*hypothesis.get("content_keys", []), *incoming_keys])
        )
        hypothesis["links"] = merged_links
        hypothesis["history"].append(
            {
                "at": now_iso(),
                "status": status,
                "evidence": incoming,
                "new_evidence": novel_ids,
                "new_content": novel_ids,
                "links": new_links,
                "note": note,
                "missing": missing,
                "reproducer": reproducer,
                "green": green,
                "equivalent_to": equivalent,
                "equivalence_reason": reason,
                "mechanism": mechanism_value.strip(),
                "source": source_value,
                "rebase_timing": rebase_timing,
                "closure": closure_info,
            }
        )
        hypothesis["status"] = status
        if status == "confirmed" and closure_info is not None:
            hypothesis["closure"] = closure_info
        if note:
            hypothesis["note"] = note

        state["round"] += 1
        if novel_ids or source_changed:
            state["no_new_evidence_rounds"] = 0
        else:
            state["no_new_evidence_rounds"] += 1
        _save_unlocked(ledger, state)
    return {
        "hypothesis": hypothesis,
        "round": state["round"],
        "revision": state.get("revision", 0),
    }


def next_action(ledger: Ledger) -> dict[str, Any]:
    state = load(ledger)
    open_items = [item for item in state["hypotheses"] if item.get("status") == "open"]
    confirmed_items = [
        item for item in state["hypotheses"] if item.get("status") == "confirmed"
    ]
    ruled_out_items = [
        item for item in state["hypotheses"] if item.get("status") == "ruled_out"
    ]
    unproven = [item["id"] for item in state["hypotheses"] if item.get("status") == "unproven"]
    confirmed = [item["id"] for item in confirmed_items]
    ruled_out = [item["id"] for item in ruled_out_items]
    legacy_unvalidated = [
        item["id"]
        for item in (*confirmed_items, *ruled_out_items)
        if not _is_validated_closed(item)
    ]
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
    elif legacy_unvalidated:
        action = "legacy_unvalidated"
    elif confirmed:
        action = "root_cause_confirmed"
    else:
        action = "no_open_hypothesis"

    return {
        "goal": state.get("goal", ""),
        "round": state.get("round", 0),
        "revision": state.get("revision", 0),
        "no_new_evidence_rounds": state.get("no_new_evidence_rounds", 0),
        "last_source": state.get("last_source", ""),
        "sources": state.get("sources", []),
        "action": action,
        "root_cause_confirmed": action == "root_cause_confirmed",
        "next_hypothesis": open_items[0] if open_items else None,
        "counts": {
            "open": len(open_items),
            "confirmed": confirmed,
            "unproven": unproven,
            "ruled_out": ruled_out,
            "legacy_unvalidated": legacy_unvalidated,
        },
        "rules": [
            "declare expectation before running the experiment",
            "each round must add or consume evidence",
            "confirmed requires a failed experiment reproducer and a passing "
            "experiment with the same test_id",
            "when a hypothesis records a ledger position, confirmatory "
            "experiments must come after it",
            "ruled_out requires at least one contradicting evidence",
            "legacy confirmed or ruled_out entries require revalidation",
            "root_cause_confirmed requires no open, unproven, or legacy-unvalidated "
            "hypotheses",
            "stalled rounds reset only on new content or a different source",
            f"after {STALE_ROUNDS} rounds without new content, "
            "mark unproven or change evidence source",
        ],
    }


def summary(ledger: Ledger) -> dict[str, Any]:
    state = load(ledger)
    open_items = [item for item in state["hypotheses"] if item.get("status") == "open"]
    confirmed_items = [
        item for item in state["hypotheses"] if item.get("status") == "confirmed"
    ]
    ruled_out_items = [
        item for item in state["hypotheses"] if item.get("status") == "ruled_out"
    ]
    legacy_unvalidated = [
        item["id"]
        for item in (*confirmed_items, *ruled_out_items)
        if not _is_validated_closed(item)
    ]
    return {
        "goal": state.get("goal", ""),
        "round": state.get("round", 0),
        "revision": state.get("revision", 0),
        "no_new_evidence_rounds": state.get("no_new_evidence_rounds", 0),
        "last_source": state.get("last_source", ""),
        "sources": state.get("sources", []),
        "open": [item["id"] for item in open_items],
        "confirmed": [item["id"] for item in confirmed_items],
        "unproven": [
            item["id"] for item in state["hypotheses"] if item.get("status") == "unproven"
        ],
        "legacy_unvalidated": legacy_unvalidated,
        "next_claim": open_items[0]["claim"] if open_items else "",
    }


def parse_evidence_arg(value: str) -> list[str]:
    return split_ids(value)
