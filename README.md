# Flatten Repo

Export a repository into LLM-friendly Markdown (`.md`) or chunked JSONL (`.jsonl`).

## What It Does

`flatten-repo` scans a project, applies include/exclude filters, and generates:

- `md`: a human-readable project export (tree + per-file blocks)
- `jsonl`: chunked records for ingestion pipelines (RAG, indexing, search)

It prefers `git ls-files` to respect Git tracking, with filesystem fallback when needed.

## Installation

### Runtime deps

```bash
pip install -r requirements.txt
```

### Dev deps

```bash
pip install -r requirements-dev.txt
```

## CLI Usage

```bash
flatten-repo --help
```

### Common examples

Export source-focused markdown:

```bash
flatten-repo --repo . --output repo_export.md
```

Export full repository to JSONL:

```bash
flatten-repo --repo . --all --format jsonl --output corpus.jsonl
```

Include tests and add custom filters:

```bash
flatten-repo \
  --repo . \
  --output out.md \
  --include-tests \
  --include-glob "src/**/*.py" \
  --exclude-glob "**/*.png"
```

Export Python files without docstrings:

```bash
flatten-repo --repo . --output out.md --strip-docstrings
```

## Project Layout

```text
src/flatten_repo/
  cli.py                  # CLI argument parsing and orchestration
  settings.py             # Runtime settings model
  logging.py              # Structlog setup
  config.py               # Shared enums/constants/models
  file_manipulation.py    # Filesystem/git/filter/content processing
  output_construction.py  # Markdown/JSONL rendering and chunking

tests/
  unit/
  integration/
  end2end/
```

## Development & Quality

Run checks from the local virtualenv:

```bash
./.venv/bin/ruff check .
./.venv/bin/ty check src/ tests/
./.venv/bin/pytest
./.venv/bin/pytest -m integration
./.venv/bin/pytest -m end2end
```

Pre-commit hooks are configured in `.pre-commit-config.yaml`.

## Scope & Filtering Notes

- Default scope: `src/` + key files (`pyproject.toml`, requirements, pre-commit config, etc.).
- `--src-only`: strict `src/` scope (excludes key files).
- `--tests-only`: restricts export to `tests/` (+ key files unless `--no-key-first`).
- `--max-bytes`: files larger than this threshold are truncated to head/tail excerpts.
- `--drop`: supports presets `api, ci, data, docker, docs, documentation, front, README, tests`.
- `--strip-docstrings`: removes Python module/class/function docstrings from exported content.

## Markdown Output Notes

- The file tree is rendered under a `## Structure` section.
- File section titles contain only the relative path (no size/SHA by default).

## Quality Gates

- Coverage gate is configured in `pyproject.toml` (`fail_under = 30`).
- Unit tests remain the default pytest selection via marker configuration.

## License

MIT (see `LICENSE`).
