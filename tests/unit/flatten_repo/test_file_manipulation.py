from pathlib import Path

from flatten_repo.file_manipulation import (
    get_init_content_if_not_empty,
    make_recs,
    normalize_globs,
)


def test_normalize_globs_strips_and_normalizes() -> None:
    globs = ["  src/**/*.py ", "\\tests\\*.py", ""]

    assert normalize_globs(globs) == ["src/**/*.py", "/tests/*.py"]


def test_get_init_content_if_not_empty_handles_empty_file(tmp_path: Path) -> None:
    init_file = tmp_path / "__init__.py"
    init_file.write_text("", encoding="utf-8")

    assert get_init_content_if_not_empty(init_file) == "(empty __init__.py)"


def test_make_recs_applies_max_file_size(tmp_path: Path) -> None:
    max_file_size = 5
    file_path = tmp_path / "src" / "module.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('1234567890')", encoding="utf-8")

    rec = make_recs(
        files=[file_path],
        repo=tmp_path,
        no_sha=True,
        max_file_size=max_file_size,
    )[0]

    assert rec.max_file_size == max_file_size
    assert rec.is_too_big
