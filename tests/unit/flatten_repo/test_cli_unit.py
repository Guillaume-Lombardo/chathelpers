from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from flatten_repo import __version__, cli
from flatten_repo.settings import Settings

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.unit
def test_parse_args_parses_scope_and_limits() -> None:
    max_bytes = 1234
    settings = cli.parse_args(
        [
            "--output",
            "out.md",
            "--src-only",
            "--max-bytes",
            str(max_bytes),
            "--drop",
            "tests,docs",
            "--strip-docstrings",
        ],
    )

    assert settings.src_only is True
    assert settings.max_bytes == max_bytes
    assert settings.drop == "tests,docs"
    assert settings.strip_docstrings is True


@pytest.mark.unit
def test_parse_args_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


@pytest.mark.unit
def test_select_scope_tests_only_without_key_files(tmp_path: Path) -> None:
    test_file = tmp_path / "tests" / "test_app.py"
    key_file = tmp_path / "pyproject.toml"
    src_file = tmp_path / "src" / "app.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_ok():\n    pass\n", encoding="utf-8")
    key_file.write_text("[project]\nname='x'\n", encoding="utf-8")
    src_file.write_text("print('ok')\n", encoding="utf-8")

    settings = Settings(output=Path("out.md"), tests_only=True, no_key_first=True)
    selected = cli.select_scope([test_file, key_file, src_file], tmp_path, settings)

    assert selected == [test_file]


@pytest.mark.unit
def test_main_uses_walk_fallback_and_jsonl_suffix(tmp_path: Path, mocker: MockerFixture) -> None:
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('hi')\n", encoding="utf-8")
    output = tmp_path / "out.jsonl"

    mocker.patch.object(cli, "git_ls_files", side_effect=RuntimeError("git failed"))
    mocker.patch.object(cli, "walk_files", return_value=[file_path])

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "--output",
            str(output),
            "--all",
        ],
    )

    assert exit_code == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines
    first = json.loads(lines[0])
    assert first["path"] == "src/app.py"


@pytest.mark.unit
def test_main_no_git_writes_markdown(tmp_path: Path, mocker: MockerFixture) -> None:
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('hello')\n", encoding="utf-8")
    output = tmp_path / "out.md"

    git_mock = mocker.patch.object(cli, "git_ls_files")
    mocker.patch.object(cli, "walk_files", return_value=[file_path])

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "--output",
            str(output),
            "--format",
            "md",
            "--all",
            "--no-git",
        ],
    )

    assert exit_code == 0
    git_mock.assert_not_called()
    content = output.read_text(encoding="utf-8")
    assert "Project Export for LLM" in content
    assert "src/app.py" in content


@pytest.mark.unit
def test_main_strip_docstrings_in_markdown(tmp_path: Path, mocker: MockerFixture) -> None:
    file_path = tmp_path / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        '"""module doc"""\n\ndef run():\n    """function doc"""\n    return "ok"\n',
        encoding="utf-8",
    )
    output = tmp_path / "out.md"

    mocker.patch.object(cli, "walk_files", return_value=[file_path])

    exit_code = cli.main(
        [
            "--repo",
            str(tmp_path),
            "--output",
            str(output),
            "--all",
            "--no-git",
            "--strip-docstrings",
        ],
    )

    assert exit_code == 0
    content = output.read_text(encoding="utf-8")
    assert "module doc" not in content
    assert "function doc" not in content
