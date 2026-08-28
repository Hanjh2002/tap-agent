"""Test path safety — resolve_within_project chặn traversal."""

from __future__ import annotations

from pathlib import Path

import pytest

from tap.tools._paths import PathOutsideProject, resolve_within_project


def test_relative_path_resolves_within_project(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    result = resolve_within_project("sub/file.txt", tmp_path)
    assert result == (tmp_path / "sub" / "file.txt").resolve()


def test_absolute_path_within_project_ok(tmp_path: Path) -> None:
    inside = tmp_path / "foo.txt"
    result = resolve_within_project(str(inside), tmp_path)
    assert result == inside.resolve()


def test_traversal_upward_denied(tmp_path: Path) -> None:
    """`../../etc/passwd` phải bị chặn."""
    with pytest.raises(PathOutsideProject):
        resolve_within_project("../../etc/passwd", tmp_path)


def test_absolute_path_outside_denied(tmp_path: Path) -> None:
    with pytest.raises(PathOutsideProject):
        resolve_within_project("/etc/passwd", tmp_path)


def test_dot_paths_ok(tmp_path: Path) -> None:
    """`./file.txt` phải resolve trong project."""
    result = resolve_within_project("./x.txt", tmp_path)
    assert result == (tmp_path / "x.txt").resolve()
