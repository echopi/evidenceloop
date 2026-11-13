# Contributing

## Development setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

```bash
ruff check .
pytest
```

Both must pass before a pull request is ready.

## Design constraints

- Standard library only at runtime.
- Raw artifacts stay on disk; summaries are bounded and never contain full
  logs.
- Evidence records are append-only. Do not rewrite history to make a
  hypothesis pass.
- The investigation state machine must reject premature `confirmed` status.
- Parsers must tolerate malformed input and return partial results instead of
  raising.

## Tests

Use synthetic fixtures. Do not commit real crash logs, internal paths, or
customer data. Add a fixture and a parser test for every supported format.
