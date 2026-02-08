from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import io
import json
import os
import stat
import subprocess  # noqa: S404
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from flatten_repo.config import (
    DEFAULT_EXCLUDES,
    DROP_PRESETS,
    EXT2LANG,
    KEY_FILES_PRIORITY,
    FileRecord,
    register_file_processor,
)
from flatten_repo.exceptions import NotAGitRepositoryError, NotAnInitFileError
from flatten_repo.logging import logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from flatten_repo.settings import Settings

    FileProcessorFn = Callable[[Path], str]


def relpath(path: Path, root: Path) -> str:
    """Send the relative path of path from root.

    Args:
        path (Path): the path to "relativise"
        root (Path): the root to relativise from

    Returns:
        str: the relative path from root to path, with POSIX separators.
            If path is not under root, returns the original path as a string.
    """
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(path)


def file_language(path: Path) -> str:
    """Heuristically determine a file's language for syntax highlighting.

    - Uses file extension and name patterns.
    - Returns a string like "python", "markdown", or "" for unknown.

    This is used to select syntax highlighting in markdown export, and can be
    extended with custom processors for specific files.

    Args:
        path (Path): the file path to analyze

    Returns:
        str: a language string for syntax highlighting, or "" if unknown
    """
    name = path.name.lower()
    if name == "dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    return EXT2LANG.get(path.suffix.lower(), "")


def is_probably_text(path: Path) -> bool:
    """Check if a file is probably text.

    Heuristically determine whether a file is text by trying to decode
    the first 4 KiB as UTF-8. Returns False on any failure.

    Args:
        path (Path): the file path to check

    Returns:
        bool: True if the file is probably text, False otherwise
    """
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode):
            return False
        with path.open("rb") as f:
            chunk = f.read(4096)
        chunk.decode("utf-8")
    except Exception:
        return False
    else:
        return True


