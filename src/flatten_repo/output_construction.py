from __future__ import annotations

import io
from typing import TYPE_CHECKING

from flatten_repo.config import FileRecord
from flatten_repo.file_manipulation import build_tree_lines, file_to_markdown_text, now_iso, order_recs

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from flatten_repo.config import FileRecord
    from flatten_repo.settings import Settings


def build_markdown(
    repo: Path,
    recs: Sequence[FileRecord],
    *,
    settings: Settings,
) -> str:
    """Build a markdown string representing the repository contents.

    The markdown includes a header with repository information, a visual tree of the file structure,
    and sections for each file with content formatted according to heuristics (e.g. redacted .env files,
    summarized pre-commit configs, truncated large files).

    Args:
        repo (Path): the root path of the repository
        recs (Sequence[FileRecord]): the file records to include in the markdown
        settings (Settings): configuration settings for markdown generation, including:
            - text_head_lines: number of head lines to include for large text files
            - text_tail_lines: number of tail lines to include for large text files
            - md_max_lines: maximum lines for markdown files before truncation
            - pem: mode for handling PEM files ('stub' or 'full')
            - tests_first: whether to prioritize test files in the output
            - no_key_first: whether to not prioritize key files in the output
            - compact: whether to use a more compact format for file sections

    Returns:
        str: the generated markdown string representing the repository contents
    """
    out = io.StringIO()
    rp = str(repo)
    out.write("# Project Export for LLM\n")
    out.write(f"root={rp}\n")
    out.write(f"generated_at={now_iso()}\n")
    out.write(f"files={len(recs)}\n\n")

    rels = [r.rel for r in recs]
    tree_lines = build_tree_lines(repo.name, rels)
    out.write("## Structure\n")
    out.write("```text\n")
    out.write("\n".join(tree_lines))
    out.write("\n```\n\n")

    ordered = order_recs(recs, tests_first=settings.tests_first, key_first=not settings.no_key_first)

    for rec in ordered:
        out.write(f"## {rec.rel}\n")
        lang = rec.language or "text"
        body, _is_text = file_to_markdown_text(
            rec,
            text_head_lines=settings.text_head_lines,
            text_tail_lines=settings.text_tail_lines,
            md_max_lines=settings.md_max_lines,
            pem_mode=settings.pem,
            strip_docstrings=settings.strip_docstrings,
        )
        if settings.compact:
            # More compact: no extra blank line between code blocks
            out.write(f"```{lang}\n{body}\n```\n")
        else:
            # Preserve existing behavior with a blank line between blocks
            out.write(f"```{lang}\n{body}\n```\n\n")

    return out.getvalue().rstrip() + "\n"


def chunk_content(text: str, chunk_chars: int) -> Iterator[tuple[int, int, str]]:
    """Chunk a text string into pieces of at most `chunk_chars` characters, splitting on line boundaries.

    Args:
        text (str): the text to chunk
        chunk_chars (int): the maximum number of characters in each chunk

    Yields:
        Iterator[tuple[int, int, str]]: an iterator of tuples containing the start line number,
            end line number, and chunk text for each chunk
    """
    if not text:
        yield (0, 0, "")
        return
    lines = text.splitlines()
    buf: list[str] = []
    cur = 0
    start_line = 1
    for i, ln in enumerate(lines, start=1):
        ln2 = ln + "\n"
        if cur + len(ln2) > chunk_chars and buf:
            yield (start_line, i - 1, "".join(buf))
            buf = []
            cur = 0
            start_line = i
        buf.append(ln2)
        cur += len(ln2)
    if buf:
        yield (start_line, start_line + len(buf) - 1, "".join(buf))
