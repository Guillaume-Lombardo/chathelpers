from flatten_repo.file_manipulation import normalize_globs


def test_normalize_globs_strips_and_normalizes() -> None:
    globs = ["  src/**/*.py ", "\\tests\\*.py", ""]

    assert normalize_globs(globs) == ["src/**/*.py", "/tests/*.py"]
