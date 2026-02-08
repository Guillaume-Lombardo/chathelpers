---
name: flatten-repo-architecture
description: Design and maintain the flatten-repo package architecture (src layout, module boundaries, CLI composition, settings and logging integration).
---

# Flatten Repo Architecture

## Scope

Use this skill when changing package structure or responsibilities between modules.

## Rules

1. Keep production code under `src/flatten_repo/`.
2. Keep modules cohesive:
   - `cli.py`: argument parsing and orchestration only.
   - `settings.py`: runtime configuration model.
   - `logging.py`: logging setup only.
   - `config.py`: enums, constants, shared models.
   - `file_manipulation.py`: filesystem/git/content processing.
   - `output_construction.py`: markdown/jsonl rendering and chunking.
3. Avoid importing heavy runtime logic in `__init__.py`.
4. Keep CLI entry point at `flatten_repo.cli:main`.
5. Preserve `src/` packaging and wheel/sdist config in `pyproject.toml`.

## Validation

Run:
- `uv run pytest -m unit`
- `uv run python -m flatten_repo.cli --help`