def sha256_file(path: Path) -> str:
    """Compute and return the SHA-256 hex digest of a file.

    Reads the file in 1 MiB chunks to handle large files without excessive memory use.

    Args:
        path (Path): the file path to hash

    Returns:
        str: the SHA-256 hex digest of the file contents
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()


def load_git_tracked_files(repo: Path) -> list[Path]:
    """Use `git ls-files` to retrieve the list of tracked files within `repo`.

    Args:
        repo (Path): the root of the git repository to query

    Raises:
        NotAGitRepositoryError: if `.git` is missing or `git` invocation fails.

    Returns:
        list[Path]: the list of tracked files within the repository
    """
    git_dir = repo / ".git"
    if not git_dir.exists():
        raise NotAGitRepositoryError(folder=repo)
    try:
        out = subprocess.run(
            ["git", "ls-files"],  # noqa: S607
            cwd=str(repo),
            text=True,
            capture_output=True,
            check=True,
        )
        return [repo / line for line in out.stdout.splitlines() if line.strip()]
    except Exception as e:
        logger.warning("git ls-files failed: %s", e)
        raise


def walk_filesystem(repo: Path) -> list[Path]:
    """Collect files by walking the filesystem under `repo`.

    Recursively walk the filesystem under `repo`, pruning common transient
    or tool-specific directories defined in `DEFAULT_EXCLUDES`.

    Args:
        repo (Path): the root directory to walk

    Returns:
        list[Path]: the list of files found under `repo`, excluding pruned directories
    """
    results: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
        for f in files:
            p = Path(root) / f
            if p.is_file():
                results.append(p)
    return results


def apply_glob_filters(
    files: Sequence[Path],
    root: Path,
    includes: Sequence[str] | None,
    excludes: Sequence[str] | None,
) -> list[Path]:
    """Apply include/exclude globbing to a list of files relative to `root`.

    - If `includes` is provided, a file must match at least one include pattern.
    - If `excludes` is provided, a matching file is removed.
    - If neither is provided, `files` is returned as-is.

    Args:
        files (Sequence[Path]): the list of file paths to filter
        root (Path): the root path to relativize file paths against for glob matching
        includes (Sequence[str] | None): glob patterns to include (relative to root)
        excludes (Sequence[str] | None): glob patterns to exclude (relative to root)

    Returns:
        list[Path]: the filtered list of file paths
    """
    if not includes and not excludes:
        return list(files)

    out: list[Path] = []
    for f in files:
        rp = relpath(f, root)
        keep = True
        if includes:
            keep = any(fnmatch.fnmatch(rp, pat) for pat in includes)
        if keep and excludes and any(fnmatch.fnmatch(rp, pat) for pat in excludes):
            keep = False
        if keep:
            out.append(f)
    return out


def is_regular_file(path: Path) -> bool:
    """Check if a file is regular.

    Args:
        path (Path): path to test.

    Returns:
        bool: True if the file is regular, False otherwise.
    """
    try:
        st = path.stat()
        return stat.S_ISREG(st.st_mode)
    except Exception:
        return False


def sniff_text_utf8(path: Path, nbytes: int = 4096) -> bool:
    """Check if path point to a utf-8 encoded text file.

    Args:
        path (Path): path to test.
        nbytes (int, optional): number of bytes to read for testing. Defaults to 4096.

    Returns:
        bool: True if the file is utf-8 encoded text, False otherwise.
    """
    try:
        if not is_regular_file(path):
            return False
        with path.open("rb") as f:
            chunk = f.read(nbytes)
        chunk.decode("utf-8")
    except Exception:
        return False
    else:
        return True


def git_ls_files(repo: Path) -> list[Path]:
    """Get the list of tracked files in a git repository using `git ls-files`.

    Args:
        repo (Path): the root of the git repository to query

    Raises:
        NotAGitRepositoryError: if `.git` is missing or `git` invocation fails.

    Returns:
        list[Path]: the list of tracked files within the repository
    """
    git_dir = repo / ".git"
    if not git_dir.exists():
        raise NotAGitRepositoryError(folder=repo)
    out = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=True,
    )
    files: list[Path] = []
    for line in out.stdout.splitlines():
        line = line.strip()  # noqa: PLW2901
        if not line:
            continue
        files.append((repo / line).resolve())
    return files


def walk_files(repo: Path) -> list[Path]:
    """Walk the directory tree rooted at `repo` and return a list of all files.

    Args:
        repo (Path): the root directory to walk

    Returns:
        list[Path]: a list of all files found
    """
    results: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
        for f in files:
            p = (Path(root) / f).resolve()
            if p.is_file():
                results.append(p)
    return results


def in_default_excludes(repo: Path, path: Path) -> bool:
    """Check if a path is in the default excludes.

    Args:
        repo (Path): the root directory of the repository
        path (Path): the path to check

    Returns:
        bool: True if the path is in the default excludes, False otherwise
    """
    try:
        parts = path.relative_to(repo).parts
    except Exception:
        return True
    return any(p in DEFAULT_EXCLUDES for p in parts)


def get_init_content_if_not_empty(path: Path) -> str:
    """Get the content of an `__init__.py` file if it likely contains code.

    This is a heuristic check to identify `__init__.py` files that are likely
    used just to mark a directory as a Python package, without containing actual code.

    Args:
        path (Path): the file path to check

    Raises:
        NotAnInitFileError: if the file is not named `__init__.py`

    Returns:
        str: the file content if the file is an `__init__.py` with code,
            "(empty __init__.py)" if it is an `__init__.py` without code, or
            "(Unparsable __init__.py)" if it cannot be parsed as Python source
    """
    if path.name != "__init__.py":
        raise NotAnInitFileError(file=path)
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
        body = tree.body
        if not body:
            return "(Unparsable __init__.py)"
        if len(body) == 1 and isinstance(body[0], ast.Expr):
            v = body[0].value
            is_ok = isinstance(v, ast.Constant) and isinstance(v.value, str)

            return "(empty __init__.py)" if is_ok else "(Unparsable __init__.py)"
        return src
    except Exception:
        return "(Unparsable __init__.py)"
    else:
        return "(Unparsable __init__.py)"


def match_any_glob(rel: str, globs: Sequence[str]) -> bool:
    """Check if a relative path matches any of the provided glob patterns.

    Args:
        rel (str): the relative path to check
        globs (Sequence[str]): the glob patterns to match against

    Returns:
        bool: True if `rel` matches any pattern in `globs`, False otherwise
    """
    return any(fnmatch.fnmatch(rel, g) for g in globs)


def normalize_globs(globs: Sequence[str]) -> list[str]:
    """Normalize a sequence of path glob patterns.

    Normalize a sequence of glob patterns by stripping whitespace and
    replacing backslashes with forward slashes.

    Args:
        globs (Sequence[str]): the glob patterns to normalize

    Returns:
        list[str]: the normalized glob patterns
    """
    out: list[str] = []
    for g in globs:
        g2 = (g or "").strip()
        if not g2:
            continue
        out.append(g2.replace("\\", "/"))
    return out


def apply_filters(
    files: Sequence[Path],
    repo: Path,
    includes: Sequence[str],
    excludes: Sequence[str],
    exclude_paths: Sequence[str],
) -> list[Path]:
    """Apply include/exclude filters to a list of files.

    Args:
        files (Sequence[Path]): the list of file paths to
            filter (absolute paths)
        repo (Path): the root path to relativize file paths against for filtering
        includes (Sequence[str]): glob patterns to include (relative to repo)
        excludes (Sequence[str]): glob patterns to exclude (relative to repo)
        exclude_paths (Sequence[str]): specific relative paths to exclude (relative to repo)

    Returns:
        list[Path]: the filtered list of file paths
    """
    inc = normalize_globs(includes)
    exc = normalize_globs(excludes)
    exc_paths = [p.strip().strip("/").replace("\\", "/") for p in exclude_paths if p.strip()]

    out: list[Path] = []
    for f in files:
        if not is_regular_file(f):
            continue
        if in_default_excludes(repo, f):
            continue
        r = relpath(f, repo)
        if any(r == ep or r.startswith(ep + "/") for ep in exc_paths):
            continue
        if inc and not match_any_glob(r, inc):
            continue
        if exc and match_any_glob(r, exc):
            continue
        out.append(f)
    return sorted(set(out), key=lambda p: relpath(p, repo).lower())


def build_tree_lines(root_name: str, rel_paths: Sequence[str]) -> list[str]:
    """Build a visual tree representation of file paths.

    Args:
        root_name (str): the name to use for the root of the tree
        rel_paths (Sequence[str]): the list of file paths relative to the root, using POSIX separators (e.g. "src/main.py")

    Returns:
        list[str]: a list of strings representing the tree structure, suitable for printing
    """
    rels = sorted(
        {p.strip("/").replace("\\", "/") for p in rel_paths if p.strip()},
        key=str.lower,
    )
    tree: dict[str, Any] = {}
    for rp in rels:
        cur = tree
        parts = rp.split("/")
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                cur.setdefault("__files__", set()).add(part)
            else:
                cur = cur.setdefault(part, {})

    lines: list[str] = [root_name]

    def walk(node: dict[str, Any], prefix: str) -> None:
        dirs = sorted([k for k in node if k != "__files__"], key=str.lower)
        files = sorted(node.get("__files__", set()), key=str.lower)
        entries: list[tuple[str, str, Any]] = []
        entries.extend(("dir", d, node[d]) for d in dirs)
        entries.extend(("file", f, None) for f in files)
        for idx, (kind, name, child) in enumerate(entries):
            last = idx == len(entries) - 1
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + name + ("/" if kind == "dir" else ""))
            if kind == "dir":
                ext = "    " if last else "│   "
                walk(child, prefix + ext)

    walk(tree, "")
    return lines


def now_iso() -> str:
    """Return the current date and time in ISO 8601 format with timezone.

    Returns:
        str: the current date and time in ISO 8601 format with timezone
    """
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def make_meta_string(rec: FileRecord) -> str:
    """Create a metadata string for a file record.

    Args:
        rec (FileRecord): the file record to create a metadata string for

    Returns:
        str: a string containing metadata about the file, such as size and SHA-256 digest
    """
    meta = f"size={rec.size} bytes"
    if rec.sha256:
        meta += f" sha256={rec.sha256}"
    return meta


def make_recs(
    files: Sequence[Path],
    repo: Path,
    max_bytes: int,
    *,
    no_sha: bool = True,
) -> list[FileRecord]:
    """Create a list of FileRecord objects for the given files.

    Args:
        files (Sequence[Path]): the list of file paths to
            create records for (absolute paths)
        repo (Path): the root path to relativize file paths against for the `rel` field
        max_bytes (int): the maximum file size in bytes to include contents for;
            files larger than this will have an empty `sha256` and `too_big=True`
        no_sha (bool, optional): if True, do not compute SHA-256 digests and set `sha256` to an empty string for all files. Defaults to True.

    Returns:
        list[FileRecord]: a list of FileRecord objects with metadata for each file
    """
    recs: list[FileRecord] = []
    for f in files:
        try:
            st = f.stat()
            rel = relpath(f, repo)
            lang = file_language(f)
            too_big = st.st_size > max_bytes
            is_text = sniff_text_utf8(f)
            digest = "" if (no_sha or st.st_size > 50_000_000) else (sha256_file(f))  # noqa: PLR2004
            recs.append(
                FileRecord(
                    path=f,
                    rel=rel,
                    size=st.st_size,
                    mtime=st.st_mtime,
                    sha256=digest,
                ),
            )
        except Exception as e:
            logger.warning("Skipping %s: %s", f, e)
    return sorted(recs, key=lambda r: r.rel.lower())


def read_text_lines(path: Path, max_lines: int | None = None) -> list[str]:
    """Read a text file and return its lines.

    Args:
        path (Path): the file path to read
        max_lines (int|None): the maximum number of lines to read; if None, read all lines

    Returns:
        list[str]: the lines of the file, or an empty list if the file cannot be read as text
    """
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if max_lines is not None and len(lines) > max_lines:
        return [*lines[: max_lines - 1], "…"]
    return lines


@register_file_processor(".env")
def redact_env(path: Path) -> str:
    """Redact environment variable values from a text file.

    This function reads a text file, identifies lines that look like environment
    variable assignments (e.g. `KEY=VALUE`), and returns a string containing only
    the variable names (keys) in sorted order. Lines that are empty, start with `#`,
    or do not contain an `=` character are ignored.

    Args:
        path (Path): the file path to read and redact

    Returns:
        str: a string containing the redacted environment variable names
    """
    lines = read_text_lines(path)
    keys: list[str] = []
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip()
        if k:
            keys.append(k)
    keys = sorted(set(keys), key=str.lower)
    return "\n".join(keys)


@register_file_processor([".pre-commit-config.yaml", ".pre-commit-config.yml"])
def summarize_precommit(path: Path) -> str:
    """Summarize the hooks defined in a pre-commit configuration file.

    This function reads a pre-commit configuration file (YAML format), extracts the
    defined hooks along with their associated repositories and revisions, and returns a
    formatted string summarizing the hooks. If the file cannot be read or parsed, it returns an error message.

    Args:
        path (Path): the file path to the pre-commit configuration file

    Returns:
        str: a summary of the pre-commit hooks defined in the configuration file, or an
            error message if the file cannot be processed
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
    hooks: list[str] = []
    repos = data.get("repos", [])
    if not isinstance(repos, list):
        repos = []
    for repo in repos:
        if not isinstance(repo, dict):
            continue
        r = str(repo.get("repo", "unknown"))
        rev = str(repo.get("rev", "unknown"))
        hs = repo.get("hooks", [])
        if not isinstance(hs, list):
            continue
        for hk in hs:
            if not isinstance(hk, dict):
                continue
            hid = str(hk.get("id", "unknown"))
            hooks.append(f"{hid} ({r}@{rev})")
    hooks = sorted(set(hooks), key=str.lower)
    return "\n".join(hooks)


