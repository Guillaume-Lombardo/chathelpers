from pathlib import Path

import pytest

from flatten_repo.settings import Settings


@pytest.mark.unit
def test_settings_defaults() -> None:
    settings = Settings(output=Path("out.md"))

    assert settings.repo.resolve() == Path.cwd().resolve()
    assert settings.output == Path("out.md")
    assert not settings.format
    assert settings.no_git is False
