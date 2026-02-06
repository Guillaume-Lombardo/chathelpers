# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "pydantic",
#     "pyyaml",
#     "structlog",
# ]
# ///
#  -*- coding: utf-8 -*-
"""
flatten_repo — Prepare the current project directory for an LLM.
 
Overview
--------
This utility exports a software project into formats that are convenient for
Large Language Models (LLMs):
 
1) **Markdown (`--format md`)** — a single readable document containing:
   - a project tree,
   - key configuration files,
   - code and text files with fenced code blocks,
   - light redaction for secrets (e.g., `.env` variable *names only*),
   - summaries for some meta files (pre-commit hooks, license head).
 
2) **JSONL (`--format jsonl`)** — a stream of chunked file contents, suitable
   for ingestion by RAG pipelines or custom tools.
 
It prefers `git ls-files` (to honor ignores), and falls back to a filesystem
walk when Git is unavailable or disabled (`--no-git`). You can constrain the
export with include/exclude globs, cap large files with `--max-bytes`, and
tune chunk size via `--chunk-chars`.
 
Python ≥ 3.13. Minimal dependency: `pyyaml` (for pre-commit parsing).
 
Usage
-----
Run `python -m flatten_repo.cli --help` for full options. Common examples:
    - Markdown (src + key files):
        uv run python -m flatten_repo.cli --output repo_for_llm.md
 
    - Full project as JSONL (32k char chunks):
        uv run python -m flatten_repo.cli --all --format jsonl --chunk-chars 32000 --output corpus.jsonl
 
    - Include tests and extra globs, exclude images:
        uv run python -m flatten_repo.cli --tests --include "**/*.cfg" --exclude "**/*.png" --output out.md
    - Log to a file:
        uv run python -m flatten_repo.cli --output out.md --log-file export.log
"""
 
from __future__ import annotations
 
import argparse
import ast
import fnmatch
import hashlib
import io
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any
 
import yaml
from pydantic import BaseModel, ConfigDict, Field

from flatten_repo.logging import setup_logging
from flatten_repo.settings import Settings
 
if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
 
    FileProcessorFn = Callable[[Path], str]
 
logger = setup_logging()
 
# ------------------------------ Types & Maps --------------------------------
 
EXT2LANG = {
    ".py": "python",
    ".toml": "toml",
    ".txt": "text",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".html": "html",
    ".css": "css",
    ".js": "javascript",
    ".ts": "typescript",
    ".sh": "bash",
    ".rs": "rust",
    ".go": "go",
    ".php": "php",
    ".sql": "sql",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".bash": "bash",
    ".zsh": "zsh",
    ".xml": "xml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".pem": "pem",
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
    "README.md",
    "pyproject.toml",
    "requirements.txt",
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
 
@dataclass(frozen=True)
class FileRec:
    path: Path
    rel: str
    language: str
    size: int
    mtime: float
    sha256: str
    is_text: bool
    too_big: bool
 
# ------------------------------ Utilities -----------------------------------
 
def register_file_processor(
    key: str | list[str],
) -> Callable[[FileProcessorFn], FileProcessorFn]:
    """Decorator to register a file processing function based on file suffix or name."""
 
    def decorator(func: FileProcessorFn) -> FileProcessorFn:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
 
        if isinstance(key, list):
            for k in key:
                FILE_PROCESSOR[k] = func
            return func
        FILE_PROCESSOR[key] = func
        return wrapper
 
    return decorator
 
def relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(path)
 
def file_language(path: Path) -> str:
    name = path.name.lower()
    if name == "dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    return EXT2LANG.get(path.suffix.lower(), "")
 
def is_probably_text(path: Path) -> bool:
    """
    Check if a file is probably text.
 
    Heuristically determine whether a file is text by trying to decode
    the first 4 KiB as UTF-8. Returns False on any failure.
    """
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode):
            return False
        with path.open("rb") as f:
            chunk = f.read(4096)
        chunk.decode("utf-8")
        return True  # noqa: TRY300
    except Exception:
        return False
 
