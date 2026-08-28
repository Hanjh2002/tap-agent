"""Read tool — read an UTF-8 text file.

v1: adds path safety via resolve_within_project.
v2:  also takes extra_read_roots (the skills directories). read may read within
    project_root OR these directories. write/edit/bash are NOT widened —
    least privilege: the model can read skills but can't write/run outside the project.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, Field

from tap.tools._paths import PathOutsideProject, resolve_within_roots
from tap.tools.base import BaseTool, ToolResult


class ReadArgs(BaseModel):
    path: str = Field(..., description="Path to file to read (relative to project root)")


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read a UTF-8 text file inside the project directory and return its content. "
        "Use this to examine source code, config files, or documentation. "
        "Fails if file doesn't exist, is a directory, is not UTF-8 text, "
        "or resolves outside the project root."
    )
    args_model = ReadArgs

    MAX_CHARS = 50_000

    def __init__(self, project_root: Path, extra_read_roots: Sequence[Path] = ()):
        self._project_root = project_root
        self._extra_read_roots = tuple(extra_read_roots)  # skills directories

    def _run(self, args: ReadArgs) -> ToolResult:
        roots = [self._project_root, *self._extra_read_roots]  # project come first
        try:
            path = resolve_within_roots(args.path, roots)
        except PathOutsideProject as e:
            return ToolResult(output=str(e), ok=False)

        if not path.exists():
            return ToolResult(output=f"File not found: {args.path}", ok=False)
        if path.is_dir():
            return ToolResult(output=f"Path is a directory, not a file: {args.path}", ok=False)

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(
                output=f"File is not valid UTF-8 text: {args.path}",
                ok=False,
            )
        except PermissionError:
            return ToolResult(output=f"Permission denied: {args.path}", ok=False)

        original_len = len(text)
        if original_len > self.MAX_CHARS:
            text = (
                text[: self.MAX_CHARS]
                + f"\n\n[truncated — file has {original_len} chars, showing first {self.MAX_CHARS}]"
            )

        return ToolResult(output=text)
    