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
- **Verify** referenced sources and experiment logs by re-hashing them.
- **Track hypotheses** with an explicit expectation, status, evidence links,
  sources, and rounds.
- **Enforce closure**: a hypothesis can only be `confirmed` with a failed
  experiment reproducer and a green run that uses the same stable `test_id`.
  After three rounds without new evidence, `next` asks for `unproven` or a
  different evidence source.

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

# 5. Re-hash the evidence sources and run logs
eloop verify

# 6. Advance
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
| `eloop verify [--evidence <id>]` | Re-hash referenced sources and experiment logs |
| `eloop status [--verify]` | Ledger counts, latest evidence, investigation summary |
| `eloop hyp add --claim ... --expect ... --evidence ... [--source <label>]` | Add an open hypothesis |
| `eloop hyp list` | Show the investigation state |
| `eloop hyp update <id> --status ... [--supports <ids>] [--contradicts <ids>] [--source <label>] [--if-revision <n>]` | Record a round result |
| `eloop next [--verify]` | Return the next hypothesis and the stop-check |
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

1. A hypothesis requires at least one existing evidence ID, a claim or explicit
   mechanism, and a pre-registered expectation.
2. Evidence IDs must exist in the ledger.
3. `confirmed` requires `--reproducer` and `--green`.
   - The reproducer must be an experiment whose test actually ran and failed
     (`exit_code != 0`). A timeout or start failure is not a valid reproduction.
   - The green run must be an experiment whose test ran and passed
     (`exit_code == 0`).
   - Both experiments must declare the same stable `test_id` in the spec. If
     they differ, pass `--equivalent-to <reproducer_test_id>` and
     `--equivalence-reason <why they are equivalent>`.
   - Confirmatory experiments must be appended to the ledger after the
     hypothesis was created.
4. `ruled_out` requires at least one `--contradicts` evidence.
5. `unproven` requires `--missing` describing the evidence gap.
6. Rounds without new evidence are counted; after three, `next` returns
   `mark_unproven_or_change_evidence_source`.
7. `root_cause_confirmed` requires no open, unproven, or legacy-unvalidated
   hypotheses. A confirmed hypothesis is a scoped conclusion, not closure of the
   whole investigation. A `confirmed` or `ruled_out` record written by an older
   version without the new closure validation is reported as
   `legacy_unvalidated` and must be revalidated before it can contribute to
   `root_cause_confirmed`.

### Experiment test identity

`run` records `summary.test.test_id` from the spec. Set it explicitly:

```json
{
  "name": "example-tests",
  "test_id": "url-map-concurrency",
  "test": {"argv": ["..."], "timeout_sec": 300}
}
```

The fallback order is `test.id`, `test.test_id`, `spec.test_id`, then
`spec.name`. Closure requires a non-empty `test_id` for both the reproducer and
the green run.

### Evidence integrity

`eloop verify` is read-only and re-hashes each evidence record's `source` and,
for experiments, the recorded build/test logs. Each part is `ok`, `missing`,
`hash_mismatch`, or `unverifiable`. Records without a digest are
`unverifiable`; old experiment records without log hashes are not silently
treated as verified.

`status --verify` and `next --verify` include the same verification block. They
do not re-hash by default, so frequent status queries stay bounded. Relative
paths in legacy records are resolved against the ledger home; missing paths and
records without digests are never reported as `ok`. Experiments run with
`--skip-build` record `build_skipped`; verify does not require a build log for
them.

### Content identity and sources

Each new evidence record carries a `content_key`. Ordinary evidence uses
`(kind, sha256)`. Experiments use the stable `test_id`, test/build argv and
results, and log digests. Re-ingesting the same file creates a new evidence ID
but does not reset the stalled-round counter.

`hyp add --source` and `hyp update --source` record the evidence source for the
round. A stalled investigation (three rounds without new content) only resets
when the round brings new content identity or a different source label. `next`
returns `last_source` (the latest round) and `sources` (the investigation-level
deduplicated history).

### Investigation revisions

Every successful state write increments `revision`. `hyp add` and `hyp update`
accept `--if-revision <n>`; a mismatch fails with `revision mismatch` and
leaves state untouched. This prevents an agent from applying a decision based
on an `next` or `status` payload that another agent has already replaced.

Legacy hypotheses without a recorded ledger position cannot produce a valid
closure. Re-attest one with `eloop hyp update <id> --status open
--rebase-timing`; confirmatory experiments added after that point can then be
used for closure.

### Record metadata and coverage

New evidence records include `producer_version`, `record_schema_version`,
`summary_schema_version`, `parser` (name and config), and `content_key`.
Parser summaries include a `coverage` object with totals, kept counts, and a
`truncated` flag. Crash logs report line/frame/translation counts, gtest logs
report failure-line counts, and text records report byte size. In crash-log
events, `frame_count` includes translated frames while `coverage.frames_total`
counts native frames only. Legacy records keep their original shape and report
unknown metadata rather than fabricated defaults.

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
- Evidence records carry `record_schema_version` and `summary_schema_version`.
  Records written before these fields read as version 1. Future record or
  summary versions are rejected on read.
- `investigation.json` carries `schema_version` and `revision`. Legacy state
  reads as schema version 1 and is upgraded on the first write.

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
- `verify` checks file digests, not whether an experiment actually proves the
  hypothesis. Closure rules decide what can be called confirmed.

## Community

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md) — report vulnerabilities privately, never in a
  public issue.
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Changelog](CHANGELOG.md)

## License

MIT
