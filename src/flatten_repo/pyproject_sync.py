"""Synchronize static dependencies in ``pyproject.toml`` from requirements files."""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
import tempfile
from pathlib import Path
from shutil import which
from subprocess import run  # noqa: S404
from typing import TYPE_CHECKING, Literal

import tomlkit
from pydantic import BaseModel, ConfigDict, field_validator
from tomlkit.items import Array, InlineTable, Table

if TYPE_CHECKING:
    from collections.abc import Sequence

    from tomlkit.toml_document import TOMLDocument

DEFAULT_RUNTIME_IN = "requirements.in"
DEFAULT_RUNTIME_TXT = "requirements.txt"
DEFAULT_LOCK_TXT = "requirements-lock.txt"
DEFAULT_GROUP_IN: dict[str, str] = {
    "dev": "requirements-dev.in",
}
DEFAULT_GROUP_TXT: dict[str, str] = {
    "dev": "requirements-dev.txt",
}

_EXACT_PIN_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?)\s*==\s*(?P<version>[^;\s]+)(?P<marker>\s*;.*)?$",
)


class DepsSyncConfig(BaseModel):
    """Configuration parameters parsed from CLI arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root: Path
    pyproject: Path | None
    dry_run: bool
    runtime_in: str
    runtime_txt: str
    group: list[str]
    compile_in: bool
    lock_txt: str
    uv_bin: str
    uv_resolution: Literal["lowest", "lowest-direct"] | None = None
    uv_verbose: bool
    pin_strategy: Literal["exact", "minimum"]
    compact_toml: bool

    @field_validator("uv_resolution", mode="before")
    @classmethod
    def _parse_uv_resolution(cls, value: str) -> str | None:
        normalized = value.strip().lower()
        if normalized in {"", "false", "none"}:
            return None
        return normalized


def find_pyproject(path: Path) -> Path:
    """Find the nearest ``pyproject.toml`` by searching upward from ``path``.

    Args:
        path (Path): Starting directory.

    Raises:
        FileNotFoundError: If no ``pyproject.toml`` is found in ``path`` or its parents.

    Returns:
        Path: Located ``pyproject.toml`` path.
    """
    current = path.resolve()
    while True:
        candidate = current / "pyproject.toml"
        if candidate.exists():
            return candidate
        if current.parent == current:
            msg = "No pyproject.toml found in path or parents"
            raise FileNotFoundError(msg)
        current = current.parent


def to_abs(root: Path, maybe_rel: str) -> Path:
    """Resolve ``maybe_rel`` against ``root`` when it is not absolute.

    Args:
        root (Path): Base directory.
        maybe_rel (str): Candidate relative or absolute path.

    Returns:
        Path: Absolute path.
    """
    path = Path(maybe_rel)
    return path if path.is_absolute() else root / path


def parse_group_overrides(values: list[str]) -> dict[str, str]:
    """Parse repeated ``--group NAME=PATH`` values.

    Args:
        values (list[str]): CLI ``--group`` values.

    Raises:
        ValueError: If a value is not in ``NAME=PATH`` form.

    Returns:
        dict[str, str]: Group name to path mapping.
    """
    out: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            msg = f"--group must be NAME=PATH, got: {value}"
            raise ValueError(msg)
        name, path = value.split("=", 1)
        name = name.strip()
        path = path.strip()
        if not name or not path:
            msg = f"--group must be NAME=PATH, got: {value}"
            raise ValueError(msg)
        out[name] = path
    return out


def read_requirements_file(path: Path) -> list[str]:
    """Read strict PEP 508 lines from a requirements file.

    Args:
        path (Path): Requirements file to read.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If unsupported pip directives/options are present.

    Returns:
        list[str]: Requirement specifiers.
    """
    if not path.exists():
        raise FileNotFoundError(path)
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(
            ("-r ", "--requirement", "-c ", "--constraint", "-e ", "--editable"),
        ):
            msg = f"Unsupported directive in {path.name}: {line}"
            raise ValueError(msg)
        if line.startswith(
            ("--index-url", "--extra-index-url", "--trusted-host", "--find-links"),
        ):
            msg = f"Index options not allowed here: {path.name}: {line}"
            raise ValueError(msg)
        out.append(line)
    return out


def write_union_in_file(
    *,
    runtime_in: Path,
    group_in: dict[str, Path],
    directory: Path,
) -> Path:
    """Create a temporary input that includes runtime and all groups via ``-r``.

    Args:
        runtime_in (Path): Runtime input file.
        group_in (dict[str, Path]): Group name to input file path.
        directory (Path): Output directory for temporary file.

    Returns:
        Path: Path to generated temporary union input.
    """
    lines = [f"-r {runtime_in.as_posix()}"]
    lines.extend(f"-r {path.as_posix()}" for _, path in sorted(group_in.items()))
    content = "\n".join(lines) + "\n"
    _, tmp = tempfile.mkstemp(prefix="requirements-union.", suffix=".in", dir=str(directory))
    out = Path(tmp)
    out.write_text(content, encoding="utf-8")
    return out


def uv_compile(
    *,
    config: DepsSyncConfig,
    input_file: Path,
    constraints: Path | None,
    output_file: Path | None = None,
) -> None:
    """Run ``uv pip compile`` for ``input_file``.

    Args:
        config (DepsSyncConfig): Runtime configuration.
        input_file (Path): Input requirements file.
        constraints (Path | None): Optional constraints file.
        output_file (Path | None): Optional explicit output file.

    Raises:
        FileNotFoundError: If configured ``uv`` binary is missing.
    """
    if which(config.uv_bin) is None:
        msg = f"`{config.uv_bin}` not found in PATH"
        raise FileNotFoundError(msg)

    output = input_file.with_suffix(".txt") if output_file is None else output_file
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [config.uv_bin, "pip", "compile", str(input_file), "-o", str(output)]
    if constraints is not None:
        cmd.extend(["--constraint", str(constraints)])
    if config.uv_resolution is not None:
        cmd.extend(["--resolution", config.uv_resolution])
    if not config.uv_verbose:
        cmd.append("--quiet")
    run(cmd, check=True)  # noqa: S603


def as_toml_array(items: list[str], *, compact: bool) -> Array:
    """Create TOMLKit array, compact on demand.

    Args:
        items (list[str]): Values to serialize.
        compact (bool): When ``True``, render one-line arrays.

    Returns:
        Array: TOML array item.
    """
    arr = tomlkit.array()
    arr.multiline(not compact)
    for item in items:
        arr.append(item)
    return arr


def ensure_project_table(doc: TOMLDocument) -> Table:
    """Return ``[project]`` table from pyproject.

    Args:
        doc (TOMLDocument): Parsed TOML document.

    Raises:
        ValueError: If ``[project]`` is missing.
        TypeError: If ``[project]`` is not a TOML table.

    Returns:
        Table: Project table.
    """
    if "project" not in doc:
        msg = "Missing [project] table in pyproject.toml"
        raise ValueError(msg)
    project = doc["project"]
    if not isinstance(project, Table):
        msg = f"Expected TOML table for [project], got {type(project).__name__}"
        raise TypeError(msg)
    return project


def remove_dynamic_dependencies(project: Table, doc: TOMLDocument) -> None:
    """Remove dynamic dependency configuration referencing requirements files."""
    if "dynamic" in project:
        dyn_item = project["dynamic"]
        dyn_values = [str(x) for x in dyn_item] if isinstance(dyn_item, Array) else [str(dyn_item)]
        kept = [value for value in dyn_values if value != "dependencies"]
        if kept:
            project["dynamic"] = as_toml_array(kept, compact=False)
        else:
            del project["dynamic"]

    tool = doc.get("tool")
    if not isinstance(tool, Table):
        return
    setuptools = tool.get("setuptools")
    if not isinstance(setuptools, Table):
        return
    dynamic = setuptools.get("dynamic")
    if not isinstance(dynamic, Table):
        return
    if "dependencies" in dynamic:
        del dynamic["dependencies"]
    if not dynamic:
        del setuptools["dynamic"]


def to_minimum_pin(requirement: str) -> str:
    """Convert ``pkg==X`` into ``pkg>=X`` while preserving markers.

    Args:
        requirement (str): Requirement specifier.

    Returns:
        str: Converted requirement.
    """
    matched = _EXACT_PIN_PATTERN.match(requirement.strip())
    if matched is None:
        return requirement
    name = matched.group("name")
    version = matched.group("version")
    marker = matched.group("marker") or ""
    return f"{name}>={version}{marker}"


def apply_pin_strategy(
    items: list[str],
    *,
    strategy: Literal["exact", "minimum"],
) -> list[str]:
    """Apply selected pinning strategy to dependency specifiers.

    Args:
        items (list[str]): Requirement lines.
        strategy (Literal["exact", "minimum"]): Pin conversion policy.

    Returns:
        list[str]: Converted lines.
    """
    if strategy == "exact":
        return items
    return [to_minimum_pin(item) for item in items]


def compact_toml_text(text: str) -> str:
    """Collapse consecutive blank lines and trim trailing spaces.

    Args:
        text (str): Rendered TOML text.

    Returns:
        str: Compacted TOML text.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    compacted: list[str] = []
    prev_blank = False
    for line in lines:
        blank = not line
        if blank and prev_blank:
            continue
        compacted.append(line)
        prev_blank = blank
    return "\n".join(compacted).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Build parser for ``sync-pyproject-deps`` subcommand.

    Returns:
        argparse.ArgumentParser: Configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="flatten-repo sync-pyproject-deps",
        description="Sync static dependencies in pyproject.toml from requirements files.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Start directory to locate pyproject.toml.",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=None,
        help="Explicit pyproject.toml path (overrides --root).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print updated pyproject.toml to stdout, do not write.",
    )
    parser.add_argument(
        "--runtime-in",
        type=str,
        default=DEFAULT_RUNTIME_IN,
        help="Runtime requirements input (.in).",
    )
    parser.add_argument(
        "--runtime-txt",
        type=str,
        default=DEFAULT_RUNTIME_TXT,
        help="Runtime requirements output (.txt).",
    )
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="Override dependency-group input mapping as NAME=PATH (repeatable).",
    )
    parser.add_argument(
        "--no-compile-in",
        dest="compile_in",
        action="store_false",
        default=True,
        help="Disable uv compilation steps (expects .txt files already present).",
    )
    parser.add_argument(
        "--lock-txt",
        type=str,
        default=DEFAULT_LOCK_TXT,
        help="Global lock/constraints output file.",
    )
    parser.add_argument(
        "--uv-bin",
        type=str,
        default="uv",
        help="uv executable (default: uv).",
    )
    parser.add_argument(
        "--uv-resolution",
        type=str,
        default="",
        choices=["lowest", "lowest-direct", "", "false", "none"],
        help="Resolution strategy for lock compilation.",
    )
    parser.add_argument(
        "--uv-verbose",
        action="store_true",
        help="Do not pass --quiet to uv (default: quiet).",
    )
    parser.add_argument(
        "--pin-strategy",
        type=str,
        default="exact",
        choices=["exact", "minimum"],
        help="Use exact pins or convert exact pins to minimum pins (>=).",
    )
    parser.add_argument(
        "--compact-toml",
        action="store_true",
        help="Render pyproject.toml in a compact format (fewer newlines).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:  # noqa: PLR0914
    """Sync dependencies from requirements files into pyproject.toml.

    Args:
        argv (Sequence[str] | None): Optional CLI arguments.

    Returns:
        int: Process exit code.
    """
    args = build_parser().parse_args(argv)
    config = DepsSyncConfig.model_validate(vars(args))

    pyproject_path = config.pyproject.resolve() if config.pyproject else find_pyproject(config.root)
    project_root = pyproject_path.parent

    group_in = dict(DEFAULT_GROUP_IN)
    group_in.update(parse_group_overrides(config.group))

    runtime_in = to_abs(project_root, config.runtime_in)
    runtime_txt = to_abs(project_root, config.runtime_txt)
    lock_txt = to_abs(project_root, config.lock_txt)

    group_in_paths = {name: to_abs(project_root, path) for name, path in group_in.items()}
    group_txt_paths = {
        name: to_abs(project_root, DEFAULT_GROUP_TXT.get(name, f"requirements-{name}.txt"))
        for name in group_in_paths
    }

    if config.compile_in:
        union_in: Path | None = None
        try:
            union_in = write_union_in_file(
                runtime_in=runtime_in,
                group_in=group_in_paths,
                directory=project_root,
            )
            uv_compile(
                config=config,
                input_file=union_in,
                constraints=None,
                output_file=lock_txt,
            )
            uv_compile(
                config=config,
                input_file=runtime_in,
                constraints=lock_txt,
                output_file=runtime_txt,
            )
            for group_name, in_path in group_in_paths.items():
                uv_compile(
                    config=config,
                    input_file=in_path,
                    constraints=lock_txt,
                    output_file=group_txt_paths[group_name],
                )
        finally:
            if union_in is not None:
                with contextlib.suppress(OSError):
                    union_in.unlink(missing_ok=True)

    runtime_deps = apply_pin_strategy(
        read_requirements_file(runtime_txt),
        strategy=config.pin_strategy,
    )
    groups = {
        name: apply_pin_strategy(
            read_requirements_file(path),
            strategy=config.pin_strategy,
        )
        for name, path in group_txt_paths.items()
    }

    original = pyproject_path.read_text(encoding="utf-8")
    doc = tomlkit.parse(original)
    project = ensure_project_table(doc)

    remove_dynamic_dependencies(project, doc)
    project["dependencies"] = as_toml_array(runtime_deps, compact=config.compact_toml)

    dependency_groups: Table | InlineTable = tomlkit.table()
    for group_name, deps in groups.items():
        dependency_groups[group_name] = as_toml_array(deps, compact=config.compact_toml)
    doc["dependency-groups"] = dependency_groups

    rendered = tomlkit.dumps(doc)
    if config.compact_toml:
        rendered = compact_toml_text(rendered)

    if config.dry_run:
        sys.stdout.write(rendered)
        return 0

    if rendered != original:
        pyproject_path.write_text(rendered, encoding="utf-8")
    return 0
