from pathlib import Path

import pytest

from flatten_repo import cli


def test_end_to_end_markdown_export(tmp_path: Path) -> None:
    repo = tmp_path
    file_path = repo / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("src/app.py", encoding="utf-8")

    output = repo / "export.md"

    exit_code = cli.main(
        [
            "--repo",
            str(repo),
            "--output",
            str(output),
            "--all",
            "--no-git",
        ],
    )

    assert exit_code == 0
    assert output.exists()
    assert "src/app.py" in output.read_text(encoding="utf-8")


def test_end_to_end_sync_pyproject_deps_dry_run_with_requirements_include(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (repo / "requirements.txt").write_text("pydantic==2.11.7\n", encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(
        "-r requirements.txt\npytest==8.4.1\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "sync-pyproject-deps",
            "--pyproject",
            str(pyproject),
            "--no-compile-in",
            "--dry-run",
        ],
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "pydantic==2.11.7" in out
    assert "pytest==8.4.1" in out


def test_end_to_end_sync_pyproject_deps_no_reconstruct_fails(tmp_path: Path) -> None:
    repo = tmp_path
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["requests==2.32.0"]\n',
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        cli.main(
            [
                "sync-pyproject-deps",
                "--pyproject",
                str(pyproject),
                "--no-compile-in",
                "--no-reconstruct",
            ],
        )
