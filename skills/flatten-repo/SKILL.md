---
name: flatten-repo
description: Build, update, or refactor the flatten-repo Python package that exports repositories into LLM-ready Markdown/JSONL. Use when creating package structure (src/ layout), CLI wiring, logging/settings modules, or adding tests for flatten-repo.
---

# Flatten Repo

## Overview

Use this skill to keep the flatten-repo package organized with a src/ layout, structured logging, settings via Pydantic, and pytest coverage.

## Workflow

1. **Package layout**
   - Keep Python sources in `src/flatten_repo/`.
   - Expose the CLI entry point from `flatten_repo.cli:main`.

2. **Configuration**
   - Manage runtime options in `flatten_repo/settings.py` with a Pydantic model.
   - Configure structlog in `flatten_repo/logging.py` and import `setup_logging()` in the CLI.

3. **Testing**
   - Unit tests mirror package structure under `tests/unit/flatten_repo/`.
   - Integration tests live in `tests/integration/`.
   - End-to-end tests live in `tests/end2end/`.
   - Prefer function-based tests; keep imports at the top; use `pytest_mock.MockerFixture` when mocking.
   - Mark tests with `@pytest.mark.unit`, `@pytest.mark.integration`, or `@pytest.mark.end2end` and keep unit tests as the default selection.

4. **Dependencies**
   - Runtime dependencies live in `requirements.txt` and `pyproject.toml`.
   - Development dependencies live in `requirements-dev.txt` and `[tool.uv].dev-dependencies`.

5. **Quality gates**
   - Maintain `.pre-commit-config.yaml`, `ruff.toml`, and `ty` configuration for formatting, linting, and type checks.
