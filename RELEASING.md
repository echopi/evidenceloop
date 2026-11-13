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

## TestPyPI rehearsal

Run a rehearsal on TestPyPI before publishing to the real index so packaging,
metadata, and the install path are proven without burning a version number on
PyPI.

1. Create an account on [test.pypi.org](https://test.pypi.org) and add a
   pending trusted publisher for the `evidenceloop` project:
   - GitHub repo: `echopi/evidenceloop`
   - workflow: `testpypi.yml`
   - environment: `testpypi`
2. Create the `testpypi` environment in GitHub repository settings. Do not add
   any secret; the workflow authenticates with OIDC.
3. Run the `testpypi` workflow manually from the Actions tab
   (`workflow_dispatch`). It builds the distributions and publishes them to
   `https://test.pypi.org/legacy/`. It does not tag or publish to PyPI.
4. Verify the install in a clean environment:

   ```bash
   pipx install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple evidenceloop==0.1.0
   ```

TestPyPI treats uploaded versions as immutable as well. If you need another
rehearsal, bump to a pre-release version (for example `0.1.0rc2`) and update the
install command. The real release still goes through `release.yml` and the PyPI
trusted publisher.

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