def sha256_file(path: Path) -> str:
    """Compute and return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()
 
def load_git_tracked_files(repo: Path) -> list[Path]:
    """
    Use `git ls-files` to retrieve the list of tracked files within `repo`.
 
    Raises:
        RuntimeError: if `.git` is missing or `git` invocation fails.
 
    """
    git_dir = repo / ".git"
    if not git_dir.exists():
        raise RuntimeError("Not a git repository")
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
    """
    Collect files by walking the filesystem under `repo`.
 
    Recursively walk the filesystem under `repo`, pruning common transient
    or tool-specific directories defined in `DEFAULT_EXCLUDES`.
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
    """
    Apply include/exclude globbing to a list of files relative to `root`.
 
    - If `includes` is provided, a file must match at least one include pattern.
    - If `excludes` is provided, a matching file is removed.
    - If neither is provided, `files` is returned as-is.
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
    try:
        st = path.stat()
        return stat.S_ISREG(st.st_mode)
    except Exception:
        return False
 
def sniff_text_utf8(path: Path, nbytes: int = 4096) -> bool:
    try:
        if not is_regular_file(path):
            return False
        with path.open("rb") as f:
            chunk = f.read(nbytes)
        chunk.decode("utf-8")
        return True
    except Exception:
        return False
 
def git_ls_files(repo: Path) -> list[Path]:
    git_dir = repo / ".git"
    if not git_dir.exists():
        raise RuntimeError("Not a git repository")
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
    results: list[Path] = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDES]
        for f in files:
            p = (Path(root) / f).resolve()
            if p.is_file():
                results.append(p)
    return results
 
def in_default_excludes(repo: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(repo).parts
    except Exception:
        return True
    return any(p in DEFAULT_EXCLUDES for p in parts)
 
def is_init_py_without_code(path: Path) -> bool:
    if path.name != "__init__.py":
        return False
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
        body = tree.body
        if not body:
            return True
        if len(body) == 1 and isinstance(body[0], ast.Expr):
            v = body[0].value
            return isinstance(v, ast.Constant) and isinstance(v.value, str)
        return False
    except Exception:
        return False
 
def match_any_glob(rel: str, globs: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) for g in globs)
 
def normalize_globs(globs: Sequence[str]) -> list[str]:
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
    inc = normalize_globs(includes)
    exc = normalize_globs(excludes)
    exc_paths = [
        p.strip().strip("/").replace("\\", "/") for p in exclude_paths if p.strip()
    ]
 
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
        for d in dirs:
            entries.append(("dir", d, node[d]))
        for f in files:
            entries.append(("file", f, None))
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
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
 
def make_recs(
    files: Sequence[Path],
    repo: Path,
    max_bytes: int,
    *,
    no_sha: bool = True,
) -> list[FileRec]:
    recs: list[FileRec] = []
    for f in files:
        try:
            st = f.stat()
            rel = relpath(f, repo)
            lang = file_language(f)
            too_big = st.st_size > max_bytes
            is_text = sniff_text_utf8(f)
            digest = "" if (no_sha or st.st_size > 50_000_000) else (sha256_file(f))
            recs.append(
                FileRec(
                    path=f,
                    rel=rel,
                    language=lang,
                    size=st.st_size,
                    mtime=st.st_mtime,
                    sha256=digest,
                    is_text=is_text,
                    too_big=too_big,
                ),
            )
        except Exception as e:
            logger.warning("Skipping %s: %s", f, e)
    return sorted(recs, key=lambda r: r.rel.lower())
 
def read_text_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()
 
def redact_env(path: Path) -> str:
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
 
def summarize_precommit(path: Path) -> str:
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
 
def license_head(path: Path, head_lines: int) -> str:
    lines = read_text_lines(path)
    head = lines[: max(0, head_lines)]
    return "\n".join(head)
 
def pem_stub(path: Path) -> str:
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
    rec: FileRec,
    *,
    text_head_lines: int,
    text_tail_lines: int,
    md_max_lines: int,
    pem_mode: str,
) -> tuple[str, bool]:
    p = rec.path
    name_low = p.name.lower()
    suf_low = p.suffix.lower()
 
    if name_low == ".env":
        return (redact_env(p), True)
 
    if name_low in {".pre-commit-config.yaml", ".pre-commit-config.yml"}:
        return (summarize_precommit(p), True)
 
    if name_low in {"license", "license.md", "license.txt"}:
        return (license_head(p, head_lines=12), True)
 
    if suf_low == ".pem":
        if pem_mode == "full" and rec.is_text and not rec.too_big:
            return (p.read_text(encoding="utf-8", errors="ignore"), True)
        return (pem_stub(p), True)
 
    if rec.path.name == "__init__.py" and is_init_py_without_code(rec.path):
        return ("(empty __init__.py)", False)
 
    if not rec.is_text and not rec.language:
        meta = f"binary size={rec.size}"
        if rec.sha256:
            meta += f" sha256={rec.sha256}"
        return (meta, False)
 
    if rec.too_big:
        lines = read_text_lines(p)
        if suf_low == ".md":
            body = take_head_tail(lines, head=min(md_max_lines, len(lines)), tail=0)
        else:
            body = take_head_tail(lines, head=text_head_lines, tail=text_tail_lines)
        meta = f"truncated size={rec.size}"
        if rec.sha256:
            meta += f" sha256={rec.sha256}"
        return (meta + "\n" + body if body else meta, True)
 
    if suf_low == ".md":
        lines = read_text_lines(p)
        if md_max_lines > 0 and len(lines) > md_max_lines:
            body = "\n".join([*lines[:md_max_lines], "…"])
            return (body, True)
        return (p.read_text(encoding="utf-8", errors="ignore"), True)
 
    return (p.read_text(encoding="utf-8", errors="ignore"), True)
 
def order_recs(
    recs: Sequence[FileRec],
    *,
    tests_first: bool,
    key_first: bool,
) -> list[FileRec]:
    def key(rec: FileRec) -> tuple[int, int, str]:
        r = rec.rel
        base = Path(r).name
        is_key = base in KEY_FILES_PRIORITY or r in KEY_FILES_PRIORITY
        in_tests = r.startswith("tests/")
        key_bucket = 0 if (key_first and is_key) else 1
        test_bucket = 0 if (tests_first and in_tests) else 1
        return (key_bucket, test_bucket, r.lower())
 
    return sorted(recs, key=key)
 
# ------------------------------ Specialty parsers ----------------------------
 
@register_file_processor(".env")
def process_env_file(path: Path) -> str:
    """
    Produce a redacted view of a `.env` file: only variable names are listed.
 
    This helps an LLM understand available configuration knobs without leaking
    secret values. Comments and blank lines are ignored.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        keys = [
            ln.split("=", 1)[0].strip()
            for ln in lines
            if "=" in ln and not ln.strip().startswith("#")
        ]
        return f"# .env redacted: {len(keys)} variables\n" + "\n".join(
            f"- {k}" for k in keys
        )
    except Exception as e:
        logger.warning("Failed to parse .env %s: %s", path, e)
        return f"# .env redacted (error reading: {e})"
 
