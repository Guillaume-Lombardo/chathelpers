---
name: flatten-repo-quality
description: Maintain quality gates for flatten-repo using pre-commit, Ruff, detect-secrets, ty, coverage checks, and package release validation.
---

# Flatten Repo Quality

## Scope

Use this skill for static analysis, formatting, type checks, secret scanning, commit-time gates, and distribution artifact validation before release.

## Rules

1. Keep `.pre-commit-config.yaml` authoritative for local checks.
2. Use Ruff for lint + formatting (`ruff`, `ruff-format` hooks).
3. Use `ty` for type checking (`src/` and `tests/`).
4. Keep `detect-secrets` baseline up to date in `.secrets.baseline`.
5. Keep strict pytest and coverage options in `pyproject.toml`.
6. For release readiness, ensure `build` + `twine` are available in dev dependencies.
7. Validate package artifacts with `python -m build` and `python -m twine check dist/*`.
8. Keep release instructions aligned between `README.md` and `RELEASING.md`.

## Validation

Run:
- `uv run pre-commit run --all-files`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run ty check src/ tests/`
- `uv run pytest`
- `uv run --with build python -m build`
- `uv run --with twine python -m twine check dist/*`
