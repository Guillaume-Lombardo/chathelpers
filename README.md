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
python -m flatten_repo.cli --help
```

### Common examples

Export source-focused markdown:

```bash
python -m flatten_repo.cli --repo . --output repo_export.md
```

Export full repository to JSONL:

```bash
python -m flatten_repo.cli --repo . --all --format jsonl --output corpus.jsonl
```

Include tests and add custom filters:

```bash
python -m flatten_repo.cli \
  --repo . \
  --output out.md \
  --include-tests \
  --include-glob "src/**/*.py" \
  --exclude-glob "**/*.png"
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

## Repository Analysis (2026-02-08)

### Current strengths

- Clear `src/` package layout aligned with module responsibilities.
- Dedicated test split (`unit`, `integration`, `end2end`) with marker auto-tagging.
- Quality tooling already in place (Ruff, ty, pre-commit, detect-secrets).

### Recommended improvements (priority order)

1. Wire `--max-bytes` to effective truncation logic.
   - `Settings.max_bytes` exists but `FileRecord.max_file_size` is never set.
   - Result: `is_too_big` never triggers, so large-file truncation is effectively inactive.
2. Remove or consolidate dead/duplicate helpers in `file_manipulation.py`.
   - Pairs like `load_git_tracked_files`/`git_ls_files` and `walk_filesystem`/`walk_files` overlap.
   - `file_language`, `is_probably_text`, and `sniff_text_utf8` are currently unused.
3. Fix `__init__.py` empty-file classification.
   - `get_init_content_if_not_empty` returns `"(Unparsable __init__.py)"` when body is empty.
   - Empty parseable files should be treated as empty, not unparsable.
4. Raise coverage expectations.
   - Coverage report currently uses `fail_under = 0` (no gate).
   - Latest local run shows low total coverage; adding targeted tests and a realistic threshold would reduce regressions.
5. Align CLI/documentation semantics.
   - `--src-only` is documented but currently redundant with default behavior.
   - `DROP_PRESETS` includes more keys than documented by `--drop` help text.

## Suggested Roadmap

- Phase 1: fix `--max-bytes` behavior + add tests for truncation.
- Phase 2: clean dead code paths and duplicate utilities.
- Phase 3: improve marker-specific tests and set progressive coverage gates.
- Phase 4: clarify CLI contract and docs (`--src-only`, `--drop` options).

## License

MIT (see `LICENSE`).
