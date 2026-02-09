---
name: flatten-repo-testing
description: Manage test architecture and execution strategy for unit, integration, and end-to-end tests in flatten-repo.
---

# Flatten Repo Testing

## Scope

Use this skill for pytest organization, markers, defaults, and test quality.

## Rules

1. Test layout:
   - `tests/unit/flatten_repo/` for unit tests.
   - `tests/integration/` for integration tests.
   - `tests/end2end/` for end-to-end tests.
2. Marker strategy:
   - Unit: `unit`
   - Integration: `integration`
   - End-to-end: `end2end`
3. Auto-tag tests from directory with `tests/conftest.py` collection hooks.
4. Default run must execute only unit tests via pytest addopts (`-m unit`).
5. Keep tests deterministic and filesystem-local (no network).
6. Prefer function-based tests over class/object-based tests.
7. Keep imports at the top of test files, never inside test functions.
8. For mocking, use `pytest_mock.MockerFixture` and the `mocker` fixture instead of `unittest.mock`.
9. For CLI changes, include tests for both behavior and UX flags (`--help`, `--version` when relevant).

## Validation

Run:
- `uv run pytest`
- `uv run pytest -m integration`
- `uv run pytest -m end2end`
