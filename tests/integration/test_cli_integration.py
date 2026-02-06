from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from flatten_repo import cli
from flatten_repo.settings import Settings


@pytest.mark.integration
def test_main_uses_git_ls_files_when_available(
    tmp_path: Path,
    mocker: MockerFixture,
) -> None:
    repo = tmp_path
    file_path = repo / "src" / "app.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("print('hi')", encoding="utf-8")

    mocker.patch.object(cli, "git_ls_files", return_value=[file_path])
    mocker.patch.object(cli, "walk_files", return_value=[])

    output = repo / "out.md"
    settings = Settings(
        repo=repo,
        output=output,
        all=True,
        no_git=False,
    )

    cli.main([
        "--repo",
        str(settings.repo),
        "--output",
        str(settings.output),
        "--all",
    ])

    assert output.exists()
