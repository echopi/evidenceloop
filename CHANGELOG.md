# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog and the project uses semantic versioning.

## [0.1.0] - 2026-11-13

### Added

- `ingest` for Android tombstone logs, gtest output, and generic text.
- `view` for bounded evidence sections.
- `run` for spec-driven build/test experiments with parsed gtest results.
- Evidence ledger with SHA-256, stable IDs, and append-only JSONL storage.
- Hypothesis tracking with expectations, evidence links, rounds, and closure
  rules.
- `next` for stop-check output.
- `migrate` from the legacy `crashlab` home.

### Fixed

- `next` no longer reports a global root cause while unproven hypotheses
  remain; it returns `root_cause_not_closed` instead.
