# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog and the project uses semantic versioning.

## [0.1.1] - 2026-11-13

### Changed

- Remove legacy `crashlab` naming from the public README and changelog.
  Documentation only; no runtime changes.

## [0.1.0] - 2026-11-13

### Added

- `ingest` for Android tombstone logs, gtest output, and generic text.
- `view` for bounded evidence sections.
- `run` for spec-driven build/test experiments with parsed gtest results.
- Evidence ledger with SHA-256, stable IDs, and append-only JSONL storage.
- Hypothesis tracking with expectations, evidence links, rounds, and closure
  rules.
- `next` for stop-check output.
- `migrate` from a legacy home.
- Cross-platform write locking (`ledger.lock`) for evidence appends and
  investigation state; evidence IDs are allocated inside the same lock.
- `meta.json` schema marker with legacy-home migration on first write and an
  explicit error for newer, unsupported schema versions.
- Security policy, code of conduct, issue templates, and pull request template.
- README sections for locking, schema compatibility, and the single-goal scope
  of a home.

### Fixed

- `next` no longer reports a global root cause while unproven hypotheses
  remain; it returns `root_cause_not_closed` instead.
- Concurrent writers could allocate duplicate evidence IDs or lose hypothesis
  updates; writes now serialize on the home lock.
- A truncated trailing ledger record is ignored instead of being parsed, and
  the next append starts on a fresh line.