@register_file_processor([".pre-commit-config.yaml", ".pre-commit-config.yml"])
def process_precommit(path: Path) -> str:
    """
    Process .pre-commit-config.(yml|yaml) files.
 
    Parse `.pre-commit-config.(yml|yaml)` and summarize listed hooks
    as `id (repo@rev)` lines.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
        hooks: list[str] = []
        for repo in data.get("repos", []):
            if not isinstance(repo, dict):
                continue
            r = repo.get("repo", "unknown")
            rev = repo.get("rev", "unknown")
            for hk in repo.get("hooks", []):
                if isinstance(hk, dict):
                    hooks.append(f"{hk.get('id', 'unknown')} ({r}@{rev})")
        return "Pre-commit hooks:\n" + "\n".join(f" - {h}" for h in hooks)
    except Exception as e:
        logger.warning("Failed to parse pre-commit %s: %s", path, e)
        return f"Pre-commit: error parsing: {e}"
 
@register_file_processor(["license", "license.md", "license.txt"])
def process_license_head(path: Path, lines: int = 8) -> str:
    """Return the first `lines` lines of a LICENSE file (or an error message)."""
    try:
        head = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:lines]
        return "\n".join(head) + ("\n[...]" if head else "")
    except Exception as e:
        return f"LICENSE head unavailable: {e}"
 
@register_file_processor(".pem")
def process_pem_head(path: Path, lines: int = 8) -> str:
    """Return the first `lines` lines of a PEM file (or an error message)."""
    try:
        head = path.read_text(encoding="utf-8", errors="ignore").splitlines()[:lines]
        return "\n".join(head) + ("\n[...]" if head else "")
    except Exception as e:
        return f"{path.name} head unavailable: {e}"
 
# ------------------------------ Models (Pydantic) ----------------------------
 
class FileRecord(BaseModel):
    """
    Lightweight metadata for a file included in the export.
 
    Attributes:
        path: Absolute path to the file on disk.
        rel: Path relative to the chosen repository root.
        language: Suggested code fence language (may be empty).
        size: File size in bytes.
        mtime: POSIX mtime (float seconds since epoch).
        sha256: SHA-256 hex digest of file contents (may be empty for huge files).
        is_text: Heuristic indicator for "text-like" files.
 
    """
 
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)
 
    path: Path = Field(..., description="Absolute file path")
    rel: str = Field(..., description="File path relative to repository root")
    language: str = Field("", description="Fenced code block language name")
    size: int = Field(..., ge=0, description="File size in bytes")
    mtime: float = Field(..., description="POSIX modification time (seconds)")
    sha256: str = Field("", description="SHA-256 hex digest (optional for huge files)")
    is_text: bool = Field(..., description="Heuristic UTF-8 sniff result")
 
# ------------------------------ Corpus building -----------------------------
 
def build_markdown(
    repo: Path,
    recs: Sequence[FileRec],
    *,
    compact: bool,
    tests_first: bool,
    key_first: bool,
    text_head_lines: int,
    text_tail_lines: int,
    md_max_lines: int,
    pem_mode: str,
) -> str:
    out = io.StringIO()
    rp = str(repo)
    out.write("# Project Export for LLM\n")
    out.write(f"root={rp}\n")
    out.write(f"generated_at={now_iso()}\n")
    out.write(f"files={len(recs)}\n\n")
 
    rels = [r.rel for r in recs]
    tree_lines = build_tree_lines(repo.name, rels)
    out.write("```text\n")
    out.write("\n".join(tree_lines))
    out.write("\n```\n\n")
 
    ordered = order_recs(recs, tests_first=tests_first, key_first=key_first)
 
    for rec in ordered:
        header = f"{rec.rel} size={rec.size}"
        if rec.sha256:
            header += f" sha256={rec.sha256}"
        out.write(f"## {header}\n")
        lang = rec.language or "text"
        body, _is_text = file_to_markdown_text(
            rec,
            text_head_lines=text_head_lines,
            text_tail_lines=text_tail_lines,
            md_max_lines=md_max_lines,
            pem_mode=pem_mode,
        )
        if compact:
            out.write(f"```{lang}\n{body}\n```\n\n")
        else:
            out.write(f"```{lang}\n{body}\n```\n\n")
 
    return out.getvalue().rstrip() + "\n"
 
def chunk_content(text: str, chunk_chars: int) -> Iterator[tuple[int, int, str]]:
    if not text:
        yield (0, 0, "")
        return
    lines = text.splitlines()
    buf: list[str] = []
    cur = 0
    start_line = 1
    for i, ln in enumerate(lines, start=1):
        ln2 = ln + "\n"
        if cur + len(ln2) > chunk_chars and buf:
            yield (start_line, i - 1, "".join(buf))
            buf = []
            cur = 0
            start_line = i
        buf.append(ln2)
        cur += len(ln2)
    if buf:
        yield (start_line, start_line + len(buf) - 1, "".join(buf))
 
def build_jsonl(
    repo: Path,
    recs: Sequence[FileRec],
    *,
    chunk_chars: int,
    text_head_lines: int,
    text_tail_lines: int,
    md_max_lines: int,
    pem_mode: str,
    include_binary_meta: bool,
) -> str:
    buf = io.StringIO()
    for rec in recs:
        text, is_text = file_to_markdown_text(
            rec,
            text_head_lines=text_head_lines,
            text_tail_lines=text_tail_lines,
            md_max_lines=md_max_lines,
            pem_mode=pem_mode,
        )
        if not is_text and not include_binary_meta:
            continue
        for start, end, chunk in chunk_content(text, chunk_chars=chunk_chars):
            item = {
                "repo_root": str(repo),
                "path": rec.rel,
                "language": rec.language,
                "size": rec.size,
                "mtime": rec.mtime,
                "sha256": rec.sha256,
                "start_line": start,
                "end_line": end,
                "text": chunk,
            }
            buf.write(json.dumps(item, ensure_ascii=False) + "\n")
    return buf.getvalue()
 
def parse_args(argv: Sequence[str] | None = None) -> Settings:
    p = argparse.ArgumentParser(
        description="Export a project for LLM consumption (md/jsonl).",
    )
    p.add_argument("--repo", type=str, default=".", help="Repository root.")
    p.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output file (.md or .jsonl).",
    )
    p.add_argument(
        "--format",
        type=str,
        choices=["md", "jsonl"],
        default="",
        help="Force format.",
    )
    p.add_argument("--no-git", action="store_true", help="Do not use git ls-files.")
    p.add_argument("--log-file", type=str, default="", help="Log file path.")
 
    scope = p.add_mutually_exclusive_group()
    scope.add_argument(
        "--all",
        action="store_true",
        help="Export all files (after filters).",
    )
    scope.add_argument(
        "--src-only",
        action="store_true",
        help="Export src/ + key files (default).",
    )
    scope.add_argument(
        "--tests-only",
        action="store_true",
        help="Export tests/ only (+ optional key files).",
    )
 
    p.add_argument(
        "--include-tests",
        action="store_true",
        help="When src-only, include tests/.",
    )
    p.add_argument(
        "--tests-first",
        action="store_true",
        help="Order tests before src in md.",
    )
    p.add_argument(
        "--no-key-first",
        action="store_true",
        help="Do not prioritize key files.",
    )
 
    p.add_argument(
        "--include-glob",
        action="append",
        default=[],
        help="Include glob (repeatable).",
    )
    p.add_argument(
        "--exclude-glob",
        action="append",
        default=[],
        help="Exclude glob (repeatable).",
    )
    p.add_argument(
        "--exclude-path",
        action="append",
        default=[],
        help="Exclude path prefix (repeatable).",
    )
    p.add_argument(
        "--drop",
        type=str,
        default="",
        help="Comma list: api,front,data,docs,tests.",
    )
 
    p.add_argument(
        "--max-bytes",
        type=int,
        default=500_000,
        help="Text files above are truncated/stubbed.",
    )
    p.add_argument(
        "--text-head-lines",
        type=int,
        default=200,
        help="Head lines for big text files.",
    )
    p.add_argument(
        "--text-tail-lines",
        type=int,
        default=80,
        help="Tail lines for big text files.",
    )
    p.add_argument(
        "--md-max-lines",
        type=int,
        default=250,
        help="Max lines for markdown/readme files.",
    )
    p.add_argument(
        "--pem",
        choices=["stub", "full"],
        default="stub",
        help="PEM handling.",
    )
    p.add_argument("--compact", action="store_true", help="Reduce markdown verbosity.")
    p.add_argument(
        "--chunk-chars",
        type=int,
        default=24_000,
        help="Chunk size for jsonl.",
    )
    p.add_argument(
        "--include-binary-meta",
        action="store_true",
        help="Include binary stubs in jsonl.",
    )
    p.add_argument(
        "--no-sha",
        action="store_true",
        help="Do not compute sha256 digests.",
    )
    args = p.parse_args(argv)
    return Settings(**vars(args))
 
def select_scope(
    files: Sequence[Path],
    repo: Path,
    settings: Settings,
) -> list[Path]:
    rels = [(f, relpath(f, repo)) for f in files]
    key_names = {"pyproject.toml", "requirements.txt", "requirements-dev.txt"} | set(
        KEY_FILES_PRIORITY,
    )
 
    def is_key(r: str) -> bool:
        return Path(r).name in key_names or r in key_names
 
    if settings.all:
        return [f for f, _ in rels]

    if settings.tests_only:
        base = [f for f, r in rels if r.startswith("tests/")]
        if not settings.no_key_first:
            base.extend([f for f, r in rels if is_key(r)])
        return sorted(set(base), key=lambda p: relpath(p, repo).lower())

    include_tests = bool(settings.include_tests)
    base: list[Path] = []
    for f, r in rels:
        if r.startswith("src/") or is_key(r):
            base.append(f)
        if include_tests and r.startswith("tests/"):
            base.append(f)
    return sorted(set(base), key=lambda p: relpath(p, repo).lower())
 
def handle_no_git_error():
    """Raise a RuntimeError for missing git."""
    raise RuntimeError("no-git")
 
def main(argv: Sequence[str] | None = None) -> int:
    settings = parse_args(argv)
    if settings.log_file:
        setup_logging(settings.log_file)
 
    repo = Path(settings.repo).resolve()
 
    try:
        if settings.no_git:
            handle_no_git_error()
        files = git_ls_files(repo)
    except Exception as e:
        logger.info("Falling back to filesystem walk: %s", e)
        files = walk_files(repo)
 
    files = [f for f in files if f.is_file()]
    files = select_scope(files, repo, settings)
 
    drop = [x.strip().lower() for x in (settings.drop or "").split(",") if x.strip()]
    drop_globs: list[str] = []
    for d in drop:
        drop_globs.extend(DROP_PRESETS.get(d, []))
 
    selected = apply_filters(
        files=files,
        repo=repo,
        includes=settings.include_glob,
        excludes=list(settings.exclude_glob) + drop_globs,
        exclude_paths=settings.exclude_path,
    )
 
    recs = make_recs(
        selected,
        repo,
        max_bytes=int(settings.max_bytes),
        no_sha=bool(settings.no_sha),
    )
 
    out_path = Path(settings.output)
    fmt = (settings.format or "").strip().lower()
    if not fmt:
        fmt = "jsonl" if out_path.suffix.lower() == ".jsonl" else "md"
 
    if fmt == "md":
        content = build_markdown(
            repo=repo,
            recs=recs,
            compact=bool(settings.compact),
            tests_first=bool(settings.tests_first),
            key_first=not bool(settings.no_key_first),
            text_head_lines=int(settings.text_head_lines),
            text_tail_lines=int(settings.text_tail_lines),
            md_max_lines=int(settings.md_max_lines),
            pem_mode=str(settings.pem),
        )
        out_path.write_text(content, encoding="utf-8")
    else:
        content = build_jsonl(
            repo=repo,
            recs=recs,
            chunk_chars=int(settings.chunk_chars),
            text_head_lines=int(settings.text_head_lines),
            text_tail_lines=int(settings.text_tail_lines),
            md_max_lines=int(settings.md_max_lines),
            pem_mode=str(settings.pem),
            include_binary_meta=bool(settings.include_binary_meta),
        )
        out_path.write_text(content, encoding="utf-8")
 
    print(f"Wrote {out_path} format={fmt} files={len(recs)}")
    return 0
 
if __name__ == "__main__":
    raise SystemExit(main())
