from __future__ import annotations

from enum import StrEnum, auto
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

if TYPE_CHECKING:
    from collections.abc import Callable

    FileProcessorFn = Callable[[Path], str]

_ = Path()


class FileType(StrEnum):
    """Categorization of file types for processing and export purposes.

    This is a heuristic classification based on file extensions and content,
    used to determine how to handle different files during export.
    """

    TEXT = auto()
    BINARY = auto()
    IMAGE = auto()
    PYTHON = auto()
    TOML = auto()
    JSON = auto()
    MARKDOWN = auto()
    YAML = auto()
    HTML = auto()
    CSS = auto()
    JAVASCRIPT = auto()
    TYPESCRIPT = auto()
    BASH = auto()
    RUST = auto()
    GO = auto()
    PHP = auto()
    SQL = auto()
    JAVA = auto()
    C = auto()
    CPP = auto()
    XML = auto()
    INI = auto()
    PEM = auto()
    OTHER = auto()


EXT2LANG: dict[str, FileType] = {
    ".bash": FileType.BASH,
    ".bmp": FileType.IMAGE,
    ".c": FileType.C,
    ".cc": FileType.CPP,
    ".cfg": FileType.INI,
    ".conf": FileType.INI,
    ".cpp": FileType.CPP,
    ".crt": FileType.PEM,
    ".css": FileType.CSS,
    ".cxx": FileType.CPP,
    ".gif": FileType.IMAGE,
    ".go": FileType.GO,
    ".h": FileType.C,
    ".hpp": FileType.CPP,
    ".htm": FileType.HTML,
    ".html": FileType.HTML,
    ".ini": FileType.INI,
    ".java": FileType.JAVA,
    ".jpeg": FileType.IMAGE,
    ".jpg": FileType.IMAGE,
    ".js": FileType.JAVASCRIPT,
    ".json": FileType.JSON,
    ".key": FileType.PEM,
    ".markdown": FileType.MARKDOWN,
    ".md": FileType.MARKDOWN,
    ".mjs": FileType.JAVASCRIPT,
    ".pem": FileType.PEM,
    ".php": FileType.PHP,
    ".png": FileType.IMAGE,
    ".py": FileType.PYTHON,
    ".rs": FileType.RUST,
    ".sh": FileType.BASH,
    ".sql": FileType.SQL,
    ".svg": FileType.IMAGE,
    ".toml": FileType.TOML,
    ".ts": FileType.TYPESCRIPT,
    ".tsx": FileType.TYPESCRIPT,
    ".txt": FileType.TEXT,
    ".webp": FileType.IMAGE,
    ".xml": FileType.XML,
    ".yaml": FileType.YAML,
    ".yml": FileType.YAML,
    ".zsh": FileType.BASH,
}

_FENCE_LANGUAGE: dict[FileType, str] = {
    FileType.PYTHON: "python",
    FileType.TOML: "toml",
    FileType.JSON: "json",
    FileType.MARKDOWN: "markdown",
    FileType.YAML: "yaml",
    FileType.HTML: "html",
    FileType.CSS: "css",
    FileType.JAVASCRIPT: "javascript",
    FileType.TYPESCRIPT: "typescript",
    FileType.BASH: "bash",
    FileType.RUST: "rust",
    FileType.GO: "go",
    FileType.PHP: "php",
    FileType.SQL: "sql",
    FileType.JAVA: "java",
    FileType.C: "c",
    FileType.CPP: "cpp",
    FileType.XML: "xml",
    FileType.INI: "ini",
    FileType.PEM: "",
    FileType.IMAGE: "",
    FileType.BINARY: "",
    FileType.TEXT: "",
    FileType.OTHER: "",
}

DEFAULT_EXCLUDES = {
    ".git",
    ".venv",
    "venv",
    "env",
    ".env",
    ".env.expanded",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".ipynb_checkpoints",
    "node_modules",
    "dist",
    "build",
    ".DS_Store",
    ".gitlab",
    ".idea",
    ".vscode",
    "data/ca-certificates",
    "README.md",  # often large and redundant with other docs
}

KEY_FILES_PRIORITY = [
    "pyproject.toml",
    "requirements.in",
    "requirements.txt",
    "requirements-dev.in",
    "requirements-dev.txt",
    ".pre-commit-config.yaml",
    ".pre-commit-config.yml",
    "Dockerfile",
    "Makefile",
]

