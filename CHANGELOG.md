# Changelog

All notable changes to this project are documented here.
The format follows Keep a Changelog and the project uses semantic versioning.

## [0.2.0] - 2026-11-16

### Added

- `verify` for read-only re-hashing of evidence sources and experiment logs,
  with `ok`, `missing`, `hash_mismatch`, and `unverifiable` statuses.
- `status --verify` and `next --verify` for explicit integrity summaries.
- Content identity (`content_key`) for novelty checks; duplicate ingests no
  longer reset stalled rounds.
- Evidence source labels on hypotheses and rounds, with `last_source` and
  `sources` returned by `next`.
- Investigation `revision` and `--if-revision` guards for `hyp add` and
  `hyp update`.
- Record and summary schema versions, producer version, parser config, and
  parser coverage metadata.
- Supports/contradicts typed evidence links; `confirmed` records reproducer and
  green links automatically.
- `mechanism` field on hypotheses, defaulting to `claim`.

### Changed

- `confirmed` now requires a failed experiment reproducer and a passing
  experiment with the same stable `test_id`; timeout and start failure are not
  valid reproductions.
- Confirmatory experiments must be appended after the hypothesis. Different
  `test_id` values require `--equivalent-to` and `--equivalence-reason`.
- `ruled_out` requires at least one `--contradicts` evidence.
- Legacy `confirmed` and `ruled_out` records without the new validation are
  reported as `legacy_unvalidated` until revalidated.
- Experiment records now include `summary.test.test_id` and log SHA-256 values.
- Absolute home and run-log paths are recorded for reliable verification.

### Fixed

- Duplicate ingests no longer bypass the stalled-round rule.
- Corrupt `investigation.json` is reported instead of silently reset.
- Evidence and investigation records from newer schema versions are rejected
  on read.

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
