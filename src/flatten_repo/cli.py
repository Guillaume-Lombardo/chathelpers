"""flatten_repo — Prepare the current project directory for an LLM.

Overview
--------
This utility exports a software project into formats that are convenient for
Large Language Models (LLMs):

1) **Markdown (`--format md`)** — a single readable document containing:
   - a project tree,
   - key configuration files,
   - code and text files with fenced code blocks,
   - light redaction for secrets (e.g., `.env` variable *names only*),
   - summaries for some meta files (pre-commit hooks, license head).

2) **JSONL (`--format jsonl`)** — a stream of chunked file contents, suitable
   for ingestion by RAG pipelines or custom tools.

It prefers `git ls-files` (to honor ignores), and falls back to a filesystem
walk when Git is unavailable or disabled (`--no-git`). You can constrain the
export with include/exclude globs, cap large files with `--max-bytes`, and
tune chunk size via `--chunk-chars`.

Python ≥ 3.13. Minimal dependency: `pyyaml` (for pre-commit parsing).

Usage
-----
Run `flatten-repo --help` for full options. Common examples:
    - Markdown (src + key files):
        flatten-repo --output repo_for_llm.md

    - Full project as JSONL (32k char chunks):
        flatten-repo --all --format jsonl --chunk-chars 32000 --output corpus.jsonl

    - Include tests and extra globs, exclude images:
        flatten-repo --include-tests --include-glob "**/*.cfg" --exclude-glob "**/*.png" --output out.md
    - Log to a file:
        flatten-repo --output out.md --log-file export.log
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING

from flatten_repo import __version__, logger
from flatten_repo.config import (
    DROP_PRESETS,
    KEY_FILES_PRIORITY,
    FileRecord,
)
from flatten_repo.exceptions import GitCommandError
from flatten_repo.file_manipulation import (
    apply_filters,
    file_to_markdown_text,
    git_ls_files,
    make_recs,
    relpath,
    walk_files,
)
from flatten_repo.logging import setup_logging
from flatten_repo.output_construction import build_markdown, chunk_content
from flatten_repo.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    FileProcessorFn = Callable[[Path], str]


def build_jsonl(
    repo: Path,
    recs: Sequence[FileRecord],
    *,
    settings: Settings,
) -> str:
    """Build JSONL content from file records.

    Each file is processed into one or more JSON objects, chunked by character count.
    Binary files can be included as metadata stubs if `include_binary_meta` is True.

    Args:
        repo (Path): The repository root path.
        recs (Sequence[FileRecord]): The file records to process.
        settings (Settings): The settings object containing processing options.
             - text_head_lines: Number of head lines to include for large text files.
             - text_tail_lines: Number of tail lines to include for large text files.
             - md_max_lines: Max lines for markdown/readme files.
             - pem_mode: How to handle PEM files ("stub" or "full").
             - include_binary_meta: Whether to include metadata stubs for binary files.

    Returns:
        str: The generated JSONL content as a string.
    """
    buf = io.StringIO()
    for rec in recs:
        text, is_text = file_to_markdown_text(
            rec,
            text_head_lines=settings.text_head_lines,
            text_tail_lines=settings.text_tail_lines,
            md_max_lines=settings.md_max_lines,
            pem_mode=settings.pem,
            strip_docstrings=settings.strip_docstrings,
        )
        if not is_text and not settings.include_binary_meta:
            continue
        for start, end, chunk in chunk_content(text, chunk_chars=settings.chunk_chars):
            item = {
                "repo_root": str(repo),
                "path": rec.rel,
                "language": rec.language,
                "size": rec.size,
                "mtime": rec.mtime,
                "sha256": rec.sha256,
                "start_line": start,
                "end_line": end,
                "text": chunk,
            }
            buf.write(json.dumps(item, ensure_ascii=False) + "\n")
    return buf.getvalue()


def parse_args(argv: Sequence[str] | None = None) -> Settings:
    """Parse command-line arguments into a Settings object.

    This function defines the command-line interface for the flatten_repo utility,
    including options for repository path, output format, filtering, and processing
    settings.

    Args:
        argv (Sequence[str] | None): Optional list of command-line arguments. If None, uses sys.argv.

    Returns:
        Settings: A Settings object populated with the parsed command-line arguments.
    """
    p = argparse.ArgumentParser(
        description="Export a project for LLM consumption (md/jsonl).",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    p.add_argument("--repo", type=str, default=".", help="Repository root.")
    p.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output file (.md or .jsonl).",
    )
    p.add_argument(
        "--format",
        type=str,
        choices=["md", "jsonl"],
        default="",
        help="Force format.",
    )
    p.add_argument("--no-git", action="store_true", help="Do not use git ls-files.")
    p.add_argument("--log-file", type=str, default="", help="Log file path.")

    scope = p.add_mutually_exclusive_group()
    scope.add_argument(
        "--all",
        action="store_true",
        help="Export all files (after filters).",
    )
    scope.add_argument(
        "--src-only",
        action="store_true",
        help="Export only src/ files (exclude key files).",
    )
    scope.add_argument(
        "--tests-only",
        action="store_true",
        help="Export tests/ only (+ optional key files).",
    )

    p.add_argument(
        "--include-tests",
        action="store_true",
        help="When src-only, include tests/.",
    )
    p.add_argument(
        "--tests-first",
        action="store_true",
        help="Order tests before src in md.",
    )
    p.add_argument(
        "--no-key-first",
        action="store_true",
        help="Do not prioritize key files.",
    )

    p.add_argument(
        "--include-glob",
        action="append",
        default=[],
        help="Include glob (repeatable).",
    )
    p.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="Exclude glob (repeatable).",
    )
    p.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Exclude path prefix (repeatable).",
    )
    drop_options = ", ".join(sorted(DROP_PRESETS))
    p.add_argument(
        "--drop",
        type=str,
        default="",
        help=f"Comma list of drop presets: {drop_options}.",
    )

    p.add_argument(
        "--max-bytes",
        type=int,
        default=500_000,
        help="Text files above are truncated/stubbed.",
    )
    p.add_argument(
        "--text-head-lines",
        type=int,
        default=200,
        help="Head lines for big text files.",
    )
    p.add_argument(
        "--text-tail-lines",
        type=int,
        default=80,
        help="Tail lines for big text files.",
    )
    p.add_argument(
        "--md-max-lines",
        type=int,
        default=250,
        help="Max lines for markdown/readme files.",
    )
    p.add_argument(
        "--pem",
        choices=["stub", "full"],
        default="stub",
        help="PEM handling.",
    )
    p.add_argument("--compact", action="store_true", help="Reduce markdown verbosity.")
    p.add_argument(
        "--chunk-chars",
        type=int,
        default=24_000,
        help="Chunk size for jsonl.",
    )
    p.add_argument(
        "--include-binary-meta",
        action="store_true",
        help="Include binary stubs in jsonl.",
    )
    p.add_argument(
        "--strip-docstrings",
        action="store_true",
        help="Remove Python docstrings from exported content.",
    )
    p.add_argument(
        "--no-sha",
        action="store_true",
        help="Do not compute sha256 digests.",
    )
    args = p.parse_args(argv)
    return Settings(**vars(args))


def select_scope(
    files: Sequence[Path],
    repo: Path,
    settings: Settings,
) -> list[Path]:
    """Select files based on scope settings.

    This function filters the list of files based on the specified scope settings
    (e.g., --all, --src-only, --tests-only) and prioritizes key files if applicable.

    Args:
        files (Sequence[Path]): The list of file paths to filter.
        repo (Path): The repository root path, used for calculating relative paths.
        settings (Settings): The settings object containing scope options.

    Returns:
        list[Path]: The filtered and sorted list of file paths to include in the export.
    """
    rels = [(f, relpath(f, repo)) for f in files]
    key_names = {"pyproject.toml", "requirements.txt", "requirements-dev.txt"} | set(
        KEY_FILES_PRIORITY,
    )

    def is_key(r: str) -> bool:
        return Path(r).name in key_names or r in key_names

    if settings.all:
        return [f for f, _ in rels]

    if settings.tests_only:
        base = [f for f, r in rels if r.startswith("tests/")]
        if not settings.no_key_first:
            base.extend([f for f, r in rels if is_key(r)])
        return sorted(set(base), key=lambda p: relpath(p, repo).lower())

    include_tests = bool(settings.include_tests)
    base: list[Path] = []
    for f, r in rels:
        if r.startswith("src/") or (not settings.src_only and is_key(r)):
            base.append(f)
        if include_tests and r.startswith("tests/"):
            base.append(f)
    return sorted(set(base), key=lambda p: relpath(p, repo).lower())


def handle_no_git_error() -> None:
    """Raise a GitCommandError for missing git.

    This function is used to encapsulate the error handling logic when Git is
    not available or when the --no-git flag is set. It raises a GitCommandError with
    a specific message that can be caught in the main function to trigger the fallback
    to filesystem walking.

    Raises:
        GitCommandError: Always raises to indicate that Git is not available or should not be used.
    """
    raise GitCommandError(command="no git cli run", returncode=1, stdout="", stderr="")


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point for the flatten_repo CLI utility.

    This function orchestrates the export process by parsing command-line arguments,
    gathering files, applying filters, processing file contents, and writing the
    output in the specified format.

    Args:
        argv (Sequence[str] | None): Optional list of command-line arguments. If None, uses sys.argv.

    Returns:
        int: Exit code (0 for success, non-zero for errors).
    """
    settings = parse_args(argv)
    if settings.log_file:
        setup_logging(settings.log_file)

    repo = Path(settings.repo).resolve()

    try:
        if settings.no_git:
            handle_no_git_error()
        files = git_ls_files(repo)
    except Exception as e:
        logger.info("Falling back to filesystem walk: %s", e)
        files = walk_files(repo)

    files = [f for f in files if f.is_file()]
    files = select_scope(files, repo, settings)

    drop = [x.strip().lower() for x in (settings.drop or "").split(",") if x.strip()]
    drop_globs: list[str] = []
    for d in drop:
        drop_globs.extend(DROP_PRESETS.get(d, []))

    selected = apply_filters(
        files=files,
        repo=repo,
        includes=settings.include_glob,
        excludes=list(settings.exclude_glob) + drop_globs,
        exclude_paths=settings.exclude_path,
    )

    recs = make_recs(
        selected,
        repo,
        no_sha=bool(settings.no_sha),
        max_file_size=settings.max_bytes,
    )

    out_path = Path(settings.output)
    fmt = (settings.format or "").strip().lower()
    if not fmt:
        fmt = "jsonl" if out_path.suffix.lower() == ".jsonl" else "md"

    if fmt == "md":
        content = build_markdown(
            repo=repo,
            recs=recs,
            settings=settings,
        )
        out_path.write_text(content, encoding="utf-8")
    else:
        content = build_jsonl(
            repo=repo,
            recs=recs,
            settings=settings,
        )
        out_path.write_text(content, encoding="utf-8")

    logger.info(f"Wrote {out_path} format={fmt} files={len(recs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
