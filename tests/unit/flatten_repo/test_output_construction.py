from __future__ import annotations

from pathlib import Path

import pytest

from flatten_repo.config import FileRecord
from flatten_repo.output_construction import build_markdown, chunk_content
from flatten_repo.settings import Settings


@pytest.mark.unit
def test_chunk_content_handles_empty_text() -> None:
    chunks = list(chunk_content("", chunk_chars=10))

    assert chunks == [(0, 0, "")]


@pytest.mark.unit
def test_chunk_content_splits_on_lines() -> None:
    text = "a\nbb\nccc\n"

    chunks = list(chunk_content(text, chunk_chars=4))

    assert chunks == [
        (1, 1, "a\n"),
        (2, 2, "bb\n"),
        (3, 3, "ccc\n"),
    ]


@pytest.mark.unit
def test_build_markdown_renders_headers_and_fences(tmp_path: Path) -> None:
    py_file = tmp_path / "src" / "app.py"
    py_file.parent.mkdir(parents=True, exist_ok=True)
    py_file.write_text("print('ok')\n", encoding="utf-8")

    rec = FileRecord(
        path=py_file,
        rel="src/app.py",
        size=py_file.stat().st_size,
        mtime=py_file.stat().st_mtime,
        sha256="deadbeef",
        max_file_size=1_000,
    )
    settings = Settings(output=Path("out.md"))

    output = build_markdown(tmp_path, [rec], settings=settings)

    assert "# Project Export for LLM" in output
    assert "files=1" in output
    assert "## src/app.py size=" in output
    assert "sha256=deadbeef" in output
    assert "```python" in output


@pytest.mark.unit
def test_build_markdown_compact_mode_removes_extra_spacing(tmp_path: Path) -> None:
    py_file = tmp_path / "src" / "app.py"
    util_file = tmp_path / "src" / "util.py"
    py_file.parent.mkdir(parents=True, exist_ok=True)
    py_file.write_text("print('compact')", encoding="utf-8")
    util_file.write_text("print('util')", encoding="utf-8")

    rec = FileRecord(
        path=py_file,
        rel="src/app.py",
        size=py_file.stat().st_size,
        mtime=py_file.stat().st_mtime,
        max_file_size=1_000,
    )
    rec_two = FileRecord(
        path=util_file,
        rel="src/util.py",
        size=util_file.stat().st_size,
        mtime=util_file.stat().st_mtime,
        max_file_size=1_000,
    )
    compact_output = build_markdown(
        tmp_path,
        [rec, rec_two],
        settings=Settings(output=Path("out.md"), compact=True),
    )
    standard_output = build_markdown(
        tmp_path,
        [rec, rec_two],
        settings=Settings(output=Path("out.md"), compact=False),
    )

    assert "print('compact')\n```\n## src/util.py size=" in compact_output
    assert "print('compact')\n```\n\n## src/util.py size=" in standard_output
