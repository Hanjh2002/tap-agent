"""Edit tool — edits a file by exact string replacement.

v2: adds path safety via resolve_within_project.

Pattern:
- old_text must appear EXACTLY ONCE in the file
- Fails if not found, or if found multiple times
- Forces the LLM to pick an old_text with enough context to be unique
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tap.tools._paths import PathOutsideProject, resolve_within_project
from tap.tools.base import BaseTool, ToolResult


class EditArgs(BaseModel):
    path: str = Field(..., description="Path to file to edit (relative to project root)")
    old_text: str = Field(
        ...,
        description=(
            "Exact text to find and replace. MUST appear exactly once in the file. "
            "Include enough surrounding context (indentation, adjacent lines) "
            "to make it unique."
        ),
    )
    new_text: str = Field(..., description="Text to replace old_text with")


UTF8_BOM = "\ufeff"

def _strip_bom(text: str) -> tuple[str, str]:
    return (UTF8_BOM, text[1:]) if text.startswith(UTF8_BOM) else ("", text)

def _detect_line_ending(text: str) -> str:
    crlf = text.find("\r\n")
    lf = text.find("\n")
    if lf == -1 or crlf == -1:
        return "\n"
    return "\r\n" if crlf < lf else "\n"

def _normalize_to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")

def _restore_line_endings(text: str, ending: str) -> str:
    return text.replace("\n", "\r\n") if ending == "\r\n" else text

class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file inside the project directory by replacing an exact string with new text. "
        "The old_text must appear EXACTLY ONCE in the file — "
        "if it appears multiple times, include more surrounding context "
        "(such as indentation or adjacent lines) to make it unique. "
        "Use this to modify existing files without rewriting the whole thing. "
        "For creating new files or full rewrites, use 'write' instead. "
        "Fails if path resolves outside the project root."
    )
    args_model = EditArgs

    def __init__(self, project_root: Path):
        self._project_root = project_root

    def _run(self, args: EditArgs) -> ToolResult:
        try:
            path = resolve_within_project(args.path, self._project_root)
        except PathOutsideProject as e:
            return ToolResult(output=str(e), ok=False)

        if not path.exists():
            return ToolResult(output=f"File not found: {args.path}", ok=False)
        if path.is_dir():
            return ToolResult(output=f"Path is a directory: {args.path}", ok=False)

        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                raw = f.read()
        except UnicodeDecodeError:
            return ToolResult(output=f"File is not UTF-8 text: {args.path}", ok=False)
        except PermissionError:
            return ToolResult(output=f"Permission denied reading {args.path}", ok=False)

        bom, content = _strip_bom(raw)
        ending = _detect_line_ending(content)
        normalized = _normalize_to_lf(content)
        old = _normalize_to_lf(args.old_text)
        new = _normalize_to_lf(args.new_text)

        count = normalized.count(old)
        if count == 0:
            return ToolResult(
                output=(
                    f"old_text not found in {args.path}. "
                    f"Make sure it matches EXACTLY (including whitespace, "
                    f"indentation, and newlines)."
                ),
                ok=False,
            )
        if count > 1:
            return ToolResult(
                output=(
                    f"old_text appears {count} times in {args.path}. "
                    f"Include more surrounding context to make it unique."
                ),
                ok=False,
            )

        new_content = normalized.replace(old, new)
        final = bom + _restore_line_endings(new_content, ending)

        try:
            with path.open("w", encoding="utf-8", newline="") as f:
                f.write(final)
        except PermissionError:
            return ToolResult(output=f"Permission denied writing {args.path}", ok=False)

        return ToolResult(output=f"Edited {args.path} (1 replacement)")
