# EvidenceLoop

[![PyPI](https://img.shields.io/pypi/v/evidenceloop.svg)](https://pypi.org/project/evidenceloop/)

Local evidence ledger and investigation state machine for crash analysis.

Most crash investigations lose their thread: raw logs are too large and too
sensitive to keep in an agent's context, evidence is scattered across files,
and a conclusion can be repeated in a new session without the evidence that
supported it. EvidenceLoop keeps raw artifacts on disk and exposes bounded,
structured summaries plus stable evidence IDs. Agents reason over the
summaries and the investigation state, not over raw dumps.

## What it does

- **Ingest** crash logs and test output into a JSONL ledger with SHA-256,
  bounded summaries, and evidence IDs.
- **View** one evidence record or a section of it; output is always bounded.
- **Run** an experiment spec (build and test commands) and record exit codes,
  logs, and parsed test results as evidence.
- **Track hypotheses** with an explicit expectation, status, evidence links,
  and rounds.
- **Enforce closure**: a hypothesis can only be `confirmed` with a reproducer
  and a green run. After three rounds without new evidence, `next` asks for
  `unproven` or a different evidence source.

EvidenceLoop is deterministic and has no LLM dependency. It never uploads
artifacts and never copies raw logs into summaries.

## Install

Requires Python 3.9 or newer.

```bash
pipx install evidenceloop
# or
pip install evidenceloop
```

For development:

```bash
git clone <repo-url> && cd evidenceloop
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Quick start

```bash
# 1. Ingest a crash log
eloop ingest --kind crash_log --path ./fixtures/tombstone.log

# 2. Inspect the bounded summary
eloop view --evidence E20260101-0001

# 3. Register a hypothesis before running an experiment
eloop hyp add \
  --claim "the exporter iterates a URL map while another thread erases it" \
  --expect "the concurrent test fails with an invalid iterator; the serial case passes" \
  --evidence E20260101-0001 \
  --spec examples/example_tests.json

# 4. Run the experiment and record the result
eloop run --spec examples/example_tests.json

# 5. Advance
eloop next
eloop status
```

State lives in `~/.eloop` by default. Override with `--home` or
`ELOOP_HOME`.

## Commands

| Command | Purpose |
|---|---|
| `eloop ingest --kind crash_log\|gtest_log\|text --path <file>` | Parse and record evidence |
| `eloop view --evidence <id> [--section <name>]` | Show a bounded evidence view |
| `eloop run --spec <file> [--skip-build]` | Execute a build/test spec and record it |
| `eloop status` | Ledger counts, latest evidence, investigation summary |
| `eloop hyp add --claim ... --expect ... --evidence ...` | Add an open hypothesis |
| `eloop hyp list` | Show the investigation state |
| `eloop hyp update <id> --status ...` | Record a round result |
| `eloop next` | Return the next hypothesis and the stop-check |
| `eloop migrate --from <dir>` | Copy a legacy ledger and logs |

All commands print JSON. Errors are printed as `{"error": "..."}` and return
exit code 1.

## Investigation loop

```
crashlab next
   |  action = run_next_experiment
   v
run the pre-registered spec -> new evidence
   |
   v
hyp update --status open|ruled_out|confirmed|unproven
   |
   +--> next
```

Rules enforced by the tool:

1. A hypothesis requires at least one existing evidence ID and a pre-registered
   expectation.
2. Evidence IDs must exist in the ledger.
3. `confirmed` requires `--reproducer` and `--green`; the green evidence must be
   an experiment with exit code 0.
4. `unproven` requires `--missing` describing the evidence gap.
5. Rounds without new evidence are counted; after three, `next` returns
   `mark_unproven_or_change_evidence_source`.
6. `root_cause_confirmed` requires no open or unproven hypotheses. A confirmed
   hypothesis is a scoped conclusion, not closure of the whole investigation.

## State layout

```
~/.eloop/
  ledger.jsonl        # append-only evidence records
  investigation.json  # hypotheses, rounds, counters
  logs/               # experiment logs produced by `run`
```

Evidence records keep the source path and SHA-256. Raw artifacts are not
copied; deleting the source invalidates the reference but does not corrupt the
ledger.

### Migrating from crashlab

```bash
eloop migrate --from ~/.crashlab
```

This copies `ledger.jsonl`, `investigation.json`, and `logs/` into the target
home. Existing files are not overwritten unless `--force` is passed.

## Limits

- Summaries are only as good as their parsers; unsupported formats fall back to
  a size/SHA record.
- EvidenceLoop does not symbolize binaries or capture debugger stacks; pass
  those outputs in as `text` or `gtest_log` evidence.
- It does not decide root cause. It enforces the evidence and closure rules.

## License

MIT
