---
name: flatten-repo-quality
description: Maintain quality gates for flatten-repo using pre-commit, Ruff, detect-secrets, ty, and coverage checks.
---

# Flatten Repo Quality

## Scope

Use this skill for static analysis, formatting, type checks, secret scanning, and commit-time gates.

## Rules

1. Keep `.pre-commit-config.yaml` authoritative for local checks.
2. Use Ruff for lint + formatting (`ruff`, `ruff-format` hooks).
3. Use `ty` for type checking (`src/` and `tests/`).
4. Keep `detect-secrets` baseline up to date in `.secrets.baseline`.
5. Keep strict pytest and coverage options in `pyproject.toml`.

## Validation

Run:
- `uv run pre-commit run --all-files`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run ty check src/ tests/`
