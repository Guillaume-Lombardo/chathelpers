from pathlib import Path

import pytest

from flatten_repo import cli


@pytest.mark.unit
def test_apply_filters_respects_includes_excludes(tmp_path: Path) -> None:
    repo = tmp_path
    keep = repo / "src" / "main.py"
    drop = repo / "src" / "data.bin"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("print('ok')", encoding="utf-8")
    drop.write_text("\x00\x01", encoding="utf-8")

    files = [keep, drop]
    selected = cli.apply_filters(
        files=files,
        repo=repo,
        includes=["src/*.py"],
        excludes=["**/*.bin"],
        exclude_paths=[],
    )

    assert selected == [keep]
