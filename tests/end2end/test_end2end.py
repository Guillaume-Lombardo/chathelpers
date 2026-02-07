from pathlib import Path

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

    print(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output.exists()
    assert "test_end_to_end_markdown" in output.read_text(encoding="utf-8")
