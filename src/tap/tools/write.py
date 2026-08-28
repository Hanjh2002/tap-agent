"""Write tool — creates a new file or overwrites one completely.

v2: adds path safety via resolve_within_project.

WARNING: This tool still overwrites files without asking (it only blocks path traversal).
A confirmation step at the CLI layer will be added later if needed.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tap.tools._paths import PathOutsideProject, resolve_within_project
from tap.tools.base import BaseTool, ToolResult


class WriteArgs(BaseModel):
    path: str = Field(..., description="Path to file to write (relative to project root)")
    content: str = Field(..., description="Full content to write to the file")


class WriteTool(BaseTool):
    name = "write"
    description = (
        "Create a new file or completely overwrite an existing file with new content, "
        "inside the project directory. "
        "Automatically creates parent directories if they don't exist. "
        "Use this when the user asks to create a new file, or to replace all content of a file. "
        "For partial edits to an existing file, use 'edit' instead. "
        "Fails if path resolves outside the project root."
    )
    args_model = WriteArgs

    def __init__(self, project_root: Path):
        self._project_root = project_root

    def _run(self, args: WriteArgs) -> ToolResult:
        try:
            path = resolve_within_project(args.path, self._project_root)
        except PathOutsideProject as e:
            return ToolResult(output=str(e), ok=False)

        if path.is_dir():
            return ToolResult(
                output=f"Path is a directory, cannot write: {args.path}",
                ok=False,
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.content, encoding="utf-8")
        except PermissionError:
            return ToolResult(output=f"Permission denied: {args.path}", ok=False)
        except OSError as e:
            return ToolResult(
                output=f"Failed to write {args.path}: {type(e).__name__}: {e}",
                ok=False,
            )

        n_lines = args.content.count("\n") + 1
        n_chars = len(args.content)
        return ToolResult(
            output=f"Wrote {n_chars} chars ({n_lines} lines) to {args.path}",
        )
