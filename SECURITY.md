# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |
| < 0.1   | No        |

Fixes are made on the current release line. Pre-release builds are supported on
a best-effort basis.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately
through the repository's **Security** tab using **Report a vulnerability**
(GitHub private security advisories). If that channel is unavailable, contact a
maintainer through a private contact method listed on their repository profile.

Include as much of the following as you can:

- The affected version (`eloop --version`), Python version, and operating system.
- A minimal reproduction that uses synthetic data.
- The impact you believe the issue has, and any mitigations you found.
- Whether the issue is already public anywhere.

You can expect an initial acknowledgement within 7 days and a status update
within 30 days. Please allow time for a fix and a release before public
disclosure.

## Evidence safety

EvidenceLoop is local-first. It does not upload artifacts, call remote services,
or copy raw logs into summaries. Raw files stay where they are; the ledger
stores source paths, SHA-256 digests, and bounded summaries.

That also means the state directory is sensitive:

- Do not ingest credentials, tokens, private keys, or real user data.
- Redact personal data, hostnames, account identifiers, and device serials
  before ingesting a file.
- Treat `ledger.jsonl`, `investigation.json`, `logs/`, and `meta.json` as
  sensitive local state, and keep backups of them protected.
- Use synthetic fixtures in bug reports, issues, and pull requests. Never attach
  a production crash dump or a real test log.

Evidence records are append-only by design. If a secret reaches a ledger, a log,
or an investigation note, rotate the secret first, then delete the affected home
directory. If the secret was committed to a Git repository, remove it from the
history as well as the working tree.
