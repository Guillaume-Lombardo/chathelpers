"""Synchronize static dependencies in ``pyproject.toml`` from requirements files."""

from __future__ import annotations

import argparse
import contextlib
import re
import shutil
import sys
import tempfile
from pathlib import Path
from shutil import which
from subprocess import run  # noqa: S404
from typing import TYPE_CHECKING, Literal

import tomlkit
from packaging.requirements import InvalidRequirement, Requirement
from pydantic import BaseModel, ConfigDict, field_validator
from tomlkit.items import Array, Table

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

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
GROUP_WHITELIST: frozenset[str] = frozenset(DEFAULT_GROUP_IN)

_EXACT_PIN_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?)\s*==\s*(?P<version>[^;\s]+)(?P<marker>\s*;.*)?$",
)


class ResolvedPaths(BaseModel):
    """Absolute paths derived from CLI configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pyproject: Path
    project_root: Path
    runtime_in: Path
    runtime_txt: Path
    lock_txt: Path
    group_in: dict[str, Path]
    group_txt: dict[str, Path]


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
    fail_on_unpinned: bool
    validate_pep508: bool
    backup: bool
    strict_group_whitelist: bool

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


def warn(text: str) -> None:
    """Write warning text to stderr.

    Args:
        text (str): Warning text.
    """
    sys.stderr.write(f"WARNING: {text}\n")


def check_group_whitelist(group_names: Iterable[str], *, strict: bool) -> None:
    """Validate group names against whitelist.

    Args:
        group_names (Iterable[str]): Group names to validate.
        strict (bool): Whether unknown groups should raise.

    Raises:
        ValueError: If strict mode is enabled and unknown group names are present.
    """
    unknown = sorted({name for name in group_names if name not in GROUP_WHITELIST})
    if not unknown:
        return
    message = f"Unknown dependency groups outside whitelist {sorted(GROUP_WHITELIST)}: {unknown}"
    if strict:
        raise ValueError(message)
    warn(message)


def resolve_paths(config: DepsSyncConfig) -> ResolvedPaths:
    """Resolve paths used by the sync operation.

    Args:
        config (DepsSyncConfig): Parsed runtime configuration.

    Returns:
        ResolvedPaths: All relevant absolute paths.
    """
    pyproject_path = config.pyproject.resolve() if config.pyproject else find_pyproject(config.root)
    project_root = pyproject_path.parent

    group_in_raw = dict(DEFAULT_GROUP_IN)
    group_in_raw.update(parse_group_overrides(config.group))
    check_group_whitelist(
        group_in_raw.keys(),
        strict=config.strict_group_whitelist,
    )

    group_in_paths = {name: to_abs(project_root, path) for name, path in group_in_raw.items()}
    group_txt_paths = {
        name: to_abs(project_root, DEFAULT_GROUP_TXT.get(name, f"requirements-{name}.txt"))
        for name in group_in_paths
    }
    return ResolvedPaths(
        pyproject=pyproject_path,
        project_root=project_root,
        runtime_in=to_abs(project_root, config.runtime_in),
        runtime_txt=to_abs(project_root, config.runtime_txt),
        lock_txt=to_abs(project_root, config.lock_txt),
        group_in=group_in_paths,
        group_txt=group_txt_paths,
    )


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


def compile_inputs(config: DepsSyncConfig, paths: ResolvedPaths) -> None:
    """Compile requirements inputs into lock and text files.

    Args:
        config (DepsSyncConfig): Runtime configuration.
        paths (ResolvedPaths): Resolved paths.
    """
    union_in: Path | None = None
    try:
        union_in = write_union_in_file(
            runtime_in=paths.runtime_in,
            group_in=paths.group_in,
            directory=paths.project_root,
        )
        uv_compile(
            config=config,
            input_file=union_in,
            constraints=None,
            output_file=paths.lock_txt,
        )
        uv_compile(
            config=config,
            input_file=paths.runtime_in,
            constraints=paths.lock_txt,
            output_file=paths.runtime_txt,
        )
        for group_name, in_path in paths.group_in.items():
            uv_compile(
                config=config,
                input_file=in_path,
                constraints=paths.lock_txt,
                output_file=paths.group_txt[group_name],
            )
    finally:
        if union_in is not None:
            with contextlib.suppress(OSError):
                union_in.unlink(missing_ok=True)


def parse_requirement(requirement: str, *, source: str) -> Requirement:
    """Parse a requirement string and raise a clearer validation error.

    Args:
        requirement (str): Requirement line.
        source (str): Source identifier used in error message.

    Raises:
        ValueError: If requirement is not valid PEP 508.

    Returns:
        Requirement: Parsed requirement.
    """
    try:
        return Requirement(requirement)
    except InvalidRequirement as exc:
        msg = f"Invalid PEP 508 requirement in {source}: {requirement}"
        raise ValueError(msg) from exc


def validate_pep508_lines(items: list[str], *, source: str) -> None:
    """Validate requirement lines as PEP 508.

    Args:
        items (list[str]): Requirement lines.
        source (str): Source identifier used in error messages.
    """
    for item in items:
        parse_requirement(item, source=source)


def assert_all_pinned(items: list[str], *, source: str) -> None:
    """Ensure every requirement is pinned by version or URL.

    Args:
        items (list[str]): Requirement lines.
        source (str): Source identifier used in error message.

    Raises:
        ValueError: If one or more requirements are unpinned.
    """
    unpinned: list[str] = []
    for item in items:
        req = parse_requirement(item, source=source)
        if not req.specifier and req.url is None:
            unpinned.append(item)
    if unpinned:
        msg = f"Unpinned dependencies found in {source}: {unpinned}"
        raise ValueError(msg)


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


def load_dependencies(
    config: DepsSyncConfig,
    paths: ResolvedPaths,
) -> tuple[list[str], dict[str, list[str]]]:
    """Load, validate and normalize dependencies from requirements files.

    Args:
        config (DepsSyncConfig): Runtime configuration.
        paths (ResolvedPaths): Resolved paths.

    Returns:
        tuple[list[str], dict[str, list[str]]]: Runtime dependencies and groups.
    """
    runtime_raw = read_requirements_file(paths.runtime_txt)
    groups_raw = {name: read_requirements_file(path) for name, path in paths.group_txt.items()}

    if config.validate_pep508:
        validate_pep508_lines(runtime_raw, source=paths.runtime_txt.name)
        for group_name, lines in groups_raw.items():
            validate_pep508_lines(lines, source=paths.group_txt[group_name].name)

    runtime_deps = apply_pin_strategy(runtime_raw, strategy=config.pin_strategy)
    groups_deps = {
        name: apply_pin_strategy(lines, strategy=config.pin_strategy) for name, lines in groups_raw.items()
    }

    if config.fail_on_unpinned:
        assert_all_pinned(runtime_deps, source=paths.runtime_txt.name)
        for group_name, lines in groups_deps.items():
            assert_all_pinned(lines, source=paths.group_txt[group_name].name)

    return runtime_deps, groups_deps


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
    """Remove dynamic dependency configuration referencing requirements files.

    Args:
        project (Table): ``[project]`` table.
        doc (TOMLDocument): Parsed pyproject document.
    """
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


def render_updated_pyproject(
    pyproject_path: Path,
    *,
    runtime_deps: list[str],
    group_deps: dict[str, list[str]],
    compact_toml: bool,
) -> tuple[str, str]:
    """Render updated pyproject content.

    Args:
        pyproject_path (Path): pyproject path.
        runtime_deps (list[str]): Runtime dependencies to write.
        group_deps (dict[str, list[str]]): Dependency groups to write.
        compact_toml (bool): Whether to compact formatting.

    Returns:
        tuple[str, str]: Original and rendered file content.
    """
    original = pyproject_path.read_text(encoding="utf-8")
    doc = tomlkit.parse(original)
    project = ensure_project_table(doc)

    remove_dynamic_dependencies(project, doc)
    project["dependencies"] = as_toml_array(runtime_deps, compact=compact_toml)

    dependency_groups = tomlkit.table()
    for group_name, deps in group_deps.items():
        dependency_groups[group_name] = as_toml_array(deps, compact=compact_toml)
    doc["dependency-groups"] = dependency_groups

    rendered = tomlkit.dumps(doc)
    if compact_toml:
        rendered = compact_toml_text(rendered)
    return original, rendered


def write_updated_pyproject(
    *,
    pyproject_path: Path,
    original: str,
    rendered: str,
    create_backup: bool,
) -> None:
    """Persist updated pyproject if content has changed.

    Args:
        pyproject_path (Path): pyproject path.
        original (str): Previous file content.
        rendered (str): New file content.
        create_backup (bool): Whether to write a ``.bak`` backup file.
    """
    if rendered == original:
        return
    if create_backup:
        backup_path = pyproject_path.with_suffix(f"{pyproject_path.suffix}.bak")
        shutil.copy2(pyproject_path, backup_path)
    pyproject_path.write_text(rendered, encoding="utf-8")


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
        "--strict-group-whitelist",
        action="store_true",
        help="Fail when a group is outside the internal whitelist.",
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
        "--fail-on-unpinned",
        action="store_true",
        help="Fail if at least one dependency is missing a version pin or URL.",
    )
    parser.add_argument(
        "--validate-pep508",
        action="store_true",
        help="Validate dependency lines with packaging.Requirement parser.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Write pyproject.toml.bak before overwriting pyproject.toml.",
    )
    parser.add_argument(
        "--compact-toml",
        action="store_true",
        help="Render pyproject.toml in a compact format (fewer newlines).",
    )
    return parser


def parse_config(argv: Sequence[str] | None = None) -> DepsSyncConfig:
    """Parse CLI arguments into configuration object.

    Args:
        argv (Sequence[str] | None): Optional CLI args.

    Returns:
        DepsSyncConfig: Parsed config.
    """
    args = build_parser().parse_args(argv)
    return DepsSyncConfig.model_validate(vars(args))


def sync_dependencies(config: DepsSyncConfig) -> str:
    """Run full sync pipeline and return rendered TOML.

    Args:
        config (DepsSyncConfig): Runtime configuration.

    Returns:
        str: Rendered ``pyproject.toml`` content.
    """
    paths = resolve_paths(config)
    if config.compile_in:
        compile_inputs(config, paths)
    runtime_deps, group_deps = load_dependencies(config, paths)
    original, rendered = render_updated_pyproject(
        paths.pyproject,
        runtime_deps=runtime_deps,
        group_deps=group_deps,
        compact_toml=config.compact_toml,
    )
    if config.dry_run:
        return rendered
    write_updated_pyproject(
        pyproject_path=paths.pyproject,
        original=original,
        rendered=rendered,
        create_backup=config.backup,
    )
    return rendered


def main(argv: Sequence[str] | None = None) -> int:
    """Sync dependencies from requirements files into pyproject.toml.

    Args:
        argv (Sequence[str] | None): Optional CLI arguments.

    Returns:
        int: Process exit code.
    """
    config = parse_config(argv)
    rendered = sync_dependencies(config)
    if config.dry_run:
        sys.stdout.write(rendered)
    return 0
