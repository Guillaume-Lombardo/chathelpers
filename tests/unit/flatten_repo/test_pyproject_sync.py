from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from flatten_repo import pyproject_sync

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_to_minimum_pin_converts_exact_pin_and_keeps_marker() -> None:
    assert pyproject_sync.to_minimum_pin("requests==2.32.0") == "requests>=2.32.0"
    assert (
        pyproject_sync.to_minimum_pin('uvicorn==0.30.0 ; python_version >= "3.12"')
        == 'uvicorn>=0.30.0 ; python_version >= "3.12"'
    )


@pytest.mark.unit
def test_main_dry_run_compact_and_minimum_pin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndynamic = ["dependencies"]\n\n'
        '[tool.setuptools.dynamic]\ndependencies = { file = ["requirements.txt"] }\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text(
        "pytest==8.4.1\n",
        encoding="utf-8",
    )

    exit_code = pyproject_sync.main(
        [
            "--pyproject",
            str(pyproject),
            "--no-compile-in",
            "--pin-strategy",
            "minimum",
            "--compact-toml",
            "--dry-run",
        ],
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert 'dependencies = ["requests>=2.32.0"]' in out
    assert 'dev = ["pytest>=8.4.1"]' in out
    assert "dynamic" not in out
    assert "[tool.setuptools.dynamic]" not in out


@pytest.mark.unit
def test_main_writes_pyproject_without_changing_pins_by_default(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pydantic==2.11.7\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("ruff==0.12.1\n", encoding="utf-8")

    exit_code = pyproject_sync.main(
        [
            "--pyproject",
            str(pyproject),
            "--no-compile-in",
        ],
    )

    assert exit_code == 0
    rendered = pyproject.read_text(encoding="utf-8")
    assert "pydantic==2.11.7" in rendered
    assert "ruff==0.12.1" in rendered


@pytest.mark.unit
def test_main_warns_for_group_outside_whitelist(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pydantic==2.11.7\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("ruff==0.12.1\n", encoding="utf-8")
    (tmp_path / "requirements-ops.txt").write_text("httpx==0.28.1\n", encoding="utf-8")

    exit_code = pyproject_sync.main(
        [
            "--pyproject",
            str(pyproject),
            "--group",
            "ops=requirements-ops.in",
            "--no-compile-in",
            "--dry-run",
        ],
    )

    assert exit_code == 0
    err = capsys.readouterr().err
    assert "Unknown dependency groups outside whitelist" in err
    assert "ops" in err


@pytest.mark.unit
def test_main_fails_for_group_outside_whitelist_in_strict_mode(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pydantic==2.11.7\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("ruff==0.12.1\n", encoding="utf-8")
    (tmp_path / "requirements-ops.txt").write_text("httpx==0.28.1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown dependency groups outside whitelist"):
        pyproject_sync.main(
            [
                "--pyproject",
                str(pyproject),
                "--group",
                "ops=requirements-ops.in",
                "--strict-group-whitelist",
                "--no-compile-in",
            ],
        )


@pytest.mark.unit
def test_main_fail_on_unpinned_raises(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("ruff==0.12.1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unpinned dependencies found"):
        pyproject_sync.main(
            [
                "--pyproject",
                str(pyproject),
                "--no-compile-in",
                "--fail-on-unpinned",
            ],
        )


@pytest.mark.unit
def test_main_validate_pep508_raises_on_invalid_requirement(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("not a valid req @@@\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("ruff==0.12.1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid PEP 508 requirement"):
        pyproject_sync.main(
            [
                "--pyproject",
                str(pyproject),
                "--no-compile-in",
                "--validate-pep508",
            ],
        )


@pytest.mark.unit
def test_main_backup_writes_bak_before_update(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    original = '[project]\nname = "demo"\nversion = "0.1.0"\n'
    pyproject.write_text(original, encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pydantic==2.11.7\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("ruff==0.12.1\n", encoding="utf-8")

    exit_code = pyproject_sync.main(
        [
            "--pyproject",
            str(pyproject),
            "--no-compile-in",
            "--backup",
        ],
    )

    assert exit_code == 0
    backup = tmp_path / "pyproject.toml.bak"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original


@pytest.mark.unit
def test_main_reconstructs_missing_requirements_from_pyproject(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["requests==2.32.0"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pytest==8.4.1"]\n',
        encoding="utf-8",
    )

    exit_code = pyproject_sync.main(
        [
            "--pyproject",
            str(pyproject),
            "--no-compile-in",
        ],
    )

    assert exit_code == 0
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == "requests==2.32.0\n"
    assert (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8") == "pytest==8.4.1\n"
    err = capsys.readouterr().err
    assert "Reconstructed missing requirements files from pyproject.toml" in err


@pytest.mark.unit
def test_main_no_reconstruct_fails_when_requirements_missing(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["requests==2.32.0"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pytest==8.4.1"]\n',
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        pyproject_sync.main(
            [
                "--pyproject",
                str(pyproject),
                "--no-compile-in",
                "--no-reconstruct",
            ],
        )


@pytest.mark.unit
def test_main_missing_in_files_skips_compile_and_reconstructs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["requests==2.32.0"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pytest==8.4.1"]\n',
        encoding="utf-8",
    )

    exit_code = pyproject_sync.main(
        [
            "--pyproject",
            str(pyproject),
            "--dry-run",
        ],
    )

    assert exit_code == 0
    err = capsys.readouterr().err
    assert "Skipping compile phase because .in files are missing" in err
    assert "requirements.in" in err
    assert "Reconstructed missing requirements files from pyproject.toml" in err


@pytest.mark.unit
def test_main_handles_out_of_order_project_table_proxy(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n\n'
        "[dependency-groups]\n"
        'dev = ["pytest==8.4.1"]\n\n'
        "[project.optional-dependencies]\n"
        'docs = ["mkdocs==1.6.1"]\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text("pydantic==2.11.7\n", encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text("pytest==8.4.1\n", encoding="utf-8")

    exit_code = pyproject_sync.main(
        [
            "--pyproject",
            str(pyproject),
            "--no-compile-in",
        ],
    )

    assert exit_code == 0
