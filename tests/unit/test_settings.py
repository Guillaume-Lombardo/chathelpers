from pathlib import Path

from flatten_repo.settings import Settings


def test_settings_defaults() -> None:
    settings = Settings(output=Path("out.md"))

    assert settings.repo.resolve() == Path.cwd().resolve()
    assert settings.output == Path("out.md")
    assert not settings.format
    assert settings.no_git is False
