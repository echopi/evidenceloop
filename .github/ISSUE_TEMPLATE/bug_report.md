---
name: Bug report
about: Report a reproducible defect in the CLI, parsers, or state files
title: ""
labels: bug
assignees: ""
---

## What happened

## What you expected

## Reproduction

Minimal command, spec, or Python snippet. Use synthetic input only.

```bash
eloop --version
python3 --version
```

## Environment

- OS:
- Python version:
- eloop version:
- Install method (pipx, pip, source checkout):

## State and errors

`eloop` prints errors as JSON, for example `{"error": "..."}`. Paste the output
and, if relevant, the affected records with local paths removed.

## Data safety checklist

- [ ] I removed credentials, tokens, personal data, and device identifiers.
- [ ] The reproduction uses synthetic logs or fixtures.
- [ ] I did not attach production crash dumps, real test logs, or ledger files.
