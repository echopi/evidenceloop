"""Command-line interface."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from . import investigation
from .errors import EvidenceLoopError
from .ledger import Ledger, migrate_home
from .parsers import parse_gtest, parse_tombstone
from .runner import execute_spec, load_spec
from .util import now_iso, sha256_file, split_ids


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _revision(summary: Dict[str, Any]) -> str:
    metadata = (summary.get("app") or {}).get("metadata") or {}
    for key, value in metadata.items():
        if "revision" in key.lower():
            return value
    return ""


def _one_line(entry: Dict[str, Any]) -> str:
    summary = entry.get("summary") or {}
    if entry.get("kind") == "crash_log":
        signals = " + ".join(
            "%s pid=%s tid=%s%s"
            % (
                event.get("name"),
                event.get("pid"),
                event.get("tid"),
                " subprocess" if event.get("subprocess") else "",
            )
            for event in summary.get("signal_events", [])
        )
        revision = _revision(summary)
        suffix = "; revision=%s" % revision if revision else ""
        return "%s signal event(s): %s%s" % (
            summary.get("signal_count", 0),
            signals,
            suffix,
        )
    if entry.get("kind") == "experiment":
        gtest = summary.get("gtest") or {}
        build = summary.get("build") or {}
        test = summary.get("test") or {}
        return "build=%s test=%s tests=%s passed=%s failed=%s names=%s" % (
            build.get("exit_code"),
            test.get("exit_code"),
            gtest.get("tests_ran"),
            gtest.get("passed"),
            gtest.get("failed"),
            gtest.get("failed_tests"),
        )
    return str(entry.get("kind", "unknown"))


def cmd_ingest(args: argparse.Namespace, ledger: Ledger) -> int:
    path = Path(args.path).expanduser()
    if not path.is_file():
        raise EvidenceLoopError("not a file: %s" % path)

    if args.kind == "crash_log":
        summary = parse_tombstone(path)
    elif args.kind == "gtest_log":
        summary = parse_gtest(path)
    else:
        summary = {"format": "text", "size": path.stat().st_size}

    entry = {
        "evidence_id": ledger.next_id(),
        "kind": args.kind,
        "source": str(path.resolve()),
        "sha256": sha256_file(path),
        "captured_at": now_iso(),
        "producer": "eloop ingest",
        "note": args.note or "",
        "summary": summary,
    }
    ledger.append(entry)
    _print(
        {
            "evidence_id": entry["evidence_id"],
            "kind": entry["kind"],
            "sha256": entry["sha256"],
            "summary": summary,
        }
    )
    return 0


def cmd_view(args: argparse.Namespace, ledger: Ledger) -> int:
    for entry in ledger.entries():
        if entry.get("evidence_id") != args.evidence:
            continue
        if args.section == "all":
            payload: Any = entry
        elif args.section == "summary":
            payload = entry.get("summary", {})
        else:
            payload = (entry.get("summary") or {}).get(args.section)
            if payload is None:
                raise EvidenceLoopError("no section: %s" % args.section)
        _print(
            {
                "evidence_id": entry.get("evidence_id"),
                "kind": entry.get("kind"),
                "source": entry.get("source"),
                "sha256": entry.get("sha256"),
                "captured_at": entry.get("captured_at"),
                "summary": payload,
            }
        )
        return 0
    raise EvidenceLoopError("unknown evidence: %s" % args.evidence)


def cmd_run(args: argparse.Namespace, ledger: Ledger) -> int:
    spec_path = Path(args.spec).expanduser()
    spec = load_spec(spec_path)
    name = spec.get("name") or spec_path.stem
    repo = Path(spec.get("repo", ".")).expanduser().resolve()
    if not repo.is_dir():
        raise EvidenceLoopError("repo not found: %s" % repo)

    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))
    run_dir = ledger.logs / ("%s-%s" % (timestamp, slug))
    summary = execute_spec(spec, repo, run_dir, args.skip_build)

    entry = {
        "evidence_id": ledger.next_id(),
        "kind": "experiment",
        "source": str(spec_path.resolve()),
        "sha256": sha256_file(spec_path),
        "captured_at": now_iso(),
        "producer": "eloop run",
        "note": spec.get("note", ""),
        "summary": summary,
    }
    ledger.append(entry)
    _print({"evidence_id": entry["evidence_id"], "kind": "experiment", "summary": summary})
    return 0


def cmd_status(args: argparse.Namespace, ledger: Ledger) -> int:
    entries = ledger.entries()
    by_kind: Dict[str, int] = {}
    for entry in entries:
        kind = entry.get("kind", "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1

    latest = [
        {
            "evidence_id": entry.get("evidence_id"),
            "kind": entry.get("kind"),
            "at": entry.get("captured_at"),
            "one_line": _one_line(entry),
        }
        for entry in entries[-args.limit :][::-1]
    ]
    last_experiment = next(
        (entry for entry in reversed(entries) if entry.get("kind") == "experiment"), None
    )

    def brief(part: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not part:
            return None
        return {key: value for key, value in part.items() if key != "tail"}

    last_summary = (last_experiment or {}).get("summary") or {}
    _print(
        {
            "home": str(ledger.home),
            "ledger": str(ledger.path),
            "evidence_count": len(entries),
            "by_kind": by_kind,
            "investigation": investigation.summary(ledger),
            "latest": latest,
            "last_experiment": (
                {
                    "evidence_id": last_experiment.get("evidence_id"),
                    "captured_at": last_experiment.get("captured_at"),
                    "build": brief(last_summary.get("build")),
                    "test": brief(last_summary.get("test")),
                    "gtest": last_summary.get("gtest"),
                }
                if last_experiment
                else None
            ),
        }
    )
    return 0


def cmd_hyp_add(args: argparse.Namespace, ledger: Ledger) -> int:
    result = investigation.add_hypothesis(
        ledger,
        claim=args.claim,
        expectation=args.expect,
        evidence=split_ids(args.evidence),
        spec=args.spec or "",
        goal=args.goal or "",
        note=args.note or "",
    )
    _print(result)
    return 0


def cmd_hyp_list(args: argparse.Namespace, ledger: Ledger) -> int:
    _print(investigation.load(ledger))
    return 0


def cmd_hyp_update(args: argparse.Namespace, ledger: Ledger) -> int:
    result = investigation.update_hypothesis(
        ledger,
        hypothesis_id=args.id,
        status=args.status,
        evidence=split_ids(args.evidence),
        note=args.note or "",
        missing=args.missing or "",
        reproducer=args.reproducer or "",
        green=args.green or "",
    )
    _print(result)
    return 0


def cmd_next(args: argparse.Namespace, ledger: Ledger) -> int:
    _print(investigation.next_action(ledger))
    return 0


def cmd_migrate(args: argparse.Namespace, ledger: Ledger) -> int:
    _print(migrate_home(Path(args.source), ledger, force=args.force))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eloop",
        description="Evidence-driven investigation ledger for crash analysis.",
    )
    parser.add_argument("--home", default=None, help="state directory (default: ~/.eloop)")
    parser.add_argument("--version", action="version", version="evidenceloop " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="parse and record evidence")
    ingest.add_argument("--kind", required=True, choices=["crash_log", "gtest_log", "text"])
    ingest.add_argument("--path", required=True)
    ingest.add_argument("--note", default="")
    ingest.set_defaults(func=cmd_ingest)

    view = sub.add_parser("view", help="show a bounded evidence view")
    view.add_argument("--evidence", required=True)
    view.add_argument("--section", default="summary")
    view.set_defaults(func=cmd_view)

    run = sub.add_parser("run", help="execute a build/test spec")
    run.add_argument("--spec", required=True)
    run.add_argument("--skip-build", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="ledger and investigation summary")
    status.add_argument("--limit", type=int, default=5)
    status.set_defaults(func=cmd_status)

    hyp = sub.add_parser("hyp", help="hypothesis state machine")
    hyp_sub = hyp.add_subparsers(dest="hyp_command", required=True)

    hyp_add = hyp_sub.add_parser("add")
    hyp_add.add_argument("--claim", required=True)
    hyp_add.add_argument("--expect", required=True)
    hyp_add.add_argument("--evidence", required=True)
    hyp_add.add_argument("--spec", default="")
    hyp_add.add_argument("--goal", default="")
    hyp_add.add_argument("--note", default="")
    hyp_add.set_defaults(func=cmd_hyp_add)

    hyp_list = hyp_sub.add_parser("list")
    hyp_list.set_defaults(func=cmd_hyp_list)

    hyp_update = hyp_sub.add_parser("update")
    hyp_update.add_argument("id")
    hyp_update.add_argument("--status", required=True, choices=list(investigation.STATUSES))
    hyp_update.add_argument("--evidence", default="")
    hyp_update.add_argument("--note", default="")
    hyp_update.add_argument("--missing", default="")
    hyp_update.add_argument("--reproducer", default="")
    hyp_update.add_argument("--green", default="")
    hyp_update.set_defaults(func=cmd_hyp_update)

    next_cmd = sub.add_parser("next", help="next hypothesis and stop-check")
    next_cmd.set_defaults(func=cmd_next)

    migrate = sub.add_parser("migrate", help="copy a legacy home")
    migrate.add_argument("--from", dest="source", required=True)
    migrate.add_argument("--force", action="store_true")
    migrate.set_defaults(func=cmd_migrate)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ledger = Ledger(args.home)
    try:
        return args.func(args, ledger)
    except EvidenceLoopError as error:
        _print({"error": str(error)})
        return 1