def license_head(path: Path, lines: int = 1) -> str:
    """Extract the head lines of a license file.

    This function reads a license file and returns the first `head_lines` lines as a string.
    If the file cannot be read, it returns an error message.

    Args:
        path (Path): the file path to the license file
        lines (int): the number of lines to include from the head of the file

    Returns:
        str: the first `head_lines` lines of the license file, or an error message if the file cannot be read
    """
    license_lines = read_text_lines(path)
    head = license_lines[: max(0, lines)]
    return "\n".join(head)


@register_file_processor(["license", "license.md", "license.txt"])
def license_head_curry(path: Path) -> str:
    """Curried version of `license_head` with a default of 1 line.

    This is registered as a file processor for common license file names to provide a concise summary of the license type.

    Args:
        path (Path): the file path to the license file

    Returns:
        str: the first line of the license file, or an error message if the file cannot be read
    """
    return license_head(path, lines=1)


@register_file_processor(".pem")
def pem_stub(path: Path) -> str:
    """Generate a stub string for a PEM file.

    This function attempts to read a PEM file, extract the first and last lines, and compute
    a SHA-256 digest of the file contents. It returns a string containing the digest and the
    first and last lines. If the file cannot be read, it returns an error message.

    Args:
        path (Path): the file path to the PEM file

    Returns:
        str: a string containing the SHA-256 digest and the first and last lines of the PEM file,
        or an error message if the file cannot be read
    """
    try:
        lines = read_text_lines(path)
        first = lines[0] if lines else ""
        last = lines[-1] if len(lines) > 1 else ""
        digest = sha256_file(path)
        parts = [f"sha256={digest}"]
        if first:
            parts.append(first)
        if last and last != first:
            parts.append(last)
        return "\n".join(parts).strip()
    except Exception as e:
        return f"pem_unreadable error={e}"