DROP_PRESETS: dict[str, list[str]] = {
    "api": ["src/**/api/**", "src/**/routes/**", "src/**/api_server.py"],
    "front": ["src/**/front/**", "front/**", "ui/**", "web/**"],
    "data": ["data/**", "datasets/**", "notebooks/**", "*.db", "*.sqlite", "*.sqlite3"],
    "docs": ["docs/**", "**/*.pdf"],
    "tests": ["tests/**"],
    "README": ["*README.md", "README.txt", "*README*.md"],
    "ci": [".github/**", ".gitlab-ci.yml", "ci/**"],
    "docker": ["Dockerfile", "dockerfiles/**"],
    "documentation": ["docs/**", "**/*.md", "**/*.rst", "documentation/**"],
}

FILE_PROCESSOR: dict[str, Callable[[Path], str]] = {}


def guess_file_type(path: Path) -> FileType:
    """Heuristic guess of file type based on extension.

    This is a simple mapping and may not be accurate for all files.

    Args:
        path (Path): The file path to guess the type for.

    Returns:
        FileType: The guessed file type, or FileType.OTHER if unknown.
    """
    ext = path.suffix.lower()
    return EXT2LANG.get(ext, FileType.OTHER)


def guess_language(file_type: FileType) -> str:
    """Get the suggested code fence language for a given file type.

    Args:
        file_type (FileType): The categorized file type.

    Returns:
        str: The suggested language name for code fences, or empty string if none.
    """
    return _FENCE_LANGUAGE.get(file_type, "")


def is_textlike_type(file_type: FileType) -> bool:
    """Heuristic check if a file type is "text-like" for export purposes.

    This is used to determine if we should attempt to include file contents
    in the export, or if we should treat it as binary/meta.

    Args:
        file_type (FileType): The categorized file type.

    Returns:
        bool: True if the file type is considered text-like, False otherwise.
    """
    return file_type not in {FileType.IMAGE, FileType.BINARY}


class FileRecord(BaseModel):
    """Lightweight metadata for a file included in the export.

    Attributes:
        path: Absolute path to the file on disk.
        rel: Path relative to the chosen repository root.
        language: Suggested code fence language (may be empty).
        size: File size in bytes.
        mtime: POSIX mtime (float seconds since epoch).
        sha256: SHA-256 hex digest of file contents (may be empty for huge files).
        is_text: Heuristic indicator for "text-like" files.
        too_big: Whether the file is too big to include contents
            (based on config.max_file_size)
        file_type: Categorized file type for processing decisions.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    path: Path = Field(..., description="Absolute file path")
    rel: str = Field(..., description="File path relative to repository root")
    size: int = Field(..., ge=0, description="File size in bytes")
    mtime: float = Field(..., description="POSIX modification time (seconds)")
    sha256: str = Field("", description="SHA-256 hex digest (optional for huge files)")
    max_file_size: int | None = Field(
        default=None,
        description="Maximum file size in bytes for including contents; None means no limit",
    )

    @computed_field
    @property
    def file_type(self) -> FileType:
        """Categorize the file type based on extension and content heuristics."""
        return EXT2LANG.get(self.path.suffix.lower(), FileType.OTHER)

    @computed_field
    @property
    def language(self) -> str:
        """Get the suggested code fence language based on the file type."""
        return _FENCE_LANGUAGE.get(self.file_type, "")

    @computed_field
    @property
    def is_text(self) -> bool:
        """Heuristic check if the file is text-like based on its type."""
        return self.file_type not in {FileType.IMAGE, FileType.BINARY}

    @computed_field
    @property
    def is_too_big(self) -> bool:
        """Determine if the file is too big to include contents based on config."""
        if self.max_file_size is None:
            return False
        return self.size > self.max_file_size


def register_file_processor(
    key: str | list[str],
) -> Callable[[FileProcessorFn], FileProcessorFn]:
    """Decorator to register a file processing function based on file suffix or name.

    This allows for custom processing logic for specific file types or names when
    generating markdown or JSONL content.

    Args:
        key (str | list[str]): The file suffix (e.g. ".pem") or exact filename (e.g. "Dockerfile")
            that the decorated function should be registered to handle. Can be a single string
            or a list of strings for multiple keys.

    Returns:
        Callable[[FileProcessorFn], FileProcessorFn]: A decorator that registers the given function
        in the FILE_PROCESSOR mapping under the specified key(s) and returns the original function.
    """

    def decorator(func: FileProcessorFn) -> FileProcessorFn:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            return func(*args, **kwargs)

        if isinstance(key, list):
            for k in key:
                FILE_PROCESSOR[k] = wrapper
        else:
            FILE_PROCESSOR[key] = wrapper
        return wrapper

    return decorator
