from __future__ import annotations

import shutil
from pathlib import Path

from flatten_repo import cli

RESOURCES_ROOT = Path(__file__).resolve().parents[1] / "resources" / "sync_cli"


def copy_fixture(name: str, destination: Path) -> Path:
    """Copy a test fixture repository into a temporary destination.

    Returns:
        Path: Copied fixture root.
    """
    source = RESOURCES_ROOT / name
    target = destination / name
    shutil.copytree(source, target)
    return target


def test_sync_cli_handles_missing_in_files_and_reconstructs(
    tmp_path: Path,
    capsys,
) -> None:
    repo = copy_fixture("missing_in_reconstruct", tmp_path)
    pyproject = repo / "pyproject.toml"

    exit_code = cli.main(
        [
            "sync-pyproject-deps",
            "--pyproject",
            str(pyproject),
            "--pin-strategy",
            "minimum",
            "--compact-toml",
            "--dry-run",
        ],
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Skipping compile phase because required compile inputs are missing" in captured.err
    assert "Reconstructed missing requirements files from pyproject.toml" in captured.err
    assert 'dependencies = ["pydantic>=2.11.7", "pyyaml>=6.0.2"]' in captured.out
    assert 'dev = ["pytest>=8.4.1"]' in captured.out


def test_sync_cli_ignores_include_directives_in_requirements_txt(
    tmp_path: Path,
    capsys,
) -> None:
    repo = copy_fixture("requirements_include", tmp_path)
    pyproject = repo / "pyproject.toml"

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
    assert "-r requirements.txt" not in out


def test_sync_cli_accepts_out_of_order_project_table(tmp_path: Path) -> None:
    repo = copy_fixture("out_of_order_project_table", tmp_path)
    pyproject = repo / "pyproject.toml"

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