def take_head_tail(lines: list[str], head: int, tail: int) -> str:
    """Select the first and last lines of a file.

    Args:
        lines (list[str]): the lines of the file to select from
        head (int): the number of lines to include from the head of the file
        tail (int): the number of lines to include from the tail of the file

    Returns:
        str: a string containing the selected head and tail lines,
            separated by an ellipsis if both are included
    """
    head_n = max(0, head)
    tail_n = max(0, tail)
    if head_n == 0 and tail_n == 0:
        return ""
    if head_n + tail_n >= len(lines):
        return "\n".join(lines)
    head_part = lines[:head_n]
    tail_part = lines[-tail_n:] if tail_n else []
    out: list[str] = []
    out.extend(head_part)
    out.append("…")
    out.extend(tail_part)
    return "\n".join(out)


def file_to_markdown_text(
    rec: FileRecord,
    *,
    text_head_lines: int,
    text_tail_lines: int,
    pem_mode: str,
    md_max_lines: int | None = None,
) -> tuple[str, bool]:
    """Convert a file to a markdown-friendly string, with special handling for certain types.

    The function applies heuristics based on file name, extension, size, and type to determine
    how to represent the file content in markdown. It handles redaction for `.env` files,
    summarization for pre-commit configs, truncation for large files, and stubbing for PEM files.

    Args:
        rec (FileRecord): The file record containing metadata about the file.
        text_head_lines (int): Number of head lines to include for large text files.
        text_tail_lines (int): Number of tail lines to include for large text files.
        md_max_lines (int): Maximum lines for markdown files before truncation.
        pem_mode (str): Mode for handling PEM files ('stub' or 'full').

    Returns:
        tuple[str, bool]: A tuple containing the markdown-friendly string representation of the file
            and a boolean indicating whether the content is text-like.
    """
    p = rec.path
    name_low = p.name.lower()
    suf_low = p.suffix.lower()
    is_full_pem = suf_low == ".pem" and pem_mode == "full" and rec.is_text and not rec.is_too_big
    is_pem = suf_low == ".pem"
    is_init_without_code = rec.path.name == "__init__.py" and get_init_content_if_not_empty(rec.path)
    is_not_text_nor_language = not rec.is_text and not rec.language

    if name_low == ".env":
        result = (redact_env(p), True)
    elif name_low in {".pre-commit-config.yaml", ".pre-commit-config.yml"}:
        result = (summarize_precommit(p), True)
    elif name_low in {"license", "license.md", "license.txt"}:
        result = (license_head(p, lines=1), True)
    elif is_full_pem:
        result = (p.read_text(encoding="utf-8", errors="ignore"), True)
    elif is_pem:
        result = (pem_stub(p), True)
    elif rec.path.name == "__init__.py":
        result = get_init_content_if_not_empty(rec.path), True
    elif not rec.is_text and not rec.language:
        result = (make_meta_string(rec), False)
    elif rec.is_too_big and rec.is_text:
        body = take_head_tail(read_text_lines(p), head=text_head_lines, tail=text_tail_lines)
        meta = make_meta_string(rec)
        text = meta if not body else f"{meta}\n{body}"
        result = (text, True)
    elif suf_low == ".md":
        lines = read_text_lines(p, max_lines=md_max_lines)
        return ("\n".join(lines), True)
    else:
        result = (p.read_text(encoding="utf-8", errors="ignore"), True)
    return result


def order_recs(
    recs: Sequence[FileRecord],
    *,
    tests_first: bool,
    key_first: bool,
) -> list[FileRecord]:
    """Order file records for markdown output, optionally prioritizing tests and key files.

    The ordering is determined by the following buckets:
    1) Key files (e.g., pyproject.toml, requirements.txt) if
        `key_first` is True.
    2) Test files (paths starting with "tests/") if `tests_first`
        is True.
    3) All other files.

    Within each bucket, files are sorted alphabetically by their relative path.

    Args:
        recs (Sequence[FileRecord]): The file records to order.
        tests_first (bool): Whether to prioritize test files.
        key_first (bool): Whether to prioritize key files.

    Returns:
        list[FileRecord]: The ordered list of file records.
    """

    def key(rec: FileRecord) -> tuple[int, int, str]:
        r = rec.rel
        base = Path(r).name
        is_key = base in KEY_FILES_PRIORITY or r in KEY_FILES_PRIORITY
        in_tests = r.startswith("tests/")
        key_bucket = 0 if (key_first and is_key) else 1
        test_bucket = 0 if (tests_first and in_tests) else 1
        return (key_bucket, test_bucket, r.lower())

    return sorted(recs, key=key)
