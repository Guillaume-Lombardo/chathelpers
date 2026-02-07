from dataclasses import dataclass
from os import name
from pathlib import Path


@dataclass(frozen=True)
class FlattenRepoError(Exception):
    """Base exception for errors in the flatten_repo module."""


@dataclass(frozen=True)
class GitCommandError(FlattenRepoError):
    """Raised when a git command fails."""

    command: str
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class FileProcessingError(FlattenRepoError):
    """Raised when an error occurs during file processing."""


@dataclass(frozen=True)
class NotAGitRepositoryError(FlattenRepoError):
    """Raised when the specified directory is not a Git repository."""

    folder: Path
    message: str = "The specified directory is not a Git repository."


@dataclass(frozen=True)
class NotAnInitFileError(FlattenRepoError):
    """Raised when a file expected to be an `__init__.py` is not."""

    file: Path
    message: str = "The specified file is not an `__init__.py` file."
