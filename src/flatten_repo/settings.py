from __future__ import annotations

from pathlib import Path

from dotenv import find_dotenv
from pydantic import BaseModel, ConfigDict, Field

ENV_FILE = find_dotenv(usecwd=True)


class Settings(BaseModel):
    """Configuration settings for the flatten_repo module."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo: Path = Field(default_factory=Path.cwd, description="Repository root.")
    output: Path = Field(..., description="Output file (.md or .jsonl).")
    format: str = Field(default="", description="Force format.")
    no_git: bool = Field(default=False, description="Do not use git ls-files.")
    log_file: str = Field(default="", description="Log file path.")

    all: bool = Field(default=False, description="Export all files (after filters).")
    src_only: bool = Field(default=False, description="Export src/ + key files.")
    tests_only: bool = Field(default=False, description="Export tests/ only.")

    include_tests: bool = Field(
        default=False,
        description="When src-only, include tests/.",
    )
    tests_first: bool = Field(
        default=False,
        description="Order tests before src in md.",
    )
    no_key_first: bool = Field(
        default=False,
        description="Do not prioritize key files.",
    )

    include_glob: list[str] = Field(default_factory=list, description="Include glob.")
    exclude_glob: list[str] = Field(default_factory=list, description="Exclude glob.")
    exclude_path: list[str] = Field(
        default_factory=list,
        description="Exclude path prefix.",
    )
    drop: str = Field(default="", description="Comma list: api,front,data,docs,tests.")

    max_bytes: int = Field(
        default=500_000,
        description="Text files above are truncated/stubbed.",
    )
    text_head_lines: int = Field(
        default=200,
        description="Head lines for big text files.",
    )
    text_tail_lines: int = Field(
        default=80,
        description="Tail lines for big text files.",
    )
    md_max_lines: int = Field(
        default=250,
        description="Max lines for markdown/readme files.",
    )
    pem: str = Field(default="stub", description="PEM handling.")
    compact: bool = Field(default=False, description="Reduce markdown verbosity.")
    chunk_chars: int = Field(default=24_000, description="Chunk size for jsonl.")
    include_binary_meta: bool = Field(
        default=False,
        description="Include binary stubs in jsonl.",
    )
    no_sha: bool = Field(default=False, description="Do not compute sha256 digests.")
