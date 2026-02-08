from pathlib import Path

import pytest

from flatten_repo import cli
from flatten_repo.settings import Settings


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


@pytest.mark.unit
def test_select_scope_default_keeps_src_and_key_files(tmp_path: Path) -> None:
    src_file = tmp_path / "src" / "main.py"
    key_file = tmp_path / "pyproject.toml"
    test_file = tmp_path / "tests" / "test_main.py"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('ok')", encoding="utf-8")
    key_file.write_text("[project]\nname='x'\n", encoding="utf-8")
    test_file.write_text("def test_ok():\n    pass\n", encoding="utf-8")

    settings = Settings(output=Path("out.md"))
    files = [src_file, key_file, test_file]

    selected = cli.select_scope(files, tmp_path, settings)

    assert selected == [key_file, src_file]


@pytest.mark.unit
def test_select_scope_src_only_excludes_key_files(tmp_path: Path) -> None:
    src_file = tmp_path / "src" / "main.py"
    key_file = tmp_path / "pyproject.toml"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("print('ok')", encoding="utf-8")
    key_file.write_text("[project]\nname='x'\n", encoding="utf-8")

    settings = Settings(output=Path("out.md"), src_only=True)
    files = [src_file, key_file]

    selected = cli.select_scope(files, tmp_path, settings)

    assert selected == [src_file]
