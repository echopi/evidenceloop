# Releasing

PyPI is the primary distribution channel. The command is installed with
`pipx install evidenceloop` or `uv tool install evidenceloop`.

## One-time setup

1. The `[project.urls]` table in `pyproject.toml` points at
   `https://github.com/echopi/evidenceloop`. If the repository moves, update
   all four URLs (Homepage, Repository, Issues, Changelog).
2. The GitHub repository exists as private. After the open-source approval,
   switch it to public and push `main` and the release tags.
3. Create the `pypi` environment in GitHub repository settings.
4. Configure a PyPI trusted publisher for `echopi/evidenceloop`:
   - workflow: `release.yml`
   - environment: `pypi`

No API token is stored in the repository; the workflow uses OIDC.

## Release steps

1. Bump the version in `pyproject.toml` and
   `src/evidenceloop/__init__.py`.
2. Update `CHANGELOG.md`.
3. Run the checks:

   ```bash
   pip install -e ".[dev,release]"
   ruff check .
   pytest --cov=evidenceloop --cov-report=term-missing
   python -m build
   twine check dist/*
   ```

4. Install the built wheel in a clean environment and smoke-test it:

   ```bash
   python -m venv /tmp/eloop-smoke
   /tmp/eloop-smoke/bin/pip install dist/evidenceloop-X.Y.Z-py3-none-any.whl
   /tmp/eloop-smoke/bin/eloop --version
   /tmp/eloop-smoke/bin/eloop --home /tmp/eloop-release-smoke status
   ```

5. Commit the changes, then tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

6. The `release` workflow builds and publishes to PyPI. Verify the new version
   with `pipx install evidenceloop==X.Y.Z`.
