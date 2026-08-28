"""Path safety helper — blocks path traversal outside the allowed roots.

Every filesystem-touching tool must resolve paths through here before operating, so
a path supplied by the LLM (e.g. read('../../../etc/passwd')) can't escape
the allowed area.

There are two permission levels:
- resolve_within_project: 1 root = 1 root = project_root. Used by write/edit/bash —
  they may NEVER write/run outside the project.
- resolve_within_roots: N root. Used by read — besides the project, it may also read
  inside the skills directories (which can live at ~/.tap/skills, i.e. OUTSIDE the project).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class PathOutsideProject(Exception):
    """The path resolved outside EVERY allowed root."""


def resolve_within_roots(raw_path: str, roots: Sequence[Path]) -> Path:
    """Resolve raw_path and ensure it falls within AT LEAST one root.

    A path is accepted if, after resolving (flattening '..' and following
    symlinks to the real physical path), it is a subpath of any root in
    `roots`. Checked with Path.relative_to — compared by path *component*,
    so '/home/u/.tap-evil' does NOT slip through just because '/home/u/.tap' is a root.

    Args:
        raw_path: A path supplied by the LLM; relative or absolute. A relative
            path is joined onto roots[0] (convention: project_root is always first).
        roots: The list of allowed directories. Must not be empty.

    Returns:
        The resolved path, verified to be within one of the roots.

    Raises:
        PathOutsideProject: if the resolved path is within no root.
        ValueError: if roots is empty — this is a caller-side programming error, not
            input from the LLM.
    """
    if not roots:
        raise ValueError("roots không được rỗng")

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()

    for root in roots:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        return resolved

    raise PathOutsideProject(
        f"Path '{raw_path}' resolves outside all allowed roots."
    )


def resolve_within_project(raw_path: str, project_root: Path) -> Path:
    """Resolve raw_path and ensure it falls within project_root.

    A single-root wrapper around resolve_within_roots, for write/edit/bash —
    tools that may only operate INSIDE the project. Keeps the old signature so
    tools already calling this function need no changes.

    Args:
        raw_path: A path supplied by the LLM. Relative or absolute.
        project_root: The single upper boundary on the filesystem.

    Returns:
        The resolved path, verified to be within project_root.

    Raises:
        PathOutsideProject: if the resolved path is outside project_root.
    """
    return resolve_within_roots(raw_path, [project_root])
