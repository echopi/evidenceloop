# Releasing

PyPI is the primary distribution channel. The command is installed with
`pipx install evidenceloop` or `uv tool install evidenceloop`.

## One-time setup

1. Replace `<owner>` in the `[project.urls]` table of `pyproject.toml` with the
   real repository owner.
2. Create the `pypi` environment in GitHub repository settings.
3. Configure a PyPI trusted publisher for this repository:
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
   pytest
   python -m build
   twine check dist/*
   ```

4. Commit the changes, then tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

5. The `release` workflow builds and publishes to PyPI. Verify the new version
   with `pipx install evidenceloop==X.Y.Z`.
