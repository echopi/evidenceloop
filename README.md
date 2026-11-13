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
`ELOOP_HOME`. A home holds one investigation; version 0.1.0 does not support
multiple goals in one home (see
[One investigation per home](#one-investigation-per-home)).

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
eloop next
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
  meta.json           # schema version marker (created on first write)
  ledger.lock         # advisory lock that serializes writes
  logs/               # experiment logs produced by `run`
```

Evidence records keep the source path and SHA-256. Raw artifacts are not
copied; deleting the source invalidates the reference but does not corrupt the
ledger.

### Concurrency and locking

`eloop` can be invoked from several shells at once. Every write takes an
exclusive lock on `<home>/ledger.lock` (POSIX `flock`, Windows
`msvcrt.locking`). The lock covers evidence ID allocation and the append, so
concurrent ingests cannot allocate the same ID. Writes to `investigation.json`
use the same lock end to end (read, modify, write) and replace the file
atomically.

If the lock cannot be acquired within 5 seconds, the command fails with an
`{"error": "timed out ... waiting for lock"}` payload and exit code 1; it never
drops a write silently.

Reads do not take the lock. They consume only newline-terminated records, so a
record that is still being written is ignored rather than parsed as truncated
JSON.

### Schema and compatibility

Each home carries a `meta.json` marker:

```json
{
  "schema_version": 1,
  "created_at": "2026-11-13T12:00:00+08:00",
  "tool_version": "0.1.0"
}
```

- Homes created before schema markers (only `ledger.jsonl` and
  `investigation.json`) are read as schema version 1.
- The marker is created on the first write to a legacy home. Reads never create
  or modify it.
- If `schema_version` is newer than this build supports, `eloop` exits with an
  explicit error and leaves every file untouched. Upgrade `eloop` or point
  `--home` elsewhere; the tool does not downgrade or rewrite newer state.
- `tool_version` records which build created the marker. It is informational and
  does not affect how records are read.

### One investigation per home

Version 0.1.0 intentionally supports one goal per home. A home stores a single
`investigation.json`, and `eloop` never merges goals, hypotheses, or rounds
across homes. To investigate two problems in parallel, give each its own home:

```bash
eloop --home ~/.eloop/crash-a ingest --kind crash_log --path ./a.log
eloop --home ~/.eloop/crash-b ingest --kind crash_log --path ./b.log
```

Multiple goals in one home are out of scope for 0.1.0.

### Migrating an existing home

```bash
eloop migrate --from <old-home>
```

This copies `ledger.jsonl`, `investigation.json`, and `logs/` into the target
home. Existing files are not overwritten unless `--force` is passed.

## Limits

- Summaries are only as good as their parsers; unsupported formats fall back to
  a size/SHA record.
- EvidenceLoop does not symbolize binaries or capture debugger stacks; pass
  those outputs in as `text` or `gtest_log` evidence.
- It does not decide root cause. It enforces the evidence and closure rules.
- Evidence records keep absolute source paths and digests. Do not ingest
  credentials or real user data; see [SECURITY.md](SECURITY.md).

## Community

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md) — report vulnerabilities privately, never in a
  public issue.
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Changelog](CHANGELOG.md)

## License

MIT
