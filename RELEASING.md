# Releasing `flatten-repo`

## Prerequisites

- Python virtualenv ready (`.venv`)
- `build` and `twine` installed (`pip install -e ".[dev]"`)
- PyPI project created once: <https://pypi.org/project/flatten-repo/>

## 1. Prepare release

1. Update version in:
   - `pyproject.toml` (`[project].version`)
   - `src/flatten_repo/__init__.py` (`__version__`)
2. Run checks:
   - `./.venv/bin/ruff check .`
   - `./.venv/bin/ruff format --check .`
   - `./.venv/bin/ty check src/ tests/`
   - `./.venv/bin/pytest`

## 2. Build package

```bash
rm -rf dist/
./.venv/bin/python -m build
./.venv/bin/python -m twine check dist/*
```

Expected artifacts:

- `dist/flatten_repo-<version>-py3-none-any.whl`
- `dist/flatten_repo-<version>.tar.gz`

## 3. Publish

### Option A: API token upload (manual)

1. Create a token in PyPI account settings.
2. Export it:
   - `export TWINE_USERNAME=__token__`
   - `export TWINE_PASSWORD=<pypi-token>`
3. Upload:
   - `./.venv/bin/python -m twine upload dist/*`

### Option B: Trusted Publishing (recommended)

1. Configure a PyPI trusted publisher for this GitHub repository.
2. Add a publish workflow triggered on tags (for example `v*`).
3. Create and push tag:
   - `git tag v<version>`
   - `git push origin v<version>`

## 4. Verify release

1. Install from PyPI in a clean env:
   - `python -m pip install flatten-repo==<version>`
2. Smoke test:
   - `flatten-repo --help`
   - `flatten-repo --version`
