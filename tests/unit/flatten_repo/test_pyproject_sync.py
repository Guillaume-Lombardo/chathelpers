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
