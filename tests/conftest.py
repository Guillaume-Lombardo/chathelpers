from __future__ import annotations

from pathlib import Path

import pytest


def _mark_tests_by_directory(
    config: pytest.Config,
    items: list[pytest.Item],
    marker: str,
) -> None:
    target_dir = Path(config.rootpath) / "tests" / marker
    target_dir = target_dir.resolve()

    for item in items:
        try:
            p = Path(str(item.fspath)).resolve()
        except Exception:  # noqa: S112
            continue

        if p == target_dir or target_dir in p.parents:
            item.add_marker(getattr(pytest.mark, marker))


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    _mark_tests_by_directory(config, items, "unit")
    _mark_tests_by_directory(config, items, "integration")
    _mark_tests_by_directory(config, items, "end2end")
